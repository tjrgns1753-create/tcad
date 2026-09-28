"""Batch 7H-E6A level-L mesh family: construction and exact checks (pure numpy / Python ints; no ViennaPS, no DEVSIM).
PLAN sections 2-4. The column/row structure is generated from L (PLAN section 2 table), not from 7H-E4's L = 4 literals;
7H-E4's float32 midpoint, grid-line lookup and exact-integer helpers are reused read-only."""
import os
import sys
from collections import Counter
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate", "scripts"))
import quadtree_e4 as q4  # noqa: E402  (E4, read-only: mid32, _line, exact_ints)

H0 = 0.05
NEAR_BANDS = [(0.0, 0.025), (0.025, 0.05), (0.05, 0.1)]
OUTER_BANDS = [(0.1, 0.15), (0.15, 0.2)]


def predicted_counts(L, ny, nx_cells):
    """PLAN section 2: T(L), N(L) for a base grid of nx_cells x ny cells, fine region = 4 base columns."""
    T = 8 * ny * 4 ** L + 2 * (nx_cells - 8) * ny + 2 * ny * (4 * 2 ** L - 3)
    N = ((4 * 2 ** L + 1) * (ny * 2 ** L + 1) + 2 * (nx_cells // 2 - 3) * (ny + 1) + 2 * (ny + 1)
         + 2 * (ny * (3 * 2 ** (L - 1) - 3) + L - 1))
    return T, N


def build_level(s0_points, sl_points, sl_tris, sl_tags, L):
    """Returns (points float32, triangles, tags, report, info). Raises ValueError('<LABEL> ...') on a fail-closed
    construction problem. info holds the per-side lines/rows/columns and the template long edges for the checks."""
    if L < 3:
        raise ValueError(f"LEVEL_OUT_OF_RANGE L={L}")
    xs0 = np.unique(s0_points[:, 0])
    P = sl_points
    sides = {}
    for s in (+1, -1):
        X01, X015, X02 = q4._line(xs0, 0.1 * s), q4._line(xs0, 0.15 * s), q4._line(xs0, 0.2 * s)
        m = [X015]
        for _ in range(1, L):
            m.append(q4.mid32(X01, m[-1]))
        RL = np.sort(P[P[:, 0] == X01, 1])
        R0 = np.sort(s0_points[s0_points[:, 0] == X01, 1])
        if len(RL) != (len(R0) - 1) * 2 ** L + 1 or not np.array_equal(RL[::2 ** L], R0):
            raise ValueError(f"ROW_NESTING_FAIL side {s}: len(R_L)={len(RL)}")
        cols = [(X01, m[L - 1], L - 1, "T"), (m[L - 1], m[L - 2], L - 1, "R")]
        cols += [(m[j], m[j - 1], j, "T") for j in range(L - 2, 0, -1)]
        cols += [(m[0], X02, 0, "T")]
        sides[s] = {"X01": X01, "X015": X015, "X02": X02, "m": m, "R": {k: RL[::2 ** (L - k)] for k in range(L + 1)},
                    "cols": cols}

    x = P[:, 0]
    X01p, X01n, X02p, X02n = sides[1]["X01"], sides[-1]["X01"], sides[1]["X02"], sides[-1]["X02"]
    tx = x[sl_tris]
    fine = np.all((tx >= X01n) & (tx <= X01p), axis=1)
    base = np.all((tx >= X02p) | (tx <= X02n), axis=1)
    removed = ~(fine | base)
    rtx = tx[removed]
    if not np.all(((rtx >= X01p) & (rtx <= X02p)) | ((rtx <= X01n) & (rtx >= X02n)), axis=1).all():
        raise ValueError("NONCONFORMING_MESH removed triangle outside the transition strip")

    key = {(float(a), float(b)): i for i, (a, b) in enumerate(zip(P[:, 0], P[:, 1]))}
    if len(key) != len(P):
        raise ValueError("NONCONFORMING_MESH duplicate S_L node coordinate")
    new_pts, new_tris, long_edges = [], [], []

    def node(xv, yv):
        k = (float(xv), float(yv))
        if k not in key:
            key[k] = len(P) + len(new_pts)
            new_pts.append((np.float32(xv), np.float32(yv), np.float32(0.0)))
        return key[k]

    for s, d in sides.items():
        for xn, xf, lev, kind in d["cols"]:
            xa, xb = (xn, xf) if s > 0 else (xf, xn)
            rows, finer = d["R"][lev], d["R"][lev + 1]
            for j in range(len(rows) - 1):
                y0, y1 = rows[j], rows[j + 1]
                LL, LR, UR, UL = node(xa, y0), node(xb, y0), node(xb, y1), node(xa, y1)
                if kind == "R":
                    new_tris += [(LL, LR, UR), (LL, UR, UL)]
                    continue
                if s > 0:      # finer neighbour on the left: hanging node M on x = xa
                    M = node(xa, finer[2 * j + 1])
                    new_tris += [(LL, LR, M), (M, LR, UR), (M, UR, UL)]
                    long_edges.append((LL, UL, M))
                else:          # finer neighbour on the right: hanging node M on x = xb
                    M = node(xb, finer[2 * j + 1])
                    new_tris += [(LL, LR, M), (LL, M, UL), (UL, M, UR)]
                    long_edges.append((LR, UR, M))
    pts = np.vstack([P, np.array(new_pts, dtype=P.dtype).reshape(-1, P.shape[1])]) if new_pts else P.copy()
    tris = np.vstack([sl_tris[fine], sl_tris[base], np.array(new_tris, dtype=sl_tris.dtype)])
    tags = np.full(len(tris), sl_tags[0], dtype=sl_tags.dtype)
    used = np.zeros(len(pts), bool)
    used[tris.ravel()] = True
    rep = {"L": L, "sl_triangles": int(len(sl_tris)), "kept_fine": int(fine.sum()), "kept_base": int(base.sum()),
           "removed_strip": int(removed.sum()), "new_nodes": len(new_pts), "new_triangles": len(new_tris),
           "n_nodes": int(len(pts)), "n_triangles": int(len(tris)), "unreferenced_nodes": int((~used).sum()),
           "sl_tags_single_value": bool(np.all(sl_tags == sl_tags[0])),
           "x_lines_um": {("+" if s > 0 else "-"): {"X01": float(d["X01"]), "X015": float(d["X015"]), "X02": float(d["X02"]),
                                                    "m": [float(v) for v in d["m"]]} for s, d in sides.items()},
           "columns": {("+" if s > 0 else "-"): [{"x": [float(a), float(b)], "level": lev, "kind": kd}
                                                 for a, b, lev, kd in d["cols"]] for s, d in sides.items()}}
    info = {"sides": sides, "fine": fine, "base": base, "long_edges": np.array(long_edges, dtype=np.int64).reshape(-1, 3)}
    return pts, tris, tags, rep, info


def construction_checks(s0_points, s0_tris, sl_points, sl_tris, pts, tris, info, L):
    """PLAN 4A (except counts, checked by the caller against predicted_counts)."""
    out = {}
    sides = info["sides"]
    out["x_lines_are_mid32_recursion"] = all(
        d["m"][0] == d["X015"] and all(d["m"][k] == q4.mid32(d["X01"], d["m"][k - 1]) for k in range(1, L))
        for d in sides.values())
    out["x_lines_strictly_ordered"] = all(
        all(abs(float(a)) < abs(float(b)) for a, b in zip([d["X01"]] + d["m"][::-1], d["m"][::-1] + [d["X02"]]))
        for d in sides.values())
    nf, nb = int(info["fine"].sum()), int(info["base"].sum())
    out["sl_points_prefix_bit_identical"] = bool(np.array_equal(pts[:len(sl_points)], sl_points))
    out["fine_rows_identical_to_S_L"] = bool(np.array_equal(tris[:nf], sl_tris[info["fine"]]))
    out["base_rows_identical_to_S_L"] = bool(np.array_equal(tris[nf:nf + nb], sl_tris[info["base"]]))
    X02p, X02n = sides[1]["X02"], sides[-1]["X02"]
    t0x = s0_points[s0_tris][:, :, 0]
    s0_base = s0_tris[np.all((t0x >= X02p) | (t0x <= X02n), axis=1)]
    trip = lambda Pp, T: Counter(tuple(sorted(map(tuple, Pp[t][:, :2].astype(float).tolist()))) for t in T)  # noqa: E731
    out["base_region_equal_S0_coordinate_triples"] = trip(pts, tris[nf:nf + nb]) == trip(s0_points, s0_base)
    out["n_base_S0"] = int(len(s0_base))
    # hanging-midpoint ownership: long edge absent, both halves owned twice
    keys, counts = edge_key_counts(tris, len(pts))
    le = info["long_edges"]

    def cnt(a, b):
        k = np.minimum(a, b) * len(pts) + np.maximum(a, b)
        i = np.searchsorted(keys, k)
        hit = (i < len(keys)) & (keys[np.minimum(i, len(keys) - 1)] == k)
        return np.where(hit, counts[np.minimum(i, len(keys) - 1)], 0)
    out["n_template_cells"] = int(len(le))
    out["long_edges_present"] = int((cnt(le[:, 0], le[:, 1]) > 0).sum())
    out["half_edges_not_owned_twice"] = int(((cnt(le[:, 0], le[:, 2]) != 2) | (cnt(le[:, 2], le[:, 1]) != 2)).sum())
    out["hanging_midpoints_owned"] = out["long_edges_present"] == 0 and out["half_edges_not_owned_twice"] == 0
    return out


def edge_key_counts(tris, n):
    a = tris[:, [0, 1, 2]].ravel()
    b = tris[:, [1, 2, 0]].ravel()
    k = np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b)
    return np.unique(k, return_counts=True)


def exact_checks(P2, tris, s0_P2, s0_tris, tags, s0_tag):
    """PLAN 4B (B1-B6) on exact integers of the float32 coordinates. P2/s0_P2: (n, 2) float32."""
    I, K = q4.exact_ints(P2)
    n_nonpos = n_obtuse = 0
    area2 = 0
    for a, b, c in tris.tolist():
        A, B, C = I[a], I[b], I[c]
        o = (B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0])
        if o <= 0:
            n_nonpos += 1
        area2 += o
        if ((B[0] - A[0]) * (C[0] - A[0]) + (B[1] - A[1]) * (C[1] - A[1]) < 0
                or (C[0] - B[0]) * (A[0] - B[0]) + (C[1] - B[1]) * (A[1] - B[1]) < 0
                or (A[0] - C[0]) * (B[0] - C[0]) + (A[1] - C[1]) * (B[1] - C[1]) < 0):
            n_obtuse += 1
    area = Fraction(area2, 2 * (1 << (2 * K)))
    I0, K0 = q4.exact_ints(s0_P2)
    area0 = Fraction(sum(abs((I0[b][0] - I0[a][0]) * (I0[c][1] - I0[a][1]) - (I0[b][1] - I0[a][1]) * (I0[c][0] - I0[a][0]))
                         for a, b, c in s0_tris.tolist()), 2 * (1 << (2 * K0)))
    xl, xr, yb, yt = s0_P2[:, 0].min(), s0_P2[:, 0].max(), s0_P2[:, 1].min(), s0_P2[:, 1].max()
    rect = (Fraction(float(xr)) - Fraction(float(xl))) * (Fraction(float(yt)) - Fraction(float(yb)))
    out = {"exact_area_um2": f"{area.numerator}/{area.denominator}", "exact_rect_area_um2": f"{rect.numerator}/{rect.denominator}",
           "exact_area_S0_um2": f"{area0.numerator}/{area0.denominator}", "area_equals_rect": area == rect,
           "area_equals_S0": area == area0, "n_nonpositive_orientation": n_nonpos, "n_obtuse_exact": n_obtuse}
    s = np.sort(tris, axis=1)
    out["n_duplicate_triangles"] = int(len(s) - len(np.unique(s, axis=0)))
    out.update(tiling_conditions(P2, tris, (xl, xr, yb, yt)))

    def bset(Q):
        m = (Q[:, 0] == xl) | (Q[:, 0] == xr) | (Q[:, 1] == yb) | (Q[:, 1] == yt)
        return set(map(tuple, Q[m].astype(float).tolist()))
    b0, bc = bset(s0_P2), bset(P2)
    cset = lambda Q, xv: set(map(tuple, Q[Q[:, 0] == xv].astype(float).tolist()))  # noqa: E731
    out.update({"boundary_points_S0": len(b0), "boundary_points": len(bc), "boundary_points_lost": len(b0 - bc),
                "boundary_points_added": len(bc - b0),
                "bbox_equal": [float(P2[:, 0].min()), float(P2[:, 0].max()), float(P2[:, 1].min()), float(P2[:, 1].max())]
                              == [float(xl), float(xr), float(yb), float(yt)],
                "left_contact_set_equal": cset(P2, xl) == cset(s0_P2, xl), "right_contact_set_equal": cset(P2, xr) == cset(s0_P2, xr),
                "contact_nodes_left_right": [len(cset(P2, xl)), len(cset(P2, xr))],
                "tags_single_equal_S0": bool(np.all(tags == s0_tag))})
    return out


def tiling_conditions(P2, tris, box):
    """PLAN B4 (T2)-(T3): edge ownership and orientation, boundary chain. (T1) is n_nonpositive_orientation == 0."""
    xl, xr, yb, yt = box
    n = len(P2)
    a = tris[:, [0, 1, 2]].ravel().astype(np.int64)
    b = tris[:, [1, 2, 0]].ravel().astype(np.int64)
    key = np.minimum(a, b) * n + np.maximum(a, b)
    fwd = (a < b).astype(np.int64)
    order = np.argsort(key, kind="stable")
    ks, fs = key[order], fwd[order]
    uk, start, cnt = np.unique(ks, return_index=True, return_counts=True)
    fsum = np.add.reduceat(fs, start)
    out = {"n_edges": int(len(uk)), "n_edges_owner_gt2": int((cnt > 2).sum()),
           "n_two_owner_edges_same_direction": int(((cnt == 2) & (fsum != 1)).sum())}
    one = order[start[cnt == 1]]                         # directed edge rows owned once
    u, v = a[one], b[one]
    xu, yu, xv, yv = P2[u, 0], P2[u, 1], P2[v, 0], P2[v, 1]
    sides = {"bottom": ((yu == yb) & (yv == yb), xu, xv, +1, 0, xl, xr),
             "right": ((xu == xr) & (xv == xr), yu, yv, +1, 1, yb, yt),
             "top": ((yu == yt) & (yv == yt), xu, xv, -1, 0, xr, xl),
             "left": ((xu == xl) & (xv == xl), yu, yv, -1, 1, yt, yb)}
    on_any = np.zeros(len(one), bool)
    chains = {}
    for name, (m, s_, e_, sgn, ax, c0, c1) in sides.items():
        on_any |= m
        st, en = s_[m].astype(np.float64), e_[m].astype(np.float64)
        o = np.argsort(sgn * st, kind="stable")
        st, en = st[o], en[o]
        ok_dir = bool(np.all(sgn * (en - st) > 0))
        ok_chain = bool(len(st) > 0 and st[0] == float(c0) and en[-1] == float(c1) and np.array_equal(en[:-1], st[1:]))
        line = P2[:, 1 - ax] == (yb if name == "bottom" else yt if name == "top" else xl if name == "left" else xr)
        verts = set(np.r_[st, en].tolist())
        ok_nodes = verts == set(P2[line, ax].astype(np.float64).tolist())
        chains[name] = {"n_edges": int(m.sum()), "ccw_direction": ok_dir, "corner_to_corner_gap_free": ok_chain,
                        "all_side_nodes_are_chain_vertices": ok_nodes}
    out["n_one_owner_edges"] = int(len(one))
    out["n_one_owner_edges_off_boundary"] = int((~on_any).sum())
    out["boundary_chains"] = chains
    out["tiling_T2_ok"] = out["n_edges_owner_gt2"] == 0 and out["n_two_owner_edges_same_direction"] == 0
    out["tiling_T3_ok"] = out["n_one_owner_edges_off_boundary"] == 0 and all(
        c["ccw_direction"] and c["corner_to_corner_gap_free"] and c["all_side_nodes_are_chain_vertices"] for c in chains.values())
    return out


def delta_L(e0, L):
    """PLAN 4C: e0 2^-L + L 2^-21 um."""
    return e0 * 2.0 ** -L + L * 2.0 ** -21


def s0_spacing_error(s0_P2):
    ys = np.unique(s0_P2[:, 1]).astype(np.float64)
    xs = np.unique(s0_P2[:, 0]).astype(np.float64)
    return float(max(np.max(np.abs(np.diff(ys) - H0)), np.max(np.abs(np.diff(xs) - H0))))


def edge_bands(P2, tris):
    """Per band of edge-midpoint |x| (um, float32 coordinates): n, min / median / max, max horizontal / vertical."""
    E = np.unique(np.sort(np.r_[tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], 1), axis=0)
    Q = P2.astype(np.float64)
    L_ = np.linalg.norm(Q[E[:, 0]] - Q[E[:, 1]], axis=1)
    mid = np.abs((Q[E[:, 0], 0] + Q[E[:, 1], 0]) / 2)
    hor = P2[E[:, 0], 1] == P2[E[:, 1], 1]
    ver = P2[E[:, 0], 0] == P2[E[:, 1], 0]
    out = {}
    for lo, hi in NEAR_BANDS + OUTER_BANDS:
        m = (mid >= lo) & (mid < hi)
        out[f"{lo}-{hi}"] = {"n_edges": int(m.sum()), "min_edge_um": float(L_[m].min()), "median_edge_um": float(np.median(L_[m])),
                             "max_edge_um": float(L_[m].max()),
                             "max_horizontal_um": float(L_[m & hor].max()) if (m & hor).any() else None,
                             "max_vertical_um": float(L_[m & ver].max()) if (m & ver).any() else None}
    return out


def resolution_checks(P2, tris, sl_P2, s0_P2, s0_tris, rep, L, e0):
    """PLAN 4C1-4C5. Returns (report, x0 y-set, fine x-lines)."""
    h = H0 * 2.0 ** -L
    dl = delta_L(e0, L)
    out = {"h_L_um": h, "e0_um": e0, "delta_L_um": dl}
    y0 = np.sort(P2[P2[:, 0] == 0, 1])
    y0_sl = np.sort(sl_P2[sl_P2[:, 0] == 0, 1])
    ny = len(np.unique(s0_P2[:, 1])) - 1
    dy = np.diff(y0.astype(np.float64))
    out["C1_x0_nodes"] = int(len(y0))
    out["C1_x0_count_ok"] = len(y0) == ny * 2 ** L + 1
    out["C1_x0_equal_S_L"] = bool(np.array_equal(y0, y0_sl))
    out["C2_x0_spacing_min_median_max"] = [float(dy.min()), float(np.median(dy)), float(dy.max())]
    out["C2_x0_max_abs_dev"] = float(np.max(np.abs(dy - h)))
    out["C2_ok"] = out["C2_x0_max_abs_dev"] <= dl
    X01 = rep["x_lines_um"]["+"]["X01"]
    xf = np.unique(P2[np.abs(P2[:, 0].astype(np.float64)) <= X01, 0])
    dx = np.diff(xf.astype(np.float64))
    out["C3_fine_x_lines"] = int(len(xf))
    out["C3_fine_x_count_ok"] = len(xf) == 4 * 2 ** L + 1
    out["C3_fine_x_max_abs_dev"] = float(np.max(np.abs(dx - h)))
    out["C3_ok"] = out["C3_fine_x_count_ok"] and out["C3_fine_x_max_abs_dev"] <= dl
    widths = [(c["level"], abs(c["x"][1] - c["x"][0])) for side in rep["columns"].values() for c in side]
    out["C4_column_width_max_abs_dev"] = float(max(abs(w - H0 * 2.0 ** -k) for k, w in widths))
    out["C4_ok"] = out["C4_column_width_max_abs_dev"] <= dl
    bc, b0 = edge_bands(P2, tris), edge_bands(s0_P2, s0_tris)
    out["bands"], out["bands_S0"] = bc, b0
    le = lambda u, v: u is not None and u <= v  # noqa: E731
    out["C5_near_ok"] = all(le(bc[k]["max_horizontal_um"], h + dl) and le(bc[k]["max_vertical_um"], h + dl)
                            and le(bc[k]["max_edge_um"], np.sqrt(2.0) * (h + dl)) for k in (f"{a}-{b}" for a, b in NEAR_BANDS))
    out["C5_outer_ok"] = all(bc[k]["max_edge_um"] <= b0[k]["max_edge_um"] for k in (f"{a}-{b}" for a, b in OUTER_BANDS))
    out["ok"] = all(out[k] for k in ("C1_x0_count_ok", "C1_x0_equal_S_L", "C2_ok", "C3_ok", "C4_ok", "C5_near_ok", "C5_outer_ok"))
    return out, y0, xf


def l4_reproduction(P2, tris, tags, ref_P2, ref_tris, ref_tags):
    """PLAN section 3: coordinate-level comparison with 7H-E4's candidate (never file bytes / serialization order)."""
    ps = lambda Q: Counter(map(tuple, Q.astype(float).tolist()))  # noqa: E731
    pc, pr = ps(P2), ps(ref_P2)
    tri = lambda Q, T: Counter(tuple(sorted(map(tuple, Q[t].astype(float).tolist()))) for t in T)  # noqa: E731
    xl, xr, yb, yt = ref_P2[:, 0].min(), ref_P2[:, 0].max(), ref_P2[:, 1].min(), ref_P2[:, 1].max()

    def bnd(Q):
        m = (Q[:, 0] == xl) | (Q[:, 0] == xr) | (Q[:, 1] == yb) | (Q[:, 1] == yt)
        return set(map(tuple, Q[m].astype(float).tolist()))
    cs = lambda Q, xv: set(map(tuple, Q[Q[:, 0] == xv].astype(float).tolist()))  # noqa: E731
    out = {"n_nodes": [len(P2), len(ref_P2)], "n_triangles": [len(tris), len(ref_tris)],
           "node_set_equal": set(pc) == set(pr), "no_duplicate_coordinates": max(pc.values()) == 1 and max(pr.values()) == 1,
           "triangle_coordinate_multiset_equal": tri(P2, tris) == tri(ref_P2, ref_tris),
           "tags_equal": bool(np.array_equal(np.unique(tags), np.unique(ref_tags)) and len(np.unique(tags)) == 1),
           "outer_boundary_set_equal": bnd(P2) == bnd(ref_P2),
           "contact_sets_equal": cs(P2, xl) == cs(ref_P2, xl) and cs(P2, xr) == cs(ref_P2, xr),
           "arrays_equal_in_order_reported_only": bool(np.array_equal(P2, ref_P2) and np.array_equal(tris, ref_tris))}
    out["ok"] = all(out[k] for k in ("node_set_equal", "no_duplicate_coordinates", "triangle_coordinate_multiset_equal",
                                     "tags_equal", "outer_boundary_set_equal", "contact_sets_equal"))
    return out
