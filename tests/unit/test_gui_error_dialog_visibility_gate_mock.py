#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`_notify_error()`'s dialog gate must track LIVE window visibility,
not a one-way latch set once by `withdraw()`.

See docs/handoffs/gui-modal-hang-fix.md. The first version of this fix
used a persisted `self._interactive` flag, set False by an overridden
`withdraw()` and never restored -- so a real user who withdraws the
window and later `deiconify()`s it (minimize/restore is a real,
ordinary Tk usage pattern) would permanently and silently stop seeing
error dialogs, even though a person is watching again. Fixed by
checking `self.winfo_viewable()` at the moment of the call instead of
a latched flag. This test pins BOTH halves: no dialog while withdrawn,
and a dialog again after `deiconify()` -- neither half alone would
have caught the original bug (the latch version passed "no dialog
while withdrawn" too).

No ViennaPS/DevSim needed: the real error path exercised here is
`run_oxidation()`'s own pre-existing numeric-field validation
(`except ValueError`), which fires before any backend call. Tk is
needed; where it is unavailable this reports SKIPPED and exits 0.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _trigger_real_error_path(app):
    """A real, backend-independent error path in run_oxidation(): a
    non-numeric recipe field makes float(...) raise ValueError, which
    run_oxidation() catches and reports via _notify_error("Oxidation
    recipe", "All recipe values must be numeric.")."""
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.ox_temp_var.set("not_a_number")
    app.run_oxidation()


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    shown = []

    def trap(*args, **kwargs):
        shown.append(args[:2])

    gui.messagebox.showerror = trap

    try:
        # --- 1. withdrawn: log-only, no dialog -------------------------
        app.withdraw()
        app.update_idletasks()
        assert app.winfo_viewable() == 0, "withdraw() must make the root non-viewable"
        shown.clear()
        _trigger_real_error_path(app)
        assert not shown, (
            f"a headless (withdrawn) session must never raise a real error "
            f"dialog -- got {shown}")
        log_text = app.log.get("1.0", "end")
        assert "Oxidation recipe: All recipe values must be numeric." in log_text, (
            f"the error must still be logged while withdrawn, got: {log_text!r}")
        print("[1/2] withdrawn: error logged, no modal dialog raised")

        # --- 2. deiconify()'d again: the SAME error path must raise a
        # real dialog once more -- proving the gate is live, not latched.
        app.deiconify()
        app.update_idletasks()
        assert app.winfo_viewable() == 1, (
            "deiconify() must restore viewability -- if this fails, the "
            "test environment itself cannot map a window and the dialog "
            "assertion below is not meaningful")
        shown.clear()
        _trigger_real_error_path(app)
        assert len(shown) == 1 and shown[0][0] == "Oxidation recipe", (
            f"a real user who deiconifies the window must see error dialogs "
            f"again -- the gate must not be a permanent, one-way latch from "
            f"an earlier withdraw() call; got {shown}")
        print("[2/2] deiconify()'d: the SAME error path raises a real dialog again")
    finally:
        app.destroy()

    print()
    print("ERROR DIALOG GATE IS LIVE: silent while withdrawn, restored on")
    print("deiconify() -- not a one-way latch.")


if __name__ == "__main__":
    main()
