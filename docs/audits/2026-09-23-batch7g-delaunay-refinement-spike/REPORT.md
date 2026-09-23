# Batch 7G Phase 1 -- red-green refinement Delaunay/conformity defect proof + audit-only repair spike

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged,
nothing committed). Investigation-only -- zero `tcad/` or `tests/` changes, zero existing audit files
modified (163/163 pre-existing files, including Batch 7D/7F, confirmed byte-identical by hash before and
after this session's own work).

**Headline finding**: local non-Delaunay interior edges are REAL and PRESENT in the ViennaPS-imported,
`refine_mesh_near()`-refined mesh (68/106/257 violations at L3/L4/L5, out of 8600/... interior edges),
essentially absent on the raw unrefined mesh (0 violations) and on a comparable-resolution deterministic
structured control (0 violations at every level, every diagonal orientation, every height). The violation
count and the NodeVolume-vs-triangulated-area excess (18.6%/33.1%/62.2%, matching Batch 7F exactly) track
together almost perfectly: 20/20 of the highest-NodeVolume-excess nodes are incident to a Delaunay-violating
edge. Hanging nodes/T-junctions: **zero found at any level**. Triangle overlaps: real, small-area, growing
with level (25/166/510 pairs). A constrained local edge-flip repair (Candidate A) is CORRECT (verified on
synthetic fixtures, and reduces a known non-Delaunay case to zero violations) but finds **zero safe flips on
the real L3 mesh** -- every one of the 68 candidate flips is blocked by a pre-existing triangle overlap in
its immediate neighborhood, meaning local re-triangulation alone cannot repair this mesh's defects.

* `EVIDENCE_INTEGRITY_NOTICE.md`, `BATCH_7F_JUDGMENT_CORRECTIONS.md` -- required standalone documents (see
  chat report sections 2-3).
* `scripts/geometry_checks.py` -- the pure-numpy Delaunay/circumcenter/cotangent/T-junction/overlap/hole
  checker, validated against 7 synthetic fixtures (`test_geometry_checks_synthetic.py`, 27/27 assertions
  passed) BEFORE any real mesh was analyzed.
* `scripts/probe_delaunay_7g.py`, `case_manifest_7g.py`, `run_matrix_7g.py` -- the real-mesh measurement
  harness (raw ViennaPS / imported L3-L5 / structured L3-L5, public DEVSIM API only for the NodeVolume
  read).
* `scripts/candidate_a_edge_flip.py` -- the constrained local Delaunay edge-flip repair candidate.
* `scripts/check_completeness_7g.py`, `mutation_tests_7g.py` -- verification harness (14/14 mutations
  caught).
* `data/geometry_7g.json` -- raw per-case measurements.

See the full 24-section report in chat for the complete evidence, corrected hypothesis judgments, and the
(negative) production-readiness conclusion -- no candidate in this batch satisfies the full production bar;
the 2D step-junction gate is unchanged and must remain in place.
