"""Batch 7H-E6B SYNTHETIC judge test (no DEVSIM, no ViennaPS, no solve): eight false-PASS paths plus one fake-artifact end-to-end
run built from the real E6A geometry. Expected states are written down here BEFORE the run and never adjusted to results.
usage: synthetic_e6b_test.py <out json>"""
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
import judge_e6b as jd  # noqa: E402

E6A_OUT = os.path.join(ROOT, "docs", "audits", "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")
ROWS = []


def row(case, inputs, expected, actual, ok):
    ROWS.append({"case": case, "inputs": inputs, "expected": expected, "actual": actual, "ok": bool(ok)})
    print(f"[{'OK ' if ok else 'BAD'}] {case}: expected {expected} | actual {actual}", flush=True)
    return bool(ok)


# ---------------------------------------------------------------- tiny nested common set
def small_common():
    xs = [-5.0, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 5.0]
    ys = [-5.0, -2.5, -1.0, 0.0]
    p3 = np.array([(x, y) for y in ys for x in xs], dtype=np.float32)
    p4 = np.vstack([p3, np.array([(0.025, y) for y in ys], dtype=np.float32)])
    p5 = np.vstack([p4, np.array([(-0.025, y) for y in ys], dtype=np.float32)])
    rng = np.random.default_rng(7)
    pts = {3: p3, 4: p4[rng.permutation(len(p4))], 5: p5[rng.permutation(len(p5))]}      # levels in a different node order
    xcm = (p3[:, 0] * 1e-4).astype(float)
    ycm = (p3[:, 1] * 1e-4).astype(float)
    cs = jd.CommonSet(pts, np.ones(len(p3)), xcm, ycm)
    return cs, p3


def levels_ok(**over):
    P = {"ok": True, "converged": True, "final_rel": 2e-7, "error": None}
    C = {"ok": True, "converged": True, "final_rel": 1e-13, "error": None}
    lv = {L: {"status": None, "P": dict(P), "C": dict(C), "consistency_ok": True} for L in jd.LEVELS}
    for k, v in over.items():
        lv[int(k[1])].update(v)
    return lv


def psi_family(cs, e3, e4, e5, s=(1e-9, 1e-9, 1e-9), scale=None):
    """psi_L = base + eps_L * bump(x) on the common nodes (x-only, so y-uniform); C = P + s_L * bump."""
    base = 0.4769 * np.tanh(cs.xcm / 5e-6)
    bump = np.cos(cs.xcm / 1e-5)
    eps = {3: e3, 4: e4, 5: e5}
    return {L: {"P": base + eps[L] * bump, "C": base + eps[L] * bump + s[L - 3] * bump} for L in jd.LEVELS}


FLAGS = {"artifact_problems": [], "input_identity_ok": True, "resource_ok": True}


def main():
    cs, p3 = small_common()
    good = True
    # ---- case 1: D34 / D45 indices reversed -------------------------------------------------
    psi = psi_family(cs, 3e-3, 1e-3, 8e-4)                       # clear decrease (control)
    j = jd.judge(levels_ok(), psi, cs, FLAGS)
    good &= row("0 control: clear decrease", "eps3,4,5 = 3e-3,1e-3,8e-4; S = 1e-9", "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY",
                j["overall"], j["overall"] == "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY")
    raised = []
    for pair in ((4, 3), (5, 4), (3, 5), (3, 3)):
        try:
            jd.pair_diff({L: psi[L]["P"] for L in jd.LEVELS}, pair[0], pair[1], cs)
            raised.append(False)
        except jd.PairIndexError:
            raised.append(True)
    good &= row("1a reversed/invalid pair refused", "pair_diff(a,b) for (4,3),(5,4),(3,5),(3,3)", "PairIndexError x4", raised, all(raised))
    inc = psi_family(cs, 0.0, 1e-6, 1e-6 + 1e-3)                # increasing changes: D34 tiny, D45 large
    j = jd.judge(levels_ok(), inc, cs, FLAGS)
    d = j["metrics"]["psiLinf"]
    swapped = jd.discriminant(d["D45"], d["D34"], 1e-9, 1e-9, 1e-9)       # what an index swap would evaluate
    good &= row("1b increasing sequence must not be a trend", f"D34={d['D34']:.3e} D45={d['D45']:.3e}; a swapped evaluation would say "
                f"ineq3 {swapped['ineq3']['holds']}", "psiLinf NO_REFINEMENT_TREND, overall INCONCLUSIVE",
                (d["state"], j["overall"]), d["state"] == "NO_REFINEMENT_TREND" and j["overall"] == "INCONCLUSIVE"
                and swapped["ineq3"]["holds"] is True)
    # ---- case 2: third inequality fails while the first two pass; OUTER_FLOOR_SUSPECTED forbidden ------------
    psi = psi_family(cs, 0.0, 5e-4, 5e-4 + 5e-4 - 1e-7, s=(1e-6, 1e-6, 1e-6))
    j = jd.judge(levels_ok(), psi, cs, FLAGS)
    d = j["metrics"]["psiLinf"]["inequalities"]
    ref = fake_reference(cs, psi, floor=True)
    ra = jd.reference_assessment(ref, j, psi, cs)
    good &= row("2 ineq3 fails, ineq1/2 pass", f"ineq1 {d['ineq1']['holds']} ineq2 {d['ineq2']['holds']} ineq3 {d['ineq3']['holds']} "
                f"(lhs3={d['ineq3']['lhs']:.3e} rhs3={d['ineq3']['rhs']:.3e}); floor-like reference gap present",
                "psiLinf NO_REFINEMENT_TREND, overall INCONCLUSIVE, reference REFERENCE_INCONCLUSIVE (never OUTER_FLOOR_SUSPECTED)",
                (j["metrics"]["psiLinf"]["state"], j["overall"], ra["overall"]),
                d["ineq1"]["holds"] and d["ineq2"]["holds"] and not d["ineq3"]["holds"] and j["metrics"]["psiLinf"]["state"]
                == "NO_REFINEMENT_TREND" and j["overall"] == "INCONCLUSIVE" and ra["overall"] == "REFERENCE_INCONCLUSIVE")
    # positive path of the reference precedence (T true, gap above V, gap reduction not resolved)
    psi = psi_family(cs, 3e-3, 1e-3, 8e-4)
    j = jd.judge(levels_ok(), psi, cs, FLAGS)
    ref = fake_reference(cs, psi, floor=True)
    ra = jd.reference_assessment(ref, j, psi, cs)
    good &= row("2b reference precedence: floor-like case with a real trend", "T(M) true, G_L5 > V, Delta_G <= W", "OUTER_FLOOR_SUSPECTED",
                ra["overall"], ra["overall"] == "OUTER_FLOOR_SUSPECTED")
    # ---- case 3: control not converged but P/C differ by ~0 ----------------------------------
    psi = psi_family(cs, 3e-3, 1e-3, 8e-4, s=(1e-9, 1e-15, 1e-9))
    lv = levels_ok(L4={"C": {"ok": True, "converged": False, "final_rel": 3e-9, "error": None}})
    j = jd.judge(lv, psi, cs, FLAGS)
    good &= row("3 L4-C not converged, P/C shift ~1e-15", "L4-C converged=False, |psi_C-psi_P| ~ 1e-15; D34,D45 look like a clean trend",
                "SOLVER_CONTROL_INVALID; S4 not used; metrics NOT_CLASSIFIED",
                (j["overall"], j["regions"]["S"]["S4"], j["metrics"]["psiLinf"]["state"]),
                j["overall"] == "SOLVER_CONTROL_INVALID" and j["regions"]["S"]["S4"] is None
                and all(j["metrics"][M]["state"] == "NOT_CLASSIFIED" for M in jd.METRICS))
    for tag, C in (("missing", None), ("exception", {"ok": False, "converged": False, "error": "boom"}),
                   ("worse than primary", {"ok": True, "converged": True, "final_rel": 5e-7, "error": None})):
        j = jd.judge(levels_ok(L4={"C": C}), psi_family(cs, 3e-3, 1e-3, 8e-4), cs, FLAGS)
        good &= row(f"3b L4-C {tag}", "control record " + tag, "SOLVER_CONTROL_INVALID", j["overall"], j["overall"] == "SOLVER_CONTROL_INVALID")
    # ---- cases 4-6: Gauss diagnostic ----------------------------------------------------------
    g = chain_graph()
    R = g["delta"](np.array([0, 0, -5.0, 1e-9, 0, 0]))
    out = jd.gauss_diagnostic(*R["args"])
    signed = R["signed_max_ratio"]
    good &= row("4 large negative + small positive residual", f"bulk deltas = -5.0 (node 2), +1e-9 (node 3); signed max ratio would be {signed:.2e}",
                "abs ratio reveals the large negative residual (> 1e3 x the signed maximum)",
                out["ratios_max_abs"]["correct"], out["ratios_max_abs"]["correct"] is not None and out["ratios_max_abs"]["correct"] > 1e3 * max(signed, 1e-30)
                and not out["states"])
    R = g["delta"](np.array([1e3, 0, 0, 0, 0, -1e3]))
    out = jd.gauss_diagnostic(*R["args"])
    cont = out["contact_residual_diagnostic"]["correct"]
    good &= row("5 residual large only at the contacts", "contact deltas +-1e3, bulk deltas 0",
                "bulk ratio ~0 (< 1e-12) reported separately from a large contact ratio; contacts excluded from n_eligible",
                {"bulk": out["ratios_max_abs"]["correct"], "contact": cont["max_abs_ratio"], "n_eligible": out["n_eligible"]},
                out["ratios_max_abs"]["correct"] < 1e-12 and cont["max_abs_ratio"] > 0.1 and out["n_eligible"] == 4)
    a0 = list(g["args"](np.zeros(6)))
    a0[3], a0[5] = np.zeros(5), np.zeros(6)                        # PEF = 0, PIC = 0 -> every s_i = 0
    o1 = jd.gauss_diagnostic(*a0)
    a1 = list(g["args"](np.zeros(6)))
    a1[3] = np.array([1.0, np.nan, 1.0, 1.0, 1.0])
    o2 = jd.gauss_diagnostic(*a1)
    a2 = list(g["args"](np.zeros(6)))
    a2[6] = np.ones(6, dtype=bool)                                  # every node is a contact -> no eligible node
    o3 = jd.gauss_diagnostic(*a2)
    a3 = list(g["args"](np.array([0, 0.1, 0, 0, 0, 0])))
    a3[7] = np.array([-5.0, -0.1, 0.1, 0.2, 0.3, 5.0]) * 1e-4      # no x = 0 node
    o4 = jd.gauss_diagnostic(*a3)
    none_all = lambda o: all(v is None for v in o["ratios_max_abs"].values())  # noqa: E731
    good &= row("6a all s_i = 0", "PEF = 0, PIC = 0", "DIAG_INVALID_MAX_S_ZERO, ratios null (not 0, not PASS)", (o1["states"], o1["ratios_max_abs"]["correct"]),
                o1["states"] == ["DIAG_INVALID_MAX_S_ZERO"] and none_all(o1))
    good &= row("6b non-finite flux", "one NaN in PEF", "DIAG_INVALID_NONFINITE, ratios null", (o2["states"], o2["ratios_max_abs"]["correct"]),
                "DIAG_INVALID_NONFINITE" in o2["states"] and none_all(o2))
    good &= row("6c no non-contact node", "all nodes are contacts", "DIAG_INVALID_NO_ELIGIBLE_NODES, ratios null", (o3["states"], o3["ratios_max_abs"]["correct"]),
                o3["states"] == ["DIAG_INVALID_NO_ELIGIBLE_NODES"] and none_all(o3))
    good &= row("6d no x = 0 representative", "no eligible node at x = 0", "DIAG_DEGENERATE_NO_X0_REPRESENTATIVE, ratios still stored",
                (o4["states"], o4["ratios_max_abs"]["correct"] is not None), o4["states"] == ["DIAG_DEGENERATE_NO_X0_REPRESENTATIVE"]
                and o4["ratios_max_abs"]["correct"] is not None)
    # ---- case 7: 1D reference failed, 2D valid ---------------------------------------------------
    psi = psi_family(cs, 3e-3, 1e-3, 8e-4)
    j = jd.judge(levels_ok(), psi, cs, FLAGS)
    ra = jd.reference_assessment({"usable": False, "reason": "R7-C invalid: C_NOT_CONVERGED_OR_ERROR"}, j, psi, cs)
    good &= row("7 R7-C failed, 2D valid", "reference usable=False; 2D controls valid", "reference REFERENCE_1D_UNUSABLE, 2D overall unchanged (trend), D/S kept",
                (ra["overall"], j["overall"], j["metrics"]["psiLinf"]["D34"] is not None),
                ra["overall"] == "REFERENCE_1D_UNUSABLE" and j["overall"] == "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY" and j["metrics"]["psiLinf"]["D34"] is not None)
    # ---- case 8: mixed / mismatched artifacts -------------------------------------------------------
    arrs = {k: np.linspace(0, 1, 5) + i for i, k in enumerate(jd.REQUIRED_STATE_ARRAYS)}
    recP = {"call_id": "L4-P", "array_sha256": {k: jd.sha_arr(v) for k, v in arrs.items()}}
    ok_arr = dict(arrs, snapshot_call_id=np.array("L4-P"))
    p_ok = jd.verify_state_artifact(recP, ok_arr, "L4-P")
    p_mix = jd.verify_state_artifact(recP, dict(arrs, snapshot_call_id=np.array("L4-C")), "L4-P")      # C batch presented as P
    tam = dict(ok_arr)
    tam["Potential"] = arrs["Potential"] + 1e-12
    p_sha = jd.verify_state_artifact(recP, tam, "L4-P")
    good &= row("8a artifact checks", "clean / C-tagged batch used as P / one array altered by 1e-12", "no problem / tag problem / sha problem",
                (len(p_ok), len(p_mix), len(p_sha)), len(p_ok) == 0 and len(p_mix) >= 1 and len(p_sha) >= 1)
    j = jd.judge(levels_ok(), psi, cs, {"artifact_problems": ["L4-P: npz snapshot_call_id 'L4-C'"], "input_identity_ok": True, "resource_ok": True})
    good &= row("8b judge blocks on artifact problems", "artifact_problems non-empty; otherwise clean trend data", "ARTIFACT_INCOMPLETE, metrics NOT_CLASSIFIED",
                (j["overall"], j["metrics"]["psiLinf"]["state"]), j["overall"] == "ARTIFACT_INCOMPLETE" and j["metrics"]["psiLinf"]["state"] == "NOT_CLASSIFIED")
    # ---- end-to-end on the real E6A geometry with fabricated states ----------------------------------
    good &= end_to_end()
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump({"rows": ROWS, "ALL_OK": bool(good)}, f, indent=1, default=str)
        f.write("\n")
    print("ALL_OK", good)
    return 0 if good else 1


def fake_reference(cs, psi, floor):
    """A usable 1D reference whose distance to the 2D levels is dominated by a floor-like offset at one node's x."""
    ux = np.unique(cs.xcm)
    base = 0.4769 * np.tanh(ux / 5e-6)
    off = np.zeros(len(ux))
    if floor:
        off[np.argmin(np.abs(ux - ux[len(ux) // 2 + 1]))] = 5e-2     # shifts the reference away from every 2D level at one x
    r7 = base + off
    w = np.zeros(len(ux))
    np.add.at(w, np.searchsorted(ux, cs.xcm[~cs.contact]), cs.w[~cs.contact])
    return {"usable": True, "x": ux, "w": w, "R7P": r7, "R7C": r7 + 1e-9, "R6P": r7 + 1e-6, "R6C": r7 + 1e-6 + 1e-9}


def chain_graph():
    """6-node chain, edges (i,i+1), nodes 0 and 5 are contacts. R_i = delta_i by construction (charge cancels the flux divergence)."""
    n0, n1 = np.arange(5), np.arange(1, 6)
    EC = np.array([1.0, 2.0, 0.5, 1.5, 1.0])
    PEF = np.array([0.7, -0.3, 1.1, 0.2, -0.9])
    NV = np.ones(6)
    F = PEF * EC
    div = np.bincount(n0, F, minlength=6) - np.bincount(n1, F, minlength=6)
    contact = np.array([True, False, False, False, False, True])
    x = np.array([-5.0, -0.1, 0.0, 0.1, 0.2, 5.0]) * 1e-4
    y = np.array([-2.5, 0.0, -2.5, -2.5, -5.0, -2.5]) * 1e-4        # bulk nodes hit both the top (0) and the bottom (-5) row

    def args(delta):
        PIC = (-div + delta) / NV
        return (n0, n1, EC, PEF, NV, PIC, contact, x, y)

    def delta(d):
        a = args(d)
        F_ = PEF * EC
        s = np.bincount(n0, np.abs(F_), minlength=6) + np.bincount(n1, np.abs(F_), minlength=6) + np.abs(NV * a[5])
        R = div + NV * a[5]
        bulk = ~contact
        return {"args": a, "signed_max_ratio": float(np.max((R / s)[bulk]))}
    return {"args": args, "delta": delta}


def end_to_end():
    """Fake artifacts on the real E6A geometry (441733-node L5): fabricated smooth potentials and a fabricated reference, then
    jd.analyze_dir. Exercises loading, sha / tag verification, common-node mapping, consistency, judgement and the reference."""
    tmp = tempfile.mkdtemp(prefix="e6b_fake_")
    ok = True
    try:
        e6a = {L: jd.load_npz(os.path.join(E6A_OUT, f"level_L{L}.npz")) for L in jd.LEVELS}
        ux = np.unique(e6a[3]["x"])
        phi = lambda xx: 0.4769 * np.tanh(xx / 5e-6)  # noqa: E731
        g = lambda xx: np.cos(xx / 1e-5)  # noqa: E731
        eps = {3: 3e-3, 4: 1e-3, 5: 8e-4}
        for L in jd.LEVELS:
            e = e6a[L]
            x, y = e["x"], e["y"]
            static = {"x": x, "y": y, "elements": e["elements"].astype(np.int32), "NodeVolume": e["NodeVolume"],
                      "Donors": np.where(x >= 0, 1e18, 0.0), "Acceptors": np.where(x <= 0, 1e18, 0.0),
                      "NetDoping": np.where(x >= 0, 1e18, 0.0) - np.where(x <= 0, 1e18, 0.0), "edge_n0": e["edge_n0"].astype(np.int32),
                      "edge_n1": e["edge_n1"].astype(np.int32), "EdgeCouple": e["EdgeCouple"], "EdgeLength": e["EdgeLength"]}
            np.savez_compressed(os.path.join(tmp, f"level_L{L}_static.npz"), **static)
            snaps, recs = {}, {}
            for tag, sh in (("P", 0.0), ("C", 1e-9)):
                pot = phi(x) + (eps[L] + sh) * g(x)
                arr = {"Potential": pot, "IntrinsicElectrons": np.exp(pot), "IntrinsicHoles": np.exp(-pot), "IntrinsicCharge": np.exp(-pot) - np.exp(pot),
                       "PotentialIntrinsicCharge": pot * 1e-3, "ElectricField": np.ones(len(e["EdgeCouple"])) * 1e3,
                       "PotentialEdgeFlux": np.ones(len(e["EdgeCouple"])) * 1e-9}
                recs[tag] = {"call_id": f"L{L}-{tag}", "array_sha256": {k: jd.sha_arr(v) for k, v in arr.items()}}
                np.savez_compressed(os.path.join(tmp, f"level_L{L}_state_{tag}.npz"), snapshot_call_id=np.array(f"L{L}-{tag}"), **arr)
            solve = lambda cid, rel: {"call_id": cid, "ok": True, "converged": True, "n_iterations": 3, "final_device_relative_error": rel,  # noqa: E731
                                      "final_device_absolute_error": 1e-17}
            rec = {"status": "OK", "solve_calls": [solve(f"L{L}-P", 2e-7), solve(f"L{L}-C", 1e-13)], "snapshots": recs,
                   "static_sha256": {k: jd.sha_arr(v) for k, v in static.items()}, "identity": {"ok": True}, "doping": {"x0_ok": True}}
            json.dump(rec, open(os.path.join(tmp, f"level_L{L}.json"), "w"))
        for m in (6, 7):
            arrays = {"x": ux, "Potential_after_P": phi(ux) + (1e-6 if m == 6 else 0.0), "Potential_after_C": phi(ux) + (1e-6 if m == 6 else 0.0) + 1e-9,
                      "snapshot_call_id_P": np.array(f"R{m}-P"), "snapshot_call_id_C": np.array(f"R{m}-C")}
            np.savez_compressed(os.path.join(tmp, f"ref_R{m}.npz"), **arrays)
            solve = lambda cid, rel: {"call_id": cid, "ok": True, "converged": True, "n_iterations": 3, "final_device_relative_error": rel}  # noqa: E731
            json.dump({"status": "OK", "solve_calls": [solve(f"R{m}-P", 1e-7), solve(f"R{m}-C", 1e-13)],
                       "array_sha256": {k: jd.sha_arr(v) for k, v in arrays.items() if not k.startswith("snapshot_call_id")}},
                      open(os.path.join(tmp, f"ref_R{m}.json"), "w"))
        res = jd.analyze_dir(tmp, E6A_OUT, dict(FLAGS))
        ov = res["judgement"]["overall"]
        ok &= row("9a fake artifacts, clean trend", "fabricated smooth potentials on the real L3/L4/L5 geometry; controls shift 1e-9",
                  "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY, reference REFERENCE_INCONCLUSIVE (gap still decreasing)",
                  (ov, res["reference"]["overall"], res["artifact_problems"]),
                  ov == "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY" and not res["artifact_problems"] and res["reference"]["overall"] == "REFERENCE_INCONCLUSIVE")
        # 9b: R7 control not converged -> only the 1D reference becomes unusable; the 2D judgement is untouched
        rec7 = json.load(open(os.path.join(tmp, "ref_R7.json")))
        rec7["solve_calls"][1]["converged"] = False
        json.dump(rec7, open(os.path.join(tmp, "ref_R7.json"), "w"))
        res3 = jd.analyze_dir(tmp, E6A_OUT, dict(FLAGS))
        ok &= row("9b fake artifacts, R7-C not converged", "ref_R7.json solve R7-C converged := False",
                  "reference REFERENCE_1D_UNUSABLE, 2D overall still LOCAL_JUNCTION_REFINEMENT_TREND_ONLY",
                  (res3["reference"]["overall"], res3["judgement"]["overall"], res3["reference"].get("reason")),
                  res3["reference"]["overall"] == "REFERENCE_1D_UNUSABLE" and res3["judgement"]["overall"] == "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY")
        # 9c: the L4 C-state file is replaced by the L4 P-state file -> tag mismatch must block the judgement
        shutil.copy(os.path.join(tmp, "level_L4_state_P.npz"), os.path.join(tmp, "level_L4_state_C.npz"))
        res2 = jd.analyze_dir(tmp, E6A_OUT, dict(FLAGS))
        ok &= row("9c fake artifacts, L4 C file replaced by the P file", "level_L4_state_C.npz := level_L4_state_P.npz",
                  "ARTIFACT_INCOMPLETE before any judgement", (res2["judgement"]["overall"], res2["artifact_problems"][:2]),
                  res2["judgement"]["overall"] == "ARTIFACT_INCOMPLETE" and any("L4-C" in p for p in res2["artifact_problems"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == "__main__":
    sys.exit(main())
