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
    # material_rates naming a material NOT exposed on this bare Si wafer
    # (rather than a blanket `rate`, which is now its own recognised
    # compat path -- see test_blanket_rate_compat_bridge) so the actually
    # -exposed "Si" still falls through to a genuine empty-table lookup.
    result = step.run({**BASE, "mask_spans_um": [], "chemistry": "SF6O2",
                       "material_rates": {"SiO2": -0.1}, "default_rate": -0.2,
                       "etch_time_s": 0.3},
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


def test_blanket_rate_compat_bridge():
    print("\n[C] a blanket `rate` (the GUI etch panel's real shape) is "
          "reported too, and the mask is excluded from it")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [[-5.0, -1.5], [1.5, 5.0]],
                       "mask_material": "Mask",
                       "rate": -0.2, "etch_time_s": 0.3},
                      tempfile.mkdtemp(prefix="rw_"))
    assert Path(result["final_mesh"]).exists()
    entries = result["physics_status"]["entries"]
    by_material = {e["material"]: e for e in entries}
    assert "Si" in by_material, f"no Si entry recorded: {entries}"
    si_entry = by_material["Si"]
    assert si_entry["provenance"] == "USER_SUPPLIED", si_entry
    assert si_entry["resolution"] == "UNVERIFIED", si_entry
    assert si_entry["value"] == -0.2, si_entry
    # The resolver still reports on every EXPOSED material (Mask
    # included -- that loop is unchanged), but Mask must not be given
    # the SAME blanket rate Si got: it falls through to the normal
    # (empty) table lookup instead of the compat bridge.
    mask_entry = by_material.get("Mask")
    assert mask_entry is not None, (
        f"Mask is exposed and must still be reported on: {entries}")
    assert mask_entry["provenance"] != "USER_SUPPLIED", (
        f"the mask must be excluded from the blanket rate, not given it: "
        f"{mask_entry}")
    assert mask_entry["value"] != -0.2, (
        f"the mask must not receive the same rate as Si: {mask_entry}")
    print(f"    Si reported as {si_entry['provenance']} / "
          f"{si_entry['resolution']} value={si_entry['value']}; "
          f"Mask reported as {mask_entry['provenance']} "
          f"(excluded from the blanket rate)")


def main():
    test_unknown_still_runs()
    test_caller_rates_still_honoured()
    test_blanket_rate_compat_bridge()
    print()
    print("RESOLVER WIRED — UNKNOWN runs, caller rates still honoured")


if __name__ == "__main__":
    main()
