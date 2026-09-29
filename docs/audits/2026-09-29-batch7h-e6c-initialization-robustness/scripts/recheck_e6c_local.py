"""Batch 7H-E6C local, read-only re-check of the downloaded remote artifacts with the same pure judge (no DEVSIM, no ViennaPS).
Recomputes the judgement, compares it with the remote e6c_result.json, and extracts raw values (initial-condition proof, iteration histories,
P/Q bitwise comparison, profiles). usage: recheck_e6c_local.py <out json>"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge_e6c as jc  # noqa: E402
jb = jc.jb

BASE = os.path.join(HERE, "..", "data", "remote_run_36529279171", "outputs", "e6c_out")
E6A = os.path.join(HERE, "..", "..", "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")
E6B = os.path.join(HERE, "..", "..", "2026-09-28-batch7h-e6b-poisson-junction-refinement", "data", "remote_run_36527372624", "outputs", "e6b_out")


def main():
    res = jc.analyze_dir(BASE, E6A, E6B, {"artifact_problems": [], "input_identity_ok": True, "resource_ok": True})
    remote = json.load(open(os.path.join(BASE, "e6c_result.json"), encoding="utf-8"))["analysis"]
    out = {"local_overall": res["judgement"]["overall"], "remote_overall": remote["judgement"]["overall"],
           "judgement_json_equal": json.dumps(res["judgement"], sort_keys=True, default=str) == json.dumps(remote["judgement"], sort_keys=True, default=str),
           "judgement": res["judgement"], "gauss_diagnostic": res["gauss_diagnostic"], "consistency": res["consistency"],
           "contact_readback": res["contact_readback"], "e6b_P_reproducibility_diagnostic": res["e6b_P_reproducibility_diagnostic"]}
    e = {L: jb.load_npz(os.path.join(E6A, f"level_L{L}.npz")) for L in jc.LEVELS}
    cs = jb.CommonSet({L: e[L]["points_um_f32"][:, :2] for L in jc.LEVELS}, e[3]["NodeVolume"], e[3]["x"], e[3]["y"])
    runs = {}
    for L in jc.LEVELS:
        recs = {t: json.load(open(os.path.join(BASE, f"run_L{L}_{t}.json"), encoding="utf-8")) for t in jc.TAGS}
        init = {t: jb.load_npz(os.path.join(BASE, f"run_L{L}_{t}_init.npz"))["Potential"] for t in jc.TAGS}
        fin = {t: jb.load_npz(os.path.join(BASE, f"run_L{L}_{t}_final.npz")) for t in jc.TAGS}
        vl, vr = recs["Q"]["initialization"]["V_left"], recs["Q"]["initialization"]["V_right"]
        runs[f"L{L}"] = {
            "init": {t: {"sha256": recs[t]["init_sha256"], "min": float(init[t].min()), "max": float(init[t].max()), "n": int(len(init[t]))} for t in jc.TAGS},
            "Q_init_equals_recomputed_affine_bitwise": bool(np.array_equal(init["Q"], jc.affine_init(e[L]["x"], vl, vr))),
            "max_abs_init_diff_Q_minus_P": float(np.max(np.abs(init["Q"] - init["P"]))), "n_nodes_init_differs": int((init["Q"] != init["P"]).sum()),
            "Q_initialization": recs["Q"]["initialization"], "process_id": {t: recs[t]["process_id"] for t in jc.TAGS},
            "solve": {t: {k: recs[t]["solve"].get(k) for k in ("converged", "n_iterations", "final_device_relative_error", "final_device_absolute_error", "final_equations")} for t in jc.TAGS},
            "rel_history": {t: recs[t]["solve"].get("iteration_device_relative_errors") for t in jc.TAGS},
            "raw_info_keys": sorted(recs["P"]["solve"]["raw_info"].keys()) if isinstance(recs["P"]["solve"].get("raw_info"), dict) else None,
            "final_P_equals_Q_bitwise": {k: bool(np.array_equal(fin["P"][k], fin["Q"][k])) for k in jb.REQUIRED_STATE_ARRAYS},
            "max_abs_final_potential_diff_all_nodes": float(np.max(np.abs(fin["P"]["Potential"] - fin["Q"]["Potential"]))),
            "identity": recs["P"]["identity"] if all(recs[t]["identity"]["ok"] for t in jc.TAGS) else {t: recs[t]["identity"] for t in jc.TAGS},
            "identity_ok": {t: recs[t]["identity"]["ok"] for t in jc.TAGS}, "doping": {t: recs[t]["doping"] for t in jc.TAGS},
            "flags": {t: recs[t]["flags"] for t in jc.TAGS}, "edge_equal_E6A": {t: recs[t]["edge_arrays_equal_E6A"] for t in jc.TAGS},
            "peak_private_bytes": {t: recs[t]["memory"].get("peak_private_bytes") for t in jc.TAGS}}
    out["runs"] = runs
    with open(sys.argv[1], "w", newline="\n") as f:
        json.dump(out, f, indent=1, default=str)
        f.write("\n")
    print("local", out["local_overall"], "remote", out["remote_overall"], "equal", out["judgement_json_equal"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
