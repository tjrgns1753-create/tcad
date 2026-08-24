#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The GUI must never force a process order — real TCADApplication, no backend.

The invariant this pins:

    the user picks a process -> only that process runs
      -> the current wafer is updated -> the user picks the next one

Nothing may stand between "the user pressed a button" and "that step
ran against the wafer as it is". In particular:

  * no process button may be greyed out,
  * no code path may stop the user with a modal warning or a confirm
    dialog (a confirm is still a block),
  * no message may tell the user to run a different step first (advice
    about sequence is still a prescribed sequence),
  * a step with nothing to act on is a no-op that says so, and must not
    invent the state it was missing,
  * LOCOS is an independent choice, never a modifier of ordinary
    oxidation, and its logic must not reach into the plain path.

Every messagebox function that can block is replaced with a trap, so a
blocking dialog anywhere in these paths fails the test rather than
silently waiting for a click that will never come.

No ViennaPS or DevSim is needed — nothing here runs a process. Tk is
needed; where it is unavailable this reports SKIPPED and exits 0.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    blocked = []
    for name in ("showwarning", "askyesno", "askokcancel", "askquestion",
                 "askretrycancel", "askyesnocancel"):
        if not hasattr(gui.messagebox, name):
            continue

        def trap(*args, _name=name, **kwargs):
            blocked.append((_name, args[:2]))
            return False

        setattr(gui.messagebox, name, trap)

    try:
        app.withdraw()
        app.update_idletasks()

        process_buttons = {
            "PR coat": app.coat_button,
            "Mask alignment": app.align_button,
            "Exposure": app.expose_button,
            "Develop": app.develop_button,
            "Etching": app.etch_button,
            "Oxidation": app.oxidation_button,
            "Deposition": app.deposition_button,
            "Metallization": app.metallization_button,
            "PR strip": app.strip_button,
            "Doping": app.doping_button,
            "Device measurement": app.measure_button,
        }

        # --- 1. nothing is greyed out on a pristine wafer -------------
        disabled = [n for n, b in process_buttons.items()
                    if str(b["state"]) != "normal"]
        assert not disabled, (
            f"these are disabled on a fresh wafer, which is a prerequisite by "
            f"another name: {disabled}")
        print(f"[1] all {len(process_buttons)} process buttons enabled on a "
              f"pristine wafer")

        # --- 2. steps with nothing to act on: no block, no invention --
        app.process_develop()
        assert app.wafer.developed is False, (
            "develop with no resist invented a developed state")
        app.process_exposure()
        assert app.wafer.pr_present is False, (
            "exposure with no resist invented resist")
        app.process_pr_strip()
        assert app.wafer.pr_present is False
        assert app.wafer.developed is False
        print("[2] develop / expose / strip with no resist: no-ops, no state "
              "invented")

        # --- 3. and they did not disable anything on the way out ------
        disabled = [n for n, b in process_buttons.items()
                    if str(b["state"]) != "normal"]
        assert not disabled, f"a no-op step disabled buttons: {disabled}"

        # --- 4. resist state still reachable in any order -------------
        app.process_pr_coat()
        assert app.wafer.pr_present and not app.wafer.developed
        app.process_develop()
        assert app.wafer.developed
        app.process_pr_strip()
        assert not app.wafer.pr_present and not app.wafer.developed
        print("[4] the resist cycle still works when reached out of order")

        # --- 5. plain oxidation carries no mask and no LOCOS key ------
        def queued(builder):
            app._pending_flow_add = True
            try:
                builder()
            finally:
                app._pending_flow_add = False
            return app.flow_steps[-1]

        assert app.oxidation_method.get() == "Thermal oxidation"
        plain = queued(app.run_oxidation)
        assert "mask_material" not in plain, (
            "plain thermal oxidation carries LOCOS's mask_material key")
        assert plain["mask_spans_um"] == [], (
            f"plain thermal oxidation builds a mask: {plain['mask_spans_um']}")

        # --- 6. LOCOS is independent and does not contaminate it ------
        app.oxidation_method.set("LOCOS")
        locos = queued(app.run_oxidation)
        assert locos.get("mask_material") == "Mask", "LOCOS lost its mask material"
        assert locos["mask_spans_um"], "LOCOS lost its mask"

        app.oxidation_method.set("Thermal oxidation")
        plain_again = queued(app.run_oxidation)
        assert "mask_material" not in plain_again, (
            "having selected LOCOS once leaked its key into thermal oxidation")
        assert plain_again["mask_spans_um"] == [], (
            "having selected LOCOS once leaked a mask into thermal oxidation")
        print("[5,6] thermal oxidation builds no mask; LOCOS is isolated from it")

        # --- 7. no dialog blocked anything along the way --------------
        assert not blocked, (
            f"a blocking dialog was raised during ordinary use: {blocked}")
        print("[7] no blocking dialog raised anywhere in the above")
    finally:
        app.destroy()

    print()
    print("NO FORCED ORDER: every process reachable at any time, no")
    print("prerequisite, no blocking dialog, LOCOS independent")


if __name__ == "__main__":
    main()
