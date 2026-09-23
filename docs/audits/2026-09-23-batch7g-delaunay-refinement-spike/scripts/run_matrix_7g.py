"""Batch 7G Phase 1 -- dispatch every geometry case, subprocess-isolated,
fixed CASE_TIMEOUT_S from the manifest, never raised after seeing a result.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

with open(os.path.join(DATA, "case_manifest_7g.json"), encoding="utf-8") as f:
    MANIFEST = json.load(f)

CASE_TIMEOUT_S = MANIFEST["case_timeout_s"]


def run_one(case):
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "probe_delaunay_7g.py"), json.dumps(case)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CASE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"label": case["label"], "error": f"TIMEOUT after {CASE_TIMEOUT_S}s", "wall_s": time.time() - t0, **case}
    out = p.stdout
    wall = time.time() - t0
    if "===RESULT_JSON===" not in out:
        return {"label": case["label"], "error": f"no result JSON (rc={p.returncode}); tail: {(out + p.stderr)[-1200:]}",
                "wall_s": wall, **case}
    r = json.loads(out.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
    r["wall_s"] = wall
    return r


if __name__ == "__main__":
    results = []
    for case in MANIFEST["geometry_cases"]:
        r = run_one(case)
        results.append(r)
        if "error" in r:
            print(f"[{case['label']}] ERROR: {r['error'][:300]}")
        else:
            print(f"[{case['label']}] n_tri={r['n_triangles']} delaunay_violations={r['n_delaunay_violations']} "
                  f"({r['delaunay_violation_rate']*100:.3f}%) by_zone={r['violations_by_zone']} "
                  f"hanging={r['n_hanging_nodes']} overlap_pairs={r['n_overlap_pairs']} "
                  f"hole={r['boundary_holes']['uncovered_hole_area']} "
                  f"NodeVolume_excess_relerr={r['total_excess_relative']} wall_s={r['wall_s']:.1f}")
    path = os.path.join(DATA, "geometry_7g.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"geometry_7g": results}, f, indent=2, default=str)
    print("Wrote", path)
