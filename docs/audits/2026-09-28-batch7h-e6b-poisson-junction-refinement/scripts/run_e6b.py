"""Batch 7H-E6B driver (remote profile entry). Refuses to run outside a GitHub-hosted runner. PLAN Rev.3 sections 5, 6, 9:
input identity, resource preflight, one subprocess per device (L3, L4, L5, R6, R7; at most 10 solve calls in total),
judgement by judge_e6b.analyze_dir. Outputs: <repo>/e6b_out (not committed)."""
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
OUT = os.path.join(ROOT, "e6b_out")
E6A_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family")
E6A_OUT = os.path.join(E6A_DIR, "data", "remote_run_36388479824", "outputs", "e6a_out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402
import judge_e6b as jd  # noqa: E402

REVIEW_SHA = "023bcb90f8b8a0972d6df84f097ca6387f0ab82a"
CODE_PATHS = ["tcad", "tests", "tcad_2d_stagewise.py", "examples"]
GIB = 1 << 30
MEM_LIMIT = 8 * GIB
TIME_LIMIT_S = 7200.0
STAGE_TIMEOUT_S = 3600
MAX_SOLVES = 10
E6A_PEAK_BYTES = {3: 193695744, 4: 459726848, 5: 1425637376}     # E6A measured peak private bytes (E6A REPORT section 6)
NODES = {3: 48033, 4: 128067, 5: 441733}
# text files are compared LF-normalized (the runner checks out CRLF); binaries byte for byte
INPUTS = {
    os.path.join(HERE, "..", "PLAN.md"): ("text", "6a8d674e3548de32007f90f8a1368f9e2b31835f13d5b54eecc52da041c72e51"),
    os.path.join(E6A_DIR, "PLAN.md"): ("text", "5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba"),
    os.path.join(E6A_OUT, "e6a_result.json"): ("text", "882ed0fbc87f5ede0fcdaacafb5eaffab0d6915aee3b897509e05b8ff30ed3bc"),
    os.path.join(E6A_OUT, "level_L3.vtu"): ("binary", "5820d1d27443c0862df3b14634aa0fa8753f20895e2204a650256e98862a1734"),
    os.path.join(E6A_OUT, "level_L4.vtu"): ("binary", "85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297"),
    os.path.join(E6A_OUT, "level_L5.vtu"): ("binary", "907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70"),
    os.path.join(E6A_OUT, "level_L3.npz"): ("binary", "d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf"),
    os.path.join(E6A_OUT, "level_L4.npz"): ("binary", "d274564968f2de0501fb932c474e127d0ae1d38878d66361b3e93add87ece9d4"),
    os.path.join(E6A_OUT, "level_L5.npz"): ("binary", "7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee"),
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
    """Per level: memory = E6A measured peak + 2 GiB solver allowance; time = 3 x 0.77 s per Newton iteration per 128067 nodes
    x 110 iterations x N/128067 (7H-E5 D2D Poisson: 7.711 s / 10 iterations). 1D references: seconds."""
    return {f"L{L}": {"memory_bytes": E6A_PEAK_BYTES[L] + 2 * GIB, "time_s": 3 * 0.7711 * 110 * NODES[L] / 128067} for L in NODES}


def stage(args, timeout):
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e6b.py")] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        print(p.stdout[-100000:], flush=True)
        if p.stderr.strip():
            print("[e6b][stderr]", p.stderr[-4000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    return rc, time.time() - t


def l5_gate(peaks, walls, elapsed):
    """Measured gate before L5 (as E6A section 5): proportional and linear extrapolation of the L3/L4 peaks; time 1.5 x t_L4 x N5/N4."""
    p3, p4, t4 = peaks.get(3), peaks.get(4), walls.get(4)
    if not isinstance(p4, int) or t4 is None:
        return {"run": False, "reason": "L4 peak memory or wall time unavailable"}
    prop = p4 * NODES[5] / NODES[4]
    lin = p4 + (p4 - p3) * (NODES[5] - NODES[4]) / (NODES[4] - NODES[3]) if isinstance(p3, int) else prop
    mem_pred, t_pred = max(prop, lin), 1.5 * t4 * NODES[5] / NODES[4]
    return {"run": bool(mem_pred <= MEM_LIMIT and elapsed + t_pred <= TIME_LIMIT_S), "mem_pred": mem_pred, "mem_limit": MEM_LIMIT,
            "t_pred_L5_s": t_pred, "elapsed_s": elapsed, "time_limit_s": TIME_LIMIT_S}


def expected_files(stage_recs):
    exp = []
    for L in (3, 4, 5):
        r = stage_recs.get(f"L{L}")
        if r and r.get("status") == "RESOURCE_PREFLIGHT_FAIL":
            continue
        exp.append(f"level_L{L}.json")
        if r and r.get("status") == "OK":
            exp += [f"level_L{L}_static.npz", f"level_L{L}_state_P.npz"]
            if any(c.get("call_id") == f"L{L}-C" for c in r.get("solve_calls", [])):
                exp.append(f"level_L{L}_state_C.npz")
    for m in (6, 7):
        r = stage_recs.get(f"R{m}")
        exp.append(f"ref_R{m}.json")
        if r and r.get("status") == "OK":
            exp.append(f"ref_R{m}.npz")
    return exp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    env = envelopes()
    print(f"[e6b] envelopes: {env}", flush=True)
    if a.validate_only:
        for p, (k, want) in INPUTS.items():
            print(f"[e6b] input {os.path.basename(p)}: {sha_input(p, k) == want}", flush=True)
        return 0
    if not hosted:
        print("[e6b] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    T0 = time.time()
    res = {"runner": runner_info(), "envelopes": env, "inputs": {}, "stages": {}, "review_sha": REVIEW_SHA,
           "registered_max_solves": MAX_SOLVES}
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
        res["stop"] = "INPUT_IDENTITY_FAIL"                    # solve 0 times
        return finish(res, flags, {})
    if any(v["memory_bytes"] > MEM_LIMIT for v in env.values()) or sum(v["time_s"] for v in env.values()) > TIME_LIMIT_S:
        flags["resource_ok"] = False
        res["stop"] = "RESOURCE_PREFLIGHT_FAIL"
        return finish(res, flags, {})
    recs, peaks, walls = {}, {}, {}
    plan = [("L3", ["level", OUT, "3"]), ("L4", ["level", OUT, "4"]), ("L5", ["level", OUT, "5"]),
            ("R6", ["ref", OUT, "6"]), ("R7", ["ref", OUT, "7"])]
    for name, args in plan:
        if name == "L5":
            gate = l5_gate(peaks, walls, time.time() - T0)
            res["l5_measured_gate"] = gate
            if not gate["run"]:
                flags["resource_ok"] = False
                flags["skipped_levels"] = [5]
                recs["L5"] = {"status": "RESOURCE_PREFLIGHT_FAIL"}
                continue
        rc, w = stage(args, STAGE_TIMEOUT_S)
        res["stages"][name] = {"rc": rc, "wall_s": w}
        jp = os.path.join(OUT, f"{'level_L' if name[0] == 'L' else 'ref_R'}{name[1]}.json")
        recs[name] = ce.load_strict(jp) if os.path.exists(jp) else {"status": f"NO_RESULT_JSON(rc={rc})", "solve_calls": []}
        walls[int(name[1])] = w
        m = recs[name].get("memory", {})
        if name[0] == "L" and isinstance(m.get("peak_private_bytes"), int):
            peaks[int(name[1])] = m["peak_private_bytes"]
    return finish(res, flags, recs)


def finish(res, flags, recs):
    res["solve_counts"] = {k: r.get("solve_count") for k, r in recs.items()}
    total = sum(v for v in res["solve_counts"].values() if isinstance(v, int))
    res["total_solve_calls"] = total
    res["solve_budget_ok"] = total <= MAX_SOLVES
    if not res["solve_budget_ok"]:
        flags["artifact_problems"].append(f"total solve calls {total} > {MAX_SOLVES}")
    for k, r in recs.items():
        if r.get("devices_left") not in ([], None) and r.get("status") not in (None,):
            flags["artifact_problems"].append(f"{k}: devices left registered {r.get('devices_left')}")
        if k[0] == "L" and r.get("status") == "WORKER_ERROR":
            flags["artifact_problems"].append(f"{k}: worker error")
    files = sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []
    missing = [f for f in expected_files(recs) if f not in files] if recs else []
    res["missing_expected_files"] = missing
    if missing:
        flags["artifact_problems"].append(f"missing files: {missing}")
    if recs:
        try:
            res["analysis"] = jd.analyze_dir(OUT, E6A_OUT, flags)
        except Exception as e:  # noqa: BLE001
            res["analysis_error"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:400]
            flags["artifact_problems"].append("analysis raised")
            res["analysis"] = {"judgement": {"overall": "ARTIFACT_INCOMPLETE", "failure": "ARTIFACT_INCOMPLETE"}}
    else:
        res["analysis"] = {"judgement": {"overall": res.get("stop"), "failure": res.get("stop")}}
    res["verdict"] = {"overall": res["analysis"]["judgement"].get("overall"),
                      "reference": (res["analysis"].get("reference") or {}).get("overall"),
                      "maximum_possible": "LOCAL_JUNCTION_REFINEMENT_TREND_ONLY",
                      "note": "local junction-refinement trend of the 0 V Poisson potential / fixed-width field only; not 2D continuum "
                              "convergence, not current accuracy, not DD, not biased I-V, not production step-junction support"}
    res["output_files"] = {f: ce.sha_file(os.path.join(OUT, f)) for f in sorted(os.listdir(OUT))} if os.path.isdir(OUT) else {}
    ce.dump_strict(res, os.path.join(OUT, "e6b_result.json"))
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e6b] verdict {res['verdict']} solve_calls={total}", flush=True)
    return 0 if all(s["rc"] == 0 for s in res["stages"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
