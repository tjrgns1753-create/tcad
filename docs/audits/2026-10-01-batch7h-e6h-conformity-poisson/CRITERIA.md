# Batch 7H-E6H criteria: conformity of the structured-builder output, Poisson on builder transition meshes, resource contract (fixed before implementation)

**Base.** HEAD `25c255c59dc2ace162df15517a6e41a9f0fe68e1`, branch `claude/remote-runner`, tracked dirty 0, no evaluation process running.
Serena project tcad (session 14064f89): `structured_lateral_refine` has one production caller
(`refine_process_result_for_implant_windows`, `mesh_import.py`), plus the E6G unit test and the E6G audit script. The E6G
`test_mesh_gate_manufactured_poisson_real.py` never calls it (12-node hand-built mesh); it is kept as an importer/equation control only.

## Pre-criteria investigation (`scripts/op_analysis.py`, `op_analysis.log`; pure numpy, no DEVSIM)
Voronoi finite-volume operator (cotangent edge weights = EdgeCouple / EdgeLength, Voronoi node areas = NodeVolume for non-obtuse
triangles) assembled on real `structured_lateral_refine` outputs. Findings that fix the acceptance form:
- uniform mesh: the quadratic psi = rho x (L - x) / 2 eps is reproduced to 3.6e-15 (max exact 8).
- on the one-sided (3-triangle) and two-sided (4-triangle) transition meshes the quadratic is NOT reproduced at the nodes: the nodal
  residual of the exact quadratic is 3.1e-2 (7.7 % of the node volume) and the solve differs from it by 0.5 % of max exact. So exact
  quadratic reproduction must not be claimed; a convergence test is required.
- with a fixed 8 x 2 domain and square base cells h x h (h = 8 / n, n = 8, 16, 32, 64) the max nodal error falls with ratio 4.000 per
  halving (second order) in both families.

## A. Conformity checker (exact; `scripts/conformity_e6h.py`)
Coordinates are converted to exact integers on a common power-of-two scale (every float64 is dyadic); no epsilon anywhere.
Checks, each reported separately with counts: triangle index validity; no degenerate triangle (exact orientation != 0); one orientation
for all triangles; no duplicate coordinate; no duplicate triangle; every node used by a triangle; every edge has 1 or 2 owners, and an
edge with 2 owners is traversed in opposite directions; every 1-owner edge lies on the bounding rectangle of the mesh and the 1-owner
edges of each of the four sides chain end to end without overlap from corner to corner; the exact area sum equals the exact
rectangle area; hanging nodes (T-junctions): for every edge, no node lies strictly inside it. The hanging test is general: nodes are
indexed by exact x line (sorted y per line), and an edge is tested against the nodes on every x line strictly inside its x extent
(vertical edges: nodes on its own line strictly between its y ends), so it needs no template assumption and no O(nodes x edges) scan.
False-green tests (unit): conforming small mesh -> PASS; deliberate T-junction (coarse edge against two fine edges) -> FAIL; interior
missing triangle (unmatched edges) -> FAIL; duplicate triangle, three owners of one edge, flipped triangle, coincident nodes -> FAIL.
On small builder outputs (cases A-D of E6G) the result must agree with the E6G brute-force `exact()` hanging count.
Then the same checker is applied to the committed `B_refined.vtu` and `F_refined.vtu` (E6G run 36737500532). A failure is reported as a
failure; the checker is not changed after seeing the F result.

## B. Poisson on builder transition meshes (real DEVSIM, remote only)
Public DEVSIM API, equation -eps psi'' = rho as in the E6G control (edge flux eps (psi@n0 - psi@n1) EdgeInverseLength, node model -rho,
integrated with NodeVolume; Dirichlet 0 at Si_xmin and Si_xmax; top/bottom natural). Units: domain 2 um x 0.5 um, length scale
1e-4 cm/um, L = 2e-4 cm, eps = 1, rho = 8 eps / L^2 (max exact 1 V, exact psi = rho x (L - x) / (2 eps)). Base grid n = 8, 16, 32, 64
columns (h = 2/n um, exact in binary), n/4 rows (square base cells), single material Si (Material tag of Si), float64.
Meshes are made by `structured_lateral_refine` only:
- one-sided family: center 1.0 um, rings [h, h/2] (left- and right-finer 3-triangle templates at depths 0->1 and 1->2);
- two-sided family: centers 2h and 5h, ring [h] (a 4-triangle coarse strip [3h, 4h] between two fine bands, plus 3-triangle strips);
- uniform control: the n = 8 base grid (no refinement).
Presence checks on the OUTPUT (so a fall-back to a uniform mesh cannot pass): the one-sided family has exactly 12 "apex" triangles
(one axis-aligned edge, two diagonal edges; one per 3-triangle sub-cell) for every n; the two-sided family has exactly 4 apex
triangles, exactly n triangles with all vertices in x in [3h, 4h] (4 per coarse cell, not 2), and the interior edge
(3h, h/2)-(4h, h/2) present.
Acceptance, fixed now:
1. `check_conformity` passes on every mesh; the importer's area gate passes (`area_conservation[Si].pass`).
2. Independent check of the DEVSIM equation implementation: DEVSIM psi equals the numpy Voronoi solve of the same mesh with
   max |psi_dev - psi_np| <= 1e-9 x max exact. A failure is reported as an operator discrepancy, never absorbed.
3. Analytic: relative max nodal error e_n = max |psi - exact| / max exact, with the node of the maximum error recorded. For each family
   e_n strictly decreases with n and the observed order log2(e_n / e_2n) >= 1.5 for every consecutive pair (numpy predicts 2.0).
   No claim of exact quadratic reproduction on transition meshes.
4. Uniform control: max relative error <= 1e-9 (exact quadratic reproduction on a uniform mesh).
5. Linear precision (rho = 0, psi = 0 at Si_xmin and V at Si_xmax, exact psi = V x / L): on every transition mesh
   max relative error <= 1e-9.
6. Each solve counted (>= 1 for every case); no leaked devices.
These are numerical-equation controls on small meshes, not PN / DD / current validation.

## C. Resource / input contract of `structured_lateral_refine` (local, pure)
Reproduce first, then make the minimum fix. Suspected from reading: the centre/half-width lists are not validated (NaN comparisons
silently give identity; a non-positive half-width is silently ignored), `_strip_depths` has no budget (the tree can go as deep as the
number of rings, and a strip at depth d already needs 2^(d+1) triangles), `ysub` builds a 2^d list before the triangle cap is compared,
and a midpoint that cannot create a new float64 coordinate is not detected. Local tests: non-finite centre or half-width, empty lists,
non-positive half-width; a very large number of rings; midpoint exhaustion (interval one ulp wide); a request far over the cap; a valid
request just under the cap runs to completion. Required behaviour: every invalid or over-budget input raises
`StructuredRemeshAborted` with a reason (`INVALID_REQUEST`, `RESOURCE_CAP`, `SUBDIVISION_EXHAUSTED`) before the offending allocation;
identity is returned only for a valid request none of whose bands requires refinement. The cap (400,000) and the default B/F results
are unchanged (E6G B: 1630 triangles, F: 196,000; both must be reproduced exactly by the modified code).
Stated limits (nothing more is claimed): leaves are bounded by cap / 2 and their depth by log2(cap) during the tree build; the y
sub-division lists are bounded by the planned triangle count (checked first); the node count is not capped separately, it equals
the planned count (asserted after the build) and is below triangles + 2 for a triangulated rectangle.

## D. Fallback distinction (mock)
`StructuredRemeshUnsupported` keeps the existing graded path and now logs the reason; `StructuredRemeshAborted` propagates. A mock test
drives `refine_process_result_for_implant_windows` for both.

## Out of scope
Full regression, E6F/E6G reruns, B/F-scale Poisson, PN/DD/IV sweeps, algorithm redesign, tolerance changes after results.
