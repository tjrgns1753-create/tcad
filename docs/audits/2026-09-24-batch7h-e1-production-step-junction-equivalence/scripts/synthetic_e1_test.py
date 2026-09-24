"""Batch 7H-E1 SYNTHETIC test (no physics, no ViennaPS/DEVSIM): strict-JSON handling and analyze_e1 verdict logic.
Cases: consistent, conservation_fail, not_converged, identity_fail, nonfinite_qf, undecidable.
usage: synthetic_e1_test.py <work dir>"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common_e1 as ce  # noqa: E402

CUTS = ["-0.25", "-0.10", "+0.00", "+0.10", "+0.25"]


def point(I, scale0=1.0):
    return {"C0": {"Si_xmin": {"n": 0.3 * I, "p": 0.7 * I, "total": I}, "Si_xmax": {"n": -0.3 * I, "p": -0.7 * I, "total": -I}},
            "C1": {}, "C2": {c: {"n": 0.3 * I, "p": 0.7 * I, "total": I * scale0} for c in CUTS},
            "C3": {f"{a}..{b}": {"dI_n": 0.0, "dI_p": 0.0, "q_int_U": 0.0, "dI_total": 0.0} for a, b in zip(CUTS[:-1], CUTS[1:])},
            "positive_finite": True, "qf_dev_V": 1e-12, "mass_action_dev": 1e-12}


def shadow(case):
    s = {"identity_ok": True, "converged": True, "parameters": {"T": 300.0}, "bias_point": point(-2e-15), "equilibrium_0V": point(1e-30)}
    if case == "conservation_fail":
        s["bias_point"]["C2"]["+0.10"]["total"] *= 1 + 1e-3
    if case == "not_converged":
        s.update({"converged": False, "error": "Convergence failure"})
    if case == "identity_fail":
        s.update({"identity_ok": False, "identity": {"x_sha256_equal": False}})
    if case == "nonfinite_qf":
        s["equilibrium_0V"]["qf_dev_V"] = float("nan")
    if case == "undecidable":        # every current exactly 0: all relative checks undecidable, none failing
        s["bias_point"], s["equilibrium_0V"] = point(0.0), point(0.0)
    return s


def main():
    work = os.path.abspath(sys.argv[1])
    res, ok_all = {}, True
    # strict JSON: NaN/Inf become status objects and the file parses strictly
    p = os.path.join(work, "strict.json")
    os.makedirs(work, exist_ok=True)
    ce.dump_strict({"a": float("nan"), "b": [float("inf"), 1.0]}, p)
    txt = open(p, encoding="utf-8").read()
    strict_ok = "NaN" not in txt and "Infinity" not in txt and ce.load_strict(p)["a"]["status"] == "NONFINITE_NAN"
    try:
        open(p, "w").write('{"x": NaN}')
        ce.load_strict(p)
        rejects = False
    except ValueError:
        rejects = True
    res["strict_json"] = {"writer_ok": strict_ok, "reader_rejects_NaN": rejects}
    ok_all = ok_all and strict_ok and rejects
    want = {"consistent": "SHADOW_CONSISTENT", "conservation_fail": "SHADOW_INCONSISTENT", "not_converged": "NOT_CONVERGED",
            "identity_fail": "SHADOW_IDENTITY_FAIL", "nonfinite_qf": "SHADOW_INCONSISTENT", "undecidable": "INCONCLUSIVE"}
    prod = {"control": {"verdict": "GATE_HELD"}, "contacts": ["Si_xmin", "Si_xmax"], "regions": ["Si"],
            "region_facts": {"Si": {"x_range_um": [-5, 5], "y_range_um": [-5, 0]}}, "mesh_quality": {}, "doping_prechecks": {}}
    for case, w in want.items():
        d = os.path.join(work, case)
        os.makedirs(d, exist_ok=True)
        ce.dump_strict(prod, os.path.join(d, "prod.json"))
        ce.dump_strict(shadow(case), os.path.join(d, "shadow_S0.json"))
        subprocess.run([sys.executable, os.path.join(HERE, "analyze_e1.py"), d, os.path.join(d, "out")], capture_output=True, text=True)
        got = ce.load_strict(os.path.join(d, "out", "analysis_e1.json"))["shadows"]["S0"]["verdict"]
        res[case] = {"got": got, "expected": w, "ok": got == w}
        ok_all = ok_all and got == w
        print(case, res[case])
    print("strict_json", res["strict_json"], "ALL_OK", ok_all)
    json.dump(res, open(os.path.join(work, "synthetic_e1_results.json"), "w"), indent=1)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
