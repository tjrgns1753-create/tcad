"""Batch 7H-E6B verdict logic (pure numpy / Python; no DEVSIM, no ViennaPS). PLAN Rev.3 sections 3, 6.6, 7, 8, 9.
Everything here is testable on synthetic numbers and fake artifacts (synthetic_e6b_test.py). Names follow the PLAN:
D34(M), D45(M), S3/S4/S5(M) (`observed_solver_shift`), G_L (`observed_reference_gap`), A67 (`observed_reference_refinement_change`)."""
import hashlib
import json
import os

import numpy as np

LEVELS = (3, 4, 5)
METRICS = ("psiLinf", "psiL2", "ExLinf", "ExRMS")
PSI_METRICS = ("psiLinf", "psiL2")
REQUIRED_STATE_ARRAYS = ("Potential", "IntrinsicElectrons", "IntrinsicHoles", "IntrinsicCharge",
                         "PotentialIntrinsicCharge", "ElectricField", "PotentialEdgeFlux")
Y_UNIFORM_MAX_V = 1e-6                 # PLAN 7 (a convention inherited from 7H-E5 PLAN section 5, not derived)
ELIGIBLE_FRACTION = 1e-3               # PLAN 7 eligible-set threshold
X01_UM = float(np.float32(0.1))        # S0's own float32 0.1 um line
X02_UM = float(np.float32(0.2))
CONTACT_ABS_X_UM = 5.0

FAILURE_ORDER = ("ARTIFACT_INCOMPLETE", "INPUT_IDENTITY_FAIL", "IMPORT_IDENTITY_FAIL", "RESOURCE_PREFLIGHT_FAIL",
                 "POISSON_NOT_CONVERGED", "SOLVER_CONTROL_INVALID", "CONSISTENCY_FAIL")


class PairIndexError(ValueError):
    """A level pair other than (3,4) for D34 or (4,5) for D45 was requested (blocks index-swap false passes)."""


class NonNestedError(ValueError):
    pass


def sha_arr(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def finite(v):
    return v is not None and isinstance(v, (int, float)) and bool(np.isfinite(v))


# ---------------------------------------------------------------- common node set and metrics (PLAN 3)
class CommonSet:
    """The L3 nodes, which exist bit-identically (float32 construction coordinates) in L4 and L5 (PLAN 1 row 3)."""

    def __init__(self, pts, nv3, xcm3, ycm3):
        self.n = len(pts[3])
        self.idx = {}
        p3 = np.ascontiguousarray(pts[3], dtype=np.float32)
        k3 = self._keys(p3)
        for L in LEVELS:
            pl = np.ascontiguousarray(pts[L], dtype=np.float32)
            if L == 3:
                self.idx[L] = np.arange(self.n)
                continue
            kl = self._keys(pl)
            order = np.argsort(kl, kind="stable")
            sk = kl[order]
            pos = np.searchsorted(sk, k3)
            hit = (pos < len(sk)) & (sk[np.minimum(pos, len(sk) - 1)] == k3)
            if not bool(hit.all()):
                raise NonNestedError(f"L3 nodes missing in L{L}: {int((~hit).sum())}")
            self.idx[L] = order[pos]
        ax = np.abs(p3[:, 0].astype(np.float64))
        self.contact = ax == CONTACT_ABS_X_UM
        self.masks = {"core": (~self.contact) & (ax <= X01_UM),
                      "transition": (~self.contact) & (ax > X01_UM) & (ax < X02_UM),
                      "outer": (~self.contact) & (ax >= X02_UM)}
        self.w = np.asarray(nv3, dtype=np.float64)
        self.xcm = np.asarray(xcm3, dtype=np.float64)
        self.ycm = np.asarray(ycm3, dtype=np.float64)
        ybits = p3[:, 1].view(np.uint32)
        order = np.lexsort((self.xcm, ybits))
        yb = ybits[order]
        same = yb[1:] == yb[:-1]
        i, j = order[:-1][same], order[1:][same]
        keep = self.masks["core"][i] & self.masks["core"][j]
        self.seg_i, self.seg_j = i[keep], j[keep]
        self.seg_dx = self.xcm[self.seg_j] - self.xcm[self.seg_i]
        self.ux, self.xinv = np.unique(self.xcm, return_inverse=True)

    @staticmethod
    def _keys(p):
        b = np.ascontiguousarray(p[:, :2]).view(np.uint32).reshape(-1, 2)
        return (b[:, 0].astype(np.uint64) << np.uint64(32)) | b[:, 1].astype(np.uint64)

    def ex(self, psi):
        """Signed Ex = -(psi_j - psi_i)/(x_j - x_i) [V/cm] on the fixed core segments."""
        return -(psi[self.seg_j] - psi[self.seg_i]) / self.seg_dx

    def y_spread(self, psi):
        out = {}
        for r, m in self.masks.items():
            lo = np.full(len(self.ux), np.inf)
            hi = np.full(len(self.ux), -np.inf)
            np.minimum.at(lo, self.xinv[m], psi[m])
            np.maximum.at(hi, self.xinv[m], psi[m])
            used = np.isfinite(lo)
            out[r] = float(np.max(hi[used] - lo[used])) if used.any() else None
        return out


def metrics_between(psiA, psiB, cs):
    """PLAN 3 metric definitions; regions: core (all four), transition/outer (psi metrics only)."""
    d = psiA - psiB
    out = {}
    for r, m in cs.masks.items():
        if not m.any():
            out[r] = None
            continue
        dd, w = d[m], cs.w[m]
        out[r] = {"psiLinf": float(np.max(np.abs(dd))), "psiL2": float(np.sqrt(np.sum(w * dd * dd) / np.sum(w)))}
    de = cs.ex(psiA) - cs.ex(psiB)
    out["core"]["ExLinf"] = float(np.max(np.abs(de)))
    out["core"]["ExRMS"] = float(np.sqrt(np.mean(de * de)))
    return out


def pair_diff(psiP, a, b, cs):
    """D34 = M(L3-P, L4-P), D45 = M(L4-P, L5-P). Any other (or reversed) pair is refused."""
    if (a, b) not in ((3, 4), (4, 5)):
        raise PairIndexError(f"level pair ({a},{b}) is not (3,4) or (4,5)")
    return metrics_between(psiP[a], psiP[b], cs)


def discriminant(D34, D45, S3, S4, S5):
    """PLAN 3 / 9: three inequalities with their actual left/right values."""
    vals = (D34, D45, S3, S4, S5)
    ok = all(finite(v) for v in vals)
    rows = (("D34 > S3+S4", D34, None if not ok else S3 + S4),
            ("D45 > S4+S5", D45, None if not ok else S4 + S5),
            ("D34-D45 > S3+2*S4+S5", None if not ok else D34 - D45, None if not ok else S3 + 2 * S4 + S5))
    out = {}
    for k, (name, l, r) in enumerate(rows, 1):
        out[f"ineq{k}"] = {"expr": name, "lhs": l, "rhs": r, "holds": bool(ok and l > r)}
    out["all_finite"] = ok
    return out


def metric_state(disc):
    if not disc["all_finite"]:
        return "NONFINITE_INPUT"
    if not (disc["ineq1"]["holds"] and disc["ineq2"]["holds"]):
        return "SOLVER_NOISE_INDISTINGUISHABLE"
    if not disc["ineq3"]["holds"]:
        return "NO_REFINEMENT_TREND"
    return "trend observed"


# ---------------------------------------------------------------- solver-record gates (PLAN 7)
def primary_ok(P):
    return bool(P and P.get("ok") and P.get("converged") is True)


def control_valid(P, C):
    """Fail-closed: a control that is missing, errored, not converged, non-finite, or worse than its primary is invalid."""
    if C is None:
        return False, "C_MISSING"
    if not C.get("ok") or C.get("converged") is not True:
        return False, "C_NOT_CONVERGED_OR_ERROR"
    fc, fp = C.get("final_rel"), (P or {}).get("final_rel")
    if not (finite(fc) and finite(fp)):
        return False, "C_NONFINITE_RESIDUAL"
    if fc > fp:
        return False, "C_RESIDUAL_WORSE_THAN_PRIMARY"
    return True, None


# ---------------------------------------------------------------- Gauss diagnostic (PLAN 7, Rev.3)
def gauss_diagnostic(n0, n1, EC, PEF, NV, PIC, contact_mask, x, y):
    """R_i = sum_j sign(i,j) PEF*EC + NV_i*PIC_i with sign +1 at n0 and -1 at n1 (a HYPOTHESIS, PLAN 7); NodeVolume and
    EdgeCouple applied once each. Reported |R_i|/s_i on the non-contact eligible set only; contact nodes go to a separate
    block. INVALID states give null ratios; nothing is ever turned into 0 or a pass."""
    n = len(NV)
    n0, n1 = np.asarray(n0, dtype=np.int64), np.asarray(n1, dtype=np.int64)
    F = PEF * EC
    charge = NV * PIC

    def resid(flux, ch):
        return np.bincount(n0, flux, minlength=n) - np.bincount(n1, flux, minlength=n) + ch

    with np.errstate(all="ignore"):
        s = np.bincount(n0, np.abs(F), minlength=n) + np.bincount(n1, np.abs(F), minlength=n) + np.abs(charge)
        R = {"correct": resid(F, charge), "edgecouple_omitted": resid(PEF, charge),
             "edgecouple_twice": resid(F * EC, charge), "charge_sign_flipped": resid(F, -charge)}
    nc = ~np.asarray(contact_mask, dtype=bool)
    out = {"assumed_sign": "+1 at edge n0, -1 at edge n1 (hypothesis)", "n_noncontact": int(nc.sum()), "states": [],
           "ratios_max_abs": {v: None for v in R}}
    # contact block (separate, never mixed into the bulk ratio)
    cm = ~nc
    with np.errstate(all="ignore"):
        cont = {}
        for v, r in R.items():
            ok = cm & np.isfinite(r) & np.isfinite(s) & (s > 0)
            cont[v] = {"n": int(cm.sum()), "n_valid": int(ok.sum()),
                       "max_abs_ratio": float(np.max(np.abs(r[ok]) / s[ok])) if ok.any() else None,
                       "max_abs_R": float(np.max(np.abs(r[cm & np.isfinite(r)]))) if (cm & np.isfinite(r)).any() else None}
    out["contact_residual_diagnostic"] = cont
    nonfinite = (not np.isfinite(s[nc]).all()) or any((not np.isfinite(r[nc]).all()) for r in R.values())
    if out["n_noncontact"] == 0:
        out["states"].append("DIAG_INVALID_NO_ELIGIBLE_NODES")
        out.update({"n_eligible": 0, "n_eligible_on_x0": 0, "n_eligible_top": 0, "n_eligible_bottom": 0})
        return out
    if nonfinite:
        out["states"].append("DIAG_INVALID_NONFINITE")
    smax = float(np.max(s[nc])) if not nonfinite else None
    if smax is not None and smax == 0.0:
        out["states"].append("DIAG_INVALID_MAX_S_ZERO")
    if any(st.startswith("DIAG_INVALID") for st in out["states"]):
        out.update({"n_eligible": None, "n_eligible_on_x0": None, "n_eligible_top": None, "n_eligible_bottom": None})
        return out
    elig = nc & (s >= ELIGIBLE_FRACTION * smax)
    out["n_eligible"] = int(elig.sum())
    if out["n_eligible"] == 0:
        out["states"].append("DIAG_INVALID_NO_ELIGIBLE_NODES")
        out.update({"n_eligible_on_x0": 0, "n_eligible_top": 0, "n_eligible_bottom": 0})
        return out
    out["n_eligible_on_x0"] = int((elig & (x == 0.0)).sum())
    out["n_eligible_top"] = int((elig & (y == np.max(y))).sum())
    out["n_eligible_bottom"] = int((elig & (y == np.min(y))).sum())
    if out["n_eligible_on_x0"] == 0:
        out["states"].append("DIAG_DEGENERATE_NO_X0_REPRESENTATIVE")
    if out["n_eligible_top"] == 0:
        out["states"].append("DIAG_DEGENERATE_NO_TOP_REPRESENTATIVE")
    if out["n_eligible_bottom"] == 0:
        out["states"].append("DIAG_DEGENERATE_NO_BOTTOM_REPRESENTATIVE")
    for v, r in R.items():
        out["ratios_max_abs"][v] = float(np.max(np.abs(r[elig]) / s[elig]))
    return out


# ---------------------------------------------------------------- artifact integrity (PLAN 6.6)
def verify_state_artifact(rec, arrays, expected_call_id):
    """rec: JSON snapshot record {"call_id", "array_sha256"}; arrays: dict from the npz incl. `snapshot_call_id`.
    Returns a list of problems; any problem => ARTIFACT_INCOMPLETE before any judgement."""
    prob = []
    if rec is None:
        return [f"{expected_call_id}: snapshot record missing"]
    if rec.get("call_id") != expected_call_id:
        prob.append(f"{expected_call_id}: JSON call_id {rec.get('call_id')!r}")
    tag = arrays.get("snapshot_call_id")
    if tag is None or str(np.asarray(tag).reshape(-1)[0]) != expected_call_id:
        prob.append(f"{expected_call_id}: npz snapshot_call_id {None if tag is None else str(np.asarray(tag).reshape(-1)[0])!r}")
    for name in REQUIRED_STATE_ARRAYS:
        if name not in arrays:
            prob.append(f"{expected_call_id}: array {name} missing")
        elif sha_arr(arrays[name]) != (rec.get("array_sha256") or {}).get(name):
            prob.append(f"{expected_call_id}: sha256 mismatch for {name}")
    return prob


# ---------------------------------------------------------------- run-level judgement (PLAN 9)
def judge(levels, psi, cs, run_flags):
    """levels[L] = {"status": None|fail label, "P": rec, "C": rec|None, "consistency_ok": bool|None};
    psi[L] = {"P": array|None, "C": array|None} on the common nodes (L3 order); run_flags = {"artifact_problems": [...],
    "input_identity_ok": bool, "resource_ok": bool}. Returns the classification and every reported number."""
    res = {"gates": {}, "metrics": {}, "regions": {}}
    fail = None
    if run_flags.get("artifact_problems"):
        fail = "ARTIFACT_INCOMPLETE"
    elif not run_flags.get("input_identity_ok", True):
        fail = "INPUT_IDENTITY_FAIL"
    else:
        for L in LEVELS:
            st = (levels.get(L) or {}).get("status")
            if st in ("INPUT_IDENTITY_FAIL", "IMPORT_IDENTITY_FAIL"):
                fail = st
                break
        if fail is None and not run_flags.get("resource_ok", True):
            fail = "RESOURCE_PREFLIGHT_FAIL"
    gate = {}
    for L in LEVELS:
        lv = levels.get(L) or {}
        pok = primary_ok(lv.get("P"))
        cok, creason = control_valid(lv.get("P"), lv.get("C")) if pok else (False, "P_NOT_CONVERGED")
        gate[L] = {"primary_ok": pok, "control_valid": cok, "control_reason": creason,
                   "consistency_ok": lv.get("consistency_ok")}
    res["gates"] = {f"L{L}": g for L, g in gate.items()}
    if fail is None and not all(g["primary_ok"] for g in gate.values()):
        fail = "POISSON_NOT_CONVERGED"
    if fail is None and not all(g["control_valid"] for g in gate.values()):
        fail = "SOLVER_CONTROL_INVALID"
    if fail is None and not all(g["consistency_ok"] is True for g in gate.values()):
        fail = "CONSISTENCY_FAIL"
    # numbers are computed whenever the arrays exist (raw results are never discarded); S only where its control is valid
    have_P = all(psi.get(L, {}).get("P") is not None for L in LEVELS)
    D34 = D45 = None
    if have_P:
        D34, D45 = pair_diff({L: psi[L]["P"] for L in LEVELS}, 3, 4, cs), pair_diff({L: psi[L]["P"] for L in LEVELS}, 4, 5, cs)
        res["regions"] = {"D34": D34, "D45": D45}
    S = {}
    for L in LEVELS:
        if gate[L]["control_valid"] and psi.get(L, {}).get("P") is not None and psi[L].get("C") is not None:
            S[L] = metrics_between(psi[L]["P"], psi[L]["C"], cs)
        else:
            S[L] = None
    res["regions"]["S"] = {f"S{L}": S[L] for L in LEVELS}
    res["failure"] = fail
    for M in METRICS:
        if have_P and all(S[L] is not None for L in LEVELS):
            disc = discriminant(D34["core"][M], D45["core"][M], S[3]["core"][M], S[4]["core"][M], S[5]["core"][M])
            res["metrics"][M] = {"D34": D34["core"][M], "D45": D45["core"][M], "S3": S[3]["core"][M], "S4": S[4]["core"][M],
                                 "S5": S[5]["core"][M], "inequalities": disc,
                                 "state": "NOT_CLASSIFIED" if fail else metric_state(disc)}
        else:
            res["metrics"][M] = {"state": "NOT_CLASSIFIED", "reason": "controls invalid or arrays missing"}
    if fail:
        res["overall"] = fail
    elif all(res["metrics"][M]["state"] == "trend observed" for M in METRICS):
        res["overall"] = "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY"
    else:
        res["overall"] = "INCONCLUSIVE"
    return res


# ---------------------------------------------------------------- 1D reference states (PLAN 8, Rev.3)
def reference_assessment(ref, judged, psi2d, cs):
    """ref = {"usable": bool, "reason": str|None, "x": sorted 1D x (cm), "w": weights on those x, "R6P","R6C","R7P","R7C"};
    Returns observed quantities and per-metric / overall states by the PLAN's precedence. No bound, no 'floor absent'."""
    if not ref or not ref.get("usable"):
        return {"overall": "REFERENCE_1D_UNUSABLE", "reason": (ref or {}).get("reason"), "per_metric": {}}
    x1 = ref["x"]
    w1 = np.asarray(ref["w"], dtype=np.float64)

    def m1(a, b):
        d = a - b
        return {"psiLinf": float(np.max(np.abs(d))), "psiL2": float(np.sqrt(np.sum(w1 * d * d) / np.sum(w1)))}

    A67 = m1(ref["R6P"], ref["R7P"])
    S_R6, S_R7 = m1(ref["R6P"], ref["R6C"]), m1(ref["R7P"], ref["R7C"])
    pos = np.searchsorted(x1, cs.xcm)
    if not (pos < len(x1)).all() or not np.array_equal(x1[np.minimum(pos, len(x1) - 1)], cs.xcm):
        return {"overall": "REFERENCE_1D_UNUSABLE", "reason": "2D x-value not present bit-exactly in the 1D reference",
                "per_metric": {}}
    r7 = ref["R7P"][pos]
    G = {}
    for L in LEVELS:
        if psi2d.get(L, {}).get("P") is None:
            G[L] = None
            continue
        d = psi2d[L]["P"] - r7
        G[L] = {}
        for r, m in cs.masks.items():
            if not m.any():                       # never take the maximum of an empty region
                G[L][r] = None
                continue
            G[L][r] = {"psiLinf": float(np.max(np.abs(d[m]))), "psiL2": float(np.sqrt(np.sum(cs.w[m] * d[m] ** 2) / np.sum(cs.w[m])))}
    per = {}
    for M in PSI_METRICS:
        V = A67[M] + S_R7[M]
        info = {"A67": A67[M], "S_R6": S_R6[M], "S_R7": S_R7[M], "V": V}
        T = judged.get("overall") not in FAILURE_ORDER and judged["metrics"][M]["state"] == "trend observed"
        info["T"] = bool(T)
        if G[4] is not None and G[5] is not None:
            dG = G[4]["core"][M] - G[5]["core"][M]
            info.update({"G_L3": None if G[3] is None else G[3]["core"][M], "G_L4": G[4]["core"][M], "G_L5": G[5]["core"][M],
                         "Delta_G": dG, "W": judged_W(judged, M, S_R7[M])})
        else:
            info.update({"G_L5": None, "Delta_G": None, "W": None})
        if not T:
            info["state"], info["reason"] = "REFERENCE_INCONCLUSIVE", "T(M) false (2D trend not observed for this metric)"
        elif info["G_L5"] <= V:
            info["state"] = "REFERENCE_AGREEMENT_OBSERVED"
        elif info["Delta_G"] <= info["W"]:
            info["state"] = "OUTER_FLOOR_SUSPECTED"
        else:
            info["state"] = "REFERENCE_INCONCLUSIVE"
            info["reason"] = "gap still resolved as decreasing"
        per[M] = info
    states = {per[M]["state"] for M in PSI_METRICS}
    return {"overall": states.pop() if len(states) == 1 else "REFERENCE_INCONCLUSIVE", "per_metric": per,
            "G_all_regions": {f"L{L}": G[L] for L in LEVELS}, "reason": None}


def judged_W(judged, M, S_R7M):
    m = judged["metrics"].get(M, {})
    if m.get("S4") is None or m.get("S5") is None:
        return None
    return m["S4"] + m["S5"] + 2 * S_R7M


# ---------------------------------------------------------------- artifact directory analysis (used remotely and locally)
def load_npz(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def analyze_dir(out_dir, e6a_dir, run_flags=None):
    """Judge a completed E6B output directory. Pure numpy; used by run_e6b.py on the runner and again locally on the
    downloaded artifacts. Missing or inconsistent files become artifact problems, never silent gaps."""
    run_flags = dict(run_flags or {})
    problems = list(run_flags.get("artifact_problems", []))
    e6a = {L: load_npz(os.path.join(e6a_dir, f"level_L{L}.npz")) for L in LEVELS}
    pts = {L: e6a[L]["points_um_f32"][:, :2] for L in LEVELS}
    cs = CommonSet(pts, e6a[3]["NodeVolume"], e6a[3]["x"], e6a[3]["y"])
    levels, psi, gauss, dop, ident = {}, {}, {}, {}, {}
    skipped = set(run_flags.get("skipped_levels", []))          # levels the resource gate did not run (RESOURCE_PREFLIGHT_FAIL)
    for L in LEVELS:
        if L in skipped:
            levels[L], psi[L] = {"status": "RESOURCE_PREFLIGHT_FAIL", "P": None, "C": None}, {"P": None, "C": None}
            continue
        jp = os.path.join(out_dir, f"level_L{L}.json")
        if not os.path.exists(jp):
            problems.append(f"level_L{L}.json missing")
            levels[L], psi[L] = {"status": "MISSING", "P": None, "C": None}, {"P": None, "C": None}
            continue
        rec = json.load(open(jp, encoding="utf-8"))
        calls = {c["call_id"]: c for c in rec.get("solve_calls", [])}
        P = _solver_rec(calls.get(f"L{L}-P"))
        C = _solver_rec(calls.get(f"L{L}-C"))
        levels[L] = {"status": None if rec.get("status") == "OK" else rec.get("status"), "P": P, "C": C, "consistency_ok": None}
        psi[L] = {"P": None, "C": None}
        ident[f"L{L}"] = rec.get("identity")
        dop[f"L{L}"] = rec.get("doping")
        if rec.get("status") != "OK":
            continue
        static = _load_checked(out_dir, f"level_L{L}_static.npz", rec.get("static_sha256"), problems)
        snaps = {}
        for tag in ("P", "C"):
            if tag == "C" and f"L{L}-C" not in calls:
                continue
            arr = _load_state(out_dir, f"level_L{L}_state_{tag}.npz", (rec.get("snapshots") or {}).get(tag), f"L{L}-{tag}", problems)
            snaps[tag] = arr
        if static is None or snaps.get("P") is None:
            continue
        for tag, arr in snaps.items():
            if arr is not None:
                psi[L][tag] = arr["Potential"][cs.idx[L]]
        cons = {"finite_ok": True, "y_uniform": None}
        for arr in snaps.values():
            if arr is not None:
                cons["finite_ok"] &= all(bool(np.isfinite(arr[k]).all()) for k in REQUIRED_STATE_ARRAYS)
        if psi[L]["P"] is not None:
            cons["y_uniform"] = cs.y_spread(psi[L]["P"])
            cons["y_uniform_ok"] = all(v is not None and v <= Y_UNIFORM_MAX_V for v in cons["y_uniform"].values())
        levels[L]["consistency_ok"] = bool(cons["finite_ok"] and cons.get("y_uniform_ok"))
        levels[L]["consistency"] = cons
        xs = static["x"]
        cmask = (xs == xs.min()) | (xs == xs.max())
        pa = snaps["P"]
        gauss[f"L{L}"] = {"state_used": "P", **gauss_diagnostic(static["edge_n0"], static["edge_n1"], static["EdgeCouple"],
                                                                pa["PotentialEdgeFlux"], static["NodeVolume"],
                                                                pa["PotentialIntrinsicCharge"], cmask, xs, static["y"])}
        levels[L]["contacts_readback_V"] = {"xmin": float(np.mean(pa["Potential"][xs == xs.min()])),
                                            "xmax": float(np.mean(pa["Potential"][xs == xs.max()]))}
    run_flags["artifact_problems"] = problems
    judged = judge(levels, psi, cs, run_flags)
    ref = _load_reference(out_dir, cs)
    refstate = reference_assessment(ref, judged, psi, cs)
    return {"judgement": judged, "reference": refstate, "gauss_diagnostic": gauss, "doping": dop, "import_identity": ident,
            "level_consistency": {f"L{L}": levels[L].get("consistency") for L in LEVELS},
            "contact_readback": {f"L{L}": levels[L].get("contacts_readback_V") for L in LEVELS},
            "artifact_problems": problems}


def _solver_rec(c):
    if c is None:
        return None
    return {"ok": bool(c.get("ok")), "converged": c.get("converged"), "final_rel": c.get("final_device_relative_error"),
            "final_abs": c.get("final_device_absolute_error"), "n_iterations": c.get("n_iterations"), "error": c.get("error")}


def _load_checked(out_dir, name, sha_map, problems):
    p = os.path.join(out_dir, name)
    if not os.path.exists(p):
        problems.append(f"{name} missing")
        return None
    a = load_npz(p)
    for k, h in (sha_map or {}).items():
        if k not in a or sha_arr(a[k]) != h:
            problems.append(f"{name}: sha256 mismatch or missing array {k}")
    if not sha_map:
        problems.append(f"{name}: no recorded array sha256")
    return a


def _load_state(out_dir, name, rec, call_id, problems):
    p = os.path.join(out_dir, name)
    if not os.path.exists(p):
        problems.append(f"{name} missing")
        return None
    a = load_npz(p)
    probs = verify_state_artifact(rec, a, call_id)
    problems.extend(probs)
    return None if probs else a


def _load_reference(out_dir, cs):
    """R6 / R7 files -> usable reference dict, or {"usable": False, "reason": ...}. A damaged or failed reference makes ONLY
    the 1D reference unusable; the 2D judgement is never touched (PLAN 8)."""
    ux = np.unique(cs.xcm)
    out = {}
    for m in (6, 7):
        jp = os.path.join(out_dir, f"ref_R{m}.json")
        if not os.path.exists(jp):
            return {"usable": False, "reason": f"ref_R{m}.json missing"}
        rec = json.load(open(jp, encoding="utf-8"))
        if rec.get("status") != "OK":
            return {"usable": False, "reason": f"R{m} status {rec.get('status')}"}
        calls = {c["call_id"]: c for c in rec.get("solve_calls", [])}
        P, C = _solver_rec(calls.get(f"R{m}-P")), _solver_rec(calls.get(f"R{m}-C"))
        if not primary_ok(P):
            return {"usable": False, "reason": f"R{m}-P not converged"}
        cok, why = control_valid(P, C)
        if not cok:
            return {"usable": False, "reason": f"R{m}-C invalid: {why}"}
        local = []
        a = _load_checked(out_dir, f"ref_R{m}.npz", rec.get("array_sha256"), local)
        if a is None or local:
            return {"usable": False, "reason": f"ref_R{m}.npz unusable: {local}"}
        for tag in ("P", "C"):
            t = a.get(f"snapshot_call_id_{tag}")
            if t is None or str(np.asarray(t).reshape(-1)[0]) != f"R{m}-{tag}":
                return {"usable": False, "reason": f"ref_R{m}.npz snapshot tag {tag} mismatch"}
        xx = a["x"]
        pos = np.searchsorted(xx, ux)
        if not ((pos < len(xx)).all() and np.array_equal(xx[np.minimum(pos, len(xx) - 1)], ux)):
            return {"usable": False, "reason": f"2D x-values not present bit-exactly in R{m}"}
        out[m] = (a, pos)
    w = np.zeros(len(ux))
    np.add.at(w, np.searchsorted(ux, cs.xcm[~cs.contact]), cs.w[~cs.contact])
    g = lambda m, key: out[m][0][key][out[m][1]]  # noqa: E731
    return {"usable": True, "reason": None, "x": ux, "w": w, "R6P": g(6, "Potential_after_P"), "R6C": g(6, "Potential_after_C"),
            "R7P": g(7, "Potential_after_P"), "R7C": g(7, "Potential_after_C")}
