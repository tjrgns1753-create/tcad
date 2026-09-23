# Batch 5 (resumed) -- zero-duration GUI wording/marker fix and no-modal contract migration

Date: 2026-09-21. Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing committed).
This report replaces the earlier "STOPPED" report of the same folder; the evidence of that round is kept in `raw/` (`BEFORE_*`, `PROBE_*`, `REPRO_*`).
Approved decisions applied: findings 1 (`simulation complete` after a zero-duration request) and 2 (`Film / oxide` marker) are fixed in production;
Bosch's bitwise non-determinism is not an error (invariants larger than the exporter's representation offset are used, no exact hash/depth);
the worker failure is the fresh 0 h + invalid grid candidate, described as a worker-side wafer-state/recipe validation failure.

## 1. Code locations of findings 1 and 2 before the fix (`tcad_2d_stagewise.py`, `run_oxidation()`)

* Finding 1: at the end of `run_oxidation()` (old line 3286-3290) an unconditional `self._notify_info("ViennaPS", f"ViennaPS {model_label} simulation complete...")`, reached by the fresh-materialization and inherited-identity branches as well (the `unsupported` branch returns earlier with its own text).
* Finding 2: old line 3254 `self._mark_stage_done(1)` (index 1 = "Film / oxide"), also reached by both zero-duration branches (`identity = inherited_identity or fresh_wafer`).
* Evidence before: `raw/REPRO_zero_duration_success_wording.out.txt`, `raw/PROBE_session_state_markers.out.txt`; and the strengthened tests failing against the pre-fix file: `raw/ROUND2_test_F_against_prefix_production.out.txt`, `raw/ROUND2_target_test_against_prefix_production.out.txt` (`B: the Film / oxide marker ... changed: [0] -> [0, 1]`).

## 2. Production diff (`raw/production_diff_tcad_2d_stagewise.patch`, 2 hunks, only inside `run_oxidation()`, lines 3254-3326)

1. `self._mark_stage_done(1)` is now `if not identity:`-guarded (so it is reachable only when a real, non-zero-duration, supported oxidation succeeded).
2. The final `_notify_info` is now a three-way choice: `if fresh_wafer:` (virgin Si materialized text), `elif inherited_identity:` (identity text), `else:` the unchanged `simulation complete` text.
Not touched: `completed_steps`, `flow_step_meshes`, `history`, WaferState transitions, `processed`/`process_stage` semantics, flow physical-change counting, the unsupported branch.

## 3. Branch table (`run_oxidation()` after the fix)

| branch | notification (user-facing) | `processed` / `process_stage` | Film / oxide marker | recorded (unchanged) |
|---|---|---|---|---|
| fresh 0 h (`materialization`) | "NO OXIDATION PERFORMED (0 h)": no solver / native-oxide seed; no earlier wafer so only the requested virgin Si was materialized; no SiO2, pad oxide or Mask; the mesh is that virgin Si, not an oxidation result | not promoted | not lit | `completed_steps`, `history` (`... (0 h, no oxidation)`) |
| inherited 0 h (`identity`) | "NO OXIDATION PERFORMED (0 h)": no solver / seed; existing geometry/state preserved as an identity; no new oxide or Mask; the mesh represents the preserved geometry | not promoted | not lit | same |
| unsupported (positive time) | unchanged: `OXIDATION RESULT NOT COMPUTED (UNSUPPORTED_BY_MODEL)`, four numbered facts | not promoted | not lit | not recorded |
| real supported positive-time oxidation (none exists today) | `ViennaPS <model> simulation complete.` | `processed=True`, stage `oxidized` | lit | recorded |

## 4. Film / oxide marker, before and after (`raw/PROBE_session_state_markers.out.txt` vs `raw/AFTER_FIX_probe_session_state_markers.out.txt`)

| step | before | after |
|---|---|---|
| fresh 0 h | `_stages_done={0,1}`, `● 02 Film / oxide` | `{0}`, `Film / oxide` not lit |
| inherited 0 h | `{0,1}`, lit | `{0}`, not lit |
| positive-time (unsupported) | `{0}` | `{0}` (unchanged) |
| default deposition (a real film step) | lit | lit (unchanged, correct) |

Side effect to know about: the `● 01 Si wafer` label was lit after a zero-duration step only as a by-product of that `_mark_stage_done(1)` call (it re-colours every marker). It now stays `○` after a fresh materialization. `_stages_done` itself always contained `0`; the initial label is `○` until some step re-colours the markers, a pre-existing inconsistency that was not changed (out of scope).

## 5. Tests changed

* `tests/integration/test_oxidation_positive_time_unsupported_real.py::test_F`: strengthened, nothing removed. Zero-duration fresh and inherited, thermal and LOCOS: case-insensitive `simulation complete` / `oxidation complete` / `growth complete` absent from log and notification; a notification exists and says no oxidation performed; Film / oxide marker and `_stages_done` unchanged; fresh and inherited notifications differ ("materialized" vs "preserved"). Unsupported: no marker, no success wording, the four fail-closed facts kept. Result: rc=0 (29.8 s); against the pre-fix production file it fails on the wording.
* `tests/integration/test_gui_headless_no_modal_hang_real.py`: rewritten as independent scenarios A-G plus false-green guards (below).

## 6. A-G results (real GUI, real worker subprocesses, real ViennaPS 4.6.2; `raw/FINAL_test_gui_headless_no_modal_hang_real.out.txt`)

| scenario | request | transition / status | solver meaning | materials | geometry change | processed / stage / marker | modal calls |
|---|---|---|---|---|---|---|---|
| A | withdraw, calibrate | -- | -- | -- | -- | `winfo_viewable()==0`; 8 messagebox functions trapped and each direct call recorded, then cleared | 0 |
| B fresh zero-time | 0 h, grid 0.1 | `materialization`, inherited False, bounds `[-5,5,-5,0]` | no oxidation solver (GUI log; in-process proof is in `test_oxidation_zero_duration_identity_real`) | Si | virgin Si, area 50.0, top 0, floor -5 | False / `wafer` / not lit | 0 |
| C inherited zero-time | 0 h on B | `identity`, inherited True | no oxidation solver; identity | Si | equal to B (see section 8) | False / `wafer` / not lit | 0 |
| D default Bosch etch | GUI defaults, on C | real step (no transition) | real ViennaPS etch | Si | Si top lowered at all 9 columns | True / `etched` / not lit | 0 |
| E default deposition | Isotropic SiO2 defaults, on D | real step | real ViennaPS deposition | Si, SiO2 (a deposited film) | film at 9/9 columns | True / `deposited` / lit | 0 |
| F positive-time | 0.4 h, fresh | `unsupported`, `OXIDATION_CAPABILITY_PROOF_MISSING`, worker `success=True`; physics `UNSUPPORTED_BY_MODEL` | no solver call | Si (last-known) | none | False / `wafer` / not lit; `completed_steps` 0 | 0 |
| G validation failure | 0 h, grid -1, fresh | worker `success=False`, `ValueError(...)` | none (validator) | none returned | nothing adopted | False / `wafer` / not lit | 0 |

## 7. Bosch (D) and deposition (E) invariants and bounds

Bound: `EXPORT_TOL = 0.1 x grid = 0.010 um`, the smallest change distinguishable from the exporter's representation offset (measured 0.005-0.0099 x grid in the Batch 4 audit). It is not tuned to the observations. No seed, no retry, no exact hash, no exact depth.

* D asserts: worker success; only `Si`; at **every** one of 9 interior columns the Si top is lower than before by more than 0.010 um; Si floor unmoved; mesh inside the domain bbox; Si area decreased; finite; `processed`, stage `etched`, marker not lit. Observed in the final run: lowering 0.0690-0.0905 um (>= 6.9 x the bound); in 3 further independent invocations 0.0701-0.0905, 0.0681-0.0912, 0.0696-0.0898 (`raw/ROUND2_target_test_extra_runs.out.txt`); earlier 10-run probe 0.0682-0.0926 (`raw/PROBE_default_etch_variability.out.txt`). These are observations only and no assertion was shaped by them.
* E asserts: worker success; materials exactly `Si`,`SiO2` (no Mask); SiO2 present at 9/9 columns with thickness > 0.010 um; the film lies on the Si (SiO2 bottom = Si top within 0.010); Si top/floor unchanged within 0.010 and Si area within 0.010 x width; stage `deposited`, marker lit (a deposition is a film step). Observed film thickness 0.0240-0.0242 um (bound margin 2.4x), Si top change <= 0.0010 um. The nominal rate x time is 0.025 um; it is printed by the earlier probes only and is not an expectation.

## 8. B vs C (fresh materialization vs inherited identity)

They differ in the transition (`materialization`/inherited False/`initial_geometry` Si bounds and instance id vs `identity`/inherited True), in the text (materialized virgin Si vs preserved as an identity), and in what they claim about state. Their geometry is equal: exported per-material area, triangle counts, bbox and every sampled column extent are compared with exact equality, and the two saved domains are LOADED and compared (material order and the surface polyline of every level set). Mesh file sha256 is equal (`c19836cb9f07...`); the `.vpsd` bytes differ (`b98ab32f0974...` vs `b40b402800b2...`), which is why the comparison is on loaded content, not on the file hash.

## 9. Origin of the G error

The exception text `ValueError('recipe bounds do not describe a valid virgin Si wafer: x_extent_um=10.0, silicon_depth_um=5.0, grid_delta_um=-1.0')` is raised by tcad's own transition builder, `tcad/physics/wafer_state_accumulation.py:154-157`, INSIDE the worker subprocess: the test observes (pass-through, not a mock) that the result file did not exist before the worker ran, the worker returned code 0 and wrote `{"success": false, "error": ...}`, and no state/mesh was returned. It is a worker-side wafer-state/recipe validation failure, not a ViennaPS solver exception, not a ViennaPS `RuntimeError`, not a physical simulation failure; ViennaPS never ran. The GUI title prefix `ViennaPS:` in the log line is only the title `run_oxidation` passes to `_notify_error`. The test checks that the message text exists in that source file. Candidate 2 and the old positive-time invalid-grid recipe were not run.

## 10. Modal calls

0 in every scenario, checked immediately after each one (`Trap.assert_none`), and again at the end; the trap covers all 8 functions the running Python's `tkinter.messagebox` exposes (asserted equal at run time and by static check 6). `_notify_info`/`_notify_error` are not patched.

## 11. False-green guards (14, each with an exact expected reason; `expect_fail`: a passing check is FALSE GREEN, another reason is WRONG FAILURE REASON)

materialization judged as identity (`not an inherited identity`); inherited identity changes geometry (`exported geometry differs`); zero-duration log says simulation complete (`success wording 'simulation complete'`); zero-duration step lights the Film / oxide marker (`the Film / oxide marker ...`); Bosch changes nothing / lowers by less than 0.1 x grid (`did not lower the Si top by at least`); deposition adds no film / film thinner than 0.1 x grid (`no SiO2 film was added` / `SiO2 film missing or thinner than`); unsupported judged as a successful step (`not a plain successful step`); worker validation error judged as unsupported (`not an unsupported result`); unsupported judged as a worker error (`the worker reported success True`); worker error without an ERROR entry (`no ERROR entry / failure notice`); a messagebox call during a scenario (`1 modal dialog call(s) reached tkinter.messagebox`); a trap that records nothing (`the trap did not record every direct call`).

## 12. Target and control results (independent runs; `raw/FINAL_*.out.txt`, `raw/FINAL_run_summary.txt`)

| test | rc | time |
|---|---|---|
| `tests/integration/test_gui_headless_no_modal_hang_real.py` | 0 | 9.2 s |
| `tests/integration/test_oxidation_positive_time_unsupported_real.py` | 0 | 29.8 s |
| `tests/unit/test_gui_no_forced_order_mock.py` | 0 | 0.8 s |
| `tests/unit/test_gui_error_dialog_visibility_gate_mock.py` | 0 | 0.8 s |
| `tests/integration/test_oxidation_zero_duration_identity_real.py` | 0 | 4.5 s |
| `tests/integration/test_waferstate_sequential_flow_real.py` | 0 | 20.5 s |

No full regression was run. The migrated test was also run 3 more times independently (all rc=0) and once against the pre-fix production file (rc=1 at B, as intended).

## 13. Static checks (`scripts/static_checks.py`, `raw/FINAL_static_checks.out.txt`, ALL PASS, rc=0)

Text/AST/file-time scans only; they do not prove GUI behaviour. They confirm: the only `simulation complete` string in `run_oxidation()` is in the physical-success else-branch; the only `_mark_stage_done` call is guarded by `if not identity:` and follows the unsupported branch, which has none and returns; no un-negated "ViennaPS solver exception / physical simulation failure" wording in the test; no exact mesh-hash literal/comparison, no seed/retry, only the named bound in the Bosch/deposition checks; the trap list equals the 8 messagebox functions; the production diff is confined to `run_oxidation()`; the other 81 `tcad/**/*.py` files are unchanged; files modified since the start of the round are only the 3 allowed ones.

## 14. Scope, `git diff --check`, HEAD

`raw/repo_state_end.txt`: status differences outside this audit folder = exactly the target test becoming modified (`tcad_2d_stagewise.py` and the positive-time test were already modified/untracked before the round); 0 staged; `git diff --check` in a clean git environment rc=0, no output; HEAD unchanged, 0 commits. Changed files this round: `tcad_2d_stagewise.py` (2 hunks), `tests/integration/test_oxidation_positive_time_unsupported_real.py`, `tests/integration/test_gui_headless_no_modal_hang_real.py`, and this audit folder.

## 15. Remaining limits

* Solver-call absence for zero-duration and unsupported steps is proven in-process by `test_oxidation_zero_duration_identity_real`/`test_oxidation_positive_time_unsupported_real`; across the GUI's subprocess boundary this test relies on the GUI log and the worker's `state_transition`.
* The exact Bosch mesh is not reproducible run to run; only the invariants above are asserted.
* The zero-duration steps are still appended to `completed_steps` and `history` (`(0 h, no oxidation)`), by design and untouched.
* The `01 Si wafer` label side effect of section 4.
* The G exception is tcad's validator, not a ViennaPS exception; if a ViennaPS-originated exception is wanted, the old positive-time + grid -1 recipe (ViennaPS `RuntimeError('Domain setup is not correctly initialized.')`, 2/2 in `raw/PROBE_determinism_and_old_g.out.txt`) is available, but was not used.
* `test_oxidation_positive_time_unsupported_real.py` is an untracked file in this working tree, so its diff is not visible in `git diff`; its edits are in `raw/`-referenced runs and the file itself.
