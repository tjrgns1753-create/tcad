"""Batch 7H-E6A driver (remote profile entry). Refuses to run outside a GitHub-hosted runner. PLAN sections 1, 5, 7:
input identity, resource preflight, one subprocess per stage (regen, L3, L4, L5), cross-level nesting, family verdict.
Outputs: <repo>/e6a_out (not committed)."""
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
OUT = os.path.join(ROOT, "e6a_out")
AUD = os.path.join(ROOT, "docs", "audits")
E4_OUT = os.path.join(AUD, "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate", "data", "remote_run_36143535737", "outputs", "e4_out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402
import family_e6a as fam  # noqa: E402

LEVELS = (3, 4, 5)
GIB = 1 << 30
MEM_LIMIT = 8 * GIB
TIME_LIMIT_S = 7200.0
LEVEL_TIMEOUT_S = 3600
E4_STAGE_S, E4_T = 159.3, 255400                     # 7H-E4 measured stage time and triangle count (PLAN section 5)
INPUTS = {  # path -> (kind, expected sha256); text files compared LF-normalized (PLAN section 1.3)
    os.path.join(HERE, "..", "PLAN.md"): ("text", "5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba"),
    os.path.join(E4_OUT, "candidate_e4.vtu"): ("binary", "85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297"),
    os.path.join(E4_OUT, "candidate_e4.npz"): ("binary", "740a643ed6c965b11ea179993eff2701d87b3c0a9a5990ace71fb2e5df482329"),
    os.path.join(E4_OUT, "e4_result.json"): ("text", "3fdf069717fff85b28602bc55ae1294e836aa4d6baf5c223c0b5420de97d2299"),
}


def sha_input(path, kind):
    b = open(path, "rb").read()
    return hashlib.sha256(b.replace(b"\r\n", b"\n") if kind == "text" else b).hexdigest()


def runner_info():
    info = {"cpu_count": os.cpu_count(), "platform": platform.platform(), "python": platform.python_version()}
    for k in ("RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "ImageOS", "ImageVersion"):
        info[k] = os.environ.get(k)
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        info["total_physical_bytes"] = int(ms.ullTotalPhys)
    except Exception as e:  # noqa: BLE001
        info["total_physical_bytes"] = {"value": None, "status": "UNAVAILABLE: " + repr(e)[:100]}
    return info


def envelopes():
    out = {}
    for L in LEVELS:
        T, N = fam.predicted_counts(L, 100, 200)
        out[f"L{L}"] = {"T": T, "N": N, "memory_bytes": GIB + 4096 * T + 1024 * N, "time_s": 3 * E4_STAGE_S * T / E4_T}
    return out


def stage(args, timeout):
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e6a.py")] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        print(p.stdout[-200000:], flush=True)
        if p.stderr.strip():
            print("[e6a][stderr]", p.stderr[-6000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    return rc, time.time() - t


def peak(r):
    m = r.get("memory", {})
    return m.get("peak_private_bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    env = envelopes()
    print(f"[e6a] envelopes: {env}", flush=True)
    if a.validate_only:
        return 0
    if not hosted:
        print("[e6a] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    T0 = time.time()
    res = {"plan_sha256_LF_expected": INPUTS[os.path.join(HERE, "..", "PLAN.md")][1], "runner": runner_info(),
           "envelopes": env, "inputs": {}, "stages": {}, "labels": {}}
    ok_in = True
    for p, (kind, want) in INPUTS.items():
        got = sha_input(p, kind) if os.path.exists(p) else None
        res["inputs"][os.path.relpath(p, ROOT).replace("\\", "/")] = {"kind": kind, "sha256": got, "expected": want, "equal": got == want}
        ok_in &= got == want
    if not ok_in:
        res["stop"] = "INPUT_IDENTITY_FAIL"
        return finish(res)
    if any(v["memory_bytes"] > MEM_LIMIT for v in env.values()) or sum(v["time_s"] for v in env.values()) > TIME_LIMIT_S:
        res["stop"] = "RESOURCE_PREFLIGHT_FAIL"
        res["labels"] = {f"L{L}": "RESOURCE_PREFLIGHT_FAIL" for L in LEVELS}
        return finish(res)

    rc, w = stage(["regen", OUT], 1800)
    res["stages"]["regen"] = {"rc": rc, "wall_s": w}
    rg = ce.load_strict(os.path.join(OUT, "regen.json")) if os.path.exists(os.path.join(OUT, "regen.json")) else {}
    if rc != 0 or not rg.get("input_identity_ok"):
        res["stop"] = "INPUT_IDENTITY_FAIL"
        return finish(res)

    lv = {}
    for L in LEVELS:
        if L == 5:
            gate = l5_gate(lv, time.time() - T0)
            res["l5_measured_gate"] = gate
            if not gate["run"]:
                res["labels"]["L5"] = "RESOURCE_PREFLIGHT_FAIL"
                continue
        rc, w = stage(["level", OUT, str(L)], LEVEL_TIMEOUT_S)
        res["stages"][f"L{L}"] = {"rc": rc, "wall_s": w}
        f = os.path.join(OUT, f"level_L{L}.json")
        lv[L] = ce.load_strict(f) if os.path.exists(f) else {"error": f"no level json (rc={rc})"}
        lv[L]["_wall_s"] = w
    res["cross_level"] = cross_level()
    for L in LEVELS:
        if L in lv:
            res["labels"][f"L{L}"] = level_label(lv[L])
    res["level_summary"] = {f"L{L}": {"pass": r.get("level_pass"), "failed_checks": r.get("failed_checks"), "stop": r.get("stop"),
                                      "error": r.get("error"), "memory": r.get("memory"), "wall_s": r.get("_wall_s"),
                                      "solve_calls": r.get("solve_calls")} for L, r in lv.items()}
    res["total_wall_s"] = time.time() - T0
    return finish(res, lv)


def l5_gate(lv, elapsed):
    """PLAN section 5, measured gate before L5."""
    T3, T4, T5 = (fam.predicted_counts(L, 100, 200)[0] for L in LEVELS)
    p3, p4 = (peak(lv.get(L, {})) for L in (3, 4))
    t4 = lv.get(4, {}).get("_wall_s")
    if not isinstance(p4, int) or t4 is None:
        return {"run": False, "reason": "L4 peak memory or wall time unavailable", "p3": p3, "p4": p4, "t4": t4}
    prop = p4 * T5 / T4
    lin = p4 + (p4 - p3) * (T5 - T4) / (T4 - T3) if isinstance(p3, int) else prop
    mem_pred = max(prop, lin)
    t_pred = 1.5 * t4 * T5 / T4
    run = mem_pred <= MEM_LIMIT and elapsed + t_pred <= TIME_LIMIT_S
    return {"run": bool(run), "peak_L3": p3, "peak_L4": p4, "mem_pred_proportional": prop, "mem_pred_linear": lin,
            "mem_pred": mem_pred, "mem_limit": MEM_LIMIT, "t_L4_s": t4, "t_pred_L5_s": t_pred, "elapsed_s": elapsed,
            "time_limit_s": TIME_LIMIT_S}


def cross_level():
    """PLAN 4C6: dyadic nesting of the x = 0 y-set and the fine x-lines between consecutive levels."""
    import numpy as np
    z = {L: np.load(os.path.join(OUT, f"level_L{L}.npz")) for L in LEVELS if os.path.exists(os.path.join(OUT, f"level_L{L}.npz"))}
    out = {}
    for L in (4, 5):
        if L in z and L - 1 in z:
            out[f"L{L - 1}_in_L{L}"] = {"x0_y_nested": bool(np.array_equal(z[L]["x0_y_um_f32"][::2], z[L - 1]["x0_y_um_f32"])),
                                         "fine_x_nested": bool(np.array_equal(z[L]["fine_x_um_f32"][::2], z[L - 1]["fine_x_um_f32"]))}
        else:
            out[f"L{L - 1}_in_L{L}"] = {"status": "NOT_EVALUATED_LEVEL_MISSING"}
    return out


def level_label(r):
    """First-failure label per level (PLAN section 7); every failed check is still listed in level_summary."""
    if r.get("level_pass"):
        return "PASS"
    if r.get("stop"):
        return r["stop"]
    if "error" in r:
        return "GEOMETRY_PROOF_INCOMPLETE"
    f = set(r.get("failed_checks", []))
    order = [("input_identity", "INPUT_IDENTITY_FAIL"), ("solve_calls_0", "SOLVE_CALLED"),
             ("L4_reproduction", "L4_REPRODUCTION_FAIL"), ("construction_counts", "CONSTRUCTION_COUNT_MISMATCH"),
             ("B2_no_obtuse", "OBTUSE_TRIANGLE"), ("B4_tiling_T2", "NONCONFORMING_MESH"), ("B4_tiling_T3", "NONCONFORMING_MESH"),
             ("B1_orientation_positive", "NONCONFORMING_MESH"), ("B3_no_duplicates", "NONCONFORMING_MESH"),
             ("hanging_midpoints_owned", "NONCONFORMING_MESH"), ("B5_area_equals_rect", "AREA_OR_VOLUME_FAIL"),
             ("B5_area_equals_S0", "AREA_OR_VOLUME_FAIL"), ("D3_ratio_within_tau", "AREA_OR_VOLUME_FAIL"),
             ("D4_nodevolume_eq_F3_within_budget", "AREA_OR_VOLUME_FAIL"), ("B6_tags", "CONTACT_OR_TAG_FAIL"),
             ("B6_contacts_equal_S0", "CONTACT_OR_TAG_FAIL"), ("D2_contacts", "CONTACT_OR_TAG_FAIL"), ("C_resolution", "RESOLUTION_FAIL")]
    for k, lab in order:
        if k in f:
            return lab
    return "FAILED_OTHER:" + ",".join(sorted(f))


def finish(res, lv=None):
    lv = lv or {}
    files = sorted(os.listdir(OUT))
    res["output_files"] = {f: ce.sha_file(os.path.join(OUT, f)) for f in files}
    expected = ["regen.json", "wafer_volume.vtu"] + [f"level_L{L}.{e}" for L in LEVELS for e in ("json", "npz", "vtu")]
    res["missing_expected_files"] = [f for f in expected if f not in files]
    cl = res.get("cross_level", {})
    nested = all(v.get("x0_y_nested") and v.get("fine_x_nested") for v in cl.values()) and len(cl) == 2
    all_pass = (not res.get("stop") and all(res["labels"].get(f"L{L}") == "PASS" for L in LEVELS) and nested
                and not res["missing_expected_files"] and sum(r.get("solve_calls", 0) for r in lv.values()) == 0)
    res["verdict"] = {"verdict": "GEOMETRY_FAMILY_CANDIDATE_ONLY" if all_pass else "FAMILY_NOT_ACCEPTED", "labels": res["labels"],
                      "stop": res.get("stop"), "cross_level_nested": nested, "missing_expected_files": res["missing_expected_files"],
                      "note": "geometry and DEVSIM default integration weight only; not Poisson/current mesh convergence, not "
                              "current accuracy, not biased I-V, not production step-junction or process-order support"}
    ce.dump_strict(res, os.path.join(OUT, "e6a_result.json"))
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e6a] verdict {res['verdict']}", flush=True)
    print(f"[e6a] outputs: {sorted(os.listdir(OUT))}", flush=True)
    # rc reports execution only (a stage crashed / timed out); the geometric verdict lives in e6a_result.json
    return 0 if all(s["rc"] == 0 for s in res["stages"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
