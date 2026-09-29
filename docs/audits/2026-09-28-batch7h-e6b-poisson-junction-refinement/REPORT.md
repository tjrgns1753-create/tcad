# Batch 7H-E6B REPORT: 0 V Poisson junction-refinement trend on the E6A L3 / L4 / L5 family

**Verdict: `SOLVER_CONTROL_INVALID`** (PLAN Rev.3 section 9). All three 2D primary solves and both 1D reference primary solves
converged, but **every one of the five control solves (L3-C, L4-C, L5-C, R6-C, R7-C) reported `converged: false`**, so no `S`
value may be used, no metric is classified, and no trend statement is made. The 1D reference state is
`REFERENCE_1D_UNUSABLE`. Nothing was retried, no tolerance or criterion was changed after the result. The maximum verdict of
this batch, `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY`, was **not reached**. Not claimed, whatever the numbers: 2D continuum
convergence, current accuracy, DD, biased I-V, production step-junction support. The gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` is unchanged.

## 1. Provenance
* PLAN Rev.3: `PLAN.md` LF sha256 `6a8d674e3548de32007f90f8a1368f9e2b31835f13d5b54eecc52da041c72e51`, committed alone in
  `f929a14c7d1ef3fc32093ceb4fe0881dcae9b588` before any E6B code; Rev.1 `50555b7d...`, Rev.2 `59abed68...` kept in
  `PLAN_REVISION.md`.
* Code `92ce0f9`, profile `e6b_poisson_junction_refinement` and request `e6b-poisson-junction-refinement-001` in `b78feee1`.
* Remote run https://github.com/tjrgns1753-create/tcad/actions/runs/36527372624 (run 12), executed commit
  `b78feee188f55c3cd6ae312f9ce3a28122e91ff9`, GitHub-hosted Windows, `status PASS`, `exit_code 0`, 94.5 s, DEVSIM 2.11.0;
  `code_paths_identical_to_review_sha: true`; input identity (all E6A files and both PLANs) true. Exactly one run.
* Artifact `data/remote_run_36527372624/` (top folder `remote-run-12/` flattened): 17 outputs and `run.log` re-hashed against
  `summary.json`: 0 mismatches, `omitted_outputs: []`, redactions none, no missing expected file, sensitive-string scan of all
  text artifacts: 0 hits.
* Solve calls: L3 2, L4 2, L5 2, R6 2, R7 2 = **10** (registered maximum 10), each device in its own process, devices left `[]`
  everywhere, precision flags unset (S0) in every process.
* Independent local recomputation (`scripts/recheck_e6b_local.py` -> `data/recheck_e6b_local.json`): the same pure judge run
  on the downloaded arrays gives a `judgement` JSON identical to the remote one.

## 2. Solver records (raw, `level_L*.json` / `ref_R*.json`)

| call | converged | iterations | final device rel. error | final abs. error | peak private bytes of the process |
|---|---|---|---|---|---|
| L3-P | true | 10 | 3.932e-07 | 6.26e-17 | 3.77e8 |
| L3-C | **false** | 10 | 4.493e-07 | 6.26e-17 | |
| L4-P | true | 10 | 2.412e-07 | 5.31e-17 | 9.28e8 |
| L4-C | **false** | 10 | 1.953e-07 | 5.31e-17 | |
| L5-P | true | 10 | 3.889e-07 | 6.73e-17 | 3.11e9 |
| L5-C | **false** | 10 | 3.395e-07 | 6.73e-17 | |
| R6-P | true | 10 | 9.537e-07 | 4.55e-07 | 8.58e7 |
| R6-C | **false** | 10 | 1.158e-08 | 5.23e-17 | |
| R7-P | true | 11 | 6.001e-09 | 6.26e-10 | 1.23e8 |
| R7-C | **false** | 10 | 5.421e-10 | 5.23e-17 | |

Control settings (PLAN 6.4): `absolute_error = 1e-12`, `relative_error = 1e-12`, `maximum_iterations = 10`. In every control the
absolute error was already about 5e-17 (below 1e-12), while the device relative error did not decrease but oscillated for all
10 iterations (2D: 1.9e-07 to 4.9e-07; 1D: 4e-09 to 1.5e-08 at R6, 5e-10 to 5.8e-09 at R7; full histories in the JSONs).
**Observed fact: in every 2D level the C-state arrays (Potential, IntrinsicElectrons, IntrinsicHoles, IntrinsicCharge,
PotentialIntrinsicCharge, ElectricField, PotentialEdgeFlux) are bit-identical to the P-state arrays.** The Rev.3 rule therefore
had exactly its intended effect: the raw P-to-C shift is exactly 0.0 for all four metrics at L3, L4 and L5, which would
make every discriminant inequality trivially true if `S` were accepted; because the controls did not converge, `S` is invalid
and is not used. Why the relative error stalls at ~1e-7 (2D) is **not determined** by this batch. It is consistent with the
oscillating relative error the 7H-D1 J0 stall recorded (7H-E5 PLAN section 1, 5.8e-9 / 6.2e-9 at 1e-10 tolerances), but that is a
resemblance, not a finding. The control criterion of PLAN 6.4 (`relative_error 1e-12`) was unreachable for this system; per the
PLAN it was not adjusted and not retried.

## 3. Import identity and doping (per 2D level, before its solve)

| | L3 | L4 | L5 |
|---|---|---|---|
| nodes / elements | 48033 / 95400 | 128067 / 255400 | 441733 / 882600 |
| node coordinates = `(P32*1e-4).astype(float)` node by node | true | true | true |
| element vertex-set multiset = E6A triangles | true | true | true |
| NodeVolume bit-equal to E6A; edge n0/n1/EdgeCouple/EdgeLength bit-equal to E6A | true; true | true; true | true; true |
| contacts `Si_xmin`/`Si_xmax` by coordinate | 101 / 101 | 101 / 101 | 101 / 101 |
| x = 0 nodes; Donors / Acceptors / NetDoping there | 801; 1e18 / 1e18 / 0 | 1601; same | 3201; same |
| x = 0 sum NodeVolume (cm^2); sum Donors x NV; sum NetDoping x NV | 3.125e-10; 3.125e8; 0 | 1.5625e-10; 1.5625e8; 0 | 7.8125e-11; 7.8125e7; 0 |
| total Donors x NV (= total Acceptors x NV, cm^-1) vs continuum 2.4999997e11 | 2.50156e11 | 2.50078e11 | 2.50039e11 |

The J0 doping was constructed explicitly in the audit device (both species at full strength on x = 0, net 0). It is not evidence that
production `apply_doping()` supports a 2D step junction. The x = 0 column carries the excess of the donor/acceptor integral over
the continuum value (N h/2 per side): 0.062%, 0.031%, 0.016% at L3, L4, L5. These are raw numbers of the discrete doping
representation, not a sheet charge, and no potential difference is attributed to Poisson spatial discretization alone.

## 4. Level-to-level differences on the bit-identical common node set (raw; NOT classified)
Core |x| <= 0.1 um (26433 nodes; 33 x-nodes on a row), weights = L3 NodeVolume, Ex on the fixed core segments (width 0.00625 um).

| metric | D34 = M(L3-P, L4-P) | D45 = M(L4-P, L5-P) | D34 - D45 |
|---|---|---|---|
| psiLinf (V) | 1.02952e-03 | 2.57917e-04 | 7.7161e-04 |
| psiL2 (V) | 3.70135e-04 | 9.03832e-05 | 2.7975e-04 |
| ExLinf (V/cm) | 1698.41 | 387.295 | 1311.12 |
| ExRMS (V/cm) | 520.613 | 123.760 | 396.853 |

Transition region (psi only): D34 1.99e-11 (Linf), D45 1.84e-12; outer region: D34 1.7e-16, D45 1.1e-16 (the outer
mesh is identical at every level and the potential there sits on the plateau set by the contact boundary value).
`S3`, `S4`, `S5` are **invalid** (controls not converged): the three inequalities are not evaluated and the four metric states are
`NOT_CLASSIFIED`. The observation that D34 exceeds D45 by a factor 4.0 to 4.4 in all four metrics is a raw number of this one
pair of pairs at fixed outer mesh; it is not a trend verdict and no convergence order is inferred from three levels.
Potential on the row y = -2.5 um at x = -0.1, -0.00625, 0, +0.00625, +0.1 um (P state): L3 -0.47685972, -0.20843456, 1.2e-18,
+0.20843456, +0.47685972; L4 -0.47685972, -0.20791490, 6.6e-18, +0.20791490, +0.47685972; L5 -0.47685972, -0.20778296,
-9.5e-19, +0.20778296, +0.47685972 (V).

## 5. Consistency and diagnostics (reported; none of them is a physics gate)
* y-uniformity (P state, max spread over each common x-line, limit 1e-6 V): core 7.8e-12 / 2.1e-15 / 7.2e-16, transition 8.0e-14 /
  1.7e-14 / 1.1e-14, outer 5.6e-17 at L3 / L4 / L5; all values finite: `consistency_ok` true at every level.
* Contact readback (P state): `Si_xmin` -0.4768597199126636 V, `Si_xmax` +0.4768597199126636 V at every level; this is the
  contact boundary formula's own value (Vt ln 1e8 = 0.476859719913), read back only.
* Gauss diagnostic on the P state (`PotentialIntrinsicCharge`, `PotentialEdgeFlux`, `NodeVolume`, `EdgeCouple` once each; sign
  +1 at n0 / -1 at n1 is the stated hypothesis). Non-contact nodes 47831 / 127865 / 441531; eligible 12015 / 46425 / 176047, of
  them on x = 0: 801 / 1601 / 3201, top row 15 / 27 / 51, bottom row 15 / 27 / 51; no `DIAG_*` state raised. `max |R_i|/s_i`:
  correct 8.05e-14 / 9.56e-14 / 3.36e-13; EdgeCouple omitted 2.35e+06 / 3.97e+06 / 6.58e+06; EdgeCouple twice 0.381 / 0.267 /
  0.161; charge sign flipped 0.763 / 0.534 / 0.322. Contact nodes (separate block): correct 1.0 at every level. The correct
  assembly and the three wrong variants are separated by many orders of magnitude, which is consistent with the sign and
  single-weight hypotheses; per PLAN 7 this is `ASSEMBLY_RECONSTRUCTION_DIAGNOSTIC_ONLY` and is not used for any pass or fail.

## 6. 1D reference R6 / R7 (observed quantities; no bound, no "floor" statement)
Both 1D meshes were built as planned (14849 and 29697 nodes, positions bit-identical to the plan, all 233 2D x-values present
bit-exactly, J0 doping at the single x = 0 node). Because R6-C and R7-C did not converge the reference is
`REFERENCE_1D_UNUSABLE` (recorded reason `R6-C invalid: C_NOT_CONVERGED_OR_ERROR`), so **no `observed_reference_gap` and no
`observed_reference_refinement_change` was computed** and no floor-related state exists. The raw R6/R7 potentials are kept in
`ref_R6.npz` / `ref_R7.npz`. The conditional 1D-2D equivalence of PLAN section 8 remains unverified and untested here.

## 7. What this batch does and does not establish
Established (observation, one mesh family, 0 V): three imports identical to E6A; all primary Poisson solves converged in 10-11 iterations
with device relative error 2e-7 to 1e-6 (2D) and 6e-9 to 1e-6 (1D); y-uniform potentials; raw core differences D34 > D45 in all four
metrics. **Not established:** any solver-shift estimate, any trend (the metric states are `NOT_CLASSIFIED`), any relation to
a 1D reference, 2D convergence of any kind. Open: the control of PLAN 6.4 cannot measure the solver shift on this J0 system
(its relative-error target is not reachable and the state does not move), so a different control design would need its own
pre-registered PLAN; it is not proposed or attempted here.

## 8. Change record
Files of this batch: `PLAN.md`, `PLAN.sha256`, `PLAN_REVISION.md` (documents); `scripts/judge_e6b.py`, `stage_e6b.py`, `run_e6b.py`,
`synthetic_e6b_test.py`, `recheck_e6b_local.py`; `data/synthetic_e6b_results_pre_run.json` (21 synthetic rows, all as
pre-registered; the one defect it found, an empty-region maximum in `reference_assessment`, was fixed in the code, not in the
test), `data/recheck_e6b_local.json`, `data/remote_run_36527372624/`, `data/batch_e6b_code.patch` (unabridged `git diff -U1
f929a14c HEAD` of `scripts/` and `remote/`, 6 files, 1442 added and 3 removed lines, sha256
`2717c16e6c9b2397c3eeeed2080c3a30f03eb55c58580e198cdfc00a38bb8953`; verified to apply to `f929a14c`); `remote/profiles.py` (new profile
only, existing ones unchanged) and `remote/request.json`. `tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/`, DEVSIM / ViennaPS and
all E4 / E5 / E6A evidence are unchanged (`git diff` against the review SHA `023bcb90...` is empty).
