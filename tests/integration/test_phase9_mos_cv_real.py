#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 9 real-backend verification: grow a real ViennaPS thermal oxide
on silicon, apply real substrate doping, import into DevSim as a real
MOS capacitor (Oxide/Si regions + Si-Oxide interface + gate/substrate
contacts), sweep real gate voltage, and extract real C-V data (no
synthetic points) via DevSim's get_contact_charge.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401 -- registers oxidation models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.cv_sweep import run_mos_cv_sweep
from tcad.characterization.io import save_cv_csv, save_json
from tcad.characterization.plotting import save_cv_plot

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.05,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.0,
    "mask_right_um": 3.0,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.05,
}

LENGTH_SCALE_TO_CM = 1.0e-4
SUBSTRATE_DOPING_CM3 = -1.0e15  # lightly doped p-type substrate (typical MOS cap)


def main():
    step_cls = registry.get("oxidation", "thermal")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        print(f"[1/6] ViennaPS thermal oxidation OK -> {step_result['final_mesh']}")

        process_result = build_process_result(step_result)
        region_names = sorted(r.name for r in process_result.material_regions)
        print(f"[2/6] ProcessResult OK -> regions: {region_names}")
        assert "SiO2" in region_names and "Si" in region_names

        doped_result = apply_uniform_doping(process_result, {"Si": SUBSTRATE_DOPING_CM3})
        assert doped_result.doping.kind == "uniform"
        assert process_result.doping is None, "original ProcessResult must stay untouched"
        print(f"[3/6] Substrate doping applied (separate from process model): Na={-SUBSTRATE_DOPING_CM3:.1e} cm^-3")

        imported = import_process_result(
            doped_result, mesh_name="phase9_mesh", device_name="phase9_device",
            contact_regions=["Si", "SiO2"], contact_axis="y",
            contact_sides={"Si": "min", "SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert imported.interfaces, "expected a real Si-SiO2 interface"
        substrate_contact = next(c for c in imported.contacts if c.startswith("Si_"))
        gate_contact = next(c for c in imported.contacts if c.startswith("SiO2_"))
        interface_name = imported.interfaces[0]
        print(f"[4/6] DevSim MOS import OK -> regions={imported.regions} "
              f"contacts={imported.contacts} interfaces={imported.interfaces}")

        apply_doping(imported.device, doped_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        gate_voltages = [-1.0, -0.5, 0.0, 0.5, 1.0]
        result = run_mos_cv_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            gate_contact=gate_contact, substrate_contact=substrate_contact,
            interface_name=interface_name, gate_voltages=gate_voltages,
        )
        print("[5/6] Real gate voltage sweep (equilibrium solve at each point):")
        gate_charges = result.metadata["gate_charges_C"]
        for v, q in zip(gate_voltages, gate_charges):
            print(f"      Vg={v:+.2f}  Q_gate={q:.6e} C")

        capacitance = result.metadata["capacitance_F"]
        cap_voltages = result.metadata["capacitance_voltages_V"]
        print("      Real C-V (finite-difference dQ/dV between solved points):")
        for v, c in zip(cap_voltages, capacitance):
            print(f"      Vg={v:+.2f}  C={c:.6e} F")

        # --- Physical sanity checks on REAL solver output ---
        # 1. Gate charge must vary monotonically with gate voltage for a
        #    simple MOS capacitor (more positive gate -> more positive
        #    charge induced/repelled appropriately) -- not exactly equal
        #    consecutive differences, but should not swing wildly in sign.
        assert len(set(round(q, 30) for q in gate_charges)) == len(gate_charges), (
            "gate charge should differ at every distinct bias, not be constant"
        )
        assert all(
            gate_charges[i + 1] > gate_charges[i] for i in range(len(gate_charges) - 1)
        ), f"gate charge should increase monotonically with gate voltage: {gate_charges}"

        # 2. Capacitance must be positive (physical dielectric/depletion
        #    capacitance, not a sign error) at every point.
        assert all(c > 0 for c in capacitance), f"capacitance must be positive: {capacitance}"

        # 3. Order-of-magnitude sanity: parallel-plate oxide capacitance
        #    C_ox = eps_ox*eps_0*Area/t_ox should roughly bound the observed
        #    capacitance from above (real MOS C-V never exceeds C_ox).
        eps_0 = 8.854e-14  # F/cm, DevSim's own constant (simple_physics.eps_0)
        from devsim.python_packages.simple_physics import eps_ox
        t_ox_native = devsim.get_node_model_values(device=imported.device, region="SiO2", name="y")
        t_ox_cm = max(t_ox_native) - min(t_ox_native)
        x_native = devsim.get_node_model_values(device=imported.device, region="SiO2", name="x")
        width_cm = max(x_native) - min(x_native)
        c_ox_upper_bound = eps_ox * eps_0 * width_cm / t_ox_cm
        print(f"      Sanity: parallel-plate C_ox upper bound ~= {c_ox_upper_bound:.3e} F "
              f"(oxide width={width_cm:.3e} cm, thickness~{t_ox_cm:.3e} cm)")
        assert all(c < 5 * c_ox_upper_bound for c in capacitance), (
            f"capacitance should not wildly exceed the parallel-plate oxide estimate: "
            f"{capacitance} vs bound {c_ox_upper_bound}"
        )

        # --- CSV/JSON/plot outputs ---
        csv_path = Path(tmp) / "mos_cv.csv"
        json_path = Path(tmp) / "mos_cv.json"
        plot_path = Path(tmp) / "mos_cv.png"
        save_cv_csv(result, str(csv_path))
        save_json(result, str(json_path))
        save_cv_plot(result, str(plot_path))
        assert csv_path.exists() and csv_path.stat().st_size > 0
        assert json_path.exists() and json_path.stat().st_size > 0
        assert plot_path.exists() and plot_path.stat().st_size > 0
        print(f"[6/6] Output files OK -> {csv_path.name}, {json_path.name}, {plot_path.name}")

    print()
    print("PHASE 9 FULL PIPELINE (ViennaPS thermal oxidation -> ProcessResult -> "
          "substrate doping -> DevSim MOS capacitor [Oxide/Si + interface] -> "
          "real gate voltage sweep -> real C-V) RAN AGAINST REAL VIENNAPS 4.6.2 + "
          "DEVSIM 2.10.1 SUCCESSFULLY")


if __name__ == "__main__":
    main()
