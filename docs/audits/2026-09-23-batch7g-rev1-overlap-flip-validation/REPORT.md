# Batch 7G Rev.1 -- overlap checker and Candidate A validation-defect fix, pass-by-pass root cause tracing

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged,
nothing committed). Investigation-only -- zero `tcad/` or `tests/` changes, zero existing audit files
modified (186/186 pre-existing Batch 7D/7F/7G-Phase-1 files confirmed byte-identical before and after this
session's own work).

**Headline finding**: Batch 7G Phase 1's Candidate A had a real P0 defect (a dead `id()`-vs-int comparison
that never actually excluded a legitimately-adjacent, shared-vertex/shared-edge neighbor triangle from the
overlap check). On the real L3 mesh, every one of the 68 blocked flips traced to this defect combined with
a coordinate-scale-blind absolute area threshold (`1e-20`) catching float32 clipping noise (~1e-8 um^2,
right at the coordinate's own float32 ULP) at legitimate shared-vertex/edge touches -- not real overlap.
A corrected, two-independent-method (clip + separating-axis) checker with a properly derived tolerance,
plus a corrected Candidate A built on it, flips **68/68** real L3 Delaunay violations successfully (100%,
vs Phase 1's 0/68), preserving every geometry/material/contact invariant exactly, and **reduces the real
NodeVolume-vs-barycentric-area relative error from 18.6% to 4.97%** -- a genuine causal intervention result,
not merely a correlation. Non-Delaunay interior edges are promoted to `CONFIRMED_PRIMARY_CAUSE` (partial: a
~5% residual excess remains unexplained). Overlap is downgraded to `UNRESOLVED / CHECKER_METHOD_A_LIMITATION`
-- the corrected checker confirms **zero** real overlap pairs at every traced pass, but a large,
non-decisive `unknown` (method-disagreement) bucket remains, traced to a real numerical degeneracy in the
Sutherland-Hodgman clipping method at exact shared-vertex configurations (not a new bug introduced this
session -- inherited from reusing the same clip algorithm, caught by this session's own required
cross-validation design rather than swept under the rug). The `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`
gate is unchanged.

* `scripts/phase_a_reproduce_p0_bug.py` -- A1/A2/A5/A8/A9 synthetic reproduction of the OLD, unmodified
  `_would_overlap_any_other()` (imported from Phase 1, never edited) -- 0/5 wrong on clean synthetic
  coordinates (see chat report section 3 for why, proven not assumed).
* `scripts/phase_a_l3_diagnosis.py`, `phase_a_l3_full_scan.py` -- real L3 mesh diagnosis: every one of the
  68 real blocks traced with exact polygon/area numbers; 57/68 are pure float32-clip-noise artifacts,
  11/68 have a larger single-shared-vertex area requiring the corrected checker.
* `scripts/geometry_checks_v2.py` -- corrected checker: index-based topology classification
  (duplicate/shared_edge/shared_vertex/disjoint), derived tolerance, two independent overlap methods
  (Sutherland-Hodgman clip + separating-axis theorem), UNKNOWN-on-disagreement, extended hole check.
* `scripts/candidate_a_edge_flip_v2.py` -- corrected Candidate A: convexity + opposite-side + new-diagonal-
  inside checks, old/new-pair-union area preservation, before/after LOCAL overlap comparison (never a
  blanket "any nearby pre-existing overlap blocks the flip"), no unproven monotonicity termination rule.
* `scripts/test_phase_ab_synthetic.py` -- A1-A12, 12/12 passed.
* `scripts/test_candidate_a_v2_synthetic.py` -- kite/boundary/material/nonconvex fixtures, 4/4 passed.
* `scripts/phase_d_trace_refinement.py`, `phase_d_investigate_unknowns.py` -- pass-by-pass tracing using
  the REAL production `_refine_once()` directly (not a reimplementation).
* `scripts/phase_e_l3_spike.py` -- the decisive real-L3 corrected-Candidate-A run.
* `data/phase_d_trace.json`, `data/phase_e_l3_spike.json`, `data/pre_existing_hashes_7g_rev1_START.txt`.

See the full 19-section report in chat for tolerance derivation, the two-method agreement table, the
pass-by-pass topology table, the before/after cause-judgment table, and the disclosed residual limitations.
