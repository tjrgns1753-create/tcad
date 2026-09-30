# E7A supplement S1 (written AFTER the first run, before the supplement runs; the E7A CRITERIA.md and its verdict mapping are unchanged)

Reason: the first run (remote run 36761352831) raised two questions the pre-registered routes could not answer: (1) `B2_R2` (pad = 1 grid) failed inside the project's single-level-set export of the
material level set returned by `getMaterialLevelSet` -- is the level set empty/invalid, or only that export helper? (2) Is the nested topology (C-N, A, B) already exported correctly by the
official `saveVolumeMesh` on a floored copy, i.e. without `save_locos_volume_mesh`? These routes were added post hoc and are labelled so; they do not alter the verdict mapping of CRITERIA.md section 5.

Routes (same inputs A, B1, B2, C, CN; same judgement items 1-6 and tolerance delta = 0.02 x grid + 1e-6 um):
- **R4** `vio._floored_copy_for_export(domain, 1.0)` then the official `saveVolumeMesh(path)` (default epsilon) -- what `save_volume_mesh` does when no LOCOS hint is registered (the hint is bypassed on purpose).
- **R5** for each material: `ls = getMaterialLevelSet(m)`; record the point count and surface bbox; mesh it (a) with the project's `_export_single_level_set` (exception captured with its message) and (b) with the official raw
  `saveVolumeMesh` of a throwaway single-level-set domain, no floor (exception captured). Slab materials (SiO2, Mask) are compared to the analytic area with the same tolerance; Si is not judged (no floor in (b)).

## S1b (written after the S1 run, before the S1b run)
S1 result: `B2_R5` aborted because the surface mesh of the SiO2 material level set was empty (`nodes.min` on an empty array). S1b repeats B2 R5 with the empty case recorded instead of raising, and adds **R6**: a
thickness scan at grid 0.10 with pad in {0.05, 0.10, 0.15, 0.20} um (0.5 / 1 / 1.5 / 2 grid), recording for `getMaterialLevelSet(SiO2)` the level-set point count and whether its surface mesh is empty. Characterisation only; no pass/fail, no threshold adopted.
