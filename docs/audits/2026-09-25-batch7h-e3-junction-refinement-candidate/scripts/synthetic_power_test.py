"""Batch 7H-E3 SYNTHETIC test (no ViennaPS / DEVSIM): proves the corrected control logic in controls_power.py cannot
reproduce 7H-E2's flaw -- comparing an unmodified input to itself can never yield a cause-exclusion verdict.
usage: synthetic_power_test.py <work dir>"""
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import controls_power as cp  # noqa: E402


def main():
    work = os.path.abspath(sys.argv[1])
    os.makedirs(work, exist_ok=True)
    res, ok = {}, True

    # Case 1: reproduce 7H-E2's exact flaw on purpose -- a null manipulation (n_changed=0) compared to itself.
    # Even though the "comparison" trivially reports equal (it's the same object), the verdict must NOT be a
    # no-effect / cause-exclusion string.
    v = cp.powered_verdict("orientation", n_changed=0, n_total=247000, comparison_equal_within_budget=True)
    case1_ok = v["verdict"] == "CONTROL_NOT_POWERED" and "cannot exclude a cause" in v["reason"]
    res["null_control_cannot_exclude_cause"] = {"verdict": v, "ok": case1_ok}
    ok &= case1_ok

    # Case 2: the same null manipulation, but the (meaningless) comparison reports UNEQUAL -- still must not be
    # read as a positive "effect" claim about a manipulation that changed nothing to begin with.
    v2 = cp.powered_verdict("orientation", n_changed=0, n_total=247000, comparison_equal_within_budget=False)
    case2_ok = v2["verdict"] == "CONTROL_NOT_POWERED"
    res["null_control_no_effect_claim_either"] = {"verdict": v2, "ok": case2_ok}
    ok &= case2_ok

    # Case 3: a genuinely powered manipulation (reverse_all_windings) on a synthetic triangle list -- n_changed
    # must equal every triangle, unconditionally, regardless of input winding (unlike E2's ccw_only which depended
    # on the input already containing negative-oriented triangles).
    for tris, name in (([(0, 1, 2), (2, 1, 3)], "all_ccw_input"), ([(0, 2, 1), (2, 3, 1)], "all_cw_input")):
        rev, n_changed = cp.reverse_all_windings(tris)
        case_ok = n_changed == len(tris) and rev != tris and all(r != t for r, t in zip(rev, tris))
        res[f"reverse_all_windings_powered_{name}"] = {"n_changed": n_changed, "n_total": len(tris), "ok": case_ok}
        ok &= case_ok

    # Case 4: powered control, equal readback -> a real NO_EFFECT verdict (not CONTROL_NOT_POWERED).
    v4 = cp.powered_verdict("orientation", n_changed=247000, n_total=247000, comparison_equal_within_budget=True)
    case4_ok = v4["verdict"] == "ORIENTATION_NO_EFFECT" and v4["changed_fraction"] == 1.0
    res["powered_control_no_effect"] = {"verdict": v4, "ok": case4_ok}
    ok &= case4_ok

    # Case 5: powered control, unequal readback -> a real EFFECT verdict.
    v5 = cp.powered_verdict("orientation", n_changed=247000, n_total=247000, comparison_equal_within_budget=False)
    case5_ok = v5["verdict"] == "ORIENTATION_EFFECT"
    res["powered_control_effect"] = {"verdict": v5, "ok": case5_ok}
    ok &= case5_ok

    # Case 6: partially powered control (e.g. only some triangles changed) -- still counts as powered if n_changed>0.
    v6 = cp.powered_verdict("shape", n_changed=1600, n_total=247000, comparison_equal_within_budget=False)
    case6_ok = v6["verdict"] == "SHAPE_EFFECT" and abs(v6["changed_fraction"] - 1600 / 247000) < 1e-12
    res["partially_powered_control"] = {"verdict": v6, "ok": case6_ok}
    ok &= case6_ok

    res["ALL_OK"] = bool(ok)
    json.dump(res, open(os.path.join(work, "synthetic_power_results.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
