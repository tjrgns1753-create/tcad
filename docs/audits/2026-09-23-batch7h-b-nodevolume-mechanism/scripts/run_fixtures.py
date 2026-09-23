"""Batch 7H-B Phases B-D: T1-T9, P1-P7 (+ H6 float32 interventions derived
deterministically from T4/T5) through DEVSIM's public geometric models."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formulas as fm  # noqa: E402
import fixtures as fx  # noqa: E402
import devsim_probe as dp  # noqa: E402

ANALYTIC = ("F1", "F2", "F3", "F4", "F4b", "F5")
RECON = ("F6a", "F6b", "F6c", "F6d", "F6e")


def reconstructions(m, pts):
    n = len(pts)
    out = {r: np.zeros(n) for r in RECON}
    e0, e1 = m["edge_n0"].astype(int), m["edge_n1"].astype(int)
    for k, (a, b) in enumerate(zip(e0, e1)):
        vals = {"F6a": m["EdgeNodeVolume"][k] if m["EdgeNodeVolume"] is not None else np.nan,
                "F6b": 0.5 * m["EdgeCouple"][k] * m["EdgeLength"][k],
                "F6c": 0.25 * m["EdgeCouple"][k] * m["EdgeLength"][k]}
        for r, v in vals.items():
            out[r][a] += v
            out[r][b] += v
    t0, t1 = m["el_en0"].astype(int), m["el_en1"].astype(int)
    for k, (a, b) in enumerate(zip(t0, t1)):
        L = float(np.hypot(pts[a, 0] - pts[b, 0], pts[a, 1] - pts[b, 1]))
        vd = m["ElementNodeVolume"][k] if m["ElementNodeVolume"] is not None else np.nan
        ve = 0.25 * m["ElementEdgeCouple"][k] * L if m["ElementEdgeCouple"] is not None else np.nan
        for node in (a, b):
            out["F6d"][node] += vd
            out["F6e"][node] += ve
    return out


def compare(dv, pred, abs_tol):
    err = np.abs(dv - pred)
    rel = err / np.maximum(np.abs(pred), 1e-300)
    ok = all(dp.match(d, p, abs_tol) for d, p in zip(dv, pred))
    return {"all_nodes_match": bool(ok), "max_abs_err": float(err.max()), "max_rel_err": float(rel.max()),
            "sum_pred": float(pred.sum())}


def element_level(m, pts, tris):
    """ElementEdgeCouple / ElementNodeVolume vs signed/abs (L/2)cot(opposite)."""
    res = {"ElementEdgeCouple_vs_signed": True, "ElementEdgeCouple_vs_abs": True,
           "ElementNodeVolume_vs_quarter_L_signed_couple": True, "ElementNodeVolume_vs_quarter_L_abs_couple": True,
           "negative_ElementEdgeCouple": 0, "negative_ElementNodeVolume": 0, "rows": []}
    if m["ElementEdgeCouple"] is None:
        return {"available": False}
    area = sum(fm.tri_area(pts[list(t)]) for t in tris)
    tol = dp.ABS_FACTOR * dp.EPS * area
    for k, (a, b, c) in enumerate(zip(m["el_en0"].astype(int), m["el_en1"].astype(int), m["el_en2"].astype(int))):
        L = float(np.hypot(*(pts[a] - pts[b])))
        cot = fm._cot(pts[c], pts[a], pts[b])
        cs = 0.5 * L * cot
        eec = float(m["ElementEdgeCouple"][k])
        env = float(m["ElementNodeVolume"][k]) if m["ElementNodeVolume"] is not None else np.nan
        res["ElementEdgeCouple_vs_signed"] &= dp.match(eec, cs, tol)
        res["ElementEdgeCouple_vs_abs"] &= dp.match(eec, abs(cs), tol)
        res["ElementNodeVolume_vs_quarter_L_signed_couple"] &= dp.match(env, 0.25 * L * cs, tol)
        res["ElementNodeVolume_vs_quarter_L_abs_couple"] &= dp.match(env, 0.25 * L * abs(cs), tol)
        res["negative_ElementEdgeCouple"] += eec < 0
        res["negative_ElementNodeVolume"] += env < 0
        res["rows"].append({"en0": a, "en1": b, "en2": c, "L": L, "signed_couple": cs,
                            "ElementEdgeCouple": eec, "ElementNodeVolume": env})
    res["available"] = True
    return res


def run_one(devsim, name, pts_um, tris):
    pts_in = np.asarray(pts_um, dtype=np.float64) * 1e-4
    dev, region, mesh = dp.import_fixture(devsim, pts_in, tris, name)
    try:
        m = dp.read_models(devsim, dev, region)
    finally:
        devsim.delete_device(device=dev)
        devsim.delete_mesh(mesh=mesh)
    ver = dp.verify_import(m, pts_in, tris)
    pts = np.column_stack([m["x"], m["y"]])          # coordinates DEVSIM holds
    area = sum(fm.tri_area(pts[list(t)]) for t in tris)
    abs_tol = dp.ABS_FACTOR * dp.EPS * max(area, 1e-300)
    nv = m["NodeVolume"]
    rules = {r: compare(nv, fm.node_areas(pts, tris, r), abs_tol) for r in ANALYTIC}
    rec = reconstructions(m, pts)
    rules.update({r: compare(nv, rec[r], abs_tol) for r in RECON})
    g1, g2, glen = fm.edge_couple_predictions(pts, tris)
    ec = {"n_edges": len(m["EdgeCouple"]), "negative": int((m["EdgeCouple"] < 0).sum()),
          "zero": int((m["EdgeCouple"] == 0).sum()), "vs_G1_signed": True, "vs_G2_abs": True, "rows": []}
    for k, (a, b) in enumerate(zip(m["edge_n0"].astype(int), m["edge_n1"].astype(int))):
        key = (min(a, b), max(a, b))
        d = float(m["EdgeCouple"][k])
        ec["vs_G1_signed"] &= dp.match(d, g1[key], abs_tol)
        ec["vs_G2_abs"] &= dp.match(d, g2[key], abs_tol)
        ec["rows"].append({"edge": key, "EdgeCouple": d, "G1_signed": g1[key], "G2_abs": g2[key],
                           "EdgeLength": float(m["EdgeLength"][k]),
                           "EdgeNodeVolume": float(m["EdgeNodeVolume"][k]) if m["EdgeNodeVolume"] is not None else None})
    orient = [float(np.sign((pts[b, 0] - pts[a, 0]) * (pts[c, 1] - pts[a, 1]) - (pts[b, 1] - pts[a, 1]) * (pts[c, 0] - pts[a, 0])))
              for a, b, c in tris]
    classes = []
    for t in tris:
        cot, _, _ = fm.tri_parts(pts[list(t)])
        classes.append("obtuse" if min(cot) < 0 else ("right" if min(abs(x) for x in cot) < 1e-12 else "acute"))
    return {"name": name, "verify": ver, "orientation_sign": orient, "triangle_class": classes,
            "physical_area_cm2": area, "abs_tol": abs_tol, "NodeVolume": nv.tolist(),
            "sum_NodeVolume": float(nv.sum()), "ratio_sum_NodeVolume_over_area": float(nv.sum() / area),
            "predictions": {r: fm.node_areas(pts, tris, r).tolist() for r in ANALYTIC},
            "reconstructions": {r: rec[r].tolist() for r in RECON},
            "rule_match": rules, "edge_couple": ec, "element_level": element_level(m, pts, tris),
            "models_available": {"edge": m["edge_models_builtin"], "element": m["element_models_builtin"]}}


def main():
    import devsim
    names = list(fx.FIXTURES)
    runs = [(n, *fx.as_arrays(n)) for n in names]
    # H6 intervention: T4/T5 with um coordinates rounded to float32 first
    for n in ("T4_mild_obtuse", "T5_strong_obtuse"):
        p, t = fx.as_arrays(n)
        runs.append((n + "_float32", p.astype(np.float32).astype(np.float64), t))
    results = {}
    for name, p, t in runs:
        r = run_one(devsim, name, p, t)
        results[name] = r
        if not all(r["verify"].values()):
            print("!!! STOP: import changed geometry/connectivity or mapping not proven", name, r["verify"])
            break
        rm = r["rule_match"]
        print(f"{name:32s} cls={r['triangle_class']} NV/area={r['ratio_sum_NodeVolume_over_area']:.15f} "
              f"match={[k for k, v in rm.items() if v['all_nodes_match']]} "
              f"EC(neg={r['edge_couple']['negative']},zero={r['edge_couple']['zero']},G1={r['edge_couple']['vs_G1_signed']},G2={r['edge_couple']['vs_G2_abs']}) "
              f"EL(EEC_signed={r['element_level'].get('ElementEdgeCouple_vs_signed')},EEC_abs={r['element_level'].get('ElementEdgeCouple_vs_abs')},"
              f"ENV_signed={r['element_level'].get('ElementNodeVolume_vs_quarter_L_signed_couple')},ENV_abs={r['element_level'].get('ElementNodeVolume_vs_quarter_L_abs_couple')},"
              f"negEEC={r['element_level'].get('negative_ElementEdgeCouple')},negENV={r['element_level'].get('negative_ElementNodeVolume')})")
    print("devices left:", devsim.get_device_list())
    out = os.path.join(HERE, "..", "data", "fixture_results.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o), sort_keys=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
