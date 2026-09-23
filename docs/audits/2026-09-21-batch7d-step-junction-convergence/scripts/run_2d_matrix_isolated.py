"""Batch 7D -- dispatch every 2D case as its own subprocess (see run_2d_case_isolated.py's own docstring for why:
a contaminated in-process run showed devsim.solve() solving an earlier, still-registered failed device together
with the current one). Writes data/matrix_2d_isolated.json (Trial A tolerance) and data/matrix_2d_trialB_isolated.json
(Trial B tolerance -- this project's own pre-existing tcad/characterization/pn_junction_iv_sweep.py defaults).
usage: python run_2d_matrix_isolated.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
LEVELS = [0, 1, 2, 3]


def run_one(level, representation, shifted, rel_err, max_it, label):
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "run_2d_case_isolated.py"), str(level), representation, "1" if shifted else "0",
         str(rel_err), str(max_it), label],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    out = p.stdout
    if "===RESULT_JSON===" not in out:
        return {"label": label, "level": level, "representation": representation, "shifted": shifted,
                "error": f"subprocess produced no result JSON (rc={p.returncode}); tail: {(out + p.stderr)[-600:]}"}
    return json.loads(out.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])


def run_trial(name, rel_err, max_it):
    matrix = {name: []}
    print(f"=== {name} (isolated subprocess per case; relative_error={rel_err}, maximum_iterations={max_it}) ===")
    for level in LEVELS:
        for representation in ("R1", "R2"):
            for shifted in (False, True):
                label = f"{name}_L{level}_{representation}_{'shift' if shifted else 'node'}"
                r = run_one(level, representation, shifted, rel_err, max_it, label)
                matrix[name].append(r)
                print(f"[{label}] nodes={r.get('n_nodes')} min_h_near_j={r.get('min_spacing_near_junction_cm')} "
                      f"on_node={r.get('junction_on_a_node')} eq_ok={r.get('equilibrium_converged')} "
                      f"Vbi_analytic={r.get('V_bi_analytic')} Vbi_solved={r.get('V_bi_solved')} err={r.get('V_bi_error')} "
                      f"bias_pts_ok={[b['converged'] for b in r.get('bias_points', [])]}" + (f" ERROR={r['error']}" if "error" in r else ""))
    path = os.path.join(DATA, f"{name}.json")
    json.dump(matrix, open(path, "w", encoding="utf-8"), indent=2, default=str)
    print("Wrote", path)
    return matrix


if __name__ == "__main__":
    run_trial("matrix_2d_isolated_A", 1e-10, 30)          # Trial A: diode_1d.py's own tolerance (correct for 1D, tested here on 2D)
    run_trial("matrix_2d_isolated_B", 1e-6, 100)           # Trial B: pn_junction_iv_sweep.py's own pre-existing 2D tolerance
