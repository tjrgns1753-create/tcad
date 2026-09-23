"""Batch 7H-D3 driver (remote profile entry). Runs each configuration in its own subprocess,
then the PLAN analysis. Refuses to run outside a GitHub-hosted runner (--validate-only lists the
matrix and checks inputs). Exit 0 only if every run produced a JSON without error and the analysis
was written; the physics verdicts live in analysis_d3.json (runner PASS != physics PASS).
Outputs go to <repo>/d3_out (not committed)."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))   # scripts -> batch -> audits -> docs -> repo root
D3 = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "d3_out")
PER_RUN_TIMEOUT_S = 1500
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")


def matrix():
    m = []
    for P in ("P0", "P12", "P4"):
        m.append({"id": f"E1_M2_D0_h0.005_{P}", "kind": "2d", "fam": "M2", "variant": "D0", "h": 0.005, "P": P, "mirror": False})
    for P in ("P4", "P0"):
        for side in ("orig", "mirror"):
            m.append({"id": f"E2_1D_h0.005_{P}_{side}", "kind": "1d", "h": 0.005, "P": P, "mirror": side == "mirror"})
            m.append({"id": f"E2_M1_h0.005_{P}_{side}", "kind": "2d", "fam": "M1", "variant": "D0", "h": 0.005, "P": P, "mirror": side == "mirror"})
    return m


def sha_lf(path):
    return hashlib.sha256(open(path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    cfgs = matrix()
    plan_sha, recorded = sha_lf(os.path.join(D3, "PLAN.md")), open(os.path.join(D3, "PLAN.sha256"), encoding="utf-8").read().split()[0]
    print(f"[d3] matrix: {len(cfgs)} runs; PLAN sha256 {plan_sha} (recorded {recorded}, match={plan_sha == recorded})", flush=True)
    for c in cfgs:
        print("[d3]  ", c["id"])
    if a.validate_only:
        return 0
    if not hosted:
        print("[d3] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(os.path.join(OUT, "runs"), exist_ok=True)
    bad = []
    for c in cfgs:
        path = os.path.join(OUT, "runs", c["id"] + ".json")
        print(f"\n[d3] ===== {c['id']} =====", flush=True)
        t = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(HERE, "worker_d3.py"), json.dumps(c), path], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PER_RUN_TIMEOUT_S)
            print(p.stdout, flush=True)
            if p.stderr.strip():
                print("[d3][stderr]", p.stderr[-3000:], flush=True)
            ok = os.path.exists(path) and "error" not in json.load(open(path, encoding="utf-8"))
        except subprocess.TimeoutExpired:
            print(f"[d3] TIMEOUT after {PER_RUN_TIMEOUT_S} s", flush=True)
            json.dump({"cfg": c, "error": "NOT_COMPLETED: timeout"}, open(path, "w", encoding="utf-8"))
            ok = False
        print(f"[d3] {c['id']} completed={ok} in {time.time() - t:.1f} s", flush=True)
        if not ok:
            bad.append(c["id"])
    rc = subprocess.run([sys.executable, os.path.join(HERE, "analyze_d3.py"), "--runs", os.path.join(OUT, "runs"), "--out", OUT,
                         "--plan-dir", D3], cwd=ROOT).returncode
    n = 0
    for base, _, files in os.walk(OUT):      # outputs are not passed through the runner sanitizer: scrub user paths here
        for f in files:
            p = os.path.join(base, f)
            s = open(p, encoding="utf-8", errors="replace").read()
            s2, k = USER_PATH.subn("<USERPROFILE>", s)
            if k:
                open(p, "w", encoding="utf-8", newline="\n").write(s2)
                n += k
    print(f"[d3] output scrub replacements: {n}; runs not completed: {bad}; analysis rc={rc}", flush=True)
    return 0 if not bad and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
