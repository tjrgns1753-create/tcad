# Batch 7C Rev.2 -- explicit activation everywhere, exact reattach support, compensated transport fail-closed

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing committed). Batch 7C is kept.

1. No implicit ACTIVE: `apply_*_doping(..., chemical_state)` is a required keyword-only argument; the CLI rejects a doping config without
   `chemical_state`, and ACTIVE for gaussian_implant / implant_windows needs `profile_semantics: DIRECT_ANALYTIC_ACTIVE` as well.
2. Compensated transport: `wafer_state_v2.compensated_transport_problems` (exact positive rectangles per model, no sampling / threshold) is checked in
   the one place every DevSim doping write goes through, `doping_mapping.canonical_node_doping`: reason_code COMPENSATED_TRANSPORT_MODEL_MISSING,
   0 writes, 0 solves, no current; canonical donor/acceptor/net are preserved. Ideal step junction: donor x >= p, acceptor x < p (one polarity per x).
3. Exact reattach: `_desired_target` (shared by attach and reattach) -> `attachment.support_region_um == desired support`, same barrier carve.

* `patches/PROD_rev2.patch`, `TESTS_rev2_edits.patch`, `TESTS_fixture_states.patch` -- this revision only (snapshot-before vs now).
* `scripts/mutation_runner.py` + `raw/MUTATION_production.out.txt` -- 13 production mutations on scratch copies, all caught.
* `scripts/run_suite.py`, `raw/SUITE_now.txt`, `raw/SUITE_baseline_before_rev2.txt` -- 44 impacted integration tests, current tree vs pre-Rev.2 tree.
* `raw/FINAL_*` -- targeted runs.
