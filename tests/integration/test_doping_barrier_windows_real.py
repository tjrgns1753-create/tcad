#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
derive_barrier_covered_windows() must find the real x-range where SiO2
covers Si with real ViennaPS geometry (blanket oxidation -> litho
developed -> selective SiO2 etch through the opening), not assume it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session
from tcad.process.flow import FlowStep, run_flow
from tcad.device.devsim.mesh_import import derive_barrier_covered_windows

assert session.is_available(), "ViennaPS must be installed for this test"

WIDTH = 10.0
HALF = WIDTH / 2.0

BASE = dict(grid_delta_um=0.1, x_extent_um=WIDTH, y_extent_um=8.0,
            silicon_depth_um=5.0, pr_thickness_um=0.5)


def main():
    oxidation_recipe = {
        **BASE, "mask_spans_um": [],
        "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 1.0,
    }
    etch_recipe = {
        **BASE,
        "remask_spans_um": [[-HALF, -1.5], [1.5, HALF]],
        "mask_material": "PHS",
        "material_rates": {"SiO2": -0.3, "Si": 0.0, "PHS": 0.0},
        "default_rate": 0.0, "etch_time_s": 1.0,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        results = run_flow(
            [
                FlowStep("oxidation", "thermal", oxidation_recipe),
                FlowStep("etching", "isotropic", etch_recipe),
            ],
            tmp_dir,
        )

        etch_result = results[1]
        windows = derive_barrier_covered_windows(
            etch_result, doped_region="Si",
            barrier_material="SiO2", axis="x", min_barrier_thickness_um=0.01,
        )
        print("Barrier-covered windows:", windows)

        # The open window (etched clear of SiO2) must NOT be covered.
        for w in windows:
            assert not (w["min_um"] < 0.0 < w["max_um"]), (
                f"the open window (x=0, SiO2 etched away) must not be marked "
                f"barrier-covered: {windows}")

        # The protected region (x=-4, SiO2 intact) MUST be covered.
        assert any(w["min_um"] <= -4.0 <= w["max_um"] for w in windows), (
            f"the SiO2-protected region (x=-4) must be marked barrier-covered: "
            f"{windows}")

        print("derive_barrier_covered_windows() correctly separates the "
              "SiO2-covered region from the etched-open one.")


if __name__ == "__main__":
    main()
