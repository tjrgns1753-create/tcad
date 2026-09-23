"""Batch 7H-D2 analysis: applies ONLY the rules registered in data/fixed_d2.json to
data/runs/*.json. Reuses 7H-D1 interp()/yvar() (read-only import).
-> data/analysis_d2.json + printed summary."""
import glob
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-d1-pn-convergence", "scripts"))
from analyze_d1 import interp, yvar  # noqa: E402  (7H-D1, read-only)

TAU, HCM = 1e-5, 1e-5
PS = ("P0", "P1", "P2", "P3", "P4")
BIASED = ("C+0.050", "C+0.100", "C-0.100")
CUTS = ("-0.25", "-0.10", "+0.00", "+0.10", "+0.25")
H1D = (0.02, 0.01, 0.005, 0.0025, 0.00125, 0.000625, 0.0003125)
H2D = (0.02, 0.005, 0.00125)
FAMS = (("M2", "D0"), ("M1", "D0"), ("M3", "D1"))
R = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in glob.glob(os.path.join(DATA, "runs", "*.json"))}


def rid(kind, h, P, fam=None, var=None, mirror=False):
    b = f"1D_h{h}" if kind == "1d" else f"{fam}_{var}_h{h}"
    return f"{b}_{P}" + ("_mirror" if mirror else "")


def ok_run(r):
    st = [v["info"] for v in r.get("steps", {}).values() if isinstance(v, dict) and "info" in v]
    return bool(st) and all(i["ok"] for i in st) and len(st) == 11


def cut(s, c):
    return s["C2"][c]["total"]


def point_metrics(s):
    L, Rr = s["C0"]["left"]["total"], s["C0"]["right"]["total"]
    cs = np.array([cut(s, c) for c in CUTS])
    med = float(np.median(cs))
    i0 = cut(s, "+0.00")
    c3 = max(max(abs(v["dI_n"] - v["q_int_U"]), abs(v["dI_p"] + v["q_int_U"])) for v in s["C3"].values()) / abs(i0)
    c3t = max(abs(v["dI_total"]) for v in s["C3"].values()) / abs(i0)
    c1 = all(abs(s["C1"][k]["total"] - s["C0"][k]["total"]) <= 1e-10 * abs(s["C0"][k]["total"]) + 1e-30 for k in ("left", "right"))
    return {"C0_left": L, "C0_right": Rr, "I_cut": dict(zip(CUTS, cs.tolist())),
            "mis_lr": abs(L + Rr) / abs(L), "spread": float(np.max(np.abs(cs - med)) / abs(med)),
            "c0L_vs_cut0": abs(L - i0) / abs(i0), "c0R_vs_cut0": abs(Rr + i0) / abs(i0),
            "c3_species": c3, "c3_total": c3t, "c1_identity": c1,
            "ulp_left_min": (s["ulp"]["left_contact"] or {}).get("min_abs_dpsi_over_ulp"),
            "ulp_right_min": (s["ulp"]["right_contact"] or {}).get("min_abs_dpsi_over_ulp"),
            "dev_vs_py_dpsi_left": (s["ulp"]["left_contact"] or {}).get("max_rel_dev_minus_py_dpsi"),
            "cancel_left_p": (s["ulp"]["left_contact"] or {}).get("max_cancellation_p"),
            "cancel_right_n": (s["ulp"]["right_contact"] or {}).get("max_cancellation_n"),
            "cancel_cut0_n": (s["ulp"]["cut+0.00"] or {}).get("max_cancellation_n"),
            "vdiff_left": (s["ulp"]["left_contact"] or {}).get("vdiff_range")}


def run_metrics(r):
    out = {"ok": ok_run(r), "wall_s": r.get("wall_s"), "points": {}}
    for b in BIASED:
        s = r.get("steps", {}).get(b, {})
        if "C0" in s:
            out["points"][b] = point_metrics(s)
    b0 = r.get("steps", {}).get("B0", {})
    if "C0" in b0 and "C-0.100" in out["points"]:
        ref = out["points"]["C-0.100"]
        out["zero_bias_ok"] = abs(b0["C0"]["left"]["total"]) <= 1e-6 * abs(ref["C0_left"]) and \
            all(abs(b0["C2"][c]["total"]) <= 1e-6 * abs(ref["I_cut"][c]) for c in CUTS)
        out["qf_dev_V"], out["mass_action_dev"] = b0.get("qf_dev_V"), b0.get("mass_action_dev")
        out["positive"] = all(r["steps"][k].get("positive_finite", True) for k in ("B0",) + BIASED if k in r["steps"])
    return out


M = {k: run_metrics(v) for k, v in R.items()}


def pts(P):
    return [(k, b, p) for k, m in M.items() if k.endswith("_" + P) for b, p in m["points"].items()]


def restores(P):
    ps = pts(P)
    a = all(p["mis_lr"] <= TAU for _, _, p in ps)
    b = all(p["spread"] <= TAU for _, _, p in ps)
    c = all(p["c0L_vs_cut0"] <= TAU for _, _, p in ps)
    d = {}
    for bb in BIASED:
        seq = [M.get(rid("1d", h, P), {}).get("points", {}).get(bb, {}).get("C0_left") for h in (0.0025, 0.00125, 0.000625, 0.0003125)]
        if None in seq:
            d[bb] = None
            continue
        ch = [abs(seq[i + 1] - seq[i]) for i in range(3)]
        d[bb] = {"changes": ch, "ok": ch[0] > ch[1] > ch[2] and ch[2] / abs(seq[-1]) <= 1e-3}
    dd = all(v and v["ok"] for v in d.values())
    worst = {q: max((p[q] for _, _, p in ps), default=None) for q in ("mis_lr", "spread", "c0L_vs_cut0", "c3_total", "c3_species")}
    return {"a": a, "b": b, "c": c, "d": dd, "d_detail": d, "restores": a and b and c and dd, "n_points": len(ps), "worst": worst}


out = {"n_runs": len(R), "runs_not_ok": [k for k, m in M.items() if not m["ok"]], "per_run": M}
rest = {P: restores(P) for P in PS}
out["restoration"] = rest
p0 = [M.get(rid("1d", 0.00125, "P0"), {}).get("points", {}).get(b, {}).get("mis_lr") for b in ("C+0.100", "C-0.100")]
out["P0_reproduces"] = all(v is not None and v > TAU for v in p0)
single = [P for P in ("P1", "P2", "P3") if rest[P]["restores"]]
names = {"P1": "FLOAT64_MODEL_CANCELLATION_CONFIRMED", "P2": "FLOAT64_EQUATION_ASSEMBLY_CONFIRMED", "P3": "FLOAT64_SOLVER_PRECISION_CONFIRMED"}
cause = [names[P] for P in single]
if not cause:
    if rest["P4"]["restores"]:
        cause = ["FLOAT64_CAUSAL_ONLY_WITH_ALL_FLAGS (attribution INCONCLUSIVE)"]
    else:
        w0, w4 = rest["P0"]["worst"]["mis_lr"], rest["P4"]["worst"]["mis_lr"]
        cause = ["PRECISION_NOT_CAUSAL"] if (w4 and w0 and 0.5 <= w4 / w0 <= 2) else ["INCONCLUSIVE"]
out["cause_verdicts"] = cause if out["P0_reproduces"] else ["INCONCLUSIVE (P0 did not reproduce)"]
mode = single[0] if single else "P4"
out["certifying_mode"] = mode


def modepts(P, pred=lambda k: True):
    return [(k, b, p) for k, b, p in pts(P) if "_mirror" not in k and pred(k)]


def certify(P):
    ps = modepts(P)
    c = {"spread": all(p["spread"] <= TAU for _, _, p in ps),
         "contacts_vs_cut0": all(p["c0L_vs_cut0"] <= TAU and p["c0R_vs_cut0"] <= TAU for _, _, p in ps),
         "c3_species": all(p["c3_species"] <= TAU for _, _, p in ps),
         "c3_total": all(p["c3_total"] <= TAU for _, _, p in ps),
         "c1_identity": all(p["c1_identity"] for _, _, p in ps),
         "zero_bias": all(M[k].get("zero_bias_ok", False) for k in {k for k, _, _ in ps})}
    same = {}
    for h in H2D:
        a, b = M.get(rid("2d", h, P, "M2", "D0"), {}).get("points", {}), M.get(rid("1d", h, P), {}).get("points", {})
        for bb in BIASED:
            if bb in a and bb in b:
                same[f"{h}{bb}"] = max(abs(a[bb]["I_cut"][cc] / HCM - b[bb]["I_cut"][cc]) / abs(b[bb]["I_cut"][cc]) for cc in CUTS)
    c["M2_same_h"] = bool(same) and all(v <= 1e-8 for v in same.values())
    mir = {}
    for base in (rid("1d", 0.005, P), rid("2d", 0.005, P, "M1", "D0")):
        o, m = M.get(base, {}).get("points", {}), M.get(base + "_mirror", {}).get("points", {})
        for bb in BIASED:
            if bb in o and bb in m:
                mir[f"{base}{bb}"] = max(abs(m[bb]["I_cut"][f"{-float(cc) + 0.0:+.2f}"] + o[bb]["I_cut"][cc]) / abs(o[bb]["I_cut"][cc])
                                         for cc in CUTS)
    c["mirror"] = bool(mir) and all(v <= TAU for v in mir.values())
    if not c["c3_total"]:
        v = "INTERIOR_CUT_CURRENT_NOT_CONSERVATIVE"
    elif all(c.values()):
        v = "INTERIOR_CUT_CURRENT_CERTIFIED"
    elif not c["spread"]:
        v = "INTERIOR_CUT_CURRENT_POSITION_DEPENDENT"
    else:
        v = "INCONCLUSIVE"
    return {"checks": c, "M2_same_h_rel": same, "mirror_rel": mir, "verdict": v,
            "worst": {q: max((p[q] for _, _, p in ps), default=None) for q in ("spread", "c0L_vs_cut0", "c0R_vs_cut0", "c3_species", "c3_total")}}


out["cut_certification"] = {P: certify(P) for P in sorted({mode, "P4", "P0"})}


def reeval(P, fam, var):
    ref = R.get(rid("1d", 0.0003125, P), {})
    ref2 = R.get(rid("1d", 0.000625, P), {})
    if not ref or not ok_run(ref):
        return {"status": "NO_REFERENCE"}
    refpts = {bb: point_metrics(ref["steps"][bb]) for bb in BIASED}
    U = {bb: abs(refpts[bb]["I_cut"]["+0.00"] - point_metrics(ref2["steps"][bb])["I_cut"]["+0.00"]) / abs(refpts[bb]["I_cut"]["+0.00"]) for bb in BIASED}
    seqs = {bb: [point_metrics(R[rid("1d", h, P)]["steps"][bb])["I_cut"]["+0.00"] for h in (0.0025, 0.00125, 0.000625, 0.0003125)] for bb in BIASED}
    decr = {bb: (lambda s: abs(s[1] - s[0]) > abs(s[2] - s[1]) > abs(s[3] - s[2]))(seqs[bb]) for bb in BIASED}
    ref_ok = all(u <= 0.01 for u in U.values()) and all(decr.values())
    rA = R[rid("1d", 0.0003125, "P4")]["steps"]["A"]["state"]
    rA2 = R[rid("1d", 0.000625, "P4")]["steps"]["A"]["state"]
    xr = np.array(rA["x"])
    U_psi = float(np.max(np.abs(np.array(rA2["psi"]) - interp(xr, np.array(rA["psi"]), np.array(rA2["x"])))))
    rB = ref["steps"]["B0"]["state"]
    E_ref = ref["steps"]["A"]["max_abs_ElectricField"]
    rows = []
    for h in H2D:
        r = R.get(rid("2d", h, P, fam, var), {})
        if not r or not ok_run(r):
            rows.append({"h": h, "complete": False})
            continue
        m = M[rid("2d", h, P, fam, var)]
        a, b0 = r["steps"]["A"]["state"], r["steps"]["B0"]["state"]
        x = np.array(a["x"])
        e_psi = float(np.max(np.abs(np.array(a["psi"]) - interp(xr, np.array(rA["psi"]), x))))
        xb = np.array(b0["x"])
        e_logc = float(max(np.max(np.abs(np.array(b0[q]) - interp(np.array(rB["x"]), np.array(rB[q]), xb))) for q in ("ln_n", "ln_p")))
        eI = {bb: {cc: (m["points"][bb]["I_cut"][cc] / HCM - refpts[bb]["I_cut"][cc]) / abs(refpts[bb]["I_cut"][cc]) for cc in CUTS} for bb in BIASED}
        rows.append({"h": h, "complete": True, "e_psi_V": e_psi, "e_logc": e_logc, "e_I_signed": eI,
                     "e_I_max": max(abs(v) for d in eI.values() for v in d.values()),
                     "e_Epeak": abs(r["steps"]["A"]["max_abs_ElectricField"] - E_ref) / E_ref,
                     "yvar_psi_V": yvar(xb, np.array(b0["psi"])), "spread_max": max(p["spread"] for p in m["points"].values()),
                     "qf_dev_V": m.get("qf_dev_V"), "mass_action_dev": m.get("mass_action_dev"), "positive": m.get("positive"),
                     "zero_bias_ok": m.get("zero_bias_ok"), "c1_identity": all(p["c1_identity"] for p in m["points"].values()),
                     "wall_s": r.get("wall_s")})
    done = [q for q in rows if q.get("complete")]
    res = {"U_ref": U, "ref_decreasing": decr, "ref_ok": ref_ok, "U_psi_V": U_psi, "levels": rows}
    if len(done) == 3:
        dec = lambda k: done[0][k] > done[1][k] > done[2][k]  # noqa: E731
        f = done[-1]
        tolI = max(5 * max(U.values()), 0.02)
        res["checks"] = {"e_psi_decreasing": dec("e_psi_V"), "e_logc_decreasing": dec("e_logc"),
                         "e_I_decreasing_every_cut_bias": all(abs(done[0]["e_I_signed"][bb][cc]) > abs(done[1]["e_I_signed"][bb][cc]) >
                                                              abs(done[2]["e_I_signed"][bb][cc]) for bb in BIASED for cc in CUTS),
                         "finest_psi": f["e_psi_V"] <= max(5 * U_psi, 1e-6), "finest_I": f["e_I_max"] <= tolI,
                         "spread": all(q["spread_max"] <= TAU for q in done), "positive": all(q["positive"] for q in done),
                         "qf": all(q["qf_dev_V"] <= 1e-6 for q in done), "mass_action": all(q["mass_action_dev"] <= 1e-6 for q in done),
                         "zero_bias": all(q["zero_bias_ok"] for q in done), "ref_ok": ref_ok,
                         "E_peak_decreasing": dec("e_Epeak"), "yvar_decreasing": dec("yvar_psi_V") or all(q["yvar_psi_V"] <= 1e-6 for q in done),
                         "c1_identity": all(q["c1_identity"] for q in done)}
        res["tol_I"], res["tol_psi"] = tolI, max(5 * U_psi, 1e-6)
    return res


out["reevaluation"] = {f"{f}_{v}": reeval(mode, f, v) for f, v in FAMS}
A_keys = ("e_psi_decreasing", "e_logc_decreasing", "e_I_decreasing_every_cut_bias", "finest_psi", "finest_I", "spread",
          "positive", "qf", "mass_action", "zero_bias", "ref_ok")
okA = all(all(out["reevaluation"][k].get("checks", {}).get(c, False) for c in A_keys) for k in ("M1_D0", "M2_D0"))
m3 = out["reevaluation"]["M3_D1"].get("checks", {})
okB = okA and all(m3.get(c, False) for c in A_keys + ("E_peak_decreasing", "yvar_decreasing", "c1_identity"))
# M3 D1 -0.10 V sign-crossing classification (cut x = 0)
sc = {}
for h in (0.02, 0.005, 0.0025, 0.00125):
    e = {}
    for P in ("P0", mode):
        r1 = R.get(rid("1d", 0.0003125, P))
        r2 = M.get(rid("2d", h, P, "M3", "D1"), {}).get("points", {}).get("C-0.100")
        if r1 and r2:
            ref = point_metrics(r1["steps"]["C-0.100"])["I_cut"]["+0.00"]
            e[P] = (r2["I_cut"]["+0.00"] / HCM - ref) / abs(ref)
    sc[str(h)] = e
out["M3_D1_sign_crossing"] = sc
out["final"] = {"cause": out["cause_verdicts"], "cut": out["cut_certification"][mode]["verdict"],
                "A": okA, "B": okB, "terminal_unresolved": not any(rest[P]["restores"] for P in ("P1", "P2", "P3", "P4"))}
with open(os.path.join(DATA, "analysis_d2.json"), "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, indent=1, default=float)
print("runs", len(R), "not ok", out["runs_not_ok"])
print("P0 reproduces", out["P0_reproduces"], p0)
for P in PS:
    rr = rest[P]
    print(P, "restores", rr["restores"], {k: rr[k] for k in "abcd"}, "worst", {k: "%.2e" % v for k, v in rr["worst"].items() if v is not None},
          "d", {b: (["%.2e" % c for c in v["changes"]] if v else None) for b, v in rr["d_detail"].items()})
print("cause", out["cause_verdicts"], "mode", mode)
for P, c in out["cut_certification"].items():
    print("cert", P, c["verdict"], c["checks"], {k: "%.2e" % v for k, v in c["worst"].items() if v is not None})
    print("   M2 same-h max %.2e" % max(c["M2_same_h_rel"].values(), default=float("nan")), "mirror max %.2e" % max(c["mirror_rel"].values(), default=float("nan")))
for k, v in out["reevaluation"].items():
    print("reeval", k, "U_ref", {b: "%.2e" % u for b, u in v.get("U_ref", {}).items()}, "ref_ok", v.get("ref_ok"), "U_psi %.2e" % v.get("U_psi_V", 0))
    for q in v.get("levels", []):
        if q.get("complete"):
            print("   h=%s psi=%.3e logc=%.3e eI_max=%.3e Ep=%.3e yvar=%.3e spread=%.2e qf=%.1e ma=%.1e wall=%s" % (
                q["h"], q["e_psi_V"], q["e_logc"], q["e_I_max"], q["e_Epeak"], q["yvar_psi_V"], q["spread_max"], q["qf_dev_V"], q["mass_action_dev"], q["wall_s"]))
            print("     eI cut0:", {b: "%+.3e" % q["e_I_signed"][b]["+0.00"] for b in BIASED})
    print("   checks", v.get("checks"))
print("M3 D1 sign crossing (-0.10 V, cut 0)", sc)
print("FINAL", out["final"])
