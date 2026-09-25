"""Batch 7H-E5 SYNTHETIC test (no ViennaPS / DEVSIM): grid_1d_um()/cols_right() reproduce D1's own meshes_d1.py values
exactly at X_HALF=0.5 (the file this batch generalizes, read-only, not modified), and behave correctly at this batch's
actual runtime parameters (h=0.003125, X_HALF=5.0). usage: synthetic_e5_test.py <out json>"""
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-d1-pn-convergence", "scripts"))
import devices_e5 as de5  # noqa: E402
import meshes_d1 as md1  # noqa: E402  (D1, read-only: the original fixed-0.5 formula this batch generalizes)


def main():
    res, ok = {}, True
    for h in (0.02, 0.01, 0.005, 0.0025, 0.00125):
        for kind in ("J0", "J1"):
            want = md1.grid_1d(h, kind)
            got = de5.grid_1d_um(h, kind, x_half=0.5)
            same = len(want) == len(got) and all(abs(a - b) < 1e-12 for a, b in zip(want, got))
            res[f"h{h}_{kind}_matches_D1"] = same
            ok &= same
    xs_j0 = de5.grid_1d_um(de5.H_UM, "J0")
    xs_j1 = de5.grid_1d_um(de5.H_UM, "J1")
    res["runtime_J0"] = {"n": len(xs_j0), "has_x0": 0.0 in xs_j0, "min": xs_j0[0], "max": xs_j0[-1],
                         "symmetric": abs(xs_j0[0] + xs_j0[-1]) < 1e-9}
    res["runtime_J1"] = {"n": len(xs_j1), "has_x0": 0.0 in xs_j1, "min": xs_j1[0], "max": xs_j1[-1],
                         "symmetric": abs(xs_j1[0] + xs_j1[-1]) < 1e-9,
                         "min_abs_x": min(abs(v) for v in xs_j1)}
    ok &= res["runtime_J0"]["has_x0"] and res["runtime_J0"]["n"] == 3201 and res["runtime_J0"]["symmetric"]
    ok &= (not res["runtime_J1"]["has_x0"]) and res["runtime_J1"]["symmetric"]
    ok &= abs(res["runtime_J1"]["min_abs_x"] - de5.H_UM / 2) < 1e-9
    # doping rule (pure logic, no devsim): J0 both species full strength at x=0; J1 excludes x=0 by construction
    import numpy as np
    x = np.array(xs_j0)
    don0, acc0 = np.where(x >= 0, de5.N_CONC, 0.0), np.where(x <= 0, de5.N_CONC, 0.0)
    at0 = x == 0.0
    res["J0_donor_acceptor_both_full_at_x0"] = bool((don0[at0] == de5.N_CONC).all() and (acc0[at0] == de5.N_CONC).all())
    ok &= res["J0_donor_acceptor_both_full_at_x0"]
    res["ALL_OK"] = bool(ok)
    json.dump(res, open(sys.argv[1], "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
