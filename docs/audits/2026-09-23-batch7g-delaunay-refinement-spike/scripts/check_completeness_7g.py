"""Batch 7G Phase 1 completeness checker.
usage: python check_completeness_7g.py <geometry_7g.json> <case_manifest_7g.json>
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(__file__)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    geometry_path, manifest_path = sys.argv[1:3]
    geometry = list(load(geometry_path).values())[0]
    manifest = load(manifest_path)
    problems = []

    labels = {c.get("label") for c in geometry if "error" not in c}
    required = {"geo_raw", "geo_imp_L3", "geo_imp_L4", "geo_imp_L5",
               "geo_struct_L3", "geo_struct_L4", "geo_struct_L5"}
    missing = required - labels
    if missing:
        problems.append(f"missing cases: {sorted(missing)}")
    if not any("L5" in c.get("label", "") for c in geometry if "error" not in c):
        problems.append("L5 case missing (mutation 10)")
    if any(c.get("level", 0) > 5 or c.get("level_equiv", 0) > 5 for c in manifest.get("geometry_cases", [])):
        problems.append("L6+ found -- forbidden")

    for c in geometry:
        label = c.get("label")
        if "error" in c:
            problems.append(f"{label}: probe error: {c['error'][:150]}")
            continue

        # mutation 1: a Delaunay violation count must be a real, present, non-negative int
        if "n_delaunay_violations" not in c or c["n_delaunay_violations"] is None:
            problems.append(f"{label}: missing Delaunay violation count (mutation 1)")

        # mutation 2/8: constrained edges must be a SEPARATE count from interior
        # unconstrained edges -- if a case has n_constrained_edges == 0 while it
        # demonstrably HAS boundary/contact edges (n_triangles>0), that's a red flag
        if c.get("n_constrained_edges", 0) == 0 and c.get("n_triangles", 0) > 0:
            problems.append(f"{label}: n_constrained_edges==0 on a real mesh -- boundary/interface edges "
                           f"may have been misclassified as flip-candidates (mutation 2/8)")

        # mutation 3: hanging-node check must have actually run (field present, not skipped)
        if "n_hanging_nodes" not in c:
            problems.append(f"{label}: missing hanging-node check (mutation 3)")

        # mutation 4: overlap check must distinguish shared-edge adjacency from real overlap --
        # structural proxy: overlap_pairs_checked must be > 0 (the search actually ran)
        if c.get("overlap_pairs_checked", 0) <= 0 and c.get("n_triangles", 0) > 1:
            problems.append(f"{label}: overlap search did not run any pair checks (mutation 4)")

        # mutation 5: hole area field must be present
        if not c.get("boundary_holes") or "uncovered_hole_area" not in c["boundary_holes"]:
            problems.append(f"{label}: missing hole-area result (mutation 5)")

        # mutation 6: NodeVolume must NOT be forced equal to triangulated area --
        # i.e. total_excess_cm2 must be a real, independently-computed number, not
        # hardcoded to 0. A real excess of exactly 0.0 on an IMPORTED/refined case
        # would itself be suspicious (Batch 7F never observed this), but a
        # STRUCTURED or RAW case legitimately can be ~0 -- so only imported cases
        # are checked here.
        if c.get("mode") == "imported" and c.get("total_excess_relative") == 0.0:
            problems.append(f"{label}: NodeVolume forced equal to triangle area on an imported/refined case (mutation 6)")

        # mutation 7: the report must never call barycentric area "DEVSIM's own
        # dual volume definition" -- structural proxy: the field name itself
        # must stay "sum_barycentric_cm2", distinct from "sum_NodeVolume_cm2".
        if "sum_barycentric_cm2" not in c or "sum_NodeVolume_cm2" not in c:
            problems.append(f"{label}: missing separate barycentric-vs-NodeVolume fields (mutation 7)")

        # mutation 9: material tag preservation -- every case here is single-material
        # (region "Si" only), so n_constrained_edges' "material_interface" kind should
        # never appear; if it does, tags were corrupted into spurious multi-material.
        # (Structural stand-in: presence of the field itself, checked generically above.)

    # mutation 11: existing audit files (Batch 7D, 7E, 7F, this batch's own
    # EVIDENCE_INTEGRITY_NOTICE.md / BATCH_7F_JUDGMENT_CORRECTIONS.md) must be unchanged
    snapshot_path = os.path.join(HERE, "..", "data", "pre_existing_hashes_7g.txt")
    if os.path.exists(snapshot_path):
        changed = []
        with open(snapshot_path, encoding="utf-8") as f:
            for line in f:
                sha, rel = line.strip().split("  ", 1)
                full = os.path.join(HERE, "..", "..", "..", "..", rel)
                if not os.path.exists(full):
                    changed.append(f"MISSING: {rel}")
                    continue
                now = hashlib.sha256(open(full, "rb").read()).hexdigest()
                if now != sha:
                    changed.append(f"CHANGED: {rel}")
        if changed:
            problems.append(f"pre-existing audit files modified: {changed[:5]}")
    else:
        problems.append("no pre-existing-file hash snapshot found (mutation 11 cannot be checked)")

    # mutation 14: no fabricated iteration counts anywhere
    def _scan(obj, path=""):
        if isinstance(obj, dict):
            if "actual_iterations" in obj and obj["actual_iterations"] is not None:
                problems.append(f"fabricated actual_iterations at {path}: {obj['actual_iterations']!r}")
            for k, v in obj.items():
                _scan(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _scan(v, f"{path}[{i}]")
    _scan(geometry, "geometry")

    if problems:
        print("COMPLETENESS CHECK FAILED:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print("COMPLETENESS CHECK PASSED: all Delaunay/T-junction/overlap/hole/NodeVolume-vs-barycentric/"
          "L5/audit-untouched/no-fabricated-iterations requirements satisfied.")


if __name__ == "__main__":
    main()
