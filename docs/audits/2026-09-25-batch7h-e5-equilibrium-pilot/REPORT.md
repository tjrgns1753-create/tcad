# Checkpoint A + Batch 7H-E5 REPORT: raw-evidence portability + 0 V equilibrium electrical pilot

## Summary
* **Checkpoint A: `RAW_EVIDENCE_PORTABLE`.** 5 raw `.vtu` files whose committed blob previously differed from their
  recorded artifact sha256 on a `core.autocrlf=false` checkout now match on both settings. Fixed with a narrow
  `.gitattributes` rule, not by hand-editing any file's bytes. Commit `668da8f9a093dae9784a7fa98355129852794963`.
* **Checkpoint B (Batch 7H-E5): all 6 registered runs `CONVERGED_OK`.** Maximum verdict: **`EQUILIBRIUM_PILOT_ONLY`**
  — geometry- and mesh-representation-dependent observations at one bias point (0 V) on one candidate mesh; not a
  claim about I-V accuracy, 2D mesh convergence at other bias points, or general PN behaviour. 7H-E4's own
  `GEOMETRY_CANDIDATE_ONLY` verdict is unchanged and is not merged with this batch's electrical result.
* The first remote attempt at Batch 7H-E5 (run `36149228558`) failed with `conclusion: failure` — two script bugs
  (a tuple-unpacking error and a missing `finally` for device cleanup, which leaked a device into every subsequent
  run — the exact leaked-device failure mode this project's own CLAUDE.md already documents). Fixed
  (`BUGFIX_NOTE_1.md`), rerun clean (run `36151109973`). `PLAN.md`/`PLAN.sha256` were never touched by the fix.
* `devsim.solve` was called **12 times total** across the clean run: 2 per device-variant pair (1 Poisson, 1
  drift-diffusion-at-0V) x 6 pairs. Every one of the 12 calls reports `converged: true` from DEVSIM's own `info=True`
  result. No call was retried with unchanged settings; S0 and S12 are reported as separate, never-merged verdicts.

## Checkpoint A: raw `.vtu` checkout portability

### Before / after, per file (working-tree sha256 = the byte content on this machine = the recorded artifact sha256
throughout; only the **committed git blob** sha256 changed)

| file | artifact sha256 (unchanged throughout) | git blob sha256 BEFORE | git blob sha256 AFTER |
|---|---|---|---|
| E2 `C_ccw.vtu` | `82fa87b0...4d5767` | `7696bf0c...d3aeeb` (LF, differs) | `82fa87b0...4d5767` (matches) |
| E2 `C_rt.vtu` | `82fa87b0...4d5767` | `7696bf0c...d3aeeb` (differs) | `82fa87b0...4d5767` (matches) |
| E2 `candidate_flip.vtu` | `d5a73665...331f04` | `893bf0be...25ed555` (differs) | `d5a73665...331f04` (matches) |
| E3 `candidate.vtu` | `9ea67bd5...34ec0` | `ea928848...d8d019c` (differs) | `9ea67bd5...34ec0` (matches) |
| E4 `candidate_e4.vtu` | `85ebcbae...421297` | `7482df16...9e65787` (differs) | `85ebcbae...421297` (matches) |

Full values in `docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/data/checkpointA_before.txt` and
`checkpointA_after.txt`.

### Method
1. Recorded working-tree, remote-`summary.json`, and git-blob sha256 for all 5 files before any change
   (`checkpointA_before.txt`) — working tree already equalled the artifact hash on this machine
   (`core.autocrlf=true` restores the original CRLF bytes on checkout here); only the committed LF blob differed.
2. Added `.gitattributes`: `docs/audits/*/data/remote_run_*/outputs/*_out/*.vtu -text` — verified with
   `git check-attr text` on the exact 5 paths (all `unset`, i.e. the rule matched) and on an unrelated production file
   (`tcad/backends/viennaps/io.py`: `unspecified`, i.e. untouched).
3. `git add --renormalize` on the 5 files (plus 3 already-LF `wafer_volume.vtu` files under the same pattern, which
   needed no byte change) — re-hashed the staged blob to equal the working-tree bytes exactly
   (`checkpointA_after.txt`, all 5 `match: YES`).
4. Verified with `git -c core.autocrlf={true,false} checkout-index` from the staged index (before commit) and again
   from `HEAD` (after commit): identical sha256 under both settings, for all 5 files, at both points.

No JSON/NPZ/PLAN/REPORT content was changed. The prior `eol_normalization_note.txt` (which first found the
inconsistency) is preserved unchanged as history. Committed separately: `668da8f9a093dae9784a7fa98355129852794963`.

## Batch 7H-E5: PLAN, path correspondence, execution

PLAN `PLAN.md` sha256 (LF) `924395fb86a72658853a9b8ffd7827cdb0ddf6c1473d55609af09764ce8802fa` (runner CRLF checkout
`8bf59502...`, same content, verified equal this session). Committed alone in
`fd9881ec012465af1936326dd2a64079582d1468`. Run only because Checkpoint A returned `RAW_EVIDENCE_PORTABLE`.

Doping equation: `tcad/device/devsim/doping_mapping.py:864,868` (`Donors = donor_conc*step(x-x_j)`,
`Acceptors = acceptor_conc*step(x_j-x)`); mirrored convention `tcad/physics/wafer_state_v2.py:743-744`. Node-array
write mechanism (public API, no gate call): `shadow_e1.py:144-145`. Equilibrium equations, unmodified:
`tcad/device/devsim/semiconductor_equation.py:50-91`. Solver tolerances, production default:
`tcad/characterization/pn_junction_iv_sweep.py:88-93` (Poisson `abs=1.0, rel=1e-6, maxiter=100`; DD
`abs=1e10, rel=1e-6, maxiter=100`) — only its first two solve calls are reproduced, never its bias-ramp third call.
1D method: `docs/audits/2026-09-23-batch7h-d1-pn-convergence/scripts/common_d1.py:30-53`,
`meshes_d1.py:33-45`, generalized from X_HALF=0.5 to 5.0 um (synthetic test proves exact agreement with D1's own
formula at every one of D1's own 5 mesh sizes: `data/synthetic_e5_results_pre_run.json`, `ALL_OK: true`).

**First attempt failed (script bugs, not physics)**: run `36149228558`, `conclusion: failure`, archived as
`data/remote_run_36149228558/` + `data/artifact_remote_run_36149228558_FAILED_BUGGY.sha256`. `D2D_S0` crashed
(`AttributeError: 'tuple' object has no attribute 'get'`) immediately AFTER both its solve calls had already
converged; the resulting leaked `e5_d2d_device` then made `D2D_S12` fail outright (mesh-name collision) and left the
device registered through the remaining 4 runs, whose `POISSON_NOT_CONVERGED` results (`psi_range_V: [0.0, 0.0]`
throughout — no progress from the zero initial guess at all, unlike 7H-D1's own genuine oscillating-residual J0
finding) are recorded as **`INCONCLUSIVE`**, confounded by the leak, not attributed to J0 or J1 physics. Full account:
`BUGFIX_NOTE_1.md`. Fixed (cleanup moved into `finally`, keyed off tracked resources; a pre-flight
`devsim.get_device_list()` check now stops closed with `STOP_LEAKED_DEVICE_FROM_PRIOR_RUN` if this ever recurs) and
committed as `6a3f5a96926ad3447e291992ab2054a0ba4e3657`, then rerun with a bumped request id (no PLAN change)
`e5-equilibrium-pilot-002`.

**Clean run**: https://github.com/tjrgns1753-create/tcad/actions/runs/36151109973 (commit
`e3141f3f5d2489bdbf782746befc7570b05a317c`), `PASS`, exit 0, 89.4 s, DEVSIM 2.11.0,
`code_paths_identical_to_review_sha = true`. 7 outputs + log, all matching `summary.json` sha256; strict JSON parse
OK; sensitive-pattern scan clean; `devices_left: []`. Serena MCP unavailable again this session
("Skipping connection, recent failure cached"); rg + direct reading used, same as every 7H-E batch.

## solve() call accounting (PLAN section 3.5)

| run | Poisson call | DD call | total this run | converged (both) |
|---|---|---|---|---|
| D2D_S0 | 1 (10 it) | 1 (1 it) | 2 | yes |
| D2D_S12 | 1 (10 it) | 1 (1 it) | 2 | yes |
| D1D_J0_S0 | 1 (10 it) | 1 (1 it) | 2 | yes |
| D1D_J0_S12 | 1 (10 it) | 1 (1 it) | 2 | yes |
| D1D_J1_S0 | 1 (11 it) | 1 (1 it) | 2 | yes |
| D1D_J1_S12 | 1 (11 it) | 1 (1 it) | 2 | yes |
| **total** | **6** | **6** | **12** | **12/12** |

No retry with unchanged settings anywhere; S0 and S12 are 6 independent runs, each its own fresh device.

## Comparison table (D2D / D1D_J0 / D1D_J1, S0 shown; S12 numbers in `data/remote_run_36151109973`, agree to the
digits shown except where noted)

| | D2D (7H-E4 candidate, 2D) | D1D_J0 (1D companion) | D1D_J1 (1D staggered comparison) |
|---|---|---|---|
| nodes | 128067 | 3201 | 3202 |
| x=0 node present | yes (1601 nodes, matches E4) | yes (1) | **no** (by construction) |
| Poisson: converged, iterations | yes, 10 | yes, 10 | yes, 11 |
| DD @ 0V: converged, iterations | yes, 1 | yes, 1 | yes, 1 |
| contact potentials (V) | +-0.4768597199126636 | +-0.4768597199126637 | +-0.4768597199126637 |
| = analytic V_bi/2 (0.47685971991...) | yes, 13+ digits | yes, 13+ digits | yes, 13+ digits |
| y-symmetry max spread (2D only) | 3.89e-16 V | n/a | n/a |
| qf flatness (V) | 7.06e-16 | 4.90e-16 | 6.94e-16 |
| mass-action deviation | 2.53e-14 | 1.93e-14 | 2.76e-14 |
| n_range / p_range (cm^-3) | [100, 1e18] | [100, 1e18] | [100, 1e18] |
| = n_i^2/N (100 exactly) | yes | yes | yes |
| max \|E\| (V/cm) | 358113.011 | 358113.010 | **382716.987** |
| bias readback (V) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| C0 contact currents (A, both species) | ~1e-30 (numerical zero) | exactly 0.0 | ~1e-27 (numerical zero) |
| Potential at x=+0.00 cut (V) | +7.23e-18 (node at exact x=0) | -4.20e-18 (node at exact x=0) | **-0.0598** (nearest node is at x=-0.0015625, h/2 off-centre — labelled honestly by its own `x_actual_um`, not a defect) |
| donor NodeVolume integral | 2.500780905e11 cm^-1 | 5.0015625e14 cm^-2 | 5.0e14 cm^-2 |
| geometric continuum reference (as recorded) | 2.499999828e11 cm^-1 | **0** (script bug, see below) | **0** (same bug) |
| donor integral - continuum, relative | +0.031236 % | n/a (bug) | n/a (bug) |
| analytic V_bi / W(0V) / L_D | 0.953719 V / 0.048396 um / 0.003987 um | same (identical N, T) | same |

**A units bug in `doping_integrals()`'s `geometric_continuum_reference` field, found post-hoc (not fixed in the raw
JSON, corrected here by direct computation from the already-recorded, unchanged inputs):** the 1D branch multiplied
by a "depth" read from the device's own `y` node model, which DEVSIM's 1D devices report as uniformly 0 (a 1D device
has no y-extent) — giving `N * 0 * 5 um = 0` exactly, matching the recorded `0` in both 1D JSONs. The PLAN's own text
(section 4: "geometric continuum reference (N x domain half-length, here N x 5 um in appropriate units)") did not call
for a depth factor at all; the correct 1D value is simply `N x X_HALF_UM x UM = 1e18 x 5.0 x 1e-4 = 5e14 cm^-2`. Against
that corrected reference: D1D_J0's 5.0015625e14 is **+0.03125 %** high; D1D_J1's 5.0e14 matches to machine precision
(0 %). Both numbers are exactly consistent with the same J0 junction-line mechanism 7H-E2/E4's supplementary erratum
already quantified for the 2D case: the 1D analogue of that formula (no y-height factor, since 1D has none) is
`N x h / 2 = 1e18 x 3.125e-7 cm / 2 = 1.5625e11 cm^-2` — and `5.0015625e14 - 5.0e14 = 1.5625e11` exactly. This is a
clean, shape-defect-free confirmation of that same mechanism, on plain uniform 1D meshes with no obtuse geometry
involved at all — the excess is purely the J0 double-assignment rule, nothing else. This bug affects only the
recorded continuum-reference NUMBER, not the underlying NodeVolume integrals themselves (which come straight from
DEVSIM and are correct) and not any solve.

## What this batch establishes and does not

**Established, for 0 V equilibrium on this exact mesh and doping only:**
* The real production doping rule (J0: both species at full strength on the x=0 node) solves cleanly on the 7H-E4
  candidate at production's own default tolerances, both without and with extended precision — 10 Newton iterations
  for Poisson, 1 for drift-diffusion-at-0V, every time.
* The result agrees with the analytic V_bi/2 to 13+ significant digits, with a simple 1D device built on the exact
  same doping rule, domain and finest local spacing.
* y-independence (a real symmetry the true physics requires and the mesh does not enforce structurally) holds to
  3.9e-16 V.
* Mass-action and quasi-Fermi flatness are at or below machine-precision-scale deviations in every run.
* The J0 junction-line doping-integral excess (already found and formularized for the 2D case) reproduces in a
  shape-defect-free 1D setting exactly as the formula predicts.

**Not established, explicitly:**
* Anything about non-zero bias, forward or reverse I-V, or terminal-current accuracy — never attempted.
* 2D mesh convergence — one mesh only.
* MOS or any process geometry beyond 7H-E1's single-Si planar wafer.
* That the J0 junction-line term (now confirmed real and quantified, ~0.03 %) is acceptable for any downstream use —
  a separate physics decision, not made here.
* That 7H-E4's mesh is production-ready — its own `GEOMETRY_CANDIDATE_ONLY` verdict stands, unmerged with this
  batch's `CONVERGED_OK` electrical results; an electrical result here is not folded back into, and does not upgrade,
  that geometric verdict.
* Whether the first (buggy) run's non-convergence pattern was PURELY the leaked-device confound or also partly a
  genuine effect of 1e18/10um-scale J0 — the clean rerun converging in 10-11 iterations at both S0 and S12, versus the
  first run's 100-iteration stall on the SAME devices, is strong but not exhaustive evidence for "purely confounded";
  this is not re-tested further in this batch.

## No-change confirmation
Production and tests byte-identical to the start of this session's work
(`docs/audits/2026-09-25-batch7h-e5-equilibrium-pilot/data/start_hashes_prod_tests.txt`, rc 0) and to review SHA
`023bcb90` (`git diff --quiet`, rc 0). Prior batches (7H-E1-E4, 7H-D1, 7H-D2) tracked files and all pre-existing
`docs/audits/` files unchanged (`start_hashes_prior_batches_tracked.txt`, `start_hashes_all_audits.txt`, rc 0 each).
Gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` untouched, never called, never bypassed — this batch's device is
built entirely in an audit script, labelled `AUDIT-ONLY SHADOW` (reusing `shadow_e1.py`'s own label convention), never
presented as a production-supported result. No precision flag persists outside its own run (S12's flags are reset in
`finally`). No full regression, no GUI run. `origin/claude/waferstate-v2 = 023bcb90...`,
`origin/main = d60e9aed...`, unchanged.

## Files and commits
`.gitattributes` (new); Checkpoint A evidence under
`docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/data/checkpointA_{before,after}.txt` (commit
`668da8f9`). E5: `PLAN.md`, `PLAN.sha256` (`fd9881ec`); `scripts/{devices_e5,stage_e5,run_e5,synthetic_e5_test}.py`,
`remote/profiles.py` (profile added), `remote/request.json`, start-state hashes, synthetic results (`3084a3dd`);
`BUGFIX_NOTE_1.md`, the fixed `stage_e5.py`, archived first-run evidence (`6a3f5a96`); bumped request id
(`e3141f3f`); this `REPORT.md` and clean-run evidence (commit recorded after push, in the closing chat message).
