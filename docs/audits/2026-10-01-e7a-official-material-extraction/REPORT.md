# E7A REPORT: can ViennaPS 4.6.2 official API replace `save_locos_volume_mesh()`'s own material classification?

Investigation only. No file under `tcad/` or `tests/` was changed; engines untouched; no fallback added. Mesh extraction success is geometry evidence only, not DEVSIM electrical or process-physics evidence.
Criteria fixed before the probe: `CRITERIA.md` (cc53271); post-hoc supplements labelled in `S1_CRITERIA.md` (routes R4-R7; the verdict mapping of CRITERIA.md section 5 was not changed).
Runs (GitHub-hosted Windows, viennaps 4.6.2, viennals 5.8.5, numpy 2.4.6, meshio 5.3.5): main 36761352831 (exec b65ea01), S1 36761746538 (feb5811), S1b 36762248912 (160baff), S1c 36762442241. Two earlier S1b triggers failed on my own
probe syntax errors (runs 36761956228 and 36762108802, fixed in 160baff) and produced no evidence.

## Verdict: **limited (제한적 가능)**
- The official `saveVolumeMesh` (on the project's floored copy) extracts every NESTED input correctly (A, B1, B2 incl. the 1-grid pad, C-N), with conformal Si|SiO2 and Mask|SiO2 interface edges (no `dedupe_materials` needed). It fails the project's un-nested oxidation-time LOCOS stack (C): Si is lost.
- The official `getMaterialLevelSet` cannot replace the `_top_lookup` classification in general: it returns an empty surface for a slab <= 1 grid thick (B2) and lost 1.7 % of the mask area on C / C-N (pre-registered item 2 fails).
- "Replaceable" (R2 passes A, B1, B2, C, C-N) is NOT met; "not replaceable" is not met either (R2 passes A, B1 and the positions of C / C-N; R4 passes all nested inputs).

## 1. What the current code does (`tcad/backends/viennaps/io.py`; details in CRITERIA.md section 1)
`save_locos_volume_mesh` (622-830): per-level-set isolated export (`_export_single_level_set` 506-581), per-x-bin top-surface lookup `_top_lookup` (584-619) with centroid clipping for `wrapped` level sets (768-776), merge, optional coordinate dedupe (808-821).
`save_volume_mesh` (396-452): floored deep copy (`_floored_copy_for_export` 236-328) + `domain.saveVolumeMesh`; delegates to `save_locos_volume_mesh` when an export hint exists (440-445).

## 2. Official sources (same tags as the installed wheels)
- ViennaPS v4.6.2 `psDomain.hpp`: `getMaterialLevelSet` (l.461-490) = copy of level set i, `RELATIVE_COMPLEMENT` against level set i-1; `saveVolumeMesh(file, wrappingLayerEpsilon = 1e-2)` (l.645-656); `insertNextLevelSetAsMaterial(..., wrapLowerLevelSet = true)` unions with the previous level set (l.189-193).
- ViennaLS v5.8.5 `lsWriteVisualizationMesh.hpp`: "Level sets wrapping other level sets have to be inserted last." (l.445); the k-th lower level set is rasterised with offset `-LSEpsilon * counter` (l.600).
  => `wrappingLayerEpsilon` is a per-layer iso-surface offset, not a wrapping tolerance. Measured (`A_R1*`): epsilon 0.0 -> exact areas (SiO2 0.6000 vs analytic 0.6); default 0.01 -> SiO2 0.5990 (interface up by 0.0005 = 0.01 x grid, matches the predicted `epsilon * k * grid`);
  0.02 -> 0.5980; on C-N epsilon 0.02 moves a boundary beyond the position tolerance (`CN_R1_eps0.02` J3 False). No epsilon was tuned or selected; the default 0.01 stays inside tolerance (<= 0.86 of it). The python stubs document none of this.
- The official convention is NESTED level sets. The project's oxidation-time LOCOS stack [Si, SiO2 (wrapped), Mask (not wrapped)] violates it; `_make_locos_domain_chainable` (locos.py:280-335) nests it afterwards.

## 3. Results (ground truth = explicit input geometry; tolerance delta = 0.02 x grid + 1e-6 um, area tol = perimeter x delta; raw JSON / meshes / native logs in the `data/` run directories)
| run tag | materials | area | positions | columns | shared edges (index) | duplicate pts | max area err / tol |
|---|---|---|---|---|---|---|---|
| A_R0 (project) | ok | ok | ok | ok | 0 | 861 | 0.0 |
| A_R0d (project + dedupe) | ok | ok | ok | ok | 40 | 0 | 0.0 |
| A_R1 official raw | ok | ok | ok | ok | 40 | 0 | 0.22 |
| A_R2 official material LS | ok | ok | ok | ok | 0 | 41 | 0.0 |
| A_R4 official on floored copy | ok | ok | ok | ok | 40 | 0 | 0.11 |
| B1_R0 / R0d / R1 / R2 / R4 (pad 2 grid) | ok | ok | ok | ok | 0 / 40 / 40 / 0 / 40 | 861 / 0 / 0 / 41 / 0 | 0.0 / 0.0 / 0.24 / 0.0 / 0.12 |
| B2_R0 / R0d / R1 / R4 (pad 1 grid) | ok | ok | ok | ok | 0 / 20 / 20 / 20 | 231 / 0 / 0 / 0 | 0.0 / 0.0 / 0.24 / 0.12 |
| **B2_R2** | **exception** | | | | | | `ValueError: need at least one array to concatenate` (empty VTU) |
| C_R0 / R0d (project topology) | ok | ok | ok | ok | 0 / 60 | 883 / 0 | 0.78 |
| **C_R1** official raw | **Si missing** | fail | fail | ok | 20 | 0 | 47.5 |
| **C_R2** official material LS | ok | **fail (Mask 0.2950 vs 0.3000, tol 0.0032)** | ok | ok | 0 | 61 | 1.56 |
| **C_R4** official on floored copy | **Si missing** | fail | fail | ok | 20 | 0 | 333 |
| CN_R0 / R0d | ok | ok | ok | ok | 0 / 60 | 1804 / 0 | 0.78 |
| CN_R1 / **CN_R4** (nested) | ok | ok | ok | ok | 60 | 0 | 0.86 |
| **CN_R2** | ok | **fail (same Mask 0.2950)** | ok | ok | 0 | 61 | 1.56 |
R1 does not judge Si area (no floor: Si is the ~2-grid narrow band). R3 (`getSurfaceMesh`) returns boundary nodes/lines only (A: 82 nodes / 80 lines; interface lines at y = 0 and the top, matching the analytic values in every column; C has the mask bottom at 0.099999), with no readable material ids in the
cell-data names (`getScalarDataLabel` exists; not parsed): a boundary mesh, not a volume replacement.
Mask area attribution (local analysis of the saved meshes): the deficit sits in the two 0.05-wide x-slabs at the mask inner corners (R0 0.01375, R2 0.01250 vs 0.01500 full); R2's extra loss comes from the complement removing the pad region at the level-set-rounded contact corner.
No native warning or error line appeared in any raw log (30 + 10 + 2 + 1 runs); the only diagnostics are the exceptions above.

## 4. Relation to the old Boolean-failure evidence (`docs/investigation_log.md` 719-735)
- Old claim: `RELATIVE_COMPLEMENT` returns an EMPTY level set whenever an operand went through a UNION. NOT reproduced here: P0 (two independent planes vs a wrapped stack, `session.create_domain`) both give the 0 -> 0.5 slab (164 points, y in [0, 0.5]); `getMaterialLevelSet` returned valid,
  non-empty level sets for every material of A, B1, C and C-N, including C-N where both operands are UNION-tainted and C where the mask was built with the explicit-bounds `vls.Domain(bounds, bcs, dx)` constructor the old note suspected.
- What IS reproduced: the official complement returns an empty result for thin slabs. S1c (grid 0.10): pad 0.5 grid -> 0 points; 1 grid -> 42 points but an empty surface; 1.5 and 2 grid -> valid slabs, and the never-unioned planes give identical counts to the wrapped stack, so the cause is slab thickness (<= 1 grid), not the UNION.
  The old note's specific configuration (explicit-bounds constructor on the minimal planes) was not re-run, so this is "not reproduced in the tested configurations", not a refutation.
- The project's own pad (B2) survives in `save_locos_volume_mesh` and in the nested official export because they mesh the native wrapped level set directly rather than a Boolean difference.

## 5. Replaced / not replaced
Replaced by official API (evidence above): per-material region separation and stacking for nested level-set stacks (R4/R1), including thin (1 grid) slabs, plus conformal shared interface vertices (index-based shared edges 40/20/60 with 0 duplicate points -- the capability `dedupe_materials` adds to R0).
Not replaced: (a) the floor (`_floored_copy_for_export` is still needed: R1 has no substrate depth); (b) the un-nested oxidation-time LOCOS stack C; (c) getMaterialLevelSet-based classification for slabs <= 1 grid and, at the tested grid, the mask corner area (1.56 x tolerance).
Unverified: other stack topologies `save_locos_volume_mesh` serves (gate stack with several separate metals), non-planar/etched interfaces, other grids, 3D; the DEVSIM import of an R4 mesh (this is geometry only).

## 6. Minimal next change (PROPOSAL only, not applied, needs approval)
Keep `save_locos_volume_mesh` unchanged. Add an explicit, separately named exporter for LOCOS-class stacks (Si / pad oxide / mask) that (1) deep-copies the domain, (2) nests the copy exactly as `_make_locos_domain_chainable` does (union of each un-wrapped level set with the one below), (3) calls `_floored_copy_for_export` and the official `saveVolumeMesh`
with the default epsilon, and (4) runs the existing missing-material check as a hard error instead of a warning. Select it by domain class (LOCOS stack, verified here) rather than as an automatic fallback; do not switch gate-stack or other topologies until they get the same A/B/C-style evidence. A pre-registered rule for epsilon
(keep 0.01, or 0.0) would be needed before any use: this probe only characterised it.

## 7. Production-change evidence
`git diff --name-only 5495b29..HEAD` outside `docs/audits/2026-10-01-e7a-official-material-extraction/` and `remote/` is empty (tcad/, tests/, installed engines untouched). Raw evidence SHA-256 (summary.json / e7a_result.json, first 16 hex):
36761352831 756972176697668d / a881b199a907d69c; 36761746538 d6eb42857b80978c / 50c72dde28e4504a; 36762248912 713e2897d9afb66a / a7de4a57c1e9dc75; 36762442241 95e85faac678b135 / b208970e2df8c8fa.
