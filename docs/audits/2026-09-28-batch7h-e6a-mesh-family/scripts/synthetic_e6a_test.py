"""Batch 7H-E6A SYNTHETIC test (no ViennaPS, no DEVSIM): small rectangles with the real base-grid line structure
(0.05 um, lines at +-0.1 / +-0.15 / +-0.2), both diagonal orientations, refined by the unmodified production
refine_mesh_near (pure numpy/Python). Checks the level-L rule at L = 3, 4, 5, bit-equality with 7H-E4's own
build_candidate at L = 4, cross-level nesting, and that every checker catches a deliberate defect.
usage: synthetic_e6a_test.py <out json>"""
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import family_e6a as fam  # noqa: E402
q4 = fam.q4
from tcad.device.devsim.mesh_refine import refine_mesh_near  # noqa: E402

TAG = 10


def synthetic_s0(nx_half=10, ny=3, diag="LLUR"):
    xs = (np.arange(-nx_half, nx_half + 1) * 0.05).astype(np.float32)
    ys = (np.arange(-ny, 1) * 0.05).astype(np.float32)
    P = np.array([(x, y, 0.0) for y in ys for x in xs], dtype=np.float32)
    idx = lambda i, j: j * len(xs) + i  # noqa: E731
    T = []
    for j in range(ny):
        for i in range(2 * nx_half):
            ll, lr, ur, ul = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            T += [(ll, lr, ur), (ll, ur, ul)] if diag == "LLUR" else [(ll, lr, ul), (lr, ur, ul)]
    return P, np.array(T, dtype=np.int64), np.full(len(T), TAG, dtype=np.int64), 2 * nx_half, ny


def level_mesh(P0, T0, G0, L):
    PL, TL, GL = refine_mesh_near(P0, T0, G0, lambda c: abs(c[0] - 0.0) < 0.1, levels=L)
    pts, tris, tags, rep, info = fam.build_level(P0, PL, TL, GL, L)
    return PL, TL, GL, pts, tris, tags, rep, info


def verify(P0, T0, G0, nxc, ny, L, PL, TL, pts, tris, tags, rep, info):
    r = {"counts": [rep["n_triangles"], rep["n_nodes"]], "predicted": list(fam.predicted_counts(L, ny, nxc))}
    r["counts_ok"] = r["counts"] == r["predicted"]
    cc = fam.construction_checks(P0, T0, PL, TL, pts, tris, info, L)
    ex = fam.exact_checks(pts[:, :2], tris, P0[:, :2], T0, tags, G0[0])
    rc, y0, xf = fam.resolution_checks(pts[:, :2], tris, PL[:, :2], P0[:, :2], T0, rep, L, fam.s0_spacing_error(P0[:, :2]))
    r["construction_ok"] = all(cc[k] for k in ("x_lines_are_mid32_recursion", "x_lines_strictly_ordered",
                                               "sl_points_prefix_bit_identical", "fine_rows_identical_to_S_L",
                                               "base_rows_identical_to_S_L", "base_region_equal_S0_coordinate_triples",
                                               "hanging_midpoints_owned"))
    r["exact_ok"] = exact_ok(ex)
    r["resolution_ok"] = bool(rc["ok"])
    r["n_obtuse"], r["n_template_cells"] = ex["n_obtuse_exact"], cc["n_template_cells"]
    r["delta_L_um"], r["x0_max_dev_um"] = rc["delta_L_um"], rc["C2_x0_max_abs_dev"]
    r["unreferenced"] = rep["unreferenced_nodes"]
    return r, y0, xf


def exact_ok(ex):
    return (ex["n_nonpositive_orientation"] == 0 and ex["n_obtuse_exact"] == 0 and ex["n_duplicate_triangles"] == 0
            and ex["tiling_T2_ok"] and ex["tiling_T3_ok"] and ex["area_equals_rect"] and ex["area_equals_S0"]
            and ex["boundary_points_lost"] == 0 and ex["bbox_equal"] and ex["left_contact_set_equal"]
            and ex["right_contact_set_equal"] and ex["tags_single_equal_S0"])


def mutations(P0, T0, G0, pts, tris, tags):
    """Each defect must be caught by the check named in the PLAN."""
    ch = lambda P, T: fam.exact_checks(P[:, :2], T, P0[:, :2], T0, np.full(len(T), TAG), G0[0])  # noqa: E731
    out = {}
    Pf = pts[:, :2].astype(np.float64)
    fine_ix = np.where(np.all(np.abs(Pf[tris][:, :, 0]) < 0.05, axis=1))[0]
    t = tris.copy()
    t[fine_ix[0]] = t[fine_ix[0]][[0, 2, 1]]
    e = ch(pts, t)
    out["flip_orientation"] = e["n_nonpositive_orientation"] > 0 and not e["tiling_T2_ok"]
    e = ch(pts, np.delete(tris, fine_ix[5], axis=0))
    out["delete_interior_triangle"] = not e["tiling_T3_ok"] and not e["area_equals_rect"]
    e = ch(pts, np.vstack([tris, tris[fine_ix[7]]]))
    out["duplicate_triangle"] = e["n_duplicate_triangles"] > 0 and not e["tiling_T2_ok"]
    # hanging node: split one fine triangle across its longest edge on one side only
    a, b, c = tris[fine_ix[9]]
    Q = Pf[[a, b, c]]
    lens = [np.linalg.norm(Q[1] - Q[2]), np.linalg.norm(Q[2] - Q[0]), np.linalg.norm(Q[0] - Q[1])]
    k = int(np.argmax(lens))
    apex, u, v = [(a, b, c), (b, c, a), (c, a, b)][k]
    Mxy = (pts[u] + pts[v]) / np.float32(2.0)
    P2 = np.vstack([pts, Mxy[None, :]])
    mid = len(pts)
    t = np.vstack([np.delete(tris, fine_ix[9], axis=0), [[apex, u, mid], [apex, mid, v]]])
    e = ch(P2, t)
    out["hanging_node"] = e["n_one_owner_edges_off_boundary"] > 0 and not e["tiling_T3_ok"]
    # obtuse by one float32 ulp: move an interior fine node right by one ulp (topology unchanged)
    inner = np.where((np.abs(Pf[:, 0]) < 0.04) & (Pf[:, 0] != 0) & (Pf[:, 1] < -0.02) & (Pf[:, 1] > -0.13))[0][0]
    P3 = pts.copy()
    P3[inner, 0] = np.nextafter(P3[inner, 0], np.float32(1.0))
    e = ch(P3, tris)
    out["obtuse_one_ulp"] = e["n_obtuse_exact"] > 0 and e["tiling_T2_ok"] and e["tiling_T3_ok"]
    # overlap: an extra triangle on three existing nodes spanning several cells
    s = np.where((np.abs(Pf[:, 1] + 0.05) < 1e-6))[0]
    s = s[np.argsort(Pf[s, 0])]
    up = np.where((np.abs(Pf[:, 1] + 0.0) < 1e-6) & (np.abs(Pf[:, 0] - Pf[s[3], 0]) < 1e-6))[0][0]
    e = ch(pts, np.vstack([tris, [[s[2], s[5], up]]]))
    out["overlapping_triangle"] = not (e["tiling_T2_ok"] and e["tiling_T3_ok"]) and not e["area_equals_rect"]
    # boundary gap: remove one triangle touching the bottom boundary
    bi = np.where(np.any(Pf[tris][:, :, 1] == Pf[:, 1].min(), axis=1))[0][0]
    e = ch(pts, np.delete(tris, bi, axis=0))
    out["boundary_gap"] = not e["tiling_T3_ok"]
    return out


def main():
    res, ok = {}, True
    for diag in ("LLUR", "LRUL"):
        P0, T0, G0, nxc, ny = synthetic_s0(diag=diag)
        prev = None
        for L in (3, 4, 5):
            PL, TL, GL, pts, tris, tags, rep, info = level_mesh(P0, T0, G0, L)
            r, y0, xf = verify(P0, T0, G0, nxc, ny, L, PL, TL, pts, tris, tags, rep, info)
            if prev is not None:
                r["x0_nested_in_previous"] = bool(np.array_equal(y0[::2], prev[0]))
                r["fine_x_nested_in_previous"] = bool(np.array_equal(xf[::2], prev[1]))
                ok &= r["x0_nested_in_previous"] and r["fine_x_nested_in_previous"]
            prev = (y0, xf)
            if L == 4:
                ep, et, eg, _ = q4.build_candidate(P0, PL, TL, GL)
                r["bit_identical_to_E4_build_candidate"] = bool(np.array_equal(ep, pts) and np.array_equal(et, tris)
                                                                 and np.array_equal(eg, tags))
                ok &= r["bit_identical_to_E4_build_candidate"]
            if L == 3:
                r["mutations_caught"] = mutations(P0, T0, G0, pts, tris, tags)
                ok &= all(r["mutations_caught"].values())
            ok &= r["counts_ok"] and r["construction_ok"] and r["exact_ok"] and r["resolution_ok"] and r["unreferenced"] == 0
            res[f"{diag}_L{L}"] = r
            print(f"{diag} L{L}: {r}", flush=True)
    try:
        fam.build_level(*synthetic_s0()[:1], *refine_mesh_near(*synthetic_s0()[:3], lambda c: abs(c[0]) < 0.1, levels=2), 2)
        res["L2_rejected"] = False
    except ValueError as e:
        res["L2_rejected"] = str(e).startswith("LEVEL_OUT_OF_RANGE")
    ok &= res["L2_rejected"]
    res["ALL_OK"] = bool(ok)
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump(res, f, indent=1, default=str)
        f.write("\n")
    print("ALL_OK", res["ALL_OK"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
