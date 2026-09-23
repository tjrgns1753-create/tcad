"""Batch 7F -- dispatch every case in case_manifest.json, each its own
subprocess (devsim.solve() has no device= filter; one un-torn-down device
corrupts every later case in the same process -- established project
convention, e.g. tcad/cli/run_pipeline.py's own comment). Fixed
CASE_TIMEOUT_S, set once, never raised after seeing a result.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

with open(os.path.join(DATA, "case_manifest.json"), encoding="utf-8") as f:
    MANIFEST = json.load(f)

CASE_TIMEOUT_S = MANIFEST["case_timeout_s"]


def run_one(case):
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "probe_case_7f.py"), json.dumps(case)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CASE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"label": case["label"], "error": f"TIMEOUT after {CASE_TIMEOUT_S}s", "wall_s": time.time() - t0, **case}
    out = p.stdout
    wall = time.time() - t0
    if "===RESULT_JSON===" not in out:
        return {"label": case["label"], "error": f"no result JSON (rc={p.returncode}); tail: {(out + p.stderr)[-1000:]}",
                "wall_s": wall, **case}
    r = json.loads(out.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
    r["wall_s"] = wall
    return r


def run_group(name, cases):
    print(f"=== {name} ({len(cases)} cases, CASE_TIMEOUT_S={CASE_TIMEOUT_S}) ===")
    results = []
    for case in cases:
        r = run_one(case)
        results.append(r)
        if "error" in r:
            print(f"[{case['label']}] ERROR: {r['error'][:200]}")
        else:
            eq = r.get("equilibrium_converged")
            inv = r.get("inventory", {})
            print(f"[{case['label']}] n_nodes={r.get('n_nodes')} eq_ok={eq} "
                  f"NodeVolume_vs_triangulated_relerr={inv.get('sum_NodeVolume_vs_triangulated_area_relative_error')} "
                  f"wall_s={r['wall_s']:.1f}")
    path = os.path.join(DATA, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({name: results}, f, indent=2, default=str)
    print("Wrote", path)
    return results


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "imported"):
        run_group("imported_7f", MANIFEST["imported_cases"])
    if stage in ("all", "structured"):
        run_group("structured_7f", MANIFEST["structured_cases"])
