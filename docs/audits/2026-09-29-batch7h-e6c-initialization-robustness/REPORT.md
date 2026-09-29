# Batch 7H-E6C REPORT: initialization robustness of the local junction-refinement change (0 V Poisson, E6A L3 / L4 / L5)

**Verdict: `INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY`** (PLAN section 7): all six solves (L3/L4/L5 x P/Q) converged, all
import / doping / initialization contracts held, every consistency check passed, and for all four core metrics all three pre-registered
inequalities hold, so each metric is `INITIALIZATION_ROBUST_DECREASE_OBSERVED`. This is the PLAN's ceiling and it means only this: on these three meshes at
0 V, two independent initial potentials gave converged solutions whose difference (`observed_initialization_shift`) is far smaller than the observed
level-to-level change, and that change shrank from (L3,L4) to (L4,L5). **Reaching the same solution from two initial states is not evidence
that the solution is physically or numerically accurate.** Not claimed: a solver-error bound, 2D continuum convergence, a convergence order,
current / DD / I-V accuracy, production step-junction support, anything about a 1D reference or a fixed-outer-mesh floor. E6B's `S3/S4/S5`
stay invalid and were not reused. The gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` is unchanged.

## 1. Provenance
* E6B `ERRATUM.md` (wording only) `d848f2b9`; E6C PLAN committed alone in `9851fdf7b9a719ff8818922036c77ad0af468815`, `PLAN.md` LF sha256
  `3c91c361a6ae445b795890e919f1e1ea26011cc33091423335442b9bd581194e`, before any E6C code. Code `a1c85b2`, profile `e6c_initialization_robustness` and
  request `e6c-initialization-robustness-001` in `a7a1333a9bbb05245a72761914ca63645aa2affb` (executed commit).
* Remote run https://github.com/tjrgns1753-create/tcad/actions/runs/36529279171 (run 13), GitHub-hosted Windows, `status PASS`, `exit_code 0`, 79.7 s;
  `code_paths_identical_to_review_sha: true`; all 14 pinned inputs (E6A vtu / npz / result / PLAN, E6B PLAN, `judge_e6b.py`, the three E6B P arrays) equal. One run.
* Artifact `data/remote_run_36529279171/` (folder `remote-run-13/` flattened): 19 outputs and `run.log` re-hashed against `summary.json`: 0 mismatches, `omitted_outputs: []`,
  redactions none, no missing expected file, sensitive-string scan of all text artifacts 0 hits; committed blobs equal the artifact hashes.
* Solve calls: L3-P, L3-Q, L4-P, L4-Q, L5-P, L5-Q = 1 each = **6** (registered maximum 6), each run in its own process (6 different `process_id`s per level pair), devices left `[]`,
  precision flags unset in every process. Independent local recomputation (`scripts/recheck_e6c_local.py` -> `data/recheck_e6c_local.json`) with the same pure judge gives a
  judgement JSON identical to the remote one.

## 2. The six runs (raw, `run_L*_P/Q.json`)
| run | converged | iterations | final device rel. error | final abs. error | initial Potential min / max (V) | nodes where initial Q differs from P |
|---|---|---|---|---|---|---|
| L3-P | true | 10 | 3.932e-07 | 6.26e-17 | 0 / 0 | |
| L3-Q | true | 8 | 5.569e-07 | 8.87e-08 | -0.4768597199126637 / +0.4768597199126637 | 47232 of 48033 (max diff 0.4768597199126637 V) |
| L4-P | true | 10 | 2.412e-07 | 5.31e-17 | 0 / 0 | |
| L4-Q | true | 8 | 3.131e-07 | 4.53e-08 | same | 126466 of 128067 |
| L5-P | true | 10 | 3.889e-07 | 6.73e-17 | 0 / 0 | |
| L5-Q | true | 8 | 5.125e-07 | 2.54e-08 | same | 438532 of 441733 |

Iteration histories (device relative error per iteration) differ between P and Q and are stored in full in the JSONs together with the raw `solve` `info` result
(keys `converged`, `iterations`, `number_of_equations`; DEVSIM returned no problem-node field). **Initialization contract:** for every Q, `V_t = 0.025887193125`, `n_i = 1e10`,
`V_left = -0.4768597199126637`, `V_right = +0.4768597199126637` (contact formula at the doping on the contact nodes, read from the device); the array read back after
`set_node_values` is bit-equal to the intended affine array (`readback_bit_equal_intended: true`, `contract_ok: true`), and the saved Q initial array is bit-equal to an
independent recomputation; P's initial Potential is the DEVSIM default (all zeros). **Observed but unexplained:** the reported final device *absolute* error is ~1e-17 for every P
and 2.5e-08 to 8.9e-08 for every Q although the two converged potentials agree to ~1e-15 (section 4); this batch does not determine why.

## 3. Import identity and doping (every run, before its solve)
| | L3 | L4 | L5 |
|---|---|---|---|
| nodes / elements | 48033 / 95400 | 128067 / 255400 | 441733 / 882600 |
| coordinates = `(P32*1e-4).astype(float)` node by node; vertex-set multiset = E6A triangles; NodeVolume bit-equal E6A | true; true; true (P and Q) | true; true; true | true; true; true |
| contacts `Si_xmin` / `Si_xmax` by coordinate | 101 / 101 | 101 / 101 | 101 / 101 |
| edge n0 / n1 / EdgeCouple / EdgeLength equal E6A | true (P and Q) | true | true |
| x = 0 nodes; Donors / Acceptors / NetDoping | 801; 1e18 / 1e18 / 0 | 1601; same | 3201; same |
| x = 0 sum NodeVolume (cm^2); sum Donors x NV; sum NetDoping x NV | 3.125e-10; 3.125e8; 0 | 1.5625e-10; 1.5625e8; 0 | 7.8125e-11; 7.8125e7; 0 |
| total Donors x NV (= total Acceptors x NV) vs continuum 2.49999966e11 (cm^-1) | 2.50156e11 | 2.50078e11 | 2.50039e11 |
The P and Q doping records are identical. The J0 doping was constructed explicitly in the audit device; it is not evidence that production `apply_doping()` supports a 2D step junction.

## 4. Metrics (core, bit-identical common nodes, L3 NodeVolume weights)
`A3, A4, A5` = `observed_initialization_shift` = `M(L<n>-P, L<n>-Q)`; left/right sides of the three inequalities as computed by the judge.

| metric | D34 | D45 | A3 | A4 | A5 |
|---|---|---|---|---|---|
| psiLinf (V) | 1.029524e-03 | 2.579170e-04 | 5.1625e-15 | 1.3323e-15 | 4.4409e-16 |
| psiL2 (V) | 3.701352e-04 | 9.038317e-05 | 1.7807e-15 | 4.7043e-16 | 1.5403e-16 |
| ExLinf (V/cm) | 1698.4129 | 387.29503 | 4.8822e-09 | 1.1569e-09 | 3.7835e-10 |
| ExRMS (V/cm) | 520.61335 | 123.76019 | 1.8555e-09 | 4.7477e-10 | 1.7359e-10 |

| metric | (1) D34 > A3+A4: lhs / rhs | (2) D45 > A4+A5: lhs / rhs | (3) D34-D45 > A3+2A4+A5: lhs / rhs | state |
|---|---|---|---|---|
| psiLinf | 1.0295e-03 / 6.495e-15 true | 2.5792e-04 / 1.776e-15 true | 7.7161e-04 / 8.271e-15 true | ROBUST_DECREASE_OBSERVED |
| psiL2 | 3.7014e-04 / 2.251e-15 true | 9.0383e-05 / 6.245e-16 true | 2.7975e-04 / 2.876e-15 true | ROBUST_DECREASE_OBSERVED |
| ExLinf | 1698.41 / 6.039e-09 true | 387.295 / 1.535e-09 true | 1311.12 / 7.574e-09 true | ROBUST_DECREASE_OBSERVED |
| ExRMS | 520.613 / 2.330e-09 true | 123.760 / 6.484e-10 true | 396.853 / 2.979e-09 true | ROBUST_DECREASE_OBSERVED |

**What the numbers mean and do not mean.** The P and Q potentials at the same level agree to at most 5.2e-15 V (max over all nodes 5.2e-15 / 1.4e-15 / 4.4e-16 at L3 / L4 / L5) and none of the
seven saved model arrays is bit-equal between P and Q (so A is a measured difference, not an artifact of identical data). Because A sits at the rounding level, inequalities (1) and (2) hold with
margins of 11 to 13 orders of magnitude and the pre-registered test practically reduces to "D34 > D45 > 0"; D34 / D45 is 4.0 (psiLinf), 4.1 (psiL2), 4.4 (ExLinf), 4.2 (ExRMS) with three levels only, so **no
convergence order is inferred**. The transition and outer regions were computed and stored unclassified (E6B saw D ~1e-11 / 1e-16 there, the same here since P is identical). The statement "two initial
conditions reach the same solution" concerns the solver's basin of attraction (for this strictly monotone Boltzmann-Poisson problem uniqueness is expected, PLAN E6B section 8 marks the
1D-2D side of that reasoning `CONDITIONAL`); it says nothing about the discretization error, the solver's termination error, or physical accuracy.

## 5. Reproducibility diagnostic (separate, not in the verdict)
The new P final `Potential` versus E6B's `level_L<L>_state_P.npz` (sha256 pinned in the PLAN): **bit-equal on all nodes at L3, L4 and L5** (max abs difference 0.0, all four core metrics 0.0). The
P solve is reproducible bit for bit across independent processes and runs on the runner; consequently D34 / D45 are numerically the same as E6B's raw values.

## 6. Diagnostics (none is a physics gate)
* y-uniformity (limit 1e-6 V by convention): core 7.8e-12 / 2.1e-15 / 7.2e-16, transition 8.0e-14 / 1.7e-14 / 1.1e-14, outer 5.6e-17 at L3 / L4 / L5, identical for P and Q; all values finite; `consistency_ok` true for all six.
* Contact readback (final state): `Si_xmin` -0.4768597199126636 V, `Si_xmax` +0.4768597199126636 V in all six runs (the boundary formula's own value; reported only).
* Gauss diagnostic (E6B Rev.3 definition, non-contact eligible nodes; `max |R_i|/s_i`): eligible 12015 / 46425 / 176047, on x = 0: 801 / 1601 / 3201, top row 15 / 27 / 51, bottom row 15 / 27 / 51, no `DIAG_*` state.
  correct assembly: P 8.05e-14 / 9.56e-14 / 3.36e-13, Q 3.17e-13 / 6.30e-13 / 1.10e-12; EdgeCouple omitted 2.35e+06 / 3.97e+06 / 6.58e+06 (P and Q); EdgeCouple twice 0.381 / 0.267 / 0.161;
  charge sign flipped 0.763 / 0.534 / 0.322; contact block (separate) correct 1.0. Diagnostic only; E6B's numbers were not reused as approval.

## 7. Limits and open items
Established (observation, one mesh family, 0 V, default solver settings): both initial conditions converge in 8-10 iterations to potentials equal to ~1e-15, and the level-to-level change is larger and decreasing.
**Not established:** any bound on the solver's termination error (A is not one: both runs stop under the same rule, and E6B showed the tighter control cannot be met), any relation to a
1D reference or a fixed-outer-mesh floor (L|x|>0.2 um is identical at all levels), 2D continuum convergence, that the shrinking continues, current accuracy, DD, bias, production support. L3 does not resolve the
Debye length a priori (`L3_BELOW_DEBYE_SCALE`, L_D/h_3 = 0.638), so D34 may be dominated by under-resolution. Open questions for a later, separately pre-registered batch: the origin of the different reported
absolute errors of P and Q; how to bound the terminal error of the primary solve; the floor question.

## 8. Change record
Files: `ERRATUM.md` (E6B dir); `PLAN.md`, `PLAN.sha256`; `scripts/judge_e6c.py`, `stage_e6c.py`, `run_e6c.py`, `synthetic_e6c_test.py`, `recheck_e6c_local.py`;
`data/synthetic_e6c_results_pre_run.json` (23 rows as pre-registered; it found one real sign bug in `contact_potentials` for `V_left` and one ineffective test perturbation before any remote run — the
code and the test perturbation were fixed, no expected value was relaxed), `data/recheck_e6c_local.json`, `data/remote_run_36529279171/`, `data/batch_e6c_code.patch` (unabridged `git diff -U1 9851fdf7`
of `scripts/` and `remote/`; sha256 in the final chat report); `remote/profiles.py` (new profile only) and `remote/request.json`. `tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/`, DEVSIM / ViennaPS and all
E4 / E5 / E6A / E6B evidence are unchanged (`git diff` against review SHA `023bcb90...` empty). The E6A `.vtu` CRLF hygiene item (`git diff --check` rc 2 on that evidence commit) is unchanged and is not a geometry or physics failure.
