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
| Phase 4 (oxidation, LOCOS variant) | **FAIL** — segfault, pre-existing, unrelated to this session's changes (see "Oxidation" section below) |
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

### PN junction (Phase 8) convergence sensitivity to the floor mechanism — UNRESOLVED, investigation closed (this session)

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