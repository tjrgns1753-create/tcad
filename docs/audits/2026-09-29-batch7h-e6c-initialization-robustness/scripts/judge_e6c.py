"""Batch 7H-E6C verdict logic (pure numpy / Python; no DEVSIM, no ViennaPS). PLAN sections 2-7.
Reuses E6B's judge_e6b (common node set, four metrics, Gauss diagnostic, artifact-tag verification) read-only. Names: D34, D45 on the P
solutions; A3, A4, A5 = `observed_initialization_shift` between the P and Q solutions of one level."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-28-batch7h-e6b-poisson-junction-refinement", "scripts"))
import judge_e6b as jb  # noqa: E402  (E6B, read-only)

LEVELS = jb.LEVELS
METRICS = jb.METRICS
TAGS = ("P", "Q")
FAILURE_ORDER = ("ARTIFACT_INCOMPLETE", "INPUT_IDENTITY_FAIL", "IMPORT_IDENTITY_FAIL", "INITIALIZATION_CONTRACT_FAIL",
                 "RESOURCE_PREFLIGHT_FAIL", "POISSON_NOT_CONVERGED", "CONSISTENCY_FAIL")
N_CONC = 1.0e18


def contact_potentials(vt, ni, n=N_CONC):
    """PLAN 2: the contact boundary formula (simple_physics.py:31-32,211-213) at bias 0 for the doping on the two contact nodes."""
    root = np.sqrt(n * n + 4.0 * ni * ni)
    celec = 1e-10 + 0.5 * abs(+n + root)             # NetDoping = +N at the right contact (x_max)
    chole = 1e-10 + 0.5 * abs(-(-n) + root)          # NetDoping = -N at the left contact (x_min): the formula's -NetDoping term is +N
    return float(-vt * np.log(chole / ni)), float(+vt * np.log(celec / ni))      # V_left, V_right


def affine_init(x, vl, vr):
    """V_init(x) = V_left + (V_right - V_left) * (x - x_min) / (x_max - x_min), float64 on the device's own node x."""
    x = np.asarray(x, dtype=np.float64)
    xmin, xmax = np.min(x), np.max(x)
    return vl + (vr - vl) * (x - xmin) / (xmax - xmin)


def metric_state(disc):
    if not disc["all_finite"]:
        return "NONFINITE_INPUT"
    if not (disc["ineq1"]["holds"] and disc["ineq2"]["holds"]):
        return "INITIALIZATION_SHIFT_INDISTINGUISHABLE"
    if not disc["ineq3"]["holds"]:
        return "NO_REFINEMENT_TREND"
    return "INITIALIZATION_ROBUST_DECREASE_OBSERVED"


def finite_arr(a):
    return a is not None and bool(np.isfinite(a).all())


def judge(runs, psi, cs, flags):
    """runs[L][tag] = {"status": "OK"|fail label|None, "solve": {"ok","converged",...}|None, "consistency_ok": bool|None};
    psi[L][tag] = Potential on the common nodes (L3 order) or None; flags = {"artifact_problems": [...], "input_identity_ok",
    "resource_ok"}. Returns the classification and every number that could be computed."""
    res = {"gates": {}, "regions": {}, "metrics": {}}
    fail = None
    if flags.get("artifact_problems"):
        fail = "ARTIFACT_INCOMPLETE"
    elif not flags.get("input_identity_ok", True):
        fail = "INPUT_IDENTITY_FAIL"
    else:
        sts = [(runs.get(L, {}).get(t) or {}).get("status") for L in LEVELS for t in TAGS]
        for lab in ("IMPORT_IDENTITY_FAIL", "INITIALIZATION_CONTRACT_FAIL"):
            if lab in sts:
                fail = lab
                break
        if fail is None and not flags.get("resource_ok", True):
            fail = "RESOURCE_PREFLIGHT_FAIL"
    conv = {}
    for L in LEVELS:
        for t in TAGS:
            conv[(L, t)] = jb.primary_ok((runs.get(L, {}).get(t) or {}).get("solve"))
    res["gates"] = {f"L{L}-{t}": {"converged_ok": conv[(L, t)],
                                  "consistency_ok": (runs.get(L, {}).get(t) or {}).get("consistency_ok")} for L in LEVELS for t in TAGS}
    if fail is None and not all(conv.values()):
        fail = "POISSON_NOT_CONVERGED"
    if not cs.masks["core"].any():
        res["core_empty"] = True
        fail = fail or "CONSISTENCY_FAIL"
    if fail is None and not all(res["gates"][k]["consistency_ok"] is True for k in res["gates"]):
        fail = "CONSISTENCY_FAIL"
    # numbers: only from finite arrays of runs that converged; nothing is ever turned into 0
    okP = {L: psi.get(L, {}).get("P") is not None and finite_arr(psi[L]["P"]) and conv[(L, "P")] for L in LEVELS}
    D34 = D45 = None
    if all(okP.values()) and cs.masks["core"].any():
        Ps = {L: psi[L]["P"] for L in LEVELS}
        D34, D45 = jb.pair_diff(Ps, 3, 4, cs), jb.pair_diff(Ps, 4, 5, cs)
        res["regions"].update({"D34": D34, "D45": D45})
    A = {}
    for L in LEVELS:
        p, q = psi.get(L, {}).get("P"), psi.get(L, {}).get("Q")
        if conv[(L, "P")] and conv[(L, "Q")] and finite_arr(p) and finite_arr(q) and cs.masks["core"].any():
            A[L] = jb.metrics_between(p, q, cs)
        else:
            A[L] = None                                          # invalid A: never promoted to 0
    res["regions"]["A"] = {f"A{L}": A[L] for L in LEVELS}
    res["failure"] = fail
    for M in METRICS:
        if D34 is not None and all(A[L] is not None for L in LEVELS):
            disc = jb.discriminant(D34["core"][M], D45["core"][M], A[3]["core"][M], A[4]["core"][M], A[5]["core"][M])
            res["metrics"][M] = {"D34": D34["core"][M], "D45": D45["core"][M], "A3": A[3]["core"][M], "A4": A[4]["core"][M],
                                 "A5": A[5]["core"][M], "inequalities": disc, "state": "NOT_CLASSIFIED" if fail else metric_state(disc)}
        else:
            res["metrics"][M] = {"state": "NOT_CLASSIFIED", "reason": "an A or D is unavailable (non-converged, non-finite or missing run)"}
    if fail:
        res["overall"] = fail
    elif all(res["metrics"][M]["state"] == "INITIALIZATION_ROBUST_DECREASE_OBSERVED" for M in METRICS):
        res["overall"] = "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY"
    else:
        res["overall"] = "INCONCLUSIVE"
    return res


# ---------------------------------------------------------------- pure checks used by the worker (testable without DEVSIM)
UM = 1e-4


def import_identity(x, y, vol, el, contacts, regions, ref):
    """PLAN 3: node count and coordinates, the vertex-set MULTISET of the elements (not the count), NodeVolume, region, contacts by
    coordinate. `contacts` = {name: sorted node list}; `ref` = the E6A level npz arrays."""
    P32 = ref["points_um_f32"][:, :2]
    exp_xy = (P32 * UM).astype(float)                              # the production scaling expression (mesh_import.py:989)
    a, b = np.sort(ref["triangles"], axis=1), np.sort(el, axis=1)
    ia, ib = np.lexsort((a[:, 2], a[:, 1], a[:, 0])), np.lexsort((b[:, 2], b[:, 1], b[:, 0]))
    want = {"Si_xmin": set(np.where(x == x.min())[0].tolist()), "Si_xmax": set(np.where(x == x.max())[0].tolist())}
    idn = {"n_nodes": [int(len(x)), int(len(P32))], "nodes_equal": bool(len(x) == len(P32)),
           "xy_equal_scaled_construction": bool(len(x) == len(P32) and np.array_equal(x, exp_xy[:, 0]) and np.array_equal(y, exp_xy[:, 1])),
           "n_elements": [int(len(el)), int(len(ref["triangles"]))],
           "vertex_set_multiset_equal": bool(len(a) == len(b) and np.array_equal(a[ia], b[ib])),
           "NodeVolume_bit_equal_E6A": bool(len(vol) == len(ref["NodeVolume"]) and np.array_equal(vol, ref["NodeVolume"])),
           "regions": list(regions), "contacts": {c: len(n) for c, n in contacts.items()},
           "contacts_by_coordinate_ok": bool(sorted(contacts) == ["Si_xmax", "Si_xmin"]
                                              and all(set(contacts[c]) == want[c] and len(contacts[c]) == 101 for c in want))}
    idn["ok"] = bool(idn["nodes_equal"] and idn["xy_equal_scaled_construction"] and idn["n_elements"][0] == idn["n_elements"][1]
                     and idn["vertex_set_multiset_equal"] and idn["NodeVolume_bit_equal_E6A"] and idn["regions"] == ["Si"]
                     and idn["contacts_by_coordinate_ok"])
    return idn


def doping_check(x, donors, acceptors, nets):
    """PLAN 3: x = 0 nodes carry Donors = Acceptors = 1e18 and NetDoping = 0."""
    m0 = x == 0.0
    return bool(m0.any() and set(donors[m0]) == {N_CONC} and set(acceptors[m0]) == {N_CONC} and set(nets[m0]) == {0.0})


def init_precheck(vt, ni, vl, vr, intended, n_right, n_left, default_init):
    """PLAN 2 pre-conditions of the Q initial potential; returns a list of reasons (empty = ok)."""
    why = []
    if not np.isfinite([vt, ni, vl, vr]).all() or not np.isfinite(intended).all():
        why.append("non-finite V_t, n_i, contact potential or intended array")
    if n_right != N_CONC or n_left != -N_CONC:
        why.append("contact-node NetDoping is not +1e18 at x_max and -1e18 at x_min")
    if not (vl < vr):
        why.append("V_left is not below V_right")
    if len(default_init) != len(intended) or not bool((np.abs(intended - default_init) > 0).any()):
        why.append("intended Q array does not differ from the default initial Potential at any node")
    return why


def init_contract(precheck_reasons, intended, readback):
    """PLAN 2: the readback after set_node_values must be bit-equal to the intended array."""
    equal = bool(len(readback) == len(intended) and np.array_equal(readback, intended))
    return {"readback_bit_equal_intended": equal, "precheck_reasons": list(precheck_reasons),
            "contract_ok": bool(equal and not precheck_reasons)}


# ---------------------------------------------------------------- run records and artifacts
def _solver_rec(rec):
    c = (rec or {}).get("solve")
    if c is None:
        return None
    return {"ok": bool(c.get("ok")), "converged": c.get("converged"), "final_rel": c.get("final_device_relative_error"),
            "n_iterations": c.get("n_iterations"), "error": c.get("error")}


def check_initialization(recQ, initP, initQ, xcm):
    """Independent re-check of the initialization contract from the saved arrays (PLAN 2). Returns a list of problems."""
    prob = []
    ini = (recQ or {}).get("initialization") or {}
    vl, vr = ini.get("V_left"), ini.get("V_right")
    if not (jb.finite(vl) and jb.finite(vr)):
        return ["Q: V_left / V_right missing or non-finite"]
    want = affine_init(xcm, vl, vr)
    if initQ is None or initP is None:
        return ["init arrays missing"]
    if len(initQ) != len(want) or not np.array_equal(initQ, want):
        prob.append("Q initial Potential readback is not bit-equal to the intended affine array")
    if len(initP) != len(initQ) or not bool((np.abs(initQ - initP) > 0).any()):
        prob.append("Q initial Potential does not differ from P's initial Potential at any node")
    return prob


def load_run(out_dir, L, tag, problems):
    """Returns (record, init array, final arrays) with integrity checks; problems are appended, never swallowed."""
    jp = os.path.join(out_dir, f"run_L{L}_{tag}.json")
    if not os.path.exists(jp):
        problems.append(f"run_L{L}_{tag}.json missing")
        return None, None, None
    rec = json.load(open(jp, encoding="utf-8"))
    if rec.get("status") != "OK":
        return rec, None, None
    init = fin = None
    ip, fp = os.path.join(out_dir, f"run_L{L}_{tag}_init.npz"), os.path.join(out_dir, f"run_L{L}_{tag}_final.npz")
    if not os.path.exists(ip):
        problems.append(f"run_L{L}_{tag}_init.npz missing")
    else:
        a = jb.load_npz(ip)
        t = a.get("snapshot_call_id")
        if t is None or str(np.asarray(t).reshape(-1)[0]) != f"L{L}-{tag}-init":
            problems.append(f"L{L}-{tag}: init npz tag mismatch")
        elif jb.sha_arr(a["Potential"]) != rec.get("init_sha256"):
            problems.append(f"L{L}-{tag}: init npz sha256 mismatch")
        else:
            init = a["Potential"]
    if rec.get("solve_count") != 1:
        problems.append(f"L{L}-{tag}: solve_count {rec.get('solve_count')} != 1")
    if not os.path.exists(fp):
        problems.append(f"run_L{L}_{tag}_final.npz missing")
    else:
        a = jb.load_npz(fp)
        probs = jb.verify_state_artifact(rec.get("snapshot"), a, f"L{L}-{tag}")
        problems.extend(probs)
        fin = None if probs else a
    return rec, init, fin


def analyze_dir(out_dir, e6a_dir, e6b_dir=None, flags=None):
    """Judge a completed E6C output directory (used on the runner and again locally on the downloaded artifacts)."""
    flags = dict(flags or {})
    problems = list(flags.get("artifact_problems", []))
    e6a = {L: jb.load_npz(os.path.join(e6a_dir, f"level_L{L}.npz")) for L in LEVELS}
    pts = {L: e6a[L]["points_um_f32"][:, :2] for L in LEVELS}
    cs = jb.CommonSet(pts, e6a[3]["NodeVolume"], e6a[3]["x"], e6a[3]["y"])
    runs, psi, gauss, inits, cons, readback, repro = {}, {}, {}, {}, {}, {}, {}
    skipped = set(flags.get("skipped_levels", []))
    for L in LEVELS:
        runs[L], psi[L] = {}, {}
        if L in skipped:
            for t in TAGS:
                runs[L][t], psi[L][t] = {"status": "RESOURCE_PREFLIGHT_FAIL", "solve": None}, None
            continue
        loaded = {t: load_run(out_dir, L, t, problems) for t in TAGS}
        for t in TAGS:
            rec, init, fin = loaded[t]
            runs[L][t] = {"status": None if rec is None else (None if rec.get("status") == "OK" else rec.get("status")),
                          "solve": _solver_rec(rec), "consistency_ok": None}
            psi[L][t] = None
            if rec is None:
                runs[L][t]["status"] = "MISSING"
        # cross-run integrity: separate processes, and (for a valid Q) the initialization contract
        recP, recQ = loaded["P"][0], loaded["Q"][0]
        if recP and recQ and recP.get("process_id") == recQ.get("process_id"):
            problems.append(f"L{L}: P and Q ran in the same process")
        if recP and recQ and recQ.get("status") == "OK" and recP.get("status") == "OK":
            xcm = e6a[L]["x"]
            ip = check_initialization(recQ, loaded["P"][1], loaded["Q"][1], xcm)
            if ip:
                runs[L]["Q"]["status"] = "INITIALIZATION_CONTRACT_FAIL"
                runs[L]["Q"]["init_problems"] = ip
        for t in TAGS:
            rec, init, fin = loaded[t]
            if rec is None or fin is None:
                continue
            psi[L][t] = fin["Potential"][cs.idx[L]]
            inits[f"L{L}-{t}"] = {"init_sha256": rec.get("init_sha256"), "n": None if init is None else int(len(init)),
                                  "min": None if init is None else float(np.min(init)), "max": None if init is None else float(np.max(init)),
                                  "initialization": rec.get("initialization")}
            c = {"finite_ok": all(bool(np.isfinite(fin[k]).all()) for k in jb.REQUIRED_STATE_ARRAYS)}
            if c["finite_ok"]:
                c["y_uniform"] = cs.y_spread(psi[L][t])
                c["y_uniform_ok"] = all(v is not None and v <= jb.Y_UNIFORM_MAX_V for v in c["y_uniform"].values())
            runs[L][t]["consistency_ok"] = bool(c["finite_ok"] and c.get("y_uniform_ok"))
            cons[f"L{L}-{t}"] = c
            xs = e6a[L]["x"]
            cm = (xs == xs.min()) | (xs == xs.max())
            eq = rec.get("edge_arrays_equal_E6A") or {}
            if all(eq.get(k) for k in ("n0", "n1", "EdgeCouple", "EdgeLength")) and c["finite_ok"]:
                gauss[f"L{L}-{t}"] = {"state_used": f"{t} final", **jb.gauss_diagnostic(
                    e6a[L]["edge_n0"], e6a[L]["edge_n1"], e6a[L]["EdgeCouple"], fin["PotentialEdgeFlux"], e6a[L]["NodeVolume"],
                    fin["PotentialIntrinsicCharge"], cm, xs, e6a[L]["y"])}
            else:
                gauss[f"L{L}-{t}"] = {"states": ["DIAG_INVALID_NOT_COMPUTED"], "reason": "edge arrays not equal to E6A or non-finite"}
            readback[f"L{L}-{t}"] = {"xmin": float(np.mean(fin["Potential"][xs == xs.min()])), "xmax": float(np.mean(fin["Potential"][xs == xs.max()]))}
            if t == "P" and e6b_dir:                                   # separate reproducibility diagnostic, never in the verdict
                bp = os.path.join(e6b_dir, f"level_L{L}_state_P.npz")
                if os.path.exists(bp):
                    old = jb.load_npz(bp)["Potential"]
                    repro[f"L{L}"] = {"potential_bit_equal_all_nodes": bool(np.array_equal(old, fin["Potential"])),
                                      "max_abs_diff_all_nodes": float(np.max(np.abs(old - fin["Potential"]))) if len(old) == len(fin["Potential"]) else None,
                                      "core_metrics": (jb.metrics_between(old[cs.idx[L]], psi[L]["P"], cs)["core"]
                                                       if len(old) == len(fin["Potential"]) else None)}
    flags["artifact_problems"] = problems
    judged = judge(runs, psi, cs, flags)
    # a contract failure discovered from the saved arrays is a state of its own (never a silent pass)
    if any(runs[L][t].get("status") == "INITIALIZATION_CONTRACT_FAIL" for L in LEVELS for t in TAGS) and not problems:
        judged = judge(runs, psi, cs, flags)
    return {"judgement": judged, "gauss_diagnostic": gauss, "initialization": inits, "consistency": cons, "contact_readback": readback,
            "e6b_P_reproducibility_diagnostic": repro, "artifact_problems": problems}
