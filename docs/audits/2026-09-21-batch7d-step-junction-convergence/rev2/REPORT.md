# Batch 7D Rev.2 -- correct the convergence audit (no production physics changes)

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing
committed). This subfolder corrects three measurement/reporting defects Codex found in the PARENT `../` (Batch 7D
Rev.1) audit's own probe scripts -- P0-1 (2D shift computation collapsed to 0.0 on the symmetric mesh), P0-2
(`V_bi_solved` was circular against DEVSIM's own contact BC), P1 (`actual_iterations` was really `maximum_iterations`).
No file under `../` (Rev.1) was modified -- verified byte-identical via `../../rev2/scripts` cross-check against a
pre-turn SHA-256 snapshot (see the chat report, section 20).

* `scripts/probe_case.py` -- the corrected single-case probe (real node-based shift, independent E-field/depletion
  metrics, honest iteration reporting).
* `scripts/run_matrix.py` -- subprocess-isolated dispatcher, fixed `CASE_TIMEOUT_S=900`, L0-L5.
* `scripts/check_matrix_completeness.py`, `scripts/scan_public_api_only.py`, `scripts/mutation_runner_rev2.py`,
  `scripts/analyze_convergence.py` -- verification harness.
* `data/rev2_L0L3.json`, `data/rev2_L4L5.json` -- the corrected L0-L5 matrix (32 cases: 2 geometries x 6 levels x 2
  representations x 2 shift states), plus per-node equilibrium CSVs.
* `data/convergence_analysis.txt` -- the full per-bias-point log-current / R1-R2 / aligned-shifted / conservation /
  E-field / depletion convergence tables.

See the full 21-section report in chat for the complete evidence, judgment and remaining limits.
