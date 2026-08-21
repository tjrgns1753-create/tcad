#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real ViennaPS + DevSim verification of
tcad/characterization/robust_iv_sweep.py.

Two things must both hold for this path to be worth having, and this
test pins both:

  1. IT MUST NOT CHANGE ANSWERS. On the project's own known-passing
     4x3um implant_windows recipe (the same one
     test_gui_measurement_doping_kinds_real.py uses), the robust path
     must reproduce the current `run_pn_junction_iv_sweep` already
     produces there. Measured: +3.475281e-11 A vs +3.475285e-11 A --
     six significant figures. Asserted here as a relative tolerance
     against a freshly-run reference, not a hardcoded number, so the
     two paths are compared on identical geometry every run.

  2. IT MUST CONVERGE WHERE THE SIMPLE PATH DOES NOT. On the GUI's own
     default 10x8um wafer, the simple path fails outright in the
     EQUILIBRIUM solve; the robust path's doping continuation reaches
     full doping and completes a real biased solve. Exercised here at
     1e19 cm^-3 windows, which is the highest level this geometry is
     measured to complete at (1e20 on this geometry still fails in the
     bias ramp -- see CLAUDE.md's implant_windows OPEN item; this test
     deliberately pins what actually works rather than the open case).

Every solve is on a real ViennaPS-etched mesh, and every device is
deleted (device AND mesh) before the next one is built -- a leaked
DevSim device makes the NEXT, unrelated solve fail, a trap this project
has already been caught by once (see CLAUDE.md).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_import import (
    import_process_result,
    refine_process_result_for_implant_windows,
)
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from tcad.characterization.robust_iv_sweep import run_robust_pn_junction_iv_sweep

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

LENGTH_SCALE_TO_CM = 1.0e-4
VOLTAGE = 0.3
REGION = "Si"
BACKGROUND_CM3 = -1.0e17

RECIPE_4x3 = {
    "grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5,
    "pr_thickness_um": 0.5, "etch_time_s": 0.5, "rate": -0.05,
    "mask_material": "Mask",
}
# The GUI's own default wafer -- the configuration whose EQUILIBRIUM
# solve the simple path cannot get through at all.
RECIPE_10x8 = {
    "grid_delta_um": 0.2, "x_extent_um": 10.0, "y_extent_um": 8.0,
    "silicon_depth_um": 5.0, "mask_left_um": 3.5, "mask_right_um": 6.5,
    "pr_thickness_um": 1.0, "etch_time_s": 0.5, "rate": -0.05,
    "mask_material": "Mask",
}


def build_device(recipe, conc_cm3, device_name, mesh_name, tmp):
    """Real etch -> implant_windows doping -> production refinement ->
    DevSim import. Returns (imported, doped_result)."""
    step_result = registry.get("etching", "isotropic")().run(recipe, tmp)
    process_result = build_process_result(step_result)
    doped = apply_implant_windows_doping(
        process_result, region=REGION, axis="x",
        background_doping_cm3=BACKGROUND_CM3,
        windows=[
            {"min_um": -1.6, "max_um": -0.6, "conc_cm3": conc_cm3},
            {"min_um": 0.6, "max_um": 1.6, "conc_cm3": conc_cm3},
        ],
    )
    refined = refine_process_result_for_implant_windows(doped)
    assert refined is not None, "no refinement derived for implant_windows"
    imported = import_process_result(
        refined, mesh_name=mesh_name, device_name=device_name,
        contact_regions=[REGION], contact_axis="x",
        length_scale_to_cm=LENGTH_SCALE_TO_CM,
    )
    assert len(imported.contacts) == 2, imported.contacts
    return imported, refined


def cleanup(imported):
    """BOTH calls: a leaked device breaks the NEXT solve."""
    devsim.delete_device(device=imported.device)
    devsim.delete_mesh(mesh=imported.mesh)


def main():
    # ---- Check 1: robust path reproduces the simple path's answer ----
    with tempfile.TemporaryDirectory() as tmp:
        imported, doped = build_device(
            RECIPE_4x3, 1.0e20, "simple_dev", "simple_mesh", tmp)
        try:
            apply_doping(imported.device, doped.doping,
                         length_scale_to_cm=LENGTH_SCALE_TO_CM)
            gnd, src = imported.contacts[0], imported.contacts[1]
            simple = run_pn_junction_iv_sweep(
                device=imported.device, region=REGION,
                all_contacts=imported.contacts, sweep_contact=src,
                sweep_voltages=[VOLTAGE], fixed_contacts={gnd: 0.0},
            )
            i_simple = simple.points[-1].currents[src]
        finally:
            cleanup(imported)
    assert not devsim.get_device_list(), "device leaked after simple sweep"
    print(f"[1/3] simple path (reference): I = {i_simple:+.6e} A")

    with tempfile.TemporaryDirectory() as tmp:
        imported, doped = build_device(
            RECIPE_4x3, 1.0e20, "robust_dev", "robust_mesh", tmp)
        try:
            gnd, src = imported.contacts[0], imported.contacts[1]
            robust = run_robust_pn_junction_iv_sweep(
                device=imported.device, region=REGION,
                all_contacts=imported.contacts, sweep_contact=src,
                sweep_voltages=[VOLTAGE], doping=doped.doping,
                length_scale_to_cm=LENGTH_SCALE_TO_CM,
                fixed_contacts={gnd: 0.0},
            )
            point = robust.points[-1]
            i_robust, i_gnd = point.currents[src], point.currents[gnd]
        finally:
            cleanup(imported)
    assert not devsim.get_device_list(), "device leaked after robust sweep"

    rel = abs(i_robust - i_simple) / abs(i_simple)
    assert rel < 0.05, (
        f"robust path changed the answer on a known-passing case: "
        f"{i_robust:+.6e} A vs {i_simple:+.6e} A (relative {rel:.3e})"
    )
    assert abs(i_robust + i_gnd) < 1.0e-4 * abs(i_robust), (
        f"terminal currents not equal and opposite: {i_robust:+.6e} / {i_gnd:+.6e}"
    )
    print(f"[2/3] robust path: I = {i_robust:+.6e} A "
          f"(matches reference to {rel:.2e} relative); KCL satisfied")

    # ---- Check 2: robust path converges where the simple one cannot ----
    # The simple path fails this configuration in the EQUILIBRIUM solve.
    with tempfile.TemporaryDirectory() as tmp:
        imported, doped = build_device(
            RECIPE_10x8, 1.0e19, "gui_dev", "gui_mesh", tmp)
        try:
            gnd, src = imported.contacts[0], imported.contacts[1]
            result = run_robust_pn_junction_iv_sweep(
                device=imported.device, region=REGION,
                all_contacts=imported.contacts, sweep_contact=src,
                sweep_voltages=[VOLTAGE], doping=doped.doping,
                length_scale_to_cm=LENGTH_SCALE_TO_CM,
                fixed_contacts={gnd: 0.0},
            )
            point = result.points[-1]
            i_src, i_gnd = point.currents[src], point.currents[gnd]
        finally:
            cleanup(imported)
    assert not devsim.get_device_list(), "device leaked after GUI-default sweep"

    assert abs(i_src + i_gnd) < 1.0e-3 * abs(i_src), (
        f"terminal currents not equal and opposite on the GUI-default wafer: "
        f"{i_src:+.6e} / {i_gnd:+.6e}"
    )
    print(f"[3/3] GUI-default 10x8um wafer at 1e19 cm^-3 (simple path fails "
          f"this in equilibrium): I = {i_src:+.6e} A; KCL satisfied")

    print()
    print("ROBUST IV SWEEP VERIFIED: same answer where the simple path works, "
          "and converges where it does not")


if __name__ == "__main__":
    main()
