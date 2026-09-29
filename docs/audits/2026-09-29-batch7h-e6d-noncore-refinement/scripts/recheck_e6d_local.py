"""Local recomputation of the E6D judgement from the downloaded artifacts (pure; no DEVSIM).
usage: recheck_e6d_local.py <downloaded e6d_out dir>"""
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_e6d as rd  # noqa: E402  (paths and INPUTS only; main() is not called)
import judge_e6d as jd  # noqa: E402


def main():
    out = os.path.abspath(sys.argv[1])
    res = json.load(open(os.path.join(out, "e6d_result.json"), encoding="utf-8"))
    sha_ok = {f: rd.ce.sha_file(os.path.join(out, f)) == s for f, s in res["output_files"].items()
              if f != "e6d_result.json" and os.path.exists(os.path.join(out, f))}
    missing = [f for f in res["output_files"] if not os.path.exists(os.path.join(out, f))]
    inputs_ok = {os.path.basename(p): rd.sha_input(p, k) == w for p, (k, w) in rd.INPUTS.items()}
    flags = {"input_identity_ok": res.get("input_identity_ok"), "artifact_problems": []}
    a = jd.analyze_dir(out, rd.E6A_OUT, rd.E6C_OUT, flags)
    r_j, l_j = res["analysis"]["judgement"], a["judgement"]
    same = {"overall": r_j.get("overall") == l_j.get("overall"), "G2_state": r_j.get("G2_state") == l_j.get("G2_state"),
            "metrics": json.dumps(r_j.get("metrics"), sort_keys=True) == json.dumps(json.loads(json.dumps(l_j.get("metrics"))), sort_keys=True)}
    rep = {"output_sha_ok": all(sha_ok.values()), "n_files_checked": len(sha_ok), "missing": missing, "inputs_ok": all(inputs_ok.values()),
           "runner_overall": r_j.get("overall"), "local_overall": l_j.get("overall"), "local_G2_state": l_j.get("G2_state"),
           "agree": same, "local_artifact_problems": a["artifact_problems"]}
    print(json.dumps(rep, indent=1))
    return 0 if rep["output_sha_ok"] and not missing and all(same.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
