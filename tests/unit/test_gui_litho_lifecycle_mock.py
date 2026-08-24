#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI lithography-lifecycle smoke test — real TCADApplication, no backend.

Builds the actual GUI object (window hidden with withdraw(), so nothing
appears on screen), clicks through the lithography sequence by calling
the same handlers the buttons call, and checks the recipe keys the NEXT
process step would receive at each point.

Why this exists as a test rather than a one-off check: the resist state
and the recipe are connected through GUI-only code
(`_resist_spans_um` / `_mask_recipe_keys_for_current_step`) that no
library-level test can reach. The library-level counterpart, which runs
the resulting recipes through real ViennaPS and measures the geometry,
is tests/integration/test_litho_lifecycle_state_real.py.

No ViennaPS and no DevSim are needed — nothing here runs a process — so
this belongs in tests/unit. It does need Tk; where Tk or a display is
unavailable it reports SKIPPED and exits 0 rather than failing, matching
how tests/run_regression.py treats a missing backend.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

FULL_WAFER_SPAN = [[-5.0, 5.0]]                    # blanket resist, 10um wafer
PATTERNED_SPANS = [[-5.0, -1.5], [1.5, 5.0]]       # opaque complement of 3.5-6.5


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display for the GUI smoke test ({exc!r})")
        return

    try:
        app.withdraw()
        app.update_idletasks()

        def next_step_keys(first_step=True):
            """What the next process step's recipe would carry right now."""
            app.completed_steps = (
                [] if first_step else [{"_process_category": "oxidation"}]
            )
            return app._mask_recipe_keys_for_current_step()

        # --- fresh wafer: a process step must not invent lithography ---
        assert next_step_keys() == {"mask_spans_um": []}, (
            "a fresh wafer must ask for a BARE wafer; building a mask from the "
            "Wafer defaults is what made a plain deposition produce a Mask "
            "material and a patterned film")
        assert next_step_keys(first_step=False) == {}, (
            "a chained step with no lithography must leave the domain untouched")
        assert app._stages_done == {0}, (
            f"only 'Si wafer' should be marked on a fresh wafer: {app._stages_done}")

        # --- PR COAT: blanket resist, and only its own marker ----------
        app.process_pr_coat()
        assert app.wafer.pr_present and not app.wafer.developed
        assert next_step_keys()["mask_spans_um"] == FULL_WAFER_SPAN, (
            "PR COAT must produce a BLANKET film; producing the opaque "
            "complement means coat behaved as coat+align+expose+develop")
        assert app._stages_done == {0, 2}, (
            f"PR COAT marked stages it did not run: {app._stages_done}")

        # --- alignment and exposure change no geometry -----------------
        app.process_mask_alignment()
        after_align = next_step_keys()
        app.process_exposure()
        assert next_step_keys() == after_align, (
            "mask alignment / exposure must not change resist geometry -- the "
            "mask is process input and exposure is chemistry")
        assert app._stages_done == {0, 2, 3, 4}, (
            f"align/expose marked stages they did not run: {app._stages_done}")

        # --- DEVELOP: the first step that opens the resist -------------
        app.process_develop()
        assert next_step_keys()["mask_spans_um"] == PATTERNED_SPANS
        assert next_step_keys(first_step=False) == {
            "remask_spans_um": PATTERNED_SPANS
        }, "a developed resist on an existing wafer must remask, not rebuild"

        # --- PR STRIP: no further step is masked -----------------------
        app.process_pr_strip()
        assert not app.wafer.pr_present and not app.wafer.developed
        assert next_step_keys() == {"mask_spans_um": []}
        assert next_step_keys(first_step=False) == {}

        # --- a second cycle must start unpatterned ---------------------
        app.process_pr_coat()
        assert app.wafer.developed is False, (
            "a new coat must not inherit 'developed' from the previous cycle")
        assert next_step_keys()["mask_spans_um"] == FULL_WAFER_SPAN, (
            "the second coat must be blanket again, not the previous pattern")

        # --- NEW WAFER clears everything -------------------------------
        app.reset()
        assert not app.wafer.pr_present and not app.wafer.developed
        assert app._stages_done == {0}, (
            f"NEW WAFER left stage markers behind: {app._stages_done}")
        assert next_step_keys() == {"mask_spans_um": []}
    finally:
        app.destroy()

    print("GUI LITHOGRAPHY LIFECYCLE OK")
    print("  fresh wafer      -> no mask")
    print("  PR coat          -> blanket resist")
    print("  align / expose   -> no geometry change")
    print("  develop          -> patterned resist")
    print("  strip            -> no mask")
    print("  re-coat          -> blanket again (no stale 'developed')")
    print("  stage markers    -> only steps actually run")


if __name__ == "__main__":
    main()
