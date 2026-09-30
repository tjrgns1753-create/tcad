# Batch 7H-E6E REPORT: fail-closed per-region area-conservation gate in the DEVSIM importer

**Result.**
- **Gate.** Implemented and verified on the pre-registered controls: G0, G1, the two-material mesh and the large-coordinate mesh pass.
  E6D G2 is refused inside `import_process_result()` before any device is returned. That refusal was checked in all three paths —
  the importer called directly, both GUI paths and the CLI — each with 0 doping writes, 0 solves and no number reported.
- **Full regression (run once).** 101 passed / 41 failed.
  - 20 failures carry the new refusal `MESH_AREA_NOT_CONSERVED` in their own output.
  - Several of these are **raw, unrefined ViennaPS meshes whose `Mask` region's DEVSIM NodeVolume sum is 8-28x the region's triangle
    area**, and whose `Si` region is up to +30 %. This was NOT predicted in PLAN section 3, which predicted only refined meshes.
  - The gate's scope was not changed after this result. Neither was its region list: for example, it was not narrowed to regions that
    carry equations.
  - This is a structural finding that needs Codex/user review before anything else changes.
- **What remains unverified.** Not verified here: the effect of the second non-core refinement pass, 2D mesh convergence, and PN
  physics. G2's refusal is not mesh convergence. Passing this gate is not physics approval.

## 1. Before the change: did production accept G2? (measured)
Run 36667603273 (HEAD `decb8f9`; production identical to `023bcb90`, rc 0; DEVSIM 2.11.0, numpy 2.4.6, Python 3.11.9) used the
unmodified `import_process_result()` on the raw, sha-gated E6D meshes. `devsim.solve` and the node / edge / equation write APIs were
trapped, and all of them stayed at 0 calls.

| mesh | device returned | sum NodeVolume [cm^2] | file area x 1e-8 [cm^2] | relative |
|---|---|---|---|---|
| G0 | yes | 4.999999310821319e-07 | 5.000000000000001e-07 | -1.3783573649117642e-07 |
| G1 | yes | 4.999999310821319e-07 | 5.000000000000001e-07 | -1.3783573649117642e-07 |
| G2 | **yes** | 5.015624284563546e-07 | 5.000000000000001e-07 | **+3.1248569127091397e-03** |

- **Verdict:** production created and returned the G2 device. Only the E6D audit script had stopped it before.
- **The -1.38e-7 is a coordinate artifact, not a DEVSIM error.** It is float32 um x 1e-8 compared with DEVSIM's float64 cm coordinates.
  This is why the contract computes area on DEVSIM's own coordinates.
- Evidence: `data/remote_run_36667603273/` (repro_G0/G1/G2.json shas `2515b362…`, `332dc97e…`, `f09306e3…`).

## 2. Call paths
| path | file:line | order |
|---|---|---|
| GUI measurement | `tcad_2d_stagewise.py:5822` `run_measurement` | optional refinement (step 5781 / gaussian 5788 / implant-windows `_refine_for_implant_windows` 5796) -> `import_process_result` -> `apply_doping` (5891) or robust sweep (5870) -> sweep solve -> log / info dialog with current (5943-5960); `finally` deletes device |
| GUI electrodes | `tcad_2d_stagewise.py:6121` `resolve_electrode_pins` | pin resolution -> `import_process_result` -> kept in `last_electrode_import`; `run_dc_operating_point` (6149) -> `apply_doping` (6247) -> `solve_mosfet_dc_operating_point` |
| CLI | `tcad/cli/run_pipeline.py:432` `run_pipeline` -> `_import_device` (228) | process -> doping profile -> import -> `_apply_device_doping` (434) -> `_run_characterization` (441) -> `_save_outputs` (442); `finally` `_cleanup_device` |

Other production caller: `examples/build_pn_diode.py:165,183` (receives the exception).

## 3. Contract (PLAN `537c4b4`, LF sha256 `2e366a06f92cd9847684d56ad0024e75991c3b440696c51f83d599972b544fdc`)
The contract is evaluated on the exact float64 arrays handed to DEVSIM.

**Before DEVSIM.** Each of the following is refused before anything is created:
- `MESH_NONFINITE_COORDINATES`
- `MESH_NOT_PLANAR_2D`
- `MESH_UNSUPPORTED_CELLS` (any other area-carrying block)
- `MESH_TAG_UNMAPPED`
- `MESH_EMPTY_REGION`
- `MESH_DUPLICATE_TRIANGLE`
- `MESH_DEGENERATE_TRIANGLE` (|o_t| <= gamma4(|p1|+|p2|))
- `MESH_ORIENTATION_MIXED`

**After `create_device`, per region.** The checks are:
- `MESH_REGION_ELEMENT_MISMATCH`
- `MESH_NODEVOLUME_INVALID` (empty, non-finite, <= 0, or unreadable)
- `MESH_AREA_NOT_CONSERVED`: |S_r - A_r| > B_r

**The tolerance.** B_r = E_A + E_S + E_NV:
- E_A = 1/2 gamma4 sum(|p1|+|p2|) + u A_r
- E_S = u S_r
- E_NV = 128 u sum A_t / sin theta_min,t. This term is an **assumption** inherited from 7H-E2 and was not derived from DEVSIM
  source.

The comparison is per region, so errors in different regions cannot cancel.

**Why not reuse E6D's tau.** E6D's tau uses the worst node's 1/sin theta for the whole mesh and is a whole-mesh quantity.

**Unsupported inputs.** The following are refused as `UNSUPPORTED_BY_MODEL`:
- non-planar or 3D meshes
- extra cell blocks
- any cylindrical / axisymmetric model (only Cartesian `NodeVolume` is certified; no cylindrical model exists in `tcad/`)

**Refusal behaviour.** On refusal the device and mesh are deleted with the public `delete_device()` / `delete_mesh()`. The outcome of
that cleanup is added to the same exception, and a cleanup failure is never hidden.

## 4. Production changes (commit `c5c0fad`; full patch `e6e_code.patch`, 784 lines, sha256 `413dc1441a27f6d38b3540a00aba1b18111e7b134e1eee472120f0bebd2dae19`, `git apply --check -R` ok)
- **New `tcad/device/devsim/mesh_conservation.py` (+153).** It adds:
  - `MeshAreaConservationError`
  - `triangle_terms`
  - `check_mesh_input`
  - `check_nodevolume`
  - `verify_device`
- **`tcad/device/devsim/mesh_import.py` (+23).** Changes, one per hunk:
  - `@@ -46` imports the gate.
  - `@@ -729` gives `ImportedDevice` an additive field `area_conservation` and adds `_ZERO_AREA_CELL_TYPES`.
  - `@@ -992` runs `check_mesh_input(points, triangles, tags, tag_to_name, extra_area_cells)` right after `tag_to_name`, before any
    DEVSIM call.
  - `@@ -1222` runs `verify_device(...)` after `create_device`, before the return.
  - `@@ -1228` passes `area_conservation=area_report` into the returned `ImportedDevice`.
- **`tcad_2d_stagewise.py` (+24).** Changes:
  - `@@ -5767` and `@@ -6104` import the error class.
  - `@@ -5916` (`run_measurement`) adds an `except MeshAreaConservationError` before the generic `except`. It sets
    `last_physics_status` and reports that no doping, no solve and no current were produced.
  - `@@ -6131` (`resolve_electrode_pins`) does the same and returns None.
- **CLI: no change.** The exception propagates before doping, characterization and output.
- **Unchanged:** DEVSIM, `NodeVolume`, `mesh_refine.py`, doping mapping, `tcad/physics`, examples, and the
  `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` gate. `git diff --quiet 023bcb90 HEAD` on doping_mapping, physics, mesh_refine and
  examples gave rc 0.
- **New tests:** `tests/unit/test_mesh_area_conservation_mock.py` (+139) and `tests/integration/test_mesh_area_conservation_gate_real.py`
  (+278).
- **Driver and profiles:** `scripts/run_tests_e6e.py`, and profiles `e6e_targeted` / `e6e_full_regression`.

## 5. Per-region numbers (targeted run 36668414619, exec SHA `33449384d9fc2b46040bfb7edbcebc2f746e480b`)
Tolerances were computed on DEVSIM's own coordinates.

| mesh | region | triangles / DEVSIM elements | area [cm^2] | sum NodeVolume | relative | tau | verdict |
|---|---|---|---|---|---|---|---|
| G0 | Si | 882600 / 882600 | 4.999999310821319e-07 | 4.999999310821319e-07 | 0.0 | 2.0853900949333038e-14 | pass |
| G1 | Si | 998000 / 998000 | 4.999999310821319e-07 | 4.999999310821319e-07 | 0.0 | 2.0923990510392493e-14 | pass |
| G2 | Si | 1459200 / 1459200 | 4.999999310821319e-07 | 5.015624284563546e-07 | 3.1249951791816333e-03 | 2.1077991226866585e-14 | **refused** `MESH_AREA_NOT_CONSERVED` |
| two-material | Si | 200 / 200 | 1e-08 | 1e-08 | 0.0 | 2.0763317285927422e-14 | pass |
| two-material | SiO2 | 200 / 200 | 1e-08 | 1e-08 | 0.0 | 2.076331728592743e-14 | pass |
| large coords (+1e4 um) | Si | 400 / 400 | 1.9999999999995597e-08 | 1.9999999999995593e-08 | -1.1102230246251565e-16 | 2.0763317286021123e-14 | pass |

## 6. Refusal path
`G2_refused`, `gui_measure_G2_refused`, `gui_pins_G2_refused`, `gui_dc_op_after_G2_refusal_solves_nothing` and `cli_G2_refused` all
passed. In each:
- `solve` = 0, `node_model` = 0, `set_node_values` = 0, `set_node_value` = 0.
- No current in any log or info dialog.
- CLI: `_apply_device_doping` was called 0 times and 0 output files were written.

Cleanup:
- `physics_status.cleanup = {"delete_device": "ok", "delete_mesh": "ok"}`, and the device list was empty afterwards.
- Re-importing G1 with the same names `gate_mesh` / `gate_device` succeeded.
- No devices were left at the end.

G1 controls in the GUI paths:
- Measurement: the importer was reached and returned a device. The test then stopped deliberately after import, with no doping and no
  solve.
- Electrodes: the importer was reached.

Local pure unit test: all cases passed. Fixture deviation from PLAN section 4, disclosed:
- The PLAN's boundary case "B_r (1 +/- 2^-20)" is not representable next to a 0.0625 node value.
- It was replaced by a one-node region with a known budget (area 1.0, E_NV = 1e-6) at B(1 -/+ 2^-10).

## 7. Controls and the one full regression (run 36668767301, exec SHA `e79f2a0a23b9387bf45d321ec430f0930de6661d`, 449.1 s)
The new tests passed, including `test_mesh_area_conservation_mock.py` and `test_mesh_area_conservation_gate_real.py`.

**`tests/run_regression.py`: 101 passed, 41 failed, 0 timed out, 0 skipped.** Failures were classified by the test's own output only.

**20 failures carry `MESH_AREA_NOT_CONSERVED`** (first failing region, relative difference):
- `Mask` region:
  - test_auto_refine_from_doping 7.107
  - test_device_lifecycle_repeat 17.935
  - test_gaussian_implant_doping 17.935
  - test_gui_measurement_doping_kinds 17.935
  - test_implant_windows_doping 0.01114
  - test_phase5_devsim 17.935
  - test_phase6_characterization 17.935
  - test_phase7_doping 17.935
  - test_phase8_pn_junction 7.107
  - test_robust_iv_sweep 27.219
- `Si` region:
  - test_device_fabrication_to_dc_sweep 0.0857
  - test_dopant_activation_devsim_gate 0.180
  - test_measurement_canonical_state_gate 0.30000000000004756
  - test_mosfet_body_bias 0.0857
  - test_mosfet_body_contact 0.0857
  - test_mosfet_gate_stack_cv 0.0101
  - test_mosfet_id_vds 0.0857
  - test_mosfet_id_vgs 0.0857
  - test_mosfet_vth_extraction 0.0857
  - test_wafer_state_v2_initial_geometry_devsim 0.186

**21 failures with no `MESH_*` code in their output are not classified:**
- test_ce2_oxidation_conversion_unsupported
- test_ce3_implant_anneal_etch_implant
- test_dopant_profile_matches_devsim
- test_doping_barrier_windows
- test_doping_mapping_per_node
- test_doping_mapping_recovery
- test_gui_doping_color_overlay
- test_gui_doping_donor_acceptor
- test_gui_doping_survives_geometry_steps
- test_gui_electrode_panel
- test_gui_implant_windows_overlay_note
- test_gui_measurement_captures_physics_status
- test_gui_thermal_anneal
- test_phase13_process_flow
- test_phase14_flow_devsim
- test_phase9_mos_cv
- test_physics_rules
- test_process_state_resume
- test_voltage_probe
- test_wafer_state_accumulation_devsim
- test_wafer_state

Why these 21 stay unclassified:
- No per-file baseline exists for this commit, so none is classified as pre-existing.
- A GUI test can fail on an assertion while the refusal text lives only in the GUI log, so "no code in output" does not prove the gate
  is uninvolved.

What a baseline would need: the same regression on `537c4b4` (the commit before the production edit). It was not run, because the batch
allows one full regression.

Test files were not edited to pass.

**Unexpected finding.** The first failing regions above include unrefined ViennaPS meshes, for example phase5, whose
`import_process_result` call passes no refinement argument (`tests/integration/test_phase5_devsim_real.py:60-66`).
`e6e_code.patch` is a verbatim `git diff -U1` (it must stay byte-exact to apply); its 5 blank context lines are a single space, which
`git diff --check` reports as trailing whitespace.
- In those meshes the `Mask` region's DEVSIM NodeVolume sum is 18-28x its triangle area.
- The `Si` regions of the MOSFET / gate-stack meshes are +1 % to +30 %.
- Whether these regions carry equations in each test was not examined.
- The cause, suspected to be sliver or obtuse triangles at level-set material interfaces per 7H-B, was not investigated.
- The gate was not adjusted.

## 8. Hygiene, commits, runs, evidence
**Commits (`claude/remote-runner`):**
- `decb8f9` repro script and profile
- `40a4681` step-1 evidence
- `537c4b4` PLAN, alone
- `c5c0fad` production and tests
- `3344938` targeted profile and request
- `e79f2a0` targeted evidence and regression request
- this REPORT commit

**`git diff --check`:**
- Range 537c4b4..3344938: rc 0 normal, rc 0 clean env.
- Evidence commit e79f2a0: rc 2. The only hit is the raw runner `run.log`, "new blank line at EOF" (raw evidence, not modified).
- Pre-commit anomaly: before committing `c5c0fad`, the clean-env `git diff --cached --check` reported every line of `mesh_import.py` as
  trailing whitespace (rc 2). The committed blob has 0 CR, and the committed range is rc 0 in both environments. The cause of that
  staged-index report was not determined.

**Runs:**
- repro https://github.com/tjrgns1753-create/tcad/actions/runs/36667603273
- targeted https://github.com/tjrgns1753-create/tcad/actions/runs/36668414619
- regression https://github.com/tjrgns1753-create/tcad/actions/runs/36668767301

**Evidence sha256:**
- targeted `e6e_tests_result.json` 2e34825d…
- gate log 5dda3833…
- mock log 92d6781d…
- regression `e6e_tests_result.json` 3de30c28…
- `run_regression.log` 784ec322…
- regression `summary.json` 5bcebee6…

**Sensitive scan:** no user path or token. User paths in logs appear as `<USERPROFILE>`.

## 9. Still unverified
- The effect of the second outer refinement pass is unknown. G2 could not be solved, and E6D's `NO_RESOLVABLE_NONCORE_CHANGE` applies to
  G1's single pass only.
- 2D mesh convergence is unverified. The `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` gate stays.
- PN-junction physical accuracy is not established by this gate.
- The ViennaPS `Mask` / `Si` NodeVolume non-conservation found by the regression is open, and so is its consequence for the 20 refused
  test paths.
