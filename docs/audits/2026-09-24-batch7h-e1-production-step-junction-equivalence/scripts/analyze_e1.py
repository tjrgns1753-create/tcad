"""Batch 7H-E1 analysis: PLAN sections 2-5 verdicts + production-vs-benchmark comparison table. Strict JSON output.
usage: analyze_e1.py <work dir> <out dir>"""
import json
import math
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
import common_e1 as ce  # noqa: E402

TAU, ZERO, DEN, QF, MA = 1e-5, 1e-6, 1e-6, 1e-6, 1e-6
PLAN_SHA = "ef7a3eadcd4d2e16935f95696bda257dd47c5f91f351ea08fe8fec83fd030a57"


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def shadow_verdict(s):
    if s is None:
        return {"verdict": "NOT_RUN"}
    if not s.get("identity_ok"):
        return {"verdict": "SHADOW_IDENTITY_FAIL", "identity": s.get("identity")}
    if not s.get("converged"):
        return {"verdict": "NOT_CONVERGED", "error": s.get("error"), "solve_calls": s.get("solve_calls")}
    eq, bp = s.get("equilibrium_0V"), s["bias_point"]
    c = list(bp["C0"])
    L, R = bp["C0"][c[0]]["total"], bp["C0"][c[1]]["total"]
    cuts = [v["total"] for v in bp["C2"].values()]
    i0 = bp["C2"]["+0.00"]["total"]
    scale = max(abs(v) for v in cuts)
    chk, undec = {}, []

    def rel(name, a, ref, limit):
        if ref == 0 or abs(ref) < DEN * scale:
            undec.append(name)
            chk[name] = {"value": None, "status": "UNDECIDABLE_DENOMINATOR"}
            return
        v = abs(a) / abs(ref)
        chk[name] = {"value": v, "limit": limit, "ok": v <= limit}
    rel("lr_mismatch", L + R, L, TAU)
    med = sorted(cuts)[2]
    rel("cut_spread", max(abs(v - med) for v in cuts), med, TAU)
    rel("left_vs_cut0", (L - i0) if c[0].endswith("xmin") else (L + i0), i0, TAU)
    rel("right_vs_cut0", (R + i0) if c[1].endswith("xmax") else (R - i0), i0, TAU)
    rel("c3_species", max(max(abs(v["dI_n"] - v["q_int_U"]), abs(v["dI_p"] + v["q_int_U"])) for v in bp["C3"].values()), i0, TAU)
    rel("c3_total", max(abs(v["dI_total"]) for v in bp["C3"].values()), i0, TAU)
    chk["positivity_bias"] = {"ok": bool(bp["positive_finite"])}
    if eq is None:
        chk["equilibrium"] = {"ok": False, "status": "NO_0V_SNAPSHOT"}
    else:
        chk["positivity_0V"] = {"ok": bool(eq["positive_finite"])}
        zc = all(abs(eq["C0"][k]["total"]) <= ZERO * abs(bp["C0"][k]["total"]) for k in c)
        zk = all(abs(eq["C2"][k]["total"]) <= ZERO * abs(bp["C2"][k]["total"]) for k in eq["C2"])
        chk["zero_bias_currents"] = {"ok": bool(zc and zk)}
        qf, ma = num(eq["qf_dev_V"]), num(eq["mass_action_dev"])
        chk["qf_flatness_0V"] = {"value": qf, "limit": QF, "ok": qf is not None and qf <= QF}
        chk["mass_action_0V"] = {"value": ma, "limit": MA, "ok": ma is not None and ma <= MA}
    fails = [k for k, v in chk.items() if v.get("ok") is False]
    v = "SHADOW_INCONSISTENT" if fails else ("INCONCLUSIVE" if undec else "SHADOW_CONSISTENT")
    return {"verdict": v, "failed_checks": fails, "undecidable": undec, "checks": chk}


def bench():
    f1 = json.load(open(os.path.join(ROOT, "docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixtures_d1.json"), encoding="utf-8"))
    fx = json.load(open(os.path.join(ROOT, "docs/audits/2026-09-23-batch7h-d2-current-precision/data/fixed_d2.json"), encoding="utf-8"))
    return {k: f1[k]["quality"] for k in ("M1_h0.005", "M2_h0.005")}, fx


def main():
    work, outd = sys.argv[1], sys.argv[2]
    os.makedirs(outd, exist_ok=True)
    prod = ce.load_strict(os.path.join(work, "prod.json"))
    sh = {v: (ce.load_strict(os.path.join(work, f"shadow_{v}.json")) if os.path.exists(os.path.join(work, f"shadow_{v}.json")) else None)
          for v in ("S0", "S12")}
    plan = ce.sha(open(os.path.join(HERE, "..", "PLAN.md"), "rb").read().replace(b"\r\n", b"\n"))
    out = {"plan_sha256": plan, "plan_matches": plan == PLAN_SHA, "control": prod.get("control"),
           "prod_error": prod.get("error"), "shadows": {v: shadow_verdict(s) for v, s in sh.items()}}
    q, dp = prod.get("mesh_quality", {}), prod.get("doping_prechecks", {})
    qb, fx = bench()
    b1, b2 = qb["M1_h0.005"], qb["M2_h0.005"]
    rows = []

    def row(name, p, b, same):
        rows.append({"property": name, "production": p, "benchmark_D2_D4": b, "same": same})
    pr = prod.get("region_facts", {}).get("Si", {})
    row("domain Si x range (um)", pr.get("x_range_um"), [-0.5, 0.5], pr.get("x_range_um") == [-0.5, 0.5])
    row("domain Si y range (um)", pr.get("y_range_um"), [0.0, 0.1], pr.get("y_range_um") == [0.0, 0.1])
    row("regions", prod.get("regions"), ["Si"], prod.get("regions") == ["Si"])
    row("Si nodes / triangles", [q.get("n_nodes"), q.get("n_triangles")], {"M1": [b1["n_nodes"], b1["n_triangles"]], "M2": [b2["n_nodes"], b2["n_triangles"]]}, False)
    row("angle classes", q.get("classes"), {"M1": b1["classes"], "M2": b2["classes"]}, None)
    row("max angle (deg)", q.get("max_angle_deg"), 90.0, q.get("max_angle_deg") is not None and q.get("max_angle_deg") <= 90.0)
    row("exact Delaunay violations", q.get("exact_delaunay_violations_interior"), 0, q.get("exact_delaunay_violations_interior") == 0)
    row("boundary Gabriel violations", q.get("boundary_gabriel_violations"), 0, q.get("boundary_gabriel_violations") == 0)
    row("negative signed edge couples", (q.get("signed_edge_couple") or {}).get("negative"), 0, (q.get("signed_edge_couple") or {}).get("negative") == 0)
    row("negative signed node volumes", (q.get("signed_node_volume") or {}).get("negative"), 0, (q.get("signed_node_volume") or {}).get("negative") == 0)
    row("DEVSIM sum NodeVolume / exact area", q.get("devsim_sum_NodeVolume_over_exact_area"), 1.0, None)
    row("nodes exactly at x = 0", dp.get("nodes_x_eq_0"), 0, dp.get("nodes_x_eq_0") == 0)
    row("junction representation", dp.get("representation"), "J1 (no node on x = 0, dual boundary exactly on x = 0)", dp.get("nodes_x_eq_0") == 0)
    row("NetDoping at x = 0 nodes (cm^-3)", dp.get("netdoping_at_x0_values"), "no such node", None)
    row("N_A / N_D (cm^-3)", [ce.GUI["doping"]["acceptor_conc_cm3"], ce.GUI["doping"]["donor_conc_cm3"]], [1e17, 1e17], False)
    row("dopant inventory donor / acceptor (cm^-1)", [dp.get("inventory_donor_cm-1"), dp.get("inventory_acceptor_cm-1")], "N x side area exactly (J1)", None)
    row("x = 0 control-volume area (cm^2)", dp.get("sum_NodeVolume_x0_cm2"), 0.0, dp.get("sum_NodeVolume_x0_cm2") == 0.0)
    row("contacts", prod.get("contacts"), ["left", "right"], None)
    row("contact x positions (um)", prod.get("contact_x_um"), [-0.5, 0.5], None)
    row("mesh spacing near junction (um)", prod.get("mesh_spacing"), "uniform 0.005 (M2) / irregular non-obtuse (M1), half cells at contacts", None)
    for v, s in sh.items():
        if s and s.get("parameters"):
            row(f"material parameters ({v} readback)", s["parameters"], "same production setup functions (T 300 K, n_i 1e10, mu_n 400, mu_p 200, taun = taup 1e-8)", None)
    row("solver rule", "production routine: Poisson abs 1.0 / rel 1e-6; DD abs 1e10 / rel 1e-6; 100 it; no info", fx["solver"], False)
    row("precision flags", "none (production default)", "P12 / P4 in D3/D4", False)
    row("bias", "single jump to +0.3 V on the max-x (n) contact = 0.3 V reverse", "p contact ramp 0.025 V steps to +-0.10 V", False)
    out["comparison"] = rows
    out["prechecks"] = {"mesh_quality": q, "doping": dp, "capture": prod.get("capture"), "barrier_windows": prod.get("barrier_windows"),
                        "state": prod.get("state"), "dimension": prod.get("dimension"), "contact_facts": prod.get("contact_facts")}
    out["mesh_convergence"] = "UNVERIFIED (one production mesh; no refinement study registered)"
    ce.dump_strict(out, os.path.join(outd, "analysis_e1.json"))
    print(json.dumps({"plan_matches": out["plan_matches"], "control": (out["control"] or {}).get("verdict"),
                      "shadows": {k: v["verdict"] for k, v in out["shadows"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
