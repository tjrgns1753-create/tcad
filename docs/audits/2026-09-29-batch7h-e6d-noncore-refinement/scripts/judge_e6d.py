"""Batch 7H-E6D verdict logic (pure numpy / Python; no DEVSIM, no ViennaPS). PLAN sections 2, 3, 5, 6, 7.
Reuses E6B judge_e6b (common set, four metrics, Gauss diagnostic, artifact tags) and E6C judge_e6c (initialization contract) read-only.
Names: F01 = M(G0-P, G1-P), F12 = M(G1-P, G2-P); A0, A1, A2 = `observed_initialization_shift` M(Gk-P, Gk-Q)."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(AUD, "2026-09-29-batch7h-e6c-initialization-robustness", "scripts"))
import judge_e6c as jc  # noqa: E402  (E6C, read-only)
jb = jc.jb               # E6B, read-only

METRICS = jb.METRICS
X01_UM, X02_UM = jb.X01_UM, jb.X02_UM
GS = (1, 2)
TAGS = ("P", "Q")
UM = 1e-4
# PLAN 2 / 3: every pre-solve check and the failure state it maps to (a missing check is a failed check).
CHECK_CLASS = {
    "core_node_set_equal": "CORE_IDENTITY_FAIL", "core_triangle_multiset_equal": "CORE_IDENTITY_FAIL",
    "construction_counts": "GEOMETRY_UNSUPPORTED", "tags_single_equal_G0": "GEOMETRY_UNSUPPORTED", "bbox_equal": "GEOMETRY_UNSUPPORTED",
    "area_equals_G0": "GEOMETRY_UNSUPPORTED", "orientation_positive": "GEOMETRY_UNSUPPORTED", "no_duplicate_triangles": "GEOMETRY_UNSUPPORTED",
    "no_duplicate_nodes": "GEOMETRY_UNSUPPORTED", "no_isolated_nodes": "GEOMETRY_UNSUPPORTED", "tiling_T2": "GEOMETRY_UNSUPPORTED",
    "tiling_T3": "GEOMETRY_UNSUPPORTED", "writer_roundtrip_exact": "GEOMETRY_UNSUPPORTED",
    "nodevolume_positive": "GEOMETRY_UNSUPPORTED", "nodevolume_sum_within_tau": "GEOMETRY_UNSUPPORTED",
    "edgecouple_no_negative": "GEOMETRY_UNSUPPORTED",
    "import_ok": "IMPORT_IDENTITY_FAIL", "xy_equal_scaled_construction": "IMPORT_IDENTITY_FAIL",
    "vertex_set_multiset_equal": "IMPORT_IDENTITY_FAIL", "regions_Si": "IMPORT_IDENTITY_FAIL", "contacts_ok": "IMPORT_IDENTITY_FAIL",
}
STATE_ORDER = ("CORE_IDENTITY_FAIL", "GEOMETRY_UNSUPPORTED", "IMPORT_IDENTITY_FAIL")


# ---------------------------------------------------------------- node keys, core identity, change record (PLAN 2)
def keys(P):
    """uint64 key of the float32 (x, y) bit patterns."""
    return jb.CommonSet._keys(np.ascontiguousarray(np.asarray(P, dtype=np.float32)[:, :2]))


def node_index(base, other):
    """Index into `other` of every `base` node (bit-identical float32 x, y); ValueError if any is missing."""
    kb, ko = keys(base), keys(other)
    order = np.argsort(ko, kind="stable")
    sk = ko[order]
    pos = np.searchsorted(sk, kb)
    hit = (pos < len(sk)) & (sk[np.minimum(pos, len(sk) - 1)] == kb)
    if not bool(hit.all()):
        raise ValueError(f"{int((~hit).sum())} base nodes missing")
    return order[pos]


def tri_rows(P, T):
    """Per triangle, its three vertex keys sorted: a node-id and vertex-order independent representation."""
    return np.sort(keys(P)[np.asarray(T, dtype=np.int64)], axis=1)


def _multiset_diff(A, B):
    """Rows of A not matched in B and rows of B not matched in A, as multisets. Returns (removed rows, added rows)."""
    both = np.concatenate([A, B]).view([("a", "u8"), ("b", "u8"), ("c", "u8")]).reshape(-1)
    u, inv = np.unique(both, return_inverse=True)
    inv = inv.reshape(-1)
    net = np.bincount(inv[:len(A)], minlength=len(u)) - np.bincount(inv[len(A):], minlength=len(u))
    rem = np.repeat(u[net > 0], net[net > 0])
    add = np.repeat(u[net < 0], -net[net < 0])
    f = lambda r: r.view(np.uint64).reshape(-1, 3)  # noqa: E731
    return f(rem), f(add)


def _region_of_abs_x(ax):
    return np.where(ax <= X01_UM, "core", np.where(ax >= X02_UM, "outer", "transition"))


def core_identity(P0, T0, Pk, Tk):
    """Core = |x| <= X01. Node set by bit pattern, and the multiset of vertex-coordinate triples of all-core triangles."""
    def core(P, T):
        ax = np.abs(np.asarray(P, dtype=np.float32)[:, 0].astype(np.float64))
        cm = ax <= X01_UM
        k = keys(P)
        tm = cm[np.asarray(T, dtype=np.int64)].all(axis=1)
        return np.sort(k[cm]), tri_rows(P, np.asarray(T)[tm])
    n0, t0 = core(P0, T0)
    nk, tk = core(Pk, Tk)
    rem, add = _multiset_diff(t0, tk) if len(t0) or len(tk) else (np.zeros((0, 3), np.uint64), np.zeros((0, 3), np.uint64))
    out = {"n_core_nodes": [int(len(n0)), int(len(nk))], "n_core_triangles": [int(len(t0)), int(len(tk))],
           "core_node_set_equal": bool(len(n0) == len(nk) and np.array_equal(n0, nk)),
           "core_triangle_multiset_equal": bool(len(rem) == 0 and len(add) == 0),
           "core_triangles_removed": int(len(rem)), "core_triangles_added": int(len(add))}
    out["ok"] = out["core_node_set_equal"] and out["core_triangle_multiset_equal"]
    return out


def change_record(P0, T0, Pk, Tk):
    """PLAN 2: G0 -> Gk triangle multiset difference by region of the triangle centroid, and the x-range of changed transition ones."""
    all_pts = np.concatenate([np.asarray(P0, np.float32)[:, :2], np.asarray(Pk, np.float32)[:, :2]])
    kall = keys(all_pts)
    ku, first = np.unique(kall, return_index=True)
    xs = all_pts[first, 0].astype(np.float64)
    rem, add = _multiset_diff(tri_rows(P0, T0), tri_rows(Pk, Tk))
    out = {}
    for name, rows in (("removed", rem), ("added", add)):
        cx = xs[np.searchsorted(ku, rows)].mean(axis=1) if len(rows) else np.zeros(0)
        reg = _region_of_abs_x(np.abs(cx))
        out[name] = {r: int((reg == r).sum()) for r in ("core", "transition", "outer")}
        tr = np.abs(cx[reg == "transition"])
        out[name]["transition_abs_centroid_x_um_range"] = [float(tr.min()), float(tr.max())] if len(tr) else None
    out["transition_changed"] = bool(out["removed"]["transition"] or out["added"]["transition"])
    return out


# ---------------------------------------------------------------- pre-solve gates (PLAN 3)
def contact_check(x, y, ext, nodes, edges):
    """Contact `nodes` must be every node on the line x == ext, include both corners, and consecutive nodes (by y) must be joined by a
    contact edge; `edges` = contact element node pairs. The node count is recorded, never fixed."""
    x, y = np.asarray(x), np.asarray(y)
    want = set(np.where(x == ext)[0].tolist())
    got = set(int(v) for v in nodes)
    ys = sorted(got, key=lambda i: y[i])
    es = {tuple(sorted((int(a), int(b)))) for a, b in edges}
    gaps = [(a, b) for a, b in zip(ys[:-1], ys[1:]) if tuple(sorted((a, b))) not in es]
    out = {"n_nodes": len(got), "n_edges": len(es), "node_set_equals_line": got == want and len(got) > 1,
           "has_both_corners": bool(len(ys) > 1 and y[ys[0]] == y.min() and y[ys[-1]] == y.max()), "n_uncovered_gaps": len(gaps)}
    out["ok"] = bool(out["node_set_equals_line"] and out["has_both_corners"] and not gaps)
    return out


def contacts_ok(x, y, contacts):
    """contacts = {name: {"nodes": [...], "edges": [[a, b], ...]}}; Si_xmin at x.min(), Si_xmax at x.max()."""
    out = {}
    for c, ext in (("Si_xmin", np.min(x)), ("Si_xmax", np.max(x))):
        d = contacts.get(c)
        if d is None or not d["nodes"]:
            out[c] = {"ok": False, "reason": "missing"}
        else:
            out[c] = contact_check(x, y, ext, d["nodes"], d["edges"])
    out["ok"] = bool(sorted(contacts) == ["Si_xmax", "Si_xmin"] and out["Si_xmin"]["ok"] and out["Si_xmax"]["ok"])
    return out


def nodevolume_gate(nv, area, tau):
    nv = np.asarray(nv, dtype=np.float64)
    r = float(nv.sum() / area)
    return {"min": float(nv.min()), "n_nonpositive": int((nv <= 0).sum()), "sum_cm2": float(nv.sum()), "area_cm2": float(area),
            "ratio": r, "tau": float(tau), "abs_ratio_minus_1": abs(r - 1.0), "positive": bool((nv > 0).all()),
            "sum_within_tau": bool(np.isfinite(r) and abs(r - 1.0) <= tau)}


def edgecouple_record(ec, n0, n1, x_cm):
    ec = np.asarray(ec, dtype=np.float64)
    mid = 0.5 * np.abs(np.asarray(x_cm)[n0] + np.asarray(x_cm)[n1]) / UM
    reg = _region_of_abs_x(mid)
    z = ec == 0
    return {"n_edges": int(len(ec)), "min": float(ec.min()), "n_negative": int((ec < 0).sum()), "n_zero": int(z.sum()),
            "n_zero_by_region_of_edge_midpoint": {r: int((z & (reg == r)).sum()) for r in ("core", "transition", "outer")},
            "no_negative": bool((ec >= 0).all() and np.isfinite(ec).all())}


def mesh_state(checks):
    """First failure class in STATE_ORDER among checks that ran and failed; then (fail-closed) among checks that never ran."""
    for bad in ({k: v for k, v in CHECK_CLASS.items() if k in checks and checks[k] is not True},
                {k: v for k, v in CHECK_CLASS.items() if k not in checks}):
        for st in STATE_ORDER:
            if st in bad.values():
                return st, sorted(k for k, v in bad.items() if v == st)
    return "OK", []


def core_doping_equal(idx, don, acc, net, ref):
    """Donors / Acceptors / NetDoping of Gk on the G0 core nodes (index `idx` into Gk, G0 order) equal the E6B L5 static arrays."""
    m = ref["core_mask"]
    return bool(all(np.array_equal(np.asarray(a)[idx][m], np.asarray(ref[k])[m]) for a, k in ((don, "Donors"), (acc, "Acceptors"), (net, "NetDoping"))))


# ---------------------------------------------------------------- decision (PLAN 5)
def inequalities(F01, F12, A0, A1, A2):
    vals = (F01, F12, A0, A1, A2)
    ok = all(jb.finite(v) for v in vals)
    rows = (("F01 > A0+A1", F01, A0 + A1 if ok else None), ("F12 > A1+A2", F12, A1 + A2 if ok else None),
            ("F01-F12 > A0+2*A1+A2", F01 - F12 if ok else None, A0 + 2 * A1 + A2 if ok else None))
    out = {f"ineq{k}": {"expr": e, "lhs": l, "rhs": r, "holds": bool(ok and l > r)} for k, (e, l, r) in enumerate(rows, 1)}
    out["all_finite"] = ok
    return out


def ineq01(F01, A0, A1):
    ok = all(jb.finite(v) for v in (F01, A0, A1))
    return {"ineq1": {"expr": "F01 > A0+A1", "lhs": F01, "rhs": A0 + A1 if ok else None, "holds": bool(ok and F01 > A0 + A1)},
            "all_finite": ok}


def metric_state(ineq, g2_valid):
    if not ineq["all_finite"]:
        return "NONFINITE_INPUT"
    if not ineq["ineq1"]["holds"]:
        return "NO_RESOLVABLE_NONCORE_CHANGE"
    if not g2_valid:
        return "NONCORE_CHANGE_RESOLVED_01"
    if not ineq["ineq2"]["holds"]:
        return "NONCORE_CHANGE_RESOLVED_01"                     # F12 not resolved: decrease test cannot hold
    return "NONCORE_REFINEMENT_DECREASE_OBSERVED" if ineq["ineq3"]["holds"] else "NO_NONCORE_DECREASE"


def g_state(mesh_st, runs):
    """mesh_st: "OK" or a failure label; runs[tag] = {"status", "solve", "consistency_ok"}. Never promotes a failed run to a result."""
    if mesh_st != "OK":
        return mesh_st
    sts = [(runs.get(t) or {"status": "MISSING"}).get("status") for t in TAGS]
    if "INITIALIZATION_CONTRACT_FAIL" in sts:
        return "INITIALIZATION_CONTRACT_FAIL"
    for st in sts:
        if st is not None:
            return st
    if not all(jb.primary_ok((runs.get(t) or {}).get("solve")) for t in TAGS):
        return "POISSON_NOT_CONVERGED"
    if not all((runs.get(t) or {}).get("consistency_ok") is True for t in TAGS):
        return "CONSISTENCY_FAIL"
    return "OK"


def judge(gstate, psi, cs, flags):
    """gstate = {0: "OK"|label, 1: ..., 2: ...}; psi[k][t] = Potential in G0 node order (or None); cs = common set on the G0 nodes.
    flags = {"artifact_problems", "input_identity_ok"}."""
    res = {"g_states": {f"G{k}": gstate.get(k) for k in (0, 1, 2)}, "regions": {}, "metrics": {}}
    fail = None
    if flags.get("artifact_problems"):
        fail = "ARTIFACT_INCOMPLETE"
    elif not flags.get("input_identity_ok", True):
        fail = "INPUT_IDENTITY_FAIL"
    elif not cs.masks["core"].any():
        fail = "CONSISTENCY_FAIL"
        res["core_empty"] = True
    elif gstate.get(0) != "OK":
        fail = gstate.get(0)
    elif gstate.get(1) != "OK":
        fail = gstate.get(1)
    ok = {k: gstate.get(k) == "OK" and all(psi.get(k, {}).get(t) is not None and jc.finite_arr(psi[k][t]) for t in TAGS)
          for k in (0, 1, 2)}
    if fail is None and not (ok[0] and ok[1]):
        fail = "CONSISTENCY_FAIL"
    res["failure"] = fail
    g2 = ok[2]
    if fail is None:
        F01 = jb.metrics_between(psi[0]["P"], psi[1]["P"], cs)
        A = {k: jb.metrics_between(psi[k]["P"], psi[k]["Q"], cs) for k in (0, 1, 2) if ok[k]}
        F12 = jb.metrics_between(psi[1]["P"], psi[2]["P"], cs) if g2 else None
        res["regions"] = {"F01": F01, "F12": F12, "A": {f"A{k}": A.get(k) for k in (0, 1, 2)}}
        for M in METRICS:
            f01, a0, a1 = F01["core"][M], A[0]["core"][M], A[1]["core"][M]
            if g2:
                f12, a2 = F12["core"][M], A[2]["core"][M]
                iq = inequalities(f01, f12, a0, a1, a2)
            else:
                f12 = a2 = None
                iq = ineq01(f01, a0, a1)
            res["metrics"][M] = {"F01": f01, "F12": f12, "A0": a0, "A1": a1, "A2": a2, "inequalities": iq, "state": metric_state(iq, g2)}
    else:
        for M in METRICS:
            res["metrics"][M] = {"state": "NOT_CLASSIFIED", "reason": f"failure {fail}"}
    st = [res["metrics"][M]["state"] for M in METRICS]
    if fail:
        res["overall"] = fail
    elif all(s == "NONCORE_REFINEMENT_DECREASE_OBSERVED" for s in st):
        res["overall"] = "NONCORE_REFINEMENT_DECREASE_OBSERVED"
    elif all(res["metrics"][M]["inequalities"]["ineq1"]["holds"] for M in METRICS):
        res["overall"] = "NONCORE_REFINEMENT_SENSITIVITY_ONLY"
    elif all(s == "NO_RESOLVABLE_NONCORE_CHANGE" for s in st):
        res["overall"] = "NO_RESOLVABLE_NONCORE_CHANGE"
    else:
        res["overall"] = "INCONCLUSIVE"
    res["G2_state"] = gstate.get(2)
    res["decrease_test_evaluated"] = bool(fail is None and g2)
    return res


# ---------------------------------------------------------------- artifacts and the full analysis
def g0_common_set(e6a_l5):
    P0 = e6a_l5["points_um_f32"][:, :2]
    return jb.CommonSet({3: P0, 4: P0, 5: P0}, e6a_l5["NodeVolume"], e6a_l5["x"], e6a_l5["y"])


def load_g_run(out_dir, k, tag, problems):
    """Returns (record, init Potential, final arrays); integrity problems are appended, never swallowed (as E6C load_run)."""
    name, cid = f"run_G{k}_{tag}", f"G{k}-{tag}"
    jp = os.path.join(out_dir, f"{name}.json")
    if not os.path.exists(jp):
        problems.append(f"{name}.json missing")
        return None, None, None
    rec = json.load(open(jp, encoding="utf-8"))
    ip, fp = os.path.join(out_dir, f"{name}_init.npz"), os.path.join(out_dir, f"{name}_final.npz")
    init = fin = None
    if rec.get("status") in ("OK", "INITIALIZATION_CONTRACT_FAIL"):
        if not os.path.exists(ip):
            problems.append(f"{name}_init.npz missing")
        else:
            a = jb.load_npz(ip)
            t = a.get("snapshot_call_id")
            if t is None or str(np.asarray(t).reshape(-1)[0]) != f"{cid}-init":
                problems.append(f"{cid}: init npz tag mismatch")
            elif jb.sha_arr(a["Potential"]) != rec.get("init_sha256"):
                problems.append(f"{cid}: init npz sha256 mismatch")
            else:
                init = a["Potential"]
    if rec.get("status") != "OK":
        return rec, init, None
    if rec.get("solve_count") != 1:
        problems.append(f"{cid}: solve_count {rec.get('solve_count')} != 1")
    if not os.path.exists(fp):
        problems.append(f"{name}_final.npz missing")
    else:
        a = jb.load_npz(fp)
        pr = jb.verify_state_artifact(rec.get("snapshot"), a, cid)
        problems.extend(pr)
        fin = None if pr else a
    return rec, init, fin


def _solver_rec(rec):
    return jc._solver_rec(rec)


def analyze_dir(out_dir, e6a_out, e6c_out, flags=None):
    """Judge an E6D output directory (on the runner and again locally on the downloaded artifacts)."""
    flags = dict(flags or {})
    problems = list(flags.get("artifact_problems", []))
    L5 = jb.load_npz(os.path.join(e6a_out, "level_L5.npz"))
    P0 = L5["points_um_f32"][:, :2]
    cs = g0_common_set(L5)
    psi, gstate, runs_all, cons, gauss, readback, mesh = {}, {}, {}, {}, {}, {}, {}
    # ---- G0: E6C L5-P / L5-Q (reused, not re-solved)
    psi[0], g0runs = {}, {}
    for t in TAGS:
        rec = json.load(open(os.path.join(e6c_out, f"run_L5_{t}.json"), encoding="utf-8"))
        fin = jb.load_npz(os.path.join(e6c_out, f"run_L5_{t}_final.npz"))
        pr = jb.verify_state_artifact(rec.get("snapshot"), fin, f"L5-{t}")
        problems.extend(pr)
        g0runs[t] = {"status": None if rec.get("status") == "OK" else rec.get("status"), "solve": _solver_rec(rec),
                     "consistency_ok": bool(not pr and all(np.isfinite(fin[a]).all() for a in jb.REQUIRED_STATE_ARRAYS))}
        psi[0][t] = fin["Potential"] if not pr else None
    gstate[0] = g_state("OK", g0runs)
    runs_all["G0"] = g0runs
    # ---- G1, G2
    for k in GS:
        psi[k] = {t: None for t in TAGS}
        mp = os.path.join(out_dir, f"mesh_G{k}.json")
        if not os.path.exists(mp):
            problems.append(f"mesh_G{k}.json missing")
            gstate[k] = "ARTIFACT_INCOMPLETE"
            continue
        mrec = json.load(open(mp, encoding="utf-8"))
        if mrec.get("status") == "RESOURCE_PREFLIGHT_FAIL":
            gstate[k], mesh[f"G{k}"] = "RESOURCE_PREFLIGHT_FAIL", {"status": "RESOURCE_PREFLIGHT_FAIL"}
            continue
        mst, why = mesh_state(mrec.get("checks") or {})
        if mrec.get("status") not in ("OK", "GATE_FAIL"):
            mst = mrec.get("status") or "ARTIFACT_INCOMPLETE"
            problems.append(f"G{k} mesh stage status {mrec.get('status')}")
        mesh[f"G{k}"] = {"state": mst, "failed_checks": why}
        runs = {}
        if mst == "OK":
            st = jb.load_npz(os.path.join(out_dir, f"mesh_G{k}_static.npz"))
            gp = jb.load_npz(os.path.join(out_dir, f"mesh_G{k}.npz"))["points_um_f32"]
            idx = node_index(P0, gp)
            loaded = {t: load_g_run(out_dir, k, t, problems) for t in TAGS}
            recP, recQ = loaded["P"][0], loaded["Q"][0]
            if recP and recQ and recP.get("process_id") == recQ.get("process_id"):
                problems.append(f"G{k}: P and Q ran in the same process")
            for t in TAGS:
                rec, init, fin = loaded[t]
                runs[t] = {"status": "MISSING" if rec is None else (None if rec.get("status") == "OK" else rec.get("status")),
                           "solve": _solver_rec(rec), "consistency_ok": None}
            if recP and recQ and recP.get("status") == "OK" and recQ.get("status") == "OK":
                ip = jc.check_initialization(recQ, loaded["P"][1], loaded["Q"][1], st["x"])
                if ip:
                    runs["Q"]["status"], runs["Q"]["init_problems"] = "INITIALIZATION_CONTRACT_FAIL", ip
            xs = st["x"]
            cm = (xs == xs.min()) | (xs == xs.max())
            for t in TAGS:
                rec, init, fin = loaded[t]
                if rec is None or fin is None:
                    continue
                c = {"finite_ok": all(bool(np.isfinite(fin[a]).all()) for a in jb.REQUIRED_STATE_ARRAYS),
                     "identity_ok": bool((rec.get("identity") or {}).get("ok")), "core_doping_equal_G0": rec.get("core_doping_equal_G0")}
                if c["finite_ok"]:
                    psi[k][t] = fin["Potential"][idx]
                    c["y_uniform_reported_only"] = cs.y_spread(psi[k][t])
                runs[t]["consistency_ok"] = bool(c["finite_ok"] and c["identity_ok"] and c["core_doping_equal_G0"] is True)
                cons[f"G{k}-{t}"] = c
                eq = rec.get("edge_arrays_equal_mesh_stage") or {}
                if c["finite_ok"] and all(eq.get(a) for a in ("n0", "n1", "EdgeCouple", "EdgeLength")):
                    gauss[f"G{k}-{t}"] = {"state_used": f"{t} final", **jb.gauss_diagnostic(
                        st["edge_n0"], st["edge_n1"], st["EdgeCouple"], fin["PotentialEdgeFlux"], st["NodeVolume"],
                        fin["PotentialIntrinsicCharge"], cm, xs, st["y"])}
                else:
                    gauss[f"G{k}-{t}"] = {"states": ["DIAG_INVALID_NOT_COMPUTED"]}
                readback[f"G{k}-{t}"] = {"xmin": float(np.mean(fin["Potential"][xs == xs.min()])),
                                         "xmax": float(np.mean(fin["Potential"][xs == xs.max()]))}
        gstate[k] = g_state(mst, runs)
        runs_all[f"G{k}"] = runs
        for t in TAGS:
            if gstate[k] != "OK":
                psi[k][t] = None                                           # never used when the level is not valid
    flags["artifact_problems"] = problems
    judged = judge(gstate, psi, cs, flags)
    return {"judgement": judged, "mesh_states": mesh, "runs": runs_all, "consistency": cons, "gauss_diagnostic": gauss,
            "contact_readback": readback, "descriptive_E6C_D45": descriptive_d45(psi, e6a_out, e6c_out, out_dir, gstate),
            "artifact_problems": problems}


def descriptive_d45(psi, e6a_out, e6c_out, out_dir, gstate):
    """PLAN 5: F01 / F12 on E6C's own D45 definition (L3 common nodes, L3 weights, h_3 segments), with D45 recomputed; no threshold."""
    try:
        e6a = {L: jb.load_npz(os.path.join(e6a_out, f"level_L{L}.npz")) for L in (3, 4, 5)}
        cs3 = jb.CommonSet({L: e6a[L]["points_um_f32"][:, :2] for L in (3, 4, 5)}, e6a[3]["NodeVolume"], e6a[3]["x"], e6a[3]["y"])
        pP = {L: jb.load_npz(os.path.join(e6c_out, f"run_L{L}_P_final.npz"))["Potential"] for L in (4, 5)}
        D45 = jb.metrics_between(pP[4][cs3.idx[4]], pP[5][cs3.idx[5]], cs3)["core"]
        i30 = node_index(e6a[3]["points_um_f32"], e6a[5]["points_um_f32"])       # L3 nodes in G0 (= L5) order
        out = {"D45_E6C_definition": D45}
        if psi.get(0, {}).get("P") is not None and psi.get(1, {}).get("P") is not None and gstate.get(1) == "OK":
            F01 = jb.metrics_between(psi[0]["P"][i30], psi[1]["P"][i30], cs3)["core"]
            out["F01_E6C_definition"] = F01
            out["F01_over_D45"] = {M: F01[M] / D45[M] for M in METRICS}
            if psi.get(2, {}).get("P") is not None and gstate.get(2) == "OK":
                F12 = jb.metrics_between(psi[1]["P"][i30], psi[2]["P"][i30], cs3)["core"]
                out["F12_E6C_definition"] = F12
                out["F12_over_D45"] = {M: F12[M] / D45[M] for M in METRICS}
        out["note"] = "descriptive only; no threshold attached"
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "NOT_COMPUTED", "error": repr(e)[:300]}
