"""Batch 7H-E1 driver (remote profile entry). A: production build + control + pre-checks; B: shadows S0, S12 only if
the control held and the capture is complete; C: analysis. Refuses to run outside a GitHub-hosted runner.
Exit 0 only if step A produced prod.json without error and the analysis ran (physics verdicts are in analysis_e1.json).
Outputs: <repo>/e1_out (not committed)."""
import argparse
import os
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e1_out")
WORK = os.path.join(ROOT, "e1_work")
sys.path.insert(0, HERE)
import common_e1 as ce  # noqa: E402


def step(name, args, timeout):
    t = time.time()
    print(f"\n[e1] ===== {name} =====", flush=True)
    try:
        p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        print(p.stdout[-200000:], flush=True)
        if p.stderr.strip():
            print("[e1][stderr]", p.stderr[-4000:], flush=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        print(f"[e1] NOT_COMPLETED: {name} timeout {timeout} s", flush=True)
        rc = "timeout"
    print(f"[e1] {name} rc={rc} in {time.time() - t:.1f} s", flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    print(f"[e1] GUI defaults reproduced: {ce.GUI}", flush=True)
    if a.validate_only:
        return 0
    if not hosted:
        print("[e1] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    step("A production build + control + pre-checks", [os.path.join(HERE, "prod_build_e1.py"), WORK], 7200)
    prod_path = os.path.join(WORK, "prod.json")
    if not os.path.exists(prod_path):
        print("[e1] STOP: prod.json missing", flush=True)
        return 1
    prod = ce.load_strict(prod_path)
    go = ("error" not in prod and (prod.get("control") or {}).get("verdict") == "GATE_HELD"
          and (prod.get("capture") or {}).get("one_record_per_node_in_order") and (prod.get("capture") or {}).get("all_known"))
    print(f"[e1] shadow allowed by PLAN: {bool(go)}", flush=True)
    if go:
        for v in ("S0", "S12"):
            step(f"B shadow {v}", [os.path.join(HERE, "shadow_e1.py"), WORK, v], 7200)
    rc = step("C analysis", [os.path.join(HERE, "analyze_e1.py"), WORK, OUT], 3600)
    for f in os.listdir(WORK):
        if f.endswith((".json", ".npz")):
            shutil.copyfile(os.path.join(WORK, f), os.path.join(OUT, f))
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            ce.load_strict(os.path.join(OUT, f))     # every JSON must parse strictly
    print(f"[e1] outputs: {sorted(os.listdir(OUT))}", flush=True)
    return 0 if "error" not in prod and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
