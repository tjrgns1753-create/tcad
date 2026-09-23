"""Read-only production audit. Run scripts serially; retain full logs and budgets.

This is a bounded audit run, not the project's full-budget regression runner.
No production files or existing assertions are modified.
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
OUT = Path(__file__).resolve().parent / "validated-env"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
lib = ROOT.parent / ".venv/Library/bin"
os.environ["PATH"] = str(lib) + os.pathsep + os.environ["PATH"]
os.environ["DEVSIM_MATH_LIBS"] = "mkl_rt.3.dll"


def main():
    OUT.mkdir(exist_ok=True)
    versions = {p: importlib.metadata.version(p) for p in ("ViennaPS", "devsim", "numpy", "meshio")}
    print("VERSIONS", versions, flush=True)
    priority = [
        "test_wafer_state_v2_initial_geometry_devsim_real.py",
        "test_physics_references_real.py", "test_etch_selectivity_real.py",
        "test_order_independence_real.py", "test_thermal_anneal_acceptance_real.py",
        "test_gui_thermal_anneal_real.py", "test_ce1_order_sensitive_geometry_real.py",
        "test_ce2_oxidation_conversion_unsupported_real.py",
        "test_ce3_implant_anneal_etch_implant_real.py",
        "test_gui_measurement_doping_kinds_real.py",
    ]
    units = sorted((ROOT / "tests/unit").glob("test_*.py"))
    integration = sorted((ROOT / "tests/integration").glob("test_*.py"),
                         key=lambda p: (priority.index(p.name) if p.name in priority else len(priority), p.name))
    paths = units + integration
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
        row = dict(test=str(path.relative_to(ROOT)), status=status, returncode=rc,
                   seconds=round(time.monotonic()-started, 3), budget_s=budget, log=log.name)
        results.append(row)
        (OUT / "results.json").write_text(json.dumps(dict(versions=versions,
            environment={k: os.environ[k] for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "DEVSIM_MATH_LIBS")},
            planned=len(paths), complete=len(results)==len(paths), results=results), indent=2), encoding="utf-8")
        print(status, path.name, row["seconds"], flush=True)
    print("SUMMARY", {s:sum(r["status"]==s for r in results) for s in sorted({r["status"] for r in results})}, flush=True)


if __name__ == "__main__":
    main()
