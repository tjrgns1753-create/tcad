#!/usr/bin/env python3
"""Pins E6L CORRECTION_1: the E6K W_E (mid-point trapezoid) and the edge-sum quantity are different numbers; the edge-sum identity needs a field that never
changes sign; the L2 37.50 V/cm is (PB edge mean) - (DEVSIM edge). Reads the committed E6K states.npz read-only; pure Python + numpy, no engine import."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
E6K = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6l-judge-integrity-equilibrium/scripts"))
import pb_equilibrium as PB  # noqa: E402

EXPECTED = {"L0": (0.8348742913514126, 0.8345045098471620), "L1": (0.8345993964579969, 0.8345045098471621), "L2": (0.8345293145189819, 0.8345045098471620)}


def main():
    z = np.load(E6K / "states.npz")
    stored = json.load(open(E6K / "pn_1d_diagnostic.json"))["metrics"]["WE"]
    rel = []
    for lv, (t_ref, s_ref) in EXPECTED.items():
        p = f"{lv}_rev__2__bias+0.000__"
        x, v, e = z[p + "x"], z[p + "Potential"], z[p + "ElectricField"]
        xm, ae = 0.5 * (x[:-1] + x[1:]), np.abs(e)
        trap = float(np.sum(0.5 * (ae[:-1] + ae[1:]) * np.diff(xm)))
        esum = float(np.sum(ae * np.diff(x)))
        assert abs(trap - t_ref) <= 1e-13 and abs(esum - s_ref) <= 1e-13, (lv, trap, esum)
        assert abs(2 * trap / ae.max() / stored[lv]["0.0"] - 1) <= 1e-12, "the stored E6K W_E is the mid-point trapezoid"
        assert abs(2 * esum / ae.max() / stored[lv]["0.0"] - 1) > 1e-6, "the edge-sum quantity is NOT the stored E6K W_E"
        assert not np.any(e > 0), "edge-sum identity needs a field that never changes sign"
        assert abs(esum - abs(v[-1] - v[0])) <= 1e-14 and abs(float(np.sum(e * np.diff(x))) - (v[0] - v[-1])) <= 1e-14
        rel.append(trap / esum - 1)
    assert rel[0] > rel[1] > rel[2] > 0 and 3.0 < rel[0] / rel[1] < 5.0 and 3.0 < rel[1] / rel[2] < 5.0, rel   # shrinks ~4x per level
    # B: the L2 residual is (PB mean over the edge) - (DEVSIM edge value); only the quadrature convergence is established
    c = PB.constants()
    _a, _psi_n, e_of, _e0 = PB.pb_field(c)
    p = "L2_rev__2__bias+0.000__"
    x, e = z[p + "x"], z[p + "ElectricField"]
    i = int(np.argmax(np.abs(e)))
    d = float(x[i + 1] - x[i])
    pb32, pb64 = PB.pb_edge_average(e_of, d, 32)[0], PB.pb_edge_average(e_of, d, 64)[0]
    assert abs(pb64 - pb32) < 1e-6
    assert abs((pb64 - float(abs(e[i]))) - 37.50) < 0.01, pb64 - float(abs(e[i]))
    print("E6L CORRECTION_1 NUMERIC CHECKS PASSED")


if __name__ == "__main__":
    main()
