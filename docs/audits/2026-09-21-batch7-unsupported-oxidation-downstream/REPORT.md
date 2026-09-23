# Batch 7 -- unsupported positive-time oxidation: downstream contracts (three tests migrated)

Date: 2026-09-21. Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged or committed).
Changed: the three tests below and this folder. `tcad/**/*.py`, `tcad_2d_stagewise.py` and `CLAUDE.md`: NOT modified.

## 0. Points Codex should look at

1. **LOCOS reason code.** The prompt's production contract lists `LOCOS_CAPABILITY_PROOF_MISSING` for LOCOS and `OXIDATION_CAPABILITY_PROOF_MISSING` for thermal; the tests pin exactly that (the real runs return it). No mismatch this time.
2. **`import_process_result()` is not a gate.** It never reads `physics_status`/`state_transition` (observed in its source). The authorization is `canonical_node_doping()`/`apply_doping()` raising `UnsupportedDopingState`, reached through the GUI `run_measurement()`. The GUI still performs the geometry-only mesh/device import (1 call observed) before the gate blocks; nothing is written or solved and no device leaks. That import is reported, not asserted to be 0.
3. **`run_doping` after a refused LOCOS logs "DOPING APPLIED: UNIFORM ... net_doping_cm3=1e+16"** although the canonical state refuses it (`Accumulated dopant profile(s) on this wafer: 0`, canonical query stays `None`). Not asserted and not changed (out of scope); worth a look as a possible wording issue.
4. **Other callers of positive-time oxidation still exist** (Serena section): `test_physics_rules_real.py` (0.5 h x3), `test_phase13_process_flow_real.py`, `test_phase14_flow_devsim_real.py` (0.05 h), `test_ce2_oxidation_conversion_unsupported_real.py` (0.01 h), `examples/build_pn_diode.py` (0.3 h). Out of scope; they will need the same migration.

## 1. Start state

* HEAD `3ba9404...`, branch `claude/waferstate-v2`; 72 dirty entries (user-owned, untouched); whole-tree `git diff --check` rc=0; only editor/language-server helper processes running; the three tests were tracked and unmodified. `CLAUDE.md` was read in full before starting (its Serena-first policy is followed below).
* Production hashed before any edit (82 files, `raw/production_sha256_start.txt`); `CLAUDE.md` sha256 saved (`raw/claude_md_sha256_start.txt`).

## 2. Serena investigation (CLAUDE.md policy)

* Active project: `tcad` (python language server ready).
* Target symbols: `run_flow` (`flow.py:63-140`), `registry.get`/`register`/`_REGISTRY` (`registry.py`), `ProcessStep` (`base.py:86-282`), `build_process_result` (`viennaps_adapter.py:36-98`), `import_process_result` (`mesh_import.py:731-1228`), `canonical_node_doping` (`doping_mapping.py:109-316`), `apply_doping`, `UnsupportedDopingState`, `TCADApplication/run_measurement` (`tcad_2d_stagewise.py:5540-5796`), `run_dc_operating_point` (5985-6164).
* Findings: `run_flow` `break`s after the first `state_transition.kind == "unsupported"` result, before the next `registry.get` (so a later step is never looked up, constructed or run; its step directory is created at the top of the loop iteration, so none exists). `build_process_result` copies `physics_status` and `state_transition` into the `ProcessResult` unchanged. `import_process_result` contains none of `physics_status`, `state_transition`, `UNSUPPORTED`. `UnsupportedDopingState` is raised in `canonical_node_doping` (via `apply_doping`) and caught in `run_measurement` and `run_dc_operating_point`; CLI/pipeline and several unit tests use the same gate.
* Callers: `run_flow` -> `worker_main` (GUI), `examples/build_pn_diode.py`, and many tests (list in section 0.4 and `tests/integration/_explicit_chain_fixture.py`, `test_oxidation_positive_time_unsupported_real.py`). `apply_doping`/`UnsupportedDopingState` -> `run_measurement`, `run_dc_operating_point`, the CLI and the gate tests.
* Bypass/duplicate paths: none found that reach a solver or a doping write for an unsupported state; the geometry-only import before the gate is the one observed step (section 0.2).
* Symbols changed: the three test modules (their helpers and `main`); production symbols possibly affected but unchanged: all of the above.
* Agreement with direct inspection: the source read of `run_flow`, `build_process_result` and the observed GUI behaviour agree with Serena's symbol/reference results; no index mismatch; no fallback needed.
* Real evidence for the verdict: the real runs (traps, sentinel, observers, real GUI, real DevSim), the controls, static checks and `git diff --check` -- not Serena output.

## 3. Failures before the change (`raw/BEFORE_*.out.txt`)

| test | rc | time | first failure |
|---|---|---|---|
| `test_blanket_no_mask_real.py` | 1 | 0.7 s | `expected Si+SiO2 only, got {10: (-4.98, -0.017)}` -- only Si returned by the refused oxidation |
| `test_locos_chaining_real.py` | 1 | 0.6 s | `[1/8] LOCOS step's own export should have all 3 materials ... got [10]` |
| `test_locos_devsim_import_real.py` | 1 | 0.6 s | `expected all three materials present ... got ['Si']` |

Each demands an oxidation result from a request the backend refuses; none is a production regression.

## 4. Files and roles

| file | role now |
|---|---|
| `tests/integration/test_blanket_no_mask_real.py` | positive-time thermal (no mask / `mask_spans_um=[]` / masked) = fail-closed contract; supported blanket deposition kept and strengthened (own function) |
| `tests/integration/test_locos_chaining_real.py` | positive-time LOCOS: direct contract + real `run_flow` stops before a sentinel step; no manual chaining |
| `tests/integration/test_locos_devsim_import_real.py` | positive-time LOCOS -> `build_process_result` preserves the verdict -> real GUI measurement is blocked by the canonical gate (0 solve, 0 doping writes) |
| `docs/audits/2026-09-21-batch7-unsupported-oxidation-downstream/` | this report, `raw/`, `scripts/` (static checks and a read-only probe of the GUI measurement path) |

## 5. Wrong physical claims removed

* blanket: SiO2 growth and Si consumption from an oxidation request; the "oxide straddles y=0, contiguous with Si" coherence check; the "masked oxidation still builds a Mask" check (Mask/oxide were results of a run that no longer happens).
* chaining: LOCOS producing 3 materials with >=90 % mask retention; a chained directional etch, second etch and Bosch keeping 3 materials and removing oxide; fin-style oxidation growing oxide on a LOCOS domain; a second LOCOS refused on a modified domain; a second LOCOS chained onto the first growing oxide and consuming Si. All now documented as HISTORICAL results (including the 10 hr measurement SiO2 +0.17511 / Si -0.06407), not a contract.
* devsim: importing the LOCOS result as a Si/SiO2/Mask device with two Si contacts; mask retention > 90 %.
* Static check 2: none of `retention`, `mask_area`, `areas1..5`, `oxide_tag`, `si_top`, 0.9 ... remains in the code.

## 6. New fail-closed contract

Every positive-time request: result keys exactly `final_mesh, snapshots, physics_status, state_transition`; `state_transition == {"kind": "unsupported", "category": "oxidation", "reason": <code>}`; `physics_status.resolution == "UNSUPPORTED_BY_MODEL"`; `reason_code == state_transition.reason == <code>`; `measured_min_oxide_um is None`; status keys exactly the known set; fresh input -> returned materials exactly `['Si']` (no SiO2, no Mask). Codes: thermal `OXIDATION_CAPABILITY_PROOF_MISSING`, LOCOS `LOCOS_CAPABILITY_PROOF_MISSING`.

* blanket: three thermal requests (0.5 h; no mask keys; `mask_spans_um=[]` from `mask_spans_from_openings`; masked) all refused with `['Si']`; the first two return equal exported mesh arrays, reported as "the same fresh materialized virgin-Si geometry", never "the same oxidation result".
* chaining: 0.02 h LOCOS refused (direct); `run_flow([positive-time LOCOS, SENTINEL])` -> 1 result.
* devsim: 0.02 h LOCOS refused; `build_process_result()` keeps `physics_status` and `state_transition` equal to the step's, regions `['Si']`, `doping None`; real GUI: LOCOS request (0.1 h) -> `UNSUPPORTED_BY_MODEL / LOCOS_CAPABILITY_PROOF_MISSING`, `completed_steps 0`, canonical query `None`; doping + MEASURE -> blocked.

## 7. Solver-call-zero evidence

`SolverTrap` in every file replaces `vps.Process`, `vps.Oxidation` (construction and `setInitialOxideThickness`) and `LocosOxidation._build_locos_geometry` with recorders that also raise; `calibrate_trap()` calls each of the four directly first (all fire). Every positive-time request runs under it and `assert_not_entered` requires an empty list (this also catches a call swallowed by a broad `except`). Observed for every request in the blanket, chaining and devsim files (3 + 1 + 1 direct requests plus the flow): `{'vps.Process': 0, 'vps.Oxidation': 0, 'setInitialOxideThickness': 0, 'LocosOxidation._build_locos_geometry': 0}`. Inside the GUI worker subprocess a trap is not possible; that step rests on the GUI log/physics status ("1) No solver ran.") and on the in-process traps of the same entry point.

## 8. Flow sentinel

`SentinelStep(ProcessStep)` (category `sentinel_tripwire`, name `must_never_run`) is registered temporarily; its constructor and `run()` record and raise; `registry.get` is wrapped pass-through to record lookups; `calibrate_sentinel()` touches each directly and checks the registry is clean afterwards. `run_flow([LOCOS 0.02 h, SENTINEL])`: 1 result (transition `unsupported`, reason `LOCOS_CAPABILITY_PROOF_MISSING`), registry lookups exactly `[('oxidation', 'locos')]`, sentinel lookups/constructions/run() `{lookups: 0, constructed: 0, run: 0}`, step directories `['00_oxidation_locos']` only (no geometry for a second step), the first result's mesh `['Si']` described as last-known/fresh geometry, not post-LOCOS, and handed to nothing. No `inherited_domain=` and no `.last_domain` is used anywhere in the chaining/devsim tests (static check 3) -- an uncomputed LOCOS state is never replaced by an "unoxidized last-known domain".

## 9. DevSim write/solve zero evidence

Pass-through observers on the real `devsim.solve`, `devsim.node_model`/`set_node_values` (models `Donors`/`Acceptors`/`NetDoping`) and on `mesh_import.import_process_result`; calibrated on a fake module (counts solve, counts doping writes by model name, ignores `Potential`). Two real GUI variants after a refused LOCOS: (a) wafer materialized before the request (canonical cell `UNRESOLVED`, exact bounds, `si#substrate`), (b) no earlier state (`LEGACY_UNRESOLVED` cells). Each: `devsim.solve` calls 0; DevSim doping writes 0; currents reported 0; log has `UNSUPPORTED_BY_MODEL`, "N of N mesh node(s) blocked" (N=126) and "Measurement blocked: no doping was written to DevSim, no solve was run, and no current is reported."; `last_physics_status.resolution == UNSUPPORTED_BY_MODEL` with `blocked_nodes == total_nodes`; no "imported successfully"/"LOCOS device"/"device imported" text; canonical state object unchanged, query `None`, attachments 0; history unchanged; modal calls 0; leaked DevSim devices `[]`. Geometry-only import calls observed on the way to the gate: 1 per variant.

## 10. Supported blanket deposition (real geometry, `raw/AFTER_TARGET_test_blanket_no_mask_real.out.txt`)

Real isotropic SiO2 deposition (`deposition_time_s 1.0`, `rate 0.1`, grid 0.05) on a bare wafer, 7 sampled columns x = -1.5..1.5: materials `['Si', 'SiO2']`, no Mask; Si top 0.0002 um; DEPOSITED SiO2 film thickness 0.0998 um at 7/7 columns (bound: > 0.1 x grid = 0.005 um, the exporter's representation offset); film bottom equals Si top within 0.005; Si top within 0.005 of the bare surface. Stated as a deposited film, not an oxidation oxide. A masked deposition recipe (`mask_left/right`, `pr_thickness`) still yields a Mask (materials `['Mask', 'Si', 'SiO2']`), replacing the oxidation-based "masked path unchanged" check. The nominal rate x time is not used as an expectation.

## 11. False-green guards (`expect_fail`: a passing check is FALSE GREEN, another reason is WRONG FAILURE REASON)

Per file (8 / 7 / 10): thermal<->LOCOS reason swapped (`reason code is '...'`); transition kind `identity`; resolution `MODELLED`; SiO2 in the fresh result (`not the virgin Si wafer only: materials ['Si', 'SiO2']`); Mask in the fresh result; solver trap actually called with the call swallowed (`solver/oxidation path was entered: ['vps.Process']`). blanket adds: supported deposition with no film (`no SiO2 film was added`) and a film thinner than 0.1 x grid. chaining adds: `run_flow` executing the sentinel (`sentinel step was reached: {'lookups': 1, 'constructed': 1, 'run': 0}`). devsim adds: a DevSim doping write on the unsupported state (`1 DevSim doping write(s) on an unsupported state`), a `devsim.solve` (`devsim.solve was called 1 time(s)`), a log without `UNSUPPORTED_BY_MODEL`, and a log presenting the refusal as an imported device.

## 12. Target results (independent runs; `raw/AFTER_TARGET_*.out.txt`)

| test | rc | time | assertions that passed |
|---|---|---|---|
| `test_blanket_no_mask_real.py` | 0 | 4.4 s | 3 thermal requests unsupported/`OXIDATION_...`, 0 solver-path calls, `['Si']`, two meshes equal; supported deposition (film 0.0998 um at 7/7, no Mask); mask recipe keeps Mask; 8 guards |
| `test_locos_chaining_real.py` | 0 | 0.6 s | direct LOCOS unsupported/`LOCOS_...`, 0 calls, `['Si']`; `run_flow` 1 result, sentinel 0/0/0, no second directory; 7 guards |
| `test_locos_devsim_import_real.py` | 0 | 3.1 s | LOCOS unsupported, 0 calls; `build_process_result` preserves verdict; GUI x2: 0 solve, 0 doping writes, no current, `UNSUPPORTED_BY_MODEL` + node counts, state unchanged/None, 0 modal, no leak; 10 guards |

## 13. Controls (independent runs; `raw/AFTER_CONTROL_*.out.txt`)

| test | rc | time |
|---|---|---|
| `test_oxidation_positive_time_unsupported_real.py` | 0 | 29.6 s |
| `test_oxidation_zero_duration_identity_real.py` | 0 | 4.5 s |
| `test_waferstate_sequential_flow_real.py` (the supported sequential-flow control) | 0 | 18.5 s |
| `test_blanket_no_mask_real.py::test_blanket_deposition_supported` only (called on its own; materials `['Si','SiO2']`) | 0 | 2.2 s |
| `tests/unit/test_wafer_state_v2_devsim_mapping_gate_mock.py` | 0 | 0.4 s |
| `test_measurement_canonical_state_gate_real.py` | 0 | 2.8 s |

No full regression was run.

## 14. Production diff 0, `git diff --check`, HEAD

* Static checks (`scripts/static_checks.py`, ALL PASS; text/AST/file-time scans that do not prove behaviour): no skip/xfail/marks/broad `except`; old claim identifiers/literals absent; no `inherited_domain=`, no `.last_domain`, no `import_process_result()` call on the refused result; every `time_hours` > 0; four-path trap + calibration + exact reason code per file; every `expect_fail` has an expected reason; sentinel and observers present; deposition is a separate function; 82 production files unchanged; `CLAUDE.md` byte-identical; only the three allowed tests modified since the start (`.serena/cache` excluded).
* Whole-tree `git diff --check`: rc=0, no output. HEAD unchanged, 0 staged, 0 commits (`raw/repo_state_end.txt`).

## 15. Remaining limits

* The GUI worker subprocess cannot be trapped from the test process (section 7).
* The geometry-only DevSim mesh/device import still happens before the gate (1 call, observed, not asserted).
* Fresh vs materialized-first variants differ only in the canonical reason text (`LEGACY_UNRESOLVED` vs `UNRESOLVED`); both are fail-closed.
* Fresh-request equality of the two returned meshes is checked for the no-mask and `mask_spans_um=[]` requests only.
* Other positive-time oxidation callers remain (section 0.4).
