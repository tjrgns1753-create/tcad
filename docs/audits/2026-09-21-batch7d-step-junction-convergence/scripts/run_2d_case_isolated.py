"""Batch 7D -- run exactly ONE 2D case in its own fresh process and print its result as one JSON line on stdout.

Found by inspection of a contaminated run: `devsim.solve()` takes no `device=` filter -- it solves EVERY currently
registered device together (this project's own tcad/cli/run_pipeline.py already documents this: "devsim.solve()
takes no `device=` argument -- it solves ALL registered devices"). When one case's device fails to fully converge
and is left in a divergent numerical state, that device is not always safely removable by `delete_device()`
afterward, so it silently keeps corrupting every later case's solve() call in the SAME process -- exactly what
this project's own tests/run_regression.py already avoids by running every test file as its own subprocess. This
script applies that same, already-established isolation pattern per case; it changes NOTHING about DEVSIM itself.
usage: python run_2d_case_isolated.py <level> <representation> <shifted:0|1> <relative_error> <maximum_iterations> <label>
"""
import json
import os
import sys
import tempfile
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
sys.path.insert(0, os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

import probe_step_junction_convergence as base  # noqa: E402

level, representation, shifted_i, rel_err, max_it, label = sys.argv[1:7]
level, shifted, rel_err, max_it = int(level), bool(int(shifted_i)), float(rel_err), int(max_it)

with tempfile.TemporaryDirectory() as tmp:
    process_result = base.build_2d_mesh_once(tmp)
    r = base.run_case_2d(process_result, level, representation, shifted, label, relative_error=rel_err, maximum_iterations=max_it)

print("===RESULT_JSON===")
print(json.dumps(r, default=str))
