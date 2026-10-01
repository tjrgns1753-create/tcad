"""E6M pure metrics (numpy only; no DEVSIM / ViennaPS import). PLAN: ../PLAN.md.
`compute()` derives every compared quantity from the RAW evidence (raw JSON + stored arrays + the preserved E6K 1D evidence); the remote test stores its result as `summary`
and the judge recomputes it, so a summary that does not follow from the raw data is detected."""
import math
import sys
from pathlib import Path

import numpy as np

H_UM = 0.1
H_CM = H_UM * 1.0e-4            # the only um -> cm conversion of the height
L_CM = 40.0e-4
Y_LINES_UM = [-0.1, -0.05, 0.0]
N_DOP = 1.0e17
LEVELS = ("L0", "L1", "L2")
DIRECTIONS = ("fwd", "rev")
VOLTAGES = {"fwd": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], "rev": [-0.25, -0.5, -0.75, -1.0]}
SNAP_BIASES = {"fwd": [0.0, 0.3, 0.5, 0.6], "rev": [0.0, -0.5, -1.0]}
PROFILE_CASES = [("rev", 0.0), ("fwd", 0.5), ("fwd", 0.6), ("rev", -0.5), ("rev", -1.0)]
JUDGED_CURRENT = [("fwd", 0.5), ("fwd", 0.6), ("rev", -0.5), ("rev", -1.0)]
FIELD_CASES = [("rev", 0.0), ("rev", -1.0)]
GEOM_ARRAYS = ("x", "y", "NodeVolume", "Donors", "Acceptors", "NetDoping", "edge_x0", "edge_x1", "edge_y0", "edge_y1", "EdgeLength", "element_nodes")
SNAP_ARRAYS = ("Potential", "Electrons", "Holes", "ElectricField")

E6L_SCRIPTS = Path(__file__).resolve().parents[2] / "2026-10-01-e6l-judge-integrity-equilibrium" / "scripts"


def vkey(v):
    return f"{v:+.3f}"


def akey(level, direction, name, bias=None):
    return f"{level}__{direction}__{name}" if bias is None else f"{level}__{direction}__bias{vkey(bias)}__{name}"


def build_mesh(x_cm):
    """Tensor-product mesh on the stored 1D node coordinates (cm -> um) and the three planned y lines; every cell split into two right triangles."""
    x_um = np.asarray(x_cm, dtype=np.float64) * 1.0e4
    nx = len(x_um)
    pts = np.array([[x, y, 0.0] for y in Y_LINES_UM for x in x_um])
    tris = []
    for j in range(len(Y_LINES_UM) - 1):
        for i in range(nx - 1):
            a, b = j * nx + i, j * nx + i + 1
            c, d = b + nx, a + nx
            tris += [(a, b, c), (a, c, d)]
    return pts, np.array(tris, dtype=np.int64)


def geometry_checks(points_um, triangles):
    p = np.asarray(points_um, dtype=np.float64)[:, :2] * 1.0e-4
    t = np.asarray(triangles)
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    obtuse = 0
    for u, v, w in ((a, b, c), (b, c, a), (c, a, b)):
        obtuse += int(np.sum(np.einsum("ij,ij->i", v - u, w - u) < 0))
    total = float(np.sum(area))
    return {"area_cm2": total, "area_expected_cm2": L_CM * H_CM, "area_rel_err": abs(total - L_CM * H_CM) / (L_CM * H_CM), "obtuse_triangles": obtuse,
            "degenerate_triangles": int(np.sum(area == 0)), "n_triangles": int(len(t)), "n_points": int(len(p))}


def e6k_snapshot(e6k_npz, level, direction, bias):
    """Last stored E6K DD snapshot of device L*_<direction> whose l-bias equals `bias`."""
    dev, tag = f"{level}_{direction}", f"bias{bias:+.3f}"
    idx = sorted({int(k.split("__")[1]) for k in e6k_npz.files if k.startswith(dev + "__") and f"__{tag}__" in k})
    if not idx:
        return None
    p = f"{dev}__{idx[-1]}__{tag}__"
    return {a: e6k_npz[p + a] for a in ("x", "Potential", "Electrons", "Holes", "ElectricField")}


def _grid(npz, level, direction):
    x, y = npz[akey(level, direction, "x")], npz[akey(level, direction, "y")]
    xs, ys = np.unique(x), np.unique(y)
    ix, iy = np.searchsorted(xs, x), np.searchsorted(ys, y)
    full = len(x) == len(xs) * len(ys) and len(set(zip(ix.tolist(), iy.tolist()))) == len(x)
    return xs, ys, ix, iy, bool(full)


def _on_grid(values, ix, iy, nx, ny):
    g = np.full((nx, ny), np.nan)
    g[ix, iy] = values
    return g


def compute(raw, npz, e6k_json, e6k_npz):
    out = {"H_cm": H_CM, "levels": {}}
    for lv in LEVELS:
        rec = {}
        g = geometry_checks(npz[f"{lv}__points_um"], npz[f"{lv}__triangles"])
        xs, ys, ix, iy, full = _grid(npz, lv, "fwd")
        x1d = e6k_snapshot(e6k_npz, lv, "rev", 0.0)["x"]
        same_len = len(xs) == len(x1d)
        g.update({"n_x_lines": int(len(xs)), "n_y_lines": int(len(ys)), "grid_complete": full, "y_lines_cm": [float(v) for v in ys],
                  "x_lines_equal_1d_count": bool(same_len), "x_lines_max_abs_diff_cm": float(np.max(np.abs(xs - x1d))) if same_len else float("nan"),
                  "nodevolume_sum_cm2": float(np.sum(npz[akey(lv, "fwd", "NodeVolume")])),
                  "nodevolume_rel_err": abs(float(np.sum(npz[akey(lv, "fwd", "NodeVolume")])) - L_CM * H_CM) / (L_CM * H_CM)})
        i0 = int(np.flatnonzero(xs == 0.0)[0]) if np.any(xs == 0.0) else -1
        g["junction_x_index"] = i0
        g["junction_left_edge_nm"] = float((xs[i0] - xs[i0 - 1]) * 1e7) if i0 > 0 else float("nan")
        g["junction_right_edge_nm"] = float((xs[i0 + 1] - xs[i0]) * 1e7) if 0 <= i0 < len(xs) - 1 else float("nan")
        rec["geometry"] = g
        # doping written (audit): step convention on the stored arrays
        xn = npz[akey(lv, "fwd", "x")]
        rec["doping_step_convention_ok"] = bool(np.array_equal(npz[akey(lv, "fwd", "Donors")], N_DOP * (xn >= 0)) and np.array_equal(npz[akey(lv, "fwd", "Acceptors")], N_DOP * (xn <= 0))
                                                and np.array_equal(npz[akey(lv, "fwd", "NetDoping")], N_DOP * (xn >= 0) - N_DOP * (xn <= 0)))
        # currents
        cur = {}
        for d in DIRECTIONS:
            dev2 = raw["levels"][lv]["devices"][d]
            dev1 = e6k_json["devices"][f"{lv}_{d}"]
            for c2, c1 in zip(dev2["currents"], dev1["currents"]):
                j2 = c2["I_min"] / H_CM
                cur[vkey(c2["V"])] = {"I_min_A_per_cm": c2["I_min"], "I_max_A_per_cm": c2["I_max"], "J_2d_A_per_cm2": j2, "J_1d_raw": c1["I_l"], "V_1d": c1["V"],
                                      "rel_diff": abs(j2 - c1["I_l"]) / abs(c1["I_l"]), "same_sign": bool(j2 * c1["I_l"] > 0),
                                      "kcl_rel": abs(c2["I_min"] + c2["I_max"]) / abs(c2["I_min"])}
        rec["currents"] = cur
        # y invariance and 1D profile comparison
        prof = {}
        for d, v in PROFILE_CASES:
            xs_d, ys_d, ix_d, iy_d, full_d = _grid(npz, lv, d)
            s1 = e6k_snapshot(e6k_npz, lv, d, v)
            ent = {"grid_complete": full_d}
            for name in ("Potential", "Electrons", "Holes"):
                gr = _on_grid(npz[akey(lv, d, name, v)], ix_d, iy_d, len(xs_d), len(ys_d))
                one = s1[name][:, None]
                if name == "Potential":
                    ent["psi_y_spread_V"] = float(np.max(gr.max(axis=1) - gr.min(axis=1)))
                    ent["psi_max_abs_diff_vs_1d_V"] = float(np.max(np.abs(gr - one)))
                else:
                    ent[f"{name}_y_spread_rel"] = float(np.max((gr.max(axis=1) - gr.min(axis=1)) / gr.mean(axis=1)))
                    ent[f"{name}_max_rel_diff_vs_1d"] = float(np.max(np.abs(gr - one) / one))
            prof[vkey(v)] = ent
        rec["profiles"] = prof
        # junction horizontal edges: x component of the edge field vs the 1D edge with the same end points
        fld = {}
        for d, v in FIELD_CASES:
            ex0, ex1 = npz[akey(lv, d, "edge_x0")], npz[akey(lv, d, "edge_x1")]
            ey0, ey1 = npz[akey(lv, d, "edge_y0")], npz[akey(lv, d, "edge_y1")]
            e = npz[akey(lv, d, "ElectricField", v)]
            xs_d = np.unique(npz[akey(lv, d, "x")])
            j0 = int(np.flatnonzero(xs_d == 0.0)[0])
            horiz = ey0 == ey1
            lo, hi = np.minimum(ex0, ex1), np.maximum(ex0, ex1)
            ex = e * np.sign(ex1 - ex0)
            s1 = e6k_snapshot(e6k_npz, lv, d, v)
            k1 = int(np.flatnonzero(s1["x"] == 0.0)[0])
            ent = {"non_horizontal_max_abs_E": float(np.max(np.abs(e[~horiz]))) if np.any(~horiz) else 0.0}
            for side, a, b, e1 in (("left", xs_d[j0 - 1], xs_d[j0], s1["ElectricField"][k1 - 1]), ("right", xs_d[j0], xs_d[j0 + 1], s1["ElectricField"][k1])):
                sel = horiz & (lo == a) & (hi == b)
                vals = ex[sel]
                ent[side] = {"n_edges": int(sel.sum()), "E_x_2d": [float(t) for t in sorted(vals.tolist())], "E_x_1d": float(e1), "edge_length_nm": float((b - a) * 1e7),
                             "max_rel_diff": float(np.max(np.abs(vals - e1) / abs(e1))) if sel.any() else float("nan")}
            fld[vkey(v)] = ent
        rec["junction_field"] = fld
        out["levels"][lv] = rec
    # 2D mesh sensitivity (E6K limits) and equilibrium diagnostics (not judged)
    c1, c2 = out["levels"]["L1"], out["levels"]["L2"]
    out["mesh_sensitivity"] = {
        "J_0.6_L1_vs_L2": abs(c1["currents"][vkey(0.6)]["J_2d_A_per_cm2"] - c2["currents"][vkey(0.6)]["J_2d_A_per_cm2"]) / abs(c2["currents"][vkey(0.6)]["J_2d_A_per_cm2"]),
        "J_-1.0_L1_vs_L2": abs(c1["currents"][vkey(-1.0)]["J_2d_A_per_cm2"] - c2["currents"][vkey(-1.0)]["J_2d_A_per_cm2"]) / abs(c2["currents"][vkey(-1.0)]["J_2d_A_per_cm2"]),
        "E_junction_left_-1.0_L1_vs_L2": abs(np.mean(c1["junction_field"][vkey(-1.0)]["left"]["E_x_2d"]) - np.mean(c2["junction_field"][vkey(-1.0)]["left"]["E_x_2d"]))
        / abs(np.mean(c2["junction_field"][vkey(-1.0)]["left"]["E_x_2d"]))}
    out["mesh_sensitivity"] = {k: float(v) for k, v in out["mesh_sensitivity"].items()}
    sys.path.insert(0, str(E6L_SCRIPTS))
    import pb_equilibrium as PB
    rp = e6k_json["reference_parameters"]
    c = {"q": rp["q"], "n_i": rp["n_i"], "Vt": rp["Vt"], "eps": rp["eps"], "N": rp["N_A"], "V_bi": rp["V_bi"]}
    _a, _psi_n, e_of, e0 = PB.pb_field(c)
    e_dep = math.sqrt(2 * c["q"] * c["V_bi"] / c["eps"] * c["N"] / 2)
    diag = {"E_dep_center_0V": e_dep, "E_PB_center_0V": e0, "levels": {}}
    for lv in LEVELS:
        left = out["levels"][lv]["junction_field"][vkey(0.0)]["left"]
        d_cm = left["edge_length_nm"] * 1e-7
        diag["levels"][lv] = {"E_PB_edge_mean_left_0V": float(PB.pb_edge_average(e_of, d_cm, 64)[0]), "abs_E_x_2d_left_0V_mean": float(abs(np.mean(left["E_x_2d"]))), "abs_E_x_1d_left_0V": abs(left["E_x_1d"])}
    out["equilibrium_diagnostics_not_judged"] = diag
    return out
