"""Batch 7G Rev.1 Phase E: corrected Candidate A applied to the REAL L3
mesh (level=3 -> refine_levels=4, EXACTLY matching Phase 1's own
case_manifest_7g.json geo_imp_L3 case -- n_triangles=5760, n_points=2921,
n_delaunay_violations=68, reconfirmed). Only reached after the corrected
checker (Phase B) and corrected Candidate A (Phase C) both passed every
synthetic fixture (Phase A/B: 12/12; Candidate A synthetic: 4/4).
"""
import json
import os
import sys
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
PHASE1_SCRIPTS = os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts")
sys.path.insert(0, PHASE1_SCRIPTS)
sys.path.insert(0, os.path.dirname(__file__))

from probe_delaunay_7g import build_raw_or_imported  # noqa: E402
from geometry_checks import local_delaunay_check, hanging_node_check  # noqa: E402
from geometry_checks_v2 import (  # noqa: E402
    corrected_triangle_overlap_check, corrected_hole_check, triangle_signed_area,
)
from candidate_a_edge_flip_v2 import flip_to_local_delaunay_v2  # noqa: E402


def mesh_summary(label, points, triangles, tags):
    n = len(triangles)
    areas_signed = np.array([triangle_signed_area(*points[triangles[ti]][:, :2]) for ti in range(n)])
    interior, constrained = local_delaunay_check(points, triangles, tags)
    violations = [e for e in interior if e["angle_sum_violation"]]
    hang = hanging_node_check(points, triangles, tags)
    overlap = corrected_triangle_overlap_check(points, triangles, tags)
    hole = corrected_hole_check(points, triangles)
    return {
        "label": label, "n_points": len(points), "n_triangles": n,
        "total_abs_area_um2": float(np.abs(areas_signed).sum()),
        "n_zero_area": int((np.abs(areas_signed) < 1e-300).sum()),
        "n_inverted": int((areas_signed < 0).sum()),
        "n_delaunay_violations": len(violations),
        "n_hanging_nodes": len(hang),
        "n_confirmed_overlap_pairs": overlap["n_confirmed_overlaps"],
        "confirmed_overlap_area_um2": sum(o["area_clip"] for o in overlap["confirmed_overlaps"]),
        "n_unknown_overlap_pairs": overlap["n_unknown_pairs"],
        "n_boundary_loops": hole["n_boundary_loops"],
        "boundary_clean_manifold": hole["is_clean_manifold_boundary"],
        "n_constrained_edges": len(constrained),
        "material_tags_present": sorted(set(int(t) for t in tags)),
    }


def main():
    print("Building real imported L3 mesh (level=3 -> refine_levels=4, matches manifest geo_imp_L3)...")
    points, triangles, tags = build_raw_or_imported(3)
    before = mesh_summary("L3_before_flip", points, triangles, tags)
    print(json.dumps(before, indent=2, default=str))

    print("\nRunning corrected Candidate A (flip_to_local_delaunay_v2)...")
    new_points, new_triangles, new_tags, report = flip_to_local_delaunay_v2(points, triangles, tags, max_passes=20)
    print(f"terminated={report['terminated']}  passes={len(report['passes'])}")
    total_flips = sum(p.get("n_flips", 0) for p in report["passes"])
    print(f"total_flips={total_flips}")
    for p in report["passes"]:
        print(f"  pass {p['pass']}: violations_before={p['n_violations_before']} flips={p.get('n_flips')} "
              f"rejects={p.get('rejects')}")

    after = mesh_summary("L3_after_flip", new_points, new_triangles, new_tags)
    print("\n" + json.dumps(after, indent=2, default=str))

    # invariants
    coords_unchanged = np.array_equal(points, new_points)
    old_tri_multiset = sorted(tuple(sorted(int(v) for v in t)) for t in triangles)
    new_tri_multiset = sorted(tuple(sorted(int(v) for v in t)) for t in new_triangles)
    same_triangle_count = len(triangles) == len(new_triangles)
    material_tags_preserved = before["material_tags_present"] == after["material_tags_present"]

    print(f"\ncoords_unchanged={coords_unchanged}")
    print(f"same_triangle_count={same_triangle_count} (before={len(triangles)} after={len(new_triangles)})")
    print(f"material_tags_preserved={material_tags_preserved}")
    print(f"total_area_before={before['total_abs_area_um2']:.6f} total_area_after={after['total_abs_area_um2']:.6f} "
          f"diff={abs(before['total_abs_area_um2']-after['total_abs_area_um2']):.3e}")
    print(f"n_delaunay_violations before={before['n_delaunay_violations']} after={after['n_delaunay_violations']}")
    print(f"n_confirmed_overlap_pairs before={before['n_confirmed_overlap_pairs']} after={after['n_confirmed_overlap_pairs']}")
    print(f"n_unknown_overlap_pairs before={before['n_unknown_overlap_pairs']} after={after['n_unknown_overlap_pairs']}")
    print(f"n_hanging_nodes before={before['n_hanging_nodes']} after={after['n_hanging_nodes']}")
    print(f"n_zero_area before={before['n_zero_area']} after={after['n_zero_area']}")
    print(f"n_inverted before={before['n_inverted']} after={after['n_inverted']}")
    print(f"boundary_clean_manifold before={before['boundary_clean_manifold']} after={after['boundary_clean_manifold']}")

    out = {"before": before, "after": after, "flip_report": report,
           "coords_unchanged": bool(coords_unchanged), "same_triangle_count": bool(same_triangle_count),
           "material_tags_preserved": bool(material_tags_preserved), "total_flips": total_flips}
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "phase_e_l3_spike.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}")

    invariants_ok = coords_unchanged and same_triangle_count and material_tags_preserved
    if not invariants_ok:
        print("\n!!! GEOMETRY INVARIANTS FAILED -- per stop condition, halting before any NodeVolume measurement.")
        return

    if after["n_delaunay_violations"] >= before["n_delaunay_violations"] and total_flips == 0:
        print("\nNo flips were made; skipping DevSim NodeVolume re-measurement (would be identical to Phase 1's own L3 result).")
        return

    print("\nInvariants OK and flips were made -- proceeding to public-API DevSim NodeVolume measurement...")
    import devsim
    from probe_delaunay_7g import node_volume_vs_barycentric
    LENGTH_SCALE = 1.0e-4
    x, y, nv, bary = node_volume_vs_barycentric(new_points, new_triangles, "d_l3_flipped", "m_l3_flipped")
    nv_arr = np.array(nv)
    bary_arr = np.array(bary)
    total_nv = float(nv_arr.sum())
    total_bary = float(bary_arr.sum())
    rel_err = (total_nv - total_bary) / total_bary if total_bary else None
    print(f"sum_NodeVolume_cm2={total_nv:.6e} sum_barycentric_cm2={total_bary:.6e} relative_error={rel_err}")

    out["nodevolume_after_flip"] = {"sum_NodeVolume_cm2": total_nv, "sum_barycentric_cm2": total_bary,
                                    "relative_error": rel_err}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)


if __name__ == "__main__":
    main()
