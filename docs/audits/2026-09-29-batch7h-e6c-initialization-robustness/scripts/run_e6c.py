"""Batch 7H-E6C driver (remote profile entry). Refuses to run outside a GitHub-hosted runner. PLAN sections 1, 2, 6, 7:
input identity, resource gate, six subprocesses (L3-P, L3-Q, L4-P, L4-Q, L5-P, L5-Q; one devsim.solve each), judgement by
judge_e6c.analyze_dir. Outputs: <repo>/e6c_out (not committed)."""
import argparse
import hashlib
import os
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
AUD = os.path.join(ROOT, "docs", "audits")
OUT = os.path.join(ROOT, "e6c_out")
E6A_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family")
E6A_OUT = os.path.join(E6A_DIR, "data", "remote_run_36388479824", "outputs", "e6a_out")
E6B_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6b-poisson-junction-refinement")
E6B_OUT = os.path.join(E6B_DIR, "data", "remote_run_36527372624", "outputs", "e6b_out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402
import judge_e6c as jc  # noqa: E402

REVIEW_SHA = "023bcb90f8b8a0972d6df84f097ca6387f0ab82a"
CODE_PATHS = ["tcad", "tests", "tcad_2d_stagewise.py", "examples"]
GIB = 1 << 30
MEM_LIMIT = 8 * GIB
TIME_LIMIT_S = 7200.0
STAGE_TIMEOUT_S = 3600
MAX_SOLVES = 6
E6B_PEAK_BYTES = {3: 377188352, 4: 927952896, 5: 3114303488}      # E6B measured process peak private bytes (E6B REPORT section 2)
NODES = {3: 48033, 4: 128067, 5: 441733}
INPUTS = {   # text files are compared LF-normalized (the runner checks out CRLF); binaries byte for byte
    os.path.join(HERE, "..", "PLAN.md"): ("text", "3c91c361a6ae445b795890e919f1e1ea26011cc33091423335442b9bd581194e"),
    os.path.join(E6A_DIR, "PLAN.md"): ("text", "5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba"),
    os.path.join(E6B_DIR, "PLAN.md"): ("text", "6a8d674e3548de32007f90f8a1368f9e2b31835f13d5b54eecc52da041c72e51"),
    os.path.join(E6B_DIR, "scripts", "judge_e6b.py"): ("text", "9f37ad88310b6bac19ff13465a50db0127de9c322dd3cf7c41f3edac98e26bb2"),
    os.path.join(E6A_OUT, "e6a_result.json"): ("text", "882ed0fbc87f5ede0fcdaacafb5eaffab0d6915aee3b897509e05b8ff30ed3bc"),
    os.path.join(E6A_OUT, "level_L3.vtu"): ("binary", "5820d1d27443c0862df3b14634aa0fa8753f20895e2204a650256e98862a1734"),
    os.path.join(E6A_OUT, "level_L4.vtu"): ("binary", "85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297"),
    os.path.join(E6A_OUT, "level_L5.vtu"): ("binary", "907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70"),
    os.path.join(E6A_OUT, "level_L3.npz"): ("binary", "d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf"),
    os.path.join(E6A_OUT, "level_L4.npz"): ("binary", "d274564968f2de0501fb932c474e127d0ae1d38878d66361b3e93add87ece9d4"),
    os.path.join(E6A_OUT, "level_L5.npz"): ("binary", "7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee"),
    os.path.join(E6B_OUT, "level_L3_state_P.npz"): ("binary", "3c6142d70d8af6893c14eec85f47b86761609acf5d751d0c4c616aadfef120d8"),
    os.path.join(E6B_OUT, "level_L4_state_P.npz"): ("binary", "54b4987fb1f9637b64d8b2fa8278597b33bebbc3f564e58cdb8d36c542b97971"),
    os.path.join(E6B_OUT, "level_L5_state_P.npz"): ("binary", "be34ae4a98ceae8b6c9207437df0a66e402fd51ddcc0a38e6139e6b330803d28"),
}


def sha_input(path, kind):
    b = open(path, "rb").read()
    return hashlib.sha256(b.replace(b"\r\n", b"\n") if kind == "text" else b).hexdigest()


def code_identity():
    """git diff --quiet REVIEW_SHA -- code paths: rc 0 identical, 1 differs, anything else = unverifiable (fail closed)."""
    try:
        p = subprocess.run(["git", "diff", "--quiet", REVIEW_SHA, "--"] + CODE_PATHS, cwd=ROOT, capture_output=True, timeout=300)
        return {"rc": p.returncode, "identical": p.returncode == 0}
    except Exception as e:  # noqa: BLE001
        return {"rc": None, "identical": False, "error": ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:200]}


def runner_info():
    info = {"cpu_count": os.cpu_count(), "platform": platform.platform(), "python": platform.python_version()}
    for k in ("RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "ImageOS", "ImageVersion"):
        info[k] = os.environ.get(k)
    return info


def envelopes():
    return {f"L{L}": {"memory_bytes": E6B_PEAK_BYTES[L] + 2 * GIB, "time_s": 0.77 * 110 * NODES[L] / 128067} for L in NODES}


def stage(args, timeout):
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e6c.py")] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        print(p.stdout[-100000:], flush=True)
        if p.stderr.strip():
            print("[e6c][stderr]", p.stderr[-4000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    return rc, time.time() - t


def l5_gate(peaks, walls, elapsed):
    """Measured gate before L5 (as E6B): proportional and linear extrapolation of the L3/L4 P-run peaks; time 1.5 x t_L4 x N5/N4."""
    p3, p4, t4 = peaks.get(3), peaks.get(4), walls.get(4)
    if not isinstance(p4, int) or t4 is None:
        return {"run": False, "reason": "L4 peak memory or wall time unavailable"}
    prop = p4 * NODES[5] / NODES[4]
    lin = p4 + (p4 - p3) * (NODES[5] - NODES[4]) / (NODES[4] - NODES[3]) if isinstance(p3, int) else prop
    mem_pred, t_pred = max(prop, lin), 1.5 * t4 * NODES[5] / NODES[4]
    return {"run": bool(mem_pred <= MEM_LIMIT and elapsed + t_pred <= TIME_LIMIT_S), "mem_pred": mem_pred, "mem_limit": MEM_LIMIT,
            "t_pred_L5_s": t_pred, "elapsed_s": elapsed, "time_limit_s": TIME_LIMIT_S}


def expected_files(recs):
    exp = []
    for L in (3, 4, 5):
        for t in ("P", "Q"):
            r = recs.get(f"L{L}-{t}")
            if r and r.get("status") == "RESOURCE_PREFLIGHT_FAIL":
                continue
            exp.append(f"run_L{L}_{t}.json")
            if r and r.get("status") == "OK":
                exp += [f"run_L{L}_{t}_init.npz", f"run_L{L}_{t}_final.npz"]
            elif r and r.get("status") == "INITIALIZATION_CONTRACT_FAIL":
                exp.append(f"run_L{L}_{t}_init.npz")
    return exp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    env = envelopes()
    print(f"[e6c] envelopes: {env}", flush=True)
    if a.validate_only:
        for p, (k, want) in INPUTS.items():
            print(f"[e6c] input {os.path.basename(p)}: {sha_input(p, k) == want}", flush=True)
        return 0
    if not hosted:
        print("[e6c] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    T0 = time.time()
    res = {"runner": runner_info(), "envelopes": env, "inputs": {}, "stages": {}, "review_sha": REVIEW_SHA, "registered_max_solves": MAX_SOLVES}
    ok_in = True
    for p, (kind, want) in INPUTS.items():
        got = sha_input(p, kind) if os.path.exists(p) else None
        res["inputs"][os.path.relpath(p, ROOT).replace("\\", "/")] = {"kind": kind, "sha256": got, "expected": want, "equal": got == want}
        ok_in &= got == want
    res["code_paths_identical_to_review_sha"] = code_identity()
    ok_in &= res["code_paths_identical_to_review_sha"]["identical"]
    res["input_identity_ok"] = bool(ok_in)
    flags = {"input_identity_ok": bool(ok_in), "resource_ok": True, "artifact_problems": []}
    if not ok_in:
        res["stop"] = "INPUT_IDENTITY_FAIL"                                 # 0 solves
        return finish(res, flags, {})
    if any(v["memory_bytes"] > MEM_LIMIT for v in env.values()) or sum(v["time_s"] for v in env.values()) > TIME_LIMIT_S:
        flags["resource_ok"] = False
        res["stop"] = "RESOURCE_PREFLIGHT_FAIL"
        return finish(res, flags, {})
    recs, peaks, walls = {}, {}, {}
    for L in (3, 4, 5):
        for t in ("P", "Q"):
            name = f"L{L}-{t}"
            if L == 5 and t == "P":
                gate = l5_gate(peaks, walls, time.time() - T0)
                res["l5_measured_gate"] = gate
                if not gate["run"]:
                    flags["resource_ok"], flags["skipped_levels"] = False, [5]
                    recs["L5-P"] = recs["L5-Q"] = {"status": "RESOURCE_PREFLIGHT_FAIL"}
            if recs.get(name, {}).get("status") == "RESOURCE_PREFLIGHT_FAIL":
                continue
            rc, w = stage(["run", OUT, str(L), t], STAGE_TIMEOUT_S)
            res["stages"][name] = {"rc": rc, "wall_s": w}
            jp = os.path.join(OUT, f"run_L{L}_{t}.json")
            recs[name] = ce.load_strict(jp) if os.path.exists(jp) else {"status": f"NO_RESULT_JSON(rc={rc})"}
            if t == "P":
                walls[L] = w
                m = recs[name].get("memory", {})
                if isinstance(m.get("peak_private_bytes"), int):
                    peaks[L] = m["peak_private_bytes"]
    return finish(res, flags, recs)


def finish(res, flags, recs):
    res["solve_counts"] = {k: r.get("solve_count") for k, r in recs.items()}
    total = sum(v for v in res["solve_counts"].values() if isinstance(v, int))
    res["total_solve_calls"], res["solve_budget_ok"] = total, total <= MAX_SOLVES
    if not res["solve_budget_ok"]:
        flags["artifact_problems"].append(f"total solve calls {total} > {MAX_SOLVES}")
    for k, r in recs.items():
        if r.get("devices_left") not in ([], None):
            flags["artifact_problems"].append(f"{k}: devices left registered {r.get('devices_left')}")
        if r.get("status") == "WORKER_ERROR" or str(r.get("status", "")).startswith("NO_RESULT_JSON"):
            flags["artifact_problems"].append(f"{k}: {r.get('status')}")
    files = sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []
    res["missing_expected_files"] = [f for f in expected_files(recs) if f not in files] if recs else []
    if res["missing_expected_files"]:
        flags["artifact_problems"].append(f"missing files: {res['missing_expected_files']}")
    if recs:
        try:
            res["analysis"] = jc.analyze_dir(OUT, E6A_OUT, E6B_OUT, flags)
        except Exception as e:  # noqa: BLE001
            res["analysis_error"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:400]
            res["analysis"] = {"judgement": {"overall": "ARTIFACT_INCOMPLETE", "failure": "ARTIFACT_INCOMPLETE"}}
    else:
        res["analysis"] = {"judgement": {"overall": res.get("stop"), "failure": res.get("stop")}}
    res["verdict"] = {"overall": res["analysis"]["judgement"].get("overall"),
                      "maximum_possible": "INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY",
                      "note": "observed initialization sensitivity vs local junction-refinement change of the 0 V Poisson potential / fixed-width "
                              "field only; not a solver-error bound, not 2D continuum convergence, not current accuracy, not DD, not biased I-V, "
                              "not production step-junction support. Reaching the same solution from two initial states is not evidence that "
                              "the solution is physically accurate."}
    res["output_files"] = {f: ce.sha_file(os.path.join(OUT, f)) for f in sorted(os.listdir(OUT))} if os.path.isdir(OUT) else {}
    ce.dump_strict(res, os.path.join(OUT, "e6c_result.json"))
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e6c] verdict {res['verdict']} solve_calls={total}", flush=True)
    return 0 if all(s["rc"] == 0 for s in res["stages"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
