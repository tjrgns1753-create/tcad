#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 5 real-backend verification: run a real ViennaPS Etching
ProcessStep, adapt its result into a canonical ProcessResult, import
that into DevSim as a device (regions + contacts), and run the minimal
potential-only solve skeleton — all against actually-installed
ViennaPS 4.6.2 and DevSim 2.10.1, not mocks.
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
from tcad.device.devsim.solve import run_basic_potential_solve

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"


def main():
    # 1. Real ViennaPS process step (isotropic etch, small grid)
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
        assert Path(step_result["final_mesh"]).exists()
        print(f"[1/4] ViennaPS process step OK -> {step_result['final_mesh']}")

        # 2. Process -> canonical ProcessResult (viennaps-aware adapter)
        process_result = build_process_result(step_result)
        assert process_result.volume_mesh_path == step_result["final_mesh"]
        assert len(process_result.material_regions) >= 2, (
            "expected at least Mask + Si regions"
        )
        region_names = sorted(r.name for r in process_result.material_regions)
        print(f"[2/4] ProcessResult built OK -> regions: {region_names}")

        # 3. ProcessResult -> DevSim device (devsim-only from here on;
        #    no viennaps import anywhere below this line)
        imported = import_process_result(
            process_result,
            mesh_name="phase5_mesh",
            device_name="phase5_device",
            contact_regions=["Si"],
            contact_axis="x",
        )
        assert set(imported.regions) == set(region_names)
        assert len(imported.contacts) == 2, f"expected 2 contacts, got {imported.contacts}"
        print(f"[3/4] DevSim import OK -> regions={imported.regions} contacts={imported.contacts}")

        # 4. Minimal potential-only solve (no doping)
        contact_bias = {imported.contacts[0]: 1.0, imported.contacts[1]: 0.0}
        solve_result = run_basic_potential_solve(
            device=imported.device,
            region="Si",
            contact_bias=contact_bias,
        )
        assert solve_result["num_nodes"] > 0
        assert abs(solve_result["potential_max"] - 1.0) < 1e-6
        assert abs(solve_result["potential_min"] - 0.0) < 1e-6
        print(f"[4/4] DevSim solve OK -> {solve_result}")

    print()
    print("PHASE 5 FULL PIPELINE (ViennaPS -> ProcessResult -> DevSim -> solve) "
          "RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 SUCCESSFULLY")


if __name__ == "__main__":
    main()
