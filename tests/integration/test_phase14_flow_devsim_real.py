#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 14: Process Flow -> DevSim end-to-end connection, against real
ViennaPS 4.6.2 + real DevSim 2.10.1 — no mocks, no independently-built
Phase 7-9-style structures. Every DevSim import below consumes the
actual ProcessResult that tcad.process.flow.run_flow() produced.

This phase is a CONNECTION test, not a physics benchmark: the values
reported are real solver output on flow-produced geometry, but no
claim is made here that they are physically realistic for any specific
real device (see the report for Phase 15 benchmark planning).
"""

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import tcad.process.etching  # noqa: F401
import tcad.process.oxidation  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

from tcad.process.flow import FlowStep, run_flow
from tcad.physics.doping import apply_uniform_doping
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
from tcad.device.devsim.mos_equation import setup_mos_potential_equation
from tcad.device.devsim.resistor_equation import set_bias
from tcad.characterization.cv_sweep import run_mos_cv_sweep

OXIDATION_RECIPE = {
    "grid_delta_um": 0.05, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.0, "mask_right_um": 3.0, "pr_thickness_um": 0.5,
    "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.05,
}
LENGTH_SCALE_TO_CM = 1.0e-4


def _devsim_region_extent(device, region, axis):
    """Real coordinate extent of `region` as DevSim itself sees it,
    for direct, quantitative comparison against ProcessResult.structure
    (which comes from the ViennaPS side)."""
    vals = devsim.get_node_model_values(device=device, region=region, name=axis)
    return min(vals), max(vals), len(vals)


def test_1_flow_oxidation_to_devsim_import():
    print("=" * 70)
    print("Test 1: Si -> oxidation -> flow ProcessResult -> DevSim mesh import")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", OXIDATION_RECIPE)],
            str(Path(tmp) / "flow"),
        )
        final = results[-1]  # the flow's ProcessResult -- used as-is, not rebuilt

        print(f"[Flow]  materials={final.structure['materials']} "
              f"level_sets={final.structure['num_level_sets']} "
              f"bbox={final.structure['bounding_box']} "
              f"grid_delta={final.structure['grid_delta']}")

        imported = import_process_result(
            final, mesh_name="p14t1_mesh", device_name="p14t1_device",
            contact_regions=["Si"], contact_axis="x",
        )
        print(f"[DevSim import] regions={imported.regions} contacts={imported.contacts}")

        # Quantitative geometry check: DevSim's own Si-region x-extent
        # must match the flow's ViennaPS-side bounding box (both are in
        # "um" here since length_scale_to_cm defaults to 1.0).
        xmin, xmax, n_si_nodes = _devsim_region_extent(imported.device, "Si", "x")
        flow_xmin, flow_xmax = final.structure["bounding_box"][0][0], final.structure["bounding_box"][1][0]
        print(f"[Geometry check] DevSim Si x-range=({xmin:.6f}, {xmax:.6f}), "
              f"{n_si_nodes} nodes | Flow (ViennaPS) x bbox=({flow_xmin:.6f}, {flow_xmax:.6f})")

        assert abs(xmin - flow_xmin) < 1e-6, f"x-min mismatch: DevSim={xmin} vs flow={flow_xmin}"
        assert abs(xmax - flow_xmax) < 1e-6, f"x-max mismatch: DevSim={xmax} vs flow={flow_xmax}"
        assert "SiO2" in final.structure["materials"], "flow step must have produced oxide"
        assert set(imported.regions) == set(final.structure["materials"])

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print("RESULT: DevSim-imported Si x-extent matches the flow's own ViennaPS-side "
          "bounding box to 1e-6 um. Region set matches exactly. PROVEN: DevSim consumed "
          "the flow's actual geometry, not a rebuilt one.\n")


def test_2_flow_oxidation_doping_semiconductor_solve():
    print("=" * 70)
    print("Test 2: Si -> oxidation -> doping -> DevSim semiconductor equilibrium solve")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", OXIDATION_RECIPE)],
            str(Path(tmp) / "flow"),
        )
        final = results[-1]

        doped = apply_uniform_doping(final, {"Si": 1.0e17})
        print(f"[Doping] kind={doped.doping.kind} "
              f"regions={[(d.region, d.net_doping_cm3) for d in doped.doping.regions]}")
        assert final.doping is None, "doping must not mutate the flow's ProcessResult"

        imported = import_process_result(
            doped, mesh_name="p14t2_mesh", device_name="p14t2_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        print(f"[DevSim import] regions={imported.regions} contacts={imported.contacts}")

        apply_doping(imported.device, doped.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        setup_semiconductor_potential_equation(imported.device, "Si", imported.contacts, temperature_k=300.0)
        for c in imported.contacts:
            set_bias(imported.device, c, 0.0)
        devsim.solve(type="dc", solver_type="direct", absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)

        pot = devsim.get_node_model_values(device=imported.device, region="Si", name="Potential")
        spread = max(pot) - min(pot)
        n_i = devsim.get_parameter(device=imported.device, region="Si", name="n_i")
        v_t = devsim.get_parameter(device=imported.device, region="Si", name="V_t")
        v_bi_analytic = v_t * math.log(1.0e17 / n_i)

        print(f"[Solve] Si region node count={len(pot)}, "
              f"potential min={min(pot):.9f} V, max={max(pot):.9f} V, spread={spread:.9f} V")
        print(f"[Check] analytic V_t*ln(Nd/n_i) = {v_bi_analytic:.9f} V")

        # Uniform doping -> uniform potential (spread ~0); the potential
        # LEVEL itself (not the spread) is what must match the analytic
        # built-in potential -- same check as Phase 7.
        assert spread < 1e-9, f"uniform doping should give uniform potential, spread={spread}"
        assert abs(max(pot) - v_bi_analytic) < 1e-6, (
            f"equilibrium potential level does not match analytic built-in potential: "
            f"{max(pot)} vs {v_bi_analytic}"
        )

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print(f"RESULT: equilibrium potential on the FLOW's oxidized+doped Si region "
          f"is uniform at {max(pot):.6f} V (spread={spread:.2e} V), matching the "
          f"analytic built-in potential to 1e-6 V. Same physics check as Phase 7, "
          f"now run on flow-produced (not independently-built) geometry.\n")
    return max(pot), v_bi_analytic


def test_3_flow_oxidation_mos_cv():
    print("=" * 70)
    print("Test 3: Si -> oxidation -> flow MOS structure -> DevSim MOS C-V")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", OXIDATION_RECIPE)],
            str(Path(tmp) / "flow"),
        )
        final = results[-1]

        doped = apply_uniform_doping(final, {"Si": -1.0e15})

        imported = import_process_result(
            doped, mesh_name="p14t3_mesh", device_name="p14t3_device",
            contact_regions=["Si", "SiO2"], contact_axis="y",
            contact_sides={"Si": "min", "SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        print(f"[DevSim import] regions={imported.regions} contacts={imported.contacts} "
              f"interfaces={imported.interfaces}")
        assert imported.interfaces, "MOS structure needs a real Si-SiO2 interface"

        apply_doping(imported.device, doped.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        substrate_contact = next(c for c in imported.contacts if c.startswith("Si_"))
        gate_contact = next(c for c in imported.contacts if c.startswith("SiO2_"))
        gate_voltages = [-1.0, -0.5, 0.0, 0.5, 1.0]

        result = run_mos_cv_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            gate_contact=gate_contact, substrate_contact=substrate_contact,
            interface_name=imported.interfaces[0], gate_voltages=gate_voltages,
        )

        gate_charges = result.metadata["gate_charges_C"]
        capacitance = result.metadata["capacitance_F"]
        print("[Sweep] gate charge vs voltage:")
        for v, q in zip(gate_voltages, gate_charges):
            print(f"    Vg={v:+.2f}  Q_gate={q:.6e} C")
        print(f"[C-V] capacitance_F = {capacitance}")

        assert all(gate_charges[i + 1] > gate_charges[i] for i in range(len(gate_charges) - 1))
        assert all(c > 0 for c in capacitance)

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print(f"RESULT: real C-V extracted on the flow's oxidation output "
          f"(capacitance ~= {capacitance[len(capacitance)//2]:.6e} F at mid-sweep). "
          f"Same equations/extraction as Phase 9, now driven by run_flow()'s "
          f"ProcessResult instead of a directly-called ThermalOxidation step.\n")
    return capacitance


def test_4_flow_oxidation_etch_doping_devsim():
    print("=" * 70)
    print("Test 4: Si -> oxidation -> etch -> doping -> DevSim (2-step flow)")
    print("=" * 70)
    etch_recipe = {
        "etch_time_s": 0.3,
        "material_rates": [{"material": "SiO2", "rate": -0.06},
                           {"material": "Si", "rate": 0.0},
                           {"material": "Mask", "rate": 0.0}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [
                FlowStep("oxidation", "thermal", OXIDATION_RECIPE, label="01_oxidation"),
                FlowStep("etching", "wet_etching", etch_recipe, label="02_wet_etch"),
            ],
            str(Path(tmp) / "flow"),
            reload_between_steps=True,
        )
        for i, r in enumerate(results):
            print(f"[Flow step {i}] materials={r.structure['materials']} "
                  f"level_sets={r.structure['num_level_sets']}")

        final = results[-1]
        assert "SiO2" in final.structure["materials"], (
            "step 2 must still carry the oxide grown in step 1 (continuity)"
        )

        doped = apply_uniform_doping(final, {"Si": 1.0e17})

        imported = import_process_result(
            doped, mesh_name="p14t4_mesh", device_name="p14t4_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        print(f"[DevSim import] regions={imported.regions} contacts={imported.contacts}")

        apply_doping(imported.device, doped.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        setup_semiconductor_potential_equation(imported.device, "Si", imported.contacts, temperature_k=300.0)
        for c in imported.contacts:
            set_bias(imported.device, c, 0.0)
        devsim.solve(type="dc", solver_type="direct", absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)

        pot = devsim.get_node_model_values(device=imported.device, region="Si", name="Potential")
        spread = max(pot) - min(pot)
        print(f"[Solve] Si node count={len(pot)}, potential spread={spread:.9f} V")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print(f"RESULT: a 2-step ViennaPS flow (oxidation -> wet_etching, continuity "
          f"proven by SiO2 surviving into step 2) was doped and solved in DevSim, "
          f"potential spread={spread:.6f} V. Process -> Doping -> Device chain works "
          f"across a multi-step flow.\n")


def main():
    test_1_flow_oxidation_to_devsim_import()
    test_2_flow_oxidation_doping_semiconductor_solve()
    test_3_flow_oxidation_mos_cv()
    test_4_flow_oxidation_etch_doping_devsim()
    print("ALL PHASE 14 FLOW -> DEVSIM CONNECTION TESTS PASSED "
          "AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1")


if __name__ == "__main__":
    main()
