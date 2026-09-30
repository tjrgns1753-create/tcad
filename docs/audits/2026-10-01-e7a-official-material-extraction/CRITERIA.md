# E7A criteria: can ViennaPS 4.6.2 official API replace `save_locos_volume_mesh()`'s own material classification? (fixed before the probe runs)

Investigation only: no production refactor, no physics change, no version change, no non-public API, no automatic fallback. Output: a new audit directory, a remote profile/request.
**Base.** HEAD `5495b296884ee402ee5ca82d84d2cb321fa0d274`, branch `claude/remote-runner`, tracked dirty 0, no evaluation running. Only the root CLAUDE.md exists. Serena session 14064f89.
ViennaPS / ViennaLS run only on the GitHub-hosted runner; local work = reading and static checks.

## 1. What the project code does today (read, file:line in `tcad/backends/viennaps/io.py`)
- `save_volume_mesh` (396-452): floored deep copy (`_floored_copy_for_export`, 236-328: `vls.Expand(ls, 3)` then a per-level-set `BooleanOperation INTERSECT` with a floor box) then `domain.saveVolumeMesh(path)`;
  if an export hint is registered it delegates to `save_locos_volume_mesh`; warns when a domain material is missing in the written mesh (`_warn_if_materials_missing_from_export`, 331-393).
- `save_locos_volume_mesh` (622-830): (1) every level set is exported ALONE as a single-material throwaway domain (`_export_single_level_set`, 506-581, floored, `bounds_hint` = union bbox from `_union_bounding_box`, 465-503);
  (2) for a level set flagged `wrapped` it keeps only triangles whose centroid is above the running top-surface lookup `_top_lookup` (584-619: per-x-bin max vertex y, nearest-bin fill, bin = grid_delta) plus margin 0.1 grid_delta;
  (3) merges all materials into one mesh; optional `dedupe_materials` merges coincident vertices of the listed materials (9-decimal rounding) so the importer can find shared interface edges.
  Its stated reason (docstring 648-656, `docs/investigation_log.md` 719-735): a ViennaLS `RELATIVE_COMPLEMENT` returns an EMPTY level set whenever an operand has been through a `UNION` (every wrapped level set), so wrapped layers cannot be separated with Booleans.

## 2. What the official 4.6.2 / 5.8.5 sources say (installed wheels: viennaps 4.6.2, viennals 5.8.5; source fetched at the same tags)
- ViennaPS v4.6.2 `include/viennaps/psDomain.hpp`: `insertNextLevelSetAsMaterial(ls, material, wrapLowerLevelSet=true)` (l.177-200) unions the new level set with the previous one when wrapping;
  `getMaterialLevelSet(material)` (l.461-490) copies `levelSets_[i]` and, for i > 0, applies `BooleanOperation RELATIVE_COMPLEMENT(copy, levelSets_[i-1])` -- i.e. exactly the Boolean operation the project found empty for UNION-tainted operands -- and returns an empty level set with a warning when the material is absent;
  `saveVolumeMesh(fileName, wrappingLayerEpsilon = 1e-2)` (l.645-656) passes all level sets and the material map to `viennals::WriteVisualizationMesh` with `setWrappingLayerEpsilon`; `DEFAULT_WRAPPING_EPSILON = 1e-2` (l.718).
- ViennaLS v5.8.5 `lsWriteVisualizationMesh.hpp`: "Level sets wrapping other level sets have to be inserted last." (l.445); level sets are processed from the last (top) down, the k-th lower one is rasterised with an offset of `-LSEpsilon * counter` (l.600) into the current mesh and clipped.
  So `wrappingLayerEpsilon` is a per-layer offset of the lower layers' iso-surface (unit: level-set value units = grid delta, to be confirmed by measurement), NOT a wrapping-resolution tolerance. Prediction (fixed now): the k-th layer boundary from the top moves by about `epsilon * k * grid_delta`;
  the E2-era measurement "native saveVolumeMesh interface +0.0100 x grid" (`docs/audits/2026-09-20-explicit-oxide-fixture-spike/REPORT.md` EXP 10) is consistent with epsilon 0.01 and k = 1.
- The bindings (`viennaps/d2/__init__.pyi`: `getMaterialLevelSet` l.325, `saveVolumeMesh` l.405, `getSurfaceMesh` l.359) document none of this.
- The official wrapped convention is NESTED level sets (each inserted level set contains all lower ones). The project's LOCOS oxidation-time stack is [Si, SiO2 (wrapped), Mask (NOT wrapped)], which violates "wrapping level sets last"; `_make_locos_domain_chainable` (locos.py:280-335) later unions the mask into the stack (nested).

## 3. Fixed inputs (explicit geometry; `vps.Oxidation` and `vps.Process` trapped with counters, never a positive-time oxidation)
Common: `session.create_domain(grid, 2.0, 2.0)` (x in [-1, 1] um), Si `MakePlane(0.0)`, export floor depth 1.0 um (Si region [-1.0, 0]).
- **A** planar Si/SiO2: SiO2 `MakePlane(0.30, wrap=True)`, grid 0.05. Analytic: SiO2 [-1,1] x [0, 0.30].
- **B1** thin wrapped pad oxide: pad 0.10, grid 0.05 (2 grid); **B2**: pad 0.10, grid 0.10 (1 grid). Analytic: SiO2 [-1,1] x [0, 0.10].
- **C** partial-mask LOCOS stack as built by `LocosOxidation._build_locos_geometry` (EXP 6 recipe): grid 0.05, pad 0.10, mask window |x| < 0.5, mask [0.5, 1.0] and [-1.0, -0.5] x [0.10, 0.40]; stack [Si, SiO2, Mask], wrap [F, T, F] (project topology).
  **C-N** = the same stack after `_make_locos_domain_chainable` on a deep copy (nested, official-convention topology). Analytic: Si [-1,1] x [-1,0]; SiO2 [-1,1] x [0,0.10]; Mask two boxes x [0.10,0.40].

## 4. Extraction routes compared on every input
- **R0** project `save_locos_volume_mesh` (no dedupe) and **R0d** with `dedupe_materials` = all materials (the reference for shared-interface capability).
- **R1** official, raw: `domain.saveVolumeMesh(path)` with the default epsilon on the unmodified domain (no floor: Si is cut by the narrow band; Si bottom reported, Si area NOT judged). Plus the epsilon sensitivity set {0.0, 0.01, 0.02} on A and C-N (characterisation only, nothing is selected or tuned).
- **R2** official material level sets: for each material in `domain.getMaterialsInDomain()`: `ls = domain.getMaterialLevelSet(m)`; record `ls.getNumberOfPoints()` (empty = failure), then mesh each non-empty `ls` with the project's existing single-level-set export (floored) and merge with tags. This is the candidate that would replace `_top_lookup` clipping.
- **R3** official `domain.getSurfaceMesh(addInterfaces=True)`: characterised only (nodes/lines/cell data; interface line positions vs analytic). It is a boundary mesh, not a volume replacement.
- **P0** control reproducing the old minimal proof (`docs/investigation_log.md` 719-735) in this runner: two never-unioned planes `RELATIVE_COMPLEMENT` -> slab; the same after one `UNION` -> (old claim) empty. Native stdout/stderr is captured for every call and saved raw.

## 5. Judgement items (per route x input; ground truth = the explicit input geometry, never another route's output)
Position tolerance delta = 0.02 x grid_delta + 1e-6 um: twice the default-epsilon offset predicted above plus float32 mesh serialisation. Not adjusted after results.
1. Materials: the set of tags equals the expected set and each has > 0 triangles (no empty / missing material).
2. Area: per-material area within (interface length x delta) of the analytic area (Si compared only for routes with the floor).
3. Interface / boundary positions at columns x = 0, +-0.8 (and the C window edges): Si top, SiO2 bottom/top, Mask bottom/top within delta of analytic.
4. Column consistency: within each scanned column, material extents do not overlap and leave no gap larger than delta.
5. Interface connectivity: number of mesh edges shared between touching materials, and duplicate-coordinate points (R0 without dedupe is known to give 0 shared edges; conformal = shared edges ~ interface length / element size).
6. No native warning/error of the form "not found" / "empty" and no exception; a crash or an empty level set is recorded with its raw native log as the result.
Verdict mapping (fixed): **replaceable** = R2 passes items 1-4 and 6 on A, B1, B2, C and C-N and its interface connectivity is not worse than R0d; **limited** = R2 (or R1) passes on a proper subset (e.g. only nested / non-Boolean cases);
**not replaceable** = R2 and R1 fail items 1-3 on A or B; **insufficient evidence** = results are inconsistent or a failure cannot be attributed. A successful extraction is geometry evidence only, not DEVSIM electrical or process-physics evidence.

## 6. Out of scope / forbidden
No change to `tcad/`, existing tests, installed engines; no private API; no automatic fallback; no full regression; no PN/DD solve. The probe lives only in this directory; the remote profile/request are the only other files touched.
