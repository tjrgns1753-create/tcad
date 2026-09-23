# Batch 3B — center clearance and boundary residual kept apart in the etch diagnostic

**STATUS: implemented and verified as specified. Awaiting Codex review. No full regression, no commit.**

Scope kept: `tcad/mesh/etch_diagnostics.py`, `_log_etch_material_summary()` only inside `tcad_2d_stagewise.py`, the three
named tests, and this report. Etch models, exporter, WaferState, oxidation code, the Batch 3A audit and every earlier audit
are untouched (hash-verified, §13). Starting state: branch `claude/waferstate-v2`, HEAD
`3ba940404fd19c88eaaccc96a39ffe8444fb8851`, 64 dirty entries — the same 64 at the end.

Order of the prescribed tests, final run after the last edit (all `rc=0`):

| test | rc | time |
|---|---|---|
| `tests/unit/test_etch_material_summary_mock.py` | 0 (42/42) | 1.5 s |
| `tests/integration/test_oxidation_pr_etch_reaches_si_real.py` | 0 | 8.3 s |
| `tests/integration/test_etch_selectivity_real.py` | 0 (all four real runs) | 8.5 s |
| `tests/integration/test_cad_negative_validation_real.py` | 0 | 0.6 s |
| `tests/integration/test_pin_placement_validation_real.py` | 0 | 0.6 s |
| `tests/integration/test_oxidation_zero_duration_identity_real.py` | 0 | 4.5 s |
| `tests/integration/test_oxidation_positive_time_unsupported_real.py` | 0 | 29.7 s |

## 1. Changed files and roles

| file | role | exact delta vs the pre-batch copy |
|---|---|---|
| `tcad/mesh/etch_diagnostics.py` | the diagnostic: shared-edge components, component-carrying scanlines, 5 contract states, centre-clear span, residual metadata, 3-scanline `_reach`. Numpy only. | rewritten: +334 / −122 |
| `tcad_2d_stagewise.py` | only `_log_etch_material_summary()` (hunks at old lines 6948–7009, inside the function): formatting of the structured results and a docstring | +47 / −13, 6 hunks |
| `tests/unit/test_etch_material_summary_mock.py` | 20 existing cases kept (3 expectations updated by the new contract, §7) + 22 new cases | +353 / −21 |
| `tests/integration/test_oxidation_pr_etch_reaches_si_real.py` | new states/wording, stale `max(y)` comment fixed; strict logger-vs-core check unchanged | +29 / −7 |
| `tests/integration/test_etch_selectivity_real.py` | `check_diagnostic()` now asserts the four expected states incl. the Directional/selective residual | +95 / −12 |
| this report | | |

## 2. State data structure (`etch_diagnostics.py`)

`analyze_window(pre, post, window)` returns one `MaterialResult` per material per window (`analyze_etch_windows` runs each
window independently; nothing is shared between windows, residual metadata included).

```
MaterialResult(material, status, window_um,
               displacement_um, run_x_um, n_intervals, reach, reason, post_top_range_um,      # paired displacement / ambiguity
               center_clear_x_um, n_center_clear_intervals,                                   # CENTER_CLEARED_RESIDUAL_REMAINS
               residual: Residual | None,                                                     # CENTER_CLEARED... and POST_ONLY_RESIDUAL
               evidence_source = "exported_volume_mesh")
  .contract_state  ->  FULLY_CLEARED_IN_WINDOW | CENTER_CLEARED_RESIDUAL_REMAINS | POST_ONLY_RESIDUAL
                       | PAIRED_VERTICAL_DISPLACEMENT | AMBIGUOUS
```
`status` keeps the finer paired outcomes (`ETCHED`, `UNCHANGED` with a `reach`, `ROSE_OR_INDETERMINATE`) so a fact is never
squeezed into one string; `contract_state` maps them to the five approved states (`ROSE_OR_INDETERMINATE` has no number → `AMBIGUOUS`).
Renamed from Batch 3: `CLEARED → FULLY_CLEARED_IN_WINDOW`, `POST_ONLY → POST_ONLY_RESIDUAL`, `NO_PAIRED_FLAT_INTERIOR → AMBIGUOUS`.

## 3. Shared-edge components (`triangle_components`)

Union-find over triangles; a triangle joins another **iff** both have the same material and one complete edge — the same
sorted pair of point indices, key `(material, min(u, v), max(u, v))`. A vertex shared by two triangles, a T-junction, or a
coincident-but-differently-indexed edge is **not** connectivity; no coordinate tolerance is applied anywhere in this function.
`_Ctx.sections()` keeps, per scanline, `(y_lo, y_hi, component id)`; y-ranges are merged only within one component, so two
components that touch at the same height stay two entries (a scanline with more than one entry is ambiguous). A paired run
(or a centre-clear span) whose pre or post component id changes is `AMBIGUOUS`. The synthetic-mesh builder in the unit test now
shares a point index only where the nominal coordinates are exactly equal; production rules were not loosened for the tests.

## 4. Centre-clear span algorithm (`_center_clear`)

1. Whole-window post absence (no positive-area intersection anywhere) is decided first → `FULLY_CLEARED_IN_WINDOW`; no span needed.
2. Otherwise on the common x-partition, take the interval(s) containing the window midpoint. Pre must be a single component there.
3. Post must be **absent** on all three scanlines of those intervals (a single component → the paired-displacement path; several
   components / partial / two node sides disagreeing → `AMBIGUOUS`).
4. Extend left and right while "pre single component, post absent" holds; a change of pre component → `AMBIGUOUS`.
5. Require ≥ 2 common intervals and width > 0, else `AMBIGUOUS` ("the centre-clear span is fewer than two common intervals wide").
6. Residual metadata is built from all positive-area post intersections of that material anywhere in the window →
   `CENTER_CLEARED_RESIDUAL_REMAINS` with `center_clear_x_um`, `n_center_clear_intervals` and `residual`.
`POST_ONLY_RESIDUAL`: pre has no window intersection, post has one; the residual is attached, nothing else is inferred.

## 5. Residual metadata (per material component; every positive-area component, no cutoff)

`clipped_area_um2`, `clipped_x_extent_um`, `clipped_y_extent_um`, `touches_left_window_edge`, `touches_right_window_edge`,
`whole_mesh_triangle_count`, `triangles_intersecting_window`, `isolated_island`; aggregated in `Residual`
(`total_clipped_area_um2`, x/y extent, edge flags, `component_count`, `components`, `evidence_source`).
**`isolated_island` definition, verbatim in the code and here:** the whole material component's every triangle lies inside or
on the boundary of the window, i.e. **no triangle of the component has positive area outside the window** (tested with the
geometry epsilon on the x-extent). It is *not* "touches no edge": an island with a vertex exactly on the window edge is still an island (unit case 26).
"Positive-area intersection" means: clipped polygon area > ε² and clipped x-extent > ε, where ε is 4 float32 ulps of the largest
coordinate (≈ 1.9e-6 µm here). That is a numeric-zero test — a triangle merely touching the window boundary clips to zero area up to
rounding — not a size cutoff (§10).

## 6. `_reach()`: start, midpoint and end scanlines of every interval

Every common interval of the whole measured run is inspected on all three scanlines. Per scanline: `exposed` when no other material
lies above the top, `overlain` when exactly one other component touches it from above, otherwise `UNKNOWN`; the run is
`REACH_EXPOSED` / `REACH_OVERLAIN` only if all scanlines of all intervals agree, else `REACH_UNKNOWN`.
* unit 32 (start/mid/end all covered) → `OVERLAIN`; 33 (all exposed) → `EXPOSED`;
* unit 34: SiO₂ wedge thinning to zero at the interval start — middle covered, start exposed → `UNKNOWN` (midpoint-only said `overlain`);
* unit 35 + replay of the Batch 3A sweep (same seed 20260921, same law, 4000 valid cases): `overlain` 890, `cannot_be_inferred` 3110,
  **0 definite answers contradicting the exact end-gap rule**; the 111 Batch 3A midpoint-vs-exact disagreements (end gap 1.01–2.0 ε) are all closed as `UNKNOWN`.

## 7. Unit tests: 42/42

* Existing 01–20 kept. Three expectations changed **because the approved contract changed**, nothing was loosened:
  case 07's centre hole was `AMBIGUOUS` and is now `CENTER_CLEARED_RESIDUAL_REMAINS` (centre-clear x = [−0.3, 0.3], residual on both sides);
  case 13 and 15 wording ("etched 0.1000um" + detail line; "post-step exported-mesh residual detected; no comparable pre-step support").
  Renamed constants in 03, 06, 09, 10, 16, 17. The synthetic builder now shares point indices for exactly coincident coordinates.
* New 21–42: 21 fully cleared · 22 centre-clear + edge residual · 23 span of 1 interval → `AMBIGUOUS` · 24 post-only residual ·
  25 residual metadata (area 0.04, x/y extent, both edges, 2 components of 2 triangles) · 26 isolated one-triangle island (+ island with a vertex on the edge) ·
  27 residual attached to outside bulk by a shared edge · 28 hairline gap (0.5 ε, 0.9 ε) between same-height bodies → `AMBIGUOUS` ·
  29 vertex-only and T-junction contacts are separate components · 30 shared-edge triangles are one component ·
  31 component switch mid-run (post; pre) → `AMBIGUOUS` · 32–35 reach · 36 Mask post-only text has no `created` / `newly exposed` / `mask moved` ·
  37 every state prints `evidence source: exported volume mesh` · 38 residual does not erase the centre-clear fact ·
  39 no cutoff removes a 2e-9 µm² sliver · 40 several windows keep metadata separate · 41 ripple centre patch prints its 0.100 of 4.000 µm run width, no window-wide claim ·
  42 static (§9).
* Mutation check (scratch, repo untouched): vertex-only counts as connected → 29, 31 fail · component id not tracked → 28, 31 fail ·
  midpoint-only `_reach` → 34, 35 fail · residual size cutoff → 39 fails · centre-clear reported as fully cleared → 07, 22, 25, 26, 27, 38, 39, 40 fail ·
  island = "touches no edge" → 26 fails (first survived; case 26 was strengthened). The tests can fail.

## 8. Real selectivity runs (`test_etch_selectivity_real.py`, all four run to the end)

Native physics assertions untouched and passing: Directional plain 0.75000 / selective 0.15000 µm native Si removal, oxide removed,
protected bands unmoved, independence proven. Diagnostic Si displacement vs native core, bound = the project's 0.001 µm comparison tolerance:
plain 0.7505 (native 0.7500), selective 0.1505 (native 0.1500).

| run | SiO₂ | Mask |
|---|---|---|
| Directional / plain | `FULLY_CLEARED_IN_WINDOW` | no line |
| Directional / **selective** | `CENTER_CLEARED_RESIDUAL_REMAINS` | `POST_ONLY_RESIDUAL` |
| Isotropic / plain | `FULLY_CLEARED_IN_WINDOW` | no line |
| Isotropic / selective | `FULLY_CLEARED_IN_WINDOW` | no line |

Directional/selective asserted, not waved through: centre-clear span covers the fixture core (−0.75, 0.75); not fully cleared;
residual components lie wholly outside the core; component areas sum to the total; evidence source on every state; the Mask line
makes no creation/motion claim.

## 9. Complete diagnostic logs of the four real runs

**directional/plain**

```
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-2.000, 2.000]:
    Si: etched 0.7505um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.800, 1.800], 72 common intervals, 3.600 of 4.000 um of the window; evidence source: exported volume mesh)
    SiO2: fully cleared in the exported-mesh window
      (no positive-area post-step intersection; evidence source: exported volume mesh)
```

**directional/selective**

```
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-2.000, 2.000]:
    Mask: post-step exported-mesh residual detected; no comparable pre-step support
      (physical creation or exposure is not inferred; evidence source: exported volume mesh)
      (Mask-tagged residual: total clipped area 0.0001685 um2; x=[-2.00000, 2.00000], y=[-0.04204, 0.20000]; touches left window edge: yes, right: yes; 4 component(s); evidence source: exported volume mesh)
        component 1: clipped area 8.196e-05 um2; x=[-2.00000, -1.99725], y=[-0.04204, 0.13740]; touches left: yes, right: no; whole-mesh triangles 10; triangles intersecting the window 5; isolated island (every triangle of the component lies inside or on the window boundary): no
        component 2: clipped area 8.196e-05 um2; x=[1.99725, 2.00000], y=[-0.04204, 0.13740]; touches left: no, right: yes; whole-mesh triangles 10; triangles intersecting the window 6; isolated island (every triangle of the component lies inside or on the window boundary): no
        component 3: clipped area 2.276e-06 um2; x=[-2.00000, -1.99991], y=[0.15013, 0.20000]; touches left: yes, right: no; whole-mesh triangles 802; triangles intersecting the window 1; isolated island (every triangle of the component lies inside or on the window boundary): no
        component 4: clipped area 2.276e-06 um2; x=[1.99991, 2.00000], y=[0.15013, 0.20000]; touches left: no, right: yes; whole-mesh triangles 802; triangles intersecting the window 1; isolated island (every triangle of the component lies inside or on the window boundary): no
    Si: etched 0.1505um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.900, 1.900], 76 common intervals, 3.800 of 4.000 um of the window; evidence source: exported volume mesh)
    SiO2: cleared from the window center; residual exported-mesh material remains elsewhere in the window
      (center-clear x=[-1.99982, 1.99982], 90 common intervals; no whole-window full-clear claim; evidence source: exported volume mesh)
      (SiO2-tagged residual: total clipped area 1.484e-05 um2; x=[-2.00000, 2.00000], y=[0.05000, 0.15022]; touches left window edge: yes, right: yes; 2 component(s); evidence source: exported volume mesh)
        component 1: clipped area 7.422e-06 um2; x=[-2.00000, -1.99982], y=[0.05000, 0.15022]; touches left: yes, right: no; whole-mesh triangles 410; triangles intersecting the window 6; isolated island (every triangle of the component lies inside or on the window boundary): no
        component 2: clipped area 7.422e-06 um2; x=[1.99982, 2.00000], y=[0.05000, 0.15022]; touches left: no, right: yes; whole-mesh triangles 410; triangles intersecting the window 6; isolated island (every triangle of the component lies inside or on the window boundary): no
```

**isotropic/plain**

```
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-2.000, 2.000]:
    Si: etched 0.7505um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.900, 1.900], 76 common intervals, 3.800 of 4.000 um of the window; evidence source: exported volume mesh)
    SiO2: fully cleared in the exported-mesh window
      (no positive-area post-step intersection; evidence source: exported volume mesh)
```

**isotropic/selective**

```
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-2.000, 2.000]:
    Si: etched 0.1505um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.900, 1.900], 76 common intervals, 3.800 of 4.000 um of the window; evidence source: exported volume mesh)
    SiO2: fully cleared in the exported-mesh window
      (no positive-area post-step intersection; evidence source: exported volume mesh)
```

**Oxide/PR test (`test_oxidation_pr_etch_reaches_si_real.py`, strict checks unchanged, rc = 0):**

```
LOGGER (insufficient budget):
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-1.500, 1.500]:
    Si: unchanged within diagnostic tolerance; overlying material remains; etch front not demonstrated to have reached this material in the measured interior
      (measured on the paired flat interior x=[-1.500, 1.500], 62 common intervals, 3.000 of 3.000 um of the window; evidence source: exported volume mesh)
    SiO2: etched 0.1000um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.400, 1.400], 56 common intervals, 2.800 of 3.000 um of the window; evidence source: exported volume mesh)
LOGGER (sufficient budget):
ETCH RESULT BY MATERIAL (open window only):
  Window x=[-1.500, 1.500]:
    Si: etched 0.1505um
      (vertical paired flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.400, 1.400], 56 common intervals, 2.800 of 3.000 um of the window; evidence source: exported volume mesh)
    SiO2: fully cleared in the exported-mesh window
      (no positive-area post-step intersection; evidence source: exported volume mesh)
logger SiO2 etched 0.1000 um (insufficient) vs core exported 0.1000 (native 0.10000); logger Si etched 0.1505 um (sufficient) vs core exported 0.1505 (native 0.15000)
```

## 10. Static evidence: no size cutoff

* `test_etch_material_summary_mock.py` case 42 (AST): every numeric literal in `etch_diagnostics.py` (docstrings excluded) is in
  `{0, 1, 2, 3, 4, 23, 0.5, 0.001, 1e-30}`. Actual set: `0, 1, 2.0, 3, 4.0, 23, 0.5, 0.001, 1e-30`. Their roles: indices and counts;
  `2.0 ** -23` and `4.0` (the float32 geometry epsilon = 4 ulps of the largest coordinate); `0.5` (the midpoint); `0.001` =
  `DIAGNOSTIC_TOLERANCE_UM`, the project's existing comparison tolerance (only compares two top heights, never sizes a residual);
  `1e-30` (a zero-scale guard). No comparison against any other literal exists.
* The GUI formatter contains no `1e-`, `0.001` or `noise_floor`.
* Behaviour (not only source): case 39 keeps a 2e-5 µm × 1e-4 µm sliver (area 2e-9 µm²) next to a 0.02 µm² one; case 25/27/40 list every component.
* Scope: this proves what the SOURCE contains; behaviour is proven by the unit and real runs.
* Limit, stated openly: a clipped width ≤ ε (≈ 1.9e-6 µm) is indistinguishable from a boundary touch in float32 coordinates and is not counted
  (§14 UNKNOWN 1). Every residual measured in Batch 3A was ≥ 5.5e-5 µm wide (≥ 29 ε).

## 11. Evidence the strict physics assertions are kept

Lines removed from the two real tests (exact diff): oxide/PR test — the old single-line "vertical flat-interior displacement" check and the old
"fully cleared" substring check (both replaced by stricter block checks: paired-displacement wording, evidence source, exact
`SiO2: fully cleared in the exported-mesh window`, no residual listed, insufficient `SiO2: etched 0.1000um`) and a stale comment about a whole-window `max(y)`;
selectivity test — the old `check_diagnostic` body (replaced). **Kept unchanged**: the strict `logger_mismatches` block
(logger vs exported core AND vs native core, `abs(got - want) > fx.UNCHANGED_UM`), the final `assert not logger_mismatches`, every native
assertion in `check_model`, `check_protected`, the `abs(got - native_si_removed_um) <= fx.UNCHANGED_UM` check (now inside the new
`check_diagnostic`), the independence checks and the mask/window/budget/grid inputs.
Results: logger SiO₂ 0.1000 vs exported core 0.1000 / native 0.10000; logger Si 0.1505 vs exported core 0.1505 / native 0.15000.

## 12. Control tests

`test_cad_negative_validation_real` rc 0 (0.6 s) · `test_pin_placement_validation_real` rc 0 (0.6 s) ·
`test_oxidation_zero_duration_identity_real` rc 0 (4.5 s) · `test_oxidation_positive_time_unsupported_real` rc 0 (29.7 s).
No control broke; positive-time oxidation remains unsupported.

## 13. Repository state

```
$env:GIT_CONFIG_GLOBAL='NUL'; $env:GIT_CONFIG_NOSYSTEM='1'; git diff --check
(no output)   rc=0
```
Tracked files only; the two new source files were scanned separately (LF only). HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`;
`git log 3ba9404..HEAD` empty — **no commit**; 64 dirty entries before and after (same set). SHA-256 unchanged for `directional.py`,
`isotropic.py`, `backends/viennaps/io.py`, `wafer_state_v2.py`, `wafer_state.py`, `thermal.py`, `locos.py`, `zero_duration.py`,
`_explicit_etch_fixture.py`, `_explicit_oxide_fixture.py`; the manifest of every file under `docs/audits/` (1311 files, Batch 3A included, this report excluded) is identical to its pre-batch value.

## 14. Not executed / remaining UNKNOWN

Not executed: full regression; any commit; a live Tk window (the wrapper runs headlessly through the real `_log_etch_material_summary`, and the oxide/PR test instantiates `TCADApplication`);
the Batch 3A scripts (re-running them would rewrite that audit's raw files); two-window masks, oblique directional etch and other grids in the REAL tests.
As extra evidence (scratch, not a test) the new analyzer was run on the 12 saved Batch 3A meshes (grids 0.10 / 0.05 / 0.025): the same states appear at every grid
(Directional/selective: SiO₂ `CENTER_CLEARED_RESIDUAL_REMAINS`, Mask `POST_ONLY_RESIDUAL`; at g = 0.10 the SiO₂ residual is two isolated single-triangle islands; all other runs `FULLY_CLEARED_IN_WINDOW`, no Mask).

UNKNOWN:
1. The geometry epsilon: a residual whose clipped width is ≤ ~1.9e-6 µm cannot be distinguished from a boundary touch and is not listed (no measured residual is close to it).
2. What the residual is (native level-set feature, exporter tagging, or numerical) — still not established; the diagnostic claims none of it, by design.
3. A centre-clear span or flat run needs ≥ 2 common intervals: a very coarse mesh yields `AMBIGUOUS` (mesh-density dependent).
4. A real gap between two same-height bodies wider than ε ends the run at the gap and reports the connected body's number; only a gap below ε (or a touching/T-junction contact) triggers the component-switch `AMBIGUOUS`. Whether a wider gap should also refuse is a policy question.
5. `_reach` judges exposure on the post mesh only; "touching" uses the geometry epsilon.
6. The x-partition merges breakpoints closer than ε; component ids keep bodies separate, but an interval narrower than ε cannot exist.
7. Isolated-island uses the geometry epsilon at the window boundary.

---

# APPENDIX — original Batch 3 report (SUPERSEDED, kept unchanged for history)

The text below is the report written when Batch 3 stopped at the Directional/selective residual. Its statements about "cutoff needed",
`no unambiguous paired flat interior` for SiO₂ and the old wording are superseded by the sections above.

# Batch 3 implementation report — etch-result diagnostic

**STATUS: STOPPED at an immediate-stop condition (prompt §9). Not complete. Awaiting Codex review.**

Implemented per the prompt: paired centre-connected flat-interior diagnostic
(`tcad/mesh/etch_diagnostics.py`), wired into `_log_etch_material_summary()`.
Verified: 20/20 unit cases, the strict oxide/PR real test, and 3 of the 4 real
selectivity experiments. **One real experiment (Directional × selective) contradicts
the prompt's expected output ("SiO2 cleared") because of sub-grid slivers; satisfying
the expectation would need an arbitrary cutoff, which §9 forbids. Nothing was
adjusted.** Details in §8–§9 and §18.

Starting state: branch `claude/waferstate-v2`, HEAD
`3ba940404fd19c88eaaccc96a39ffe8444fb8851`, 62 dirty entries. Nothing was reset,
stashed, cleaned, reverted or committed. No full regression was run.

## 1. Call flow before this change

`TCADApplication.run_etch()` (tcad_2d_stagewise.py ~7290) →
`_log_etch_material_summary(pre_etch_mesh, final_mesh, open_windows_domain_um)` →
per material, `top_in_window()` = `max(y)` over mesh **nodes** whose x lies in the
inclusive window; `before - after` printed as "etched X um"; `Si` with `|moved| <
0.001` printed as "unchanged (not yet reached)"; a material with no node in the window
after → "fully cleared"; no node before → "newly exposed". Measured defect
(`raw/logger_shoulder.json`, `raw/narrow_window_real_rows.jsonl`): the maximum is the
protected mask-edge shoulder (0.045 vs 0.100 µm for oxide; 0.127 vs 0.150 µm for Si).

## 2. Changed files

| file | role |
|---|---|
| `tcad/mesh/etch_diagnostics.py` (new, 13.2 KB) | pure numpy diagnostic: triangle/slab presence, common x-partition, per-interval scanline sections, paired centre-connected flat run, reach classification. No ViennaPS/GUI import. |
| `tcad_2d_stagewise.py` | only `_log_etch_material_summary()`: reads the two meshes into `TaggedMesh`, calls `analyze_etch_windows`, formats structured results. Exact delta +52/−35 lines, all inside the function (hunks at 6945, 6951, 6963). Outer exception/`open_windows=[]` behaviour untouched. `grid_delta_um` not needed, not passed. |
| `tests/unit/test_etch_material_summary_mock.py` (new) | 19 required cases + 1 static case. |
| `tests/integration/test_oxidation_pr_etch_reaches_si_real.py` | old phrase requirement replaced by evidence-based wording; strict logger-vs-core check kept and extended with the NATIVE core; docstring/success message updated. Delta +24/−10. |
| `tests/integration/test_etch_selectivity_real.py` | native physics assertions untouched; added `check_diagnostic()` applying the GUI's real log path to each of the 4 runs. Delta +36/−0. |
| this report | |

`isotropic.py`, `directional.py`, exporter, WaferState, oxidation: not touched
(`isotropic.py` already showed ` M` at session start; not edited by this batch).
Pre-batch working diffs of the three allowed existing files were preserved before any
edit; the pre-batch `tcad_2d_stagewise.py` was reconstructed and its SHA-256
(`75A48B83…46A1`) matches the recorded one, so the deltas above are exact.

## 3. Production diff

Exact production delta: `tcad_2d_stagewise.py` +52/−35, function-local. The removed
lines are the node-`max` reader (`top_in_window`, `by_mat`, `noise_floor_um`, the
"not yet reached" / "newly exposed" branches); the added lines are the mesh reader
into `TaggedMesh`, a `describe()` formatter, and the call
`etch_diag.analyze_etch_windows(pre, post, open_windows_um)`. Full new-module source:
`tcad/mesh/etch_diagnostics.py`.

## 4. Static evidence that the node/max method is gone

* `test_etch_material_summary_mock.py` case 20 (AST): `_log_etch_material_summary`
  calls no `max`/`min`, has no nested `top_in_window`, and its source contains none of
  `top_in_window`, `not yet reached`, `newly exposed`, `noise_floor_um`, `node_idxs`;
  `etch_diagnostics.py` contains none of `np.median`, `statistics`, `node_idxs`, `by_mat`.
* `Select-String` on `tcad_2d_stagewise.py` for those four phrases: 0 matches.
* Scope of this evidence: it shows the OLD path is absent from these two files. It does
  not prove the new analyzer correct (cases 1–19 and the real runs do).

## 5. Triangle/window intersection contract (§3.1)

Presence = a triangle of that material whose polygon clipped to the slab
`[x_lo, x_hi]` (Sutherland–Hodgman) has area > ε² **and** x-extent > ε. A vertex inside
the window is neither necessary nor sufficient. `CLEARED` only if pre has such a
triangle and post has none; `POST_ONLY` if the reverse.
ε (geometry epsilon) = 4 float32 ulps of the largest coordinate involved
(`4·2⁻²³·max|coord|`, ≈1.9e-6 µm here) — derived from the exporter's float32
serialization, used only for same-point tests and slab-crossing; it is **not** the
diagnostic tolerance.

## 6. Paired centre-flat selection contract (§3.2–3.4)

Common x-partition = window ends + every pre/post triangle vertex x inside the window
(deduplicated within ε). At each interval three vertical scanlines (both ends and the
middle) give, per material, merged y-components (merged within ε). An interval is
valid only if pre and post each have exactly one component on all three scanlines.
The run starts at the interval(s) containing the window midpoint (both sides if the
midpoint is a node; they must agree) and extends while pre tops stay within
`DIAGNOSTIC_TOLERANCE_UM` (0.001 µm, the project's old logger noise floor, called a
comparison tolerance, never a resolution) of the centre pre top and post tops within
it of the centre post top. Number reported only if the run has ≥2 adjacent intervals and
width > ε; else `no unambiguous paired flat interior`, with reason and post top range
in the structured result. Displacement = pre centre top − post centre top
(> tol → `etched`; |·| ≤ tol → `unchanged`; < −tol → `top rose or correspondence is
indeterminate`). UNCHANGED reach on the post mesh along the whole run: `exposed` (no
other material above), `overlain` (another material directly above), else
`cannot be inferred`. `newly exposed` removed.

## 7. Synthetic cases (20/20 PASS, rc=0, 0.9 s)

01 flat known displacement PASS · 02 shoulder above centre → centre chosen (0.15, run
[−0.8, 0.8]) PASS · 03 remesh, all post vertices outside window, still present PASS ·
04 pre/post x-columns differ PASS · 05 feature-switch counterexample (independent
longest plateaus would say 0.5; paired says 0.2) PASS · 06 two vertical components PASS
· 07 equal-height runs separated in x not merged; centre hole cannot be bridged PASS ·
08 two windows independent PASS · 09 sloped surface refuses PASS · 10 ripple: flat piece
off-centre refused, flat piece at centre reported with its 0.1 µm extent on record PASS
· 11 float32 (mixed float32/float64 meshes, no sliver intervals) PASS · 12 zero-rate
exposed Si PASS · 13 oxide remains, Si unchanged PASS · 14 negative displacement PASS ·
15 pre-absent/post-present not "newly exposed" PASS · 16 vertices outside window ≠
"fully cleared" PASS · 17 <2 intervals / zero width refuses PASS · 18 `open_windows=[]`
PASS · 19 analyzer exception is diagnostic-only through the real GUI wrapper (no other
state touched; unreadable mesh also swallowed) PASS · 20 static (§4) PASS.

Mutation check (scratch, repo untouched): M1 window-wide max → 02,05,06,07,09,10,12,13,14,17
fail; M2 widest interval not centre-connected → 01,02,05,07,09,10,13,14,17 fail; M3
vertex-based presence → 03,06,08,16,17 fail; reach forced "overlain" → 12 fails; forced
"exposed" → 13 fails. The tests can fail.

## 8. Real experiments

**`test_oxidation_pr_etch_reaches_si_real.py`: PASS, rc=0, 8.4 s.** Grid, window, mask,
budgets unchanged. Real logger output:

```
LOGGER (insufficient budget):
  Window x=[-1.500, 1.500]:
    Si: unchanged within diagnostic tolerance; overlying material remains; etch front not demonstrated to have reached this material in the measured interior
      (measured on the paired flat interior x=[-1.500, 1.500], 62 common intervals, 3.000 of 3.000 um of the window)
    SiO2: etched 0.1000um (vertical flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.400, 1.400], 56 common intervals, 2.800 of 3.000 um of the window)
LOGGER (sufficient budget):
    Si: etched 0.1505um (vertical flat-interior displacement; not undercut/path length)
      (measured on the paired flat interior x=[-1.400, 1.400], 56 common intervals, 2.800 of 3.000 um of the window)
    SiO2: fully cleared (was present, now gone here)
logger SiO2 etched 0.1000 um vs core exported 0.1000 (native 0.10000); logger Si etched 0.1505 um vs core exported 0.1505 (native 0.15000)
```
Shoulder excluded automatically at |x| = 1.4 (the mesh's own flat/non-flat boundary; no fitted margin).

**`test_etch_selectivity_real.py`: FAIL, rc=1, 2.8 s**, at directional/selective, on
the new diagnostic check only (all native physics assertions before it passed).

| run | Si (vertical flat-interior) | native core | SiO2 | Mask |
|---|---|---|---|---|
| directional / plain | 0.7505 | 0.75000 | fully cleared | — |
| directional / **selective** | 0.1505 | 0.15000 | **no unambiguous paired flat interior** | **`present in post mesh but no comparable pre-step support`** |
| isotropic / plain | 0.7505 | — | fully cleared | — |
| isotropic / selective | 0.1505 | — | fully cleared | — |

(Isotropic runs were not reached by the failing test; their rows come from the
non-asserting evidence script below.)

## 9. Why it stopped (§9: triangle-tagging/export characteristic; directional passes where…; arbitrary cutoff needed)

Non-asserting evidence run, real ViennaPS, all four experiments, window x=[−2, 2]:

```
directional/selective
   SiO2 post triangles crossing the window: 12; total area 1.485e-05 µm²
      area 2.72e-06  clipped x-width 1.78e-04  bbox x[ 1.9998, 2.0]   y[0.10, 0.15]
      area 2.29e-06  clipped x-width 9.2e-05   bbox x[-2.0, -1.9999]  y[0.10, 0.15]
      area 1.37e-06  clipped x-width 5.5e-05   bbox x[ 1.9999, 2.0]   y[0.05, 0.10]
   Mask post triangles crossing the window: 13; total area 1.68e-04 µm² (pre: 0)
      area 3.58e-05  clipped x-width 1.43e-03  bbox x[ 1.9986, 2.0]   y[0.05, 0.10]
      area 1.33e-05  clipped x-width 2.75e-03  bbox x[ 1.9972, 2.0]   y[-0.042, -0.016]
directional/plain, isotropic/plain, isotropic/selective:
   SiO2 post triangles crossing the window: 0;  Mask post triangles crossing the window: 0
```

The SiO2 slivers (≤1.8e-4 µm wide) and the Mask slivers (≤2.75e-3 µm wide) sit at the
window edge (x within 0.003 µm of ±2.0), far below the 0.05 µm grid but 30–1400×
above the geometry ε. By the §3.1 rule ("positive-area intersection") they ARE
present, so the analyzer's `not cleared` / `post-only Mask` verdicts follow the
contract. Making SiO2 read "cleared" and hiding Mask would require a minimum sliver
width or area — an arbitrary cutoff the prompt forbids — so nothing was adjusted.
Interior (centre) result for Si is correct in all four runs.

## 10. Zero-rate exposed Si (synthetic, real GUI wrapper)

```
    Si: unchanged within diagnostic tolerance; surface is exposed
      (measured on the paired flat interior x=[-1.000, 1.000], 8 common intervals, 2.000 of 2.000 um of the window)
    SiO2: fully cleared (was present, now gone here)
```
No "not yet reached".

## 11. Unchanged Si with oxide remaining

```
    Si: unchanged within diagnostic tolerance; overlying material remains; etch front not demonstrated to have reached this material in the measured interior
    SiO2: etched 0.1000um (vertical flat-interior displacement; not undercut/path length)
```

## 12. Ambiguity / sloped / disconnected outputs

```
sloped:        Si: no unambiguous paired flat interior; vertical displacement not reported
                 (reason: the window midpoint sits on a node whose two sides disagree; post top range -0.2963..-0.0038 um)
2 components:  Si: no unambiguous paired flat interior; vertical displacement not reported
                 (reason: material is absent or has more than one vertical component at the window midpoint (pre or post))
centre hole:   Si: no unambiguous paired flat interior; vertical displacement not reported
                 (reason: ... absent or has more than one vertical component at the window midpoint ...; post top range -0.1000..-0.1000 um)
negative:      Si: top rose or correspondence is indeterminate; etch displacement not reported
pre-absent:    SiO2: present in post mesh but no comparable pre-step support; displacement unavailable
```
Note: the sloped case is refused with the "two sides disagree" reason because its
midpoint happens to be a mesh node; with the midpoint inside an interval the reason is
"no flat surface (pre and post) at the window midpoint". Both refuse; wording differs.

## 13. Strict logger-vs-core check

Kept unrelaxed in the oxide/PR test and extended: logger vs exported core AND vs native
core, both bounded by `fx.UNCHANGED_UM` (0.001). **Passed** (0.1000/0.1000 and
0.1505 vs 0.1500, difference 0.0005).

## 14. Targeted test results

| test | rc | time |
|---|---|---|
| `tests/unit/test_etch_material_summary_mock.py` | 0 (20/20) | 0.9 s |
| `test_oxidation_pr_etch_reaches_si_real.py` | 0 | 8.4 s |
| `test_etch_selectivity_real.py` | **1** (directional/selective diagnostic check) | 2.8 s |
| `test_cad_negative_validation_real.py`, `test_pin_placement_validation_real.py`, `test_oxidation_zero_duration_identity_real.py`, `test_oxidation_positive_time_unsupported_real.py` | **not run** | — |

## 15. `git diff --check`

```
$env:GIT_CONFIG_GLOBAL='NUL'; $env:GIT_CONFIG_NOSYSTEM='1'; git diff --check
(no output)   rc=0
```
Covers tracked files only. The two new files (not covered by `git diff --check`) were
scanned separately: 0 CRLF, 0 trailing-whitespace lines.

## 16. HEAD and commits

HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`; no commit made; 62 pre-existing dirty
entries + this batch's files (3 modified, 2 new source files, this audit folder).

## 17. Not executed

Full regression; the four Batch-1/zero-duration/positive-time control tests (stopped at
§9 before the run order reached them, so they are **unverified**, not "assumed
unaffected"); a real GUI canvas/`app` run of the log path with a live Tk window (the
wrapper was exercised headlessly through the real `_log_etch_material_summary` with a
stub `_log`, plus the real oxide/PR test which instantiates `TCADApplication`);
non-isotropic/oblique directional etch beyond the vertical Directional case; two-window
masks on real meshes.

## 18. Remaining physical / numerical UNKNOWNs

1. Cause of the sub-grid SiO2 and Mask slivers in Directional/selective (level-set
   narrow-band, exporter, or the selective `material_rates` path) — unidentified, not
   investigated; the Mask sliver (rate 0) protruding 2.75e-3 µm into the window is
   unexplained.
2. Decision needed from Codex: how a diagnostic may treat sub-grid slivers **without an
   arbitrary cutoff** (e.g. tie presence to the same paired centre-run instead of
   whole-window area; or report "sliver present, centre cleared" as its own status).
   The current contract yields a truthful but unhelpful line for this real case.
3. The ≥2-interval requirement depends on mesh density (documented in the prompt);
   coarse meshes refuse valid flat floors.
4. The 0.0005 µm offset between exported (0.1505) and native (0.1500) Si displacement is
   the known grid-proportional exporter representation offset (cause unidentified);
   it is inside the 0.001 µm comparison tolerance but is not a measured resolution.
5. Reach "overlain"/"exposed" is judged at midpoint scanlines of the run only.
6. Sloped-surface refusal reason text depends on whether the midpoint is a node.

## Reproduction

* Unit: `python tests\unit\test_etch_material_summary_mock.py`
* Real: `python tests\integration\test_oxidation_pr_etch_reaches_si_real.py`,
  `python tests\integration\test_etch_selectivity_real.py` (currently fails as in §8).
* Environment note: the prompt's `$env:PATH = "$(Resolve-Path '..\.venv\Library\bin);$env:PATH"`
  has a quoting error (PowerShell parse failure); it was run as
  `"$((Resolve-Path '..\.venv\Library\bin').Path);$env:PATH"`, same intent.
  The non-asserting evidence script for §9 is not stored in the repo (only this
  report's outputs are); it is a 60-line scratch driver over the test module's own recipes.
