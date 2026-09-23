"""Batch 7D Rev.2 -- dispatch the full (geometry x level x representation x shifted) matrix, each case its own
subprocess (see probe_case.py's own docstring). Levels L0-L5 (L0-L3 re-run under the corrected probe; L4/L5 are
new, Trial-B tolerance only, per the bounded prompt). A FIXED timeout/resource budget is set once here and never
raised after seeing results -- CASE_TIMEOUT_S below. A timeout is recorded as its own outcome, not silently
dropped.
usage: python run_matrix.py
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)

#: Fixed once, for every case in this run, both L0-L3 and L4-L5. Not adjusted after seeing any result.
CASE_TIMEOUT_S = 900


def run_one(geometry, level, representation, shifted, rel_err, max_it, label):
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "probe_case.py"), geometry, str(level), representation, "1" if shifted else "0",
             str(rel_err), str(max_it), label],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CASE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"label": label, "geometry": geometry, "level": level, "representation": representation, "shifted": shifted,
                "error": f"TIMEOUT after {CASE_TIMEOUT_S}s (fixed budget, not raised after the fact)", "wall_s": time.time() - t0}
    out = p.stdout
    wall = time.time() - t0
    if "===RESULT_JSON===" not in out:
        return {"label": label, "geometry": geometry, "level": level, "representation": representation, "shifted": shifted,
                "error": f"subprocess produced no result JSON (rc={p.returncode}); tail: {(out + p.stderr)[-800:]}", "wall_s": wall}
    r = json.loads(out.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
    r["wall_s"] = wall
    return r


def run_trial(name, rel_err, max_it, levels):
    matrix = {name: []}
    print(f"=== {name} (subprocess-isolated; relative_error={rel_err}, maximum_iterations={max_it}, "
          f"CASE_TIMEOUT_S={CASE_TIMEOUT_S}, levels={levels}) ===")
    for geometry in ("1d", "2d"):
        for level in levels:
            for representation in ("R1", "R2"):
                for shifted in (False, True):
                    label = f"{name}_{geometry}_L{level}_{representation}_{'shift' if shifted else 'node'}"
                    r = run_one(geometry, level, representation, shifted, rel_err, max_it, label)
                    matrix[name].append(r)
                    if "error" in r:
                        print(f"[{label}] ERROR: {r['error'][:200]}")
                        continue
                    bp = [b["converged"] for b in r.get("bias_points", [])]
                    print(f"[{label}] nodes={r.get('n_nodes')} xj_used={r.get('xj_used_cm')} on_node={r.get('junction_on_a_node')} "
                          f"eq_ok={r.get('equilibrium_converged')} Vbi_analytic={r.get('V_bi_analytic')} "
                          f"contact_span_err={r.get('contact_boundary_consistency_error')} "
                          f"peak_E_solved={r.get('peak_field_solved_Vpercm')} peak_E_analytic={r.get('E_max_analytic_Vpercm')} "
                          f"bias_pts_ok={bp} wall_s={r['wall_s']:.1f}")
    path = os.path.join(DATA, f"{name}.json")
    json.dump(matrix, open(path, "w", encoding="utf-8"), indent=2, default=str)
    print("Wrote", path)
    return matrix


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "l0l3"):
        run_trial("rev2_L0L3", 1e-6, 100, [0, 1, 2, 3])
    if stage in ("all", "l4l5"):
        run_trial("rev2_L4L5", 1e-6, 100, [4, 5])
