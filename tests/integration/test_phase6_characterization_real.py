#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6 real-backend verification: run a real ViennaPS Etching
ProcessStep, import into DevSim, run a real bias sweep, extract real
terminal current, and write CSV/JSON/plot outputs.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.characterization.iv_sweep import run_iv_sweep
from tcad.characterization.io import save_csv, save_json
from tcad.characterization.plotting import save_iv_plot

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"


def main():
    recipe = {
        "grid_delta_um": 0.2,
        "x_extent_um": 4.0,
        "y_extent_um": 3.0,
        "mask_left_um": 1.5,
        "mask_right_um": 2.5,
        "pr_thickness_um": 0.5,
        "etch_time_s": 0.5,
        "rate": -0.05,
        "mask_material": "Mask",
    }
    step_cls = registry.get("etching", "isotropic")

    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(recipe, tmp)
        print(f"[1/5] ViennaPS process step OK -> {step_result['final_mesh']}")

        process_result = build_process_result(step_result)
        print(f"[2/5] ProcessResult OK -> regions: {[r.name for r in process_result.material_regions]}")

        imported = import_process_result(
            process_result,
            mesh_name="phase6_mesh",
            device_name="phase6_device",
            contact_regions=["Si"],
            contact_axis="x",
        )
        assert len(imported.contacts) == 2
        print(f"[3/5] DevSim import OK -> regions={imported.regions} contacts={imported.contacts}")

        sweep_contact, fixed_contact = imported.contacts[0], imported.contacts[1]
        sweep_voltages = [0.0, 0.1, 0.2, 0.3, 0.4]

        result = run_iv_sweep(
            device=imported.device,
            region="Si",
            all_contacts=imported.contacts,
            sweep_contact=sweep_contact,
            sweep_voltages=sweep_voltages,
            fixed_contacts={fixed_contact: 0.0},
            conductivity=1.0,
        )
        assert len(result.points) == len(sweep_voltages)
        print(f"[4/5] Real bias sweep OK -> {len(result.points)} points")
        for p in result.points:
            v = p.voltages[sweep_contact]
            i_sweep = p.currents[sweep_contact]
            i_fixed = p.currents[fixed_contact]
            print(f"      V={v:.2f}  I({sweep_contact})={i_sweep:.6e}  I({fixed_contact})={i_fixed:.6e}")

        # Physical sanity checks on REAL extracted values (not fabricated):
        v0_point = result.points[0]
        assert abs(v0_point.currents[sweep_contact]) < 1e-12, "I should be ~0 at V=0"
        last_point = result.points[-1]
        assert last_point.currents[sweep_contact] > 0, "current should flow for V>0"
        # charge conservation: current in one contact ~ -current in the other
        assert abs(last_point.currents[sweep_contact] + last_point.currents[fixed_contact]) < 1e-9

        csv_path = Path(tmp) / "iv_curve.csv"
        json_path = Path(tmp) / "iv_curve.json"
        plot_path = Path(tmp) / "iv_curve.png"

        save_csv(result, str(csv_path))
        save_json(result, str(json_path))
        save_iv_plot(result, str(plot_path))

        assert csv_path.exists() and csv_path.stat().st_size > 0
        assert json_path.exists() and json_path.stat().st_size > 0
        assert plot_path.exists() and plot_path.stat().st_size > 0

        print(f"[5/5] Output files OK -> {csv_path.name}, {json_path.name}, {plot_path.name}")
        print()
        print("--- CSV content ---")
        print(csv_path.read_text())

    print("PHASE 6 FULL PIPELINE (ViennaPS -> ProcessResult -> DevSim -> I-V sweep -> files) "
          "RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 SUCCESSFULLY")


if __name__ == "__main__":
    main()
