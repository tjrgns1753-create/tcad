"""Batch 7H-E4 candidate construction and exact geometric checks (pure numpy / Python ints; no ViennaPS, no DEVSIM).
PLAN sections 2-4. Keeps production S4's fine region and untouched base mesh, and re-fills only the 0.1-0.2 um strips on
each side with 2:1-balanced square cells split by the non-obtuse template (data/patch_proof.txt)."""
import numpy as np

F32 = np.float32


def mid32(a, b):
    """float32 midpoint computed exactly like production _refine_once: (p[a] + p[b]) / 2.0 on float32 values."""
    return (np.array([a], dtype=F32) + np.array([b], dtype=F32))[0] / F32(2.0)


def _line(xs, target):
    v = xs[np.argmin(np.abs(xs.astype(float) - target))]
    if abs(float(v) - target) > 1e-6:
        raise ValueError(f"no base grid line near x = {target}")
    return v


def build_candidate(s0_points, s4_points, s4_tris, s4_tags):
    """Returns (points float32 (n,3), triangles int64, tags, report). Raises ValueError on a fail-closed identity problem
    (ROW_NESTING_FAIL etc.) -- the caller records it and stops."""
    rep = {}
    xs0 = np.unique(s0_points[:, 0])
    P = s4_points
    lines = {}
    for s in (+1, -1):
        X01, X015, X02 = _line(xs0, 0.1 * s), _line(xs0, 0.15 * s), _line(xs0, 0.2 * s)
        X0125 = mid32(X01, X015)
        X01125 = mid32(X01, X0125)
        X0106 = mid32(X01, X01125)
        R4 = np.sort(P[P[:, 0] == X01, 1])
        R0_s0 = np.sort(s0_points[s0_points[:, 0] == X01, 1])
        if len(R4) != (len(R0_s0) - 1) * 16 + 1 or not np.array_equal(R4[::16], R0_s0):   # 1601 for the real 101-row mesh
            raise ValueError(f"ROW_NESTING_FAIL on side {s}: len(R4)={len(R4)}")
        lines[s] = dict(X01=X01, X0106=X0106, X01125=X01125, X0125=X0125, X015=X015, X02=X02, R4=R4)
    rep["x_lines_um"] = {("+" if s > 0 else "-"): {k: float(v) for k, v in d.items() if k != "R4"} for s, d in lines.items()}
    x = P[:, 0]
    X01p, X01n, X02p, X02n = lines[1]["X01"], lines[-1]["X01"], lines[1]["X02"], lines[-1]["X02"]
    tx = x[s4_tris]
    fine = np.all((tx >= X01n) & (tx <= X01p), axis=1)
    base = np.all((tx >= X02p) | (tx <= X02n), axis=1)
    removed = ~(fine | base)
    rtx = tx[removed]
    in_strip = np.all(((rtx >= X01p) & (rtx <= X02p)) | ((rtx <= X01n) & (rtx >= X02n)), axis=1)
    if not in_strip.all():
        raise ValueError("REMOVED_TRIANGLE_OUTSIDE_STRIP")
    rep.update({"s4_triangles": int(len(s4_tris)), "kept_fine": int(fine.sum()), "kept_base": int(base.sum()),
                "removed_strip": int(removed.sum())})

    key = {(float(a), float(b)): i for i, (a, b) in enumerate(zip(P[:, 0], P[:, 1]))}
    if len(key) != len(P):
        raise ValueError("DUPLICATE_S4_NODE")
    new_pts = []

    def node(xv, yv):
        k = (float(xv), float(yv))
        if k not in key:
            key[k] = len(P) + len(new_pts)
            new_pts.append((F32(xv), F32(yv), F32(0.0)))
        return key[k]

    new_tris = []
    for s, d in lines.items():
        R4 = d["R4"]
        R = {4: R4, 3: R4[::2], 2: R4[::4], 1: R4[::8], 0: R4[::16]}
        # sub-columns ordered from the fine side outward: (x_near, x_far, level, kind)
        cols = [(d["X01"], d["X0106"], 3, "T"), (d["X0106"], d["X01125"], 3, "R"), (d["X01125"], d["X0125"], 2, "T"),
                (d["X0125"], d["X015"], 1, "T"), (d["X015"], d["X02"], 0, "T")]
        for xn, xf, lev, kind in cols:
            xa, xb = (xn, xf) if s > 0 else (xf, xn)          # xa < xb always
            rows, finer = R[lev], R[lev + 1]
            for j in range(len(rows) - 1):
                y0, y1 = rows[j], rows[j + 1]
                LL, LR, UR, UL = node(xa, y0), node(xb, y0), node(xb, y1), node(xa, y1)
                if kind == "R":
                    new_tris += [(LL, LR, UR), (LL, UR, UL)]
                    continue
                ym = finer[2 * j + 1]
                if s > 0:      # finer neighbour on the LEFT (toward x = 0): M on x = xa
                    M = node(xa, ym)
                    new_tris += [(LL, LR, M), (M, LR, UR), (M, UR, UL)]
                else:          # finer neighbour on the RIGHT: M on x = xb
                    M = node(xb, ym)
                    new_tris += [(LL, LR, M), (LL, M, UL), (UL, M, UR)]
    pts = np.vstack([P, np.array(new_pts, dtype=P.dtype).reshape(-1, P.shape[1])]) if new_pts else P.copy()
    tris = np.vstack([s4_tris[fine], s4_tris[base], np.array(new_tris, dtype=s4_tris.dtype)])
    tags = np.full(len(tris), s4_tags[0], dtype=s4_tags.dtype)
    used = np.zeros(len(pts), bool)
    used[tris.ravel()] = True
    rep.update({"new_nodes": len(new_pts), "new_triangles": len(new_tris), "n_nodes": int(len(pts)),
                "n_triangles": int(len(tris)), "unreferenced_nodes": int((~used).sum()),
                "s4_tags_single_value": bool(np.all(s4_tags == s4_tags[0]))})
    rep["_masks"] = {"fine": fine, "base": base, "removed": removed, "n_new_tris": len(new_tris)}
    return pts, tris, tags, rep


def exact_ints(P2):
    """Exact integer coordinates X = x * 2^K (same construction as 7H-A exact_geometry.exact_integer_points)."""
    ratios = [(float(a).as_integer_ratio(), float(b).as_integer_ratio()) for a, b in P2]
    K = max(max(dx.bit_length(), dy.bit_length()) - 1 for (_, dx), (_, dy) in ratios)
    return [(nx * ((1 << K) // dx), ny * ((1 << K) // dy)) for (nx, dx), (ny, dy) in ratios], K


def exact_checks(P2, tris, s0_P2, s0_tris):
    """PLAN 4B: exact area (um^2), orientation, obtuse, duplicates, conforming, boundary, contacts."""
    from fractions import Fraction
    I, K = exact_ints(P2)
    area2 = 0
    n_nonpos = n_obtuse = 0
    for a, b, c in tris:
        A, B, C = I[a], I[b], I[c]
        o = (B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0])
        if o <= 0:
            n_nonpos += 1
        area2 += abs(o)
        for p, q, r in ((A, B, C), (B, C, A), (C, A, B)):
            if (q[0] - p[0]) * (r[0] - p[0]) + (q[1] - p[1]) * (r[1] - p[1]) < 0:
                n_obtuse += 1
                break
    I0, K0 = exact_ints(s0_P2)
    area2_0 = sum(abs((I0[b][0] - I0[a][0]) * (I0[c][1] - I0[a][1]) - (I0[b][1] - I0[a][1]) * (I0[c][0] - I0[a][0]))
                  for a, b, c in s0_tris)
    area = Fraction(area2, 2 * (1 << (2 * K)))
    area0 = Fraction(area2_0, 2 * (1 << (2 * K0)))
    owners = {}
    for t in tris:
        for u, v in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            owners[(min(u, v), max(u, v))] = owners.get((min(u, v), max(u, v)), 0) + 1
    x0l, x0r = s0_P2[:, 0].min(), s0_P2[:, 0].max()
    y0b, y0t = s0_P2[:, 1].min(), s0_P2[:, 1].max()

    def on_line(p, q):
        return (P2[p, 0] == P2[q, 0] and P2[p, 0] in (x0l, x0r)) or (P2[p, 1] == P2[q, 1] and P2[p, 1] in (y0b, y0t))
    bnd_edges = [e for e, n in owners.items() if n == 1]
    bnd_off_line = sum(1 for e in bnd_edges if not on_line(*e))

    def bset(Q):
        m = (Q[:, 0] == x0l) | (Q[:, 0] == x0r) | (Q[:, 1] == y0b) | (Q[:, 1] == y0t)
        return set(map(tuple, Q[m].astype(float).tolist()))
    b0, bc = bset(s0_P2), bset(P2)
    cset = lambda Q, xv: set(map(tuple, Q[Q[:, 0] == xv].astype(float).tolist()))  # noqa: E731
    return {"exact_area_um2": f"{area.numerator}/{area.denominator}", "exact_area_S0_um2": f"{area0.numerator}/{area0.denominator}",
            "exact_area_equal_S0": area == area0, "n_nonpositive_orientation": n_nonpos, "n_obtuse_exact": n_obtuse,
            "n_duplicate_triangles": len(tris) - len({tuple(sorted(map(int, t))) for t in tris}),
            "n_non_manifold_edges": sum(1 for n in owners.values() if n > 2),
            "n_boundary_edges": len(bnd_edges), "n_boundary_edges_off_outer_lines": bnd_off_line,
            "boundary_points_S0": len(b0), "boundary_points_candidate": len(bc), "boundary_points_lost": len(b0 - bc),
            "boundary_points_added": len(bc - b0),
            "bbox_equal": [float(P2[:, 0].min()), float(P2[:, 0].max()), float(P2[:, 1].min()), float(P2[:, 1].max())]
                          == [float(x0l), float(x0r), float(y0b), float(y0t)],
            "left_contact_set_equal": cset(P2, x0l) == cset(s0_P2, x0l), "right_contact_set_equal": cset(P2, x0r) == cset(s0_P2, x0r),
            "left_right_contact_nodes": [len(cset(P2, x0l)), len(cset(P2, x0r))]}


def exact_area_of(P2, tris):
    from fractions import Fraction
    I, K = exact_ints(P2)
    a2 = sum(abs((I[b][0] - I[a][0]) * (I[c][1] - I[a][1]) - (I[b][1] - I[a][1]) * (I[c][0] - I[a][0])) for a, b, c in tris)
    return Fraction(a2, 2 * (1 << (2 * K)))


BANDS = [(0.0, 0.025), (0.025, 0.05), (0.05, 0.1), (0.1, 0.15), (0.15, 0.2)]


def band_stats(x_cm, y_cm, el):
    """PLAN 4D: per band of edge-midpoint |x| (um): max / median / max-horizontal / max-vertical edge (um)."""
    P = np.c_[x_cm, y_cm] / 1e-4
    E = np.unique(np.sort(np.r_[el[:, [0, 1]], el[:, [1, 2]], el[:, [2, 0]]], 1), axis=0)
    L = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    mid = np.abs((P[E[:, 0], 0] + P[E[:, 1], 0]) / 2)
    horiz = P[E[:, 0], 1] == P[E[:, 1], 1]
    vert = P[E[:, 0], 0] == P[E[:, 1], 0]
    out = {}
    for lo, hi in BANDS:
        m = (mid >= lo) & (mid < hi)
        out[f"{lo}-{hi}"] = {"n_edges": int(m.sum()), "max_edge_um": float(L[m].max()), "median_edge_um": float(np.median(L[m])),
                             "max_horizontal_um": float(L[m & horiz].max()) if (m & horiz).any() else None,
                             "max_vertical_um": float(L[m & vert].max()) if (m & vert).any() else None}
    ys = np.sort(y_cm[x_cm == 0.0])
    xs = np.unique(x_cm)
    i0 = np.searchsorted(xs, 0.0)
    out["x0_line"] = {"n_nodes": int(len(ys)), "y_spacing_cm_min_median_max": [float(np.diff(ys).min()), float(np.median(np.diff(ys))),
                                                                                float(np.diff(ys).max())],
                      "first_columns_cm": [float(xs[i0 - 1]), float(xs[i0 + 1])]}
    return out, ys
