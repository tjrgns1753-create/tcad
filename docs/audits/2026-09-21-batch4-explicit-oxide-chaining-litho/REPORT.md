# Batch 4 -- explicit Si/SiO2 based process chaining + lithography lifecycle migration

Date: 2026-09-21. Branch `claude/waferstate-v2`. HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; no commit made).
Scope: two of the 17 contract-change migrations. No full regression was run. No production code was touched.

All numbers below are copied from the raw files in `raw/` (listed with SHA-256 in `raw/SHA256SUMS.txt`).

## Round 2 (evidence-rigour corrections; no physics assertion loosened, no tolerance widened, no production change)

Round 2 changed only the helper, the two target tests, this report and the audit scripts. Sections 6, 8, 9, 10, 11, 13 and 16 below are the
corrected versions. The five corrections:

1. **`assert_fails(check, label, expected)`**: the old form accepted ANY `AssertionError`. Now `expected` (a substring, a tuple of substrings that must all
   appear, or a predicate) is mandatory; a passing check is `FALSE GREEN`, a failing check with another reason is `WRONG FAILURE REASON`, any other
   exception type propagates. All 14 calls name their reason (section 10). Contract exercised on the real helper: `raw/ROUND2_assert_fails_contract.out.txt` (11 rows).
2. **Domain independence**: the helper now holds strong references to every domain it hands out, compares each new one with every held one using `is not`,
   and derives `copies_loaded` (ids, report only) from that list. One load per scenario is asserted by label (section 6).
3. **Native-vs-requested offset**: the earlier cause statement (a deliberate placement of the plane by ViennaLS) had no source. The installed wheels contain no C++ headers or
   sources, the stubs and docstrings say nothing about it, so the cause is `UNKNOWN_NUMERICAL_REPRESENTATION_OFFSET` and that wording is gone
   from the helper and this report (section 9).
4. **Oxide clearance wording**: replaced by the contract in section 8, with the real native residual array printed.
5. **Static checks** extended (section 13).

Code evidence for the defects as they were: `raw/ROUND2_BEFORE_evidence.out.txt` (an unrelated `AssertionError` was accepted as a passing sensitivity
check; recycled ids were NOT observed in 40 loads, so the id-only design is recorded as a structural weakness, not as an observed failure).

## 1. Start state

* HEAD `3ba9404...`, 64 dirty entries in `git status --short` (saved before any edit), tracked diff sha256
  `281494393609e8447081eff98dbc1fbd6d753d2b25b70ecb2c2db6dd016687fb`, 1344 untracked-not-ignored files (saved list).
* 82 production files (`tcad/**/*.py` + `tcad_2d_stagewise.py`) hashed before any edit: `raw/production_sha256_before.txt`.
* The two target tests were the pre-batch versions (working copies CRLF, index/HEAD LF).

## 2. Pre-change reproductions (real ViennaPS 4.6.2, before any edit)

* `test_gui_process_state_chaining_real.py` -- rc=1 at its first assertion:
  `AssertionError: blanket oxidation produced unexpected materials: {'Si': (-3.967, 3.967, -3.967, -0.033)}`.
  Its step 0 was a positive-time thermal oxidation, which is now `UNSUPPORTED_BY_MODEL`
  (`OXIDATION_CAPABILITY_PROOF_MISSING`), so no SiO2 was created. (`raw/BEFORE_test_gui_process_state_chaining_real.out.txt`)
* `test_litho_lifecycle_state_real.py` -- A, A2, B1 pass; B2 fails with `IndexError: list index out of range` at
  `results[1].volume_mesh_path` (the flow stopped after the first, unsupported, oxidation: one result of two). (`raw/BEFORE_test_litho_lifecycle_state_real.out.txt`)

Both failures are the contract change (no oxide can be grown), not a regression of the behaviour the tests are for.

## 3. Changed files and roles

| file | change | role |
|---|---|---|
| `tests/integration/test_gui_process_state_chaining_real.py` | rewritten (205 -> 285 lines, +255/-175) | chaining test on an explicit Si/SiO2 stack |
| `tests/integration/test_litho_lifecycle_state_real.py` | edited (597 -> 631 lines, +319/-285) | A, A2, B1 source unchanged (verified per function by AST comparison, `raw/code_change_evidence.txt`); B2, B3, C and `main` rewritten; sensitivity test added |
| `tests/integration/_explicit_chain_fixture.py` | NEW, test-only helper | build/save/reload the explicit stack, native and exported column measurement, solver-call counting, tolerance definitions (section 9 states each one's basis and limits) |
| `docs/audits/2026-09-21-batch4-explicit-oxide-chaining-litho/**` | NEW | this report, raw outputs, two scripts |

Not modified (byte-identical to the pre-batch copies): `tests/integration/_explicit_oxide_fixture.py`,
`_explicit_etch_fixture.py` (Batch 1/2 frozen helpers), every `tcad/**/*.py`, `tcad_2d_stagewise.py`.
The Batch 1 helper's `build_explicit_si_sio2_stack` never saves nor returns the domain, so a new additive helper was used instead of editing the frozen one;
it reuses only the frozen helper's public API (`forbid_oxidation_and_process`, `measure_exported_mesh`, `PROVENANCE`).
The two edited tests and the helper are LF. (The two edited tests had CRLF working copies; under the clean git environment
CRLF makes `git diff --check` report trailing whitespace, so they were normalised to LF, the same as index/HEAD.)

## 4. Explicit initial geometry: provenance, creation, save, load

* Provenance label: `DIRECT_EXPLICIT_GEOMETRY`. Printed with every fixture. It is an input structure, never called a process result, an oxidation result or grown oxide.
* Creation: `MakePlane(...)` Si, then `MakePlane(..., addToExisting=True)` SiO2, built under the Batch 1 traps so
  `vps.Oxidation()` and `vps.Process()` cannot be called during the build. The helper requires the requested oxide top >= 2 grid cells.
* Saved with `session.save_domain_state` to a `.vpsd`; SHA-256 recorded. Every scenario reloads an independent domain via
  `session.load_domain_state`; `load_independent_copy()` re-checks the SHA and refuses to hand the same domain object out twice.
* Requested vs native vs exported kept apart (see section 9). The exporter representation offset (0.005 x grid on the initial stack) is reported and never read as oxide growth or Si consumption.

| test | grid (um) | requested Si surface / oxide top / floor (um) | initial `.vpsd` sha256 (first 16) |
|---|---|---|---|
| chaining | 0.1 | 0 / 0.4 / -4.0 | `791fc2629cfa48f5` |
| litho | 0.05 | 0 / 0.2 / -5.0 | `d2e89a59c738f4d6` |

## 5. Oxidation / Process call counts

Counting uses pass-through wrappers on `module.Oxidation` / `module.Process` (calls counted per run, nothing globally blocked in the flow); the fixture build runs under the blocking traps.

| what | `vps.Oxidation` | `vps.Process` |
|---|---|---|
| fixture build (both tests) | 0 | 0 |
| chaining flow (deposition + etch) | 0 | exactly 2 |
| litho C, zero-duration thermal step alone | 0 | 0 (transition `identity`) |
| litho C, whole flow (thermal-0 + etch + deposition) | 0 | exactly 2 (the etch and the deposition only) |

## 6. Initial `.vpsd` SHA-256 and independent copies

The helper keeps a STRONG reference to every domain object it hands out (`ExplicitChainState._domains`), so no object is freed while the test runs and
`id()` is unique among live objects. Each `load_independent_copy(label)` re-checks the `.vpsd` SHA-256, loads the file again (nothing is copied in memory, so no solver
or domain state is shared), and asserts `domain is not previous` for every held domain. `copies_loaded` is a read-only property that derives the ids from the held list.
`assert_independent_loads(expected_labels)` asserts the loads performed equal the scenarios run (one load per scenario, labels unique), all held domains are pairwise
`is not`, and the file SHA-256 is unchanged.

* Chaining: 7 loads `['check_initial', 'main', 'partial', 'fresh_copy', 'metal_rate_0', 'sio2_rate', 'si_and_sio2_rate']`, 7 distinct held domain objects, file sha256
  still `791fc2629cfa48f5...`, a fresh copy's native state equals the initial state. (The no-oxide state has its own file and its own single load.)
* Litho sensitivity: 6 loads `['s_blanket', 's_devel', 's_c_good', 's_c_si', 's_c_inert', 'fresh_copy']`, 6 distinct held domain objects from one `.vpsd`
  (sha256 `d2e89a59c738f4d6...`), file unchanged, a fresh copy still equals the initial state; the no-oxide state has exactly one load `['s_no_oxide']`.

## 7. Chaining test result (explicit Si/SiO2 -> deposition -> etching -> doping), rc=0, 2.4 s

* [0] initial state is exactly Si + SiO2, no Mask.
* [1] unmasked isotropic Metal deposition (rate 0.15, 1.0 s): materials `['Metal','Si','SiO2']`, no Mask, Metal native thickness 0.15 at all 9 columns, Si and SiO2 native level sets unchanged, exported geometry within a tenth of a cell.
* [2] etch with `material_rates` Metal -1.0, Si 0, SiO2 0, default 0: Metal removed, Si/SiO2 preserved, no Mask. A partial 0.06 s etch thins Metal 0.15 -> 0.09 (= |rate| x time to within one cell).
* [3] uniform doping attaches to region `Si` of the final real mesh; material geometry and mesh-file hash unchanged (state attachment only -- no kinetics/activation claim).
* [4] independence as in section 6.
* Nothing in the flow creates oxide; the recipes contain no `time_hours` at all.

## 8. Lithography results (rc=0, 17.4 s)

* A (resist decision table), A2 (a new coat starts an unpatterned cycle), B1 (first deposition with no lithography: materials `['Si','SiO2']`, film spans x=[-5,5], no Mask) -- source unchanged, pass.
* B2 (explicit stack -> PR COAT only -> deposition): materials `['Mask','Si','SiO2']`; resist present at all 13 sample columns (x=-5..5), no Si3N4 reached the wafer; resist native thickness 1.0 um on the oxide; Si/SiO2 native unchanged, exported within 0.0050 um.
* B3 (coat + develop -> deposition): resist opened over x=(-1.5,1.5); measured film confined to x=[-1.4995, 1.4995]; resist present at 8/13 columns, all outside the opening.
* C (explicit Si/SiO2 -> zero-duration thermal step -> selective oxide etch through the developed window -> unmasked deposition -> doping):
  * zero-duration thermal on the inherited domain returns `{'kind':'identity','reason':'zero_duration_oxidation','category':'oxidation','inherited':True}`; no solver call; the flow proceeds to the next step; Si/SiO2 native and exported geometry identical.
  * etch, contract (identical wording in the test, its printed output and here): **SiO2 is absent from the exported mesh at the sampled opening columns, and the native
    residual SiO2 thickness there is at or below the declared model-resolution bound (0.1 x grid = 0.005 um).** At the 5 sampled opening columns
    x = [-1.4, -1.125, 0, 1.125, 1.4] the measured native residual (SiO2 level-set top minus Si level-set top, same column) is `[0. 0. 0. 0. 0.]` um against the bound 0.005 um;
    the contract is a clearance to the resolution of this model, even though the measured values happen to be exactly 0. The Si level set is unmoved (rate 0),
    and SiO2 is preserved at the 6 protected columns. The protected columns are derived from the physics (isotropic lateral undercut ~ |rate| x time under the resist:
    |x| > opening_half + |rate|*time + grid), not chosen to make the test pass. Resist only where the mask is opaque.
  * deposition: blanket Si3N4 at all 13 columns; materials `['Mask','Si','Si3N4','SiO2']`; earlier materials neither resurrected nor removed.
  * PR strip: state only. The resist already meshed by the etch step stays -- the known limitation (CLAUDE.md, OPEN minor threads) is asserted, not hidden.
  * doping: attached to `Si` of the final mesh, geometry unchanged.

## 9. Requested vs native vs exported (measured, `raw/tolerance_basis.out.txt`)

| quantity | grid 0.1 (x 8) | grid 0.05 (x 10) | grid 0.1 (x 10) |
|---|---|---|---|
| requested oxide top (um) | 0.4 | 0.2 | 0.4 |
| native - requested (um) | 1e-13 (= 1e-12 x grid) | 5e-14 (= 1e-12 x grid) | 1e-13 (= 1e-12 x grid) |
| worst native drift after later steps | 0 | 0 | 0 |
| exporter offset of the initial stack (exported Si top - native) | 4.975e-4 (0.0050 x grid) | 2.488e-4 (0.0050 x grid) | 4.975e-4 (0.0050 x grid) |
| worst exported drift after later steps | 0.0050 x grid | 0.0099 x grid | 0.0099 x grid |
| exported_tolerance (0.1 x grid) headroom | x20.1 | x10.1 | x10.1 |

**Native-vs-requested offset: cause `UNKNOWN_NUMERICAL_REPRESENTATION_OFFSET`.** Search for a documented mechanism (round 2): the installed
`viennals 5.8.5` / `viennaps 4.6.2` wheels (`..\.venv\Lib\site-packages`) contain only compiled modules and `.pyi` stubs -- no C++ headers or sources, and no other
local Vienna source tree was found on the machine (searched the project tree, Documents, Downloads, Program Files for `lsMakeGeometry.hpp`: none). The stubs give
`MakePlane(domain, height, material, addToExisting)` a one-line docstring with no numerical statement; the only `eps=1e-12` default in the stubs belongs to the
surface-mesh readers `ToSurfaceMesh` / `ToMultiSurfaceMesh` (`minNodeDistFactor=0.05, eps=1e-12`) and has no documentation of its role. **No direct evidence
for a mechanism was found**, so none is asserted.

Pre-registered matrix (`scripts/measure_native_request_offset.py`, rule and case list fixed before the first run; `raw/native_request_offset_matrix.out.txt`):
14 cases = grid {0.2, 0.1, 0.05, 0.025} um x requested oxide top {0.2, 0.25, 0.4, 0.6} um (only tops >= 2 grid cells; x extent 8, y extent 5, 9 columns).
Observed `max |native - requested|` = 1.0e-12 x grid in every case (0.1 um grid: 1e-13; 0.05: 5e-14; 0.025: 2.5e-14; 0.2: 2e-13; top 0.25 on the 0.1 grid: SiO2 0, Si 1e-13);
all 14 cases WITHIN the bound `1e-11 x grid`; none outside. A separate observation on grid 0.1 / top 0.4 with the reader `vls.ToSurfaceMesh(..., eps)`:
offset 1.1e-16 / 1e-13 / 1e-10 um for eps = 1e-15 / 1e-12 (default, used by the tests) / 1e-9 -- it changed with the reader's `eps` (following eps x grid in those
three cases). This is an observation about the reading path only; it does not show whether the stored level set is itself offset, and no document says what `eps` does.

| tolerance | basis of the definition | observed | verified range | outside the range |
|---|---|---|---|---|
| `native_eps` (native vs native) | 16 float64 ulps x max(scale,1): bound on double-precision rounding of the same level set read twice (the 16 is a chosen margin, not measured) | drift exactly 0 in all scenarios | the 3 scenarios of `raw/tolerance_basis.out.txt` | UNKNOWN |
| `native_request_tolerance` (native vs REQUESTED) | OBSERVATIONAL: 1e-11 x grid = the observed offset with a factor-10 margin; not derived from a mechanism (cause unknown) | 1.0e-12 x grid (1e-13 at grid 0.1) | the 14-case matrix above (grid 0.025-0.2 um, top 0.2-0.6 um, x 8, y 5) and the two tests' stacks | UNKNOWN; not widened to fit a result, must be measured first |
| `exported_tolerance` (exported vs exported) | 0.1 x grid: the bound these tests already carried before the migration (kept, not retuned) | exporter drift 0.0050-0.0099 x grid (headroom x10-x20); exporter offset of the initial stack 0.0050 x grid | grids 0.05 and 0.1 um, the chaining and litho stacks and their later steps | UNKNOWN for other grids/topologies |
| `geometry_eps` (float32 points) | 4 ulps of float32 spacing at the largest coordinate: a serialization bound | not separately measured | only used to compare a resist bottom with an oxide top in the same exported mesh | UNKNOWN |

Static check 4 confirms no numeric literal other than 0/1/2/3 is compared against a measurement in anything this batch wrote. Note the memory-recorded project rule that
tolerances should be derived from a mechanism: `native_request_tolerance` cannot be, because the mechanism is unknown -- that limit is stated rather than hidden.

## 10. Sensitivity (false-green) results -- every guard fails when its subject is broken

Every one of the 14 calls is `assert_fails(check, label, expected)`; the sensitivity check passes only if the check fails with an `AssertionError` whose message
matches `expected` (all substrings of a tuple must appear; a predicate is used where an absence must be shown). Observed: all 14 "fails for the expected reason"
(`raw/ROUND2_AFTER_*.out.txt`); the contract itself (FALSE GREEN, WRONG FAILURE REASON, other exception types propagating, 2-argument form rejected) is exercised in
`raw/ROUND2_assert_fails_contract.out.txt`, 11 rows PASS.

| # | test | scenario | expected reason (must match) |
|---|---|---|---|
| 1 | chaining | initial oxide missing, initial-state check | `the initial state must be exactly Si + SiO2` and `exported ['Si']` |
| 2 | chaining | initial oxide missing, preservation | `no-oxide chain: SiO2 vanished` |
| 3 | chaining | Metal etch rate 0, thinning | `the etch did not thin the Metal at every column` |
| 4 | chaining | Metal etch rate 0, rate contract | `the Metal rate must be negative` |
| 5 | chaining | SiO2 rate -1.0 | `SiO2-rate chain: SiO2 vanished` |
| 6 | chaining | SiO2 and Si rates -1.0 | `Si+SiO2-rate chain: native Si level set moved by` |
| 7 | chaining | Si rate -1.0, rate contract | `Si / SiO2 / default rates must be exactly 0` |
| 8 | litho | blanket span -> patterned span, B2 pattern | `B2 pattern with a patterned span: blanket resist missing at x=` and `the coat was applied as a DEVELOPED pattern` |
| 9 | litho | blanket span -> patterned span, B2 full check | `B2 with a patterned span: unexpected materials` and `'Si3N4'` (film went through the opening) |
| 10 | litho | developed span -> blanket span, B3 pattern | `B3 pattern with a blanket span: developed resist still covers the opening at x=` and `develop did not open the pattern` |
| 11 | litho | developed span -> blanket span, B3 full check | predicate: `B3 with a blanket span: unexpected materials` present and `'Si3N4'` absent |
| 12 | litho | initial oxide missing, B2 | predicate: `B2 without the initial oxide: unexpected materials` present and `'SiO2'` absent |
| 13 | litho | Si rate -0.2 in C | `C with a nonzero Si rate after the etch: native Si level set moved by` |
| 14 | litho | SiO2 rate 0 in C | `C with a zero SiO2 rate: SiO2 is present in the exported mesh at sampled opening columns` |

Note recorded in the test: a nonzero Si rate alone is physically inert while SiO2 covers the Si everywhere, so it is guarded by the rate contract and, once SiO2 is also etched, by the geometry check.
Plus the independence assertion of section 6 in each test.

## 11. Target test results (independent runs, `PYTHONIOENCODING=utf-8`, `..\.venv\Scripts\python.exe`)

| test | rc | elapsed |
|---|---|---|
| `test_gui_process_state_chaining_real.py` | 0 | 2.3 s |
| `test_litho_lifecycle_state_real.py` | 0 | 17.2 s |

(Round 2 re-run after all edits: `raw/ROUND2_target_runs.txt`, outputs `raw/ROUND2_AFTER_*.out.txt`. Round 1 values were 2.4 s and 17.4 s. The control tests below
are round-1 runs and were NOT re-run in round 2; round 2 changed only the helper, the two target tests and audit files, none of which the controls import.)

## 12. Control test results (independent runs)

| test | rc | elapsed |
|---|---|---|
| `tests/unit/test_gui_litho_lifecycle_mock.py` | 0 | 0.9 s |
| `test_cad_negative_validation_real.py` | 0 | 0.7 s |
| `test_pin_placement_validation_real.py` | 0 | 0.6 s |
| `test_oxidation_pr_etch_reaches_si_real.py` | 0 | 8.9 s |
| `test_etch_selectivity_real.py` | 0 | 9.8 s |
| `tests/unit/test_etch_material_summary_mock.py` | 0 (42/42) | 1.6 s |
| `test_oxidation_zero_duration_identity_real.py` | 0 | 5.3 s |
| `test_oxidation_positive_time_unsupported_real.py` | 0 | 34 s |
| `test_waferstate_sequential_flow_real.py` | 0 | 20.5 s |

Raw outputs: `raw/AFTER_*.out.txt`. This is not a full regression; no claim is made about the rest of the suite.

## 13. Production diff 0 evidence

* `scripts/static_checks.py` check 6: 82 production files hashed before; changed=[], missing=[], new=[]. (`raw/static_checks.out.txt`, "ALL STATIC CHECKS PASS", rc=0.)
* `raw/repo_state_end.txt`: entries in `git status` under `tcad/` and `tcad_2d_stagewise.py` changed vs the start: 0. New untracked (not ignored): the helper file and this audit directory only. Tracked modifications added by this batch: the two target tests only.
* Static checks 1-5 (what each proves and does not prove is in the script docstring; none proves physical correctness -- the real-ViennaPS runs do): only zero-duration `time_hours` present; no phrase naming the explicit oxide a grown/oxidation result without negation; no oxide-thickness subtraction/seed compensation; no magic tolerance literal; no code constructing or overwriting a state transition (the tests only read and assert it).
* Round-2 static checks 7-10 (text/AST scans only; they state what is written in the files, not that the physics is right): every `assert_fails()` call has three arguments and no 2-argument call remains (14 calls found); the helper signature is `(check, label, expected)`; `copies_loaded` is a read-only property and nothing stores integer ids in it, new domains are compared with `is not` against held objects; none of the earlier unsupported cause wording for the native-vs-requested offset (a fixed list of phrases, kept in the script) and none of the earlier unconditional opening-clearance wording (also a fixed list in the script) appears in the helper, the two tests or this report. Check 6 (production hash) is re-run: 82 files, changed/missing/new all empty. Output: `raw/static_checks.out.txt` (overwritten by the round-2 run).

## 14. `git diff --check`

Run in a clean git config environment (`GIT_CONFIG_GLOBAL=NUL`, `GIT_CONFIG_SYSTEM=NUL`) at the end of the batch: output empty, exit code 0
(re-checked after this report was written; literal result recorded in the submission message).

## 15. HEAD / commit

`git rev-parse HEAD` = `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, branch `claude/waferstate-v2`; commits since the start: 0. Nothing was staged or committed.

## 16. Remaining UNKNOWN / limits

* The explicit initial stack proves only that later steps preserve/alter what they should; it says nothing about how oxide grows (still `UNSUPPORTED_BY_MODEL`).
* PR strip after an etch leaves the already-meshed resist in the geometry: known limitation, asserted as such, not fixed here (production is out of scope).
* Exported-vs-exported tolerance `0.1 x grid` is a pre-existing bound, verified only to have 10-20x headroom over measured exporter drift at grids 0.05 and 0.1 and these two geometries; other grids/topologies were not measured.
* The native-vs-requested offset (1.0e-12 x grid) has an UNKNOWN cause (`UNKNOWN_NUMERICAL_REPRESENTATION_OFFSET`); its bound is observational and verified only over the 14-case matrix (grid 0.025-0.2 um, oxide top 0.2-0.6 um). It followed the reader's `eps` in three cases, which was not investigated further (no sources available).
* Domain identity is judged by object identity over held references; a recycled `id()` was not observed in 40 loads, so the id-only weakness was structural, not a seen failure.
* The oxide-clearance contract is a statement at the sampled opening columns and to the declared 0.1 x grid resolution, not a continuum claim.
* The isotropic-undercut protected-column rule in C is derived from measured behaviour of this etch model at rate -0.2, time 1.5 s, and is not a general lateral-etch law.
* Doping steps here assert state attachment only; nothing claims dopant kinetics or activation.
* The remaining contract-change migrations, the full regression and the commit are not part of this batch and were not started.
