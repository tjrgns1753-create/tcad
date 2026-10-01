#!/usr/bin/env python3
"""E6L PB equilibrium reference: closed form == first integral, boundary behaviour, quadrature convergence, small-edge limit and the independently stated numbers. Pure Python."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6l-judge-integrity-equilibrium/scripts"))
import pb_equilibrium as P  # noqa: E402

C = {"q": 1.6e-19, "n_i": 1e10, "Vt": 0.025887193125, "eps": 9.8235e-13, "N": 1e17}
C["V_bi"] = C["Vt"] * math.log(C["N"] ** 2 / C["n_i"] ** 2)


def main():
    a, psi_n, e_of, e0 = P.pb_field(C)
    assert abs(e_of(0.0) / e0 - 1) < 1e-14, (e_of(0.0), e0)
    assert abs(e0 - 112910.1264) < 1e-3, e0                                   # independently stated value (Codex arithmetic)
    e_dep = math.sqrt(2 * C["q"] * C["V_bi"] / C["eps"] * C["N"] / 2)
    assert abs(e_dep - 116584.6063) < 1e-3, e_dep
    assert abs(2 * C["n_i"] * math.sinh(psi_n / C["Vt"]) / C["N"] - 1) < 1e-12   # neutrality at psi_n
    assert e_of(psi_n * (1 - 1e-9)) < 1e-3 * e0                                # field vanishes toward the neutral region
    assert all(e_of(s * psi_n) > e_of((s + 0.1) * psi_n) for s in (0.0, 0.3, 0.6))   # |E| decreases away from the junction
    # Poisson consistency: d(E^2/2)/dpsi = (q/eps)(2 n_i sinh(psi/V_T) - N) on the n side
    for s in (0.1, 0.25, 0.4):
        h = 1e-7
        lhs = (e_of(s + h) ** 2 - e_of(s - h) ** 2) / (4 * h)
        rhs = (C["q"] / C["eps"]) * (2 * C["n_i"] * math.sinh(s / C["Vt"]) - C["N"])
        assert abs(lhs / rhs - 1) < 1e-5, (s, lhs, rhs)
    # quadrature convergence and the small-edge limit
    d = 0.9040947809e-7
    vals = [P.pb_edge_average(e_of, d, n)[0] for n in (4, 8, 16, 32, 64)]
    assert max(abs(v - vals[-1]) for v in vals[1:]) < 1e-6, vals
    assert abs(vals[-1] - 112173.8554) < 1e-3, vals[-1]                        # independently stated first-order value at this edge length
    tiny = 1e-12
    expect = e0 - C["q"] * C["N"] / C["eps"] * tiny / 2                       # small-edge limit: E0 minus the first-order slope term
    assert abs(P.pb_edge_average(e_of, tiny, 32)[0] / expect - 1) < 1e-9
    first = e0 - C["q"] * C["N"] / C["eps"] * d / 2
    assert abs(e0 - first - 736.2710) < 1e-3, e0 - first
    print("PB EQUILIBRIUM REFERENCE CHECKS PASSED")


if __name__ == "__main__":
    main()
