# Batch 7H-B: DEVSIM NodeVolume mechanism on acute/right/obtuse meshes (public API only)

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, nothing staged or committed.
Audit only: no `tcad/` or `tests/` change; all 1951 pre-existing `docs/audits/` files byte-identical.
Phase A (`REPORT_DRAFT.md`, formulas, fixtures, analytic predictions) was hashed at 06:23:42 UTC before the
first DEVSIM import (`data/draft_sha256_before_devsim.txt`); the completeness check re-verifies those hashes.

**Verdict: A. NODEVOLUME_RULE_IDENTIFIED_AND_L3_RESIDUAL_EXPLAINED.** No production change was made. The
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` gate stays in place.

## Identified rule (DEVSIM 2.11.0)

`NodeVolume` equals rule F3 on every fixture and on every L3 node:

    NodeVolume(i) = sum over triangles T at i, over the two edges e of T at i, of 0.25 * L_e * |(L_e / 2) * cot(theta_opp(e))|

That is: `ElementEdgeCouple = |(L/2) cot theta_opp|` (the absolute value of the signed circumcentric couple),
`ElementNodeVolume = 0.25 * ElementEdgeCouple * L`, `EdgeCouple = sum of the element couples of the edge`,
`EdgeNodeVolume = 0.25 * EdgeCouple * EdgeLength`, and `NodeVolume = sum of EdgeNodeVolume at the node`.
For an acute or right triangle this is the exact circumcentric dual (sum = area). For an obtuse triangle the
couple of the edge opposite the obtuse angle is negative in the signed dual; DEVSIM uses its magnitude, so the
triangle's node volumes sum to MORE than its area (T4 104 deg: 1.714x; T5 156.5 deg: 24x).

## Results

| Item | Result |
|---|---|
| Fixtures T1-T9, P1-P7 (+ T4/T5 float32) | import coordinates, node order, connectivity, edge and element-edge endpoint mapping proven for all 18 |
| F3 per node | matches on all 18 fixtures, max relative error 2.4e-16 |
| F1, F2, F4, F4b, F5 | match only fixtures without obtuse triangles; fail every over-counting obtuse fixture |
| F6a/F6c/F6d/F6e (public reconstructions) | match all fixtures; F6b (manual example 0.5*EdgeCouple*EdgeLength) is exactly 2x |
| Mirror/rotation/scale (T6-T9) | sum ratio 1.7142857142857146 in all five T4-family cases |
| L3 before flip | DEVSIM relative excess 0.1855566466 = F3 0.1855566466, all 2921 nodes match, max rel 1.7e-16 |
| L3 after exact-safe flip | DEVSIM 0.0497390209 = F3 0.0497390209, all 2921 nodes match, max rel 2.2e-16 |
| Share of the excess explained by F3 | 100 % before and after |
| Nodes with positive excess (after) | 259, every one incident to an obtuse triangle |

H1 abs contribution: CONFIRMED; H2 right-triangle degeneracy: EXCLUDED; H3 boundary only: EXCLUDED;
H4 interior obtuse: CONFIRMED; H5 obtuse without non-Delaunay edge: CONFIRMED; H6 float32 primary: EXCLUDED
(all by controlled intervention, `data/judgments.json`).

## Tests

`test_formulas.py` 30/30, `check_completeness_7hb.py` PASS, `mutation_tests_7hb.py` 5/5 (endpoint mapping,
cot sign, absolute-vs-signed, boundary/interior classification, tolerance enlargement).

## Limits

* The DEVSIM node-level tolerance is area-derived; two edge-level couple comparisons at exactly-zero couples
  (P4 right-angle element edge: DEVSIM 0 vs formula 3.7e-21; P7 near-right edges at 2e-21) fall outside it.
  Node volumes are unaffected. No tolerance was changed.
* P7 was intended to be all right triangles; float64 `cos(260 deg)` and `cos(100 deg)` differ by 2.8e-17, so one
  triangle is obtuse by a negligible amount. All rules still coincide on P7.
* NodeVolume is only the volume weight. PN field/current and IV convergence are not assessed here.
