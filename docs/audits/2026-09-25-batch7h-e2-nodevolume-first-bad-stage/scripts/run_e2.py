"""Batch 7H-E2 driver (remote profile entry). Refuses to run outside a GitHub-hosted runner.
Runs stage_e2.py in a subprocess, then strict-parses every JSON output. Outputs: <repo>/e2_out (not committed)."""
import argparse
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e2_out")
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    print(f"[e2] GUI defaults (E1): {ce.GUI}", flush=True)
    if a.validate_only:
        return 0
    if not hosted:
        print("[e2] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e2.py"), OUT], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=16000)
        print(p.stdout[-300000:], flush=True)
        if p.stderr.strip():
            print("[e2][stderr]", p.stderr[-6000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        print("[e2] NOT_COMPLETED: stage_e2 timeout 16000 s", flush=True)
        rc = "timeout"
    print(f"[e2] stage_e2 rc={rc} in {time.time() - t:.1f} s", flush=True)
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e2] outputs: {sorted(os.listdir(OUT))}", flush=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
