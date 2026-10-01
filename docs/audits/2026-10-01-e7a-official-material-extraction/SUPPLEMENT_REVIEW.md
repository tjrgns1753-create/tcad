# E7A review supplement (wording only; no new computation, no new remote run; REPORT.md, CRITERIA.md, S1_CRITERIA.md, JSON, meshes and native logs are unchanged)

Written after the E7A review. It narrows four statements of `REPORT.md`; where this file and REPORT.md differ in strength, this file governs.

A. "Nested inputs are extracted correctly" holds only for the inputs actually run (A, B1, B2, C-N; one grid each, planar, explicit geometry, no positive-time oxidation) and only for the checks actually made:
   material set present, per-material area against the analytic area, boundary y positions at 3 (A, B) or 7 (C, C-N) columns, no overlap/gap larger than delta per scanned column, index-shared edges between touching materials, duplicate coordinates.
   Not shown: other grids, non-planar or etched interfaces, other stack topologies (gate stack), the importer or any DEVSIM behaviour on these meshes, and any oxidation or process physics.
   The approved use is therefore: on those nested stacks, with the floor kept, the official `saveVolumeMesh` replaced part of the own material separation and interface-vertex deduplication.
   `getMaterialLevelSet` is not a general replacement, and the original C topology cannot be passed to the official exporter as is.

B. Shared edges > 0 and zero duplicate coordinates do NOT prove the conformity of the whole mesh. Not verified: global hanging nodes / T-junctions, connectivity of the entire interface (the count of shared edges was not compared with the interface length element by element),
   local overlaps or gaps away from the scanned columns, and the DEVSIM import with its mesh gates. No statement of mesh validity beyond the listed checks is made.

C. "Slab <= 1 grid thick fails" is an observation of the planar thin-layer experiment at one fixed grid (0.10 um; pad 0.05 / 0.10 / 0.15 / 0.20 um) with explicit-plane level sets built by `session.create_domain`. It is not a threshold for all shapes, boundary conditions or dimensions;
   the thickness at which the official complement stops returning a surface may depend on grid alignment of the planes (the planes sat exactly on grid values), the level-set construction and the boundary conditions, none of which was varied.

D. The earlier Boolean-failure evidence (`docs/investigation_log.md` 719-735) is preserved as recorded. The E7A runs contain successful counter-examples (wrapped and nested stacks whose official `RELATIVE_COMPLEMENT` returned non-empty level sets, including a UNION-tainted operand on both sides in C-N),
   so the cause of the old failure can NOT be stated as a universal failure of Boolean operations on operands with a UNION history, and that sentence must not be used as a general rule. The old minimal fixture (explicit-bounds `vls.Domain(bounds, bcs, dx)` constructor on the minimal planes) was not reproduced
   in E7A; that limitation stands, so the old failure is neither confirmed nor refuted for its exact configuration.

Frozen for the following batches: no production exporter, no change of `save_locos_volume_mesh` or its callers, no automatic nesting of process domains, no `wrappingLayerEpsilon` choice, no positive-time oxidation change, no further LOCOS extraction/import experiment, no fallback.
Backlog item only: a later caller-driven migration in this order -- pick a concrete caller, convert a domain COPY to the nested representation, use the official exporter, validate with the existing DEVSIM import and mesh gates, migrate only the callers that pass.
A new function without a caller would not be "code simplification".
