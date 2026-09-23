#!/usr/bin/env python3
"""Driver: Question C's 9-case explicit-planar-oxide matrix, one real
ViennaPS process per case, each under a wall-clock timeout."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUT_DIR = Path(sys.argv[1]).resolve()
PYTHON = sys.argv[2] if len(sys.argv) > 2 else sys.executable
TIMEOUT_S = 240
SCRIPT = str(Path(__file__).resolve().parent / "run_case_C.py")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", KMP_DUPLICATE_LIB_OK="TRUE")

# (initial_oxide_um, [grids], x_extent, y_extent)
GROUPS = [
    (0.002, [0.001, 0.002, 0.005], 0.3, 0.5),
    (0.02, [0.01, 0.02, 0.05], 3.0, 2.0),
    (0.05, [0.02, 0.05, 0.1], 4.0, 2.0),
]

OUT_DIR.mkdir(parents=True, exist_ok=True)
summary = []
for oxide_um, grids, x_ext, y_ext in GROUPS:
    for grid in grids:
        label = f"C_oxide{oxide_um:.4f}_grid{grid:.4f}".replace(".", "p")
        print(f"=== {label} (x={x_ext},y={y_ext}, timeout={TIMEOUT_S}s) ===", flush=True)
        started = time.time()
        try:
            proc = subprocess.run(
                [PYTHON, SCRIPT, str(OUT_DIR), label, str(grid), str(oxide_um), str(x_ext), str(y_ext)],
                capture_output=True, text=True, timeout=TIMEOUT_S, env=ENV,
            )
            elapsed = time.time() - started
            entry = {"label": label, "initial_oxide_um": oxide_um, "grid_delta_um": grid,
                      "elapsed_wall_s": elapsed, "returncode": proc.returncode, "timed_out": False}
            print(proc.stdout[-1500:])
            if proc.returncode != 0:
                print("STDERR:", proc.stderr[-3000:])
                entry["stderr_tail"] = proc.stderr[-3000:]
        except subprocess.TimeoutExpired:
            elapsed = time.time() - started
            entry = {"label": label, "initial_oxide_um": oxide_um, "grid_delta_um": grid,
                      "elapsed_wall_s": elapsed, "returncode": None, "timed_out": True,
                      "note": f"killed after {TIMEOUT_S}s -- recorded as-is"}
            print(f"TIMEOUT after {TIMEOUT_S}s")
        summary.append(entry)

(OUT_DIR / "C_matrix_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\n\nDONE:", OUT_DIR / "C_matrix_summary.json")
