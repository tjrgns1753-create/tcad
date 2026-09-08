#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test for `TCADApplication._doping_unsupported_hover_note()`
(the STEP-5 UX addition from the Bosch/PR-strip/doping-oxidation
investigation session): a real, computed explanation must appear on
canvas hover when the doping overlay is showing an UNSUPPORTED_BY_MODEL
bucket, so a user does not misread the gray hatch as "doping is gone"
-- see docs/investigation_log.md, "Doping -> Oxidation -> MEASURE".

No mock physics: builds a real WaferState by hand (the same pattern
tests/unit/test_wafer_state_doping_mock.py already uses for the
identical oxidation/conversion scenario) and exercises the real
WaferState.net_doping_at()/_polarity_sum() logic this project already
verified against real ViennaPS+DevSim -- only the GUI's own
string-formatting method is what's under test here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tkinter  # noqa: F401 -- import guard: skip cleanly if Tk is unavailable
import tcad_2d_stagewise as gui
from tcad.physics.wafer_state import WaferState, LayerInfo, _Cell
from tcad.physics.dopant_profile import DopantProfile


def main():
    app = gui.TCADApplication()
    app.withdraw()
    app.update_idletasks()

    profile = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 1e17,
        host_material="Si", model="uniform_v1", model_params={},
    )

    # Si genuinely still exists in the mesh (a real DevSim node would
    # find it), but the SURFACE at this x is SiO2 -- exactly what a
    # real Doping -> Oxidation sequence produces (Thermal Oxidation has
    # no mask concept at all, so exposed_materials() reports {'SiO2'}
    # across the entire wafer regardless of where doping was applied).
    app.wafer_state = WaferState(
        materials=("Si", "SiO2"), stack=(LayerInfo("Si", 0), LayerInfo("SiO2", 1)),
        grid_delta_um=0.05, _cells=(_Cell(-5.0, 5.0, 0.06, "SiO2"),),
        _thin_x=(), dopant_profiles=(profile,),
        last_step_category="oxidation",
    )

    app.viewer_layer_var.set("doping")
    note = app._doping_unsupported_hover_note(0.0)
    assert note, "expected a real UNSUPPORTED note after Doping->Oxidation while hovering the doping layer"
    assert "UNSUPPORTED" in note
    assert "excluded" in note or "NOT zero" in note, (
        f"note must make clear this is 'excluded', not a real zero: {note!r}")
    print("PASS: real UNSUPPORTED explanation present and correctly worded")

    app.viewer_layer_var.set("geometry")
    note2 = app._doping_unsupported_hover_note(0.0)
    assert note2 == "", "must stay silent outside the doping overlay view"
    print("PASS: silent outside the doping overlay view")

    # Control: a location where Si genuinely IS still exposed (no oxide
    # grown there) must NOT show the note -- real doping, not unsupported.
    app.viewer_layer_var.set("doping")
    app.wafer_state = WaferState(
        materials=("Si",), stack=(LayerInfo("Si", 0),),
        grid_delta_um=0.05, _cells=(_Cell(-5.0, 5.0, 0.0, "Si"),),
        _thin_x=(), dopant_profiles=(profile,), last_step_category="doping",
    )
    note3 = app._doping_unsupported_hover_note(0.0)
    assert note3 == "", "a genuinely computable doping value must not show the UNSUPPORTED note"
    print("PASS: silent when the doping value is genuinely computable (not unsupported)")

    app.destroy()
    print("DONE")


if __name__ == "__main__":
    main()
