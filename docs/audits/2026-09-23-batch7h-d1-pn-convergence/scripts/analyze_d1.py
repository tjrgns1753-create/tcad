"""Batch 7H-D1 analysis: applies ONLY the rules registered in data/fixed_d1.json.
Writes data/analysis_d1.json and prints a summary. Supplementary (NOT a registered
input): 7H-D J0 1D results (read-only, solver rel 1e-6 there) for H1/H2 context."""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
FX = json.load(open(os.path.join(DATA, "fixed_d1.json"), encoding="utf-8"))
NI, VT, NA = 1e10, 0.025887193125000003, 1e17
H_CM = FX["physics"]["height_2d_cm"]
I2 = FX["physics"]["I_scale_2D_A_per_cm"]
J1S = FX["physics"]["J_scale_1D_A_per_cm2"]
BIAS = ["C-0.100", "C+0.050", "C+0.100"]
FLOOR = FX["layer_B_convergence"]["floors"]


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def A(d, k):
    return np.array(d[k], dtype=float)


def jl(step):
    return step["currents"]["left"]["total"]


def interp(xs, vs, xt):
    """per-side local 4-point Lagrange on (xs, vs); target side = sign(xt)."""
    xs, vs, xt = np.asarray(xs), np.asarray(vs), np.asarray(xt)
    out = np.empty(len(xt))
    for side in (-1, 1):
        m = (xs * side) > 0
        sx, sv = xs[m], vs[m]
        o = np.argsort(sx)
        sx, sv = sx[o], sv[o]
        tm = (xt * side) > 0
        for k in np.where(tm)[0]:
            x = xt[k]
            i = int(np.clip(np.searchsorted(sx, x) - 2, 0, len(sx) - 4))
            px, pv = sx[i:i + 4], sv[i:i + 4]
            out[k] = sum(pv[a] * np.prod([(x - px[b]) / (px[a] - px[b]) for b in range(4) if b != a]) for a in range(4))
    return out


def solves_ok(r):
    infos = [v["info"] for v in r.get("steps", {}).values() if isinstance(v, dict) and "info" in v]
    return bool(infos) and all(i["ok"] and i["rel_below_threshold"] for i in infos), \
        max((i.get("final_device_rel") or 0) for i in infos if i["ok"]) if infos else None


def eq_checks(r, scale):
    b = r["steps"]["B0"]
    st = b["state"]
    psi, n, p = A(st, "Potential"), A(st, "Electrons"), A(st, "Holes")
    il, ir = b["currents"]["left"]["total"], b["currents"]["right"]["total"]
    phin, phip = psi - VT * np.log(n / NI), psi + VT * np.log(p / NI)
    out = {"I_left": il, "I_right": ir, "eq_current_ok": max(abs(il), abs(ir)) <= 1e-10 * scale,
           "qf_dev_V": float(max(np.max(np.abs(phin - np.median(phin))), np.max(np.abs(phip - np.median(phip))))),
           "mass_action_dev": float(np.max(np.abs(n * p / NI ** 2 - 1)))}
    out["qf_ok"] = out["qf_dev_V"] <= 1e-6
    out["mass_action_ok"] = out["mass_action_dev"] <= 1e-6
    cons, pos = [], []
    for k in ["B0"] + BIAS:
        s = r["steps"].get(k, {})
        if "currents" not in s:
            cons.append(False)
            pos.append(False)
            continue
        a, c = s["currents"]["left"]["total"], s["currents"]["right"]["total"]
        cons.append(abs(a + c) <= 1e-6 * max(abs(a), abs(c)) + 1e-10 * scale)
        pos.append(s["summary"]["positive_finite"])
    out["conservation_all"], out["positivity_all"] = all(cons), all(pos)
    out["all_ok"] = all(out[k] for k in ("eq_current_ok", "qf_ok", "mass_action_ok", "conservation_all", "positivity_all"))
    return out


def reference():
    r = load("results_ref1d_J1.json")
    ids = sorted(r, key=lambda k: -r[k]["cfg"]["h"])
    lv = {}
    for k in ids:
        s = r[k]["steps"]
        ok, maxrel = solves_ok(r[k])
        x = A(s["A"]["state"], "x")
        lv[k] = {"h": r[k]["cfg"]["h"], "n_nodes": r[k]["mesh"]["n_nodes"], "x0_nodes": r[k]["mesh"]["x0_nodes"],
                 "all_solves_accepted": ok, "max_final_rel_update": maxrel,
                 "iterations": {kk: v["info"]["iterations"] for kk, v in s.items() if isinstance(v, dict) and "info" in v},
                 "E_peak_V_per_cm": s["A"]["max_abs_ElectricField_V_per_cm"],
                 "V_bi_V": float(A(s["A"]["state"], "Potential")[np.argmax(x)] - A(s["A"]["state"], "Potential")[np.argmin(x)]),
                 "J": {b: jl(s[b]) for b in BIAS}, "eq": eq_checks(r[k], J1S)}
    for a, b in zip(ids[:-1], ids[1:]):          # level-to-level changes (coarser vs next finer)
        sa, sb = r[a]["steps"], r[b]["steps"]
        xa = A(sa["A"]["state"], "x")
        lv[a]["psi_change_vs_next_V"] = float(np.max(np.abs(A(sa["A"]["state"], "Potential") - interp(
            A(sb["A"]["state"], "x"), A(sb["A"]["state"], "Potential"), xa))))
        xb0 = A(sa["B0"]["state"], "x")
        lv[a]["logc_change_vs_next"] = float(max(
            np.max(np.abs(np.log(A(sa["B0"]["state"], q)) - interp(A(sb["B0"]["state"], "x"), np.log(A(sb["B0"]["state"], q)), xb0)))
            for q in ("Electrons", "Holes")))
        lv[a]["J_change_vs_next"] = {bb: abs(jl(sa[bb]) - jl(sb[bb])) / abs(jl(sb[bb])) for bb in BIAS}
    fin, sec = ids[-1], ids[-2]
    U = {"U_psi_V": lv[sec]["psi_change_vs_next_V"], "U_logc": lv[sec]["logc_change_vs_next"],
         "U_I": lv[sec]["J_change_vs_next"]}
    U["current_converged"] = all(v <= 0.01 for v in U["U_I"].values())
    rich = {}
    for bb in BIAS:
        J = [lv[k]["J"][bb] for k in ids]
        p1 = math.log2(abs(J[2] - J[3]) / abs(J[3] - J[4]))
        p2 = math.log2(abs(J[1] - J[2]) / abs(J[2] - J[3]))
        stable = 0.5 <= p1 <= 4 and 0.5 <= p2 <= 4 and abs(p1 - p2) <= 0.25
        rich[bb] = {"p_finest": p1, "p_previous": p2, "stable": stable,
                    "J_extrapolated": (J[4] + (J[4] - J[3]) / (2 ** p1 - 1)) if stable else None}
    return r, ids, lv, U, rich


def trend(e, floor):
    if all(v <= floor for v in e):
        return "AT_FLOOR"
    return "DECREASING" if len(e) >= 3 and e[-3] > e[-2] > e[-1] else "NOT_DECREASING"


def yvar(x, v):
    cols = {}
    for xi, vi in zip(np.round(x * 1e10).astype(np.int64), v):
        cols.setdefault(int(xi), []).append(vi)
    sp = [max(c) - min(c) for c in cols.values() if len(c) >= 2]
    return float(max(sp)) if sp else 0.0


def main():
    r1, ids, lv, U, rich = reference()
    ref = r1[ids[-1]]["steps"]
    rx = A(ref["A"]["state"], "x")
    r2 = load("results_2d.json")
    out = {"ref1d_levels": lv, "U_ref": U, "richardson": rich, "layer_A": {}, "variants": {}}
    # ---- layer A: M2(h) vs 1D J1(h)
    for h in FX["runs"]["2D_h_um"]:
        k2, k1 = f"M2_D0_h{h}", f"1D_J1_h{h}"
        a2, a1 = r2.get(k2, {}).get("steps", {}), r1[k1]["steps"]
        if "A" not in a2 or "state" not in a2.get("B0", {}):
            out["layer_A"][str(h)] = {"status": "NOT_AVAILABLE"}
            continue
        m = {round(x * 1e10): i for i, x in enumerate(A(a1["A"]["state"], "x"))}
        idx = np.array([m[round(x * 1e10)] for x in A(a2["A"]["state"], "x")])
        dpsi = float(np.max(np.abs(A(a2["A"]["state"], "Potential") - A(a1["A"]["state"], "Potential")[idx])))
        idb = np.array([m[round(x * 1e10)] for x in A(a2["B0"]["state"], "x")])
        dlog = float(max(np.max(np.abs(np.log(A(a2["B0"]["state"], q)) - np.log(A(a1["B0"]["state"], q))[idb]))
                         for q in ("Electrons", "Holes")))
        dI = {b: abs(jl(a2[b]) / H_CM - jl(a1[b])) / abs(jl(a1[b])) for b in BIAS if "currents" in a2.get(b, {})}
        out["layer_A"][str(h)] = {"max_dpsi_V": dpsi, "max_dlog": dlog, "current_rel": dI,
                                  "pass": dpsi <= 1e-9 and dlog <= 1e-9 and len(dI) == 3 and all(v <= 1e-8 for v in dI.values())}
    # ---- layers B / C
    for fam, var in (("M1", "D0"), ("M2", "D0"), ("M3", "D0"), ("M3", "D1")):
        rows = []
        for h in FX["runs"]["2D_h_um"]:
            k = f"{fam}_{var}_h{h}"
            r = r2.get(k, {})
            s = r.get("steps", {})
            row = {"h": h, "status": r.get("status", "COMPLETED" if s else "MISSING"), "wall_s": r.get("wall_s")}
            ok, maxrel = solves_ok(r) if s else (False, None)
            row.update({"all_solves_accepted": ok, "max_final_rel_update": maxrel,
                        "iterations": {kk: v["info"]["iterations"] for kk, v in s.items() if isinstance(v, dict) and "info" in v}})
            if "state" not in s.get("A", {}) or "state" not in s.get("B0", {}) or any("currents" not in s.get(b, {}) for b in BIAS):
                row["complete"] = False
                rows.append(row)
                continue
            row["complete"] = True
            a, b0 = s["A"]["state"], s["B0"]["state"]
            x = A(a, "x")
            row["e_psi_V"] = float(np.max(np.abs(A(a, "Potential") - interp(rx, A(ref["A"]["state"], "Potential"), x))))
            xb = A(b0, "x")
            row["e_logc"] = float(max(np.max(np.abs(np.log(A(b0, q)) - interp(A(ref["B0"]["state"], "x"),
                                                                              np.log(A(ref["B0"]["state"], q)), xb)))
                                      for q in ("Electrons", "Holes")))
            row["yvar_psi_V"] = yvar(xb, A(b0, "Potential"))
            row["yvar_logn"] = yvar(xb, np.log(A(b0, "Electrons")))
            row["e_I"] = {bb: abs(jl(s[bb]) / H_CM - jl(ref[bb])) / abs(jl(ref[bb])) for bb in BIAS}
            row["I_A_per_cm"] = {bb: jl(s[bb]) for bb in BIAS}
            vb = float(A(a, "Potential")[x == x.max()].mean() - A(a, "Potential")[x == x.min()].mean())
            row["e_Vbi_V"] = abs(vb - lv[ids[-1]]["V_bi_V"])
            row["e_Epeak"] = abs(s["A"]["max_abs_ElectricField_V_per_cm"] - lv[ids[-1]]["E_peak_V_per_cm"]) / lv[ids[-1]]["E_peak_V_per_cm"]
            row["eq"] = eq_checks(r, I2)
            row["contact_consistency"] = s.get("C+0.100", {}).get("contact_consistency")
            row["psi_range_V"] = [s["B0"]["summary"]["psi_min"], s["B0"]["summary"]["psi_max"]]
            rows.append(row)
        done = [q for q in rows if q.get("complete")]
        v = {"levels": rows, "n_complete": len(done)}
        if len(done) >= 1:
            fin = done[-1]
            tr = {m: trend([q[m] for q in done], FLOOR[f]) for m, f in
                  (("e_psi_V", "e_psi_V"), ("e_logc", "e_logc"), ("yvar_psi_V", "yvar_psi_V"),
                   ("yvar_logn", "yvar_logn"), ("e_Vbi_V", "e_Vbi_V"), ("e_Epeak", "e_Epeak"))}
            for bb in BIAS:
                tr[f"e_I[{bb}]"] = trend([q["e_I"][bb] for q in done], FLOOR["e_I"])
            ratio = {}
            if len(done) >= 2:
                prev = done[-2]
                ratio = {"e_psi_V": fin["e_psi_V"] / prev["e_psi_V"] if prev["e_psi_V"] else None,
                         "yvar_psi_V": fin["yvar_psi_V"] / prev["yvar_psi_V"] if prev["yvar_psi_V"] else None}
                ratio.update({f"e_I[{bb}]": fin["e_I"][bb] / prev["e_I"][bb] for bb in BIAS})
            tolp = max(5 * U["U_psi_V"], 1e-6)
            tolI = {bb: max(5 * U["U_I"][bb], 0.02) for bb in BIAS}
            C = {"tol_psi_V": tolp, "psi_pass": fin["e_psi_V"] <= tolp, "tol_I": tolI,
                 "I_pass": {bb: fin["e_I"][bb] <= tolI[bb] for bb in BIAS},
                 "yvar_exceeds_potential_tol": fin["yvar_psi_V"] > tolp}
            v.update({"trend": tr, "finest_over_previous": ratio, "layer_C": C,
                      "all_eq_ok": all(q["eq"]["all_ok"] for q in done),
                      "all_solves_accepted": all(q["all_solves_accepted"] for q in rows)})
        out["variants"][f"{fam}_{var}"] = v
    # ---- hypotheses (registered rules)
    fx = load("fixtures_d1.json")

    def h3_like(v):
        if v.get("n_complete", 0) < 3:
            return False
        need = ["e_psi_V", "e_logc", "yvar_psi_V", "e_Epeak"] + [f"e_I[{bb}]" for bb in BIAS]
        return (all(v["trend"][m] in ("DECREASING", "AT_FLOOR") for m in need) and v["layer_C"]["psi_pass"]
                and all(v["layer_C"]["I_pass"].values()) and U["current_converged"] and v["all_eq_ok"]
                and v["all_solves_accepted"])

    def stagnant_fail(v):
        if v.get("n_complete", 0) < 2:
            return False
        C, rt = v["layer_C"], v["finest_over_previous"]
        fails = []
        if not C["psi_pass"]:
            fails.append(rt.get("e_psi_V"))
        fails += [rt.get(f"e_I[{bb}]") for bb in BIAS if not C["I_pass"][bb]]
        if C["yvar_exceeds_potential_tol"]:
            fails.append(rt.get("yvar_psi_V"))
        return any(f is not None and f >= 0.8 for f in fails)

    V = out["variants"]
    H = {}
    H["H1"] = {"verdict": "INCONCLUSIVE", "why": "registered J0 1D solves not accepted at any h (Poisson rel update not below 1e-10), so the registered J0-J1 current comparison cannot be evaluated"}
    H["H2"] = {"verdict": "INCONCLUSIVE", "why": "same: no accepted registered J0 current"}
    h3 = h3_like(V["M1_D0"]) and h3_like(V["M2_D0"])
    h3x = any(stagnant_fail(V[k]) for k in ("M1_D0", "M2_D0"))
    H["H3"] = {"verdict": "CONFIRMED" if h3 else ("EXCLUDED" if h3x else "INCONCLUSIVE")}
    m3d0 = V["M3_D0"]
    h4c = m3d0.get("n_complete", 0) >= 2 and stagnant_fail(m3d0)
    H["H4"] = {"verdict": "CONFIRMED" if h4c else ("EXCLUDED" if h3_like(m3d0) else "INCONCLUSIVE")}
    m3d1 = V["M3_D1"]
    negs = all(fx[f"M3_h{h}"]["quality"]["signed_edge_couple"]["negative"] == 0 and
               fx[f"M3_h{h}"]["quality"]["signed_node_volume"]["negative"] == 0 for h in FX["runs"]["2D_h_um"])
    cc = all((q.get("contact_consistency") or {}).get("pass") for q in m3d1["levels"] if q.get("complete"))
    h5 = h3_like(m3d1) and negs and cc
    H["H5"] = {"verdict": "CONFIRMED" if h5 else ("EXCLUDED" if stagnant_fail(m3d1) else "INCONCLUSIVE"),
               "no_negative_geometry": negs, "contact_consistency_all": cc}
    out["hypotheses"] = H
    verd = []
    if H["H3"]["verdict"] == "CONFIRMED":
        verd.append("A")
    if H["H5"]["verdict"] == "CONFIRMED":
        verd.append("B")
    if H["H4"]["verdict"] == "CONFIRMED":
        verd.append("C")
    if H["H1"]["verdict"] == "CONFIRMED" and H["H2"]["verdict"] == "CONFIRMED":
        verd.append("D")
    if not U["current_converged"]:
        verd.append("E")
    if any(V[k].get("trend", {}).get(m) == "NOT_DECREASING" for k in ("M1_D0", "M2_D0")
           for m in ["e_psi_V"] + [f"e_I[{bb}]" for bb in BIAS]):
        verd.append("F")
    out["verdicts_by_registered_rule"] = verd or ["G"]
    # ---- supplementary J0 context (7H-D data, rel 1e-6 there; not registered)
    try:
        j0 = json.load(open(os.path.join(DATA, "..", "..", "2026-09-23-batch7h-d-sg-pn-mesh-validity", "data",
                                         "results_ref1d.json"), encoding="utf-8"))
        sup = {}
        for key, rr in j0.items():
            h = rr["cfg"]["dx_um"]
            k1 = f"1D_J1_h{h}"
            sup[str(h)] = {bb: {"J_J0_7HD": rr["steps"][bb.replace("C", "C_").replace("+0.050", "+0.050")]["currents"]["left"]["total"]}
                           for bb in BIAS}
            for bb in BIAS:
                sup[str(h)][bb]["J_J1"] = jl(r1[k1]["steps"][bb])
                sup[str(h)][bb]["rel_diff"] = abs(sup[str(h)][bb]["J_J0_7HD"] - sup[str(h)][bb]["J_J1"]) / abs(sup[str(h)][bb]["J_J1"])
        out["supplementary_J0_from_7HD"] = sup
    except Exception as e:  # noqa: BLE001
        out["supplementary_J0_from_7HD"] = {"error": repr(e)}
    with open(os.path.join(DATA, "analysis_d1.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(json.dumps({"U_ref": U, "richardson": rich, "layer_A": out["layer_A"], "hypotheses": H,
                      "verdicts": out["verdicts_by_registered_rule"]}, indent=1, default=float))
    for k, lvv in lv.items():
        print(k, {q: lvv.get(q) for q in ("n_nodes", "all_solves_accepted", "max_final_rel_update", "E_peak_V_per_cm", "V_bi_V",
                                           "psi_change_vs_next_V", "logc_change_vs_next")}, lvv["J"], lvv.get("J_change_vs_next"),
              {q: lvv["eq"][q] for q in ("qf_dev_V", "mass_action_dev", "all_ok")})
    for k, v in V.items():
        print("\n==", k, "trend", v.get("trend"), "ratio", v.get("finest_over_previous"), "C", v.get("layer_C"))
        for q in v["levels"]:
            if q.get("complete"):
                print("  h=%s psi=%.3e logc=%.3e yv=%.3e yvn=%.3e Ep=%.3e Vbi=%.1e eI=%s acc=%s rel=%.1e eq=%s cc=%s it=%s wall=%s" % (
                    q["h"], q["e_psi_V"], q["e_logc"], q["yvar_psi_V"], q["yvar_logn"], q["e_Epeak"], q["e_Vbi_V"],
                    {b: "%.3e" % e for b, e in q["e_I"].items()}, q["all_solves_accepted"], q["max_final_rel_update"],
                    q["eq"]["all_ok"], (q["contact_consistency"] or {}).get("pass"), q["iterations"], q["wall_s"]))
            else:
                print("  h=%s INCOMPLETE" % q["h"], q)


if __name__ == "__main__":
    main()
