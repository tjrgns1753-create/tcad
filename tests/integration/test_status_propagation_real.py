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


if __name__ == "__main__":
    main()
