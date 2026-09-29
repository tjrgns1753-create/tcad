"""Batch 7H-E6C SYNTHETIC judge test (no DEVSIM, no ViennaPS, no solve): eight false-PASS paths plus fake-artifact end-to-end runs built from
the real E6A geometry. Expected states are written down here BEFORE the run and never relaxed to observed results.
usage: synthetic_e6c_test.py <out json>"""
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
import judge_e6c as jc  # noqa: E402
import run_e6c as rc  # noqa: E402
jb = jc.jb

E6A_OUT = os.path.join(ROOT, "docs", "audits", "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")
ROWS = []
FLAGS = {"artifact_problems": [], "input_identity_ok": True, "resource_ok": True}


def row(case, inputs, expected, actual, ok):
    ROWS.append({"case": case, "inputs": inputs, "expected": expected, "actual": actual, "ok": bool(ok)})
    print(f"[{'OK ' if ok else 'BAD'}] {case}: expected {expected} | actual {actual}", flush=True)
    return bool(ok)


def small_common(core_empty=False):
    xs = [-5.0, -0.5, 0.5, 5.0] if core_empty else [-5.0, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 5.0]
    ys = [-5.0, -2.5, -1.0, 0.0]
    p3 = np.array([(x, y) for y in ys for x in xs], dtype=np.float32)
    p4 = np.vstack([p3, np.array([(0.025 if not core_empty else 1.0, y) for y in ys], dtype=np.float32)])
    p5 = np.vstack([p4, np.array([(-0.025 if not core_empty else -1.0, y) for y in ys], dtype=np.float32)])
    rng = np.random.default_rng(3)
    pts = {3: p3, 4: p4[rng.permutation(len(p4))], 5: p5[rng.permutation(len(p5))]}
    return jb.CommonSet(pts, np.ones(len(p3)), (p3[:, 0] * 1e-4).astype(float), (p3[:, 1] * 1e-4).astype(float))


def runs_ok(**over):
    S = {"ok": True, "converged": True, "final_rel": 3e-7, "error": None}
    r = {L: {t: {"status": None, "solve": dict(S), "consistency_ok": True} for t in jc.TAGS} for L in jc.LEVELS}
    for k, v in over.items():                       # keys like "L4Q"
        r[int(k[1])][k[2]].update(v)
    return r


def psi_sets(cs, eps, shift):
    """P_L = base + eps_L * bump; Q_L = P_L + shift_L * bump (x-only, so y-uniform)."""
    base = 0.4769 * np.tanh(cs.xcm / 5e-6)
    bump = np.cos(cs.xcm / 1e-5)
    return {L: {"P": base + eps[L] * bump, "Q": base + (eps[L] + shift[L]) * bump} for L in jc.LEVELS}


def main():
    cs = small_common()
    good = True
    # ---- 1: all converge, clear decrease ---------------------------------------------------------------
    psi = psi_sets(cs, {3: 3e-3, 4: 1e-3, 5: 8e-4}, {3: 1e-9, 4: 1e-9, 5: 1e-9})
    j = jc.judge(runs_ok(), psi, cs, FLAGS)
    good &= row("1 all P/Q converge, clear decrease", "eps 3e-3,1e-3,8e-4; A ~ 1e-9", "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY, four metrics robust",
                (j["overall"], [j["metrics"][M]["state"] for M in jc.METRICS]),
                j["overall"] == "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY"
                and all(j["metrics"][M]["state"] == "INITIALIZATION_ROBUST_DECREASE_OBSERVED" for M in jc.METRICS))
    # ---- 2: Q not converged while P/Q arrays are identical --------------------------------------------
    psi2 = psi_sets(cs, {3: 3e-3, 4: 1e-3, 5: 8e-4}, {3: 0.0, 4: 0.0, 5: 0.0})           # Q arrays bit-equal to P
    j = jc.judge(runs_ok(L4Q={"solve": {"ok": True, "converged": False, "final_rel": 3e-7, "error": None}}), psi2, cs, FLAGS)
    good &= row("2 L4-Q not converged, Q arrays == P arrays", "L4-Q converged=False; A4 would be exactly 0", "POISSON_NOT_CONVERGED; A4 None (not promoted to 0); metrics NOT_CLASSIFIED",
                (j["overall"], j["regions"]["A"]["A4"], j["metrics"]["psiLinf"]["state"]),
                j["overall"] == "POISSON_NOT_CONVERGED" and j["regions"]["A"]["A4"] is None and j["metrics"]["psiLinf"]["state"] == "NOT_CLASSIFIED")
    for tag, S in (("missing", None), ("exception", {"ok": False, "converged": False, "error": "boom"})):
        j = jc.judge(runs_ok(L3P={"solve": S}), psi, cs, FLAGS)
        good &= row(f"2b L3-P {tag}", "solve record " + tag, "POISSON_NOT_CONVERGED", j["overall"], j["overall"] == "POISSON_NOT_CONVERGED")
    j = jc.judge(runs_ok(), psi2, cs, FLAGS)
    good &= row("2c A = 0 with all solves converged", "Q == P bitwise, all converged, initialization contract fine",
                "A reported as 0.0 (an observed difference), verdict decided by the inequalities, not treated as invalid",
                (j["regions"]["A"]["A3"]["core"]["psiLinf"], j["overall"]),
                j["regions"]["A"]["A3"]["core"]["psiLinf"] == 0.0 and j["overall"] == "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY")
    # ---- 3: first two inequalities true, third false ---------------------------------------------------
    psi3 = psi_sets(cs, {3: 0.0, 4: 5e-4, 5: 5e-4 + 5e-4 - 1e-7}, {3: 1e-6, 4: 1e-6, 5: 1e-6})
    j = jc.judge(runs_ok(), psi3, cs, FLAGS)
    d = j["metrics"]["psiLinf"]["inequalities"]
    good &= row("3 ineq 1,2 true, ineq 3 false", f"ineq {d['ineq1']['holds']},{d['ineq2']['holds']},{d['ineq3']['holds']}; lhs3={d['ineq3']['lhs']:.3e} rhs3={d['ineq3']['rhs']:.3e}",
                "NO_REFINEMENT_TREND, overall INCONCLUSIVE", (j["metrics"]["psiLinf"]["state"], j["overall"]),
                d["ineq1"]["holds"] and d["ineq2"]["holds"] and not d["ineq3"]["holds"] and j["overall"] == "INCONCLUSIVE"
                and j["metrics"]["psiLinf"]["state"] == "NO_REFINEMENT_TREND")
    # ---- 4: level or P/Q indices reversed ---------------------------------------------------------------
    raised = []
    for pair in ((4, 3), (5, 4), (3, 5)):
        try:
            jb.pair_diff({L: psi[L]["P"] for L in jc.LEVELS}, pair[0], pair[1], cs)
            raised.append(False)
        except jb.PairIndexError:
            raised.append(True)
    good &= row("4a reversed level pair", "pair_diff (4,3),(5,4),(3,5)", "PairIndexError x3", raised, all(raised))
    inc = psi_sets(cs, {3: 0.0, 4: 1e-6, 5: 1e-6 + 1e-3}, {3: 1e-9, 4: 1e-9, 5: 1e-9})
    j = jc.judge(runs_ok(), inc, cs, FLAGS)
    good &= row("4b increasing changes (the pairs read in the wrong direction) are not a trend", "D34 tiny, D45 large", "NO_REFINEMENT_TREND, overall INCONCLUSIVE",
                (j["metrics"]["psiLinf"]["state"], j["overall"]), j["metrics"]["psiLinf"]["state"] == "NO_REFINEMENT_TREND" and j["overall"] == "INCONCLUSIVE")
    # ---- 5: input / import identity ---------------------------------------------------------------------
    j = jc.judge(runs_ok(), psi, cs, dict(FLAGS, input_identity_ok=False))
    good &= row("5a input sha / review-sha mismatch", "input_identity_ok False", "INPUT_IDENTITY_FAIL", j["overall"], j["overall"] == "INPUT_IDENTITY_FAIL")
    tmp = tempfile.mkdtemp(prefix="e6c_in_")
    try:
        fp = os.path.join(tmp, "PLAN.md")
        open(fp, "wb").write(b"a\r\nb\r\n")
        h_lf = rc.sha_input(fp, "text")
        open(fp, "wb").write(b"a\r\nc\r\n")
        good &= row("5b driver input hash", "text file edited after pinning (CRLF normalised)", "hash differs", h_lf != rc.sha_input(fp, "text"), h_lf != rc.sha_input(fp, "text"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    e = {L: jb.load_npz(os.path.join(E6A_OUT, f"level_L{L}.npz")) for L in (3,)}
    ref = e[3]
    x, y, vol, el = ref["x"], ref["y"], ref["NodeVolume"].copy(), ref["elements"].copy()
    xs = ref["x"]
    ok_contacts = {"Si_xmin": np.where(xs == xs.min())[0].tolist(), "Si_xmax": np.where(xs == xs.max())[0].tolist()}
    base = jc.import_identity(x, y, vol, el, ok_contacts, ["Si"], ref)
    el_dup = el.copy()
    el_dup[5] = el_dup[6]                                             # same element COUNT, different vertex-set multiset
    vol_bad = vol.copy()
    vol_bad[10] = np.nextafter(vol_bad[10], np.inf)               # a real one-ulp change
    assert vol_bad[10] != vol[10]
    bad_contacts = {"Si_xmin": ok_contacts["Si_xmin"][:-1], "Si_xmax": ok_contacts["Si_xmax"]}
    don = np.where(x >= 0, 1e18, 0.0)
    acc = np.where(x <= 0, 1e18, 0.0)
    good &= row("5c identity checks catch each tampering", "clean / one element replaced by a copy (count unchanged) / one NodeVolume +1 ulp / one contact node missing / doping x=0 wrong",
                "ok True / False / False / False / doping False",
                (base["ok"], jc.import_identity(x, y, vol, el_dup, ok_contacts, ["Si"], ref)["ok"], jc.import_identity(x, y, vol_bad, el, ok_contacts, ["Si"], ref)["ok"],
                 jc.import_identity(x, y, vol, el, bad_contacts, ["Si"], ref)["ok"], jc.doping_check(x, don, acc * 0 + 5e17, don - acc)),
                base["ok"] and not jc.import_identity(x, y, vol, el_dup, ok_contacts, ["Si"], ref)["ok"] and not jc.import_identity(x, y, vol_bad, el, ok_contacts, ["Si"], ref)["ok"]
                and not jc.import_identity(x, y, vol, el, bad_contacts, ["Si"], ref)["ok"] and not jc.doping_check(x, don, acc * 0 + 5e17, don - acc) and jc.doping_check(x, don, acc, don - acc))
    j = jc.judge(runs_ok(L4Q={"status": "IMPORT_IDENTITY_FAIL", "solve": None}), psi, cs, FLAGS)
    good &= row("5d a level failing import identity", "L4-Q status IMPORT_IDENTITY_FAIL", "IMPORT_IDENTITY_FAIL (no solve was made)", j["overall"], j["overall"] == "IMPORT_IDENTITY_FAIL")
    # ---- 6: initialization readback mismatch --------------------------------------------------------------
    vl, vr = jc.contact_potentials(0.025887193125, 1e10)
    xx = np.linspace(-5e-4, 5e-4, 101)
    want = jc.affine_init(xx, vl, vr)
    default = np.zeros_like(want)
    back_ok = want.copy()
    back_ulp = want.copy()
    back_ulp[40] = np.nextafter(back_ulp[40], np.inf)
    pre = jc.init_precheck(0.025887193125, 1e10, vl, vr, want, 1e18, -1e18, default)
    same = jc.init_precheck(0.025887193125, 1e10, vl, vr, want, 1e18, -1e18, want.copy())
    c_ok, c_ulp, c_pre = jc.init_contract(pre, want, back_ok), jc.init_contract(pre, want, back_ulp), jc.init_contract(same, want, want.copy())
    good &= row("6a initialization contract", "readback equal / one node 1 ulp off / Q identical to the default initial array",
                "contract_ok True / False / False", (c_ok["contract_ok"], c_ulp["contract_ok"], c_pre["contract_ok"]),
                c_ok["contract_ok"] and not c_ulp["contract_ok"] and not c_pre["contract_ok"] and not pre)
    good &= row("6b affine endpoints", "V_left, V_right from the contact formula; x_min / x_max nodes", "first node = V_left, last node = V_right (to rounding of the interpolation)",
                (float(want[0]), float(want[-1]), vl, vr), want[0] == vl and abs(want[-1] - vr) <= 4e-16 and vl < 0 < vr)
    # ---- 7: non-finite potential, empty core ----------------------------------------------------------------
    bad = {L: dict(v) for L, v in psi.items()}
    bad[4]["Q"] = bad[4]["Q"].copy()
    bad[4]["Q"][3] = np.nan
    j = jc.judge(runs_ok(L4Q={"consistency_ok": False}), bad, cs, FLAGS)
    good &= row("7a non-finite Q potential", "one NaN in L4-Q, consistency flag False", "CONSISTENCY_FAIL, A4 None, no numeric 0", (j["overall"], j["regions"]["A"]["A4"]),
                j["overall"] == "CONSISTENCY_FAIL" and j["regions"]["A"]["A4"] is None)
    j = jc.judge(runs_ok(), bad, cs, FLAGS)                        # even with the flag wrongly True, the NaN array must not become a number
    good &= row("7b NaN array with an optimistic flag", "NaN in L4-Q, consistency flag True", "A4 None (never a number), overall not a trend", (j["regions"]["A"]["A4"], j["overall"]),
                j["regions"]["A"]["A4"] is None and j["overall"] != "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY")
    cse = small_common(core_empty=True)
    pe = {L: {"P": np.zeros(cse.n) + 0.1 * L, "Q": np.zeros(cse.n) + 0.1 * L} for L in jc.LEVELS}
    j = jc.judge(runs_ok(), pe, cse, FLAGS)
    good &= row("7c empty core", "no node with |x| <= 0.1 um", "CONSISTENCY_FAIL, D34 absent (no number, no PASS)", (j["overall"], "D34" in j["regions"]),
                j["overall"] == "CONSISTENCY_FAIL" and "D34" not in j["regions"] and j["metrics"]["psiLinf"]["state"] == "NOT_CLASSIFIED")
    # ---- 8 and end-to-end on the real E6A geometry -------------------------------------------------------------
    good &= end_to_end()
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump({"rows": ROWS, "ALL_OK": bool(good)}, f, indent=1, default=str)
        f.write("\n")
    print("ALL_OK", good)
    return 0 if good else 1


def fake_dir(tmp, e6a, pid_q=2, solve_count_q=1, q_shift=1e-9):
    """Six fake runs on the real E6A geometry: P_L = phi + eps_L g (default zero initial potential), Q_L = P_L + shift g (affine initial)."""
    phi = lambda xx: 0.4769 * np.tanh(xx / 5e-6)  # noqa: E731
    g = lambda xx: np.cos(xx / 1e-5)  # noqa: E731
    eps = {3: 3e-3, 4: 1e-3, 5: 8e-4}
    vl, vr = jc.contact_potentials(0.025887193125, 1e10)
    for L in jc.LEVELS:
        x = e6a[L]["x"]
        ne = len(e6a[L]["EdgeCouple"])
        for tag in jc.TAGS:
            pot = phi(x) + (eps[L] + (q_shift if tag == "Q" else 0.0)) * g(x)
            arr = {"Potential": pot, "IntrinsicElectrons": np.exp(pot), "IntrinsicHoles": np.exp(-pot), "IntrinsicCharge": np.exp(-pot) - np.exp(pot),
                   "PotentialIntrinsicCharge": pot * 1e-3, "ElectricField": np.ones(ne) * 1e3, "PotentialEdgeFlux": np.ones(ne) * 1e-9}
            init = np.zeros(len(x)) if tag == "P" else jc.affine_init(x, vl, vr)
            np.savez_compressed(os.path.join(tmp, f"run_L{L}_{tag}_init.npz"), Potential=init, snapshot_call_id=np.array(f"L{L}-{tag}-init"))
            np.savez_compressed(os.path.join(tmp, f"run_L{L}_{tag}_final.npz"), snapshot_call_id=np.array(f"L{L}-{tag}"), **arr)
            rec = {"status": "OK", "process_id": 1 if tag == "P" else pid_q, "solve_count": 1 if tag == "P" else solve_count_q,
                   "init_sha256": jb.sha_arr(init),
                   "snapshot": {"call_id": f"L{L}-{tag}", "array_sha256": {k: jb.sha_arr(v) for k, v in arr.items()}},
                   "solve": {"call_id": f"L{L}-{tag}", "ok": True, "converged": True, "n_iterations": 10, "final_device_relative_error": 3e-7,
                             "final_device_absolute_error": 1e-17},
                   "edge_arrays_equal_E6A": {"n0": True, "n1": True, "EdgeCouple": True, "EdgeLength": True}}
            if tag == "Q":
                rec["initialization"] = {"V_left": vl, "V_right": vr, "contract_ok": True}
            json.dump(rec, open(os.path.join(tmp, f"run_L{L}_{tag}.json"), "w"))


def end_to_end():
    ok = True
    e6a = {L: jb.load_npz(os.path.join(E6A_OUT, f"level_L{L}.npz")) for L in jc.LEVELS}
    tmp = tempfile.mkdtemp(prefix="e6c_fake_")
    e6b = tempfile.mkdtemp(prefix="e6c_fake_b_")
    try:
        fake_dir(tmp, e6a)
        for L in jc.LEVELS:                                          # fake E6B P files: identical to the new P (reproducibility diagnostic path)
            shutil.copy(os.path.join(tmp, f"run_L{L}_P_final.npz"), os.path.join(e6b, f"level_L{L}_state_P.npz"))
        res = jc.analyze_dir(tmp, E6A_OUT, e6b, dict(FLAGS))
        ov = res["judgement"]["overall"]
        rep = res["e6b_P_reproducibility_diagnostic"]
        ok &= row("9a fake artifacts, clean", "six fake runs, Q shift 1e-9, real L3/L4/L5 geometry", "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY, no artifact problem, reproducibility diagnostic bit-equal",
                  (ov, res["artifact_problems"], {k: v["potential_bit_equal_all_nodes"] for k, v in rep.items()}),
                  ov == "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY" and not res["artifact_problems"] and all(v["potential_bit_equal_all_nodes"] for v in rep.values()))
        # 8a: Q final replaced by the P final -> tag mismatch, judged before any number
        shutil.copy(os.path.join(tmp, "run_L4_P_final.npz"), os.path.join(tmp, "run_L4_Q_final.npz"))
        r2 = jc.analyze_dir(tmp, E6A_OUT, None, dict(FLAGS))
        ok &= row("8a P/Q snapshots mixed", "run_L4_Q_final.npz := run_L4_P_final.npz", "ARTIFACT_INCOMPLETE, metrics NOT_CLASSIFIED",
                  (r2["judgement"]["overall"], r2["artifact_problems"][:2]), r2["judgement"]["overall"] == "ARTIFACT_INCOMPLETE" and any("L4-Q" in p for p in r2["artifact_problems"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="e6c_fake_")
    try:
        fake_dir(tmp, e6a, pid_q=1)                                  # P and Q recorded in the same process (sequential runs on one device)
        r3 = jc.analyze_dir(tmp, E6A_OUT, None, dict(FLAGS))
        ok &= row("8b P and Q in the same process", "process_id equal for P and Q", "ARTIFACT_INCOMPLETE", (r3["judgement"]["overall"], r3["artifact_problems"][:1]),
                  r3["judgement"]["overall"] == "ARTIFACT_INCOMPLETE" and any("same process" in p for p in r3["artifact_problems"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="e6c_fake_")
    try:
        fake_dir(tmp, e6a, solve_count_q=2)                          # a second solve in the same run
        r4 = jc.analyze_dir(tmp, E6A_OUT, None, dict(FLAGS))
        ok &= row("8c more than one solve in a run", "solve_count 2 for Q", "ARTIFACT_INCOMPLETE", (r4["judgement"]["overall"], r4["artifact_problems"][:1]),
                  r4["judgement"]["overall"] == "ARTIFACT_INCOMPLETE" and any("solve_count" in p for p in r4["artifact_problems"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="e6c_fake_")
    try:
        fake_dir(tmp, e6a)
        L = 5
        bad = jb.load_npz(os.path.join(tmp, f"run_L{L}_Q_init.npz"))
        bad["Potential"] = bad["Potential"] + 1e-6                   # saved initial Potential is not the affine array (sha recorded from the original -> also tampered)
        np.savez_compressed(os.path.join(tmp, f"run_L{L}_Q_init.npz"), **bad)
        r5 = jc.analyze_dir(tmp, E6A_OUT, None, dict(FLAGS))
        ok &= row("6c saved Q initial Potential tampered", "run_L5_Q_init.npz altered after hashing", "ARTIFACT_INCOMPLETE (init sha256 mismatch) before any judgement",
                  (r5["judgement"]["overall"], r5["artifact_problems"][:1]), r5["judgement"]["overall"] == "ARTIFACT_INCOMPLETE")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="e6c_fake_")
    try:
        fake_dir(tmp, e6a)
        L = 5
        rec = json.load(open(os.path.join(tmp, f"run_L{L}_Q.json")))
        wrong = jc.affine_init(e6a[L]["x"], -0.3, 0.3)               # a consistent (sha-matching) init array that is NOT the pre-registered affine one
        np.savez_compressed(os.path.join(tmp, f"run_L{L}_Q_init.npz"), Potential=wrong, snapshot_call_id=np.array(f"L{L}-Q-init"))
        rec["init_sha256"] = jb.sha_arr(wrong)
        json.dump(rec, open(os.path.join(tmp, f"run_L{L}_Q.json"), "w"))
        r6 = jc.analyze_dir(tmp, E6A_OUT, None, dict(FLAGS))
        ok &= row("6d saved Q initial array differs from the intended affine array (hash-consistent)", "recorded V_left/V_right vs saved initial array", "INITIALIZATION_CONTRACT_FAIL",
                  (r6["judgement"]["overall"], r6["artifact_problems"][:1]), r6["judgement"]["overall"] == "INITIALIZATION_CONTRACT_FAIL")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(e6b, ignore_errors=True)
    return ok


if __name__ == "__main__":
    sys.exit(main())
