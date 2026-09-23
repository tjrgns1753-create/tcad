"""Batch 7D -- 2D Trial B: re-run ONLY the 2D matrix, with the project's own PRE-EXISTING solver tolerance
(tcad/characterization/pn_junction_iv_sweep.py's defaults: relative_error=1e-6, maximum_iterations=100) instead of
diode_1d.py's own tight 1D-example tolerance (1e-10/30) that probe_step_junction_convergence.py's Trial A used for
BOTH geometries. That file's docstring already documents -- independently of this audit -- that 1e-10/30 fails to
converge on a real unstructured 2D ViennaPS-derived mesh; this is not a tolerance chosen after seeing Trial A's
results. 1D is untouched (Trial A's 1D result already used the correct official reference tolerance and converged
perfectly at every level). Same public-API-only construction as probe_step_junction_convergence.py; imports it
rather than duplicating it.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import probe_step_junction_convergence as base  # noqa: E402

DATA = base.DATA


def main():
    matrix = {"2d_trialB": []}
    print("=== 2D Trial B (project's own pre-existing pn_junction_iv_sweep.py tolerance: rel_err=1e-6, max_iter=100) ===")
    with tempfile.TemporaryDirectory() as tmp:
        process_result = base.build_2d_mesh_once(tmp)
        for level in base.LEVELS:
            for representation in ("R1", "R2"):
                for shifted in (False, True):
                    label = f"2dB_L{level}_{representation}_{'shift' if shifted else 'node'}"
                    try:
                        r = base.run_case_2d(process_result, level, representation, shifted, label,
                                             relative_error=1e-6, maximum_iterations=100)
                    except Exception as exc:  # noqa: BLE001
                        r = {"label": label, "level": level, "representation": representation, "shifted": shifted, "error": repr(exc)}
                    matrix["2d_trialB"].append(r)
                    print(f"[{label}] nodes={r.get('n_nodes')} min_h_near_j={r.get('min_spacing_near_junction_cm')} "
                          f"on_node={r.get('junction_on_a_node')} eq_ok={r.get('equilibrium_converged')} "
                          f"Vbi_analytic={r.get('V_bi_analytic')} Vbi_solved={r.get('V_bi_solved')} err={r.get('V_bi_error')} "
                          f"bias_pts_ok={[b['converged'] for b in r.get('bias_points', [])]}")
    with open(os.path.join(DATA, "matrix_2d_trialB.json"), "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2, default=str)
    print("\nWrote", os.path.join(DATA, "matrix_2d_trialB.json"))


if __name__ == "__main__":
    main()
