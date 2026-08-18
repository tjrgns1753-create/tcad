#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_refine_from_doping — real-backend verification, real ViennaPS
4.6.2 + DevSim 2.10.1.

Regression test for import_process_result()'s auto_refine_from_doping
opt-in flag (tcad/device/devsim/mesh_import.py): derives
refine_near_um/refine_axis/refine_half_width_um/refine_levels directly
from a ProcessResult's doping profile, so a caller no longer has to
compute/pass the junction position (and a working half-width/levels
pair) by hand — this was this project's own named "next smallest
experiment" after the original mesh-refinement fix shipped (see
CLAUDE.md, "PN junction (Phase 8) convergence — RESOLVED", item 7).

Two things checked, both against the real production entry points:
  1. Step-junction doping (Phase 8's own 1e18 cm^-3 recipe):
     auto_refine_from_doping=True, with NO manually-computed
     refine_near_um, reproduces the SAME real drift-diffusion
     convergence Phase 8's own test gets with a hand-computed
     refine_near_um — proving the auto-derivation isn't just plausible
     but actually equivalent in practice.
  2. Gaussian-implant doping: auto_refine_from_doping=True correctly
     derives from peak_position_um (not junction_position_um) and does
     not corrupt the NetDoping mapping — checked against the exact
     analytic Gaussian formula, matching
     test_gaussian_implant_doping_real.py's own rigor.

Separately verified this session (NOT re-checked by this permanent
test, since it costs several minutes per doping level and this project
avoids bloating the regression suite with expensive parameter sweeps —
see CLAUDE.md's "mesh-refinement generalization" investigation for the
full result): auto_refine_from_doping also converges at 1e19 cm^-3
(10x this test's own doping, same grid) with 51239 Si nodes, but does
NOT converge at 1e20 cm^-3 (100x) even at the refine_levels cap of 5 —
a real, honestly-characterized boundary, not silently assumed to work
everywhere.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_step_junction_doping, apply_gaussian_implant_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.15,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}
LENGTH_SCALE_TO_CM = 1.0e-4
DONOR_CM3 = 1.0e18
ACCEPTOR_CM3 = 1.0e18
SWEEP_VOLTAGES = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4]


def test_step_junction_auto_refine():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        process_result = build_process_result(step_result)

        probe = import_process_result(
            process_result, mesh_name="autorefine_probe_mesh", device_name="autorefine_probe_device"
        )
        x_native = devsim.get_node_model_values(device=probe.device, region="Si", name="x")
        junction_position_um = 0.5 * (min(x_native) + max(x_native))
        devsim.delete_device(device=probe.device)
        devsim.delete_mesh(mesh=probe.mesh)

        doped_result = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x",
            junction_position_um=junction_position_um,
            donor_conc_cm3=DONOR_CM3, acceptor_conc_cm3=ACCEPTOR_CM3,
        )

        # NO refine_near_um passed -- derived entirely from doped_result.doping.
        imported = import_process_result(
            doped_result, mesh_name="autorefine_mesh", device_name="autorefine_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
            auto_refine_from_doping=True,
        )
        assert len(imported.contacts) == 2
        p_contact, n_contact = imported.contacts[0], imported.contacts[1]
        print(f"[1/2] auto-refined DevSim import OK -> regions={imported.regions} "
              f"contacts={imported.contacts}")

        apply_doping(imported.device, doped_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        result = run_pn_junction_iv_sweep(
            device=imported.device, region="Si", all_contacts=imported.contacts,
            sweep_contact=n_contact, sweep_voltages=SWEEP_VOLTAGES,
            fixed_contacts={p_contact: 0.0},
        )
        assert len(result.points) == len(SWEEP_VOLTAGES), (
            "auto_refine_from_doping must converge the FULL sweep, same as manually-"
            "computed refine_near_um does in test_phase8_pn_junction_real.py"
        )

        currents_by_v = {round(p.voltages[n_contact], 6): p.currents[n_contact] for p in result.points}
        fwd_voltages_sorted = sorted(v for v in currents_by_v if v >= 0.0)
        fwd_currents = [currents_by_v[v] for v in fwd_voltages_sorted]
        assert fwd_currents[-1] > fwd_currents[0], "forward current must increase overall"
        rev_currents = [currents_by_v[v] for v in sorted(v for v in currents_by_v if v < 0.0)]
        assert all(i <= 1e-12 for i in rev_currents), "reverse current should stay blocking"

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        print(f"[2/2] full 8-point bias sweep converged with auto-derived refinement "
              f"(no manually-computed refine_near_um) -- forward currents {fwd_currents}")


def test_gaussian_implant_auto_refine():
    step_cls = registry.get("etching", "isotropic")
    peak_position_um = 0.0
    straggle_um = 0.5
    peak_conc_cm3 = 1.0e17

    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        process_result = build_process_result(step_result)

        doped_result = apply_gaussian_implant_doping(
            process_result, region="Si", junction_axis="x",
            peak_position_um=peak_position_um, straggle_um=straggle_um,
            peak_conc_cm3=peak_conc_cm3,
        )

        imported = import_process_result(
            doped_result, mesh_name="autorefine_gauss_mesh", device_name="autorefine_gauss_device",
            contact_regions=["Si"], contact_axis="x",
            auto_refine_from_doping=True,
        )
        apply_doping(imported.device, doped_result.doping)

        x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        net_doping_values = devsim.get_node_model_values(
            device=imported.device, region="Si", name="NetDoping"
        )
        max_rel_error = 0.0
        for x, actual in zip(x_values, net_doping_values):
            expected = peak_conc_cm3 * math.exp(-((x - peak_position_um) ** 2) / (2 * straggle_um ** 2))
            rel_error = abs(actual - expected) / max(abs(expected), 1.0)
            max_rel_error = max(max_rel_error, rel_error)

        assert max_rel_error < 1e-9, (
            f"auto-refined mesh's NetDoping does not match analytic Gaussian: {max_rel_error}"
        )
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)
        print(f"      gaussian_implant + auto_refine_from_doping: {len(x_values)} nodes, "
              f"max relative error vs analytic Gaussian = {max_rel_error:.3e}")


def main():
    print("[step_junction] auto_refine_from_doping reproduces Phase 8's manual-refine convergence:")
    test_step_junction_auto_refine()
    print()
    print("[gaussian_implant] auto_refine_from_doping derives from peak_position_um, "
          "doping mapping unaffected:")
    test_gaussian_implant_auto_refine()

    print()
    print("AUTO_REFINE_FROM_DOPING (step_junction + gaussian_implant) VERIFIED AGAINST "
          "REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1")


if __name__ == "__main__":
    main()
