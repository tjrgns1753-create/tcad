"""Batch 7H-B Phase E: apply the accepted rule (F3) to the Batch 7H-A L3
before mesh and exact-safe after mesh, regenerated read-only (Phase 1
build_raw_or_imported(3) + 7H-A exact_flip), imported with the same Batch 7F
helper 7H-A used. The flip history is checked against 7H-A's stored JSON."""
import hashlib
import json
import os
import sys
import warnings

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
A7H = os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-exact-flip-certification")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-22-batch7f-step-junction-root-cause", "scripts"))
sys.path.insert(0, os.path.join(A7H, "scripts"))

import formulas as fm  # noqa: E402
import devsim_probe as dp  # noqa: E402
from probe_delaunay_7g import build_raw_or_imported  # noqa: E402
from structured_mesh import import_structured_device  # noqa: E402
import exact_geometry as eg  # noqa: E402
import exact_flip as ef  # noqa: E402

XJ, BAND, RING = 0.0, 0.1, 0.3


def zone(x_um):
    d = abs(x_um - XJ)
    return "band" if d < BAND else ("ring" if d < RING else "outer")


def measure(devsim, pts_um, tris, name):
    region, mesh, _ = import_structured_device(devsim, pts_um, np.asarray(tris), np.zeros(len(tris), dtype=np.int64),
                                               f"d7hb_{name}", f"m7hb_{name}", 1e-4)
    m = dp.read_models(devsim, f"d7hb_{name}", region)
    devsim.delete_device(device=f"d7hb_{name}")
    devsim.delete_mesh(mesh=mesh)
    pts_cm = (pts_um * 1e-4).astype(np.float64)   # the float32 products the helper passes, as float64
    ver = dp.verify_import(m, pts_cm, tris)
    return m, ver


def analyse(m, tris, label):
    pts = np.column_stack([m["x"], m["y"]])
    nv = m["NodeVolume"]
    area = sum(fm.tri_area(pts[list(t)]) for t in tris)
    abs_tol = dp.ABS_FACTOR * dp.EPS * area
    f3, f2, f1 = (fm.node_areas(pts, tris, r) for r in ("F3", "F2", "F1"))
    err = nv - f3
    match = [dp.match(d, p, abs_tol) for d, p in zip(nv, f3)]
    resid = nv - f1                       # 7H-A residual definition (vs barycentric)
    excess_meas = nv - f2                 # measured over-count relative to the signed (area-conserving) dual
    excess_pred = f3 - f2                 # predicted over-count from |negative element couples|
    obt_inc = np.zeros(len(pts), dtype=int)
    for t in tris:
        cot, _, _ = fm.tri_parts(pts[list(t)])
        if min(cot) < 0:
            for v in t:
                obt_inc[v] += 1
    x_um = pts[:, 0] / 1e-4
    by_zone = {}
    for z in ("band", "ring", "outer"):
        sel = np.array([zone(x) == z for x in x_um])
        by_zone[z] = {"measured_residual_vs_bary": float(resid[sel].sum()), "measured_excess_vs_F2": float(excess_meas[sel].sum()),
                      "predicted_excess_F3_minus_F2": float(excess_pred[sel].sum()), "F3_minus_NV": float(-err[sel].sum())}
    top = np.argsort(-np.abs(resid))[:30]
    hot = set(int(i) for i in top)
    obtuse_nodes = set(int(i) for i in np.where(obt_inc > 0)[0])
    pos_excess_nodes = set(int(i) for i in np.where(excess_meas > abs_tol)[0])
    return {
        "label": label, "n_nodes": len(pts), "n_triangles": len(tris), "area_cm2": area, "abs_tol": abs_tol,
        "sum_DEVSIM": float(nv.sum()), "sum_F3": float(f3.sum()), "sum_F2": float(f2.sum()),
        "relative_error_DEVSIM": float((nv.sum() - area) / area), "relative_error_F3": float((f3.sum() - area) / area),
        "all_nodes_match_F3": bool(all(match)), "n_nodes_mismatch_F3": int(len(match) - sum(match)),
        "max_abs_node_err": float(np.abs(err).max()), "max_rel_node_err": float((np.abs(err) / np.abs(f3)).max()),
        "L1_err": float(np.abs(err).sum()), "L2_err": float(np.sqrt((err ** 2).sum())),
        "fraction_of_excess_explained_by_F3": float((f3.sum() - area) / (nv.sum() - area)) if nv.sum() != area else None,
        "residual_by_zone": by_zone,
        "n_obtuse_triangles": int(sum(1 for t in tris if min(fm.tri_parts(pts[list(t)])[0]) < 0)),
        "nodes_with_positive_measured_excess": len(pos_excess_nodes),
        "positive_excess_nodes_all_obtuse_incident": pos_excess_nodes <= obtuse_nodes,
        "obtuse_incident_nodes": len(obtuse_nodes),
        "top30_residual_nodes_obtuse_incident": len(hot & obtuse_nodes),
        "top30": [{"node": int(i), "x_um": float(x_um[i]), "y_um": float(pts[i, 1] / 1e-4), "zone": zone(float(x_um[i])),
                   "DEVSIM": float(nv[i]), "F3_pred": float(f3[i]), "barycentric": float(f1[i]), "abs_err": float(abs(err[i])),
                   "obtuse_incident": int(obt_inc[i])} for i in top],
    }


def main():
    import devsim
    points, tri0, tags0 = build_raw_or_imported(3)
    points = np.asarray(points)
    pts_sha = hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest()
    tris_b = [[int(v) for v in t] for t in tri0]
    ipts, K = eg.exact_integer_points(points[:, :2])
    _, bset, iset, _ = eg.edge_sets(tris_b, tags0)
    protected = frozenset(e for e, _ in bset) | frozenset(e for e, _ in iset)
    tris_a, _, rep = ef.exact_flip(points[:, :2], tris_b, tags0, protected=protected, max_passes=50)
    stored = json.load(open(os.path.join(A7H, "data", "phase_c_exact_flip.json"), encoding="utf-8"))
    hist_same = [(h["quad"], list(h["old_diagonal"]), list(h["new_diagonal"])) for h in rep["history"]] == \
                [(h["quad"], list(h["old_diagonal"]), list(h["new_diagonal"])) for h in stored["history"]]
    print(f"regenerated: points sha={pts_sha} (7H-A {stored['geometry_invariants']['points_sha256']}) flips={len(rep['history'])} "
          f"history_identical_to_7H-A={hist_same}")
    if pts_sha != stored["geometry_invariants"]["points_sha256"] or not hist_same:
        print("!!! STOP: could not regenerate the 7H-A mesh read-only"); sys.exit(2)
    out = {"points_sha256": pts_sha, "history_identical_to_7H_A": hist_same}
    for label, tris in (("before", tris_b), ("after", tris_a)):
        m, ver = measure(devsim, points[:, :2], tris, label)
        out[label + "_verify"] = ver
        if not all(ver.values()):
            print("!!! STOP: import verification failed", label, ver); sys.exit(2)
        out[label] = analyse(m, tris, label)
        a = out[label]
        print(f"[{label}] DEVSIM rel={a['relative_error_DEVSIM']:.10f} F3 rel={a['relative_error_F3']:.10f} "
              f"match_all={a['all_nodes_match_F3']} mismatches={a['n_nodes_mismatch_F3']} max_abs={a['max_abs_node_err']:.3e} "
              f"max_rel={a['max_rel_node_err']:.3e} L1={a['L1_err']:.3e} L2={a['L2_err']:.3e} explained={a['fraction_of_excess_explained_by_F3']}")
        print(f"    obtuse_tri={a['n_obtuse_triangles']} pos_excess_nodes={a['nodes_with_positive_measured_excess']} "
              f"all_obtuse_incident={a['positive_excess_nodes_all_obtuse_incident']} top30_obtuse_incident={a['top30_residual_nodes_obtuse_incident']}/30")
        print(f"    by zone={a['residual_by_zone']}")
    print("devices left:", devsim.get_device_list())
    with open(os.path.join(HERE, "..", "data", "l3_f3_prediction.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True, default=str)


if __name__ == "__main__":
    main()
