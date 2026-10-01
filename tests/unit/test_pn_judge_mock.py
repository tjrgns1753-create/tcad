#!/usr/bin/env python3
"""E6K judge: NaN / inf / None / str never pass; each category fails independently; unit-control failure stops the numeric categories. Pure Python."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/scripts"))
import judge_e6k as J  # noqa: E402


def good():
    dev = {"production_calls": 1, "solves": 8, "expected_solves": 8, "dimension": 1, "writes_ok": True, "error": None, "converged": True}
    return {"unit": {"metadata_unit_1d": None, "metadata_dimension_1d": 1, "formatted_1d": "1.0e-06 (unit not established)", "e6j_failed_checks": 0,
                     "established_by_control": True, "control_ratio": 1.0},
            "devices": {f"L{k}_{d}": dict(dev) for k in range(3) for d in ("fwd", "rev")},
            "J": {l: {"0.3": 2e-5, "0.5": 3.7e-3, "0.6": 0.116, "-0.5": -3.3e-7, "-1.0": -5.8e-7} for l in ("L0", "L1", "L2")},
            "Emax": {l: {"0.0": 1.16e5, "-1.0": 1.72e5} for l in ("L0", "L1", "L2")}, "WE": {"L2": {"0.0": 1.43e-5, "-1.0": 2.12e-5}},
            "ref": {"0.5": {"J_model": 3.7e-3}, "0.6": {"J_model": 0.116}, "-0.5": {"J_model": -3.3e-7}, "-1.0": {"J_model": -5.8e-7}},
            "ref_E": {"0.0": {"E_max": 1.16e5, "W": 1.43e-5}, "-1.0": {"E_max": 1.72e5, "W": 2.12e-5}},
            "minority": {"s_um": [3, 5, 8], "dev": [1e12, 5e11, 1e11], "ref": [1e12, 5e11, 1e11]}}


def verdicts(m):
    return {k: v["verdict"] for k, v in J.judge(m).items()}


def main():
    v = verdicts(good())
    assert all(x == "PASS" for k, x in v.items() if k in J.CATEGORIES), v
    nan, inf = float("nan"), float("inf")
    for bad in (nan, inf, -inf, None, "x"):
        for path, cats in ((("J", "L2", "0.6"), ["E_"]), (("J", "L1", "-1.0"), ["C_", "E_"]), (("Emax", "L2", "0.0"), ["D_"]), (("WE", "L2", "-1.0"), ["D_"]),
                           (("minority", "dev", 1), ["F_"]), (("ref", "0.5", "J_model"), ["E_"]), (("ref_E", "0.0", "E_max"), ["D_"])):
            m = good()
            o = m
            for key in path[:-1]:
                o = o[key]
            o[path[-1]] = bad
            vv = verdicts(m)
            assert any(vv[c] == "FAIL" for k in cats for c in J.CATEGORIES if c.startswith(k)), (path, bad, vv)
    # each tolerance is enforced
    for mut, cat in ((lambda m: m["J"]["L2"].__setitem__("0.6", 0.116 * 1.12), "E_"), (lambda m: m["Emax"]["L2"].__setitem__("0.0", 1.16e5 * 1.05), "D_"),
                     (lambda m: m["minority"]["dev"].__setitem__(0, 1.2e12), "F_"), (lambda m: m["J"]["L1"].__setitem__("0.6", 0.116 * 1.02), "C_"),
                     (lambda m: m["devices"]["L2_rev"].__setitem__("converged", False), "C_"), (lambda m: m["devices"]["L0_fwd"].__setitem__("solves", 7), "B_"),
                     (lambda m: m["unit"].__setitem__("metadata_unit_1d", "A"), "A_"), (lambda m: m["J"]["L2"].__setitem__("-0.5", 3.3e-7), "E_")):
        m = good()
        mut(m)
        vv = verdicts(m)
        assert [vv[c] for c in J.CATEGORIES if c.startswith(cat)] == ["FAIL"], (cat, vv)
    # unit control not established: numeric categories not evaluated, never PASS
    m = good()
    m["unit"]["established_by_control"] = False
    vv = verdicts(m)
    assert all(vv[c] == "NOT_EVALUATED" for c in J.CATEGORIES[2:]), vv
    # no overall PASS key and no PN_PHYSICS_VALIDATED anywhere
    assert "PN_PHYSICS_VALIDATED" not in str(J.judge(good()))
    print("PN JUDGE TESTS PASSED")


if __name__ == "__main__":
    main()
