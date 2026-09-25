"""Batch 7H-E4 SYNTHETIC test (no ViennaPS / DEVSIM): structured float32 grid like ViennaPS's (0.05 um squares split by
one diagonal), production refine_mesh_near(|x|<0.1, levels=4) as S4, then build_candidate(). Checks: 0 exact obtuse,
exact area kept, conforming, boundary/contacts kept, fine region identical, and the 7H-B rules F3 == F2 (non-obtuse)
while S4 has F3 > F2. usage: synthetic_e4_test.py <out json>"""
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import quadtree_e4 as q  # noqa: E402
import formulas as fm  # noqa: E402
from tcad.device.devsim.mesh_refine import refine_mesh_near  # noqa: E402  (pure numpy)


def grid():
    xs = (np.arange(21) * 0.05 - 0.5).astype(np.float32)
    ys = (np.arange(5) * 0.05 - 0.2).astype(np.float32)
    P = np.array([(x, y, 0.0) for y in ys for x in xs], dtype=np.float32)
    nx, T = len(xs), []
    for j in range(len(ys) - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i
            T += [(a, b, c), (a, c, d)]
    return P, np.array(T, dtype=np.int64), np.ones(len(T))


def main():
    res, ok = {}, True
    P0, T0, G0 = grid()
    P4, T4, G4 = refine_mesh_near(P0, T0, G0, lambda c: abs(c[0]) < 0.1, levels=4)
    pts, tris, tags, rep = q.build_candidate(P0, P4, T4, G4)
    masks = rep.pop("_masks")
    res["build"] = rep
    ex = q.exact_checks(pts[:, :2], tris, P0[:, :2], T0)
    res["exact"] = ex
    ok &= ex["n_obtuse_exact"] == 0 and ex["n_nonpositive_orientation"] == 0 and ex["exact_area_equal_S0"]
    ok &= ex["n_duplicate_triangles"] == 0 and ex["n_non_manifold_edges"] == 0 and ex["n_boundary_edges_off_outer_lines"] == 0
    ok &= ex["boundary_points_lost"] == 0 and ex["bbox_equal"] and ex["left_contact_set_equal"] and ex["right_contact_set_equal"]
    ok &= rep["unreferenced_nodes"] == 0
    rem_area = q.exact_area_of(P4[:, :2], T4[masks["removed"]])
    new_area = q.exact_area_of(pts[:, :2], tris[len(tris) - masks["n_new_tris"]:])
    res["removed_equals_generated_area"] = rem_area == new_area
    ok &= rem_area == new_area
    fine_same = {tuple(sorted(map(tuple, P4[t, :2].astype(float).tolist()))) for t in T4[masks["fine"]]} == \
        {tuple(sorted(map(tuple, pts[t, :2].astype(float).tolist()))) for t in tris[:masks["fine"].sum()]}
    res["fine_region_identical"] = fine_same
    ok &= fine_same
    for lab, PP, TT in (("S4", P4, T4), ("candidate", pts, tris)):
        Pc = PP[:, :2].astype(float) * 1e-4
        tl = [list(map(int, t)) for t in TT]
        f2, f3 = fm.node_areas(Pc, tl, "F2"), fm.node_areas(Pc, tl, "F3")
        area = float(q.exact_area_of(PP[:, :2], TT)) * 1e-8
        res[lab] = {"sum_F3_over_area": float(f3.sum() / area), "sum_F2_over_area": float(f2.sum() / area),
                    "max_rel_F3_minus_F2": float(np.max(np.abs(f3 - f2) / f2))}
    ok &= res["candidate"]["max_rel_F3_minus_F2"] < 1e-12 and abs(res["candidate"]["sum_F3_over_area"] - 1) < 1e-12
    ok &= res["S4"]["sum_F3_over_area"] > 1.001    # the original defect is present in the synthetic S4
    b4, y4 = q.band_stats(P4[:, 0].astype(float) * 1e-4, P4[:, 1].astype(float) * 1e-4, T4)
    bc, yc = q.band_stats(pts[:, 0].astype(float) * 1e-4, pts[:, 1].astype(float) * 1e-4, tris)
    res["x0_y_equal"] = bool(np.array_equal(y4, yc))
    res["bands_candidate_le_S4_first3"] = all(bc[k]["max_edge_um"] <= b4[k]["max_edge_um"] for k in ("0.0-0.025", "0.025-0.05", "0.05-0.1"))
    ok &= res["x0_y_equal"] and res["bands_candidate_le_S4_first3"]
    # negative control: a deliberately broken template (M bisected from the far corner) must be caught as obtuse
    bad = np.array([[0, 1, 2]], dtype=np.int64)
    Pb = np.array([[0, 0], [1, 1], [1, 2]], dtype=np.float32)   # contains an obtuse angle
    exb = q.exact_checks(Pb, bad, Pb, bad)
    res["negative_control_obtuse_detected"] = exb["n_obtuse_exact"] == 1
    ok &= res["negative_control_obtuse_detected"]
    res["ALL_OK"] = bool(ok)
    json.dump(res, open(sys.argv[1], "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
