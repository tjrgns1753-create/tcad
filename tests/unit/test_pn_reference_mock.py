#!/usr/bin/env python3
"""Self-identity, sign and quadrature checks of the E6K analytic PN reference (docs/audits/2026-10-01-e6k-pn-1d-diagnostic/scripts/pn_reference.py). Pure Python."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/scripts"))
import pn_reference as R  # noqa: E402

P = R.params(q=1.6e-19, n_i=1e10, temperature_k=300.0, mu_n=400.0, mu_p=200.0, taun=1e-8, taup=1e-8, eps=11.1 * 8.85e-14, n_a=1e17, n_d=1e17,
             w_p_cm=20e-4, w_n_cm=20e-4)


def main():
    # V = 0: no net SRH and no diffusion current (equilibrium); q n_i W / (2 tau) is a reverse-generation SCALE, not an equilibrium current
    r0 = R.reference(P, 0.0)
    assert r0["J_srh"] == 0.0 and r0["J_diff"] == 0.0 and r0["J_model"] == 0.0, r0
    scale0 = P["q"] * P["n_i"] * r0["W"] / (2 * P["taun"])
    assert scale0 > 1e-7, scale0                                      # the scale is large (1.1e-6) while the net current is exactly zero
    # signs
    for v in (0.3, 0.5, 0.6):
        r = R.reference(P, v)
        assert r["J_diff"] > 0 and r["J_srh"] > 0 and r["J_model"] > 0, (v, r)
    for v in (-0.5, -1.0):
        r = R.reference(P, v)
        assert r["J_diff"] < 0 and r["J_srh"] < 0 and r["J_model"] < 0, (v, r)
    # potential continuity at x = 0, edge values, n p product, depletion charge neutrality
    for v in (-1.0, 0.0, 0.6):
        d = R.depletion(P, v)
        assert abs(R.psi(P, v, -1e-15) - R.psi(P, v, 1e-15)) < 1e-9
        assert abs((R.psi(P, v, d["x_n"]) - R.psi(P, v, -d["x_p"])) - (P["V_bi"] - v)) < 1e-12, v
        assert abs(P["N_A"] * d["x_p"] - P["N_D"] * d["x_n"]) < 1e-9 * P["N_A"] * d["x_p"]
        for x in (-0.9 * d["x_p"], -0.3 * d["x_p"], 0.0, 0.4 * d["x_n"], 0.95 * d["x_n"]):
            n, p = R.carriers(P, v, x)
            assert abs(n * p / (P["n_i"] ** 2 * math.exp(v / P["Vt"])) - 1.0) < 1e-12
        n_edge, p_edge = R.carriers(P, v, d["x_n"])
        assert abs(n_edge / P["N_D"] - 1.0) < 1e-9, (v, n_edge)       # neutral n-side edge: n = N_D
        n_edge, p_edge = R.carriers(P, v, -d["x_p"])
        assert abs(p_edge / P["N_A"] - 1.0) < 1e-9
    # an independent algebraic form of the equal-lifetime SRH rate at random depletion points
    for v in (-1.0, -0.5, 0.5, 0.6):
        d = R.depletion(P, v)
        for f in (-0.8, -0.2, 0.1, 0.7):
            x = f * (d["x_p"] if f < 0 else d["x_n"])
            n, p = R.carriers(P, v, x)
            u1 = R.srh_rate(P, n, p)
            u2 = P["n_i"] * math.expm1(v / P["Vt"]) / (2 * P["taun"] * (math.exp(v / (2 * P["Vt"])) * math.cosh(R.psi(P, v, x) / P["Vt"]) + 1.0))
            assert abs(u1 - u2) <= 1e-9 * abs(u2), (v, x, u1, u2)
    # reverse generation bound and sign of the integrand
    for v in (-0.5, -1.0):
        r = R.reference(P, v)
        bound = P["q"] * P["n_i"] * r["W"] / (2 * P["taun"])
        assert 0 < abs(r["J_srh"]) <= bound * (1 + 1e-12), (v, r["J_srh"], bound)     # the scale is an upper bound, not the value
    # Simpson refinement (integration error only, not a model error)
    for v in (-1.0, 0.5, 0.6):
        a, b = R.j_srh(P, v, 1024), R.j_srh(P, v, 4096)
        assert abs(a - b) <= 1e-9 * abs(b), (v, a, b)
    # plan numbers recomputed from the same constants
    assert abs(R.j_diff(P, 0.5) / 2.1487e-3 - 1) < 2e-3 and abs(R.j_diff(P, 0.6) / 0.10228 - 1) < 2e-3, (R.j_diff(P, 0.5), R.j_diff(P, 0.6))
    assert abs(P["V_bi"] / 0.8345045 - 1) < 1e-6 and abs(R.depletion(P, 0.0)["W"] / 0.14316e-4 - 1) < 2e-3
    # minority profile: law of the junction at the edge, zero at the contact, exponential decay for a long region
    v = 0.6
    d = R.depletion(P, v)
    p_n0 = P["n_i"] ** 2 / P["N_D"]
    assert abs(R.minority_excess_profile(P, v, 0.0) / (p_n0 * math.expm1(v / P["Vt"])) - 1) < 1e-12
    assert abs(R.minority_excess_profile(P, v, P["W_n"] - d["x_n"])) < 1e-9 * p_n0
    for s in (1e-4, 3e-4, 5e-4):
        approx = p_n0 * math.expm1(v / P["Vt"]) * math.exp(-s / P["L_p"])
        assert abs(R.minority_excess_profile(P, v, s) / approx - 1) < 1e-5
    # width-from-field on an exact triangle recovers W; with a flat 1 % tail it stays within 1 %
    d = R.depletion(P, -1.0)
    xs = [(-3 * d["W"]) + i * (6 * d["W"] / 6000) for i in range(6001)]
    es = [max(0.0, d["E_max"] * (1 - abs(x) / (d["W"] / 2))) for x in xs]
    assert abs(R.width_from_field(xs, es) / d["W"] - 1) < 1e-3
    print("PN REFERENCE SELF-CHECKS PASSED")


if __name__ == "__main__":
    main()
