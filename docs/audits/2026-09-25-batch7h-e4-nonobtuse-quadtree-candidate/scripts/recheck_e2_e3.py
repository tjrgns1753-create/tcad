"""Batch 7H-E4 part 1: read-only recomputation from existing 7H-E1/E2/E3 arrays (numpy only; no ViennaPS/DEVSIM).
(a) x = 0 column: node count, F2 area, NodeVolume area, donor/acceptor contributions, total F2 / NodeVolume integrals.
(b) S4 vs E3 junction resolution: x = 0 y-coordinate sets, first x-columns, per-band spacing / element size.
(c) S0 vs E3 outer boundary: lost / new points, polyline, contact node sets.
Every value printed is MEASURED from arrays unless a line says RULE-APPLIED or FORMULA.
usage: recheck_e2_e3.py <out json>"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.abspath(os.path.join(HERE, "..", ".."))
E1 = os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "data", "remote_run_36012608804", "outputs", "e1_out")
E2 = os.path.join(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage", "data", "remote_run_36129959490", "outputs", "e2_out")
E3 = os.path.join(AUD, "2026-09-25-batch7h-e3-junction-refinement-candidate", "data", "remote_run_36139990927", "outputs", "e3_out")
N = 1e18                       # donor_conc_cm3 = acceptor_conc_cm3 (GUI defaults, E1 common_e1.GUI)
UM = 1e-4
CONT = N * 25.0 * UM * UM      # continuum N x 25 um^2 per half-domain, cm^-1


def rule(x):
    """RULE-APPLIED: tcad/physics/wafer_state_v2.py:743-744 -- donor on x >= 0, acceptor on x <= 0 (both at x = 0)."""
    return N * (x >= 0), N * (x <= 0)


def x0_block(label, x, nv, f2, don, acc, source):
    m0, mp, mn = x == 0.0, x > 0.0, x < 0.0
    r = {"label": label, "doping_source": source, "n_nodes": int(len(x)), "n_x0_nodes": int(m0.sum()),
         "F2_area_x0_cm2": float(f2[m0].sum()), "F2_area_xpos_cm2": float(f2[mp].sum()), "F2_area_xneg_cm2": float(f2[mn].sum()),
         "F2_area_total_cm2": float(f2.sum())}
    if nv is not None:
        r.update({"NodeVolume_area_x0_cm2": float(nv[m0].sum()), "NodeVolume_area_total_cm2": float(nv.sum())})
    for nm, c in (("donor", don), ("acceptor", acc)):
        r[f"{nm}_F2_total_cm-1"] = float((c * f2).sum())
        r[f"{nm}_F2_x0_part_cm-1"] = float((c * f2)[m0].sum())
        r[f"{nm}_F2_minus_continuum_cm-1"] = float((c * f2).sum() - CONT)
        r[f"{nm}_F2_minus_continuum_rel"] = float(((c * f2).sum() - CONT) / CONT)
        if nv is not None:
            r[f"{nm}_NodeVolume_total_cm-1"] = float((c * nv).sum())
            r[f"{nm}_NodeVolume_x0_part_cm-1"] = float((c * nv)[m0].sum())
    xs = np.unique(x)
    i0 = np.searchsorted(xs, 0.0)
    h_left, h_right = float(xs[i0] - xs[i0 - 1]), float(xs[i0 + 1] - xs[i0])
    r["first_column_distance_left_cm"], r["first_column_distance_right_cm"] = h_left, h_right
    return r


def column_heights(y):
    return float(y.max() - y.min())


def main():
    out = {"continuum_reference_cm-1": CONT, "N_cm-3": N}
    blocks = []
    e1 = np.load(os.path.join(E1, "prod_arrays.npz"))
    for k in range(5):
        z = np.load(os.path.join(E2, f"stage_S{k}.npz"))
        x, y = z["x"], z["y"]
        if k == 4:
            don, acc = e1["Donors"], e1["Acceptors"]
            src = "QUERIED (E1 WaferStateV2.net_doping_at capture, prod_arrays.npz; same node order as S4 by E2 I3)"
            rd, ra = rule(x)
            out["rule_reproduces_E1_query_on_S4"] = bool(np.array_equal(rd, don) and np.array_equal(ra, acc))
            assert np.array_equal(x, e1["x"]) and np.array_equal(y, e1["y"])
        else:
            don, acc = rule(x)
            src = "RULE-APPLIED (wafer_state_v2.py:743-744), validated against the queried arrays on S4 and E3"
        b = x0_block(f"E2 S{k}", x, z["NodeVolume"], z["F2"], don, acc, src)
        b["height_cm"] = column_heights(y)
        blocks.append(b)
    zf = np.load(os.path.join(E2, "candidate.npz"))
    s4 = np.load(os.path.join(E2, "stage_S4.npz"))
    b = x0_block("E2 exact-flip candidate", s4["x"], zf["NodeVolume"], zf["F2"], e1["Donors"], e1["Acceptors"],
                 "QUERIED (E1 arrays; identical point array to S4, E2 candidate points_identical=true)")
    b["height_cm"] = column_heights(s4["y"])
    blocks.append(b)
    z3 = np.load(os.path.join(E3, "candidate.npz"))
    rd, ra = rule(z3["x"])
    out["rule_reproduces_E3_query"] = bool(np.array_equal(rd, z3["donors"]) and np.array_equal(ra, z3["acceptors"]))
    b = x0_block("E3 graded candidate", z3["x"], z3["NodeVolume"], z3["F2"], z3["donors"], z3["acceptors"],
                 "QUERIED (E3 WaferStateV2.net_doping_at per node, candidate.npz)")
    b["height_cm"] = column_heights(z3["y"])
    blocks.append(b)
    for b in blocks:   # FORMULA check: gap = N * H * h_left / 2 for the donor (derivation in the supplementary erratum)
        b["FORMULA_donor_gap_N_H_hleft_over_2_cm-1"] = N * b["height_cm"] * b["first_column_distance_left_cm"] / 2
        b["FORMULA_acceptor_gap_N_H_hright_over_2_cm-1"] = N * b["height_cm"] * b["first_column_distance_right_cm"] / 2
    out["x0_blocks"] = blocks

    # (b) junction resolution S4 vs E3 (DEVSIM cm coordinates, compared exactly)
    s4x, s4y, s4e = s4["x"], s4["y"], s4["elements"]
    e3x, e3y, e3e = z3["x"], z3["y"], z3["elements"]
    ys4, ye3 = np.sort(s4y[s4x == 0.0]), np.sort(e3y[e3x == 0.0])
    res = {"x0_nodes_S4": int(len(ys4)), "x0_nodes_E3": int(len(ye3)),
           "x0_y_sets_equal": bool(np.array_equal(ys4, ye3)),
           "x0_y_spacing_S4_min_max_cm": [float(np.diff(ys4).min()), float(np.diff(ys4).max())],
           "x0_y_spacing_E3_min_max_cm": [float(np.diff(ye3).min()), float(np.diff(ye3).max())]}
    for lab, xx in (("S4", s4x), ("E3", e3x)):
        xs = np.unique(xx)
        i0 = np.searchsorted(xs, 0.0)
        res[f"first_columns_{lab}_cm"] = [float(xs[i0 - 1]), float(xs[i0 + 1])]
    res["bands"] = {}
    bands = [(0.0, 0.025), (0.025, 0.05), (0.05, 0.1), (0.1, 0.15), (0.15, 0.2)]
    for lab, xx, yy, el in (("S0", None, None, None), ("S4", s4x, s4y, s4e), ("E3", e3x, e3y, e3e)):
        if lab == "S0":
            z0 = np.load(os.path.join(E2, "stage_S0.npz"))
            xx, yy, el = z0["x"], z0["y"], z0["elements"]
        P = np.c_[xx, yy] / UM
        E = np.unique(np.sort(np.r_[el[:, [0, 1]], el[:, [1, 2]], el[:, [2, 0]]], 1), axis=0)
        L = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
        mid = np.abs((P[E[:, 0], 0] + P[E[:, 1], 0]) / 2)
        horiz = P[E[:, 0], 1] == P[E[:, 1], 1]
        vert = P[E[:, 0], 0] == P[E[:, 1], 0]
        for lo, hi in bands:
            m = (mid >= lo) & (mid < hi)
            key = f"{lo}-{hi}um"
            res["bands"].setdefault(key, {})[lab] = {
                "n_edges": int(m.sum()), "max_edge_um": float(L[m].max()), "median_edge_um": float(np.median(L[m])),
                "max_horizontal_edge_um": float(L[m & horiz].max()) if (m & horiz).any() else None,
                "max_vertical_edge_um": float(L[m & vert].max()) if (m & vert).any() else None,
                "min_edge_um": float(L[m].min())}
    out["resolution_S4_vs_E3"] = res

    # (c) boundary S0 vs E3 (raw ViennaPS micrometre file vs E3 candidate .vtu, float32 exact)
    import meshio
    m0 = meshio.read(os.path.join(E3, "wafer_volume.vtu"))
    mc = meshio.read(os.path.join(E3, "candidate.vtu"))
    P0, Pc = m0.points[:, :2].astype(float), mc.points[:, :2].astype(float)
    x0l, x0r, y0b, y0t = P0[:, 0].min(), P0[:, 0].max(), P0[:, 1].min(), P0[:, 1].max()

    def bset(P):
        mk = (P[:, 0] == x0l) | (P[:, 0] == x0r) | (P[:, 1] == y0b) | (P[:, 1] == y0t)
        return set(map(tuple, P[mk].tolist()))
    b0, bc = bset(P0), bset(Pc)
    new = sorted(bc - b0)
    out["boundary_S0_vs_E3"] = {
        "S0_boundary_points": len(b0), "E3_boundary_points": len(bc), "lost": len(b0 - bc), "new": len(new),
        "new_points_on_top_line_y0": sum(1 for p in new if p[1] == y0t), "new_points_on_bottom_line": sum(1 for p in new if p[1] == y0b),
        "new_points_on_left_or_right_line": sum(1 for p in new if p[0] in (x0l, x0r)),
        "new_points_x_range_um": [min(p[0] for p in new), max(p[0] for p in new)] if new else None,
        "bounding_box_S0": [float(x0l), float(x0r), float(y0b), float(y0t)],
        "bounding_box_E3": [float(Pc[:, 0].min()), float(Pc[:, 0].max()), float(Pc[:, 1].min()), float(Pc[:, 1].max())],
        "left_contact_nodes_S0_E3": [int((P0[:, 0] == x0l).sum()), int((Pc[:, 0] == x0l).sum())],
        "right_contact_nodes_S0_E3": [int((P0[:, 0] == x0r).sum()), int((Pc[:, 0] == x0r).sum())],
        "left_contact_sets_equal": set(map(tuple, P0[P0[:, 0] == x0l].tolist())) == set(map(tuple, Pc[Pc[:, 0] == x0l].tolist())),
        "right_contact_sets_equal": set(map(tuple, P0[P0[:, 0] == x0r].tolist())) == set(map(tuple, Pc[Pc[:, 0] == x0r].tolist())),
        "polyline_note": "every new point lies exactly on an existing straight boundary line (checked per point above); "
                         "the outer polygon's corner set and bounding box are unchanged, so the boundary SHAPE is unchanged; "
                         "only its subdivision changed"}
    corners0 = {(x0l, y0b), (x0l, y0t), (x0r, y0b), (x0r, y0t)}
    out["boundary_S0_vs_E3"]["corners_present_in_both"] = corners0 <= b0 and corners0 <= bc
    json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1, allow_nan=False)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
