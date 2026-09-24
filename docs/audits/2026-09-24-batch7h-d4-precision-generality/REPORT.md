# Batch 7H-D4 REPORT: fail-closed D3 analyzer and P12 vs P4 on three more non-obtuse default fixtures

Remote execution only (GitHub-hosted Windows runner). Read together with `ERRATUM.md` (interpretation corrections from
Codex's interim review, written before the results were read). PLAN, analyzer, thresholds and raw data are unchanged.

## 1. Carried in (not re-judged)
Approved: `P12_CURRENT_EQUIVALENT_TO_P4_ON_M2_D0_H0.005` (contact + five cut currents only);
`P4_MIRROR_PASSES_ON_1D_AND_M1_H0.005_WITH_PREREGISTERED_BIAS`; P0 contact-current defect reproduced.
Not approved and still not approved after D4: 2D mesh convergence, production precision flag change, release of
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, PN physical validity.

## 2. D3 false-PASS paths (synthetic copies only, no physics)
| case | mutation | old `analyze_d3.py` | new `analyze_d4.py --mode d3` |
|---|---|---|---|
| baseline | none | E1 PASS / E2 MIRROR_PASS | EVIDENCE_INTEGRITY_PASS, E1 PASS / E2 MIRROR_PASS (reproduced) |
| A | `identical_to_stored` = False | E1 PASS / E2 MIRROR_PASS (identity_all_ok False ignored) | EVIDENCE_INTEGRITY_FAIL, both BLOCKED |
| B | PLAN.md copy edited | E1 PASS / E2 MIRROR_PASS (plan_hash_matches False ignored) | EVIDENCE_INTEGRITY_FAIL, both BLOCKED |
| C | `E2_M1_h0.005_P4_mirror.json` removed | E2 MIRROR_PASS from the 1D pair alone | EVIDENCE_INTEGRITY_FAIL, both BLOCKED |
| D | `identical_to_stored` deleted | defaulted to True, PASS | EVIDENCE_INTEGRITY_FAIL, both BLOCKED |
Code sites (read only): `analyze_d3.py:192` (default True), `:215-220` (final verdicts independent of identity / PLAN, E2 graded on
existing pairs only). Evidence: `data/mutation_results_pre_plan.json`, `data/mutation_results_after_pin.json`; 9 synthetic d4-mode
cases `data/synthetic_d4_results_pre_run.json` (all as expected).

## 3. PLAN and execution
* PLAN commit `18d678de81ebdff84c162665d9bb38340c7c48cb` (PLAN only), sha256 (LF) `3a53e29b24a7d29aee198a57f8e06f604d243d73babf1b1926ec11fc6fb32912`,
  fixed 2026-09-24T12:32:59Z; file = recorded = pinned on the runner.
* Run commit `a5a3489890c70cc3d2c80a95969e785f72a97137`; Actions run https://github.com/tjrgns1753-create/tcad/actions/runs/36000025313
  (runner PASS, 1740 s). Windows Server 2025 (10.0.26100), Python 3.11.9, ViennaPS 4.6.2, ViennaLS 5.8.5, DevSim 2.11.0
  (extended_precision true, mkl_pardiso, mkl_rt.3.dll), mkl 2026.1.0. Production/test paths identical to review SHA (runner-recorded True).
* Artifact `remote-run-4` stored in `data/remote_run_36000025313/` with per-file sha256 in `data/artifact_remote_run_36000025313.sha256`.
  Sensitive-pattern scan of all text files: 0.

## 4. Fixtures, flags, bias
* `fixtures_d2.json` regenerated on the runner by the unchanged D2 script in 138 s: sha256 `e2c018a6...a6f2` = D2-recorded value, gate passed
  before any solve. Every run's fixture file hash, coordinate / connectivity hashes and node / triangle counts equal PLAN section 2.
* P12 and P4 of each fixture: identical DEVSIM x, y and element-list hashes (node order proven).
* Flags unset at start, set to target (P12: model, equation True, solver False; P4: all True), unchanged at end; bias readback exact,
  applied voltage from contact potentials within 1e-9 V; all 12 solves of all 6 runs accepted.
* Wall time: M1 h=0.005: P12 24.6 s, P4 26.3 s; M1 h=0.00125: P12 388 s, P4 422 s; M2 h=0.00125: P12 377 s, P4 362 s.

## 5. Registered verdicts (verbatim from `analysis_d4_mode_d4.json`)
```
EVIDENCE_INTEGRITY: EVIDENCE_INTEGRITY_PASS   integrity_errors: []
P12_generality:     P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES
node_state:         NODE_STATE_MATCHES_ON_TESTED_FIXTURES
per_fixture: M1_D0_h0.005 {current: PASS, node_state: MATCHES}; M1_D0_h0.00125 {current: PASS, node_state: MATCHES};
             M2_D0_h0.00125 {current: PASS, node_state: MATCHES}
```
Current comparisons: 0 fail, 0 undecidable per fixture; max relative P12-P4 difference 4.3e-16 / 4.2e-16 / 6.4e-16; P12 and P4 both
SELF_OK. Worst self-consistency residuals over the biased points (L/R mismatch, 5-cut spread, contacts vs cut(0), C3 species / total):
<= 8.5e-16 (P12) and <= 2.7e-16 (P4) on every fixture.

## 6. Node state (registered comparison + descriptive statistics, ERRATUM section 3)
| fixture | point | max abs dpsi (V) and location (um) | max in abs(x) <= 0.10 um | max abs ln n / ln p | final rel update P12 / P4 |
|---|---|---|---|---|---|
| M1 h=0.005 | 0 V | 5.6e-17 at (0.0325, 0) | 5.6e-17 | 7.8e-16 / 6.7e-16 | 4.6e-15 / 8.3e-21 |
| | +0.05 | 5.6e-17 at (-0.06, 0.005) | 5.6e-17 | 6.7e-16 / 6.7e-16 | 5.9e-15 / 3.2e-23 |
| | +0.10 | 5.6e-17 at (-0.0525, 0.06) | 5.6e-17 | 5.6e-16 / 4.4e-16 | 2.0e-15 / 5.4e-24 |
| | -0.10 | 5.6e-17 at (0.0525, 0) | 5.6e-17 | 6.7e-16 / 6.7e-16 | 9.8e-11 / 9.8e-11 |
| M1 h=0.00125 | 0 V | 5.6e-17 at (0.0325, 0.00125) | 5.6e-17 | 8.9e-16 / 8.9e-16 | 3.1e-15 / 3.3e-19 |
| | +0.05 | 5.6e-17 at (0.028125, 0) | 5.6e-17 | 7.8e-16 / 8.9e-16 | 1.3e-14 / 6.4e-23 |
| | +0.10 | 5.6e-17 at (0.026875, 0.0475) | 5.6e-17 | 8.9e-16 / 1.0e-15 | 5.2e-14 / 4.6e-22 |
| | -0.10 | 1.1e-16 at (-0.091875, 0) | 1.1e-16 | 2.2e-16 / 2.2e-16 | 2.4e-14 / 2.1e-24 |
| M2 h=0.00125 | 0 V | 5.6e-17 at (0.014375, 0) | 5.6e-17 | 2.1e-15 / 2.2e-15 | 8.9e-15 / 3.8e-32 |
| | +0.05 | 5.6e-17 at (0.025625, 0) | 5.6e-17 | 1.3e-15 / 1.3e-15 | 2.6e-14 / 1.7e-22 |
| | +0.10 | 5.6e-17 at (0.029375, 0) | 5.6e-17 | 1.2e-15 / 1.3e-15 | 1.4e-14 / 1.6e-22 |
| | -0.10 | 5.6e-17 at (0.034375, 0) | 5.6e-17 | 1.1e-15 / 1.1e-15 | 4.7e-14 / 4.3e-24 |
B0rev equals B0 for every fixture. Registered potential threshold 8.3e-11 V (1.0e-10 V at -0.10 V); carriers 2e-10. 90-99 % of nodes
have dpsi exactly 0. The maxima (5.6e-17, 1.1e-16 V) equal one or two double-precision ulps of psi (~0.25-0.5 V); the junction
band shows the same maxima. Observation: the reported final relative update of P4 is 1e-19 to 1e-32 where P12 reports 1e-14
(both far below 1e-10); the one exception, M1 h=0.005 at -0.10 V, is 9.8e-11 in both. What causes the difference in the reported
update is not investigated.

## 7. Cross-checks
Remote P4 currents equal the earlier local 7H-D2 P4 runs of the same fixtures bit for bit (max relative difference 0 for
M1 h=0.005, M1 h=0.00125, M2 h=0.00125).

## 8. Meaning and limits (see ERRATUM)
Established on the three tested non-obtuse default fixtures, the recorded biases, DEVSIM 2.11.0 and this runner: P12 and P4 give the
same contact / cut / species currents and the same node Potential, Electrons, Holes to double-precision rounding. The node verdict
uses a pre-registered comparison threshold, not an error bound. Not established: that either run is close to the true discrete or
physical solution (both may share the same discretisation error), M3 signed override, other meshes, doping, temperature, lifetime,
process order, absolute PN current, mesh convergence. No production flag, gate or code change.

## 9. Integrity
`tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/` and the 7H-D/D1/D2 audits identical to review SHA `023bcb90...`; 7H-D3
tracked files identical to `e16e67a`; `claude/waferstate-v2` and main unchanged.
