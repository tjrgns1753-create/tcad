"""Batch 7H-E6A local, read-only re-check of the downloaded raw arrays with code independent of the in-run checks
(no ViennaPS, no DEVSIM). usage: recheck_e6a_local.py <out json>"""
import json
import os
import sys
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "data", "remote_run_36388479824", "outputs", "e6a_out")
E4 = os.path.join(HERE, "..", "..", "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate", "data", "remote_run_36143535737",
                  "outputs", "e4_out", "candidate_e4.npz")


def main():
    out = {}
    e4 = np.load(E4)
    for L in (3, 4, 5):
        z = np.load(os.path.join(D, f"level_L{L}.npz"))
        P, T = z["points_um_f32"], z["triangles"]
        x, y, nv, el, ec = z["x"], z["y"], z["NodeVolume"], z["elements"], z["EdgeCouple"]
        rect = (Fraction(float(x.max())) - Fraction(float(x.min()))) * (Fraction(float(y.max())) - Fraction(float(y.min())))
        Q = np.c_[x, y][el]
        mx = 0.0
        for k in range(3):
            u, v = Q[:, (k + 1) % 3] - Q[:, k], Q[:, (k + 2) % 3] - Q[:, k]
            c = np.einsum("ij,ij->i", u, v) / np.linalg.norm(u, axis=1) / np.linalg.norm(v, axis=1)
            mx = max(mx, float(np.degrees(np.arccos(np.clip(c, -1, 1))).max()))
        y0 = np.sort(P[P[:, 0] == 0, 1]).astype(np.float64)
        a, b = np.sort(T, 1), np.sort(el, 1)
        r = {"n_nodes": int(len(P)), "n_triangles": int(len(T)),
             "devsim_xy_equal_scaled_construction_same_node_order": bool(
                 np.array_equal(x, (P[:, 0] * 1e-4).astype(float)) and np.array_equal(y, (P[:, 1] * 1e-4).astype(float))),
             "devsim_elements_equal_construction_in_order": bool(np.array_equal(el, T)),
             "devsim_elements_vertex_set_multiset_equal_construction": bool(
                 len(a) == len(b) and np.array_equal(np.unique(a, axis=0), np.unique(b, axis=0)) and len(np.unique(a, axis=0)) == len(a)),
             "sum_NodeVolume_over_exact_rect_minus_1": float((Fraction(float(np.sum(nv))) - rect) / rect),
             "NodeVolume_all_positive": bool((nv > 0).all()),
             "EdgeCouple_min": float(ec.min()), "EdgeCouple_negative": int((ec < 0).sum()), "EdgeCouple_zero": int((ec == 0).sum()),
             "max_angle_deg_float64": mx, "x0_nodes": int(len(y0)),
             "x0_spacing_min_max_um": [float(np.diff(y0).min()), float(np.diff(y0).max())]}
        if L == 4:
            r["bit_equal_to_E4_npz"] = {k: bool(np.array_equal(z[k2], e4[k])) for k, k2 in
                                        (("x", "x"), ("y", "y"), ("elements", "elements"), ("NodeVolume", "NodeVolume"),
                                         ("EdgeCouple", "EdgeCouple"))}
        out[f"L{L}"] = r
        print(f"L{L}: {r}", flush=True)
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
