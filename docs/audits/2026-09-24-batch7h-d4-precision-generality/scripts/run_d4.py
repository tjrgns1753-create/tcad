"""Batch 7H-D4 driver (remote profile entry). Order: fixture regeneration + hash gate, six runs (one subprocess
each), then analyze_d4.py --mode d4. Refuses to run outside a GitHub-hosted runner (--validate-only lists and checks).
Exit 0 only if the fixture gate passed, every run produced a JSON without error and the analysis reported
EVIDENCE_INTEGRITY_PASS. Physics verdicts are in analysis_d4_mode_d4.json (runner PASS != physics PASS).
Outputs: <repo>/d4_out (not committed)."""
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
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
D4 = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "d4_out")
D2S = os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-d2-current-precision")
FIXD2 = os.path.join(D2S, "data", "fixtures_d2.json")
SHA_D2 = "e2c018a62292c4f4f9e215a8aa525148c15a618bc50792c141318a6a81f3a6f2"
PER_RUN_TIMEOUT_S = 3600
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")
sys.path.insert(0, HERE)
import analyze_d4 as A4  # noqa: E402


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    m = A4.expected_matrix("d4")
    plan = A4.sha_lf(os.path.join(D4, "PLAN.md"))
    print(f"[d4] {len(m)} runs; PLAN sha256 {plan} pinned {A4.PLAN_SHA['d4']} match={plan == A4.PLAN_SHA['d4']}", flush=True)
    for k in m:
        print("[d4]  ", k, flush=True)
    if a.validate_only:
        return 0
    if not hosted:
        print("[d4] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(os.path.join(OUT, "runs"), exist_ok=True)
    gate = {"expected_sha256": SHA_D2}
    if os.path.exists(FIXD2):
        gate["preexisting_file"] = True     # not expected in a fresh checkout (fixtures_d2.json is not in Git)
    t = time.time()
    p = subprocess.run([sys.executable, os.path.join(D2S, "scripts", "build_fixtures_d2.py")], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=7200)
    gate.update({"regeneration_exit_code": p.returncode, "regeneration_s": round(time.time() - t, 1),
                 "stdout_tail": USER_PATH.sub("<USERPROFILE>", p.stdout[-1500:]), "stderr_tail": USER_PATH.sub("<USERPROFILE>", p.stderr[-1500:])})
    gate["sha256"] = sha_file(FIXD2) if os.path.exists(FIXD2) else None
    gate["match"] = gate["sha256"] == SHA_D2
    json.dump(gate, open(os.path.join(OUT, "fixture_gate.json"), "w", encoding="utf-8"), indent=1)
    print(f"[d4] fixture gate: {json.dumps({k: gate[k] for k in ('regeneration_exit_code', 'regeneration_s', 'sha256', 'match')})}", flush=True)
    if not gate["match"]:
        print("[d4] STOP: regenerated fixtures_d2.json hash != D2-recorded value; no solve started", flush=True)
        return 1
    bad = []
    for rid, cfg in m.items():
        path = os.path.join(OUT, "runs", rid + ".json")
        print(f"\n[d4] ===== {rid} =====", flush=True)
        t = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(HERE, "worker_d4.py"), json.dumps(cfg), path], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PER_RUN_TIMEOUT_S)
            print(p.stdout, flush=True)
            if p.stderr.strip():
                print("[d4][stderr]", p.stderr[-3000:], flush=True)
            ok = os.path.exists(path) and "error" not in json.load(open(path, encoding="utf-8"))
        except subprocess.TimeoutExpired:
            print(f"[d4] NOT_COMPLETED: timeout after {PER_RUN_TIMEOUT_S} s", flush=True)
            json.dump({"cfg": cfg, "error": "NOT_COMPLETED: timeout"}, open(path, "w", encoding="utf-8"))
            ok = False
        print(f"[d4] {rid} completed={ok} in {time.time() - t:.1f} s", flush=True)
        if not ok:
            bad.append(rid)
    rc = subprocess.run([sys.executable, os.path.join(HERE, "analyze_d4.py"), "--mode", "d4", "--runs", os.path.join(OUT, "runs"),
                         "--out", OUT, "--plan-dir", D4], cwd=ROOT).returncode
    n = 0
    for base, _, files in os.walk(OUT):
        for f in files:
            if f.endswith((".json", ".md", ".txt")):
                q = os.path.join(base, f)
                s = open(q, encoding="utf-8", errors="replace").read()
                s2, k = USER_PATH.subn("<USERPROFILE>", s)
                if k:
                    open(q, "w", encoding="utf-8", newline="\n").write(s2)
                    n += k
    print(f"[d4] output scrub replacements: {n}; runs not completed: {bad}; analysis rc={rc} (0 = integrity pass)", flush=True)
    return 0 if not bad and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
