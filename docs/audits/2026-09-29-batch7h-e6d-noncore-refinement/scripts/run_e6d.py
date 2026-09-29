"""Batch 7H-E6D driver (remote profile entry). Refuses to run outside a GitHub-hosted runner. PLAN sections 1-7:
input identity, resource preflight, mesh stages G1 and G2 (production refine_mesh_near, pre-solve gates, 0 solves), then at most four
subprocesses G1-P, G1-Q, G2-P, G2-Q (one devsim.solve each) for meshes that passed, judgement by judge_e6d.analyze_dir.
Outputs: <repo>/e6d_out (not committed)."""
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
OUT = os.path.join(ROOT, "e6d_out")
E6A_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family")
E6A_OUT = os.path.join(E6A_DIR, "data", "remote_run_36388479824", "outputs", "e6a_out")
E6B_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6b-poisson-junction-refinement")
E6B_OUT = os.path.join(E6B_DIR, "data", "remote_run_36527372624", "outputs", "e6b_out")
E6C_DIR = os.path.join(AUD, "2026-09-29-batch7h-e6c-initialization-robustness")
E6C_OUT = os.path.join(E6C_DIR, "data", "remote_run_36529279171", "outputs", "e6c_out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402
import judge_e6d as jd  # noqa: E402

REVIEW_SHA = "023bcb90f8b8a0972d6df84f097ca6387f0ab82a"
CODE_PATHS = ["tcad", "tests", "tcad_2d_stagewise.py", "examples"]
GIB = 1 << 30
MEM_LIMIT = 8 * GIB
TIME_LIMIT_S = 7200.0
STAGE_TIMEOUT_S = 3600
MAX_SOLVES = 4
T_G = {0: 882600, 1: 998000, 2: 1459200}
N_G = {0: 441733, 1: 499725, 2: 730909}
E6C_L5_PEAK = 2972852224                      # max E6C L5-P / L5-Q peak private bytes (PLAN 3)
_S = lambda *p: os.path.join(*p)  # noqa: E731
INPUTS = {   # text files compared LF-normalized (the runner checks out CRLF); binaries byte for byte
    _S(HERE, "..", "PLAN.md"): ("text", "fb389c5df1f011f02dc7e42f23de46fd3cbe61b86e5d5dece9d6f094e2b52f9c"),
    _S(E6C_DIR, "PLAN.md"): ("text", "3c91c361a6ae445b795890e919f1e1ea26011cc33091423335442b9bd581194e"),
    _S(E6C_DIR, "scripts", "judge_e6c.py"): ("text", "96cc5fc9182be5947984490f791509679a25e5839cab44d4be59ca07f045aec9"),
    _S(E6C_DIR, "scripts", "stage_e6c.py"): ("text", "194dbc6362fc8322c7134b21444b81b01e58d23b0aeee95446c3fde01244440b"),
    _S(E6B_DIR, "scripts", "judge_e6b.py"): ("text", "9f37ad88310b6bac19ff13465a50db0127de9c322dd3cf7c41f3edac98e26bb2"),
    _S(E6A_DIR, "scripts", "family_e6a.py"): ("text", "3f7c8f0ef5c3ff240a93e02f9846cbd9a09649c2f63e236efcc8ac76f2e9e06a"),
    _S(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage", "scripts", "stage_e2.py"):
        ("text", "d9ff7926158750c5b76d0acd1dab6c39f9829ddb10809c11ea2b0b19cf7ab15d"),
    _S(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage", "scripts", "trace_refine_e2.py"):
        ("text", "7c6ff65c7626b7a2694fde89752ac26ab1d005fc22c686a05aab2131f979fd9d"),
    _S(AUD, "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate", "scripts", "quadtree_e4.py"):
        ("text", "485bd69c9db558e9640eadcc01f26e079043fa166fe3e9e33cad6f7dfb8b8534"),
    _S(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts", "common_e1.py"):
        ("text", "1c8bdec16a23e3e2e6d00fb496a6174e99d9a89b89f884c21abae22e16b2a0f9"),
    _S(E6A_OUT, "level_L5.json"): ("text", "425e956b40f60650b4b02d69159d87d020de952e2bdbdb215ddaff75ed8e6915"),
    _S(E6A_OUT, "level_L5.vtu"): ("binary", "907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70"),
    _S(E6A_OUT, "level_L3.npz"): ("binary", "d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf"),
    _S(E6A_OUT, "level_L4.npz"): ("binary", "d274564968f2de0501fb932c474e127d0ae1d38878d66361b3e93add87ece9d4"),
    _S(E6A_OUT, "level_L5.npz"): ("binary", "7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee"),
    _S(E6B_OUT, "level_L5_static.npz"): ("binary", "a0243706d029ab9fe7239a1a33bf45bc60aa3de201e5669d1912e8a91724b915"),
    _S(E6C_OUT, "run_L5_P.json"): ("text", "caca0fa5a268fed8947b723dad513b725f8bad2779e9612c17f8a56b76e7db1c"),
    _S(E6C_OUT, "run_L5_Q.json"): ("text", "2de4d1bc231a74e8346a901d16dc450b5f2fd9c066058029c4fa72cc2d4d8cdc"),
    _S(E6C_OUT, "run_L5_P_final.npz"): ("binary", "be34ae4a98ceae8b6c9207437df0a66e402fd51ddcc0a38e6139e6b330803d28"),
    _S(E6C_OUT, "run_L5_Q_final.npz"): ("binary", "35d408066a50dd184e0c3853a9df6d33cda0d7c1ec1fde7359741dae22af1c6d"),
    _S(E6C_OUT, "run_L4_P_final.npz"): ("binary", "54b4987fb1f9637b64d8b2fa8278597b33bebbc3f564e58cdb8d36c542b97971"),
}


def sha_input(path, kind):
    b = open(path, "rb").read()
    return hashlib.sha256(b.replace(b"\r\n", b"\n") if kind == "text" else b).hexdigest()


def code_identity():
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
    """PLAN 3: mesh stage 1 GiB + 4 KiB T + 1 KiB N; solve stage E6C L5 peak x T / T0 + 2 GiB."""
    return {f"G{k}": {"mesh_bytes": GIB + 4096 * T_G[k] + 1024 * N_G[k], "solve_bytes": E6C_L5_PEAK * T_G[k] / T_G[0] + 2 * GIB}
            for k in (1, 2)}


def stage(args, timeout):
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e6d.py")] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        print(p.stdout[-100000:], flush=True)
        if p.stderr.strip():
            print("[e6d][stderr]", p.stderr[-4000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    return rc, time.time() - t


def peak(rec):
    v = (rec or {}).get("memory", {}).get("peak_private_bytes")
    return v if isinstance(v, int) else None


def skip_record(path, why):
    ce.dump_strict({"status": "RESOURCE_PREFLIGHT_FAIL", "reason": why}, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    env = envelopes()
    print(f"[e6d] envelopes: {env}", flush=True)
    if a.validate_only:
        for p, (k, want) in INPUTS.items():
            print(f"[e6d] input {os.path.basename(p)}: {sha_input(p, k) == want}", flush=True)
        return 0
    if not hosted:
        print("[e6d] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    T0 = time.time()
    res = {"runner": runner_info(), "envelopes": env, "inputs": {}, "stages": {}, "gates": {}, "review_sha": REVIEW_SHA,
           "registered_max_solves": MAX_SOLVES}
    ok_in = True
    for p, (kind, want) in INPUTS.items():
        got = sha_input(p, kind) if os.path.exists(p) else None
        res["inputs"][os.path.relpath(p, ROOT).replace("\\", "/")] = {"kind": kind, "sha256": got, "expected": want, "equal": got == want}
        ok_in &= got == want
    res["code_paths_identical_to_review_sha"] = code_identity()
    ok_in &= res["code_paths_identical_to_review_sha"]["identical"]
    res["input_identity_ok"] = bool(ok_in)
    flags = {"input_identity_ok": bool(ok_in), "artifact_problems": []}
    if not ok_in:
        res["stop"] = "INPUT_IDENTITY_FAIL"
        return finish(res, flags, {})
    recs = {}
    valid = {}
    for k in (1, 2):
        mp = os.path.join(OUT, f"mesh_G{k}.json")
        why = None
        if env[f"G{k}"]["mesh_bytes"] > MEM_LIMIT:
            why = "mesh envelope above 8 GiB"
        elif k == 2 and peak(recs.get("mesh_G1")) is not None:
            pred = peak(recs["mesh_G1"]) * T_G[2] / T_G[1]
            tpred = 1.5 * res["stages"]["mesh_G1"]["wall_s"] * T_G[2] / T_G[1]
            res["gates"]["mesh_G2_measured"] = {"mem_pred": pred, "t_pred_s": tpred, "elapsed_s": time.time() - T0}
            if pred > MEM_LIMIT or time.time() - T0 + tpred > TIME_LIMIT_S:
                why = "measured G1 mesh-stage peak / wall extrapolated above the limit"
        if why:
            skip_record(mp, why)
            recs[f"mesh_G{k}"] = {"status": "RESOURCE_PREFLIGHT_FAIL"}
            valid[k] = False
            continue
        rc, w = stage(["mesh", OUT, str(k)], STAGE_TIMEOUT_S)
        res["stages"][f"mesh_G{k}"] = {"rc": rc, "wall_s": w}
        recs[f"mesh_G{k}"] = ce.load_strict(mp) if os.path.exists(mp) else {"status": f"NO_RESULT_JSON(rc={rc})"}
        valid[k] = recs[f"mesh_G{k}"].get("status") == "OK" and recs[f"mesh_G{k}"].get("state") == "OK"
    for k in (1, 2):
        for t in ("P", "Q"):
            name = f"G{k}-{t}"
            jp = os.path.join(OUT, f"run_G{k}_{t}.json")
            if not valid[k]:
                continue                                                    # a failed mesh: no import-for-solve, no solve
            why = None
            if env[f"G{k}"]["solve_bytes"] > MEM_LIMIT:
                why = "solve envelope above 8 GiB"
            elif k == 2 and peak(recs.get("G1-P")) is not None:
                pred = peak(recs["G1-P"]) * T_G[2] / T_G[1]
                tpred = 1.5 * res["stages"]["G1-P"]["wall_s"] * T_G[2] / T_G[1]
                res["gates"][f"{name}_measured"] = {"mem_pred": pred, "t_pred_s": tpred, "elapsed_s": time.time() - T0}
                if pred > MEM_LIMIT or time.time() - T0 + tpred > TIME_LIMIT_S:
                    why = "measured G1-P peak / wall extrapolated above the limit"
            if why:
                skip_record(jp, why)
                recs[name] = {"status": "RESOURCE_PREFLIGHT_FAIL"}
                continue
            rc, w = stage(["run", OUT, str(k), t], STAGE_TIMEOUT_S)
            res["stages"][name] = {"rc": rc, "wall_s": w}
            recs[name] = ce.load_strict(jp) if os.path.exists(jp) else {"status": f"NO_RESULT_JSON(rc={rc})"}
    return finish(res, flags, recs)


def expected_files(recs):
    exp = []
    for k in (1, 2):
        m = recs.get(f"mesh_G{k}")
        if m is None:
            continue
        exp.append(f"mesh_G{k}.json")
        if m.get("status") in ("OK", "GATE_FAIL") and "counts" in m:
            exp.append(f"mesh_G{k}.npz")
        if m.get("status") == "OK":
            exp += [f"mesh_G{k}.vtu", f"mesh_G{k}_static.npz"]
        for t in ("P", "Q"):
            r = recs.get(f"G{k}-{t}")
            if r is None:
                continue
            exp.append(f"run_G{k}_{t}.json")
            if r.get("status") == "OK":
                exp += [f"run_G{k}_{t}_init.npz", f"run_G{k}_{t}_final.npz"]
            elif r.get("status") == "INITIALIZATION_CONTRACT_FAIL":
                exp.append(f"run_G{k}_{t}_init.npz")
    return exp


def finish(res, flags, recs):
    res["solve_counts"] = {k: r.get("solve_count") for k, r in recs.items() if k.startswith("G")}
    res["mesh_stage_solve_calls"] = {k: r.get("solve_calls") for k, r in recs.items() if k.startswith("mesh")}
    total = sum(v for v in res["solve_counts"].values() if isinstance(v, int))
    res["total_solve_calls"], res["solve_budget_ok"] = total, total <= MAX_SOLVES
    if not res["solve_budget_ok"]:
        flags["artifact_problems"].append(f"total solve calls {total} > {MAX_SOLVES}")
    for k, v in res["mesh_stage_solve_calls"].items():
        if v not in (0, None):
            flags["artifact_problems"].append(f"{k}: {v} solve calls in the mesh stage")
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
            res["analysis"] = jd.analyze_dir(OUT, E6A_OUT, E6C_OUT, flags)
        except Exception as e:  # noqa: BLE001
            res["analysis_error"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:400]
            res["analysis"] = {"judgement": {"overall": "ARTIFACT_INCOMPLETE", "failure": "ARTIFACT_INCOMPLETE"}}
    else:
        res["analysis"] = {"judgement": {"overall": res.get("stop"), "failure": res.get("stop")}}
    res["verdict"] = {"overall": res["analysis"]["judgement"].get("overall"), "G2_state": res["analysis"]["judgement"].get("G2_state"),
                      "maximum_possible": "NONCORE_REFINEMENT_DECREASE_OBSERVED",
                      "note": "core (|x| <= 0.1 um) potential / fixed-width field change under non-core refinement of the E6A L5 mesh, "
                              "compared with the observed initialization shift only; not an outer-floor absence, not 2D continuum "
                              "convergence, not physics validation; the transition column also changes, so no attribution to the far "
                              "outer grid alone."}
    res["output_files"] = {f: ce.sha_file(os.path.join(OUT, f)) for f in sorted(os.listdir(OUT))} if os.path.isdir(OUT) else {}
    ce.dump_strict(res, os.path.join(OUT, "e6d_result.json"))
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e6d] verdict {res['verdict']} solve_calls={total}", flush=True)
    return 0 if all(s["rc"] == 0 for s in res["stages"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
