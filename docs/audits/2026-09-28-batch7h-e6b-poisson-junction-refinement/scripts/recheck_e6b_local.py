"""Batch 7H-E6B local, read-only re-check of the downloaded remote artifacts with the same pure judge (no DEVSIM, no ViennaPS).
Recomputes the judgement, compares it with the remote e6b_result.json, and extracts raw values that the verdict does not use.
usage: recheck_e6b_local.py <out json>"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge_e6b as jd  # noqa: E402

BASE = os.path.join(HERE, "..", "data", "remote_run_36527372624", "outputs", "e6b_out")
E6A = os.path.join(HERE, "..", "..", "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")


def main():
    res = jd.analyze_dir(BASE, E6A, {"artifact_problems": [], "input_identity_ok": True, "resource_ok": True})
    remote = json.load(open(os.path.join(BASE, "e6b_result.json"), encoding="utf-8"))["analysis"]
    out = {"local_overall": res["judgement"]["overall"], "remote_overall": remote["judgement"]["overall"],
           "judgement_json_equal": json.dumps(res["judgement"], sort_keys=True, default=str) == json.dumps(remote["judgement"], sort_keys=True, default=str),
           "reference": res["reference"], "D": {k: res["judgement"]["regions"][k] for k in ("D34", "D45")}}
    e = {L: jd.load_npz(os.path.join(E6A, f"level_L{L}.npz")) for L in jd.LEVELS}
    cs = jd.CommonSet({L: e[L]["points_um_f32"][:, :2] for L in jd.LEVELS}, e[3]["NodeVolume"], e[3]["x"], e[3]["y"])
    raw, bit = {}, {}
    row = np.where((np.abs(cs.ycm + 2.5e-4) < 1e-9) & cs.masks["core"])[0]
    row = row[np.argsort(cs.xcm[row])]
    prof = {}
    for L in jd.LEVELS:
        P = jd.load_npz(os.path.join(BASE, f"level_L{L}_state_P.npz"))
        C = jd.load_npz(os.path.join(BASE, f"level_L{L}_state_C.npz"))
        m = jd.metrics_between(P["Potential"][cs.idx[L]], C["Potential"][cs.idx[L]], cs)
        raw[f"L{L}"] = {k: m["core"][k] for k in jd.METRICS}
        bit[f"L{L}"] = {k: bool(np.array_equal(P[k], C[k])) for k in jd.REQUIRED_STATE_ARRAYS}
        prof[f"L{L}"] = {"x_um": [float(cs.xcm[i] / 1e-4) for i in row[[0, 15, 16, 17, 32]]],
                         "psi_V": [float(P["Potential"][cs.idx[L]][i]) for i in row[[0, 15, 16, 17, 32]]]}
    out.update({"raw_P_vs_C_shift_invalid_controls_not_used": raw, "P_equals_C_bitwise_all_nodes": bit, "row_y_minus_2p5_um_profile": prof,
                "n_row_core_nodes": int(len(row)), "y_uniformity": res["level_consistency"], "contact_readback_V": res["contact_readback"],
                "gauss_diagnostic": res["gauss_diagnostic"]})
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump(out, f, indent=1, default=str)
        f.write("\n")
    print("local", out["local_overall"], "remote", out["remote_overall"], "equal", out["judgement_json_equal"])
    print("raw P-vs-C shifts:", raw)
    print("P == C bitwise:", bit)
    print("profile:", prof)
    return 0


if __name__ == "__main__":
    sys.exit(main())
