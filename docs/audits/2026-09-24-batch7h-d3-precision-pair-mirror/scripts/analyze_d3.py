"""Batch 7H-D3 analysis: applies ONLY the rules of PLAN.md (sections 3-6) to the run JSONs.
Point-metric definitions copy 7H-D2 analyze_d2.point_metrics (which cannot be imported: it runs on import).
usage: analyze_d3.py --runs <dir of run json> --out <dir> [--plan-dir <dir with PLAN.md>]"""
import argparse
import glob
import hashlib
import json
import os
import sys

import numpy as np

TAU = 1e-5            # PLAN section 3 (7H-D2 registered threshold)
ZERO = 1e-6           # zero-bias rule
DEN = 1e-6            # denominator rule
TOL_PARAM = 1e-12     # bias parameter readback
TOL_PSI = 1e-9        # contact-potential derived applied voltage
BIASED = ("C+0.050", "C+0.100", "C-0.100")
VSET = {"C+0.050": 0.05, "C+0.100": 0.1, "C-0.100": -0.1}
CUTS = ("-0.25", "-0.10", "+0.00", "+0.10", "+0.25")
EXPECTED_STEPS = ("A", "B0", "C+0.025", "C+0.050", "C+0.075", "C+0.100", "Arev", "B0rev", "C-0.025", "C-0.050", "C-0.075", "C-0.100")


def converged(r):
    if "error" in r:
        return False
    st = r.get("steps", {})
    return all(k in st and st[k].get("info", {}).get("ok") for k in EXPECTED_STEPS)


def pm(s):
    L, R = s["C0"]["left"]["total"], s["C0"]["right"]["total"]
    cs = {c: s["C2"][c]["total"] for c in CUTS}
    arr = np.array([cs[c] for c in CUTS])
    med = float(np.median(arr))
    i0 = cs["+0.00"]
    ivl = {}
    for k, v in s["C3"].items():
        ivl[k] = {"dI_n_minus_qU": v["dI_n"] - v["q_int_U"], "dI_p_plus_qU": v["dI_p"] + v["q_int_U"],
                  "dI_total": v["dI_total"]}
    c3sp = max(max(abs(v["dI_n_minus_qU"]), abs(v["dI_p_plus_qU"])) for v in ivl.values()) / abs(i0)
    c3t = max(abs(v["dI_total"]) for v in ivl.values()) / abs(i0)
    c1 = all(abs(s["C1"][k]["total"] - s["C0"][k]["total"]) <= 1e-10 * abs(s["C0"][k]["total"]) + 1e-30 for k in ("left", "right"))
    return {"C0_left": L, "C0_right": R, "cuts": cs, "mis_lr": abs(L + R) / abs(L),
            "spread": float(np.max(np.abs(arr - med)) / abs(med)), "c0L_vs_cut0": abs(L - i0) / abs(i0),
            "c0R_vs_cut0": abs(R + i0) / abs(i0), "c3_species": c3sp, "c3_total": c3t, "c1_identity": c1, "intervals": ivl,
            "cut_scale": float(np.max(np.abs(arr)))}


def self_ok(r):
    if not converged(r):
        return {"status": "NOT_COMPLETED"}
    pts, ok = {}, True
    for b in BIASED:
        m = pm(r["steps"][b])
        chk = {"mis_lr": m["mis_lr"] <= TAU, "spread": m["spread"] <= TAU, "c0L_vs_cut0": m["c0L_vs_cut0"] <= TAU,
               "c0R_vs_cut0": m["c0R_vs_cut0"] <= TAU, "c3_species": m["c3_species"] <= TAU, "c3_total": m["c3_total"] <= TAU,
               "c1_identity": m["c1_identity"]}
        pts[b] = {"metrics": {k: m[k] for k in ("mis_lr", "spread", "c0L_vs_cut0", "c0R_vs_cut0", "c3_species", "c3_total")},
                  "checks": chk, "ok": all(chk.values())}
        ok = ok and pts[b]["ok"]
    ref = pm(r["steps"]["C-0.100"])
    zero = {}
    for tag in ("B0", "B0rev"):
        s = r["steps"][tag]
        vals = [abs(s["C0"][k]["total"]) for k in ("left", "right")] + [abs(s["C2"][c]["total"]) for c in CUTS]
        lim = [ZERO * abs(ref["C0_left"])] * 2 + [ZERO * abs(ref["cuts"][c]) for c in CUTS]
        zero[tag] = all(v <= l for v, l in zip(vals, lim))
    ok = ok and all(zero.values())
    return {"status": "SELF_OK" if ok else "SELF_VIOLATED", "points": pts, "zero_bias_ok": zero}


def equality(r_a, r_b):
    """PLAN section 4: P12 (a) vs P4 (b)."""
    if not (converged(r_a) and converged(r_b)):
        return {"verdict": "NOT_COMPLETED"}
    fails, undecided, rows = [], [], []
    for b in BIASED:
        ma, mb = pm(r_a["steps"][b]), pm(r_b["steps"][b])
        qa = {"C0_left": ma["C0_left"], "C0_right": ma["C0_right"], **{f"cut{c}": ma["cuts"][c] for c in CUTS}}
        qb = {"C0_left": mb["C0_left"], "C0_right": mb["C0_right"], **{f"cut{c}": mb["cuts"][c] for c in CUTS}}
        for k in qb:
            rel = abs(qa[k] - qb[k]) / abs(qb[k]) if qb[k] != 0 else float("inf")
            state = "OK"
            if abs(qb[k]) < DEN * mb["cut_scale"]:
                state = "UNDECIDABLE"
                undecided.append((b, k))
            elif rel > TAU:
                state = "FAIL"
                fails.append((b, k, rel))
            rows.append({"point": b, "quantity": k, "P12": qa[k], "P4": qb[k], "rel_diff": rel, "state": state})
    so = self_ok(r_a)
    if fails or so["status"] != "SELF_OK":
        verdict = "FAIL"
    elif undecided:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "P12_self": so["status"], "n_fail": len(fails), "n_undecidable": len(undecided),
            "max_rel_diff": max((x["rel_diff"] for x in rows if x["state"] != "UNDECIDABLE"), default=None), "rows": rows}


def applied_v(step, eq_step):
    rb, rb0 = step["readback"], eq_step["readback"]
    return (rb["psi_p_contact"] - rb["psi_n_contact"]) - (rb0["psi_p_contact"] - rb0["psi_n_contact"])


def mirror_pair(ro, rm):
    if not (converged(ro) and converged(rm)):
        return {"verdict": "NOT_COMPLETED"}
    issues, undecided, rows, bias = [], [], [], []
    geo = {"orig": ro["geometry"], "mirror": rm["geometry"]}
    geo_ok = all(g["max_abs_dx_vs_expected_um"] <= 1e-9 and g["donors_all_on_expected_side"] and g["acceptors_all_on_expected_side"]
                 for g in geo.values())
    for b in BIASED:
        v = VSET[b]
        eq_tag = "B0rev" if v < 0 else "B0"
        for side, r in (("orig", ro), ("mirror", rm)):
            rb = r["steps"][b]["readback"]
            va = applied_v(r["steps"][b], r["steps"][eq_tag])
            row = {"point": b, "device": side, "v_set": v, "p_bias_name": rb["p_bias_name"], "p_bias_readback": rb["p_bias_readback"],
                   "n_bias_name": rb["n_bias_name"], "n_bias_readback": rb["n_bias_readback"], "v_from_contact_potentials": va,
                   "param_ok": abs(rb["p_bias_readback"] - v) <= TOL_PARAM and abs(rb["n_bias_readback"]) <= TOL_PARAM,
                   "potential_ok": abs(va - v) <= TOL_PSI}
            bias.append(row)
            if not (row["param_ok"] and row["potential_ok"]):
                issues.append(("bias", b, side))
        so, sm = pm(ro["steps"][b]), pm(rm["steps"][b])
        scale = so["cut_scale"]
        pairs = [("p_contact: M.right vs O.left", sm["C0_right"], so["C0_left"], +1),
                 ("n_contact: M.left vs O.right", sm["C0_left"], so["C0_right"], +1)]
        for c in CUTS:
            xo = ro["steps"][b]["C2X"][c]["total"]
            xm = rm["steps"][b]["C2X"][c]["total"]
            pairs.append((f"cut {c}: I_M(-x) vs -I_O(x)", xm, xo, -1))
        for name, m_val, o_val, sign in pairs:
            expect = sign * o_val
            rel = abs(m_val - expect) / abs(o_val) if o_val != 0 else float("inf")
            state = "OK"
            if abs(o_val) < DEN * scale:
                state = "UNDECIDABLE"
                undecided.append((b, name))
            elif rel > TAU:
                state = "FAIL"
                issues.append(("current", b, name, rel))
            rows.append({"point": b, "pair": name, "original": o_val, "mirror": m_val, "expected_mirror": expect, "rel_err": rel, "state": state})
    zero = {}
    for side, r in (("orig", ro), ("mirror", rm)):
        ref = pm(r["steps"]["C-0.100"])
        for tag in ("B0", "B0rev"):
            s = r["steps"][tag]
            vals = [abs(s["C0"][k]["total"]) for k in ("left", "right")] + [abs(s["C2"][c]["total"]) for c in CUTS]
            lim = [ZERO * abs(ref["C0_left"])] * 2 + [ZERO * abs(ref["cuts"][c]) for c in CUTS]
            zero[f"{side}_{tag}"] = all(x <= y for x, y in zip(vals, lim))
    if issues or not all(zero.values()) or not geo_ok:
        verdict = "MIRROR_FAIL"
    elif undecided:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "MIRROR_PASS"
    return {"verdict": verdict, "geometry": geo, "geometry_ok": geo_ok, "issues": issues, "n_undecidable": len(undecided),
            "zero_bias": zero, "max_rel_err": max((x["rel_err"] for x in rows if x["state"] != "UNDECIDABLE"), default=None),
            "bias_rows": bias, "rows": rows}


def load(dirp):
    return {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(dirp, "*.json")))}


def sha_lf(path):
    return hashlib.sha256(open(path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    a = ap.parse_args()
    R = load(a.runs)
    out = {"schema": 1, "tau": TAU, "zero_rule": ZERO, "denominator_rule": DEN, "n_runs": len(R),
           "run_status": {k: ("ERROR" if "error" in v else ("CONVERGED" if converged(v) else "NOT_COMPLETED")) for k, v in R.items()}}
    plan = os.path.join(a.plan_dir, "PLAN.md")
    expect = open(os.path.join(a.plan_dir, "PLAN.sha256"), encoding="utf-8").read().split()[0]
    out["plan"] = {"sha256_lf_normalized": sha_lf(plan), "recorded_at_fixing": expect, "matches": sha_lf(plan) == expect}
    # fixture / flag identity
    ident, ok_all = {}, True
    for k, r in R.items():
        if "error" in r:
            continue
        f = r["fixture"]
        good = f.get("identical_to_stored", True) and f.get("n_nodes") == f.get("stored_n_nodes", f.get("n_nodes"))
        flags_ok = r["flags_set"] == dict(zip(("extended_model", "extended_equation", "extended_solver"),
                                              {"P0": (False, False, False), "P12": (True, True, False), "P4": (True, True, True)}[r["cfg"]["P"]])) \
            and r["flags_at_end"] == r["flags_set"] and r["devices_left"] == []
        ident[k] = {"fixture_identical": good, "flags_readback_ok": flags_ok, "file_sha256_raw": f.get("file_sha256_raw"),
                    "file_sha256_lf": f.get("file_sha256_lf_normalized"), "n_nodes": f.get("n_nodes"), "n_triangles": f.get("n_triangles"),
                    "flags_at_start": r["flags_at_start"], "flags_set": r["flags_set"], "flags_at_end": r["flags_at_end"],
                    "devsim": r["devsim"], "wall_s": r["wall_s"], "solve_wall_s": {s: v["info"].get("wall_s") for s, v in r["steps"].items()}}
        ok_all = ok_all and good and flags_ok
    out["identity"], out["identity_all_ok"] = ident, ok_all
    e1 = {p: R.get(f"E1_M2_D0_h0.005_{p}") for p in ("P0", "P12", "P4")}
    if all(e1.values()):
        out["experiment1"] = {"self": {p: self_ok(r) for p, r in e1.items()},
                              "P12_vs_P4": equality(e1["P12"], e1["P4"]), "P0_vs_P4": equality(e1["P0"], e1["P4"]),
                              "P0_defect_reproduced": self_ok(e1["P0"]).get("status") == "SELF_VIOLATED",
                              "points": {p: {b: pm(r["steps"][b]) for b in BIASED} for p, r in e1.items() if converged(r)}}
    e2 = {}
    for P in ("P4", "P0"):
        for fx in ("1D", "M1"):
            ro, rm = R.get(f"E2_{fx}_h0.005_{P}_orig"), R.get(f"E2_{fx}_h0.005_{P}_mirror")
            if ro and rm:
                e2[f"{fx}_{P}"] = {**mirror_pair(ro, rm), "graded": P == "P4"}
    out["experiment2"] = e2
    graded = [v["verdict"] for k, v in e2.items() if v.get("graded")]
    out["final"] = {"E1_P12_equals_P4": out.get("experiment1", {}).get("P12_vs_P4", {}).get("verdict", "NOT_COMPLETED"),
                    "E2_mirror_P4": ("MIRROR_PASS" if graded and all(g == "MIRROR_PASS" for g in graded) else
                                     "MIRROR_FAIL" if "MIRROR_FAIL" in graded else
                                     "NOT_COMPLETED" if (not graded or "NOT_COMPLETED" in graded) else "INCONCLUSIVE"),
                    "E2_per_fixture": {k: v["verdict"] for k, v in e2.items()}, "identity_all_ok": ok_all, "plan_hash_matches": out["plan"]["matches"]}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "analysis_d3.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=float)
    lines = ["# 7H-D3 analysis (generated; rules from PLAN.md)", "", f"final: `{json.dumps(out['final'])}`", ""]
    if "experiment1" in out:
        lines += ["## Experiment 1: M2/D0 h=0.005 um, currents in A/cm", ""]
        for b in BIASED:
            lines += [f"### {b}", "", "| quantity | P0 | P12 | P4 | rel(P12,P4) | rel(P0,P4) |", "|---|---|---|---|---|---|"]
            pts = out["experiment1"]["points"]
            if all(p in pts for p in ("P0", "P12", "P4")):
                for k in ("C0_left", "C0_right"):
                    v = {p: pts[p][b][k] for p in pts}
                    lines.append(f"| {k} | {v['P0']:.9e} | {v['P12']:.9e} | {v['P4']:.9e} | {abs(v['P12']-v['P4'])/abs(v['P4']):.2e} | {abs(v['P0']-v['P4'])/abs(v['P4']):.2e} |")
                for c in CUTS:
                    v = {p: pts[p][b]["cuts"][c] for p in pts}
                    lines.append(f"| cut {c} | {v['P0']:.9e} | {v['P12']:.9e} | {v['P4']:.9e} | {abs(v['P12']-v['P4'])/abs(v['P4']):.2e} | {abs(v['P0']-v['P4'])/abs(v['P4']):.2e} |")
                for q in ("mis_lr", "spread", "c0L_vs_cut0", "c0R_vs_cut0", "c3_species", "c3_total"):
                    v = {p: pts[p][b][q] for p in pts}
                    lines.append(f"| {q} (self residual) | {v['P0']:.2e} | {v['P12']:.2e} | {v['P4']:.2e} | | |")
            lines.append("")
    for k, v in out["experiment2"].items():
        lines += [f"## Experiment 2 mirror {k} ({'graded' if v.get('graded') else 'control, ungraded'}): {v['verdict']}", ""]
        if "rows" in v:
            lines += ["| point | pair | original | mirror | expected mirror | rel err | state |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {r['point']} | {r['pair']} | {r['original']:.9e} | {r['mirror']:.9e} | {r['expected_mirror']:.9e} | {r['rel_err']:.2e} | {r['state']} |" for r in v["rows"]]
            lines += ["", "| point | device | v_set | p_bias | readback | n_bias | readback | V from contact potentials |", "|---|---|---|---|---|---|---|---|"]
            lines += [f"| {r['point']} | {r['device']} | {r['v_set']} | {r['p_bias_name']} | {r['p_bias_readback']} | {r['n_bias_name']} | {r['n_bias_readback']} | {r['v_from_contact_potentials']:.12f} |" for r in v["bias_rows"]]
        lines.append("")
    with open(os.path.join(a.out, "analysis_d3.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps(out["final"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
