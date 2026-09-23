# Batch 7D -- Step Junction boundary restoration + public-API-only mesh-convergence audit

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing
committed). Batch 7C Rev.2's approved items (implicit-ACTIVE removal, CLI activation contract, compensated-transport fail-closed,
exact-support reattach, CHEMICAL/UNKNOWN blocking) are kept untouched. Only the Step Junction boundary convention is
reverted to DEVSIM's own official one, and a public-API-only capability audit is added.

* `patches/PROD_restore_*.patch` -- the two production files restored (5 lines net production diff).
* `patches/TEST_restore_*.patch` -- the three test files updated for the official convention.
* `scripts/probe_step_junction_convergence.py`, `run_2d_case_isolated.py`, `run_2d_matrix_isolated.py`,
  `probe_2d_trialB.py` -- public-API-only probes (never call anything outside the allowlist; `scan_public_api_only.py`
  verifies this statically).
* `scripts/check_matrix_completeness.py`, `mutation_runner_7d.py`, `mutation_completeness.py` -- verification harness.
* `data/*.json`, `data/*.csv` -- raw per-node and per-bias-point measurements.

See the full 20-section report in chat for the complete evidence, judgment and remaining limits.
