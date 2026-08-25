#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The resolver is on the real path, and changes nothing yet.

The table is empty, so resolution is UNKNOWN and the step must still
run. A recipe that specifies material_rates keeps working unchanged —
that is the migration bridge — and is reported as USER_SUPPLIED.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.process import registry

BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=0.05,
            x_extent_um=10.0, y_extent_um=8.0)


def test_unknown_still_runs():
    print("\n[A] empty table: UNKNOWN, and the step still runs")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [], "chemistry": "SF6O2",
                       "rate": -0.2, "etch_time_s": 0.3},
                      tempfile.mkdtemp(prefix="rw_"))
    assert Path(result["final_mesh"]).exists(), "the etch did not produce a mesh"
    status = result.get("physics_status")
    assert status is not None, "the step produced no physics status"
    assert status["resolution"] == "UNKNOWN"
    assert status["entries"], "the step must record WHICH lookups were unknown"
    print(f"    resolution={status['resolution']} "
          f"entries={[e['material'] for e in status['entries']]}")


def test_caller_rates_still_honoured():
    print("\n[B] a recipe that specifies rates keeps working")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [],
                       "material_rates": {"Si": -0.2}, "default_rate": 0.0,
                       "etch_time_s": 0.3},
                      tempfile.mkdtemp(prefix="rw_"))
    assert Path(result["final_mesh"]).exists()
    entries = result["physics_status"]["entries"]
    supplied = [e for e in entries if e["material"] == "Si"]
    assert supplied and supplied[0]["provenance"] == "USER_SUPPLIED", (
        f"caller-specified rate not reported as USER_SUPPLIED: {entries}")
    print(f"    Si reported as {supplied[0]['provenance']} / "
          f"{supplied[0]['resolution']}")


def main():
    test_unknown_still_runs()
    test_caller_rates_still_honoured()
    print()
    print("RESOLVER WIRED — UNKNOWN runs, caller rates still honoured")


if __name__ == "__main__":
    main()
