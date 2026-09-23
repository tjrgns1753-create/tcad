"""Why does the corrected checker report a large 'unknown' (methods
disagree) count on the real mesh, when all 12 synthetic A1-A12 fixtures
agreed cleanly? Investigate the first several unknown pairs directly,
printing both methods' raw numbers."""
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

from tcad.device.devsim.mesh_refine import _refine_once  # noqa: E402
from probe_delaunay_7g import build_raw_or_imported  # noqa: E402
from geometry_checks_v2 import corrected_triangle_overlap_check, classify_pair_topology  # noqa: E402

XJ_UM, BAND_HALF_WIDTH_UM = 0.0, 0.1


def _near_refine_target(centroid):
    return abs(centroid[0] - XJ_UM) < BAND_HALF_WIDTH_UM


def main():
    points, triangles, tags = build_raw_or_imported(None)
    for _ in range(3):
        centroids = points[triangles].mean(axis=1)
        marked = np.array([_near_refine_target(c) for c in centroids], dtype=bool)
        points, triangles, tags = _refine_once(points, triangles, tags, marked)

    r = corrected_triangle_overlap_check(points, triangles, tags)
    print(f"n_unknown_pairs={r['n_unknown_pairs']} area_tol={r['area_tol']:.6e} length_tol={r['length_tol']:.6e}")
    print(f"tolerance_detail={r['tolerance_detail']}")
    print()
    for u in r["unknown_pairs"][:15]:
        ti, tj = u["triangles"]
        topo, shared = classify_pair_topology(triangles[ti], triangles[tj])
        print(f"pair=({ti},{tj}) topo={topo} shared={shared} area_clip={u['area_clip']:.6e} "
              f"sat_min_overlap={u['sat_min_overlap_length']:.6e} "
              f"area_tol={r['area_tol']:.3e} length_tol={r['length_tol']:.3e}")
        print(f"  tri_i pts = {points[triangles[ti]][:, :2].tolist()}")
        print(f"  tri_j pts = {points[triangles[tj]][:, :2].tolist()}")


if __name__ == "__main__":
    main()
