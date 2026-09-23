#!/usr/bin/env python3
"""Driver: run Question B's grid sweep, one real ViennaPS process per
grid, each under a wall-clock timeout. A timeout or crash on one grid is
recorded as evidence, never silently dropped or backfilled."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUT_DIR = Path(sys.argv[1]).resolve()
PYTHON = sys.argv[2] if len(sys.argv) > 2 else sys.executable
GRIDS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05]
TIMEOUT_S = 240
SCRIPT = str(Path(__file__).resolve().parent / "run_case_B.py")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", KMP_DUPLICATE_LIB_OK="TRUE")

OUT_DIR.mkdir(parents=True, exist_ok=True)
summary = []
for grid in GRIDS:
    label = f"B_grid_{grid:.4f}".replace(".", "p")
    print(f"=== {label} (timeout={TIMEOUT_S}s) ===", flush=True)
    started = time.time()
    try:
        proc = subprocess.run(
            [PYTHON, SCRIPT, str(OUT_DIR), str(grid)],
            capture_output=True, text=True, timeout=TIMEOUT_S, env=ENV,
        )
        elapsed = time.time() - started
        entry = {"grid_delta_um": grid, "label": label, "elapsed_wall_s": elapsed,
                  "returncode": proc.returncode, "timed_out": False}
        print(proc.stdout[-2000:])
        if proc.returncode != 0:
            print("STDERR:", proc.stderr[-3000:])
            entry["stderr_tail"] = proc.stderr[-3000:]
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - started
        entry = {"grid_delta_um": grid, "label": label, "elapsed_wall_s": elapsed,
                  "returncode": None, "timed_out": True,
                  "note": f"killed after {TIMEOUT_S}s wall-clock limit -- recorded as-is, not retried/extended"}
        print(f"TIMEOUT after {TIMEOUT_S}s")
    summary.append(entry)

(OUT_DIR / "B_matrix_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n\nDONE:", OUT_DIR / "B_matrix_summary.json")
