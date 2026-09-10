#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless GUI process dispatch must never hang on a modal dialog.

Root cause (docs/handoffs/gui-modal-hang-fix.md, investigations A/B):
run_oxidation()/run_etch()/run_deposition()/etc. used to call
`messagebox.showinfo()` unconditionally after a real ViennaPS success,
and `messagebox.showerror()` on failure -- both are genuine Tk modal
dialogs, and `showinfo`/`showerror` internally block the calling
thread in `wait_window()` until someone dismisses them. A live py-spy
stack trace, captured while a headless reproduction script was
genuinely stuck, showed the Tk main thread parked exactly there:

    Thread ... (idle): "MainThread"
        show (tkinter/commondialog.py:45)
        _show (tkinter/messagebox.py:76)
        showinfo (tkinter/messagebox.py:88)
        run_oxidation (tcad_2d_stagewise.py:2481)

In a headless/automated session (`app.withdraw()` already called, as
every test and CI run in this project does) nobody is present to
click the dialog, so the call hung forever -- explaining both
Investigation A (the hang point looked "random" because it depended
on how far a script's own call sequence got) and Investigation B (the
hang point moved between attempts for the same reason: whichever
`run_X()` was reached last is the one whose own dialog blocked).

This test pins the fix: `_notify_info()`/`_notify_error()` replace
every `messagebox.showinfo()`/`showerror()` call in
`tcad_2d_stagewise.py`, gated on a LIVE `self.winfo_viewable()` check
(False for a withdrawn root) -- success is always log-only; failure is
log-only whenever the session is headless, and only additionally
raises a real dialog while a person is actually watching right now.
Every process step below runs through the REAL GUI dispatch path
(`subprocess.run` -> `tcad_2d_stagewise.py --worker`) with REAL
ViennaPS 4.6.2 -- no mocking, no shortened timeout, no retry.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tkinter  # noqa: F401
import tcad_2d_stagewise as gui
from tcad.backends.viennaps import session as viennaps_session

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"


def _trap_every_messagebox_call():
    """Replaces every messagebox function this module exposes with a
    trap that records the call instead of blocking on it. If the fix
    regresses (a real, unconditional dialog call is reintroduced
    anywhere reachable below), this test sees it as a recorded call
    and fails immediately -- instead of the whole test process hanging
    forever the way the original bug did."""
    calls = []
    for name in ("showinfo", "showwarning", "showerror", "askyesno",
                 "askokcancel", "askquestion", "askretrycancel",
                 "askyesnocancel"):
        if not hasattr(gui.messagebox, name):
            continue

        def trap(*args, _name=name, **kwargs):
            calls.append((_name, args[:2]))
            return None

        setattr(gui.messagebox, name, trap)
    return calls


def main():
    app = gui.TCADApplication()
    calls = _trap_every_messagebox_call()
    try:
        app.withdraw()
        app.update_idletasks()
        assert app.winfo_viewable() == 0, (
            "withdraw() must make the root non-viewable -- everything "
            "below depends on this to stay log-only"
        )

        app.grid_var.set(0.1)

        # --- (2)+(3): real oxidation -> etch -> deposition, chained,
        # all headless, each through the REAL GUI dispatch path.
        print("[1/4] real headless oxidation...", flush=True)
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.1)
        app.run_oxidation()
        assert app.wafer.processed and app.last_final_mesh, (
            "real oxidation must produce a real final mesh"
        )
        print("    OK: real oxidation completed, no modal wait", flush=True)

        print("[2/4] real headless etch, chained onto the oxidized wafer...", flush=True)
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        # Bosch DRIE is the panel's own default, and safe at its own
        # default cycles (see docs/investigation_log.md, Investigation
        # C / the Bosch cycle-safety fix) -- deliberately left
        # unchanged here rather than picking a different model, so
        # this test exercises the GUI's real out-of-the-box defaults.
        app.run_etch()
        assert app.wafer.processed and app.last_final_mesh, (
            "real etch must produce a real final mesh"
        )
        print("    OK: real etch completed, no modal wait", flush=True)

        print("[3/4] real headless deposition, chained onto the etched wafer...", flush=True)
        app.panel_category.set(app._PANEL_LABELS["deposition"])
        app._show_panel_category()
        # Isotropic Deposition is the panel's own default (see
        # CLAUDE.md's GUI section, "live-verified via the same
        # Xvfb+xdotool setup").
        app.run_deposition()
        assert app.wafer.processed and app.last_final_mesh, (
            "real deposition must produce a real final mesh"
        )
        print("    OK: real deposition completed, no modal wait", flush=True)

        assert not calls, (
            f"a messagebox call fired during real success paths: {calls}"
        )

        # --- (4): a real WORKER FAILURE path must also stay log-only,
        # headless. grid_delta_um=-1.0 is confirmed (by direct
        # execution, not assumed) to make ViennaPS itself raise
        # RuntimeError('Domain setup is not correctly initialized.')
        # inside the worker subprocess -- a real backend failure, not
        # a GUI-side validation short-circuit. Needs a FRESH wafer:
        # once a domain already exists (as it does after steps 1-3
        # above), run_oxidation() resumes the saved .vpsd instead of
        # re-materializing from grid_delta_um, so the invalid value
        # would silently have no effect -- confirmed by direct
        # execution, not assumed.
        print("[4/4] real headless worker FAILURE path...", flush=True)
        app.reset()
        app.grid_var.set(-1.0)
        before_log = app.log.get("1.0", "end")
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.1)
        app.run_oxidation()
        after_log = app.log.get("1.0", "end")
        delta = after_log[len(before_log):]
        assert "ERROR" in delta and "ViennaPS" in delta, (
            f"a failed worker run must log a real ERROR entry, got: {delta!r}"
        )
        assert not calls, (
            f"a messagebox call fired during the failure path: {calls}"
        )
        print("    OK: worker failure logged, no modal wait, no dialog raised", flush=True)

    finally:
        app.destroy()

    print()
    print("HEADLESS NO MODAL HANG: real oxidation -> etch -> deposition, and a real")
    print("worker failure, all completed with no dialog wait -- every messagebox call")
    print("this session could have made was trapped, and none fired.")


if __name__ == "__main__":
    main()
