#!/usr/bin/env python3
"""The E6I judge must FAIL on NaN / inf / wrong sign / violated criteria and PASS on ideal data (pure Python, no DEVSIM)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd/scripts"))
from resistor_judge import BIASES, judge, theory  # noqa: E402

TH = theory(1e16, 0.0, 1e10, 1.6e-19, 400.0, 200.0, 0.5e-4, 2.0e-4)


def ideal_mesh(family, n, g_scale=1.0):
    g = TH["G_A_per_V_per_cm_depth"] * g_scale
    b = {}
    for label, v in BIASES.items():
        ie = g * v
        b[label] = {"I_max_total": ie, "I_min_total": -ie, "Ie_max": ie, "Ie_min": -ie, "Ih_max": 1e-14 * ie, "Ih_min": -1e-14 * ie,
                    "n_uniformity": 1e-9, "psi_lin": 1e-6, "p_min_over_p0": 1.0, "p_max_over_p0": 1.0, "max_abs_USRH": 0.0,
                    "recombination_current_A_per_cm": 0.0, "finite_arrays": True, "contacts": ["Si_xmin", "Si_xmax"], "donors": [1e16]}
    return {"family": family, "n": n, "biases": b}


def ideal(scale16=1.0, scale32=1.0):
    m = {"uniform_8": ideal_mesh("uniform", 8)}
    for fam in ("one_sided", "two_sided"):
        m[f"{fam}_16"] = ideal_mesh(fam, 16, scale16)
        m[f"{fam}_32"] = ideal_mesh(fam, 32, scale32)
    return m


def expect_fail(mutate, label):
    m = ideal()
    mutate(m)
    assert not judge(TH, m)["pass"], f"judge passed despite: {label}"


def main():
    assert abs(TH["sigma_S_per_cm"] - 0.64) < 1e-6 and abs(TH["G_A_per_V_per_cm_depth"] - 0.16) < 1e-6, TH
    assert judge(TH, ideal())["pass"]
    nan, inf = float("nan"), float("inf")
    for bad in (nan, inf, -inf, None, "x"):
        expect_fail(lambda m, bad=bad: m["one_sided_16"]["biases"]["+1mV"].__setitem__("I_max_total", bad), f"I_max_total = {bad!r}")
        expect_fail(lambda m, bad=bad: m["one_sided_16"]["biases"]["0V"].__setitem__("I_min_total", bad), f"0V I_min_total = {bad!r}")
        expect_fail(lambda m, bad=bad: m["two_sided_32"]["biases"]["+2mV"].__setitem__("n_uniformity", bad), f"n_uniformity = {bad!r}")
        expect_fail(lambda m, bad=bad: m["uniform_8"]["biases"]["-1mV"].__setitem__("psi_lin", bad), f"psi_lin = {bad!r}")
        expect_fail(lambda m, bad=bad: m["uniform_8"]["biases"]["+1mV"].__setitem__("Ie_min", bad), f"Ie_min = {bad!r}")
        for key in ("p_min_over_p0", "p_max_over_p0", "max_abs_USRH", "recombination_current_A_per_cm", "Ih_max", "Ih_min"):
            expect_fail(lambda m, bad=bad, key=key: m["two_sided_16"]["biases"]["0V"].__setitem__(key, bad), f"{key} = {bad!r}")
    for key in ("p_max_over_p0", "max_abs_USRH", "recombination_current_A_per_cm"):
        expect_fail(lambda m, key=key: m["uniform_8"]["biases"]["+1mV"].pop(key), f"missing {key}")
    expect_fail(lambda m: m["two_sided_32"]["biases"]["+1mV"].__setitem__("finite_arrays", False), "non-finite state array")
    expect_fail(lambda m: [m["uniform_8"]["biases"]["+1mV"].__setitem__(k, -m["uniform_8"]["biases"]["+1mV"][k])
                           for k in ("I_max_total", "I_min_total", "Ie_max", "Ie_min")], "wrong sign")
    expect_fail(lambda m: m["uniform_8"]["biases"]["+1mV"].__setitem__("I_max_total", m["uniform_8"]["biases"]["+1mV"]["I_max_total"] * 1.02), "2 % current error")
    expect_fail(lambda m: m["uniform_8"]["biases"]["+1mV"].__setitem__("I_min_total", m["uniform_8"]["biases"]["+1mV"]["I_min_total"] * 0.9999),
                "conservation violated by 1e-4")
    expect_fail(lambda m: m["uniform_8"]["biases"]["0V"].__setitem__("I_max_total", 1e-3 * TH["I_ref"]), "equilibrium current above the bound")
    expect_fail(lambda m: m["uniform_8"]["biases"]["+1mV"].__setitem__("Ih_max", 1e-3 * m["uniform_8"]["biases"]["+1mV"]["I_max_total"]), "hole share")
    expect_fail(lambda m: m["uniform_8"]["biases"]["+2mV"].__setitem__("I_max_total", 2.05 * m["uniform_8"]["biases"]["+1mV"]["I_max_total"]), "linearity 2.5 %")
    expect_fail(lambda m: m.pop("one_sided_32"), "missing finest mesh")
    assert judge(TH, ideal(0.995, 1.004))["pass"]                 # 0.9 % mesh change, each mesh within 1 %
    assert not judge(TH, ideal(0.995, 1.007))["pass"]             # each mesh within 1 % but 1.2 % apart: only the mesh check fails
    failed = {c["id"] for c in judge(TH, ideal(0.995, 1.007))["failed"]}
    assert failed == {6}, failed
    print("RESISTOR JUDGE TESTS PASSED (NaN / inf / None / str, sign, each criterion)")


if __name__ == "__main__":
    main()
