# TCAD 2D Project

## Goal
Build a reliable 2D TCAD process → mesh → DevSim device simulation pipeline.

- 2D only. Do not expand to 3D.
- Prioritize physical correctness over feature count.
- Use actual ViennaPS 4.6.2 / DevSim execution for validation.

## Development Rules

- Investigate before modifying production code.
- For suspected problems, first make the smallest experiment that distinguishes hypotheses.
- Never change code just to make a test pass.
- Preserve existing regression tests.
- Do not refactor unrelated code.
- Report uncertainty honestly.
- Work slowly and one subsystem at a time.

Preferred order:
1. Initial wafer geometry
2. Mask representation
3. Oxidation
4. Etching
5. Isotropic etch
6. Bosch / scalloping
7. Physical benchmarks
8. DevSim electrical validation

## Architecture

Process flow:

Process → ViennaPS → ProcessResult → DevSim → device simulation

Process continuity uses explicit instance state:
`ProcessStep(inherited_domain=...)`

Do NOT introduce global/module-level process state.

## Completed

### Phase 13
Process flow continuity verified with real ViennaPS 4.6.2.

Multi-step flows successfully inherit previous geometry.

### Phase 14
ProcessResult → DevSim verified.

Examples:
- oxidation → DevSim mesh
- oxidation → doping → DevSim
- oxidation → MOS C-V
- oxidation → etch → doping → DevSim

**Historical baseline (pre-session, before any work in "Current Physical
Investigation" below):**
Phase 1–14 regression: `12 passed, 0 failed, 0 skipped`.
For the current, up-to-date regression status (after this session's
fixes), see "FINAL regression" under "Initial geometry / MakeTrench"
below — it is no longer 12/0/0 (two known, root-caused failures exist:
Phase 4 LOCOS, Phase 8 PN junction).

## Current Physical Investigation

### Initial geometry / MakeTrench

Current models use `MakeTrench`.

Important discovery:
`trenchDepth` is NOT equivalent to physical substrate thickness.

Some geometries produce Si thickness ≈ `2 × gridDelta` because of the level-set / narrow-band geometry representation.

Observed example:
- gridDelta 0.05 → Si ≈ 0.10 um
- gridDelta 0.02 → Si ≈ 0.04 um
- gridDelta 0.01 → Si ≈ 0.02 um

The trench/opening region can therefore contain almost no physical Si.

Do NOT assume increasing `trenchDepth` alone fixes this.

**Root cause confirmed (raw ViennaLS/ViennaPS API experiments, isolated from project code):**
`MakeTrench`'s own level-set geometry is NOT the cause — raw level-set
(`viennals.ToSurfaceMesh`) extent is independent of gridDelta. The
`2 × gridDelta` clipping happens specifically in `Domain.saveVolumeMesh()`
(`viennals::WriteVisualizationMesh`). For the `INFINITE_BOUNDARY` direction
(y in 2D), `WriteVisualizationMesh::LS2RectiLinearGrid` bounds its
extraction grid by the level set's own explicit narrow-band run breaks
(`getMinRunBreak`/`getMaxRunBreak`), not by any physical substrate-depth
setting — so a semi-infinite Si region is only ever meshed out to
`levelSetWidth × gridDelta` (default width 2). ViennaLS's own header
comment states this class "should ONLY BE USED FOR VISUALIZATION." This
project's DevSim import path (`tcad/mesh/viennaps_adapter.py`,
`tcad/device/devsim/mesh_import.py`) uses exactly this function as its
data source, which is architecturally the wrong tool for a
dimensionally-accurate device mesh.

**Conclusion: `MakeTrench` → `MakePlane` is NOT indicated.** Both build
the same kind of semi-infinite Si half-plane and would hit the identical
`saveVolumeMesh()` clipping.

#### Solution found, VERIFIED, and APPLIED TO PRODUCTION (this session)

**VERIFIED FACTS (each measured, not inferred):**

1. **Alternative export APIs do NOT solve it.** `viennals::ToVoxelMesh`
   computes its bounds with the same
   `isNegBoundaryInfinite(i) ? getMinRunBreak(i) : getMinBounds(i)`
   pattern, so it inherits the identical narrow-band limit. (Read from
   `lsToVoxelMesh.hpp::calculateBounds`.)

2. **`ToHullMesh::setBottomExtension` is the official 2D bounding
   mechanism, but produces line segments, not triangles.** It is
   explicitly 2D-only (logs a warning and ignores the value in 3D) and
   is used by the official `boschProcessRayTracing.py`
   (`geometry.saveHullMesh(f"run_{2*i}", 0.05)`). `Domain.saveHullMesh(
   filename, bottomExtension, sharpCorners)` is exposed in Python. Since
   a 2D hull is a closed boundary outline, using it for DevSim would
   require an external triangulation step — not a drop-in replacement.

3. **Making the y direction non-infinite is NOT reachable from the
   Python API.** `WriteVisualizationMesh` only narrow-band-clips
   directions whose boundary condition is `INFINITE_BOUNDARY` (the
   else-branch uses full grid bounds), so a non-infinite y would avoid
   the bug — but `DomainSetup(gridDelta, xExtent, yExtent, boundary)`
   hardcodes `boundaryCons_[D-1] = INFINITE_BOUNDARY` (the `boundary`
   argument applies only to directions 0..D-2), and the
   `DomainSetup(bounds[], boundaryCons[], gridDelta)` overload that would
   allow it is not bound in Python. The
   `vps.Domain(bounds, bcs, gridDelta)` overload IS bound but produces an
   uninitialized/garbage bounding box and then hangs `MakeTrench` —
   tested directly, do not use it.

4. **WORKING SOLUTION — give the level sets an explicit floor by
   boolean-intersecting each one with a bounding box, immediately before
   mesh export.** No geometry-construction API changes (`MakeTrench`
   stays), no `MakePlane`, applied as a post-processing step:
   ```python
   for ls in domain.getLevelSets():
       box = vls.Domain(ls)                      # inherits grid/bounds/BCs
       vls.MakeGeometry(box, vls.Box([x0, floor_y, 0.0],
                                     [x1, ceil_y, 0.0])).apply()
       vls.BooleanOperation(ls, box,
                            vls.BooleanOperationEnum.INTERSECT).apply()
   ```
   Verified results (Si region measured from the written `.vtu` via
   meshio, floor at y = -1.0, domain width 2.0, so expected Si area
   = 2.0 um²):

   | gridDelta | Si y-span before | Si y-span after | Si area after | area error |
   |---|---|---|---|---|
   | 0.05 | 0.10 (2×gd) | **1.00000** | 1.99920 | −0.040% |
   | 0.02 | 0.04 (2×gd) | **1.00000** | 1.99970 | −0.015% |
   | 0.01 | 0.02 (2×gd) | **1.00000** | 1.99882 | −0.059% |

   The Si span is now exactly the requested floor depth and **identical
   at every gridDelta** — the `2 × gridDelta` dependence is gone. Area
   was checked (not just bounding-box extent) to confirm the region is
   genuinely filled with triangles (1604 triangles at gridDelta 0.05),
   not a thin band with a tall bounding box.

   Also verified: surface geometry is preserved (mask top still 0.4999,
   mask area unchanged, Si top still y=0, mask window still cut); the
   step still works when applied *after* a real process step (isotropic
   etch: Si area correctly drops 1.99920 → 1.87768 while the floor holds
   at exactly −1.0); and **DevSim imports the result successfully**
   (`create_gmsh_mesh` → `add_gmsh_region` → `finalize_mesh` →
   `create_device` all succeed, giving regions `('Mask', 'Si')` with 865
   Si nodes / 1604 Si triangles).

**FOLLOW-UP VERIFICATION — multi-layer stress test (this session, still
isolated probes, no production code changed):**

5. **Flooring only the Si level set is WRONG — confirmed by direct
   comparison, not assumed.** Built Si+SiO2+Mask (real oxidation product)
   and ran the floor step two ways: (a) intersect every level set with
   the bounding box, (b) intersect only the level set tagged `Si`. Result
   (gridDelta=0.05, measured from the written `.vtu`):

   | material | floor-ALL area | floor-Si-only area | floor-Si-only y-range |
   |---|---|---|---|
   | Mask | 0.63717 | 0.63717 (identical) | unaffected either way |
   | SiO2 | 0.32103 | **0.42053 (+31% error)** | **[-1.0500, 0.5832]** — SiO2 itself extends down to the floor depth when left unfloored |
   | Si | 1.98569 | 1.98619 (~0.03% diff, noise) | floored correctly either way |

   Root cause: ViennaPS's material-stacking level-set representation
   means a non-topmost material's own level set (SiO2 here, sandwiched
   between Mask and Si) is *also* an implicit wrap around everything
   below it, so it inherits the exact same semi-infinite/narrow-band
   `saveVolumeMesh()` clipping the original Si investigation found — not
   just the literal substrate material. **Conclusion: every level set in
   the domain must be floored, not just Si.** This settles the earlier
   open question in favor of "floor ALL."

6. **Multi-layer stacks verified directly, not just Si/Mask:**
   - **Si + SiO2 + Mask** (real `vps.Oxidation()` run, t=0.1hr, both
     gridDelta 0.05 and 0.02): Si span stays exactly at the floor depth
     at both resolutions (span/gridDelta = 20.0 and 50.0 respectively,
     i.e. constant 1.0um span); SiO2 stays correctly bounded near the
     real oxide (no floor artifact, since it never reaches the floor
     once properly floored itself per point 5).
   - **Si + Polymer + Mask** (real `SingleParticleProcess` deposition
     via `duplicateTopLevelSet(Polymer)`, the same call pattern
     `bosch_drie.py` uses — first attempt at this test forgot that call
     and silently grew the wrong level set, a reminder that skipping it
     produces no error, just wrong material assignment): Polymer area
     ~0.235–0.242 at both gridDeltas (correctly gridDelta-independent,
     naturally bounded, unaffected by flooring), Si properly floored at
     both resolutions.
   - **Bosch mid-cycle, right after passivation** (the topologically
     hardest case — Polymer conformally wraps sidewalls + trench floor
     + mask top, not a flat layer): floor applied only as the very last
     step, after the real passivation `Process()` call, never mid-process.
     Polymer geometry came through intact (124 triangles, thin conformal
     coat, y-range unchanged from the pre-floor raw level-set reading:
     [-0.0284, 0.5305] vs [-0.0146, 0.5305] before — the tiny difference
     at the bottom is real: it's the coat over the *already-etched* floor
     dip from the initial pre-cycle etch, not floor damage). Si
     correctly extended to the floor depth.

(Point 7 — wiring `Wafer.silicon_depth_um` all the way through to this
parameter — happened later in this session, chronologically *after* the
production fix and regression immediately below. See "Floor depth wiring"
and "FINAL regression" further down this subsection for that step, kept
in its own place so this list stays in the order things actually
happened.)

**PRODUCTION FIX APPLIED (this session) — floor mechanism in
`tcad/backends/viennaps/io.py`:**

`save_volume_mesh(domain, path, floor_depth_um=DEFAULT_FLOOR_DEPTH_UM)` now
builds a **deep copy** of `domain` (`domain.__class__(domain)` — ViennaPS's
own copy constructor) via a new `_floored_copy_for_export()` helper, floors
every level set of the copy (box bounds auto-derived from
`domain.getBoundingBox()` + a safety margin, never hardcoded), and exports
only that copy. `domain` itself is never mutated — verified directly: the
original domain's raw level-set signature is bit-identical before/after.
`floor_depth_um` defaults to `5.0`. At this point in the session, all 13
existing call sites (`final_mesh_path = save_volume_mesh(geometry,
final_mesh)`) needed zero changes, since the new parameter was
keyword-defaulted — **this was true only until the "Floor depth wiring"
step further below, which did later edit all 13 of those call sites for
an unrelated reason (sourcing the value from the recipe, not adding the
parameter).**

**Regression, run through the real production path (`registry.get(...).run()`),
all against the actually-written `.vtu` via meshio:**
- Si+Mask (directional etch), gridDelta 0.05 and 0.02: Si span pinned at
  exactly `floor_depth_um` (4.9998/4.9999 um) at both resolutions — the
  `2×gridDelta` dependence is gone in the real pipeline, not just probes.
- Si+SiO2+Mask (thermal oxidation): Si floored, SiO2 stays correctly
  bounded near the real oxide (not floor-extended).
- Si+Polymer+Mask / Bosch mid-cycle (`bosch_drie.py`, both a full 1-cycle
  run and a hand-stepped mid-passivation snapshot): Polymer preserved,
  Si floored.
- Isotropic etch: Si floored.
- DevSim import of the floored mesh: succeeds
  (`create_gmsh_mesh`→`add_gmsh_region`→`finalize_mesh`→`create_device`,
  regions `['Mask','Si']`).

**Phase 1-14 regression suite re-run after the fix:**
- Phase 2, 3, 13 (real ViennaPS, exercise `save_volume_mesh` heavily): PASS.
- Phase 1 (`tests/unit/test_phase1_bosch_mock.py`, no real backend): a real
  fix regression — `FakeDomain` only ever modeled the old, narrow API
  (`duplicateTopLevelSet`/`removeTopLevelSet`/`removeStrayPoints`/
  `saveSurfaceMesh`/`saveVolumeMesh`), and the floor step needs
  `getGridDelta()`, `getBoundingBox()`, `getLevelSets()`, and a deep-copy
  constructor. Fixed by extending `FakeDomain` with exactly those four
  (deep-copy constructor detects being called with a `FakeDomain` instance;
  `getLevelSets()` returns real, empty `viennals.Domain` objects, since the
  floor logic's `vls.Domain`/`MakeGeometry`/`BooleanOperation` calls are
  pybind11-typed and cannot accept a plain Python stand-in). `save_volume_mesh()`
  itself was not touched or branched for this — same code path both mock
  and real. Now PASSES (`ALL PHASE 1 MOCK CHECKS PASSED`).
- Phase 4 (oxidation, LOCOS variant) segfaults, and Phase 5/6/7/8/9/14
  (all DevSim-touching) fail with a native `OMP: Error #15` (two OpenMP
  runtimes — `libiomp5md.dll` and `libomp140.x86_64.dll` — double-initialized
  in the same process) — **both confirmed pre-existing and unrelated to
  this fix**, by reverting `io.py` to its pre-fix version and reproducing
  byte-for-byte identical failures (same residual values for the LOCOS
  segfault; same OMP error at the same point for every DevSim test). Left
  untouched per explicit instruction; tracked as separate open issues below.

Remaining design question, not yet resolved: whether a *subsequent*
process step could be affected if the floor were ever applied before
further processing rather than only at export time — moot for now since
the floor is applied only inside `save_volume_mesh()`, the last step of
every `ProcessStep.run()`, never mid-process.

**Floor depth wiring — `Wafer.silicon_depth_um` connected (later in this
session, after the production fix and regression above; this is what
point 7 above refers to):**

`save_volume_mesh()`'s `floor_depth_um` parameter is now sourced from a
new optional `recipe["silicon_depth_um"]` key at all 13 call sites
(`floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM)`),
and `tcad_2d_stagewise.py`'s (sole) recipe-building site populates that
key from `self.wafer.silicon_depth_um`. This is a second, later round of
edits to the same 13 files the floor mechanism itself needed zero changes
for — the mechanism (io.py) and the depth's source (these 13 files + the
GUI) were separate changes, in that order. Absent key -> unchanged
default behavior (`DEFAULT_FLOOR_DEPTH_UM = 5.0`), so every existing
recipe/test not mentioning this key is unaffected. Verified end-to-end
through the real production path: recipe without the key -> Si floored at
exactly 5.0um; recipe with `silicon_depth_um=2.0` -> Si floored at exactly
2.0um.

Files touched by this wiring step specifically: `tcad/backends/viennaps/io.py`
(docstring only — the function already accepted `floor_depth_um`, no
logic change here), all 13 `ProcessStep.run()` files listed above, and
`tcad_2d_stagewise.py`.

Not done (explicitly out of scope for this step): centralizing the
13x-duplicated `recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM)`
line into `ProcessStep`; validating/clamping `silicon_depth_um` (a zero
or negative value is untested and would likely produce a degenerate
floor box); adding a GUI widget to actually edit
`Wafer.silicon_depth_um` (it is wired correctly but currently has no
input field, so every GUI-triggered run still effectively uses the
`Wafer` dataclass default, 5.0 — the same number `DEFAULT_FLOOR_DEPTH_UM`
already falls back to).

**FINAL regression (current, up-to-date state) — after the floor
mechanism, the floor-depth wiring, the DevSim lifecycle cleanup fix, and
the OMP fix documented elsewhere in this file, with the PN-junction
investigation closed as unresolved:**

| Test | Result |
|---|---|
| Phase 1 (mock) | PASS |
| Phase 2 (etching) | PASS |
| Phase 3 (deposition) | PASS |
| Phase 4 (oxidation, LOCOS variant) | **PASS** (later session, was FAIL — root cause found (ViennaPS's default mask `contactMode`) and fixed via `OxidationMaskParameters(contactMode=2)`, see "LOCOS (Phase 4) segfault" section below; real oxide growth verified, mask preservation still open) |
| Phase 5 (DevSim solve) | PASS |
| Phase 6 (characterization I-V) | PASS |
| Phase 7 (doping + Poisson, matches analytic V_bi) | PASS |
| Phase 8 (PN junction I-V) | **FAIL** — convergence, root-cause investigation closed unresolved (see dedicated section below); not caused by the floor-depth wiring specifically — same failure with or without a `silicon_depth_um` recipe key |
| Phase 9 (MOS C-V) | PASS |
| Phase 13 (process flow continuity) | PASS |
| Phase 14 (flow -> DevSim) | PASS |
| `test_device_lifecycle_repeat_real.py` Test A (repeated Ohmic) | PASS |
| `test_device_lifecycle_repeat_real.py` Test B (repeated PN junction) | **FAIL** — same root cause as Phase 8 |

No regressions from the floor-depth wiring step: every test that passed
before it still passes; the two known failures (Phase 4, Phase 8) fail
identically to how they failed before wiring was added.

**Updated (later session, after the LOCOS `halfTrench` fix and the GUI
`silicon_depth_um` field):** `tests/run_regression.py` reports **10
passed, 2 failed**. Phase 4 moved from FAIL to PASS (see "LOCOS (Phase
4) segfault" above). The 2 remaining failures are both the same
pre-existing, already-investigated, explicitly-not-pursued PN-junction
convergence issue: Phase 8 directly, and
`test_device_lifecycle_repeat_real.py` (fails in its Test B, same root
cause — the file also hits an unrelated cosmetic `UnicodeEncodeError` in
its own print statements when run without `PYTHONIOENCODING=utf-8`, per
the note under "DevSim / OpenMP runtime conflict" above; confirmed by
re-running with that env var set that Test A still passes and Test B
still fails with the identical convergence error either way). Nothing
else regressed.

### DevSim device/mesh lifecycle cleanup — RESOLVED (this session, found
while investigating the PN junction issue below)

`devsim.delete_device(device)` deletes the device but **not** the
underlying mesh created by `create_gmsh_mesh()` — the mesh stays
registered in DevSim's global state. Since `devsim.solve()` takes no
`device=` filter (it solves every currently-registered device together),
and re-importing with a reused mesh name fails outright, a caller that
only calls `delete_device()` between imports can leave the process in a
state where a *later, logically unrelated* `solve()` fails to converge —
confirmed directly: running two independent, geometrically-unrelated
meshes back-to-back in one process, the second `solve()` failed after the
first one failed and was "cleaned up" with `delete_device()` alone; adding
`devsim.delete_mesh(mesh=...)` alongside `delete_device()` made the second
solve succeed regardless of what happened first.

This was **already known and correctly handled** in one place —
`tcad/cli/run_pipeline.py`'s `_cleanup_device()` helper already calls
both, with a docstring explaining exactly this. It was **not** applied
consistently: `tests/integration/test_phase8_pn_junction_real.py` called
only `delete_device()` at its 3 device-lifecycle points. Fixed by adding
the matching `devsim.delete_mesh(mesh=...)` call at each of the 3 sites,
mirroring `run_pipeline.py`'s already-verified pattern. No production
`tcad/` code needed changes — `run_pipeline.py` was already correct, and
`test_device_lifecycle_repeat_real.py` already goes through
`run_pipeline()` so was never affected by this gap.

### LOCOS (Phase 4) segfault — RUNTIME RESOLVED (root cause found), MASK PRESERVATION STILL OPEN (later session, supersedes the halfTrench workaround below)

**History note:** this section previously recorded a fix using
`MakeTrench(..., halfTrench=True)` ("A" below). That fix genuinely
avoided the crash but is superseded by the contactMode fix ("C") in
this section — kept only in the A/B/C comparison for the record, no
longer used in `thermal.py`. Independently, while this fix was on a
separate branch, another local investigation (uncommitted, on the main
project worktree) found and tried a different workaround using an
explicit `MakePlane(..., SiO2, addToExisting=True)` pad-oxide layer
("B"). Both A and B are superseded; see the comparison below for why.

**Real root cause (found by a single-variable ablation against the
ORIGINAL, unmodified trench geometry — no halfTrench, no extra pad-oxide
layer, only one setting changed per run):** ViennaPS's
`OxidationMaskParameters` defaults to `contactMode=1` ("oneway"/kinematic
mask contact). For this project's trench geometry, that contact mode's
elastic solve diverges — confirmed: 16 non-converged solves, then a
native access-violation crash (`rc=3221225477` / `0xC0000005`),
reproduced deterministically across repeated runs. Setting **only**
`OxidationMaskParameters.contactMode=2` ("twoway"/elastic feedback — the
same mode the official ViennaPS `examples/locosOxidation/locosOxidation.py`
example uses via its `config.txt`'s `maskContactMode="twoway"`), with
every other mask/solver parameter left at ViennaPS's own default, is
**sufficient by itself**: 0 solver failures, real oxide growth,
geometry identical to setting the full official parameter set on top.
No trench-geometry change was needed.

**A / B / C comparison (all measured against the real, floored,
exported volume mesh via meshio — never the raw in-memory level set,
whose "bottom" edge is a narrow-band artifact for a semi-infinite
region, not a physical boundary — and all under the same LOCOS
recipe/grid used by the original crash, `test_phase4_oxidation_real.py`'s
`thermal_locos_style_with_mask` variant):**

| | A: `halfTrench=True` | B: explicit `MakePlane` pad oxide | C: `contactMode=2` (adopted) |
|---|---|---|---|
| crash | none | none | none |
| oxide growth | real, +0.2014 area (resolvable-grid test) | **zero** — identical mesh at t=0.01hr and t=0.1hr, no growth at all | real, matches Deal-Grove order of magnitude |
| mask preservation | ~0.2% area retained | ~0.2% area retained | ~0.6-3.5% area retained (same underlying problem, still open — see below) |
| mask/window coordinates | **shifted** — rebuilds domain as a half-geometry with `REFLECTIVE_BOUNDARY` at x=0; window lands at `trenchWidth/2`, not the recipe's `mask_left_um`/`mask_right_um` | preserved (no geometry change) | preserved — verified identical Si-window width to the always-correct fin-style variant (0.7994um both, recipe asked for 1.0um, difference is grid discretization, not a shift) |
| export | OK | OK | OK |
| official-example consistency | low — invents a half-domain geometry the official example doesn't use, never sets mask parameters | partial — mimics the official example's `MakePlane` pad-oxide *creation* call, but in the wrong construction order (mask placed on Si first, pad oxide inserted after) relative to the official example (Si → pad oxide → mask on top of the oxide), and never sets mask parameters either | high — uses the exact `contactMode` the official example sets, on the project's own already-correct geometry construction |

(A's oxide-growth number above is from a separate, resolvable-grid,
non-`t=0.01hr` comparison — see the scratch investigation this session;
B's "zero growth" was confirmed at both t=0.01hr and t=0.1hr, i.e. it
doesn't just grow slowly, it doesn't grow at all.)

**Decision: adopt C.** A changes coordinate semantics for no offsetting
benefit once C exists; B doesn't oxidize at all, failing the basic
requirement regardless of how clean its geometry is. Neither "just
doesn't crash" — both were rejected specifically because passing that
bar alone is not sufficient (explicit instruction this session).

**Production fix applied — `tcad/process/oxidation/thermal.py`:**
`ThermalOxidation.run()`'s LOCOS branch (`mask_material` present) now
calls `model.setMaskParameters(vls.OxidationMaskParameters(contactMode=2))`
plus the official example's own mechanics/pressure/stokes/coupling
iteration and tolerance settings (matched values, not fabricated, for
headroom on grids/recipes the ablation didn't test — only `contactMode`
itself was proven load-bearing at the tested recipe). Geometry is back
to plain `self.prepare_domain(recipe)` — the `half_trench` parameter
threaded through `session.make_trench()`/`ProcessStep.prepare_domain()`
for A was removed entirely (dead code once C landed; the
`FakeViennaPS.MakeTrench` mock's matching `halfTrench` parameter was
reverted too), since nothing else ever used it.

**Verified, real ViennaPS 4.6.2, via the actual production entry point
(`registry.get("oxidation","thermal").run()`, not just isolated
probes):**
- `test_phase4_oxidation_real.py` (fin + LOCOS variants): PASS, no crash.
- New `tests/integration/test_locos_contact_mode_fix_real.py`: real
  oxide growth (SiO2 area > 0) confirmed; Si consumption confirmed; the
  LOCOS window's pre-oxidation width matches the fin-style variant's
  (both go through the same `prepare_domain()`, unaffected by
  `mask_material`) to within grid resolution — proving C does not
  reintroduce A's coordinate shift; mask material still exists after
  oxidation (weak check only — see below, full preservation is NOT
  asserted).
- Full regression: **13 passed / 2 failed**, same two pre-existing,
  already-investigated PN-junction convergence failures (Phase 8,
  `test_device_lifecycle_repeat_real.py` Test B) — no new regressions.
- `tests/run_regression.py` itself needed an unrelated one-line fix
  found along the way: its `subprocess.run(...)` call had no explicit
  `encoding=`, so it decoded child-process output using the OS's
  locale-default codepage (cp949 on this machine) instead of UTF-8 —
  this newly started crashing the *runner itself* once C's fix made
  ViennaPS print LOCOS log lines containing `µ`/`°` characters that
  aren't valid cp949. Added `encoding="utf-8", errors="replace"`.

**Still open, NOT fixed by C, verified separately (mask erosion):**
the mask loses ~97-99% of its area during LOCOS oxidation regardless of
which of A/B/C is used, and regardless of the initial-oxide-seed value
(tested both the production formula `max(0.002, gridDelta)` and
ViennaPS's own raw default `0.002`, isolated from the contactMode fix
by holding it constant — see below). This is a real, separate,
unresolved problem. Do not treat LOCOS mask preservation as physically
validated by the contactMode fix.

**Seed-value investigation, isolated from the contactMode fix (fix held
constant, only `setInitialOxideThickness` varied — real values only, no
fabricated calibration):**
- `seed = max(0.002, gridDelta)` (current formula, 0.2um at this
  recipe's gridDelta=0.2): oxide genuinely grows with time (SiO2 area
  0.946 at t=0.01hr -> 0.985 at t=0.1hr); mask retention 0.6-3.5%
  (worse at longer time — continued erosion, not a one-time effect).
- `seed = 0.002` (ViennaPS's own raw default, below one grid cell):
  **confirmed stalled** — SiO2 area is bit-for-bit identical
  (0.00051) at t=0.01hr and t=0.1hr, i.e. it does not grow at all past
  the seed once the seed can't resolve on the grid. This directly
  confirms, in the LOCOS context specifically (not just the earlier
  fin-oxidation context this formula was originally written for), the
  existing comment in `thermal.py` about why the seed must be
  >= gridDelta. Mask retention is not meaningfully better either
  (0.85%), so a smaller seed is not a viable route to fixing mask
  erosion — it only reintroduces the CFL stall.
- Conclusion: the current `max(0.002, gridDelta)` seed formula stays
  unchanged (confirmed necessary, not just inherited); mask erosion is
  independent of it and needs a different root cause, not yet
  identified.

### LOCOS mask erosion — ROOT CAUSE FOUND AND VERIFIED FIXABLE, but blocked from production by a separate, confirmed ViennaPS 4.6.2 upstream limitation (later session)

Reopened per explicit user instruction to keep fixing real errors by
referencing the latest official ViennaPS examples/API (the same
methodology that resolved the Phase 8 PN-junction issue above).
Root-caused via direct comparison against the real, fetched
`examples/locosOxidation/locosOxidation.py` source
(github.com/ViennaTools/ViennaPS) and the `psOxidation.hpp`/
`psDomain.hpp`/`lsWriteVisualizationMesh.hpp` C++ source (all fetched
via WebFetch, not guessed).

1. **What was tested (each an isolated probe, same base LOCOS recipe
   throughout, one variable changed at a time):**
   - (a) Mask **material identity**: `Material.Mask` (current
     production) vs `Material.Si3N4` (the real physical material the
     official example uses), with mechanics parameters held constant.
   - (b) Mask **mechanical parameters**: bare `vls.OxidationMaskParameters()`
     (current production, only `contactMode` set) vs
     `vls.OxidationPresets.siliconNitrideMask1000C()` (the official
     example's own real Si3N4-at-1000°C preset — found via
     `dir(vls.OxidationPresets)`; the preset's real values differ from
     the bare defaults dramatically, e.g. `referenceViscosity` 1000x
     higher, `creepActivationEnergy` 386000 vs 0.0), with material held
     constant.
   - (c) Mask **geometry construction**: this project's current
     `MakeTrench`-based mask sitting directly on bare Si vs the
     official example's own construction (Si → pad SiO2 layer via
     `MakePlane(..., addToExisting=True)` → Si3N4 mask box placed with
     its bottom 1e-6um *inside* the pad oxide — the official script's
     own "contact epsilon" comment: "so Cartesian stencils
     unambiguously see the mask/oxide boundary").

2. **Result:**
   - (a) and (b) alone: **zero effect** — mask retention identical to
     the current baseline (3.54%) whether using `Mask`+bare params,
     `Si3N4`+bare params, or `Si3N4`+official preset. (One important
     side-finding along the way: LOCOS mode itself only activates when
     the *domain's own level-set material tag* matches
     `setMaskMaterial()`'s argument — `psOxidation.hpp`'s
     `findMaterialIndices()` checks `mat == maskMaterial_`. Passing
     `Si3N4` to `setMaskMaterial()` while the geometry itself was still
     tagged `Mask` (this project's `MakeTrench` default,
     `session.make_trench()` never overrides it) silently fell back to
     "standard" (non-LOCOS) mode — confirmed directly from the model's
     own log output, `"starting LOCOS simulation"` vs `"starting
     standard simulation"`. `MakeTrench`'s own `maskMaterial` kwarg
     (default `Material('Mask')`, confirmed via
     `help(vps.MakeTrench.__init__)`) can override this, and was needed
     to correctly test (a)/(b) at all.)
   - (c) — pad-oxide-first + contact-epsilon construction: **mask
     retention 99.80-100.00%** (measured two independent ways: raw
     unfloored `saveVolumeMesh`, and — after fixing a new floor-mechanism
     crash found along the way, see point 4 below — the production
     floored path), vs. the current baseline's 3.54%. Real SiO2 growth
     confirmed alongside it (SiO2 top surface y-position measurably
     advanced over the simulated 0.01hr, order-of-magnitude consistent
     with `estimatePlanarOxideThickness()`'s own Deal-Grove estimate).

3. **What it proves:** The real root cause of LOCOS mask erosion is
   **the mask sitting in direct contact with bare Si, with no pad-oxide
   buffer** — not a wrong material name, not wrong mechanical
   parameters (both were live hypotheses this session and both were
   cleanly ruled out by direct measurement, not assumed). This matches
   real LOCOS process physics too: real fabs always grow a thin pad
   oxide before depositing Si3N4, specifically to buffer the thermal-
   expansion mismatch between Si3N4 and Si — the official example's
   geometry isn't an arbitrary choice, it's physically required, and
   apparently numerically required for ViennaPS's own mask/oxide
   contact-mechanics solver too.

4. **Blocking issue found while trying to ship this fix (two separate,
   confirmed sub-issues):**
   - **(i) `_floored_copy_for_export()` crash — FIXED.** The pad-oxide
     LOCOS geometry produces a level set that comes out of `Process()`
     narrower than ViennaLS's own minimum width, triggering ViennaLS's
     internal "Levelset is less than 2 layers wide. Expanding levelset
     to 2 layers." auto-widen path, which then crashes the immediately
     following `vls.BooleanOperation(..., INTERSECT)` call inside this
     project's floor mechanism (`IndexError:
     vector::_M_range_check`). Fixed with one line in
     `tcad/backends/viennaps/io.py`: `vls.Expand(ls, 3).apply()`
     immediately before the existing box-intersect, for every level
     set (not just the ones known to be affected). Verified safe for
     every already-working geometry this project uses: full regression
     re-run after this fix alone (no other production changes) —
     **16 passed, 0 failed, 0 skipped**, identical to before it, since
     `Expand()` only widens the narrow-band representation, it does
     not move the actual interface.
   - **(ii) "Si" material vanishes entirely from the exported volume
     mesh — NOT FIXED, confirmed to be a ViennaPS/ViennaLS upstream
     characteristic, not a bug introduced by this project's
     adaptation.** Reproduced with THREE different constructions: this
     project's own adapted two-sided-window geometry, and — the
     decisive test — the **official example's own geometry, built
     verbatim** (same half-domain layout, `x_extent=1.0`,
     `y_min=-1.0`, `gridDelta=0.05`, `padOxideThickness=0.03`, no
     adaptation at all). All three: `getMaterialsInDomain()` correctly
     reports `{Si, Si3N4, SiO2}` are present in the domain, but
     `saveVolumeMesh()`'s actual triangulated output only ever contains
     `SiO2`/`Si3N4` triangles — zero `Si` triangles, not even a small
     number, in either the raw or the (Expand-fixed) floored export.
     Traced to `lsWriteVisualizationMesh.hpp`'s own documented
     algorithm (fetched from GitHub): it processes level sets in
     **reverse insertion order**, each one "clipping" the region still
     unclaimed by every material inserted after it. `MakePlane(...,
     addToExisting=True)` (the official example's own call, confirmed
     via `psDomain.hpp`'s `insertNextLevelSetAsMaterial` source: passing
     `wrapLowerLevelSet=True`, `MakePlane`'s own default, performs
     `BooleanOperation(newLevelSet, levelSets_.back(), UNION)`) makes
     SiO2's own level set the union of itself and Si's entire
     half-space — i.e. SiO2's *true* region, after this union, already
     contains 100% of Si's region, so the "topmost material wins"
     clipping algorithm never leaves anything for Si to claim. Tried
     the one obvious alternative — building SiO2 as an explicit,
     genuinely bounded box (not a half-space) via
     `insertNextLevelSetAsMaterial(..., wrapLowerLevelSet=False)`,
     mirroring how the mask itself is correctly built as a distinct
     material this same way — but this broke differently: the mask's
     own area is absorbed into SiO2 *during* `Process()` (mask
     retention dropped to 0.00%, SiO2 area grew by almost exactly the
     mask's own former area), so the model's internal LOCOS mechanics
     apparently depends on the wrap/union relationship being present
     for its own contact-mechanics bookkeeping to work at all. A third
     attempt — skip building a pad oxide manually altogether, rely
     purely on the model's own `setInitialOxideThickness()` auto-seed,
     and pre-position the mask box where that seed will land — failed
     even more severely (SiO2 area exploded to ~20x the domain's own
     physical size, mask reduced to ~0.2% retention): the model
     apparently requires the oxide to already physically exist in the
     domain at `Process()` start for the mask/oxide contact mechanics
     to behave sanely; a floating mask above an as-yet-nonexistent seed
     oxide is not a valid starting configuration for it.

5. **Decision: do NOT change `thermal.py`'s LOCOS geometry construction
   in this session.** The mask-retention fix is real and verified, but
   shipping it would silently break the downstream DevSim
   import/device pipeline (which needs a real, exportable `Si` region)
   for every LOCOS recipe — a strictly worse outcome than the current,
   already-documented mask-erosion limitation. Only the safe,
   independently-verified `io.py` `Expand()` crash fix (point 4(i)) is
   kept as a production change this session; `thermal.py`'s mask
   geometry, materials, and parameters are all unchanged.

6. **What remains uncertain:** whether issue (ii) is specific to
   ViennaPS 4.6.2 (untested against other versions); whether it is
   specific to the `Domain(bounds, bcs, gridDelta)` explicit-bounds
   constructor overload (used throughout every probe this session,
   including the "exact official example" reproduction) as opposed to
   `session.create_domain()`'s simpler 3-argument overload (this
   project's own normal convention, not compatible with the official
   example's asymmetric/reflective-boundary domain as-is); whether a
   completely different export path (bypassing
   `saveVolumeMesh`/`WriteVisualizationMesh`'s built-in material-
   stacking resolution entirely, e.g. resolving each material's region
   directly from its own level set via `viennals.ToVoxelMesh`/manual
   boolean subtraction rather than relying on insertion-order-based
   clipping) could sidestep it; whether ViennaPS has a newer version
   (this project pins `ViennaPS>=4.6`, installed 4.6.2) that fixes this
   specific `WriteVisualizationMesh` behavior.

7. **Attempted and RULED OUT this session (same session, immediate
   follow-up per explicit user instruction to keep trying real fixes
   rather than stop at "not yet root-caused"):** the "resolve each
   material independently via manual boolean subtraction" idea
   proposed above. Result: **`RELATIVE_COMPLEMENT` (and the equivalent
   `INTERSECT` with an `INVERT`ed operand) reliably returns an EMPTY
   level set whenever EITHER operand has ever been through a `UNION`
   operation — confirmed as a precise, reproducible ViennaLS behavior,
   not specific to this project's geometry.** Isolated, minimal proof
   (bypassing this project's own code entirely, pure `vps`/`vls` calls):
   two independent, never-unioned `vps.MakePlane` level sets (e.g.
   `y<0.5` and `y<0.0`) — `RELATIVE_COMPLEMENT` between them correctly
   returns the `[0.0, 0.5]` slab. The *exact same two shapes*, but with
   one of them first put through a single `UNION` (either via
   `MakePlane(..., addToExisting=True)` or an explicit
   `vls.BooleanOperation(..., UNION)` — both tried, identical result) —
   `RELATIVE_COMPLEMENT` between them now returns empty, even though
   `INTERSECT`/`UNION` on the very same (post-union) level set continue
   to work correctly and return the expected shapes. Tried `Prune()` +
   `Expand()` (various widths 3-50) on the unioned level set before the
   subtraction, hoping to "re-normalize" whatever internal state the
   union operation leaves it in — no effect, still empty every time.
   This means the "next smallest experiment" as originally proposed —
   manually undoing the wrap via boolean subtraction — is **not
   viable with this ViennaLS version's Python API**, full stop; it
   is not a matter of getting the operand order or pre-processing
   right.

8. **Next smallest experiment (revised, not done, out of scope for
   this round):** given point 7 above closes off the "boolean
   subtraction" route entirely, the only remaining paths are (a) a
   fully custom mesh triangulator that resolves each material's true
   region from first principles (e.g. Si's own never-unioned level
   set gives its exact true boundary already; SiO2's true boundary
   could be reconstructed geometrically as "the region between Si's
   true top surface and SiO2's own wrapped top surface," triangulated
   by hand rather than via any ViennaLS boolean op) — a genuinely new,
   nontrivial mesh-generation code path, not a quick fix; or (b)
   reporting this as a bug upstream to the ViennaPS/ViennaLS
   maintainers and checking whether a newer release (this project pins
   `ViennaPS>=4.6`, installed 4.6.2) behaves differently. Neither was
   attempted this session.

### LOCOS mask erosion — RESOLVED AND SHIPPED (later session, per explicit user instruction "더 나아갈 수 있나" / "can we go further" — picks up exactly where point 8 above stopped)

Point 8 above named a "fully custom mesh triangulator that resolves
each material's true region from first principles" as the one
remaining route once the boolean-subtraction path was confirmed closed
(point 7). This session built exactly that, made it work, and shipped
it.

1. **What was tested:** three isolated, non-production probes, each
   building directly on the previous one's result (not re-litigating
   points 1-8 above — the geometry construction, mask parameters, and
   root cause were already settled):
   - A minimal probe proving the core idea with plain arithmetic, no
     mesh-building at all: since a wrapped level set's UPPER boundary
     is geometrically unaffected by `wrapLowerLevelSet=True` (the wrap
     only extends the LOWER boundary down to match whatever it wraps —
     confirmed from `psDomain.hpp`'s own source, `wrapLowerLevelSet`
     only mutates the NEW level set being inserted, never anything
     already stored), `Area(SiO2_true) = Area(SiO2_wrapped) -
     Area(Si_true)` should hold as simple subtraction, where both areas
     come from independently, correctly exportable single-material
     meshes (Si from its own never-wrapped level set; SiO2_wrapped from
     a throwaway domain containing ONLY the SiO2 level set, still
     wrapped, but with no other level set present to lose the "topmost
     wins" contest to). Result: `SiO2_true = 0.80021`, physically sane
     (matches the Deal-Grove-estimated growth order of magnitude for
     this recipe) and, critically, positive and non-trivial — the
     concept holds.
   - A full-mesh version of the same idea: export each level set to
     its own single-material mesh (via the SAME, already-verified
     `save_volume_mesh()` — no new export logic needed to solve THIS
     part), then for the wrapped material, keep only the triangles
     whose centroid lies above a per-x-column "top of Si" lookup table
     built from Si's own true mesh, merge the surviving triangles from
     every material into one combined, per-triangle-tagged mesh. First
     attempt had a real bug: the lookup table was binned at the
     process's own (coarse, gd=0.2) grid resolution, and 4 of 22 bins
     had no Si vertex land in them at all, left at a sentinel value low
     enough that any SiO2 triangle centroid in those columns passed the
     "is this point above Si" filter unconditionally — silently keeping
     triangles that should have been clipped, inflating SiO2's area
     from the correct ~0.80 to 3.8. Fixed with a nearest-neighbor
     forward/backward fill of the lookup table for any untouched bin.
     Re-verified: SiO2 area came out 0.80004, matching the independent
     area-only arithmetic check (0.800) almost exactly, and the
     combined mesh, re-read by meshio, correctly reported all three
     materials present (`['Si', 'SiO2', 'Si3N4']`).
   - The decisive check: wrapped the combined mesh in a real
     `ProcessResult`/`MaterialRegion` and called the REAL production
     `import_process_result()` (`tcad/device/devsim/mesh_import.py`) on
     it, not a mock. Succeeded: `regions=['Si', 'SiO2', 'Si3N4']`,
     `contacts=['Si_xmin', 'Si_xmax']` — the exact bar that blocked
     shipping the geometry fix in the first place (see point 4(ii)
     above) is cleared.

2. **What it proves:** the "fully custom mesh triangulator" approach
   point 8 named as the remaining option works, generalizes correctly
   (the fix required NO changes to the already-verified mask-retention
   geometry from earlier in this investigation — only a new export
   path), and survives contact with the real DevSim import boundary,
   not just meshio round-tripping.

3. **Production implementation (this session, after the probes above):**
   - **`tcad/backends/viennaps/io.py`**: new `save_locos_volume_mesh(domain,
     materials, wrap_flags, path, floor_depth_um=DEFAULT_FLOOR_DEPTH_UM)`,
     generalizing the probes' approach beyond the fixed 3-level-set
     case: `materials[i]`/`wrap_flags[i]` describe
     `domain.getLevelSets()[i]` in insertion order (`wrap_flags[i]`
     mirrors the same `wrapLowerLevelSet` boolean used when that level
     set was inserted). Each level set is exported in total isolation
     (`_export_single_level_set` — a fresh throwaway single-level-set
     Domain run through the existing, unmodified `save_volume_mesh()`,
     so the normal floor mechanism still applies per-material); a
     wrapped level set's triangles are then clipped against a running
     "top of everything claimed so far" lookup (`_top_lookup`, the
     nearest-neighbor-filled version from the probes) built
     cumulatively over every earlier level set's TRUE (already-clipped
     where applicable) region — not just the immediately-preceding one,
     so this correctly generalizes to a longer wrap chain than the
     3-layer case actually exercises, mirroring how ViennaPS's own
     `wrapLowerLevelSet=True` cascades (unions with whatever is
     currently the top of the stack, which may itself already be a
     wrap). Surviving triangles from every level set are merged into
     one mesh, tagged per `materials`, written to
     `f"{path}_locos_volume.vtu"`.
   - **`tcad/process/oxidation/thermal.py`**: new
     `ThermalOxidation._build_locos_geometry()`, used ONLY when
     building a fresh wafer (`self._inherited_domain is None`) AND
     `mask_material` is present in the recipe — an inherited-domain
     LOCOS call (mid process-flow) falls back to the previous behavior
     unchanged (whatever geometry was carried over, mask material
     tagged onto it via `setMaskMaterial()` as before; this from-scratch
     pad-oxide construction has no meaning applied to an
     already-processed domain, the same restriction
     `ProcessStep.prepare_domain()` already documents for its own
     trench-building branch). Builds: `MakePlane(Si)` ->
     `MakePlane(pad oxide, addToExisting=True)` -> a mask box (two
     boxes, left+right of the window, unioned together, contact-epsilon
     overlap into the pad oxide) inserted with `wrapLowerLevelSet=False`.
     `run()` then skips the `setInitialOxideThickness()` seed call for
     this path specifically (a real, resolvable pad oxide already
     exists in the geometry by the time `Process()` runs — that call is
     only for the no-SiO2-exists case, confirmed by NOT including it in
     any of the verification probes above and re-confirming the fix
     still measures the same retention without it) and calls
     `save_locos_volume_mesh()` instead of `save_volume_mesh()` at
     export time. Fin-style oxidation (no `mask_material`) is completely
     unchanged — still `prepare_domain()` + `save_volume_mesh()`, same
     as before this session.
   - New `pad_oxide_thickness_um` recipe key, optional, defaulting to
     `max(0.02, grid_delta_um)` (`DEFAULT_PAD_OXIDE_THICKNESS_UM = 0.02`,
     20nm, typical real LOCOS pad-oxide thickness; floored at
     `grid_delta_um` for the same reason `setInitialOxideThickness`'s
     existing seed floor exists elsewhere in this file — a pad thinner
     than one grid cell can't be resolved by the level set).
   - `mask_material`'s value itself was kept fully generic/configurable
     (geometry is tagged with whatever `recipe["mask_material"]` names,
     and `setMaskMaterial()` is called with the same value) rather than
     hardcoded to `Si3N4` — deliberate, because the ablation earlier in
     this investigation (point 2a above) already proved material
     identity has ZERO effect on retention, so forcing a material-name
     change would be an unforced, unverified-as-necessary change to
     every existing recipe/test using `"mask_material": "Mask"`.
   - Mechanics parameters were kept as bare `vls.OxidationMaskParameters()`
     with only `contactMode=2` set (current production code,
     unchanged) rather than switched to
     `OxidationPresets.siliconNitrideMask1000C()` (which the
     verification probes happened to use) — re-verified directly, not
     assumed: a dedicated probe re-ran the new pad-oxide-first geometry
     through `session.create_domain()` (the actual production
     domain-construction function, not the probes' ad-hoc explicit-bounds
     construction) with bare parameters, confirming retention was still
     ~98% (97.99%), matching the earlier ablation's finding that the
     preset is not load-bearing. Keeping the current production
     parameters minimizes the number of simultaneously-changed
     variables.

4. **Verified, real ViennaPS 4.6.2 + DevSim 2.10.1, through the actual
   production entry points (not just probes):**
   - `tests/integration/test_phase4_oxidation_real.py`: PASS, no crash,
     both fin and LOCOS variants.
   - `tests/integration/test_locos_contact_mode_fix_real.py`: updated —
     item 3 now asserts Si is present with nonzero area (previously
     just checked growth happened, since Si-vanishing wasn't yet a
     concern the test needed to guard); item 5 upgraded from "mask area
     > 0" (a weak sanity check, explicitly documented as NOT validating
     preservation) to `retention > 0.90` (real, derived from the
     recipe's own pre-oxidation mask geometry, not a magic number) —
     PASS, measured 97.99% retention, matching the probes.
   - New `tests/integration/test_locos_devsim_import_real.py`: the
     real bar this whole investigation had to clear — calls
     `registry.get("oxidation", "thermal")().run(recipe, ...)` (the
     actual production entry point, not manual geometry construction
     like the probes used), confirms all three materials are present
     in the exported mesh, runs it through the real
     `build_process_result()` -> `import_process_result()` adapter
     chain, and re-confirms retention > 0.90 from the same production
     mesh. PASS.
   - Full regression: **`tests/run_regression.py` -> 17 passed, 0
     failed, 0 skipped** (16 before this session's new test was added;
     no regressions to anything else — fin-style oxidation and every
     other model/phase is bit-for-bit unaffected, since the new
     geometry/export path is only reachable via the specific
     fresh-wafer-LOCOS branch).

5. **What remains uncertain:** whether `pad_oxide_thickness_um`'s
   default (`max(0.02, grid_delta_um)`) is appropriate across a wider
   range of grid resolutions/recipes than the one tested here
   (gd=0.2); whether `save_locos_volume_mesh()`'s cumulative wrap-chain
   generalization (point 3 above) is correct for a 4+-level-set stack —
   only the 3-level Si/SiO2/mask case was ever actually exercised;
   whether this fix interacts with a subsequent process step continuing
   from this LOCOS result (untested — every verification here is a
   single LOCOS step, fresh wafer to final mesh, never chained into a
   further step the way Phase 13/14 chain other models).

6. **Next smallest experiment (not done, out of scope for this
   round):** now that LOCOS mask preservation is no longer a blocker,
   the LOCOS bird's-beak shape's true diffusion-driven behavior (vs. a
   seed-geometry or mask-erosion artifact) — named as unresolved
   earlier in this file — is newly investigable, since a previous
   attempt to look at it would have been confounded by the mask
   erosion this session fixed. Not attempted this session.

### LOCOS process-flow chaining — REAL BUG FOUND, safety-net mitigation SHIPPED, full fix NOT attempted (later session, per explicit user instruction "지금 발생한 모든 문제를 해결해" / "solve all the problems that have occurred" — resolves point 5's "untested" item above)

1. **What was tested:** built a fresh LOCOS geometry via the real
   production entry point (`registry.get("oxidation","thermal")().run(recipe,...)`,
   `mask_material` present), then chained a SECOND, unrelated step
   (`DirectionalEtch(inherited_domain=step1.last_domain)`) onto its
   `last_domain` — mirroring exactly how `tcad.process.flow.run_flow()`
   chains any two steps (`StepCls(inherited_domain=carried_domain)`).
   Compared against a negative control: the identical chaining pattern
   with FIN-STYLE oxidation (no `mask_material`) instead of LOCOS —
   already known-good, since Phase 13's own continuity tests chain
   fin-style oxidation into further etch/deposition steps successfully.

2. **Result:** the negative control (fin-style) chains correctly —
   step 2's own export (via the NORMAL `save_volume_mesh()`, not
   `save_locos_volume_mesh()`) contains all 3 materials (Mask, Si,
   SiO2) with sane areas, matching step 1's own areas almost exactly
   (Si 19.9889 → 19.989452, SiO2 0.95965 → 0.9190083 after a shallow
   etch — both physically reasonable). **The LOCOS case does NOT**:
   step 1's own export (via `save_locos_volume_mesh()`) correctly has
   all 3 materials, but step 2's own export — same domain, one
   `Process()` call later, through the NORMAL `save_volume_mesh()`
   that `DirectionalEtch.run()` uses — contains ONLY material tag 10
   (Si), 93 triangles, with an area (1.4698737) that matches step 1's
   MASK area (1.4698067) almost exactly, not any real Si region. SiO2
   and Mask are entirely absent from step 2's export, and the "Si"
   region present is mislabeled/wrong-shaped, not real Si.
   `domain.getMaterialsInDomain()` still correctly reports all 3
   materials present in the domain itself both before and after the
   etch — only the EXPORT is corrupted, not the underlying geometry.

3. **What it proves:** chaining a subsequent process step onto
   fresh-LOCOS-produced geometry is currently broken — NOT because the
   pad-oxide-first LOCOS geometry itself is wrong (the domain's own
   materials stay correct through the etch), but because only
   `tcad/process/oxidation/thermal.py`'s OWN `run()` knows to call
   `save_locos_volume_mesh()` instead of the normal `save_volume_mesh()`
   for ITS OWN export. A DIFFERENT step (any etch/deposition model)
   that later inherits this domain has no way to know its inherited
   domain still has ViennaPS's "wrap" stacking topology baked in
   (SiO2's level set is a union including Si beneath it — see "LOCOS
   mask erosion" above for the full mechanism) — it just calls the
   normal `save_volume_mesh()` at the end of its own `run()`, hitting
   the exact same `WriteVisualizationMesh` reverse-insertion-order
   "topmost wins" resolution bug the LOCOS export fix was built to
   route around, uncaught.

4. **Decision: do NOT attempt the full architectural fix this
   session.** A real fix would need every `ProcessStep` (13+ files) to
   know whether its `inherited_domain` requires LOCOS-style export —
   propagating that (plus the `materials`/`wrap_flags` lists
   `save_locos_volume_mesh()` needs) through `ProcessStep.__init__`
   and `tcad.process.flow.run_flow()`'s chaining mechanism is a
   materially larger, more invasive change than this session's other
   fixes, touching code far outside `mesh_import.py`/`io.py`, and
   risks regressing the ALREADY-working fin-style/other chaining paths
   Phase 13/14 depend on if done hastily. This does not meet the "work
   slowly, one subsystem at a time" bar for a same-session fix.

5. **Safety-net mitigation SHIPPED instead** — turns future silent
   data corruption into a visible signal:
   `tcad/backends/viennaps/io.py`'s `save_volume_mesh()` now calls a
   new `_warn_if_materials_missing_from_export()` after every export:
   compares `domain.getMaterialsInDomain()` against the materials
   actually present (nonzero triangles) in the just-written mesh, and
   issues a `RuntimeWarning` (never raises — a diagnostic must not
   break an export it can't itself explain) if any domain material is
   completely absent from the export. Verified directly: fires exactly
   on the reproduced bug case above (`missing 2 material(s)... tag(s)
   [0, 30]`), stays silent on the fin-style negative control, and
   stays silent across the entire regression suite (19 passed, 0
   failed, 0 skipped, including every LOCOS-touching test — the
   warning only fires for the CHAINED case, never for LOCOS's own
   single-step export via `save_locos_volume_mesh()`, which doesn't
   call this check at all).

6. **What remains uncertain / explicitly not done:** the general
   architectural fix (item 4) itself; whether a step OTHER than
   `DirectionalEtch` (e.g. another oxidation, a deposition model)
   chained onto fresh-LOCOS geometry fails the SAME way or differently
   — only one downstream model was tested; whether this same class of
   bug can occur WITHOUT LOCOS at all, for some other domain topology
   this project hasn't yet built (the fin-style negative control rules
   out "any wrapped SiO2" as sufficient to trigger it, but doesn't
   prove LOCOS's specific 3-level, mask-as-third-unwrapped-layer
   construction is the only topology that can).

7. **Next smallest experiment (not done, out of scope for this
   round):** if this needs to be fully fixed later, the smallest
   correct step is probably NOT "make every ProcessStep LOCOS-aware" —
   it's more likely tagging the inherited domain itself (or the
   `ProcessStep` instance) with an explicit "export style" descriptor
   that `ProcessStep.prepare_domain()`/every `run()`'s final export
   call reads generically (LOCOS being the first, not necessarily
   last, case needing non-default export) — a real design decision,
   not attempted here.

### LOCOS process-flow chaining — ROOT CAUSE REFINED, prototyped export fix implemented and found INSUFFICIENT — real cause is deeper than previously characterized, still NOT fixed (later session, per explicit user instruction to apply the real fix this time — "LOCOS 체이닝 버그 본수정")

Part 10 above ("LOCOS process-flow chaining — REAL BUG FOUND... re-investigated") identified a `getBoundingBox()` degeneracy (`±DBL_MAX` inverted sentinels) inside `_export_single_level_set()`'s isolated single-material domain reconstruction, and proposed a concrete fix: pass already-known-good bounds through explicitly instead of letting the broken call re-derive them. This session implemented and tested exactly that fix — and found it does NOT actually solve the problem it was meant to solve, because the true root cause turned out to be one level deeper than part 10's own diagnosis reached.

1. **What was tested:** Built a full-fidelity prototype (monkeypatching `tcad.backends.viennaps.io` at runtime, not editing production files yet) implementing part 10's proposed fix in two parts: (a) a weakref-keyed side table in `io.py` so `thermal.py` can tag a LOCOS-built domain with its `(materials, wrap_flags)` export hint — chosen over dynamic attribute assignment on the domain object itself after directly confirming that does NOT work (`geometry._custom_attr = ...` raises `AttributeError: 'viennaps.d2.Domain' object has no attribute` — the pybind11 class has no `py::dynamic_attr()`); `save_volume_mesh()` would consult this table and auto-delegate to `save_locos_volume_mesh()`, requiring zero changes to any of the 13+ `ProcessStep.run()` files. (b) `_floored_copy_for_export()`/`_export_single_level_set()` accept an optional `bounds_hint` so the known-good bounds from the ORIGINAL (pre-isolation) domain are threaded through instead of re-querying the broken isolated domain's own `getBoundingBox()`.

   Reproduced the exact scenario from part 8/10: real `ThermalOxidation.run()` (fresh LOCOS, `test_locos_devsim_import_real.py`'s own recipe) → chain a real `DirectionalEtch(inherited_domain=step1.last_domain).run()` onto it → inspect step 2's own export.

2. **Result:** The bounds-hint fix DID eliminate the hang — step 2 completed in under a second instead of hanging for minutes, confirming part 10's hang diagnosis was correct as far as it went. But the resulting per-material isolated export for Si came back as a **genuinely empty mesh** (`NumberOfPoints=0, NumberOfCells=0` in the raw VTU, which is what made meshio's compressed-binary reader crash with `ValueError: need at least one array to concatenate` — not a bbox-query artifact, a real empty file).

   Chased this with direct level-set introspection (`level_set.getNumberOfPoints()`, not just domain-level `getBoundingBox()` — part 10's investigation never checked this): right after step 1 (fresh LOCOS oxidation), Si/SiO2/Mask level sets have 38/62/104 points respectively, all real. **After step 2's chained `Process()` call (the directional etch) — still on the very same domain object, before any export is attempted at all — Si and SiO2's level sets have collapsed to 0 points each, while Mask's is unchanged (104 points).** This is not an export-layer bug at all; the domain's own in-memory geometry is what's actually gone.

   Tested and ruled out "level set too narrow for advection" as the cause (SiO2 measured width=1 right after step 1, below what several other ViennaLS operations in this codebase require ≥2 for): explicitly widened every level set to width=5 (`vls.Expand(ls, 5)`, mutating the real domain in place, not an export copy) immediately before chaining step 2. Made no difference whatsoever — Si and SiO2 still collapsed to 0 points after the same chained `Process()` call, this time even Mask lost points too (148→68, though not to zero). This rules out level-set width as the cause.

3. **What it proves:** Part 10's characterization ("only the ISOLATED single-level-set reconstruction's bbox breaks... the ORIGINAL multi-material domain's own bounding box stays correct throughout") was real but incomplete — it only checked the domain-level aggregate `getBoundingBox()` (which does stay non-degenerate) and the final multi-material export's material tags, not each level set's own point count. The real corruption happens earlier and deeper: **any subsequent `Process()` call applied to a domain built via LOCOS's pad-oxide-first wrapped construction (`insertNextLevelSetAsMaterial(..., wrapLowerLevelSet=True)` for the pad oxide) empties out the non-mask level sets' own point data**, before export is ever involved. This also retroactively explains part 8's original symptom (chained step's own export showing a small, mislabeled "Si"-tagged region matching the *mask's* area almost exactly) — consistent with only the Mask level set having survived with real data by the time any export ran.

   Because the underlying domain data is already gone by the time `save_volume_mesh()`/`save_locos_volume_mesh()` runs, **no export-layer fix — bounds-hint or otherwise — can recover it.** The fix this session implemented and tested is real (it does fix the hang, a genuine improvement) but is not sufficient to fix the actual bug, so it was NOT applied to production code. Shipping only the hang fix would silently turn a loud failure (indefinite hang, impossible to miss) into a fast, quiet one (empty/wrong mesh, already covered by the existing `_warn_if_materials_missing_from_export()` safety net from part 8 — but nothing more).

4. **What remains uncertain:** the exact ViennaPS/ViennaLS C++ mechanism causing a wrapped level-set stack's non-mask members to lose their point data under a further `Process()`/advection call — an attempt to fetch and cross-reference the real `psProcess.hpp`/advection source from GitHub for this session's investigation was blocked by a GitHub-side rate limit (HTTP 429, `Retry-After: 3600`) at the moment it was tried, so this was not root-caused at the C++ level, only precisely characterized at the Python/data level; whether this is specific to `DirectionalProcess` as the second step or would reproduce with any other model (only one downstream model was retested this session, same as part 8); whether a materially different LOCOS geometry construction (not pad-oxide-first/wrapped) could avoid triggering this at all — out of scope to explore this session since the shipped mask-erosion fix (see "LOCOS mask erosion — RESOLVED AND SHIPPED" above) already depends on the wrap topology and is not being revisited here.

5. **Decision: do NOT apply the bounds-hint export fix, or any other change, to production code this session.** It is real, verified working for what it does (eliminates a genuine hang), but does not fix the user-visible problem (materials still missing after chaining), and CLAUDE.md's own rule against shipping something that doesn't solve the actual problem applies here even though the user asked for the "real fix" this round — discovering mid-investigation that the previously-scoped fix doesn't work is exactly the kind of thing this file exists to report honestly rather than paper over. The existing `RuntimeWarning` safety net (`_warn_if_materials_missing_from_export()`, part 8) remains the only production mitigation, and remains valid — it fires correctly for this exact case.

6. **Next smallest experiment (not done, out of scope for this round):** once the GitHub rate limit clears, fetch ViennaPS's real advection/`Process()` C++ source to look specifically for how it handles a level-set stack containing a `wrapLowerLevelSet=True` member during advection, to see whether this is a documented limitation or something to report upstream; separately, test whether the SAME chained-step corruption happens with a *fin-style* (no mask, no LOCOS) domain that still happens to contain a wrapped level set for some other reason (would help isolate "wrap topology" vs. "LOCOS specifically" as the trigger); consider whether avoiding chaining onto fresh-LOCOS output altogether (documenting it as a hard workflow constraint — LOCOS as a terminal step only — rather than something to fix in code) is the more honest near-term answer, since two separate fix attempts (part 10's design, and this session's implementation of it) have now both fallen short.

### LOCOS process-flow chaining — RESOLVED AND SHIPPED (later session, per explicit user instruction "LOCOS 천천히 해도 되니까 꼭 찾아봐" / take your time but really find it, then "둘다해줘" / apply it)

Four earlier attempts failed (part 10's bounds-hint design, part 12's
implementation of it, plus a reordering and a mask-wrapping variant).
This one works. Full test-by-test record in
`LOCOS_CHAINING_TEST_LOG.txt` (items 15-18, 22).

1. **What was tested — the question every earlier attempt skipped.**
   Part 12 had established ViennaLS `Advect`'s documented precondition
   (advects only the LAST level set, then replaces each lower one with
   `lower INTERSECT last`, requiring the last to CONTAIN all others).
   But this project's NORMAL path (`MakeTrench` → Si + Mask) chains
   successfully every regression run, and its mask is also "last" — so
   *how does the working path satisfy the precondition that LOCOS
   violates?* Measured both domains side by side, reading the REAL
   material order from each domain's own `MaterialMap`
   (`getMaterialAtIdx` — every earlier test guessed the order from
   insertion code instead of reading it) and exporting every level set
   in isolation:

   | | normal MakeTrench (chains fine) | real LOCOS (chaining destroys it) |
   |---|---|---|
   | ls[0] | **Mask**, area 1.4830, y [0.0000, 0.4999] | Si, area 8.0000, y [-2.0000, 0.0000] |
   | ls[1] | **Si**, area 9.5097, y [**-2.0000**, 0.4999] | SiO2, area 8.8000, y [-2.0000, 0.2000] (wrapped) |
   | ls[2] | — | **Mask**, area 1.4700, y [**0.2000**, 0.7000] (not wrapped) |

   MakeTrench inserts the **substrate** last, and its level set is the
   union of substrate + mask (9.51 ≈ 8.0 + 1.5, spanning floor to mask
   top) — so the last level set contains the other. LOCOS's last level
   set is a small box sitting entirely above y=0.2, containing neither
   Si nor SiO2.

2. **What it proves:** LOCOS is not hitting a ViennaPS limitation this
   project must live with — it is the only geometry in the project that
   does not follow ViennaPS's own "last level set wraps everything"
   convention, which `MakeTrench` (and therefore every other model)
   follows by construction. The bug is in this project's LOCOS
   construction relative to that convention.

3. **Why the fix goes after oxidation, not in the construction.**
   Tests 11 and 14 both tried to satisfy the precondition at
   construction time and both broke `vps.Oxidation()` itself —
   reordering gave literally zero oxide growth (bit-identical SiO2 area
   at t=0.01hr and t=0.05hr, `maxDisplacement=0.000000`), and wrapping
   the mask broke the model's own oxide-band detection outright
   (`"no oxide nodes found after buildNodes()"`, a ~10^308 garbage
   displacement value, then an apparent hang). But the precondition
   does not have to hold *during* oxidation — only for the NEXT step.

4. **Production fix applied — two small pieces:**
   - **`tcad/process/oxidation/thermal.py`**: new
     `ThermalOxidation._make_locos_domain_chainable()`, called at the
     very end of `run()`'s fresh-LOCOS branch, **after**
     `save_locos_volume_mesh()` has already written this step's own
     export — so the LOCOS step's own output is bit-for-bit unchanged.
     It unions the last level set with the one below it, restoring the
     invariant, and registers the export hint.
   - **`tcad/backends/viennaps/io.py`**: new
     `register_locos_export(domain, materials, wrap_flags)` plus a
     weakref-keyed side table, and `save_volume_mesh()` now consults it
     and delegates to `save_locos_volume_mesh()` when the domain is
     registered. This is what lets a downstream step export a
     LOCOS-inherited domain correctly **without any of the 13+
     `ProcessStep.run()` files changing** — they keep calling
     `save_volume_mesh()` exactly as before. A side table rather than
     an attribute on the domain because the pybind11
     `viennaps.d2.Domain` class has no `py::dynamic_attr()` (confirmed
     directly: `domain.anything = ...` raises `AttributeError`).

5. **One-time, not per-step — measured, not assumed.** Test 18 applied
   the re-wrap after every chained step but never checked whether that
   was necessary. Test 22 did: re-wrap **once**, then chain three steps
   (directional etch → isotropic etch → isotropic deposition) with no
   further fixup — all three pass, Si stays exactly 7.99983 throughout,
   SiO2 progresses 0.80021 → 0.75394 → 0.70215, mask grows on the
   deposition step. This matches the mechanism: `Advect` replaces each
   lower layer with an intersection *with* the top, which is a subset of
   the top by construction, so it **preserves** the invariant once it
   holds. Also confirmed there: the domain's Python object identity
   survives every `Process()` call, which is what makes the
   `id(domain)` lookup work at all.

6. **Verified, real ViennaPS 4.6.2, through the actual production entry
   points:** new `tests/integration/test_locos_chaining_real.py` runs
   `registry.get("oxidation","thermal")().run()` →
   `registry.get("etching","directional")(inherited_domain=...).run()`,
   the same way `tcad.process.flow.run_flow()` chains any two steps, and
   asserts: the LOCOS step's own export is unchanged (3 materials, mask
   retention ≥90%); the chained step's own export has all 3 materials
   with nonzero area; no level set was destroyed; the chained etch is
   physically real (removes oxide — a fix that preserved materials by
   making the step a no-op would not count) and leaves Si intact; and a
   SECOND chained step still works with no further fixup. PASSES.

7. **Bosch (`duplicateTopLevelSet`) chains too — verified, was the one
   model this fix's assumptions could plausibly have broken.** Bosch is
   the only model that resizes the level-set stack mid-run
   (`duplicateTopLevelSet` adds a polymer layer each cycle,
   `removeTopLevelSet` pops it), so it could in principle have tripped
   either the Advect precondition or the export hint's fixed
   `materials`/`wrap_flags` length. Measured (LOCOS → Bosch, 2 cycles,
   gridDelta 0.05): no level set destroyed ([162, 473, 198] → [162,
   162, 297]), all 3 materials in the export, no warning raised, and
   physically sensible values (Si unchanged at 19.99983 under its
   oxide, SiO2 0.80021 → 0.73005, mask 1.49498 → 1.44223). Both
   mechanisms hold for the same reason: the duplicate is a *copy* of a
   top that already contains everything, so containment survives the
   cycle, and `removeTopLevelSet()` restores the registered stack
   length before the export runs — the length mismatch only exists
   mid-cycle, where nothing exports. Added as check 6 of
   `test_locos_chaining_real.py` (1 cycle there, enough to grow and
   shrink the stack once).

8. **Grid-resolution coverage — closed.** The fix touches three
   grid-sensitive things (the pad-oxide floor at
   `max(0.02, gridDelta)`, `save_locos_volume_mesh`'s per-x-column
   clipping lookup binned at gridDelta, and the level-set narrow
   band), so it was swept: LOCOS → chained etch at gridDelta 0.02 /
   0.1 / 0.15 / 0.25, all PASS, all 3 materials, no level set
   destroyed, no warnings, real oxide removed each time. With the two
   already-covered values that is **six resolutions over a >12x
   range**. Mask retention degrades gently and monotonically as the
   grid coarsens (100.0% at 0.02 → 95.8% at 0.25) — ordinary
   discretization behaviour, and every point clears the permanent
   test's 90% threshold.

9. **LOCOS-on-LOCOS — refused, not fixed, and NOT a regression.** A
   second LOCOS oxidation on a LOCOS-produced domain hangs: the
   re-wrap makes the mask level set contain SiO2, and
   `vps.Oxidation()`'s oxide-band detection needs a real band between
   distinct level sets (same failure signature as the construction-time
   mask-wrap attempt — `"no oxide nodes found after buildNodes()"`,
   ~10^308 garbage displacement). Verified this is pre-existing, not
   caused by the fix, by rerunning the chain with the re-wrap disabled:
   it completes but silently exports a mesh with **Si entirely absent**
   and SiO2 collapsed 0.80000 → 0.00555, i.e. the original chaining
   bug. LOCOS-on-LOCOS has never worked; the fix only changed how it
   fails. `thermal.py` now raises `NotImplementedError` up front with
   the two real workarounds, turning an indefinite hang into something
   actionable. The guard is deliberately narrow — keyed on
   `mask_material in recipe` AND the inherited domain being
   LOCOS-registered (new `io.is_locos_registered()`) — because
   **fin-style oxidation chained onto LOCOS works and must not be
   blocked**: measured, all 3 materials preserved, Si unchanged, and
   SiO2 genuinely grew 0.80000 → 0.80132.

10. **What remains uncertain:** only `DirectionalEtch`, `IsotropicEtch`,
   `BoschDRIEEtch`, fin-style `ThermalOxidation` and two deposition
   models were chained (test 18 covered four, the permanent test covers
   directional + Bosch + fin oxidation). Also, mask
   area reads ~2.7% high immediately after the re-wrap (1.51028 vs
   1.46981) — a sub-grid-cell clipping-resolution artifact of
   `save_locos_volume_mesh`'s per-x-column top lookup, not real geometry
   change; a retention-threshold assertion is unaffected, an exact-area
   assertion would need widening.

### LOCOS bird's-beak shape — INVESTIGATED, evidence supports genuine diffusion physics, no code change needed (later session, per explicit user instruction "지금 발생한 모든 문제를 해결해" — this is the "next smallest experiment" named at the end of "LOCOS mask erosion — RESOLVED AND SHIPPED" above, now that mask erosion no longer confounds it)

The open question (named repeatedly throughout this file, never
previously investigated): is the tapered oxide profile near the LOCOS
mask edge ("bird's beak") a genuine lateral-oxidant-diffusion effect,
or an artifact of this project's pad-oxide-first seed geometry/mesh
discretization? Distinguishing test (per this project's own
methodology): a real diffusion effect should have a characteristic
taper LENGTH that (a) does NOT shrink proportionally when gridDelta is
refined (an artifact tied to grid cells would), and (b) scales with a
real physical parameter — here, pad oxide thickness, since real LOCOS
literature reports bird's-beak length scaling with the pad oxide
(buffer layer) thickness.

1. **What was tested:** three isolated probes (real ViennaPS 4.6.2,
   real production `ThermalOxidation.run()` entry point, LOCOS branch,
   measuring the exported, correctly-clipped SiO2 region's own top
   surface via `save_locos_volume_mesh()`'s output — not the raw,
   contaminated level set):
   - GridDelta sweep (0.2/0.1/0.05um), pad oxide and time held fixed
     (0.1um, 0.01hr).
   - Time sweep (0.005/0.01/0.02/0.04hr), gridDelta and pad oxide held
     fixed (0.1um each) — deliberately short times, to see the taper
     forming before the field oxide grows thick enough to obscure it.
   - Pad-oxide-thickness sweep (0.05/0.1/0.2um) at TWO growth
     durations: a short one (0.02hr, matching the time-sweep's
     regime) and a more mature one (0.5hr, where total growth is a
     more substantial, less noise-dominated fraction of the pad
     thickness).

2. **Result:**
   - **GridDelta sweep**: at gd=0.2, the window (1.0um wide = 5 grid
     cells) is too coarse to resolve any taper at all — oxide reads as
     flat everywhere. At gd=0.1 and gd=0.05, a clear taper appears with
     comparable length (~0.25-0.35um) at BOTH resolutions — a 2x grid
     refinement did NOT halve the taper length, which a pure
     discretization artifact would do. The plateau (far-field) oxide
     thickness also converged closely between the two resolutions
     (0.10025 at gd=0.1 vs 0.10024 at gd=0.05, for the same time/pad),
     confirming the total growth amount itself is grid-independent.
   - **Time sweep**: plateau growth-above-pad scaled roughly LINEARLY
     with time (0.00025 at t=0.01hr, 0.00049 at t=0.02hr, 0.00097 at
     t=0.04hr — each ~2x the previous for each 2x in time) — matching
     the expected reaction-rate-limited (linear) regime of Deal-Grove
     kinetics for a thin, still-growing oxide, not an arbitrary/
     unphysical scaling. Taper length stayed roughly constant (~0.3um)
     across this 4x time range — at this SHORT-time, thin-absolute-
     growth regime, length didn't clearly track amplitude.
   - **Pad-oxide sweep, short time (0.02hr)**: taper length did NOT
     show a clean scaling with pad thickness (0.05->~0.15um,
     0.1->~0.2-0.25um, 0.2->~0.15-0.2um — noisy, non-monotonic).
     Growth amplitudes here were all under 0.0004um — smaller than the
     0.05um gridDelta itself, i.e. deep in a regime where measurement
     noise (mesh vertex placement precision at that scale) plausibly
     swamps the real signal.
   - **Pad-oxide sweep, mature time (0.5hr)**: taper length now shows
     the EXPECTED clean scaling: **0.3um at pad=0.1um vs. 0.45um at
     pad=0.2um** — thicker pad oxide gives a measurably longer bird's
     beak, consistent with real LOCOS literature. Growth amplitude at
     pad=0.2 (max 0.00467um) was smaller than at pad=0.1 (max
     0.00663um) — consistent with a thicker existing oxide growing
     more slowly (Deal-Grove's diffusion-limited term becoming more
     relevant as oxide thickens), another physically-correct
     signature, not asserted or assumed.
   - Also observed in passing (not itself the question being tested):
     the mask/oxide mechanics solver logged several "did not converge
     ... rejecting non-converged coupled predictor, retrying with
     requested_dt=..." messages at the largest (0.5hr) timestep before
     succeeding at a smaller substep — the model's own existing
     adaptive-timestep robustness handling a numerically harder step,
     not a crash or a wrong result (final residuals converged cleanly
     each time it retried).

3. **What it proves:** the LOCOS bird's-beak shape is grid-independent
   in length (rules out a pure discretization artifact) and, at a
   growth stage large enough to rise above measurement noise, scales
   with pad oxide thickness the way real lateral-oxidant-diffusion
   physics predicts — the SAME physical mechanism responsible for real
   LOCOS bird's beaks. The short-time/thin-growth pad-oxide sweep's
   noisier result is explained by growth amplitudes there being
   smaller than gridDelta itself, not by a physics contradiction —
   resolved by re-testing at a more mature (but still short,
   0.5hr) growth stage where the same relationship becomes clean.

4. **What remains uncertain:** the exact functional form of the
   length-vs-pad-thickness relationship (only 2 points, 0.1um and
   0.2um pad, were compared at the mature timescale — not enough to
   fit a scaling law, e.g. linear vs. sqrt); whether the taper length
   also depends on temperature/oxidant type (only the recipe's default
   dry, 1000C condition was tested); the exact mechanism connecting
   `save_locos_volume_mesh()`'s per-material clipping (a Python-level
   post-processing step, see "LOCOS mask erosion" above) to the
   REAL underlying diffusion field ViennaPS's own `Oxidation` model
   solves internally — this investigation verified the EXPORTED shape
   behaves physically, not the internal diffusion-solve implementation
   itself (out of scope, third-party C++ code); whether the mechanics
   solver's non-convergence-then-retry behavior at large timesteps
   ever produces a materially different final result than a
   fully-converged first attempt would (not compared directly).

5. **Next smallest experiment (not done, out of scope for this
   round):** a proper 3+ point pad-oxide-thickness sweep at a single
   mature timescale to fit and report the actual scaling exponent;
   comparing against `estimatePlanarOxideThickness()`'s own Deal-Grove
   planar estimate at the SAME conditions to see how closely the
   window-center (unmasked) growth rate matches the idealized planar
   prediction (a check this project already does elsewhere for
   non-LOCOS oxidation, not yet done for LOCOS's own field-oxide
   region specifically).

**No production code was changed for this investigation** — this
confirms the model's existing behavior is physically sound, it does
not fix a bug. `thermal.py`/`io.py` are unchanged by this section.

### DevSim BLAS/LAPACK DLL environment issue — RESOLVED (later session)

Every DevSim-touching test now fails at `import devsim` itself, before any
project code runs:
```
Loading "libopenblas.dll": MISSING DLL
Loading "liblapack.dll": MISSING DLL
Loading "libblas.dll": MISSING DLL
Could not find Intel MKL. The maximum tested version is "mkl_rt.2.dll"
```
Confirmed unrelated to any change made this session: reproduces identically
on `test_phase5_devsim_real.py`, which has no connection to
`tcad/process/oxidation/thermal.py` at all.

**Root cause (confirmed, not guessed):** the `.venv/Library/bin/` directory
this file's earlier OMP-fix section refers to (`intel_openmp`/`mkl`
packages providing `libiomp5md.dll` and, implicitly, MKL's BLAS/LAPACK) no
longer exists in this venv — `pip list` shows no `mkl`/`intel-openmp`
package installed, only `numpy 2.2.6`. The venv changed since the earlier
"Phase 5/9/14 PASS" verification was recorded; this is environment drift
between sessions, not something broken by this session's code changes.

**`DEVSIM_MATH_LIBS` attempted and ruled out as a same-venv fix:** numpy
2.2.6 does bundle its own OpenBLAS (`numpy.libs/libscipy_openblas64_*.dll`),
and pointing `DEVSIM_MATH_LIBS` at it (using a proper Windows-style path —
a Git-Bash `/c/...`-style path silently fails with "MISSING DLL", a red
herring) gets past the file-loading step but then fails with
`"MISSING SYMBOLS"`. Root cause: that DLL is built ILP64 (64-bit integer
BLAS/LAPACK symbol interface, `openblas64_` suffix) — DevSim's compiled
extension expects the standard LP64 symbol names. No LP64-compatible
BLAS/LAPACK/MKL library exists anywhere else on this machine either
(searched the user profile and common conda/Intel install locations —
none found). Confirmed inside `tcad_project_gui_fix` and this specific
venv only; not tested elsewhere.

**Fix applied (later session, after explicit confirmation):** `pip install
mkl` — exactly one package requested, no other packages specified. pip's
own dependency resolution pulled in 6 more as a result:
`intel-openmp 2026.1.1`, `intel-cmplr-lib-ur 2026.1.1`, `tbb 2023.1.0`,
`tcmlib 1.5.0`, `umf 1.1.0`, `onemkl-license 2026.1.0`, plus
`mkl 2026.1.0` itself. This matches DevSim's own suggested fallback
("install the Intel MKL") and the venv's apparent prior state (see root
cause above — this is what `.venv/Library/bin/` used to provide before it
went missing).

**Verified: the pre-existing 18 packages' versions are unchanged** —
`pip list` before and after only differ by the 7 new entries above; numpy
stayed at 2.2.6, devsim at 2.10.1, ViennaPS/ViennaLS untouched.

**Verified working, in order, exactly as planned before installing:**
`import devsim` → **PASS** (previously `RuntimeError: Issues initializing
DEVSIM.` at this exact line). `test_phase5_devsim_real.py` (pure DevSim,
no oxidation involvement) → **PASS**, real solve converges. Only then
`test_phase9_mos_cv_real.py` → **PASS**. `test_phase14_flow_devsim_real.py`
→ **PASS**.

**This was a pre-existing environment problem, confirmed unrelated to the
Phase 4 LOCOS fix** (see root cause above: `test_phase5_devsim_real.py`
has no connection to `tcad/process/oxidation/thermal.py` and failed
identically before this fix). No `tcad/` production code was touched to
resolve this — the fix is entirely a venv package addition. Note: this
was performed on the main project worktree's own `.venv`, independent of
whatever venv a given worktree checkout uses for its own regression
runs — re-verify `import devsim` on any other checkout before assuming
this is inherited there too.

**Explicitly deferred, still open (open items):**
- LOCOS mask erosion (~97-99% area loss) — **root cause now IDENTIFIED
  and a fix VERIFIED to work (later session — see "LOCOS mask erosion
  — ROOT CAUSE FOUND AND VERIFIED FIXABLE" further below)**, but not
  applied to production: shipping it would break the exported mesh's
  `Si` region entirely, a confirmed ViennaPS 4.6.2 upstream limitation
  independent of both the contactMode fix and the seed value.
- The bird's-beak shape's true diffusion-driven behavior (as opposed to
  a seed-geometry or mask-erosion artifact) is unresolved — would need
  a finer gridDelta and/or longer time to distinguish, deliberately not
  pursued now to avoid an open-ended parameter sweep.
- `gd=0.02` Si-thickness dependency: untouched, out of scope this
  session per explicit instruction.

### `gd=0.02` Si-thickness dependency — RESOLVED, was already fixed, just never re-verified through the real production path (later session)

Reopened per explicit user instruction to keep working the remaining
OPEN items toward real physical correctness. This item had been
carried forward, unexamined, across multiple sessions as "untouched,
out of scope" since the point above — but the underlying question
("does the floor mechanism actually hold at gridDelta=0.02, not just
the coarser 0.05/0.01 spot-checks in the original verification table")
had, on inspection, already been answered by that same original
table (`gridDelta=0.02` row: Si area after flooring = 1.99970,
area error −0.015%) — just never confirmed through the *real*
`ProcessStep.run()` production entry point or a real DevSim import,
only an isolated Si+Mask probe, which is why this stayed marked open.

**What was tested:** ran the actual production path
(`registry.get(category, name)().run(recipe, ...)`, not an isolated
probe) at `grid_delta_um=0.02` for (a) isotropic etch with the default
floor depth (5.0um), (b) the same etch with an explicit
`silicon_depth_um=1.0` (checking the floor depth isn't silently
gd-dependent), (c) a real thermal oxidation run, and (d) DevSim import
of the oxidation result.

**Result:** all four passed cleanly. (a) Si y-span = 4.99993um
(matches the requested 5.0um floor, not the old `2×gridDelta=0.04um`
narrow-band artifact). (b) Si y-span = 0.99993um (matches the
explicit 1.0um request exactly, confirming the floor depth is a real,
respected parameter at this resolution, not silently overridden).
(c) real oxide growth confirmed (SiO2 area 0.04361 > 0) with Si still
correctly floored at 5.00013um. (d) `import_process_result()` succeeded,
giving regions `['Mask', 'Si', 'SiO2']` and contacts
`['Si_xmin', 'Si_xmax']` — the full pipeline works end-to-end at this
resolution.

**What it proves:** the floor mechanism (and its later `Expand()`
robustness fix from this same session) generalizes correctly to
`gridDelta=0.02` through the real production pipeline, not just the
isolated probe the original verification table used. This was already
true before this session — nothing was fixed here, only verified
through the real entry point, closing out a stale "open item" that
had been carried forward without re-examination since it was first
flagged as explicitly deferred.

**No code change.** No production file was touched for this item —
this was a verification-only follow-up.

### PN junction (Phase 8) convergence sensitivity to the floor mechanism — UNRESOLVED, investigation closed (this session; ROOT-CAUSED AND FIXED in a later session — see "PN junction (Phase 8) convergence — RESOLVED" further below for the real mechanism and fix. Kept here unedited for the historical record of what was ruled out first.)

With the floor fix applied, `test_phase8_pn_junction_real.py` and
`test_device_lifecycle_repeat_real.py`'s Test B (PN junction I-V sweep)
fail with `devsim_py3.error: Convergence failure!`. Confirmed real (not
solver-tolerance-related, not the lifecycle bug above, not flakiness) by
an extensive, dead-end-reaching investigation:

- **Floor depth doesn't matter**: 0.3 (matching the un-floored narrow-band
  extent almost exactly) through 5.0 all fail identically; only *fully
  disabling* the floor mechanism succeeds.
- **Deterministic, not flaky**: floor-on fails 3/3 repeated runs; floor-off
  succeeds 3/3 (independent processes, and confirmed again after the
  lifecycle-cleanup fix above, in clean isolated processes).
- **Not a "bigger/harder mesh" issue**: at floor=0.3 the floored mesh has
  the *same node count* (91 Si nodes) as the un-floored one.
- **Not triangle quality**: worst-case sliver triangles (min angle
  0.166°/0.171°) are bit-for-bit identical between floored and un-floored.
- **Not geometry or topology**: position-matched comparison of all 211
  points shows exact (0.000e+00 distance) matches; all 340 triangles match
  as position-sets; zero winding/orientation flips; region ordering
  identical; no hidden point_data/field_data; contact-edge selection
  (replicating `mesh_import.py`'s own tolerance-based logic) picks the
  identical physical nodes either way.
- **Not node/element ordering**: randomly shuffling a known-good mesh's
  point and triangle order (same content, maximally scrambled) still
  converges fine — ruling out order sensitivity outright.
- **Not OpenMP-runtime perturbation**: performing the floor mechanism's
  exact boolean operations on a *throwaway* level set (never touching the
  exported file) doesn't break the known-good mesh either.
- **Not the assembled Jacobian's values**: `devsim.get_matrix_and_rhs()`'s
  `static` (geometry-derived) matrix entries are bit-identical between
  floored and un-floored when sorted, including the sum — the linear
  system being solved is mathematically the same problem, just under a
  different (equally valid) node permutation.
- **A from-scratch alternative floor mechanism also fails**: replaced the
  boolean-intersect approach with `viennals.Expand(levelSet, width)`
  (in-place narrow-band widening, no boolean re-merge) — this preserves
  131/211 original point indices exactly (vs. the boolean approach's
  near-total reordering) and still deepens Si correctly, but **still
  fails the same way**.

Conclusion: every geometric/topological/numerical property checkable from
Python (via meshio and DevSim's own introspection API, including the
actual assembled matrix) is identical between the failing and succeeding
cases. The distinguishing factor is something inside DevSim's own Newton
solve path (or ViennaLS's narrow-band/signed-distance internals below
what's inspectable from Python) that two independently-designed
"redesign the floor export" attempts both failed to route around.
Further progress needs C++-level instrumentation of DevSim or ViennaLS,
not more Python-side experiments.

**Decision (explicit user instruction): stop here.** Do not touch PN
solver tolerance/damping/maximum_iterations — the existing 1e-6/100
settings (already documented as "looser than DevSim's own 1e-10/30
examples, confirmed necessary" even before this issue) are left as-is.
The floor fix (`io.py`) and the lifecycle cleanup fix are both kept.
Affects: Phase 8 specifically, and any future recipe doing a PN-junction
drift-diffusion I-V sweep through the floored mesh path. Does not affect
Phase 5/6/7/9/14 (Ohmic, doping/Poisson-only, MOS C-V, and the 2-step
flow test all pass with the floor fix — only the PN-junction
drift-diffusion continuity-equation solve is affected).

### PN junction (Phase 8) convergence — RESOLVED (later session)

Reopened per explicit user instruction ("실제 tcad도 수렴 문제 발생이 빈번하니" /
solve the previously-closed issue) after the earlier investigation
above had exhausted every Python-side hypothesis it tried (iteration
count, tolerance, floor depth, geometry, triangle quality, matrix
values, node ordering, OMP) and concluded "needs C++-level
instrumentation." Found via a different route: comparing against
DEVSIM's own official example rather than more Python-side probing of
this project's own code.

1. **What was tested:** Fetched DEVSIM's real official diode example
   from source (`github.com/devsim/devsim`,
   `examples/diode/diode_common.py`/`diode_1d.py` — via WebFetch, since
   the Context7 MCP connector the user first asked for is not
   authorized/connected in this environment; confirmed by
   `SearchMcpRegistry`/`SuggestConnectors` returning
   `installState: "not_installed"`). Found it grades its mesh down to
   1e-9..1e-7 cm (0.01-1nm) spacing right at the doping junction —
   this project's ViennaPS-derived mesh is uniform
   (`grid_delta_um=0.15` = 150nm everywhere). Computed the Debye length
   at this project's Phase 8 doping (donor=acceptor=1e18 cm^-3):
   `L_D = sqrt(eps_si * V_t / (q*N)) ~= 4.09nm` — the mesh is ~37x
   coarser than the depletion-region length scale.

   Ran three previously-untried isolated probes (same production
   recipe/domain/tolerances throughout, only ever varying ONE thing at
   a time): (a) `maximum_iterations` 100->300 — no change, residual
   plateaus at the same voltage; (b) bias-ramp continuation in
   0.05/0.02/0.01V sub-steps instead of jumping straight to each
   requested voltage — no change, fails at the same ~0.19-0.20V
   regardless of path; (c) **doping swept down at fixed mesh/domain/
   tolerances** (1e18 -> 1e16 -> 1e14 cm^-3, i.e. Debye length 4nm ->
   41nm -> 409nm against the same fixed 150nm mesh) — this one flipped
   the result cleanly.

2. **Result:** At 1e18 cm^-3 (37x mismatch) the sweep fails at V=+0.20
   exactly as before. At 1e16 cm^-3 (3.7x mismatch) and 1e14 cm^-3
   (well-resolved), the *identical* mesh/domain/solver settings
   converge all 8 sweep points cleanly. A separate uniform-refinement
   probe (whole mesh at grid_delta_um=0.08/0.02, same domain/doping)
   was NOT a clean fix: 0.08um failed *earlier* (V=+0.00) than the
   0.15um baseline (V=+0.20) — non-monotonic, consistent with
   ViennaPS's own triangle quality not being a monotonic function of
   grid_delta_um (already documented under "MakeTrench floating-point
   sensitivity" above) — while 0.02um got further (failed at V=+0.30)
   but cost 50k+ nodes and 260+ seconds and still didn't fully
   converge.

3. **What it proves:** The real root cause is mesh resolution *at the
   junction* relative to the doping's Debye length/depletion width —
   not floor depth, geometry, triangle quality (elsewhere), matrix
   values, node ordering, or OMP (all already ruled out above), and
   not fixable by uniformly refining the whole mesh (expensive, and
   not even reliably monotonic). This matches exactly why DEVSIM's own
   official example grades its mesh locally instead of using a uniform
   grid.

4. **Fix applied — local mesh refinement, not a doping or tolerance
   change** (`tcad/device/devsim/mesh_refine.py`, new module):
   standard "red-green" (regular/conforming) triangle refinement —
   triangles inside a window around a target position are split into 4
   (red); untouched neighbor triangles bordering a red triangle are
   split into 2 using the already-created shared-edge midpoint
   (green), which is what keeps the mesh conforming (no hanging
   nodes/T-junctions); any triangle that would need green-splitting on
   2+ edges is promoted to red instead (closure, iterated to a fixed
   point) — the standard rule that avoids degenerate slivers. Repeated
   passes (`levels`) progressively refine only the region still
   matching the window predicate, so the whole domain doesn't grow
   uniformly. Triangles never touched keep their original vertex
   indices unchanged (far-field mesh is bit-for-bit the input).

   Verified in isolation (`tests/unit/test_mesh_refine_mock.py`, no
   ViennaPS/DevSim needed — pure geometry) before wiring into
   production: area preserved exactly across 1-3 refinement levels, no
   edge ever shared by more than 2 triangles (conforming), far-field
   triangles provably unchanged, local edge length shrinks ~2x per
   level as expected, and a predicate matching nothing is a byte-exact
   no-op.

   Wired into `tcad/device/devsim/mesh_import.py`'s
   `import_process_result()` as four new **opt-in, default-None**
   parameters (`refine_near_um`, `refine_axis`, `refine_half_width_um`,
   `refine_levels`) — every existing caller that doesn't pass
   `refine_near_um` gets bit-for-bit the same mesh as before this
   change. `tcad/cli/run_pipeline.py`'s `_import_device()` reads the
   same four keys from the JSON config's `device` block (all optional,
   same defaults), and `examples/pn_junction_config.json` now sets
   `"refine_near_um": 0.0` (this recipe's known junction position).

   Defaults (`refine_half_width_um=0.1`, `refine_levels=4`) are
   real-execution-verified minimums for this project's own Phase 8
   recipe, not guessed: 0.05um half-width caught zero triangles
   (narrower than one original grid cell — a silent no-op, failed
   identically to no refinement at all); 0.08-0.1um both converged the
   full 8-point sweep at ~10.3k Si nodes / ~15-17s total (vs. the
   whole-mesh-refinement alternative's 50k+ nodes / 260s+ and still
   not fully converged); 3 refinement levels got through V=+0.3 but
   failed at the last point (V=+0.4); 4 levels converged all 8 points.
   A different doping level or grid_delta_um will need different
   values — this is a physical meshing parameter, not a fixed
   constant, per `mesh_refine.py`'s and `mesh_import.py`'s own
   docstrings.

5. **Verified, real ViennaPS 4.6.2 + DevSim 2.10.1, via the actual
   production entry points (not just isolated probes):**
   - `tests/integration/test_phase8_pn_junction_real.py`: PASSES.
     Forward current increases monotonically with bias, reverse
     current stays near-zero/blocking, and the dedicated equilibrium
     check still matches the analytic V_bi to the same tight tolerance
     as before (0.953719440 V both sides, unchanged) — refinement
     changed the mesh but not the physics being checked.
   - `tests/integration/test_device_lifecycle_repeat_real.py`: **all
     four tests A-D now pass**, including Test B (repeated PN-junction
     sweep via the real CLI `run_pipeline()` path, through
     `examples/pn_junction_config.json`'s new `refine_near_um` key) —
     previously the project's other permanently-failing test.
   - Full suite: **`tests/run_regression.py` -> 16 passed, 0 failed, 0
     skipped** — every previously-known failure is gone, no new
     regressions. This is the first 0-failed regression run recorded
     anywhere in this file.

6. **What remains uncertain:** the exact minimum mismatch ratio
   (mesh-spacing-to-Debye-length) needed for reliable convergence in
   general (only bracketed empirically for this one recipe: 37x fails,
   3.7x and lower converges); whether `refine_half_width_um`/
   `refine_levels` need to scale with doping/grid_delta_um
   automatically (currently a manual per-recipe parameter, not
   auto-derived from the doping profile even though
   `import_process_result()` could in principle read
   `result.doping.regions[i].junction_position_um` itself — left
   manual/opt-in deliberately, to keep this change's blast radius
   small and every other existing caller provably untouched); whether
   the same technique generalizes to `gaussian_implant` doping
   (continuous profile, no single sharp `junction_position_um`) or to
   doping levels much higher than 1e18 cm^-3 (would need a smaller
   `refine_half_width_um`/more `refine_levels`, unverified).

7. **Next smallest experiment (not done, out of scope for this
   round):** auto-deriving `refine_near_um`/`refine_half_width_um`
   from `ProcessResult.doping` directly inside `import_process_result()`
   (opt-in via a boolean flag) so callers don't have to compute/pass
   the junction position by hand, matching how `silicon_depth_um`
   already flows from `Wafer` through the recipe automatically.

### `auto_refine_from_doping` — ADDED, and mesh-refinement generalization to higher doping — CHARACTERIZED (later session, per explicit user instruction "지금 발생한 모든 문제를 해결해" / "solve all the problems that have occurred" — picks up items 6 and 7 above)

Item 7 above is now implemented, and item 6's open question (does the
mesh-refinement fix generalize to doping far above 1e18 cm^-3) is now
answered with real data, not left unverified.

1. **What was tested:** `tcad/device/devsim/mesh_import.py` gained
   `auto_refine_from_doping: bool = False`. When `True` and
   `refine_near_um` was not explicitly passed, it derives
   `refine_near_um`/`refine_axis` from the first `DopingRegion` in
   `result.doping` with a determinable position
   (`junction_position_um` for `step_junction`, `peak_position_um` for
   `gaussian_implant`), plus `refine_half_width_um`/`refine_levels`
   (each only when that argument was itself left at its own default
   `None`) from the region's doping concentration — using DevSim's OWN
   real `Permittivity`/`ElectronCharge`/`kT` constants
   (`devsim.python_packages.simple_physics`, not re-derived textbook
   values) to compute a real Debye length (`_debye_length_um`).

   First attempt (probe, not shipped): `refine_half_width_um =
   max(25*debye_um, 2*local_mesh_spacing_um)`. Reproduced Phase 8's
   1e18 cm^-3 convergence correctly (14791 Si nodes, all 8 sweep points
   converge) — but this was because the `2*spacing` floor dominated at
   `0.3um` regardless of doping (spacing = grid_delta_um = 0.15um for
   this recipe), NOT because of the Debye-scaled term; testing this
   revealed the floor was simply too generous, not that the formula
   was doping-aware in the way intended.

2. **Result (generalization to higher doping):** with `refine_levels`
   left fixed at its old default (4), the same recipe's doping swept to
   1e19/1e20 cm^-3 (10x/100x the original) **failed to converge** —
   confirming item 6's open question was a REAL gap, not just
   theoretical: widening the refinement WINDOW (`refine_half_width_um`)
   does nothing for local RESOLUTION; only more halvings
   (`refine_levels`) do, and a fixed final edge length (0.15/2^4 =
   9.4nm) is only ~2.35x the Debye length at 1e18 cm^-3 but
   7.4x/23.5x too coarse at 1e19/1e20.

   Added `refine_levels` auto-derivation: however many halvings bring
   the local edge length within 2.5x the Debye length (matching the
   ratio the verified-working 1e18/4-level case already sits at),
   capped at a maximum. **First cap tried (10) was not usable in
   practice**: going from 4 to 6 levels alone (same window) took the
   recipe's equation count from ~44k to ~588k (~13x for 2 extra levels,
   consistent with each level's ~4x local triangle-count growth
   compounding) — measured directly, not estimated; the Newton solve's
   residual oscillated without improving over 90+ iterations rather
   than diverging cleanly, wasting real compute time before this was
   caught and killed. **Lowered the cap to 5** and re-verified:

   | doping (cm^-3) | Debye length | derived levels | Si nodes | equations | result |
   |---|---|---|---|---|---|
   | 1e18 (baseline) | 3.99nm | 4 | 14791 | 44373 | **CONVERGED**, all 8 sweep points |
   | 1e19 (10x) | 1.26nm | 5 (capped) | 51239 | 153717 | **CONVERGED**, all 8 sweep points |
   | 1e20 (100x) | 0.40nm | 5 (capped) | — | 153717 | **DID NOT CONVERGE** — residual plateaued ~6e-6 across 47+ Newton iterations without improving, killed after 7+ minutes rather than let run indefinitely |

   `refine_half_width_um`'s floor was also corrected from `2x` local
   spacing to `0.7x` (still above the empirically-known "0.05 caught
   zero triangles, 0.08-0.1 converged" threshold, but without the
   3x-larger, no-benefit over-refinement the `2x` floor caused).

   Also verified: `auto_refine_from_doping`'s `gaussian_implant` branch
   (using `peak_position_um`/`peak_conc_cm3` instead of
   `junction_position_um`/`donor_conc_cm3`/`acceptor_conc_cm3`)
   correctly derives `refine_near_um=peak_position_um` and does not
   corrupt the doping mapping — re-ran
   `test_gaussian_implant_doping_real.py`'s own exact analytic-Gaussian
   check WITH `auto_refine_from_doping=True` (previously unrefined):
   still `0.000e+00` max relative error across all (now more numerous,
   5537-9853 depending on recipe) Si nodes, since NetDoping is
   evaluated per-node from that node's own real coordinate regardless
   of how many nodes exist. Note: a pure Gaussian implant (single sign,
   no superposition with a separate background doping in this
   project's current API) does not by itself form a sign-crossing PN
   junction the way `step_junction` does, so this check verifies the
   auto-derivation machinery and doping-mapping correctness for this
   doping kind, not a new convergence fix — `gaussian_implant` was
   never a documented convergence problem the way 1e18 `step_junction`
   was.

3. **What it proves:** `auto_refine_from_doping` genuinely
   generalizes the mesh-refinement fix from the one hand-tuned 1e18
   cm^-3 case up through at least 1e19 cm^-3 (10x) without a caller
   computing/passing anything by hand, and does so through the real
   production entry point, not a probe. It also has a real, now
   honestly-characterized ceiling: at 1e20 cm^-3 (100x), the current
   formula + level cap is insufficient, and this is NOT a bug to
   silently paper over with a higher cap — a higher cap was tried
   (10) and found to cost far more compute for questionable benefit
   before this session lowered it, so the boundary is a genuine
   cost/benefit limit of this project's UNIFORM-window red-green
   refinement approach (`mesh_refine.py`), not a tuning oversight.

4. **Production implementation:**
   - **`tcad/device/devsim/mesh_import.py`**: new `_debye_length_um`,
     `_estimate_mesh_spacing_um` (median triangle edge length — a
     grid_delta_um proxy, since this function only ever sees the
     already-written mesh, never the recipe that produced it), and
     `_derive_refine_from_doping` (returns
     `(refine_near_um, refine_axis, refine_half_width_um,
     refine_levels)` or `None`). `import_process_result()` gained
     `auto_refine_from_doping: bool = False`; `refine_half_width_um`'s
     default changed from a bare `0.1` to `Optional[float] = None`
     resolving to `0.1`, and `refine_levels`'s default changed from a
     bare `4` to `Optional[int] = None` resolving to `4` — both purely
     to distinguish "caller explicitly passed this value" from "let
     auto-derivation fill it in", with **zero behavior change** for
     every caller that doesn't pass `auto_refine_from_doping=True`
     (verified: `run_pipeline.py`'s own `import_process_result()` call
     always passes an explicit `refine_levels` value via
     `cfg.get("refine_levels", 4)`, never `None`, so it is provably
     unaffected).
   - New `tests/integration/test_auto_refine_from_doping_real.py`
     (permanent, lightweight — the expensive 1e19/1e20 sweep above was
     a one-time investigation, not made into an ongoing regression
     gate, matching how this project treats other expensive parameter
     sweeps like the LOCOS/Bosch investigations): verifies
     `auto_refine_from_doping=True` at the Phase 8 recipe's own 1e18
     cm^-3 doping reproduces the full 8-point converged sweep with NO
     manually-computed `refine_near_um`, and verifies the
     `gaussian_implant` branch's analytic-Gaussian match.

5. **Verified, real ViennaPS 4.6.2 + DevSim 2.10.1, through the real
   production entry points:** full regression —
   `tests/run_regression.py` → **19 passed, 0 failed, 0 skipped** (18
   before this addition's new test) — no regressions to anything else.

6. **What remains uncertain:** whether doping levels between 1e19 and
   1e20 (not swept, only the two endpoints were tested) have a sharper
   or gradual convergence boundary; whether a fundamentally different
   (graded/adaptive rather than uniform-window-then-halve) refinement
   strategy could reach 1e20 without the same node-count explosion —
   not attempted, `mesh_refine.py`'s red-green algorithm was used
   as-is; whether the `_AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO=2.5`/
   `_SPACING_FLOOR_MULTIPLE=0.7` constants are optimal or just
   "verified sufficient at the two tested doping levels, on the one
   grid_delta_um=0.15 recipe" — no independent grid-resolution sweep
   was done for this addition (unlike the original manual-refinement
   fix, which was only ever verified at this same one grid resolution
   too).

7. **Next smallest experiment (not done, out of scope for this
   round):** sweep `grid_delta_um` (not just doping) with
   `auto_refine_from_doping=True` to check the derivation generalizes
   across mesh resolutions, not just the one recipe's 0.15um; consider
   whether `_AUTO_REFINE_MAX_LEVELS` should itself be configurable per
   call rather than a fixed module constant, for a caller that
   explicitly wants to spend more compute to reach a doping level like
   1e20 that the default cap doesn't reach.

### `auto_refine_from_doping` — upgraded to GRADED refinement, 1e20 cm^-3 now converges (later session, per explicit user instruction to apply the doping-ceiling fix prototyped and reported the previous round)

Item 7 above (and the 1e20 cm^-3 ceiling characterized in the section
above it) is now resolved — not by raising the level cap further
(shown not to work), but by replacing the single-window-many-levels
refinement strategy with a telescoping/graded one.

1. **What was tested:** prototyped (isolated scripts, no production
   code touched, per explicit instruction to test first) a
   telescoping sequence of refinement windows — starting at the mesh's
   own existing local spacing and halving repeatedly, each halving
   applied as its OWN `refine_mesh_near(..., levels=1)` pass — instead
   of one wide window refined `N` times. Verified at 1e19 cm^-3 (must
   still converge, matching the already-working case) and 1e20 cm^-3
   (previously failed even at the level cap).

2. **Result:** both converged, and with FEWER total nodes than the old
   approach even where the old one already worked:

   | doping (cm^-3) | old (single-window) | graded | outcome |
   |---|---|---|---|
   | 1e19 (10x) | 51239 Si nodes, converged | **16025 Si nodes**, converged | 3.2x fewer nodes, same result |
   | 1e20 (100x) | did not converge (capped at level 5, residual plateaued ~6e-6 over 47+ iterations, killed after 7+ min) | **61725 Si nodes, CONVERGED all 8 sweep points** | previously-uncrossable ceiling now crossed |

   This also answers a question the previous investigation left open:
   whether 1e20's non-convergence was a pure mesh-resolution limit or
   a sign the underlying Boltzmann-statistics physics model
   (`devsim.python_packages.simple_physics`) breaks down at doping
   levels approaching Si's solid solubility limit. It was resolution —
   the graded approach reaches the SAME target local resolution
   (2.5x the Debye length) as the old formula intended, just far more
   cheaply, and converges cleanly with no other change.

3. **Why graded is cheaper:** the old approach's node count in the
   refined region grows close to `4^levels` (each level ~4x's the
   local triangle count), because the ENTIRE window gets every level.
   Graded refinement's outer rings (wide window, few halvings) and
   inner rings (narrow window, many cumulative halvings) mean only the
   innermost, smallest ring ever reaches the full target resolution —
   the SAME idea DEVSIM's own official diode example uses (grading the
   mesh down to sub-nm right at the junction, not uniformly).

4. **Production implementation:**
   - **`tcad/device/devsim/mesh_refine.py`**: new
     `graded_refine_mesh_near(points, triangles, tags, predicates)` —
     applies one `refine_mesh_near(..., levels=1)` pass per predicate
     in `predicates`, in order. `refine_mesh_near()` itself is
     UNCHANGED; this is purely a new way of calling it repeatedly.
   - **`tcad/device/devsim/mesh_import.py`**: `_derive_refine_from_doping()`
     rewritten to return `(refine_near_um, refine_axis,
     ring_half_widths: List[float])` instead of a single
     `(half_width, levels)` pair — `ring_half_widths` starts at the
     mesh's own estimated local spacing and halves until the target
     edge length (2.5x Debye length, unchanged from before) is
     reached, capped at `_AUTO_REFINE_MAX_RINGS = 20` (raised from the
     old `_AUTO_REFINE_MAX_LEVELS = 5` — safe to raise since each ring
     is cheap, unlike each uniform level). The old
     `_AUTO_REFINE_DEBYE_MULTIPLE`/`_SPACING_FLOOR_MULTIPLE` constants
     (used only by the superseded single-window half-width formula)
     were deleted, not kept as dead code.
   - `import_process_result()`'s `auto_refine_from_doping=True` path
     now calls `graded_refine_mesh_near()` directly instead of routing
     through the generic single-window `refine_near_um`/
     `refine_half_width_um`/`refine_levels` parameters — those three
     parameters keep their EXACT old behavior and meaning for the
     manual/explicit path (any caller passing `refine_near_um`
     directly, e.g. `run_pipeline.py` and
     `test_phase8_pn_junction_real.py`, is provably unaffected: a new
     `graded_refinement_applied` flag ensures the old single-window
     block only runs when graded refinement did NOT already run).
   - New mock-only coverage in `tests/unit/test_mesh_refine_mock.py`
     for `graded_refine_mesh_near` (conformity/area/far-field
     invariants, matches the existing `refine_mesh_near` checks; a
     3-ring graded call reaches the same minimum edge length as a
     3-level single-window call using 1180 vs 2860 triangles — the
     same ~2.4x reduction pattern seen in the real ViennaPS tests, at
     the pure-geometry level with no backend needed).

5. **Verified, real ViennaPS 4.6.2 + DevSim 2.10.1, through the actual
   production `import_process_result(auto_refine_from_doping=True)`
   entry point (not just the isolated prototype scripts from the
   previous round):** 1e19 cm^-3 — 16025 Si nodes, full 8-point sweep
   converged. 1e20 cm^-3 — 61725 Si nodes, full 8-point sweep
   converged. Both match the prototype's own numbers exactly. Full
   regression: **`tests/run_regression.py` → 19 passed, 0 failed, 0
   skipped** — including `test_auto_refine_from_doping_real.py`
   (now exercising the graded path for its existing 1e18 cm^-3 check;
   its `gaussian_implant` check's node count dropped from 9853 to
   2691 while still matching the analytic Gaussian formula exactly,
   0.000e+00 relative error) — no regressions to anything else.

6. **What remains uncertain:** whether `_AUTO_REFINE_MAX_RINGS = 20`
   is itself a real ceiling for some doping level beyond 1e20 (not
   tested); whether the graded approach generalizes across
   `grid_delta_um` values other than this recipe's 0.15um (same open
   item as before, still not attempted); the 1e19/1e20 verification
   above is NOT part of the permanent regression suite (too expensive
   to run every cycle, matching how this project treats other
   expensive parameter sweeps) — only the original 1e18 cm^-3 case
   stays as an ongoing regression gate.

### Oxidation — RESOLVED (this session)

ViennaPS oxidation itself appears correct where sufficient Si exists.

Mask-side oxidation matched Deal-Grove within about 2–5%.

**Root cause found:** `vps.Oxidation()` auto-creates a native-oxide seed
level set when none exists, at a hardcoded default
`initialOxideThickness_ = 0.002 um` (`psOxidation.hpp`), independent of
`gridDelta`. `tcad/process/oxidation/thermal.py` never called
`setInitialOxideThickness()`, so this 0.002um default was always used.
Confirmed by raw level-set A/B/C experiments (isolated from
`saveVolumeMesh`/DevSim entirely — this was NOT the same issue as the
Si≈2×gridDelta problem above): whenever seed thickness < gridDelta, the
level-set cannot resolve the seed interface — oxide growth stalls exactly
at the seed value at short times and the CFL solver fails to converge
(`RuntimeError: unable to find a converged CFL-limited step`) at longer
times. Whenever seed ≥ gridDelta, growth matches ViennaPS's own
`estimatePlanarOxideThickness()` (Deal-Grove) within 1.5–2.3% at
t = 0.05/0.1/0.2/0.4 hr, confirmed via both an isolated script and the
real `ThermalOxidation.run()` production path.

**Fix applied:** one line in `tcad/process/oxidation/thermal.py`, right
after `model.setTime(...)`:
```python
model.setInitialOxideThickness(max(0.002, recipe["grid_delta_um"]))
```
Mirrors ViennaPS's own `trenchOxidation.py` example
(`seed_thickness = max(oxideThickness, gridDelta)`). Floors the seed at
one grid cell; does not make it arbitrarily large (seed=4×gridDelta was
tested and produced a separate, unexplained +99.6% error at one
condition — bigger is not automatically safer).

Verified end-to-end through the real production entry point
(`registry.get("oxidation","thermal")` → `.run()`), not just an isolated
script.

**Still separate/unresolved:** whether this fix has any interaction with
masked (LOCOS-style) geometries — the seed-wrapping behavior over a mask
was observed to be physically questionable in one exploratory experiment
this session (oxide appeared to grow uniformly over the mask "field"
region too) but was not root-caused or fixed. Do not assume the one-line
fix generalizes to `mask_material` (LOCOS) recipes without separate
verification. **Confirmed reproducible crash (this session):**
`tests/integration/test_phase4_oxidation_real.py`'s
`thermal_locos_style_with_mask` variant segfaults — `solveElasticVelocity`
(mask traction/mechanics solve) fails to converge with the residual
exploding across ~13 CFL step-halving retries (1e15 → 1e76 → ...), then
crashes. Reproduced identically with `io.py` reverted to its pre-floor-fix
state, so this is independent of the `saveVolumeMesh` floor change — it is
LOCOS mask-mechanics specific. Not yet root-caused.

### DevSim / OpenMP runtime conflict — RESOLVED (this session)

Every test that reaches a real `devsim.solve()` call
(`test_device_lifecycle_repeat_real.py`, Phase 5/6/7/8/9/14) failed
immediately after printing `number of equations N`, with a native
(non-Python-catchable) error:
```
OMP: Error #15: Initializing libiomp5md.dll, but found libomp140.x86_64.dll already initialized.
```

**Root cause found (inspected the actual installed packages, not
guessed):** two different OpenMP runtimes get loaded in the same
process. `libiomp5md.dll` (Intel OpenMP) ships with the `intel_openmp`/
`mkl` packages (`.venv/Library/bin/`), pulled in as numpy's BLAS/MKL
backend, which DevSim's linear algebra depends on. `libomp140.x86_64.dll`
(LLVM OpenMP) ships bundled inside `viennals.libs`/`viennaps.libs`
directly. Whichever solve/compute step touches Intel's runtime *after*
ViennaPS has already loaded LLVM's runtime triggers Intel OpenMP's own
safety check, which refuses to double-initialize and aborts the process.
Confirmed independent of the `saveVolumeMesh` floor change beforehand:
reproduced byte-for-byte with `io.py` reverted to its pre-fix state.
Mesh generation and DevSim *import*
(`create_gmsh_mesh`/`add_gmsh_region`/`finalize_mesh`/`create_device`)
always completed successfully — only the native `solve()` step crashed.

**Fix applied:** two lines in `tcad/device/devsim/backend.py`, before
`import devsim`:
```python
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
```
This is Intel's own documented escape hatch for exactly this two-runtime
collision (named in the error message itself). Placed here specifically
because DevSim is the side that raises the error (its Intel-OpenMP-backed
solve happens after ViennaPS has already loaded LLVM's runtime in every
observed failure), so it must be set before `import devsim` runs.

**Verified:** every previously-crashing test now runs its `devsim.solve()`
to completion — `test_device_lifecycle_repeat_real.py` Test A (repeated
Ohmic solve), Phase 5 (ViennaPS→ProcessResult→DevSim→solve), Phase 6
(I-V sweep), Phase 7 (doping + Poisson solve, matches analytic built-in
potential for both doping signs), Phase 9 (MOS C-V sweep, produces
`mos_cv.csv/json/png`), and **Phase 14** (2-step oxidation→etch flow,
doped and solved in DevSim) — all now exit 0 and complete their real
solve. This clears Phase 14 (electrical verification) as a side effect.

**Separate, unrelated finding surfaced once this crash was out of the
way:** `test_device_lifecycle_repeat_real.py`'s Test B (repeated PN
junction I-V sweep) now reaches a genuine `devsim_py3.error: Convergence
failure!` in `pn_junction_iv_sweep.py`'s Newton solve — a real numerical
issue, not OMP-related (confirmed: happens deep inside a 99+ iteration
Newton loop, well past where solve() used to crash). Not yet
investigated; tracked under Physical benchmarks below since it belongs to
that stage, not this one. Also noted in passing, not yet acted on: a
`UnicodeEncodeError` in `test_device_lifecycle_repeat_real.py`'s own
print statements (an em dash character vs the Windows console's cp949
codepage) — cosmetic, worked around with `PYTHONIOENCODING=utf-8` for
this session's verification runs, not fixed in the test file itself.

### MakeTrench floating-point sensitivity — RESOLVED (this session)

`MakeTrench`'s `trenchWidth` argument is sensitive to floating-point
noise at the ~1e-16 level, in a way that is not a normal precision/rounding
concern:

- `trenchWidth = 0.6` (exact float literal) → mask window cut correctly.
- `trenchWidth = 1.3 - 0.7 = 0.6000000000000001` (float64 subtraction
  noise, off from 0.6 by ~1.1e-16) → **mask window is not cut at all**
  (mask covers the full domain, Si never exposed).

This matters because `ProcessStep.prepare_domain()`
(`tcad/process/base.py`) always computes
`trench_width_um = recipe["mask_right_um"] - recipe["mask_left_um"]` —
i.e. every recipe that reaches this code path is exposed to this trap,
depending on the specific numbers involved.

**Root cause characterized (not root-caused inside ViennaPS/ViennaLS
source — the bug lives in third-party C++ we don't control — but its
exact boundary was mapped empirically):** swept `trenchWidth` by tiny
perturbations around 0.6 at gridDelta=0.05 (where half-width 0.3 is
exactly grid-aligned: 0.3/0.05 = 6.0). Result is **non-monotonic and
razor-thin, not a normal tolerance threshold**:

| width | delta from 0.6 | cut correct? |
|---|---|---|
| 0.6 (exact) | 0 | yes |
| 0.5999999999999999 (1 ULP below) | −1.1e-16 | yes |
| **0.6000000000000001 (1 ULP above)** | **+1.0e-16** | **NO** |
| 0.600000000000001 (2 ULPs above, i.e. 10x further off) | +1.0e-15 | yes |
| 0.6001 | +1.0e-4 | yes |

Only that single exact ULP, in the upward direction, breaks the cut —
values both closer to and further from 0.6 are fine. A non-grid-aligned
control width (0.61) never breaks under the same perturbations. Also
gridDelta-dependent: the same buggy value (`1.3-0.7`) fails at
gridDelta 0.05 and 0.1, but is fine at 0.025 and 0.03 — consistent with
an interior HRLE/level-set rasterization edge case triggered only when a
box-cutout vertex's float64 bit pattern lands *just past* a grid-line
coincidence, not a principled geometric tolerance. This points at
`viennals::FromSurfaceMesh`'s point-classification/rasterization (used by
`GeometryFactory::makeBoxStencil`'s box cutout, read from
`psGeometryFactory.hpp`/`psMakeTrench.hpp` — neither does its own exact
comparison; the box's node coordinates go in as raw floats and the
instability appears once the mesh is rasterized onto the HRLE grid), but
the precise line was not pinned down inside ViennaLS's ~500-line
`lsFromSurfaceMesh.hpp` — not necessary once a robust upstream mitigation
was found (see below).

**Fix applied:** one line in `tcad/process/base.py`'s
`prepare_domain()`:
```python
trench_width_um=round(recipe["mask_right_um"] - recipe["mask_left_um"], 9)
```
9 decimal places is nanometer-scale precision on a micrometer-scale
recipe value — far finer than any real recipe needs — so this only
strips float64 arithmetic noise below that, it cannot change intended
geometry. `round(1.3 - 0.7, 9) == 0.6` confirmed.

**Verified:**
- The exact previously-broken recipe (`mask_left_um=0.7,
  mask_right_um=1.3`) now cuts the mask window correctly through the
  real production path (`DirectionalEtch().prepare_domain(recipe)`,
  checked via raw level-set — Mask has 0 nodes at the opening, Si is
  exposed there).
- Swept 7 representative `(mask_left_um, mask_right_um)` pairs, including
  this project's own `Wafer` dataclass default (`3.5, 6.5`): only 1 of 7
  had float noise before the fix (the already-known `0.7, 1.3` case) —
  confirms the trap is real but sporadic, and the fix is a safe blanket
  mitigation regardless of which specific numbers a recipe uses.
- Phase 1 (mock), 2 (etching), 3 (deposition), 13 (process flow)
  regression re-run after the fix: all still PASS — this shared code
  path (used by every single `ProcessStep`) was not disturbed for the
  already-working cases.

Scope check done, not just assumed: only `trenchWidth` is computed via
subtraction anywhere in this codebase (`trenchDepth_um` is hardcoded
`0.0`; `mask_height_um` comes directly from `recipe["pr_thickness_um"]`,
no arithmetic) — so no other geometry parameter needed the same fix.

### Etching (basic) — VERIFIED, no changes needed (this session)

Verified two of the seven registered etching models end-to-end through
the real production path (`registry.get("etching", <name>).run()`), raw
level-set measurement only (`viennals.ToSurfaceMesh`), `saveVolumeMesh`
never used for measurement, kept fully separate from the two unresolved
issues above.

**Directional (Anisotropic) Etching** (`tcad/process/etching/directional.py`):
API (`direction, directionalVelocity, isotropicVelocity, maskMaterial,
calculateVisibility`) matches `psDirectionalProcess.hpp`'s constructor
and the installed package's own `tests/directionalEtch/test_directional_2d.py`
exactly. Ran t = 0.5/1.0/2.0/4.0 s with the existing regression recipe
(`direction=[0,-1,0], directional_velocity=-0.1`): etch depth in the
opening matched `|v|×t` within ~0% at every time point, mask top
unchanged (protected), no lateral etch (expected — no isotropic
component set). No issue found.

**Follow-up (later session):** after finding directional *deposition*
silently stalled under ViennaPS's default `calculateVisibility=True`
(see "Directional deposition growth SHAPE — RESOLVED" below), checked
whether directional *etching* (same underlying `DirectionalProcess`
model, same unexamined default) has the same issue — it does **not**.
Swept `grid_delta_um` in `{0.2, 0.15, 0.1, 0.075, 0.05, 0.02}` at
t=4s and `deposition_time_s` in `{0.5,1,2,4}` at gd=0.05, comparing
`calculateVisibility=True` (default) against `False`: **identical
results at every point either way** — etch depth matches `|v|×t`
exactly at gd∈{0.1,0.075,0.05,0.02} regardless of the visibility flag,
and the same ~12-13% deviation appears at the two coarsest grids
(0.2, 0.15) *with or without* visibility calculation, confirming that
deviation is unrelated to `calculateVisibility` (a separate, already-
accepted class of coarse-grid noise, not a new issue). Conclusion:
`calculateVisibility`'s default is safe for directional etching as-is
— the deposition-side bug does not generalize here, and
`etching/directional.py` was left unchanged.

**Isotropic Etching** (`tcad/process/etching/isotropic.py`):
API (`rate, maskMaterial`) matches `psIsotropicProcess.hpp`'s constructor
and `tests/isotropicProcess/test_isotropic_2d.py` exactly. Ran t =
0.5/1.0/2.0/4.0 s: vertical etch depth matched `|rate|×t` within ~0% at
every time point; mask fully protected; lateral undercut present and
growing with time. Quantitatively checked the undercut profile against
the analytic quarter-circle prediction for a straight mask edge
(radius R = |rate|×t centered on the mask corner) — after correcting a
measurement artifact (see below), RMS error ≈ 1.6–1.8 grid cells,
worst-case error near the arc's tangent point (a known level-set
corner-smoothing effect, not a directional/sign bug). No issue found in
the model itself.

**Measurement pitfall found (not a production bug — a lesson for future
raw-level-set verification):** a naive "max-y per x-column" reading of
the Si level set's surface mesh is unreliable once undercut creates an
overhang — the Si level set's node list also carries the mask's own
contour (material-stacking bookkeeping, same root cause as the
oxidation investigation's "field region reflects the mask, not real Si"
finding), so `max(y)` at a column under the mask returns the mask
height and hides the real (lower) undercut surface at the same x.
Confirmed directly by dumping all y-values per column
(`diag_isotropic_full_column.py` pattern): a single x can legitimately
carry both the mask-height point and the true cavity-wall point at once.
Fix for measurement code: filter out points at/near the (known) mask
height before reducing per-column, or take `min(y)` instead of `max(y)`
when checking for undercut specifically.

### Bosch — VERIFIED / PASS, no code changes needed (this session)

Bosch cycle execution works:
- passivation
- breakthrough
- silicon etch
- repeated cycles

Etch depth increases with cycle count.

GUI rendering is NOT authoritative; inspect actual ViennaPS geometry.

**Code/API comparison vs official `examples/boschProcess/boschProcessSimulate.py`:
essentially 1:1 identical.** `tcad/process/etching/bosch_drie.py` matches the
official example in geometry setup (`MakeTrench(trenchDepth=0.0,
maskHeight=...)`), passivation model (`SingleParticleProcess(rate,
stickingProbability)`), breakthrough model (same `SingleParticleProcess`
with the rate sign flipped plus `sourceExponent` + `maskMaterial=Mask` —
the official example reuses `depositionThickness` the same way), etch
model (`MultiParticleProcess` + `addNeutralParticle` +
`addIonParticle(sourcePower=..., thetaRMin=60.0)` + a custom rate
function whose logic is identical: mask→0, `fluxes[1]*ionRate`, plus
`fluxes[0]*neutralRate` on Si), and per-cycle order
(`duplicateTopLevelSet(Polymer)` → deposit → punch through → etch →
`removeTopLevelSet()` + `removeStrayPoints()`). No API or algorithmic
deviation found.

**Runtime verification (raw level-set only, `saveVolumeMesh` never used
for measurement):** replicated `BoschDRIEEtch.run()` line-by-line with a
probe after each of the 4 per-cycle sub-steps. With the project's own
`BoschRecipe` defaults: cycles complete without error; floor etch depth
increases monotonically per cycle (increments 0.0365 / 0.0372 / 0.0379 /
0.0383 um); passivation inserts a Polymer level set covering the
structure; breakthrough removes the polymer specifically at the trench
floor (Polymer center-top becomes exactly equal to Si center-top while
sidewall polymer is retained) — all physically correct.

**Scalloping — root cause identified, NOT a code bug.** With the default
recipe the sidewall came out smooth/monotonic with no visible scallops,
reproducing the previously-recorded symptom. Distinguishing experiment:
the *same* production logic re-run with ViennaPS's own
`examples/boschProcess/config.txt` parameter VALUES (`ionRate=-0.1`,
`neutralRate=-0.2`, `etchTime=1.5`, `gridDelta=0.025`) produces **clear,
textbook periodic scalloping** — the sidewall repeatedly bulges outward
then cuts back in, with a period (~0.38–0.40 um) that matches the
per-cycle floor etch increment (0.425/0.411/0.402/0.393/0.386 um)
exactly.

The difference is parameter scale, not code: `tcad/core/models.py`'s
`BoschRecipe` defaults (`ion_rate=-0.02`, `neutral_rate=-0.01`,
`etch_time_s=1.0`, `grid_delta_um=0.05`) are 5–20× weaker in rate and 2×
coarser in grid than the official example, so per-cycle material removal
is only ~1.2 grid cells — below what the level set can resolve as a
distinct scallop. Scalloping is physically present in the model; it is
numerically unresolvable at that particular grid/rate combination.

**Decision: PASS. `bosch_drie.py` is left unmodified, and the
`BoschRecipe` defaults are deliberately NOT changed** — whether the
defaults should be retuned is a question about intended process
conditions (and what GUI users enter), not a correctness bug, and was
explicitly deferred. Further Bosch root-cause investigation is closed.

## GUI

GUI visualization is not authoritative for process geometry.

Actual ViennaPS mesh/output must be used to judge physical geometry.

### Si substrate depth input field — DONE (later session)

`Wafer.silicon_depth_um` was already wired into the recipe dict
(`tcad_2d_stagewise.py`'s `run_etch()`, `"silicon_depth_um":
self.wafer.silicon_depth_um`) from the earlier "Floor depth wiring"
work, but had no GUI input field, so every GUI-triggered run silently
used the `Wafer` dataclass default (5.0). Fixed: added a "Si substrate
depth (µm)" entry to the Lithography panel (next to PR
thickness/mask-opening fields, same `self._field(...)` pattern), wired
into `_read_lithography_fields()` (`self.wafer.silicon_depth_um =
float(self.depth_var.get())`), with a positive-value check matching the
existing mask-opening validation style. Verified headless (no Tk
mainloop): default field value matches the dataclass default (5.0);
typing a new value and running the first lithography step (PR coat, the
earliest step that calls `_read_lithography_fields()`) propagates it to
`self.wafer.silicon_depth_um`; a negative value is rejected with the
same `_read_lithography_fields() -> False` pattern the mask-opening
check already uses. Full regression re-run clean after this change (see
below).

### Directional RIE wired into the GUI — DONE (later session)

GUI's etch panel only ran Bosch DRIE (`worker_main()` hardcoded
`run_viennaps_bosch`); every other model was a UI placeholder. Fixed by
generalizing `worker_main()` to dispatch through
`process_registry.get("etching", config["_etch_model_key"])().run(...)`
(the registry indirection was already imported and half-commented-for
this — just not used). `run_etch()` now allows both "Bosch DRIE" and
"Directional RIE" (`etch_model_keys` dict), builds the matching recipe
per model, and added one new field ("Directional RIE etch rate") to the
etch panel; direction is fixed at `[0,-1,0]` (vertical etch, matches
this project's own etching convention) rather than exposed as a field,
since arbitrary-direction etch was not requested. Success/log messages
that assumed `result["cycles"]` (Bosch-only) now guard with `"cycles" in
result`. Deleted the now-unused direct `run_viennaps_bosch` import.
SF6/O2 and Isotropic etch remain placeholders (not wired this round).

**Verified:** headless smoke check (messagebox stubbed to avoid modal
block in a no-display run) drives `run_etch()` through the real
subprocess worker for both models against real ViennaPS —
`wafer.etched` becomes True for each. Full regression re-run: still 10
passed / 2 failed, identical pre-existing failures (Phase 8,
`test_device_lifecycle_repeat_real.py` Test B) — no new regressions.

**Isotropic etch and SF6/O2 wired too (same session, immediate
follow-up):** same pattern — added to `etch_model_keys`, one new
recipe-building `elif` branch each, one new field each (`Isotropic etch
rate`; `SF6/O2 ion/etchant/oxygen flux`, defaults matching
`test_phase2_etching_real.py`'s own values). The generic `worker_main()`
dispatch and the `"cycles" in result` log/success guards needed no
further changes — they already covered any registered etching model.
Verified the same way: headless smoke check now drives all 4 models
(Bosch, Directional, Isotropic, SF6/O2) through the real subprocess
worker; full regression re-run still 10 passed / 2 failed, same two
pre-existing failures. Remaining GUI etch placeholders: none — all 4
models in the combobox are real now.

### Isotropic deposition — ADDED (later session)

`tcad/process/etching/isotropic.py`'s own docstring had pre-announced
this ("a positive rate grows material, see
process/deposition/isotropic.py in a later phase") but the file never
existed — a genuine, previously-identified gap, not a new idea. Added
`tcad/process/deposition/isotropic.py`, mirroring the etching file
almost exactly: same `IsotropicProcess(rate, maskMaterial)` call, same
`ProcessStep` shape, only the docstring/convention flipped to expect a
positive rate (deposition/directional.py already established this same
positive-vs-negative convention split for `DirectionalProcess`, so this
isn't a new pattern either). Registered via
`tcad/process/deposition/__init__.py`. `test_phase3_deposition_real.py`
needed one new `RECIPE_OVERRIDES["isotropic"]` entry (its loop iterates
every registered model, so a new model without an override would
KeyError) and its hardcoded "ALL 5 DEPOSITION MODELS" string was changed
to read the actual count. README's model table/count updated (13 -> 14).

**Verified:** `test_phase3_deposition_real.py` passes against real
ViennaPS (`[isotropic] real ViennaPS run OK`, "ALL 6 DEPOSITION MODELS
RAN..."). Full regression re-run: still 10 passed / 2 failed, same two
pre-existing failures (Phase 8, `test_device_lifecycle_repeat_real.py`
Test B) — no new regressions. No GUI change needed/made — deposition
has no GUI panel at all, this is registry/CLI-reachable only, same as
every other deposition model.

### HBr/O2 etching — ADDED (later session)

Checked the installed ViennaPS 4.6.2 for etching/deposition-shaped
classes not yet wired into this project's registry
(`[n for n in dir(vps.d2) if 'Process' in n or 'Etch' in n or ...]`).
Found `HBrO2Etching` has an overload with the exact same parameter
names/defaults as the already-implemented `SF6O2Etching`
(`ionFlux, etchantFlux, oxygenFlux, meanIonEnergy=100.0,
sigmaIonEnergy=10.0, ionExponent=100.0, oxySputterYield=3.0,
etchStopDepth=...`) — smallest, least ambiguous next model to add (no
new parameter shape to design, straight mirror of sf6o2.py). Added
`tcad/process/etching/hbr_o2.py`, registered via
`tcad/process/etching/__init__.py`, `test_phase2_etching_real.py` needed
one new `RECIPE_OVERRIDES["hbr_o2"]` entry (same reasoning as the
isotropic-deposition addition above — its loop iterates every registered
model). Both Phase 2/3's hardcoded "ALL N MODELS" print strings were
changed to read the actual count (`len(results)`), so this stops
recurring every time a model is added. README's model table/count
updated (14 -> 15) and its stale "Bosch DRIE only" GUI description
corrected to match the actual current etch panel (4 models via
registry).

Other classes checked but NOT added (deliberately, to keep this a small
one-model addition, not a sweep): `CF4O2Etching` (extra `polymerFlux`
param, different shape), `SF6C4F8Etching` (different param names:
`meanEnergy`/`sigmaEnergy` not `meanIonEnergy`/`sigmaIonEnergy`),
`FaradayCageEtching` (needs a `Parameters` struct + `maskMaterials`
sequence, not the flat-kwarg style this project's models use) —
candidates for a future single-model addition each, not attempted now.

**Verified:** `test_phase2_etching_real.py` passes against real
ViennaPS (`[hbr_o2] real ViennaPS run OK`, "ALL 8 ETCHING MODELS
RAN..."). Full regression re-run: still 10 passed / 2 failed, same two
pre-existing failures — no new regressions. No GUI change made (etch
panel wiring is deliberately capped at the 4 models already done; adding
a 5th combobox entry was judged UI-design scope, out of bounds per
explicit instruction this round).

### SF6/C4F8 etching — ADDED (autonomous overnight session)

Mirrored `sf6o2.py`/`hbr_o2.py`'s file shape for `SF6C4F8Etching`
(`ionFlux, etchantFlux, meanEnergy, sigmaEnergy, ionExponent=300.0,
etchStopDepth=...`) — different chemistry (no O2), so no
oxygenFlux/oxySputterYield params, everything else identical pattern.
Added `tcad/process/etching/sf6_c4f8.py`, registered, one
`RECIPE_OVERRIDES["sf6_c4f8"]` entry in `test_phase2_etching_real.py`.
**Verified:** real ViennaPS run OK, "ALL 9 ETCHING MODELS RAN...". Full
regression: 10 passed / 2 failed, same two pre-existing failures, no new
regressions. No GUI change (per this round's scope — GUI etch panel
capped at the 4 models already done).

### CF4/O2 etching — ADDED (autonomous overnight session)

Same shape as sf6o2.py, plus `polymerFlux`/`polySputterYield` (CF4/O2
deposits a passivating polymer SF6O2Etching's chemistry doesn't model).
Added `tcad/process/etching/cf4_o2.py`, registered, one
`RECIPE_OVERRIDES["cf4_o2"]` entry. **Verified:** real ViennaPS run OK,
"ALL 10 ETCHING MODELS RAN...". Full regression: 10 passed / 2 failed,
same pre-existing failures, no new regressions.

### Faraday Cage Ion Beam Etching — ADDED (autonomous overnight session)

Discovered (by instantiating `vps.FaradayCageParameters()` directly)
that this is IBE (`ion_beam.py`) plus one extra top-level field
(`cageAngle`, default 0.0) — its nested `ibeParams` has identical
field names/defaults to `ion_beam.py`'s own `_PARAM_FIELDS`, so that
dict was reused verbatim (as `_IBE_PARAM_FIELDS`) rather than
redefined. Unlike `IonBeamEtching`, `FaradayCageEtching` has no
no-maskMaterials overload — always requires `maskMaterials`, so the
wrapper defaults it to `[Material('Mask')]` when the recipe omits
`mask_materials`, matching this project's existing mask-default
convention elsewhere. Added `tcad/process/etching/faraday_cage.py`,
registered, one `RECIPE_OVERRIDES["faraday_cage"]` entry.

**Verified:** real ViennaPS run OK, "ALL 11 ETCHING MODELS RAN...".
Full regression: 10 passed / 2 failed, same pre-existing failures, no
new regressions.

### KOH/TMAH crystallographic wet etching — ADDED (later session, per explicit user instruction to expand physical scope — "물리 범위 확장" — after the LOCOS mask-erosion fix shipped)

`wet_etching.py`'s own docstring had pre-flagged this exact gap
("[the crystallographic overload] can be added once real rate
constants are supplied") — `vps.WetEtching`'s second overload
(`direction100, direction010, rate100, rate110, rate111, rate311,
materialRates`) models orientation-dependent (KOH/TMAH) etching, but
was never wired in because this project's rule against fabricating
physical constants blocked it without a real, cited rate-constant
source.

1. **What was tested:** fetched ViennaPS's own official
   `examples/cantileverWetEtching/cantileverWetEtching.py`
   (github.com/ViennaTools/ViennaPS, via WebFetch) — it uses exactly
   this overload with real, cited rate constants ("30% KOH at 70°C",
   citing https://doi.org/10.1016/S0924-4247(97)01658-0):
   `direction100=[0.707106781187, 0.707106781187, 0.0]`,
   `direction010=[-0.707106781187, 0.707106781187, 0.0]`,
   `rate100=0.797/60.0`, `rate110=1.455/60.0`, `rate111=0.005/60.0`,
   `rate311=1.436/60.0` (um/s). That official example is **3D-only**
   (a GDS-mask cantilever release, `viennaps.d3`) — this project is
   2D-only, so before wiring these values into production this session
   ran an isolated probe: the same rate constants, through
   `vps.d2.WetEtching`'s crystallographic overload, on this project's
   own normal 2D trench geometry (`session.create_domain` +
   `session.make_trench`), etched for 60s.

2. **Result:** the model ran without error in 2D, and the resulting
   Si surface (read from the real, floored `save_volume_mesh()` export
   — not the raw level set) is a symmetric, faceted V-groove centered
   on the trench window — not a circular/isotropic undercut. Measured
   two independent, parameter-free physical checks against the real Si
   (111)/(100) KOH "magic angle" (54.7356°, a textbook crystallographic
   fact, not fit to this data):
   - Apex depth: 1.455um measured vs. 1.4142um predicted
     (`window_half * tan(54.7356°)` for a fully self-limited wedge of
     this window's half-width) — 2.9% off.
   - Sidewall angle: linear fit of the surface points on the clean
     single-facet region (excluding the apex, where two facets merge
     and grid discretization smooths the corner, and excluding the
     immediate mask-edge undercut-transition point) gives 55.91° from
     vertical vs. the real 54.7356° — 1.2° off, well within
     gridDelta=0.2um's discretization limit.

3. **What it proves:** the crystallographic overload works correctly
   through this project's own 2D geometry conventions (not just the
   official example's 3D one), and — using real, cited rate constants,
   not fabricated ones — reproduces the textbook KOH V-groove shape and
   angle to within a few percent / a couple degrees. This is the same
   distinguishing-signature methodology this project already uses for
   its other etch models (e.g. isotropic etch's quarter-circle undercut
   check).

4. **Production implementation:**
   - **`tcad/process/etching/wet_etching.py`**: `WetEtch.run()` now
     builds `vps.WetEtching` via the crystallographic overload when
     `"direction100"` is present in the recipe (mirroring how
     `"mask_material"` switches fin vs LOCOS in `thermal.py`), else the
     existing uniform per-material-rate overload — fully backward
     compatible, zero behavior change for every existing recipe/test
     that doesn't set `direction100`. New module-level constant
     `KOH_30PCT_70C`, the real cited rate-constant dict above, so a
     recipe can select this exact condition via
     `{**KOH_30PCT_70C, "material_rates": [...]}` rather than
     retyping the raw numbers.
   - New `tests/integration/test_koh_crystallographic_wet_etch_real.py`:
     runs the real production entry point
     (`registry.get("etching","wet_etching").run()`), then re-checks
     both physical signatures above (V-groove monotonicity + apex depth
     within 15% + sidewall angle within 8°) against the real exported
     mesh.

5. **Verified, real ViennaPS 4.6.2, through the actual production entry
   point:** `tests/integration/test_phase2_etching_real.py`'s existing
   `wet_etching` case (uniform overload, unchanged) still passes,
   confirming zero regression to the existing behavior. New
   `test_koh_crystallographic_wet_etch_real.py` passes all 4 checks.
   Full regression: **`tests/run_regression.py` → 18 passed, 0 failed,
   0 skipped** (17 before this addition's new test) — no regressions.

6. **What remains uncertain:** whether these exact rate constants
   (specific to 30% KOH at 70°C) generalize to other KOH
   concentrations/temperatures or to TMAH (a different real etchant
   with its own published rate constants, not sourced this session);
   whether the `direction100`/`direction010` vectors need to be
   recomputed for a mask orientation other than the official example's
   own (they encode a specific crystal-to-mask alignment); no GUI
   wiring (etch panel is deliberately capped at 4 models per earlier
   sessions' scope decisions, unchanged here).

### KOH/TMAH crystallographic wet etching — self-limiting V-groove NOT reproduced; the existing regression test passes for a coincidental reason, not the physics it claims (later session, test-only per explicit instruction, following up on item 6 above)

Attempting to answer item 6's open question (do these constants
generalize to other KOH concentrations/TMAH) surfaced a more basic
problem: the model does not actually reproduce self-limiting
(111)-faceted V-groove behavior in this project's 2D configuration at
all, which the original verification above did not catch because it
only ever checked one snapshot in time. Full test-by-test record
(tests 29-35) in `LOCOS_CHAINING_TEST_LOG.txt`.

1. **What was tested:** real TMAH rate constants could not be obtained
   (the paper that has them, Sato & Shikida, is paywalled; the one
   open-access candidate is blocked by this environment's egress
   proxy; installed ViennaPS ships no TMAH data) — so rather than a
   TMAH model, this swept the region TMAH occupies using the cited KOH
   constants plus the literature-reported (111)/(100) rate-ratio range
   (0.02–0.08, vs. this KOH set's 0.0063) as a robustness/sensitivity
   probe. A temperature-like axis (scale every rate by `s`, time by
   `1/s`) and a concentration-like axis (vary `rate111/rate100`) were
   both run through the real production `WetEtch.run()` entry point at
   several etch times, isolating each of the four plane rates
   individually, then fetching ViennaPS's official 3D example and its
   `psWetEtching.hpp` rate-selection source to explain what was found.

2. **Result:** the temperature-like axis is a clean pass — scaling all
   rates and inversely scaling time gives bit-identical geometry over
   an 8× range. The concentration-like axis found something real:
   `rate111` and `rate311` are **completely inert** — zeroing either
   changes nothing — while `rate110` dominates (zeroing it stops the
   etch outright) and depth grows exactly linearly in time, never
   self-limiting. Root cause, confirmed from `psWetEtching.hpp`'s own
   source (fetched, not guessed): this project's
   `direction100`/`direction010` were copied verbatim from the
   official example, whose depth axis is **z** (3D, infinite-`z`
   boundary), while this project's 2D depth axis is **y** — so
   `directions[2] = cross(direction100, direction010) = (0,0,1)`,
   and with the 2D solver forcing the normal's z-component to 0, the
   projection onto that axis (`N2`) is identically zero for every
   possible 2D surface normal, which algebraically removes `rate111`
   from the rate formula's reachable branch and multiplies `rate311`
   by zero. Not a ViennaPS bug — this project's axis choice.

   Derived the correct 2D pair analytically from the same source
   (`direction100(θ)=[cosθ,0,sinθ]`, `direction010(θ)=[sinθ,0,-cosθ]`
   keeps `directions[2]` on the depth axis for any θ; solving for when
   the true magic-angle condition `N0=N1=N2` is reachable shows
   **θ=45° is the unique rotation** where it can occur at all, and at
   that θ the condition reduces to exactly 54.7356° from vertical —
   the real magic angle falling out of the algebra, not fitted).
   Measured that this correction does revive `rate111` (no longer
   inert). But swept θ over the full 0–90° range regardless (each
   compared at `t` and `3t`, since self-limiting means bounded depth
   while unbounded growth means the ratio tracks the time ratio): every
   single angle gave the same ~3× growth, including θ=45° — the
   analytically correct rotation is not qualitatively different from
   any wrong one. A finer time series at θ=45° (`t`=30/90/270/810s)
   tracking the width of the near-apex flat region found it stays at
   essentially the *full window width* the entire time rather than
   narrowing to a point — there is no forming-then-failing V, there is
   no V at all; the whole window bottom advances as a near-uniform
   front the entire time, at a rate between `rate100` and `rate110`.

3. **What it proves:** the existing production test
   (`tests/integration/test_koh_crystallographic_wet_etch_real.py`,
   currently part of the passing regression suite) is passing for a
   coincidental reason. Its apex-depth check lands within 2.9% of the
   self-limited prediction only because, at its own chosen `t=60s`,
   `rate110 × 60s` (1.455um) happens to land close to
   `window_half×tan(54.7356°)` (1.4142um) — not because the model
   actually stopped etching there. Its sidewall-angle check cannot be
   measuring (111) faceting either, since `rate111` was completely
   inert under the vectors that test uses. This was not previously
   known — the original verification (item 2 above) checked only one
   time snapshot and read the agreement as validation. **Do not read
   the existing test's PASS as confirmation of real self-limiting
   KOH/TMAH physics** — it confirms the model runs and produces an
   anisotropic (non-circular) profile, nothing stronger.

4. **What remains uncertain:** why the model fails to hold a facet even
   at the one crystallographically correct rotation. The evidence
   (uniform-width front rather than a narrowing V, at every rotation
   and every time checked) points at something in ViennaLS's
   level-set advection/velocity-extension handling for this class of
   strongly anisotropic, concave-corner-forming problem — a
   ViennaLS-source-level question, not a recipe-parameter one.
   Confirming that would need reading `Advect`'s velocity-extension
   algorithm specifically, not attempted. TMAH itself stays moot until
   this is resolved: its distinguishing parameter is exactly the
   `rate111/rate100` ratio this investigation showed has no traction
   on the simulated shape at all.

5. **Next smallest experiment (not done, explicitly deferred by user
   instruction to stop and record rather than keep digging into
   ViennaLS internals this round):** fetch and read ViennaLS's
   `Advect` velocity-extension source to see how it treats a
   concave/convex kink where two slow-moving facets should meet, and
   whether that is a documented limitation or something to report
   upstream.

**No production code or existing test was changed for this
investigation** — test-only per standing instruction. The existing
KOH-etch feature (item 4 above) is unmodified and still ships; this
section exists so a future reader does not mistake the existing test's
PASS for validated self-limiting physics.

### Per-material etch selectivity — ADDED (later session, found by questioning a claim this file itself had made)

Found while verifying the LOCOS chaining fix, not by looking for it: a
test-log entry described a chained etch as "removing oxide and leaving
Si untouched." That was an interpretation, never a measurement, and it
turned out to be true for the uninteresting reason.

1. **What was tested:** etched a masked window covered by 0.2um of pad
   oxide at progressively greater depths (0.05 / 0.10 / 0.20 / 0.40um)
   through the real production `DirectionalEtch.run()`, at
   `grid_delta_um=0.05` so a 0.05um etch is a full grid cell.
2. **Result:** oxide loss tracks the requested depth exactly while oxide
   remains (0.0463 / 0.0941 / 0.1902 vs 0.05 / 0.10 / 0.20 × 1.0um
   window), then saturates at 0.1999 — the whole pad oxide gone. At that
   same 0.40um step Si loses 0.1835 (~0.18um deep) against a
   no-selectivity prediction of 0.20um, i.e. within ~1/3 of a grid cell.
3. **What it proves:** it was pure geometry, not selectivity. The etch
   removed only oxide at shallow depths because the oxide was in the
   way, and consumed Si at the identical rate the moment it punched
   through. This project's directional and isotropic etches had **no
   material selectivity at all** — one rate for every non-mask material
   — even though real etch chemistry is strongly selective (a real oxide
   etch runs 10:1 or better against Si) and the installed ViennaPS
   4.6.2 supports it.
4. **The trap, measured rather than assumed.** ViennaPS exposes
   per-material rates via `DirectionalProcess` overload 1
   (`materialRates: {Material: (directional, isotropic)}`) and
   `IsotropicProcess` overload 3 (`materialRates: {Material: rate}`) —
   and **the two disagree on sign with each other**:
   - `DirectionalProcess.materialRates`: **POSITIVE removes**, the
     opposite of its own single-velocity overload. A negative value
     removed exactly 0.0000 where a positive one removed the full
     0.2001.
   - `IsotropicProcess.materialRates`: **NEGATIVE removes**, matching
     its own single-rate overload (measured separately — bit-identical
     to the single-rate result).

   A wrong sign is a **silent no-op**, not an error. This project has
   already been bitten once by this class of trap on a different
   overload (see "Directional deposition — RESOLVED, was a real
   sign-convention bug").
5. **Production implementation:** optional `material_rates` recipe key
   on `tcad/process/etching/directional.py` and
   `tcad/process/etching/isotropic.py`, selecting the per-material
   overload; absent, both files behave exactly as before (every existing
   recipe/test is provably untouched — the new code is a separate
   branch). Recipes keep ONE convention — **negative removes**, matching
   every other model in `etching/` — so `directional.py` flips the sign
   on the way to ViennaPS and `isotropic.py` does not. Optional
   `default_directional_rate`/`default_isotropic_rate`/`default_rate`
   keys cover materials absent from the map (default 0.0, i.e. inert).
6. **Verified, real ViennaPS 4.6.2, via the real production entry
   points:** new `tests/integration/test_etch_selectivity_real.py`
   builds a real oxide-on-Si stack (real `ThermalOxidation.run()`),
   etches deep enough to clear the oxide, and compares selective vs
   unselective:
   - directional: Si depth 0.18349um unselective → **0.01842um** at
     10:1 (predicted 0.01835um) — ratio 9.96
   - isotropic: Si depth 0.24381um unselective → **0.02305um** at 10:1
     (predicted 0.02438um) — within one grid cell

   The test also asserts the selective recipe removes real oxide, so a
   sign regression (which would look like "the etch did nothing" rather
   than a crash) fails it loudly.
7. **What remains uncertain / not done:** deposition models were not
   given the same key (out of scope — this was an etch-selectivity
   change, and `deposition/directional.py`'s own sign handling would
   need its own separate measurement); the other etch models
   (`sf6o2`, `hbr_o2`, `cf4_o2`, …) have their own chemistry-specific
   parameter shapes and were not touched; only 10:1 at one grid
   resolution was verified, not a selectivity sweep.

### `GeometricTrenchDeposition` — ADDED (later session, per explicit user choice among named unimplemented features)

Previously skipped, in the "Autonomous overnight session — stopping
point reached" section above, specifically because its `bottomMed`/
`a`/`b`/`n` parameters had "no documented meaning found" and this
project's rule is to never guess at what an undocumented physical
parameter does. Resolved this round by reading the real C++ source
rather than continuing to guess.

1. **What was tested:** the installed ViennaPS 4.6.2 Python bindings
   (`.pyi` stub) confirm the constructor signature
   (`trenchWidth, trenchDepth, depositionRate, bottomMed, a, b, n`) but
   carry no explanation. Fetched ViennaPS's real C++ source from GitHub
   — `include/viennaps/models/psGeometricDistributionModels.hpp`'s
   `impl::TrenchDistribution` class, the thing this Python class
   actually wraps — and read every method body verbatim (constructor,
   `getSignedDistance`, `getBounds`, `prepare`), not a summary.
2. **Result — read directly from the algorithm, not guessed:**
   - `trenchWidth` is stored by the constructor and **read nowhere
     else in the class**, confirmed by checking every method. It has
     zero effect on the output.
   - `depositionRate` is **not a physical rate**. `getBounds()`
     returns `[-depositionRate, +depositionRate]` per axis — it's the
     half-width of the geometric search box the underlying
     `GeometricAdvectDistribution` uses to find candidate surface
     points. Verified directly: setting it smaller than the true
     required thickness does **not** clip cleanly — it produces a
     visibly **larger**, wrong deposit (measured ~2.65um where
     ~0.35um was expected, in an isolated probe).
   - `trenchDepth`/`bottomMed`/`a`/`b`/`n` together define thickness as
     a function of a surface point's own y-coordinate:
     `thickness = bottomMed` within one gridDelta of `y=-trenchDepth`
     (a real trench floor, if `trenchDepth` matches an actual recess);
     `thickness = a*(1-|y|/trenchDepth)^n + b` everywhere else —
     **peaking at y=0** (this project's wafer-surface datum) and
     decaying with `|y|` in *either* direction (up onto a mask/raised
     feature, or down into a trench). Verified against a real 2D
     trench+mask geometry: mask top (y=0.5) measured 0.1247 vs.
     predicted 0.125 (a=0.3, b=0.05, n=2); trench floor (y=-1.0,
     trenchDepth=1.0) measured 0.0998 vs. predicted bottomMed=0.1 —
     both within grid resolution.
   - The model has **no mask-material concept at all** — no such
     constructor parameter exists; it deposits everywhere in the
     domain purely by y-position.
   - Confirmed empirically that `Process(geometry, model).apply()`
     needs **no duration argument** — matches
     `tests/geometricProcessStrategy`'s own comment, fetched from
     ViennaPS's real test suite, that "geometric processes typically
     have zero duration".
   - Calling the model directly (no other step first) **merges** the
     deposit into whatever material already sits at the top of the
     domain's material stack — verified: `getMaterialsInDomain()` was
     unchanged before/after. This matches every OTHER model already in
     `tcad/process/deposition/` (none of them tag a distinct material
     either), so it was kept as the default. An optional `material`
     recipe key opts into `duplicateTopLevelSet()` first (the same
     pattern `bosch_drie.py` already uses for its own polymer layer),
     verified to give the deposit its own separately-tagged,
     separately-measurable region.
3. **What it proves:** the parameter meanings were genuinely
   recoverable without fabricating anything — this was a documentation
   gap in the Python bindings, not an inherently ambiguous API. All
   seven constructor values now have a source-verified, testable
   meaning.
4. **Production implementation:**
   `tcad/process/deposition/geometric_trench.py` (new), registered as
   `("deposition", "geometric_trench")`. Recipe keys: `reference_depth_um`
   and `deposition_rate_um` required (no invented defaults for a
   parameter that silently produces wrong results if too small);
   `bottom_med_um`/`a_um`/`b_um` required (no default that could look
   like a real calibrated value); `n` optional, defaults to ViennaPS's
   own default (1.0 — a pure shape exponent, not a physical constant,
   so reusing the library's own default is not a fabrication);
   `material` optional. `trenchWidth` is not exposed as a recipe key at
   all (confirmed dead, see above) — passed as a fixed placeholder
   internally, with a comment citing the source finding.
5. **Verified, real ViennaPS 4.6.2, through the actual production entry
   points:** `tests/integration/test_phase3_deposition_real.py`'s
   registry-driven sweep (now `len(results)`-reported, no hardcoded
   count) passes with the new model included. New
   `tests/integration/test_geometric_trench_deposition_real.py`
   confirms, through `registry.get("deposition","geometric_trench").run()`:
   the `material` key gives the deposit its own distinct tag (Mask
   still separately present, not absorbed); and the field/mask-top
   thickness matches the source-verified formula (measured 0.1247um vs.
   predicted 0.1250um). Full regression: **`tests/run_regression.py` →
   22 passed, 0 failed, 0 skipped** (21 before this addition's new
   test) — no regressions. README's model table/count updated (18 →
   19).
6. **What remains uncertain:** whether `bottom_med_um`/`a_um`/`b_um`
   generalize as *the* right way to express a real non-conformal
   deposition process a user has in mind (they're shape knobs, not
   published material constants the way the KOH rate constants were —
   there is nothing to cite here, by the nature of the model); no GUI
   wiring (deposition has no GUI panel at all, same as every other
   deposition model in this project).

### Gaussian-implant doping — ADDED (autonomous overnight session)

`tcad/physics/doping.py` and `tcad/device/devsim/doping_mapping.py` had
both explicitly pre-scoped this exact feature in their own docstrings
("Future extension point: gaussian_implant... would add
position-dependent fields to DopingRegion and a new
apply_gaussian_implant()-style builder... without needing to change
ProcessResult"), but it was never implemented (a `NotImplementedError`
guarded any `kind` other than `uniform`/`step_junction`). Implemented
exactly as pre-scoped:
- `tcad/mesh/interface.py`: `DopingRegion` gained
  `peak_conc_cm3`/`peak_position_um`/`straggle_um` (reuses the existing
  `junction_axis` field for the position axis — no new axis field
  needed). No other `ProcessResult`/`DopingProfile` shape change.
- `tcad/physics/doping.py`: new `apply_gaussian_implant_doping(result,
  region, junction_axis, peak_position_um, straggle_um, peak_conc_cm3)`,
  same shape as `apply_uniform_doping`/`apply_step_junction_doping`.
- `tcad/device/devsim/doping_mapping.py`: new `elif doping.kind ==
  "gaussian_implant"` branch, sets `NetDoping` directly to
  `peak*exp(-((axis-position)^2)/(2*straggle^2))` (confirmed `exp`/`^`
  are real DevSim equation-parser functions by finding them used in
  `devsim/python_packages/simple_physics.py`, not guessed) — no
  Donors/Acceptors split, since a Gaussian implant isn't a donor/acceptor
  pair the way step_junction is (matches how "uniform" sets NetDoping
  directly too).

**Verified (new test, `tests/integration/test_gaussian_implant_doping_real.py`,
now part of the permanent regression suite):** real ViennaPS isotropic
etch -> `apply_gaussian_implant_doping` -> DevSim import -> `apply_doping`,
then DevSim's own evaluated `NetDoping` node values compared node-by-node
against the analytic Gaussian formula computed independently in Python
from each node's real DevSim `x` coordinate — **exact match, 0.000e+00
max relative error across all 550 Si nodes**. This checks DevSim's actual
equation evaluation, not just "doesn't crash". (Does not run a full
Poisson/drift-diffusion solve — that would need picking a specific
electrical check, judged out of scope for this addition; the NetDoping
mapping itself is what was unimplemented and is now verified.)

Also wired into the CLI: `tcad/cli/run_pipeline.py`'s `_apply_doping()`
gained one `if kind == "gaussian_implant":` branch (same shape as the
existing uniform/step_junction branches), and README's CLI config schema
doc updated to document the 3 new JSON fields
(`peak_position_um`/`straggle_um`/`peak_conc_cm3`) — otherwise the
feature would exist in `tcad.physics.doping` but be unreachable from the
CLI, the main way this project's features are meant to be used per
README's own examples.

Full regression re-run after the CLI wiring too: still **11 passed / 2
failed**, same two pre-existing failures (Phase 8,
`test_device_lifecycle_repeat_real.py` Test B) — no new regressions. No
GUI change (doping has no GUI panel at all, same as every deposition
model).

### Autonomous overnight session — stopping point reached (later session)

After the additions above (hbr_o2, sf6_c4f8, cf4_o2, faraday_cage
etching; isotropic deposition; gaussian_implant doping + CLI wiring),
checked for further small/clear gaps and found none that clear this
project's own bar without either fabricating physical data or starting
a large new design:
- `wet_etching.py`'s own docstring names a crystallographic (KOH/TMAH)
  overload as addable "once real rate constants are supplied" — this
  project's stated principle throughout is to never fabricate physical
  constants, and no real calibration data is available here, so this
  was left alone rather than guessed.
- `tcad/characterization/__init__.py` names Vth/subthreshold-slope
  extraction as future work — this needs an actual MOSFET transfer
  (Id-Vgs) sweep, not just an extension of the existing MOS *C-V*
  capacitor structure, i.e. new device geometry/equation design at
  roughly Phase 7/8's own scale — judged too large for this "smallest
  next feature" loop, not attempted.
- `GeometricTrenchDeposition` (ambiguous `bottomMed`/`a`/`b`/`n` tuning
  params, no documented meaning found) and `CSVFileProcess` (needs an
  external rates file) were checked earlier and already skipped for the
  same reason — no confident default without guessing.

Also fixed two now-stale doc comments found in passing (not new
features): `resistor_equation.py`/`iv_sweep.py` said "doping is not
implemented yet" / "future work" — false since Phase 7 added doping and
this session added gaussian_implant; corrected to explain
resistor_equation.py is *intentionally* doping-free (Ohmic-only,
Phase 6), with the doping-aware path living in
`semiconductor_equation.py`/`pn_junction_iv_sweep.py` instead.

**Final state this session:** `tests/run_regression.py` → **11 passed,
2 failed**, the same two pre-existing, already-investigated failures
(Phase 8 PN-junction convergence; `test_device_lifecycle_repeat_real.py`
Test B, same root cause) — no regressions introduced across the entire
sequence of changes above. Etch/Deposition registry model counts: 11
etching (was 7 at session start), 6 deposition (was 5). Doping kinds: 3
(was 2). Stopped here per the explicit instruction not to force further
features that would require guessed physical constants or a large new
design — remaining OPEN items (LOCOS physical validation, directional
deposition benchmark, Phase 8 PN junction) intentionally untouched.

### GUI: real ViennaPS mesh rendering (replaces white-rectangle placeholder) — ADDED (later session)

User asked why isotropic etch showed no undercut in the GUI. Root
cause: `redraw()`'s etched-state drawing was a plain white rectangle
sized from `mask_left_um`/`mask_right_um`/`cycles` — identical for every
etch model, never reading the real ViennaPS mesh (the code's own comment
already said so: "the white opening here only communicates the process
state; it is not pretending to be the numerical ViennaPS surface").

Added `TCADApplication._draw_real_mesh_result()`: reads
`self.last_final_mesh` (the real `.vtu` from the last successful
`run_etch()`, now stored — previously discarded) with meshio, reusing
the exact triangle/`"Material"`-cell_data access pattern already
established in `tcad/mesh/viennaps_adapter.py`'s `build_process_result`
(not a new pattern), and draws each triangle as a filled canvas polygon
colored by material (Si/Mask/SiO2/Polymer). Mesh y=0 (confirmed
throughout this project as the original wafer surface) lines up with
the existing `surface_y` so it matches the lithography drawing above it.
Falls back to the old placeholder rectangle if anything about reading
the mesh fails (meshio/ViennaPS unavailable, no file yet, degenerate
bounds, etc.) — `_draw_real_mesh_result` never raises, always returns
True/False.

**Performance guard (not a design change):** `redraw()` runs on every
window resize (`<Configure>`, bound in `__init__`), rebuilding the whole
canvas from scratch each time. A fine `grid_delta_um` combined with the
default ~5um `floor_depth_um` can produce 10000+ triangles (confirmed:
11436 for a 0.1um-grid isotropic-etch smoke run), which would make
resizing visibly stutter. Added a fixed cap (`_MAX_RENDERED_TRIANGLES =
2000`) with uniform decimation (every Kth triangle) when exceeded — a
performance safety valve, not a judgment about which part of the
geometry to prioritize.

**Verified:**
- Headless smoke test: real ViennaPS isotropic etch (grid_delta=0.1,
  etch_time=2.0) through `run_etch()`'s real subprocess path, then
  confirmed the canvas actually contains real-mesh polygons (1905, under
  the cap) and the "REAL VIENNAPS MESH" label, NOT the placeholder
  "VIENNAPS RESULT" text.
- Separately confirmed the fallback path: with `last_final_mesh = None`,
  `redraw()` still renders the placeholder rectangle correctly (old
  behavior fully preserved for the case the new code can't handle).
- Full regression: 11 passed / 2 failed, same two pre-existing failures
  — no new regressions.

### GUI: Si cross-section rendering as a stray small triangle — ROOT-CAUSED AND FIXED (later session, reported by the user: "실리콘 기판 단면에 작은 직각삼각형으로 표현이 된다" / "the Si substrate cross-section renders as a small right triangle")

1. **What was tested:** first hypothesis (wrong, corrected by the user)
   was that the etched amount itself was too small to resolve at the
   GUI's literal default field values (isotropic rate=0.05um/s,
   time=1.0s = exactly 1 gridDelta of etch — confirmed real and
   separately worth fixing, see below, but NOT what the user was
   describing). The user clarified the actual symptom: the Si
   substrate itself — not the etched notch — renders as a small stray
   right triangle instead of its real cross-section. Reproduced
   directly: ran a real isotropic etch (grid_delta=0.05,
   x_extent=10.0, silicon_depth_um=5.0 — the GUI's own default field
   values) through the real production `IsotropicEtch.run()`, then
   replicated `_draw_real_mesh_result()`'s exact decimation logic
   (`triangle_data[::step]`, the "every Kth triangle" mechanism from
   the section above) against the real exported mesh.

2. **Result:** Si is meshed as 39394 uniformly-sized triangles
   (area=0.00125 each, matching `gridDelta^2/2`) spanning its true
   y-range `[-5.000, -0.001]`. After the OLD positional-stride
   decimation (step=23, applied to the combined Mask-then-Si array),
   the SURVIVING Si triangles were confirmed to cluster almost
   entirely in the thin band `y=[-5.0, -4.95]` — the very bottom
   (floor) edge only, NOT spread across the true full extent. This
   directly reproduces the reported bug: with only a thin sliver near
   the floor surviving decimation, the rendered "Si cross-section" is
   effectively just a few small triangles near the bottom, which is
   what looked like a stray small right triangle instead of the whole
   substrate. Root cause: the exported mesh's triangle ORDER is not
   spatially uniform (a real characteristic of `saveVolumeMesh()`'s
   output, not assumed), so a fixed ARRAY-INDEX stride reproduces
   whatever ordering bias already exists in the file — it does not
   sample representatively across the shape's true spatial extent.

3. **What it proves:** the bug is in the GUI's decimation strategy,
   not in ViennaPS/the mesh export itself (the full, undecimated mesh
   is geometrically correct — confirmed by its true y-range matching
   expectation exactly) and not in anything from the earlier LOCOS/
   auto-refine-from-doping work this session (that work never touches
   `tcad_2d_stagewise.py` — completely separate files). Pre-existing
   since the mesh-rendering feature was first added.

4. **Fix applied — `tcad_2d_stagewise.py`'s `_draw_real_mesh_result()`:**
   replaced the positional stride with PER-MATERIAL RANDOM sampling:
   group triangle indices by material tag first, then for each
   material independently take a `random.Random(0).sample(...)` subset
   sized proportionally to that material's own share of the total
   triangle count (capped at `_MAX_RENDERED_TRIANGLES` overall). Fixed
   seed (0) keeps repeated redraws of the same mesh (e.g. window
   resizes, which call `redraw()` on every `<Configure>` event)
   visually stable rather than flickering between different random
   subsets. Per-material allocation also fixes a second, related risk
   the old combined stride had: a material with few triangles (e.g.
   Mask) could be crowded out entirely by one with many (e.g. Si) in a
   single combined stride — now every present material keeps a
   proportional share by construction.

5. **Verified:** re-ran the same reproduction (real isotropic etch,
   GUI default field values) with the fixed algorithm (copied
   verbatim from the actual edited file into a standalone check, not
   re-implemented separately): kept Si triangles' y-range is now
   `[-5.0, -0.0006]` — matching the TRUE full Si y-range
   (`[-5.000, -0.001]`) almost exactly, no longer clustered near the
   floor. Per-material proportional allocation confirmed too: Mask
   (13% of total triangles) got 260 of the 2000-cap (13.0%), Si (87%)
   got 1740 (87.0%). **Could NOT verify inside an actual running
   Tkinter GUI** — this container has no `tkinter` installed at all
   (`ModuleNotFoundError` even just importing it), so the fix is
   verified at the algorithm level (proven correct against real
   ViennaPS mesh data, same as `redraw()` would receive) but not via
   an actual on-screen render in this environment. `ast.parse()`
   confirmed the edited file is still syntactically valid.

6. **Separately confirmed real, but NOT what the user was
   describing — left uncorrected (a UX/default-value question, not a
   rendering bug):** the GUI's literal default field values (isotropic
   rate=0.05um/s, time=1.0s) etch exactly 1 gridDelta of depth, which
   real execution confirmed produces an almost-unmeasurable actual
   etch (-0.0004um, i.e. numerical noise, not a real signal) — the
   same "sub-grid-cell change doesn't resolve" limitation already
   documented elsewhere in this project (oxide seed thickness, mesh-
   refinement minimum window). At 5x the default time (5.0s), the same
   recipe etches a real, measurable 0.16um. Not fixed this session —
   flagged as a legitimate but separate default-value/UX question,
   left for the user to decide whether the GUI's defaults should
   change.

7. **What remains uncertain:** whether `tkinter` needs to be installed
   in this container for genuine end-to-end verification, or whether
   this GUI is only ever run in a different (e.g. Windows) environment
   per this file's own earlier session history; whether other GUI
   rendering paths (deposition/oxidation have no panel; doping has
   none either) have similar undiscovered decimation-adjacent issues
   — not audited, only the etch panel's Si-rendering bug was
   investigated, since that's what was reported.

Still not attempted (deferred, matches "no UI redesign" instruction):
zooming/panning the real-mesh view, a legend for material colors,
rendering it during etch-panel-only categories (deposition/oxidation
have no GUI panel at all, unchanged).

**Follow-up check:** also smoke-tested Bosch DRIE (multi-material
Si+Polymer+Mask, exercising the color map beyond isotropic etch's
Si+Mask) through the same real-mesh render path — 1465 real polygons
drawn, "REAL VIENNAPS MESH" label present, no crash. Confirms the
rendering generalizes across models, not just the isotropic case the
question was originally about.

### GUI: etch panel now shows only the fields the selected model actually uses — FIXED (later session, per explicit user observation "에칭 종류를 선택하면 그 종류에 맞게끔 입력할 수 있는 파라미터가 바뀌어야 하지 않을까?")

1. **What was tested:** read `_make_etch_panel()`/`run_etch()`
   directly rather than guessing. Confirmed: all 12 model-specific
   fields (7 Bosch-only, 1 Directional-only, 1 Isotropic-only, 3
   SF6/O2-only) were created with `frame` as their parent and packed
   unconditionally, so every field was visible regardless of which
   model the "Etch process" combobox had selected — e.g. selecting
   "Isotropic etch" still showed all 7 Bosch fields (cycles, polymer
   rate/sticking, ion exponent, ion/neutral Si contribution, neutral
   sticking) even though `run_etch()`'s `elif model_key == "isotropic"`
   branch never reads any of them.
2. **Root cause:** the combobox was never wired to anything besides
   `run_etch()`'s own recipe-building branch — nothing updated field
   visibility when the selection changed, because nothing was written
   to do so.
3. **Fix applied — `tcad_2d_stagewise.py`'s `_make_etch_panel()`:**
   the two fields every model actually uses (`grid_var`, `etch_time_var`)
   stay directly in `frame`, unconditionally visible, right after the
   combobox. The 12 model-specific fields were moved (not
   reordered within their own group, just re-parented) into four
   `ttk.Frame` groups (`bosch_frame`, `directional_frame`,
   `isotropic_frame`, `sf6o2_frame`), all four living inside one fixed
   `etch_params_container` frame that is itself packed exactly once.
   New `_update_etch_field_visibility()` packs only the group matching
   `self.etch_model.get()` and calls `pack_forget()` on the other
   three; `self.etch_model.trace_add("write", ...)` calls it on every
   combobox change, and it is also called once at panel-build time so
   the initial "Bosch DRIE" default shows only Bosch's own fields.
   Deliberately did NOT pack each group frame directly into `frame` —
   Tkinter's pack manager moves a widget to the END of its parent's
   pack order every time it's re-packed after `pack_forget()`, which
   would push whichever group the user last selected below the
   already-packed etch button/log panel. Routing all four groups
   through one single always-packed container sidesteps this entirely,
   since at most one of its children is ever visible at once.
   `run_etch()` itself needed no changes — the hidden fields' `tk.
   StringVar`s keep their values regardless of whether their Entry
   widget is currently packed, so whichever `elif model_key == ...`
   branch runs still reads the correct value.
4. **Verified:** `ast.parse()` confirms the edited file is still
   syntactically valid. The show/hide logic itself was checked by
   manual trace against documented Tkinter pack-manager semantics
   (`pack_forget()` on an unpacked widget is a safe no-op; child
   widgets can be packed into a frame before that frame itself is
   packed into its own parent; a `StringVar`'s value survives its
   widget being unpacked) — **could NOT be verified with an actual
   on-screen render**, since this container still has no `tkinter`
   installed (same standing blocker as the earlier Si-cross-section
   rendering fix above — `python3.11-tk` install remains blocked by
   the environment's outbound proxy policy).
5. **What remains uncertain:** whether the visual result (spacing,
   any residual layout jump when switching models) looks right on an
   actual screen — same category of unverified-by-rendering risk as
   every other GUI change this session, for the same environment
   reason.

### CLI end-to-end verification, real entry point — DONE (later session)

Everything in the previous entries was verified via direct Python
function calls (registry.get(...).run(), apply_gaussian_implant_doping,
etc.) or integration test scripts — never the actual documented CLI
entry point (`python -m tcad.cli.run_pipeline <config>.json`), which
README presents as the primary way to use this project and which this
session edited directly (`_apply_doping`'s new `gaussian_implant`
branch). Ran both for real:
- `examples/ohmic_iv_config.json` (pre-existing, unmodified) — ran
  clean, produced `iv.csv` with the expected linear-in-voltage,
  equal-and-opposite-at-both-contacts I-V curve.
- New `examples/gaussian_implant_iv_config.json` (added this session,
  mirrors the existing example) exercising the new `"doping":
  {"kind": "gaussian_implant", ...}` config block through the real CLI
  — ran clean end-to-end, confirming the CLI wiring added earlier this
  session is not just reachable in principle but actually works via the
  real entry point. README's CLI example section and project-layout
  listing both updated to mention it.

Generated run output (`examples/tcad_run/`) was deleted after each
check — it's the CLI's own regenerable artifact directory, not tracked
in git, not something to leave lying around.

Full regression re-confirmed after this (docs/example-only change, no
`tcad/` code touched): 11 passed / 2 failed, same two pre-existing
failures.

### Directional deposition — RESOLVED, was a real sign-convention bug (later session)

Reopened per explicit instruction to review this OPEN item properly
(after the earlier session's ambiguous raw-level-set reading was
deliberately not chased further). Root-caused this time using the
correct methodology: measured via the real, **floored** exported volume
mesh (`save_volume_mesh()`, same as production) instead of the raw
in-memory level set. This matters because the raw level set's "bottom"
edge (y_min) is an arbitrary narrow-band artifact for a semi-infinite
region — this project's own original Si-thickness investigation
(top of this file) already established that a raw, un-floored Si level
set only resolves ~2xgridDelta before floor-fixing — so the earlier
session's "bottom moved by velocity x time" reading was that artifact
shifting, not real growth. With the floored measurement, growth at
`direction=[0,1,0], directional_velocity=+0.1, t=1..3s` was confirmed
genuinely ~0 (Si top delta -0.0005 to -0.0009, not scaling with time),
and no new material appeared — the deposition step was doing nothing.

**Real root cause, confirmed by a bounded direction/velocity sign sweep
(4 combinations, same production path, not a physical-parameter
sweep):** ViennaPS's `DirectionalProcess.directionalVelocity` sign
convention is the *opposite* of what `deposition/directional.py`
assumed. Empirically: material grows when `direction . directionalVelocity
< 0` and erodes when `> 0` — confirmed consistent with this project's
own already-verified Etching convention (`direction=[0,-1,0],
directionalVelocity=-0.1` etches: product = (-1)(-0.1) = +0.1 > 0,
matches the erode rule). `isotropicVelocity` was checked separately and
does **not** have this problem — positive genuinely grows, no
transformation needed; only `directionalVelocity` was inverted.

**Fix applied:** one line in `deposition/directional.py` —
`"directionalVelocity": -recipe["directional_velocity"]` (was passed
through unchanged). Module docstring updated with the full empirical
finding. `isotropic_velocity` is passed through unchanged (unaffected).

**Verified:** new permanent regression test
`tests/integration/test_directional_deposition_growth_real.py` —
`directional_velocity=+0.1` now grows Si by `+|v|*t` at t=0.5/1/2/4s
against the real floored mesh, max relative error 2.0e-4 across all
four points (matches the rigor already used for the Etching
counterpart's own `|v|*t` check). `test_phase3_deposition_real.py`
re-run (was already using this exact broken config,
`direction=[0,1,0], directional_velocity=0.1` — passed before only
because it never checked direction/magnitude, just "didn't crash").
Full regression: **12 passed / 2 failed** (new test counted), same two
pre-existing, unrelated failures (Phase 8, `test_device_lifecycle_repeat_real.py`
Test B) — no new regressions.

### Directional deposition growth SHAPE — RESOLVED, calculateVisibility=True was silently under-growing (later session)

Reopened per explicit user instruction, after the LOCOS mask-export
investigation hit a dead end, to keep working toward the project's
actual goal (a TCAD that correctly implements and interprets real
physical phenomena) rather than stop at "sign/magnitude verified."
The RESOLVED section above only ever checked top-surface magnitude at
one grid resolution (`grid_delta_um=0.2`); the real growth *shape* —
does it correctly avoid depositing on surfaces perpendicular to the
source, does it spread laterally — was never checked, per this
project's own "What remains uncertain" note on that fix.

1. **What was tested:** Fetched `psDirectionalProcess.hpp`'s
   `getVectorVelocity()` from GitHub (WebFetch) to find the real
   physics: normal growth velocity is proportional to
   `dot(direction, local_surface_normal)` — a flat surface facing the
   source grows at the full rate, a sidewall parallel to the source
   should grow ~0 (cosine-law, line-of-sight deposition). Built a
   probe measuring (a) the mask's own top/sidewall growth, (b) the
   grown Si cap's x-extent vs. the recipe's own window width, across a
   `grid_delta_um` sweep (0.2 down to 0.02) and a `deposition_time_s`
   sweep, for a purely directional recipe (`isotropic_velocity` unset)
   vs. an isotropic control.

2. **Result:**
   - `maskMaterial` (default `Material('Mask')`) fully protects the
     mask from ANY growth, top or sidewall — expected/correct
     behavior, not a bug (the mask stays whatever height/width the
     lithography step gave it).
   - No lateral spread: the grown Si cap's x-extent matched the
     recipe's own window width (within 1 grid cell) for
     `isotropic_velocity` unset — confirms real directional/
     line-of-sight shape behavior, not conformal coating.
   - **Real bug found:** with ViennaPS's own default
     (`calculateVisibility=True`), growth STALLED at a small,
     grid-and-time-dependent, non-monotonic fraction of the expected
     `|v|*t` — e.g. `grid_delta_um=0.05, direction=[0,1,0]`: matched
     exactly at t=0.5s (0.0500um) then stayed pinned at exactly that
     value for t=1/2/4s (expected 0.1/0.2/0.4um) — a hard stop, not a
     slow approach to a limit. Swept `grid_delta_um` in
     `{0.2, 0.15, 0.1, 0.075, 0.05, 0.02}` at fixed t=4s: 0.2 and 0.02
     matched; 0.15 and 0.1 stalled at exactly 2 and 1 grid cells
     respectively; 0.05 stalled at 1 cell; 0.075 overshot by 12.3%
     (no stall at all) — non-monotonic, same class of ViennaPS
     numerical fragility already documented elsewhere in this file
     (MakeTrench floating-point sensitivity, Phase 8 mesh-quality
     investigation). `calculateVisibility=False` was tested across the
     identical sweep: every point matched `|v|*t` exactly except the
     same 0.075 outlier (12.3% over either way) — i.e. disabling
     visibility calculation eliminates the up-to-8x stalling and
     leaves only the same, much smaller, already-known-and-accepted
     class of grid noise.

3. **What it proves:** `calculateVisibility=True` (ViennaPS's own
   default, which this project's recipe wrapper silently inherited)
   is actively harmful for this project's own deposition geometries —
   a flat, fully-exposed window under a non-tilted, straight-overhead
   source, where genuine self-shadowing cannot physically occur at
   all. The existing, already-passing regression test only ever
   exercised `grid_delta_um=0.2`, which happens not to trigger the
   stall — it was accidentally not exposing this bug, not evidence
   the default was safe.

4. **Fix applied — `tcad/process/deposition/directional.py`:**
   `calculateVisibility` now defaults to `False`
   (`recipe.get("calculate_visibility", False)`, was previously only
   set when the recipe explicitly provided it, otherwise silently
   inheriting ViennaPS's own `True`). Still fully overridable per-recipe
   for a future geometry that has real re-entrant/tilted-source
   shadowing to model — this change does not remove the capability,
   only stops it from silently corrupting the common, simple case
   every existing recipe in this project actually uses.

5. **Verified, real ViennaPS 4.6.2, via the actual production entry
   point:** `tests/integration/test_directional_deposition_growth_real.py`
   extended (not replaced) with a `grid_delta_um` sweep at fixed t=4s
   (5 resolutions, max relative error 7.5e-8 — essentially exact) and
   a lateral-spread check (grown cap width within 1 grid cell of the
   recipe's window width). Full regression: **16 passed, 0 failed, 0
   skipped** — unchanged, no new regressions.

6. **What remains uncertain:** the exact mechanism inside ViennaPS's
   visibility/ray-tracing calculation causing the non-monotonic stall
   (not traced to C++ source level — matches this project's existing
   precedent of characterizing rather than root-causing this class of
   library-internal numerical fragility); the single
   `grid_delta_um=0.075` outlier (12.3% over expected even with the
   fix) was not chased further, consistent with how this project
   already treats this general class of non-monotonic ViennaPS
   artifact elsewhere.

7. **Etching counterpart checked (same session, immediate follow-up):**
   whether `tcad/process/etching/directional.py`'s own
   `calculateVisibility=True` default has the same silent stalling
   issue for material removal — **it does not.** Swept the identical
   `grid_delta_um`/time combinations: `calculateVisibility=True` and
   `False` gave byte-identical etch depth at every point (exact match
   at gd∈{0.1,0.075,0.05,0.02}, and the same ~12-13% deviation at the
   two coarsest grids 0.2/0.15 *regardless* of the flag, i.e. that
   deviation isn't visibility-related). See "Etching (basic)" above
   for the full result. `etching/directional.py` was left unchanged —
   the deposition-side bug is specific to growth, not general to the
   shared `DirectionalProcess` model.

## Session status snapshot (most recent — read this first)

**This supersedes the snapshot below it as "most recent."** The
snapshot below describes a *different, no-longer-relevant* environment
(a Windows machine, two local worktrees, branch
`claude/caveman-doeini-1c015f`) — kept only as history, not current
state. This session ran in a fresh Linux remote container with no
prior worktree/venv state; the project code itself (everything above
this point in the file) was inherited as-is from that prior work and
is what this session built on.

**Where the code lives now:** branch
`claude/tjrgns1753-tcad-folder-jj3yg0`, repo
`tjrgns1753-create/tcad`. The project files (previously only living on
`claude/caveman-doeini-1c015f`) were moved into this branch's repo
root this session (were at `tcadrr/tcad_project_gui_fix/` on that other
branch).

**Environment setup done this session (fresh container, nothing
pre-installed):** created `.venv`, `pip install -e ".[full]"` (real
ViennaPS 4.6.2 + DevSim 2.10.1, both from PyPI — no source/mock
substitutes). DevSim's `import devsim` initially failed with
"MISSING DLL" for `libopenblas.so`/`liblapack.so`/`libblas.so` — this
Linux container had no BLAS/LAPACK at all (a different flavor of the
same class of environment issue the "DevSim BLAS/LAPACK DLL
environment issue" section above hit on Windows). Fixed with
`apt-get install libopenblas0 liblapack3 libopenblas-dev
liblapack-dev` (the `-dev` packages specifically provide the
unversioned `libopenblas.so`/`liblapack.so`/`libblas.so` symlinks
DevSim's own default `DEVSIM_MATH_LIBS` search string looks for — the
non-dev packages alone only provide versioned `.so.3`/`.so.0` files,
which need an explicit `DEVSIM_MATH_LIBS` override to find). No
project code changes needed for this — purely a system package
install, verified by `import devsim` succeeding and
`tests/run_regression.py` reproducing the exact pre-session-documented
baseline (13 passed, 2 failed, matching this file's own numbers)
before any of this session's own changes were made.

**What this session did (part 1):** root-caused and fixed the long-open
Phase 8 PN-junction convergence failure (see "PN junction (Phase 8)
convergence — RESOLVED" above for the full investigation) — local mesh
refinement near the doping junction
(`tcad/device/devsim/mesh_refine.py`, wired into
`mesh_import.py`/`run_pipeline.py` as opt-in parameters), found by
comparing against DEVSIM's own official diode example (fetched via
WebSearch/WebFetch, since the Context7 MCP connector the user first
asked for was not connected/authorized in this environment).

**Regression after part 1:** `tests/run_regression.py` → **16 passed,
0 failed, 0 skipped** — every previously-documented failure in this
file (Phase 8 directly, `test_device_lifecycle_repeat_real.py` Test B)
is gone, no new regressions. This is the first 0-failed run recorded
anywhere in this file's history.

**What this session did (part 2, same session, continued per explicit
user instruction to keep fixing real errors against official ViennaPS
examples/API):** root-caused LOCOS mask erosion (~97-99% area loss) —
see "LOCOS mask erosion — ROOT CAUSE FOUND AND VERIFIED FIXABLE" above
— by fetching and comparing against the real
`examples/locosOxidation/locosOxidation.py` source plus the
`psOxidation.hpp`/`psDomain.hpp`/`lsWriteVisualizationMesh.hpp` C++
sources (all via WebFetch, Context7 still not connected in this
environment). Found and verified a real fix (pad-oxide-first + contact-
epsilon mask construction, mask retention 3.54% → 99.8-100%) — but
also found, via the *exact same investigation*, a confirmed ViennaPS
4.6.2 upstream limitation that blocks shipping it: `saveVolumeMesh()`
drops the `Si` material entirely from the exported mesh for this
construction (reproduced with the official example's own geometry,
verbatim, not just this project's adaptation). Decision: do **not**
change `thermal.py`'s LOCOS geometry this session — the fix is real
but not safely shippable yet. Only kept a small, independently-verified
side-fix: `tcad/backends/viennaps/io.py`'s `_floored_copy_for_export()`
now calls `vls.Expand(ls, 3)` before its existing box-intersect,
fixing a separate crash (`IndexError`) this investigation found in the
floor mechanism for a level set narrower than ViennaLS's own minimum
width — a real bug regardless of whether the LOCOS geometry fix itself
ships, verified to change nothing for every already-working geometry.

**Regression after part 2:** `tests/run_regression.py` → still
**16 passed, 0 failed, 0 skipped** (the `io.py` `Expand()` fix is the
only production change from part 2; `thermal.py` itself is untouched).

**What this session did (part 3, same session, continued per explicit
user instruction to keep working toward "a TCAD that correctly
implements and interprets real physical phenomena," after part 2's
LOCOS mask-export investigation hit a genuine dead end):**
root-caused and fixed a real, previously-undetected bug in directional
deposition's growth *shape* — see "Directional deposition growth
SHAPE — RESOLVED" above. `calculateVisibility=True` (ViennaPS's own
default, silently inherited) stalls growth at a grid-and-time-dependent,
non-monotonic fraction of the expected `|v|*t` (up to 8x under-growth)
for this project's own flat-window/non-tilted-source geometry, found
by fetching `psDirectionalProcess.hpp`'s real velocity-calculation
source from GitHub and sweeping `grid_delta_um`/`deposition_time_s`.
Fixed by defaulting `calculateVisibility=False` in
`tcad/process/deposition/directional.py` (still overridable per-recipe).
Also positively confirmed (not just assumed): no lateral spread for a
purely directional recipe — the real physical signature distinguishing
it from isotropic/conformal deposition.

**Regression after part 3:** `tests/run_regression.py` → still
**16 passed, 0 failed, 0 skipped** — the `directional.py` default-value
change and the extended regression test are the only changes; no
regressions.

**What this session did (part 4, same session, immediate follow-up):**
checked whether directional *etching* has the same
`calculateVisibility=True` stalling bug part 3 found in directional
*deposition* — it does not (see item 7 under "Directional deposition
growth SHAPE — RESOLVED" and the follow-up under "Etching (basic)"
above for the full sweep). `etching/directional.py` was deliberately
left unchanged; this is a negative result, not a missed fix.

**What this session did (part 5, same session, immediate follow-up):**
closed out the long-carried-forward "`gd=0.02` Si-thickness
dependency" open item — see "`gd=0.02` Si-thickness dependency —
RESOLVED" above. Turned out to already be fixed by the existing floor
mechanism (verification table already had a `gridDelta=0.02` row);
this item stayed open only because it had never been re-checked
through the real `ProcessStep.run()` production path or a real DevSim
import, only an isolated probe. Ran both — etch, oxidation, and DevSim
import all work correctly at `gridDelta=0.02`. No code change, just a
stale open item closed with real verification.

**What this session did (part 6, same session, per explicit user
instruction "더 나아갈 수 있나" / "can we go further" to keep pushing on
the LOCOS blocker rather than accept part 2's dead end as final):**
shipped the LOCOS mask-erosion fix to production — see "LOCOS mask
erosion — RESOLVED AND SHIPPED" above for the full investigation. The
part-2 blocker (`saveVolumeMesh()` dropping `Si` entirely) is solved by
a new export function, `save_locos_volume_mesh()`
(`tcad/backends/viennaps/io.py`), that resolves each material's true
region with plain Python geometry (independent single-material exports
+ a top-surface clip) instead of relying on
`WriteVisualizationMesh`/ViennaLS's insertion-order stacking
resolution or any ViennaLS boolean op (both confirmed broken/unusable
for this in part 2's own investigation). `thermal.py`'s LOCOS branch
now builds pad-oxide-first geometry (`_build_locos_geometry`) only for
a fresh wafer, and calls the new export function instead of the normal
one. Mask retention: 97.99% measured through the real production path,
up from the ~3.5% baseline part 2 found. New test
`tests/integration/test_locos_devsim_import_real.py` confirms the real
production entry points (registry → `ThermalOxidation.run()` →
`build_process_result()` → `import_process_result()`) all still work
end to end with the new geometry.

**Regression after part 6:** `tests/run_regression.py` → **17 passed,
0 failed, 0 skipped** (16 before this part's new test was added) — no
regressions to fin-style oxidation or any other model/phase.

**What this session did (part 7, later session, per explicit user
instruction to expand physical scope — "물리 범위 확장" — after being
asked directly whether the project was usable as a commercial TCAD "as
is": answered honestly that it was not, for several named reasons
including narrow physical coverage, then the user picked "expand
physical scope" and, from two concrete named candidates, picked
KOH/TMAH crystallographic wet etching over MOSFET Vth/subthreshold-
slope extraction — the latter needing a new source/drain/channel/gate
device design at roughly Phase 7/8's own scale, judged too large to
just start without being asked):** added KOH/TMAH crystallographic wet
etching — see "KOH/TMAH crystallographic wet etching — ADDED" above
for the full investigation. `wet_etching.py`'s own docstring had
pre-flagged this exact gap ("once real rate constants are supplied");
fetched ViennaPS's own official `cantileverWetEtching.py` example for
real, cited rate constants (30% KOH at 70°C,
https://doi.org/10.1016/S0924-4247(97)01658-0) and verified — since
that example is 3D-only and this project is 2D-only — that the same
constants produce a genuine, textbook-correct V-groove profile through
`vps.d2.WetEtching`: apex depth within 2.9% and sidewall angle within
1.2° of the real Si (111)/(100) "magic angle" (54.7356°), both
parameter-free physical predictions, not fits.

**Regression after part 7:** `tests/run_regression.py` → **18 passed,
0 failed, 0 skipped** (17 before this part's new test was added) — no
regressions.

**What this session did (part 8, later session, per explicit user
instruction "지금 발생한 모든 문제를 해결해" / "solve all the problems
that have occurred" — works through every item still open as of part
7 above):**
- Implemented `auto_refine_from_doping` (see "`auto_refine_from_doping`
  — ADDED, and mesh-refinement generalization to higher doping —
  CHARACTERIZED" above): derives `refine_near_um`/`refine_axis`/
  `refine_half_width_um`/`refine_levels` from `ProcessResult.doping`
  directly. Along the way, found and fixed a real formula bug (an
  initial spacing-floor multiplier of `2x` combined with a
  doping-scaled `refine_levels` compounded into a 588k-equation
  near-runaway at 1e19 cm^-3 before being corrected) and established a
  real, honest boundary: generalizes cleanly through 1e19 cm^-3 (10x
  the originally-tuned recipe), does NOT converge at 1e20 (100x) even
  at this session's chosen `refine_levels` cap.
- Investigated LOCOS process-flow chaining (see "LOCOS process-flow
  chaining — REAL BUG FOUND, safety-net mitigation SHIPPED" above):
  confirmed a real, previously-untested bug — a step chained onto
  fresh-LOCOS geometry corrupts ITS OWN mesh export (SiO2 and Mask
  vanish, Si is mislabeled). Full architectural fix judged too large
  for this session (would touch every `ProcessStep` + `flow.py`);
  shipped a safety-net `RuntimeWarning` in `save_volume_mesh()`
  instead, verified to fire exactly on the reproduced bug and stay
  silent everywhere else in the regression suite.
- LOCOS bird's-beak diffusion-driven shape investigation and KOH
  rate-constant generalization to other concentrations/temperatures:
  not yet reached this part — see below for what's still open.

**Regression after part 8:** `tests/run_regression.py` → **19 passed,
0 failed, 0 skipped** (18 before this part's new test was added) — no
regressions.

**What this session did (part 9, later session, immediate follow-up):**
investigated the LOCOS bird's-beak shape (see "LOCOS bird's-beak shape
— INVESTIGATED" above): a gridDelta sweep, a time sweep, and a
pad-oxide-thickness sweep (at both a short and a more mature growth
duration) together show the taper is grid-independent in length (not a
discretization artifact) and, at a growth stage large enough to rise
above measurement noise, scales with pad oxide thickness (0.3um at
pad=0.1um vs. 0.45um at pad=0.2um) the way real LOCOS lateral-diffusion
physics predicts. No production code changed — this investigation
confirms existing behavior is physically sound, it isn't a bug fix.

**What this session did (part 10, later session, per explicit user
instruction: apply the doping-ceiling fix prototyped and reported the
previous round, but only re-investigate — do not implement — the LOCOS
chaining fix):**
- Applied the graded/telescoping refinement upgrade to production —
  see "`auto_refine_from_doping` — upgraded to GRADED refinement,
  1e20 cm^-3 now converges" above. `mesh_refine.py` gained
  `graded_refine_mesh_near()`; `mesh_import.py`'s
  `_derive_refine_from_doping()` now returns a telescoping ring
  sequence instead of a single (half-width, levels) pair. Verified
  through the real production entry point: 1e19 cm^-3 converges with
  16025 nodes (was 51239 with the old formula), and 1e20 cm^-3 — a
  ceiling the old formula could not cross even at its level cap — now
  converges fully with 61725 nodes. This also resolved an open
  question from part 8: 1e20's earlier failure was a pure mesh-
  resolution limit, not the physics model breaking down at that
  doping level.
- Re-investigated LOCOS process-flow chaining (per explicit
  instruction NOT to implement yet, only to prototype/test and
  re-report): confirmed the "explicit hint propagation" design's core
  idea works in concept, but found a NEW, more precise root cause
  along the way — `_export_single_level_set()`'s isolated
  single-material domain construction, when built from a Si level set
  that has been through BOTH a LOCOS build AND a subsequent `Process()`
  call, gets a DEGENERATE bounding box from ViennaLS's own
  `getBoundingBox()` (literal `±DBL_MAX` inverted min/max sentinels),
  which then feeds an absurdly-inverted box into
  `BooleanOperation(INTERSECT)` and hangs for minutes. Traced
  precisely (isolated diagnostic scripts, not guessed): the ORIGINAL
  multi-material domain's own bounding box stays correct throughout
  (before AND after the etch) — only the ISOLATED single-level-set
  reconstruction's bbox breaks. Since `_export_single_level_set`
  already has the correct bounds in hand (from the original domain,
  computed before ever isolating the level set), the fix does not need
  to understand WHY `getBoundingBox()` breaks for this case — it can
  simply pass its own already-known-correct bounds through explicitly
  instead of letting `_floored_copy_for_export()` re-derive them via
  the broken call. No code changed — probe scripts only, deleted after
  the investigation, per explicit instruction to test without
  applying.

**Regression after part 10:** `tests/run_regression.py` → still
**19 passed, 0 failed, 0 skipped** — the graded-refinement change is
the only production change this part; no regressions.

**What this session did (part 11, later session, user-reported GUI
bug: "실리콘 기판 단면에 작은 직각삼각형으로 표현이 된다" / "the Si
substrate cross-section renders as a small right triangle" after
etching):** root-caused and fixed a real bug in
`tcad_2d_stagewise.py`'s `_draw_real_mesh_result()` — see "GUI: Si
cross-section rendering as a stray small triangle" above. The mesh
export's triangle order is not spatially uniform, so the existing
positional-stride decimation (`triangle_data[::step]`) reproduced
whatever ordering bias was already in the file, ending up keeping only
a thin sliver of Si triangles near the floor boundary instead of a
representative sample of the whole substrate. Fixed with per-material
random sampling (fixed seed for redraw stability), verified at the
algorithm level against real ViennaPS mesh data (kept Si triangles'
y-range now matches the true full extent almost exactly). Could not
verify inside an actual Tkinter window — this container has no
`tkinter` installed. This is the first GUI-file change of this
session; every other part touched only `tcad/` backend code.

**What this session did (part 12, later session, per explicit user
instruction to apply the real LOCOS-chaining fix this time, not just
re-report it — "LOCOS 체이닝 버그 본수정"):** implemented part 10's
proposed fix (bounds-hint passthrough to bypass the broken
`getBoundingBox()` re-query, plus a weakref-keyed export-hint registry
in `io.py` so no `ProcessStep` file needs to change) as a full-fidelity
prototype, and found — by testing it for real rather than assuming it
would work — that it does **not** actually fix the bug. See "LOCOS
process-flow chaining — ROOT CAUSE REFINED..." above for the full
investigation. Tracing past the bbox symptom to each level set's own
`getNumberOfPoints()` revealed the real corruption: Si and SiO2's level
sets collapse to 0 points as an in-memory side effect of the chained
step's own `Process()` call, before export is ever involved — an
export-layer fix categorically cannot recover data that's already gone
from the domain itself. Ruled out level-set width as the cause by
directly widening every level set before chaining (no effect). Could
not go further this session: cross-referencing ViennaPS's real
advection source to find the exact C++-level mechanism was blocked by
a GitHub rate limit (429, retry after 1 hour) at the moment it was
tried. Per explicit standing project rules (report uncertainty
honestly; never ship a fix that doesn't fix the actual problem), no
production code was changed — the previously-shipped `RuntimeWarning`
safety net (part 8) remains the only production mitigation.

Also attempted, separately this session, to install `tkinter` matching
the GUI's actual venv Python (3.11.15) for visual verification of the
part-11 GUI fix — blocked by the same class of environment policy: the
correctly-versioned `python3.11-tk` package is only available via the
deadsnakes PPA, and fetching it hit a 403 Forbidden from this
environment's outbound proxy (an organizational egress-policy denial,
not a transient failure — confirmed via `/root/.ccr/README.md`, which
explicitly says not to retry or route around this class of error).
Accepted as a standing limitation of this container per explicit user
instruction ("일단 적용하고 넘어가자"); the part-11 fix stays verified
only at the algorithm/data level against real ViennaPS mesh data, not
via an actual on-screen render.

**Regression after part 12:** unchanged — `tests/run_regression.py` →
still **19 passed, 0 failed, 0 skipped** (no production code was
touched).

**What this session did (part 13, later session, per explicit user
instruction "LOCOS 천천히 해도 되니까 꼭 찾아봐" / take your time on
LOCOS but really find it, then "둘다해줘" / apply both):** solved and
shipped the LOCOS process-flow chaining bug that parts 8/10/12 all
failed on — see "LOCOS process-flow chaining — RESOLVED AND SHIPPED"
above. The breakthrough was asking the question every earlier attempt
skipped: how does the NORMAL `MakeTrench` path satisfy the ViennaLS
`Advect` precondition that LOCOS violates? Measuring both domains'
real material order and per-level-set regions showed MakeTrench
inserts the substrate LAST, wrapping the mask, so its last level set
contains everything — LOCOS is the only geometry in the project not
following that convention. Since every earlier attempt to fix the
CONSTRUCTION broke `vps.Oxidation()` itself, the fix restores the
invariant AFTERWARD instead (one union at the end of LOCOS's own
`run()`, plus a weakref-keyed export hint in `io.py` so downstream
steps export correctly with zero changes to any `ProcessStep.run()`
file). Measured, not assumed, that one re-wrap suffices — three
chained steps pass with no further fixup, because `Advect` preserves
the invariant once it holds.

Also, separately: found and fixed a real physical-coverage gap
surfaced by questioning this project's own wording — a test log had
described a chained etch as "removing oxide and leaving Si untouched,"
which measurement showed was pure geometry (the etch was shallower
than the oxide), not selectivity. This project's directional and
isotropic etches had NO material selectivity at all. Added an optional
`material_rates` recipe key to both, with the per-overload sign
conventions measured rather than assumed (ViennaPS's two overloads
disagree with each other, and a wrong sign is a silent no-op) — see
"Per-material etch selectivity — ADDED" above.

Full test-by-test record for both, including every rejected
hypothesis, in `LOCOS_CHAINING_TEST_LOG.txt`.

Follow-up in the same session, prompted by a fair pushback on this
file's own hedging ("공식예제에서는 씌우는것도 잘 되던데" — the official
example's layer-adding works fine): the one case listed as untested
above, chaining Bosch DRIE (`duplicateTopLevelSet`) onto LOCOS output,
was measured rather than left flagged. It works, on both counts that
could have failed — see item 7 of the chaining section above for the
numbers and the mechanism. The hedge was unnecessary. Now covered
permanently as check 6 of `test_locos_chaining_real.py`.

**What this session did (part 14, later session, closing out the
remaining LOCOS chaining uncertainties, then per explicit instruction
"둘다해줘" adding etch selectivity, then a requested KOH/TMAH
concentration/temperature sweep that surfaced a real gap in the
existing KOH test):**
- Closed both uncertainties part 13 left open. Grid-resolution
  coverage needed no code change (6 resolutions, 0.02–0.25um, all
  pass — see "LOCOS process-flow chaining" item 8 above). LOCOS-on-
  LOCOS was confirmed pre-existing and NOT a regression (rerunning
  with the re-wrap disabled reproduces the original silent-corruption
  bug, not a clean run), then guarded with a narrow
  `NotImplementedError` — keyed specifically so fin-style oxidation
  chained onto LOCOS (which does work) is not blocked (item 9 above).
- Added per-material etch selectivity (`material_rates` recipe key on
  `directional.py`/`isotropic.py`), found while verifying the LOCOS
  fix — see "Per-material etch selectivity — ADDED" above for the
  measured, disagreeing sign conventions between ViennaPS's two
  overloads.
- Investigated the requested KOH/TMAH concentration/temperature
  sweep, test-only throughout. Found real TMAH rate constants are not
  obtainable in this environment, so swept the region TMAH occupies
  using the cited KOH constants instead — and that sweep surfaced a
  genuine problem: `rate111`/`rate311` are completely inert in this
  project's existing 2D wiring (traced to a 3D-example depth-axis
  copied verbatim onto the wrong 2D axis, confirmed from ViennaPS's
  own `psWetEtching.hpp` source), and even the analytically-correct
  fix (a uniquely determined 45° crystal-frame rotation) does not
  produce genuine self-limiting V-groove behavior — the existing
  shipped KOH test passes for a coincidental reason, not the physics
  it claims. See "KOH/TMAH crystallographic wet etching — self-
  limiting V-groove NOT reproduced" above for the full chain of
  reasoning. Per explicit user instruction, stopped at this point
  (root cause narrowed to ViennaLS-internal territory) rather than
  continuing into `Advect`'s velocity-extension source — recorded
  here instead of chased further.

**Regression after part 14:** unchanged at 21 passed, 0 failed, 0
skipped for the code changes (selectivity + LOCOS-on-LOCOS guard); the
KOH/TMAH investigation added no code and no test.

**OPEN issues carried forward, NOT resolved this session:**
- LOCOS mask preservation — **RESOLVED in part 6 above** (was open as
  of parts 1-5; struck through here rather than removed, so this list
  stays an honest record of what was still open at each point in the
  session).
- LOCOS bird's-beak shape's true diffusion-driven behavior vs.
  seed-geometry artifact — **INVESTIGATED in part 9 above**: evidence
  supports genuine diffusion physics (grid-independent length, scales
  with pad thickness at a mature growth stage), not an artifact.
- Auto-deriving `refine_near_um` from `ProcessResult.doping` — **DONE
  in part 8 above** (was open through part 7).
- Whether the mesh-refinement fix generalizes to `gaussian_implant`
  doping — **VERIFIED in part 8** (doping-mapping correctness under
  refinement, not a convergence fix — see that section for why
  `gaussian_implant` was never itself a convergence problem the way
  `step_junction` was); to doping levels far above 1e18 cm^-3 —
  **RESOLVED in part 10**: 1e19 AND 1e20 cm^-3 now both converge via
  graded refinement, shipped to production.
- Whether `save_locos_volume_mesh()`'s pad-oxide-first LOCOS fix
  interacts with a subsequent process step continuing from its result
  — **REAL BUG CONFIRMED in part 8; part 10's `getBoundingBox()`
  diagnosis was real but INCOMPLETE; part 12 found the deeper actual
  cause (in-memory level-set data loss during the chained step's own
  `Process()` call, not an export-layer bug) and confirmed the
  previously-proposed fix does NOT solve it** — see part 12 above.
  **RESOLVED AND SHIPPED in part 13** — see "LOCOS process-flow
  chaining — RESOLVED AND SHIPPED" above. Part 12's call for "a
  fundamentally different approach" was right: the answer was not an
  export-layer fix at all, but restoring ViennaLS Advect's
  containment precondition on the domain itself after oxidation
  finishes.
- LOCOS chaining's two remaining uncertainties (grid coverage,
  LOCOS-on-LOCOS) — **CLOSED in part 14**: grid coverage needed no
  code change (6 resolutions verified); LOCOS-on-LOCOS confirmed
  pre-existing (not a regression) and guarded with a narrow
  `NotImplementedError` rather than left to hang.
- Per-material etch selectivity — **ADDED in part 14** (was a gap
  found, not previously tracked as open; see "Per-material etch
  selectivity — ADDED" above).
- KOH/TMAH rate-constant generalization to other concentrations/
  temperatures, or to TMAH — **INVESTIGATED in part 14, NOT resolved,
  and turned out to be blocked on something more basic**: the model
  does not reproduce genuine self-limiting V-groove physics in this
  project's 2D configuration at all (root-caused to a depth-axis
  mismatch copied from the 3D official example; even the
  analytically-correct fix doesn't self-limit) — see "KOH/TMAH
  crystallographic wet etching — self-limiting V-groove NOT
  reproduced" above. TMAH itself is moot until this is fixed. Real
  TMAH rate constants were also not obtainable (paywalled paper,
  blocked open-access mirror, no ViennaPS data). Explicitly NOT
  pursued further into ViennaLS source this round, per user
  instruction to stop and record rather than keep digging.
- Visual (on-screen) verification of the part-11 GUI rendering fix —
  blocked by a GitHub-PPA proxy policy denial (403) when trying to
  install the venv-matching `python3.11-tk` package; accepted as a
  standing container limitation per explicit user instruction.

---

## Session status snapshot (historical — Windows environment, superseded above)

**Where the code lives:** branch `claude/caveman-doeini-1c015f`, pushed
to `https://github.com/tjrgns1753-create/tcad` (note: NOT
`tjrgns1753/tcadproject` — that remote URL was wrong/inaccessible;
corrected this session). Latest commit `c7c8516`. Local `master` was
fast-forwarded once, to `d8fdaf9` (one commit behind `c7c8516` —
the LOCOS contactMode fix landed after that fast-forward and has not
been merged into local `master` again, deliberately, see next point).
No PR opened yet (link available:
https://github.com/tjrgns1753-create/tcad/pull/new/claude/caveman-doeini-1c015f).

**Two worktrees exist for this repo, do not confuse them:**
1. This one — `.../tcad_project_gui_fix/.claude/worktrees/caveman-doeini-1c015f/...` —
   where all commits in this section were made.
2. The main project worktree — `C:/Users/PC/.vscode/tcadproject/...` —
   has its own **independent, uncommitted** work (an alternate LOCOS fix
   attempt using `MakePlane` pad-oxide, referred to as "B" throughout
   this file, plus its own BLAS/MKL environment-recovery notes, merged
   into this file's LOCOS section already). That worktree's `master` ref
   was fast-forwarded to `d8fdaf9` mid-session, which left its working
   tree/index stale relative to that ref (a known, diagnosed, NOT yet
   resolved sync gap — see "the two LOCOS implementations" comparison
   below for how B was preserved and compared, not lost). Do not run
   `git reset --hard`/`checkout`/`clean` there without re-checking that
   gap first; B's files were separately backed up (git blob objects
   `1056c7d`/`42307ce` in that worktree's own object DB, plus a scratch
   copy) precisely so this is recoverable either way.

**What this session did, in order (full detail in the dated sections
above/below — this is just the index):** fixed the LOCOS mask segfault
(first via `halfTrench=True`, then superseded by the real root-caused
fix, `OxidationMaskParameters(contactMode=2)`, after an A vs B vs C
comparison — see "LOCOS (Phase 4) segfault" section); wired 4 etch
models into the GUI; added 5 new process models (`hbr_o2`, `sf6_c4f8`,
`cf4_o2`, `faraday_cage`, deposition `isotropic`); added
`gaussian_implant` doping (physics + DevSim + CLI); replaced the GUI's
placeholder etch-result rectangle with real ViennaPS mesh rendering;
found and fixed a real sign-convention bug in directional deposition;
audited and fast-forward-merged 9 commits into local `master`; verified
the CLI's real entry point end-to-end for two examples.

**Regression, most recent run:** `tests/run_regression.py` →
**13 passed, 2 failed**. The 2 failures are the same pre-existing,
already-investigated PN-junction convergence issue (Phase 8,
`test_device_lifecycle_repeat_real.py` Test B) — not touched, not
regressed, tracked as OPEN below.

**OPEN issues, not resolved this session (do not claim fixed):**
- LOCOS mask preservation (~97-99% area loss during oxidation) —
  root cause not identified; confirmed independent of the contactMode
  fix and of the initial-oxide-seed value.
- LOCOS bird's-beak shape's true diffusion-driven behavior vs.
  seed-geometry artifact — unresolved.
- `gd=0.02` Si-thickness dependency — untouched, out of scope by
  explicit instruction.
- Phase 8 / PN-junction drift-diffusion convergence failure —
  extensively investigated earlier this session, explicitly closed by
  user instruction not to keep pursuing it.
- Directional deposition's real-growth *shape* (only the sign/magnitude
  was verified against `|v|*t`, not a full undercut/profile check).

## Current Task

Do not try to solve everything at once.

First establish a physically correct flat 2D Si wafer / mask representation.

Then verify oxidation.

Then etch/isotropic etch.

Then Bosch scalloping.

Only after geometry is trustworthy should physical device benchmarks be performed.

For each investigation report:
1. What was tested
2. Result
3. What it proves
4. What remains uncertain
5. Next smallest experiment