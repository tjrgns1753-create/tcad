"""Batch 7H-E5 driver (remote profile entry). Refuses to run outside a GitHub-hosted runner.
Runs stage_e5.py in a subprocess (real devsim.solve calls -- not trapped), then strict-parses every JSON output.
Outputs: <repo>/e5_out (not committed)."""
import argparse
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e5_out")
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    print("[e5] Batch 7H-E5: 0V equilibrium pilot, 6 runs {D2D,D1D_J0,D1D_J1}x{S0,S12}", flush=True)
    if a.validate_only:
        return 0
    if not hosted:
        print("[e5] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    t = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "stage_e5.py"), OUT], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8000)
        print(p.stdout[-300000:], flush=True)
        if p.stderr.strip():
            print("[e5][stderr]", p.stderr[-6000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        print("[e5] NOT_COMPLETED: stage_e5 timeout 8000 s", flush=True)
        rc = "timeout"
    print(f"[e5] stage_e5 rc={rc} in {time.time() - t:.1f} s", flush=True)
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))
    print(f"[e5] outputs: {sorted(os.listdir(OUT))}", flush=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
