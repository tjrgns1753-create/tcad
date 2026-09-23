# -*- coding: utf-8 -*-
"""Driver: run every experiment script in its own process, capturing native
stdout/stderr (fd-level) into raw/<job>.stdout.txt / .stderr.txt and the
return codes into raw/run_log.json. Optional argv: job names to run only."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "raw"
RAW.mkdir(exist_ok=True)
JOBS = [("exp1_deposited", []), ("exp2_explicit", []), ("exp3_devsim_import", []), ("exp4_etch", []),
        ("exp5_thin_layer", []), ("exp6_wrapped_locos", []),
        ("exp6b_nofixup_chain", ["deposition"]), ("exp6b_nofixup_chain", ["etch"]),
        ("exp7_fresh_zero_duration", []), ("exp8_contact_mode", []),
        ("exp9_resist_and_wafer_state", []), ("exp10_export_offset", [])]
only = set(sys.argv[1:])
log = []
for name, args in JOBS:
    tag = name + ("_" + args[0] if args else "")
    if only and tag not in only and name not in only:
        continue
    t0 = time.time()
    with open(RAW / f"{tag}.stdout.txt", "wb") as so, open(RAW / f"{tag}.stderr.txt", "wb") as se:
        p = subprocess.run([sys.executable, str(HERE / f"{name}.py"), *args], stdout=so, stderr=se,
                           env=os.environ.copy(), cwd=str(HERE))
    log.append({"job": tag, "returncode": p.returncode, "seconds": round(time.time() - t0, 1)})
    print(log[-1], flush=True)
with open(RAW / ("run_log.json" if not only else "run_log_partial.json"), "w") as f:
    json.dump(log, f, indent=1)

