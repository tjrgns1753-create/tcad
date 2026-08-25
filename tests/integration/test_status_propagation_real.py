#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Status must survive the worker's JSON boundary.

Physics status and the numerical (under-resolved) warning travel on
separate axes and must both reach the GUI. This is proven while
everything still reports empty/UNKNOWN, so the path is trusted before
any physics depends on it.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad_2d_stagewise as gui


def main():
    output = tempfile.mkdtemp(prefix="status_")
    config = {
        "_flow_steps": [{
            "_process_category": "deposition", "_process_model_key": "isotropic",
            "mask_spans_um": [], "pr_thickness_um": 1.0, "silicon_depth_um": 5.0,
            "grid_delta_um": 0.05, "x_extent_um": 10.0, "y_extent_um": 8.0,
            "rate": 0.05, "deposition_time_s": 0.3, "material": "SiO2",
        }],
        "output_dir": output,
    }
    config_file = os.path.join(output, "recipe.json")
    result_file = os.path.join(output, "result.json")
    Path(config_file).write_text(json.dumps(config), encoding="utf-8")

    gui.worker_main(config_file, result_file)
    result = json.loads(Path(result_file).read_text(encoding="utf-8"))
    assert result.get("success"), result.get("error")

    assert "physics_status" in result, (
        "physics status did not cross the worker's JSON boundary")
    assert "numerical_status" in result, (
        "the numerical warning must travel on its own key, not merged into "
        "physics status")

    # Whatever they hold must be JSON data, not live objects.
    json.dumps(result["physics_status"])
    json.dumps(result["numerical_status"])

    print("STATUS PROPAGATION OK")
    print(f"  physics_status   = {result['physics_status']}")
    print(f"  numerical_status = {result['numerical_status']}")


def test_two_step_flow_reports_every_step():
    """A non-final step's real status must not be dropped.

    results[-1] (the old single physics_status/numerical_status keys)
    only ever carries the LAST step. Put the etch step (wired to the
    resolver since Task 9) FIRST and a deposition step (not wired) LAST,
    so the old single-value key would have reported the deposition
    step's None/empty status while silently dropping the etch step's
    real one -- the exact scenario this finding describes.
    """
    print("\n[multi-step] every step's own status must reach the GUI, "
          "not just the last one")
    output = tempfile.mkdtemp(prefix="status2_")
    common = dict(pr_thickness_um=1.0, silicon_depth_um=5.0,
                  grid_delta_um=0.05, x_extent_um=10.0, y_extent_um=8.0,
                  mask_spans_um=[])
    config = {
        "_flow_steps": [
            {
                "_process_category": "etching", "_process_model_key": "isotropic",
                "rate": -0.2, "etch_time_s": 0.3, **common,
            },
            {
                "_process_category": "deposition", "_process_model_key": "isotropic",
                "rate": 0.05, "deposition_time_s": 0.3, "material": "SiO2",
                **common,
            },
        ],
        "output_dir": output,
    }
    config_file = os.path.join(output, "recipe.json")
    result_file = os.path.join(output, "result.json")
    Path(config_file).write_text(json.dumps(config), encoding="utf-8")

    gui.worker_main(config_file, result_file)
    result = json.loads(Path(result_file).read_text(encoding="utf-8"))
    assert result.get("success"), result.get("error")

    step_physics = result.get("step_physics_status")
    assert step_physics is not None, (
        "step_physics_status did not cross the worker's JSON boundary")
    assert len(step_physics) == 2, (
        f"expected one entry per flow step, got {len(step_physics)}: "
        f"{step_physics}")

    etch_status = step_physics[0]
    assert etch_status and etch_status.get("entries"), (
        "the etch step (step 0, NOT the last step) is wired to the "
        f"resolver and must report a real status even though it is not "
        f"the last step: {etch_status}")
    assert etch_status.get("resolution"), (
        f"etch step's status has no 'resolution' key: {etch_status}")

    print(f"    step_physics_status has {len(step_physics)} entries; "
          f"step 0 (etch, non-final) resolution="
          f"{etch_status.get('resolution')}")


if __name__ == "__main__":
    main()
    test_two_step_flow_reports_every_step()
    print("\nMULTI-STEP STATUS PROPAGATION OK")
