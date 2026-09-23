"""Tier 1-1 r3, step 2: related existing tests, serially, same
environment as the full audit. Every unit test plus the integration
tests that reach apply_doping / net_doping_at / the robust sweep / a
GUI measurement. Writes logs + results.json to ./related/.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "related"
OUT.mkdir(exist_ok=True)
env = dict(os.environ)
env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", KMP_DUPLICATE_LIB_OK="TRUE",
           OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", DEVSIM_MATH_LIBS="mkl_rt.3.dll")
env["PATH"] = str(ROOT.parent / ".venv/Library/bin") + os.pathsep + env["PATH"]

units = sorted((ROOT / "tests/unit").glob("test_*.py"))
integration = [ROOT / "tests/integration" / n for n in (
    "test_measurement_canonical_state_gate_real.py",
    "test_gui_implant_windows_overlay_note_real.py",
    "test_wafer_state_v2_initial_geometry_devsim_real.py",
    "test_gui_measurement_captures_physics_status_real.py",
    "test_dopant_profile_matches_devsim_real.py",
    "test_float32_boundary_snap_real.py",
    "test_doping_mapping_per_node_real.py",
    "test_doping_mapping_recovery_real.py",
    "test_gui_doping_donor_acceptor_real.py",
    "test_gui_measurement_doping_kinds_real.py",
    "test_robust_iv_sweep_real.py",
    "test_gui_electrode_panel_real.py",
    "test_phase8_pn_junction_real.py",
    "test_device_lifecycle_repeat_real.py",
)]
rows = []
for path in units + integration:
    budget = 120 if path.parent.name == "unit" else 600
    log = OUT / (path.stem + ".log")
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run([sys.executable, "-u", str(path)], cwd=ROOT, stdout=fh,
                                stderr=subprocess.STDOUT, env=env, timeout=budget).returncode
            status = "PASS" if rc == 0 else "FAIL"
        except subprocess.TimeoutExpired:
            rc, status = None, "TIMEOUT"
    rows.append(dict(test=str(path.relative_to(ROOT)), status=status, rc=rc,
                     seconds=round(time.monotonic() - started, 2)))
    print(status, path.name, rows[-1]["seconds"], flush=True)
(OUT / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
print("SUMMARY", {s: sum(r["status"] == s for r in rows) for s in {r["status"] for r in rows}})
