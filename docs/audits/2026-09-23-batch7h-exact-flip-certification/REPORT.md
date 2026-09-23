# Batch 7H-A: exact overlap/flip certification and same-run NodeVolume causality

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged, nothing staged or
committed). Audit only: no `tcad/` or `tests/` change, no existing audit file changed (203/203 Batch
7D/7F/7G/7G-Rev.1 files byte-identical at the end).

**Batch verdict: A. EXACT_GEOMETRY_CERTIFIED_BUT_NODEVOLUME_RESIDUAL_REMAINS.** This is not a production-ready
result. The `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` gate stays in place.

## Results (real L3: 2921 float32 points, 5760 triangles, single material tag 10)

| Item | Result |
|---|---|
| Exact positive-area overlap, before flip | 0 of 51710 closed-bbox pairs (35165 touch, 16545 disjoint, 0 duplicate/invalid) |
| Exact positive-area overlap, Rev.1 after mesh | 0 of 50011 pairs |
| Exact positive-area overlap, exact-safe after mesh | 0 of 50011 pairs |
| Rev.1 UNKNOWN before (545) | 525 touch + 20 disjoint, 0 overlap |
| Rev.1 UNKNOWN after (511) | 493 touch + 18 disjoint, 0 overlap |
| Rev.1 Method A (clip, float32) | 525 / 493 false positives, 0 false negatives |
| Rev.1 SAT | 0 false positives, 0 false negatives |
| Exact-safe flips | 187 over 4 passes, 0 rejects, 0 re-flips, 0 external-overlap increases; exact incircle violations 69 -> 0 |
| Exact invariants | points byte-equal, triangle count, tag Counter, boundary edge set, interface edge set (empty), non-manifold/duplicate/zero/inverted sets, exact total area (8 um^2) all unchanged |
| DEVSIM contacts (public `get_element_node_list`) | Si_xmin / Si_xmax node sets and edge sets identical before and after |
| Same-run NodeVolume | relative error 0.18556 -> 0.04974 (73.2 % reduction), DEVSIM 2.11.0 |
| Residual after flip | +3.98e-9 cm^2; 4.18e-9 in the ring zone, 0.20e-9 on boundary nodes; top residual nodes are interior ring nodes at x = +-0.2 um, each incident to 6-10 obtuse triangles |
| DEVSIM EdgeCouple | 0 negative, 1177 zero, 7503 positive, both before and after |

## Files

* `PRIOR_RESULT_CORRECTIONS.md`: six corrections to Rev.1 claims and tolerance numbers.
* `scripts/exact_geometry.py`: exact integer-scaled orient2d / incircle / pair classification / Fraction
  intersection polygon; standard library only.
* `scripts/exact_flip.py`: exact-safe constrained Lawson flip with oscillation detection.
* `scripts/test_exact_synthetic.py`: A1-A14 (+A10b), 15/15 pass (`data/test_exact_synthetic.log`).
* `scripts/mutation_tests_7h.py`: 7 required mutations plus 2 controls, 9/9 (`data/mutation_tests_7h.log`).
* `scripts/run_7h_l3.py`: Phases B-E in one process (`data/run_7h_l3.log`, `data/phase_*.json`).
* `data/start_hashes_*.txt`: start-of-batch SHA-256 snapshots.

## Scope limits

* Contact preservation is proven for the contacts created by the Batch 7F audit import helper
  (`import_structured_device`, x-min/x-max boundary edges, same public `create_gmsh_mesh` path as production),
  not for contacts derived by production `import_process_result`.
* Material-interface preservation on the real mesh is vacuous (L3 has no interface edges); it is exercised only
  by the synthetic two-material mutation M3.
* No drift-diffusion or IV was run; NodeVolume improvement does not verify PN current or field physics.
