"""Tier 1-1 r4 final full audit. ONE run, serially: the 2026-09-16
baseline's exact 120 test files in its own order (so that prefix can be
compared to the baseline 91/29 cohort-for-cohort), followed by the 4
files new since that baseline (not 3 -- test_float32_boundary_snap_real.py
was added this round for task 2's real regression; see the submission
for the exact reconciliation). Same per-file budgets (unit 60s /
integration 180s) and the same environment as
docs/audits/2026-09-16/run_audit.py. Writes to ./full-audit/, run
exactly once; nothing here overwrites the baseline or any prior round's
evidence dir.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "docs/audits/2026-09-16/validated-env/results.json"
OUT = Path(__file__).resolve().parent / "full-audit"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["PATH"] = str(ROOT.parent / ".venv/Library/bin") + os.pathsep + os.environ["PATH"]
os.environ["DEVSIM_MATH_LIBS"] = "mkl_rt.3.dll"


def main():
    OUT.mkdir(exist_ok=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline_paths = [ROOT / row["test"] for row in baseline["results"]]
    assert len(baseline_paths) == 120, len(baseline_paths)
    baseline_rel = {str(p.relative_to(ROOT)).replace("\\", "/") for p in baseline_paths}

    units = sorted((ROOT / "tests/unit").glob("test_*.py"))
    integ = sorted((ROOT / "tests/integration").glob("test_*.py"))
    current_all = units + integ
    new_paths = [p for p in current_all
                if str(p.relative_to(ROOT)).replace("\\", "/") not in baseline_rel]

    paths = baseline_paths + new_paths  # baseline's own 120, in its own order, then new files appended
    print("NEW_FILES_APPENDED", [str(p.relative_to(ROOT)).replace("\\", "/") for p in new_paths], flush=True)

    versions = {p: importlib.metadata.version(p) for p in ("ViennaPS", "devsim", "numpy", "meshio")}
    print("VERSIONS", versions, flush=True)
    results = []
    for idx, path in enumerate(paths, 1):
        budget = 60 if path.parent.name == "unit" else 180
        started = time.monotonic()
        log = OUT / (path.stem + ".log")
        print(f"START {idx}/{len(paths)} {path.name} budget={budget}s", flush=True)
        with log.open("w", encoding="utf-8") as handle:
            p = subprocess.Popen([sys.executable, "-u", str(path)], cwd=ROOT,
                                 stdout=handle, stderr=subprocess.STDOUT, env=os.environ)
            try:
                rc = p.wait(timeout=budget)
                content = log.read_text(encoding="utf-8", errors="replace")
                status = "PASS" if rc == 0 else "FAIL"
                if rc == 0 and ("SKIPPED:" in content or "SKIP:" in content):
                    status = "SKIP_OR_PARTIAL"
            except subprocess.TimeoutExpired:
                cleanup = subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                                         capture_output=True, text=True, timeout=20)
                handle.write("\nAUDIT TIME BUDGET EXHAUSTED; not a physics-failure verdict\n")
                handle.write(cleanup.stdout + cleanup.stderr)
                p.wait(timeout=20)
                rc, status = p.returncode, "AUDIT_TIMEOUT"
        row = dict(test=str(path.relative_to(ROOT)).replace("\\", "/"), status=status, returncode=rc,
                   seconds=round(time.monotonic() - started, 3), budget_s=budget, log=log.name,
                   is_new_since_baseline=path in new_paths)
        results.append(row)
        (OUT / "results.json").write_text(json.dumps(dict(
            versions=versions,
            environment={k: os.environ[k] for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "DEVSIM_MATH_LIBS")},
            planned=len(paths), complete=len(results) == len(paths), results=results), indent=2),
            encoding="utf-8")
        print(status, path.name, row["seconds"], flush=True)
    print("SUMMARY", {s: sum(r["status"] == s for r in results) for s in sorted({r["status"] for r in results})},
          flush=True)


if __name__ == "__main__":
    main()
