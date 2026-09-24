"""Batch 7H-D4 descriptive statistics (ERRATUM section 3). Reads the downloaded artifact only; no solve, no verdict.
For every fixture and recorded point: max |psi_P12 - psi_P4| (V) with node coordinates, the same restricted to
|x| <= 0.10 um, and max |ln n ratio|, |ln p ratio| with coordinates; per-point final relative updates; current conservation
residuals (from the D3 self-consistency metrics). These numbers do NOT change the registered verdicts.
usage: describe_d4.py <d4_out dir> <output json>"""
import json
import os
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-d3-precision-pair-mirror", "scripts"))
import analyze_d3 as A3  # noqa: E402

POINTS = ("B0", "B0rev") + A3.BIASED
UM = 1e-4
BAND_UM = 0.10


def key(p):
    return p.replace("+", "p").replace("-", "m").replace(".", "_")


def argmax_at(a, x, y):
    i = int(np.argmax(a))
    return float(a[i]), [float(x[i] / UM), float(y[i] / UM)]


def main():
    d, outp = sys.argv[1], sys.argv[2]
    runs = os.path.join(d, "runs")
    res = {}
    for fam, h in (("M1", 0.005), ("M1", 0.00125), ("M2", 0.00125)):
        fk = f"{fam}_D0_h{h}"
        r12 = json.load(open(os.path.join(runs, f"D4_{fk}_P12.json"), encoding="utf-8"))
        r4 = json.load(open(os.path.join(runs, f"D4_{fk}_P4.json"), encoding="utf-8"))
        z12 = np.load(os.path.join(runs, r12["node_state"]["npz"]))
        z4 = np.load(os.path.join(runs, r4["node_state"]["npz"]))
        x, y = z4["x"], z4["y"]
        band = np.abs(x / UM) <= BAND_UM
        pts = {}
        for p in POINTS:
            k = key(p)
            dpsi = np.abs(z12[f"psi_{k}"] - z4[f"psi_{k}"])
            ln = np.abs(np.log(z12[f"n_{k}"] / z4[f"n_{k}"]))
            lp = np.abs(np.log(z12[f"p_{k}"] / z4[f"p_{k}"]))
            mpsi, at = argmax_at(dpsi, x, y)
            mbp, atb = argmax_at(np.where(band, dpsi, -1.0), x, y)
            mn, atn = argmax_at(ln, x, y)
            mp, atp = argmax_at(lp, x, y)
            e = {"max_abs_dpsi_V": mpsi, "at_um": at, "max_abs_dpsi_junction_band_V": mbp, "band_at_um": atb,
                 "band_nodes": int(band.sum()), "max_abs_psi_P4_V": float(np.max(np.abs(z4[f"psi_{k}"]))),
                 "max_abs_ln_n": mn, "ln_n_at_um": atn, "max_abs_ln_p": mp, "ln_p_at_um": atp,
                 "n_nodes_dpsi_exactly_0": int(np.sum(dpsi == 0)), "n_nodes": int(len(x)),
                 "final_rel_update": {"P12": r12["steps"][p]["info"]["final_device_rel"], "P4": r4["steps"][p]["info"]["final_device_rel"]},
                 "iterations": {"P12": r12["steps"][p]["info"]["iterations"], "P4": r4["steps"][p]["info"]["iterations"]}}
            if p in A3.BIASED:
                for tag, r in (("P12", r12), ("P4", r4)):
                    m = A3.pm(r["steps"][p])
                    e[f"conservation_{tag}"] = {q: m[q] for q in ("mis_lr", "spread", "c0L_vs_cut0", "c0R_vs_cut0", "c3_species", "c3_total")}
                    e[f"C0_{tag}"] = [m["C0_left"], m["C0_right"]]
                    e[f"cut0_{tag}"] = m["cuts"]["+0.00"]
            pts[p] = e
        res[fk] = pts
    json.dump(res, open(outp, "w", encoding="utf-8"), indent=1)
    for fk, pts in res.items():
        for p, e in pts.items():
            print(f"{fk:14s} {p:8s} dpsi_max={e['max_abs_dpsi_V']:.3e} V at {e['at_um']}  band_max={e['max_abs_dpsi_junction_band_V']:.3e} V at {e['band_at_um']}"
                  f"  ln_n={e['max_abs_ln_n']:.2e} at {e['ln_n_at_um']}  ln_p={e['max_abs_ln_p']:.2e}  zero_dpsi_nodes={e['n_nodes_dpsi_exactly_0']}/{e['n_nodes']}"
                  f"  rel P12/P4={e['final_rel_update']['P12']:.1e}/{e['final_rel_update']['P4']:.1e}")


if __name__ == "__main__":
    main()
