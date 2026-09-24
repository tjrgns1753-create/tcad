# Batch 7H-D4 PLAN (fixed BEFORE any D4 solve; never edited after a result is seen)

Execution location: **GitHub-hosted Windows runner only** (`claude/remote-runner`, profile `d4_precision_generality`).
Locally only file writing, static checks and synthetic-input analyzer tests.

## 0. Scope
Approved before D4 (not re-judged): `P12_CURRENT_EQUIVALENT_TO_P4_ON_M2_D0_H0.005` (contact + five cut currents only),
`P4_MIRROR_PASSES_ON_1D_AND_M1_H0.005_WITH_PREREGISTERED_BIAS`, P0 contact-current defect reproduced.
D4 asks: does P12 match P4 on three more non-obtuse default fixtures, in currents AND node state?
The strongest allowed conclusion is `P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES`. It does not cover
other meshes, M3 signed override, other doping / temperature / lifetime, any process order, absolute PN current accuracy,
mesh convergence or production defaults. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and production flags stay as they are.
Current conservation and mirror symmetry test internal numerical consistency, not physical accuracy.

## 1. Evidence integrity gate (above every physics verdict)
`analyze_d4.py` (fail-closed; D3 analyzer false-PASS paths A-D reproduced and blocked in
`data/mutation_results_pre_plan.json`, synthetic copies only). `EVIDENCE_INTEGRITY_PASS` requires ALL of:
* exactly the six expected run files (section 2), no extra, none missing; each run's `cfg` equals the expected
  id / kind / fam / variant / h / P / mirror;
* this PLAN's LF-normalized sha256 equals `PLAN.sha256` and the value pinned in the analyzer;
* fixture identity per run: source file sha256, node / triangle counts, coordinate and connectivity sha256 equal to
  section 2, `identical_to_stored` present and True;
* flags: unset at process start, set equal to the target, unchanged at the end; no device left registered; DEVSIM 2.11.0;
* all 12 solve steps present, each `ok`, `converged`, final relative update < 1e-10;
* every recorded point has C0, C1, C2 (total, n, p per cut), C3, bias readback (p within 1e-12 V of the set value, n = 0),
  applied voltage from contact potentials within 1e-9 V, positive finite carriers; geometry / doping-side check passes;
* node-state archive present and its sha256 equal to the one recorded in the run JSON.
A missing field is an integrity error, never True or 0. If the gate fails, verdicts 2 and 3 cannot be PASS
(reported as `P12_GENERALITY_INCONCLUSIVE` / `NODE_STATE_INCONCLUSIVE`, per fixture `BLOCKED_BY_EVIDENCE_INTEGRITY`).

## 2. Runs (six, each its own Python subprocess)
| fixture | source file (sha256) | nodes / triangles | coordinates sha256 | connectivity sha256 |
|---|---|---|---|---|
| M1/D0 h = 0.005 um | fixtures_d1.json `80d65d51...f9f7f5` (committed) | 4242 / 8040 | `9e4b5bce717f6f37bbeb54ea93da060284a7434d759d157cf536549140a32d85` | `9de5267bb51d699955c58231aaf190aab2515445456d75a8d3d59db7a943b7fc` |
| M1/D0 h = 0.00125 um | fixtures_d2.json `e2c018a62292c4f4f9e215a8aa525148c15a618bc50792c141318a6a81f3a6f2` | 64962 / 128160 | `433cc08c391f13af584f1161073531aca76286c808ed3414bf550dff320c5a9d` | `8e360bd3164670dbcfc523642496faad509aade1920ec1a66b932318eabc0857` |
| M2/D0 h = 0.00125 um | same fixtures_d2.json | 64962 / 128160 | `9540b881034269137b94ba6ff9f2f267efb4093c2cc524f5374fb0c8d08e52fc` | `cdb40feea37c6b96cd35e1d6ffefaa3fac468f4073f3e8a70798bd7fad1988a8` |
`fixtures_d2.json` is not in Git; the runner regenerates it with the unchanged 7H-D2 `build_fixtures_d2.py` and **stops before any
solve** unless its sha256 equals the D2-recorded `e2c018a6...`. M2/D0 h = 0.005 um is D3's approved result and is not rerun.
Variants: P12 = `extended_model` True, `extended_equation` True, `extended_solver` False; P4 = all True. Geometry, doping,
contacts, material parameters, bias and stopping rule identical to 7H-D2/D3; only the flags differ.

## 3. Bias, stopping rule, measurements
Bias on the p contact (`left_bias`), as D2/D3: 0 V DD, then +0.025, +0.05, +0.075, +0.10 V; rebuilt device, 0 V, then
-0.025 ... -0.10 V. Recorded points: B0, B0rev (0 V), -0.10, +0.05, +0.10 V. Stopping rule (fixed_d2.json): Poisson abs 1e-10 /
rel 1e-10, drift-diffusion abs 1e30 / rel 1e-10, 50 iterations; accepted iff converged and final relative update < 1e-10.
Recorded per point: solve info (iterations, relative / absolute update, wall time), C0 contact currents per species,
C1, C2 five cuts (x = -0.25, -0.10, 0, +0.10, +0.25 um; per species and total), C3 continuity sources and residuals, bias
readback, carrier positivity, and node arrays Potential, Electrons, Holes. Node arrays go to one compressed `.npz`
per run (float64, not duplicated in JSON) whose sha256, plus sha256 of the DEVSIM node x, y arrays and element list, are
in the run JSON. Units: A/cm per unit depth (2D), V, cm^-3.

## 4. Current comparison (verdict per fixture)
Unchanged D3 rules and numbers: tau = 1e-5; zero-bias rule |I(0 V)| <= 1e-6 |I(-0.10 V)|; denominator rule: a relative
comparison is made only if |q_P4| >= 1e-6 x max_cut |I_cut,P4| at that point, otherwise UNDECIDABLE (never PASS by a floor).
Compared at -0.10, +0.05, +0.10 V: C0 left, C0 right, five cut totals (D3 `equality`), and additionally the electron and hole
current at each of the five cuts, all as |P12 - P4| <= tau |P4|. Self-consistency (D3 `self_ok`: L/R mismatch, 5-cut spread,
contacts vs cut(0), C3 species and total, C1 = C0, zero-bias rule; all <= tau) is required of P12 AND of the P4 reference.
PASS iff no comparison fails, none is undecidable, P12 and P4 both SELF_OK. FAIL iff a comparison exceeds tau or P12 is not
SELF_OK. INCONCLUSIVE iff not FAIL but an undecidable comparison exists or P4 is not SELF_OK. NOT_COMPLETED if a run failed.

## 5. Node-state comparison (verdict per fixture) - new, derived from the stopping rule
Only if the two runs' DEVSIM x, y arrays and element lists are identical (sha256 and array equality); otherwise INCONCLUSIVE.
Derivation: both runs solve the same discrete equations (P12 and P4 differ only in the precision of the Newton linear
solve), each accepted when its final relative update is < 1e-10. DEVSIM reports the relative error together with the node
where it is largest (manual section 9.7.1, `relative_error_node`), i.e. a maximum over nodes of a per-node relative update.
Newton converges quadratically, so each accepted state lies within one final update of the discrete root; two runs therefore
differ by at most 2 x 1e-10 relative per node. Registered at every recorded point (B0, B0rev, -0.10, +0.05, +0.10 V, reported
separately):
* carriers: both positive and finite first; max |ln(n_P12 / n_P4)| <= 2e-10 and max |ln(p_P12 / p_P4)| <= 2e-10;
* potential: max |psi_P12 - psi_P4| <= 2e-10 x max |psi_P4| (V). Scaled by max |psi| because the per-node relative
  update of psi is undefined at psi ~ 0 near the junction (the exact floor DEVSIM uses is not documented).
MATCHES iff every point passes; DIFFERS iff any bound is exceeded; INCONCLUSIVE if positivity or node identity fails.
The achieved final relative updates of both runs are reported next to each comparison.

## 6. Final verdicts (each separate)
1. `EVIDENCE_INTEGRITY_PASS` / `EVIDENCE_INTEGRITY_FAIL` (section 1).
2. `P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES` iff integrity passes and all three fixtures' current
   verdicts are PASS; `P12_DIFFERS_FROM_P4_ON_TESTED_FIXTURE` iff any is FAIL (fixture named); else `P12_GENERALITY_INCONCLUSIVE`.
3. `NODE_STATE_MATCHES_ON_TESTED_FIXTURES` iff integrity passes and all three MATCH; `NODE_STATE_DIFFERS` iff any DIFFERS;
   else `NODE_STATE_INCONCLUSIVE`.
A single successful fixture is never reported as overall PASS; per-fixture results are always listed.

## 7. Remote execution, artifacts, stop conditions
Driver runs: fixture regeneration + hash check, then six runs (per-run timeout 3600 s; 7H-D2 local wall time at h = 0.00125 um
was 314-509 s per run), then `analyze_d4.py --mode d4`. Runner timeout 350 min. Artifact: run JSONs, six `.npz`, analysis
JSON/markdown, log, summary with hashes. Estimated size: about 30 MB, under the 200 MB budget; a file over budget is omitted
and listed with its sha256 and the regeneration note (rerun the profile). Timeout, non-convergence and missing files are
recorded as NOT_COMPLETED / integrity failures, never PASS.
Stop (report, change nothing): fixture regeneration hash mismatch (no solve is started); production/test tree differing from
review SHA `023bcb90f8b8a0972d6df84f097ca6387f0ab82a`; flag readback mismatch; node ordering or contact/bias identity unproven;
non-convergence; PLAN hash mismatch; missing artifact; any need to change production or the gate.
