# Batch 7H-E6H REPORT (supplement to E6G; E6G files and evidence are unchanged)

**Result, limited to the tested algorithm and inputs.** The committed E6G B and F outputs are exactly conforming. Poisson on meshes made by
`structured_lateral_refine` with one-sided (3-triangle) and two-sided (4-triangle) transition templates agrees with DEVSIM's own operator
and converges at second order to the analytic solution. The builder's input / budget contract had real defects (two hangs, silent
identity on invalid requests); they are fixed. This is not PN / DD / current validation; `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`
and the PN/DD gates are unchanged.

## Correction of the E6G evidence scope
`tests/integration/test_mesh_gate_manufactured_poisson_real.py` (E6G) never calls the builder: it builds a 12-node mesh by hand. Its PASS
stands as an importer / equation control only and is NOT an analytic check of a transition mesh. The E6G "F hanging nodes NOT_VERIFIED"
is now resolved below by a new exact check; E6G REPORT.md is not edited.

## Evidence (kinds kept separate)
| kind | result |
|---|---|
| criteria before code | `CRITERIA.md` (6937e76), `CRITERIA_ERRATUM_1.md` (e7e2552, apex counts scale with rows; written before any DEVSIM run) |
| conformity of B / F (exact, local and remote, `conformity_bf.json`, `conformity_bf.log`) | B 876 nodes / 1630 triangles and F 98,365 / 196,000: 0 duplicate coordinates, 0 duplicate triangles, 0 unused nodes, 0 degenerate, one orientation, 0 edges with >2 owners, 0 interior same-direction edges, 0 boundary edges off the rectangle, boundary covered exactly, area equals rectangle exactly, **0 hanging nodes**. F check 1.3 s |
| checker false-green tests | conforming -> PASS; T-junction -> FAIL (1 hanging, equals brute force); missing interior triangle, duplicate triangle (3 owners), flipped triangle, coincident nodes, unused node, degenerate -> FAIL; builder outputs of E6G cases A-D-type agree with the brute-force count |
| discrete operator investigation (`op_analysis.log`) | quadratic NOT reproduced at nodes on transition meshes (residual 7.7 % of node volume); second order in numpy |
| Poisson / linear on builder meshes (remote run 36753837606) | table below |
| builder reproduces E6G | modified code gives arrays identical to committed `B_refined.vtu` (1630 / 876) and `F_refined.vtu` (196,000 / 98,365) (`reproduce_bf.json`) |

### Real DEVSIM controls on builder meshes (`poisson_transition.json`)
Domain 2 um x 0.5 um, eps = 1, rho = 8 eps / L^2, max exact 1 V; each case: 1 Poisson solve + 1 linear solve, area gate passed, conformity
passed, transition presence verified on the output (apex triangles = 1.5 n one-sided / n/2 two-sided; two-sided coarse strip has n triangles
and the midline edge).
| mesh | triangles | Poisson max rel. error (node, um) | DEVSIM vs numpy Voronoi solve | linear precision error |
|---|---|---|---|---|
| uniform 8 | 32 | 1.1e-16 | 1.4e-15 | 2.8e-17 |
| one-sided 8 / 16 / 32 / 64 | 116 / 296 / 848 / 2720 | 4.949e-3 (0.875, 0.0625) / 1.237e-3 / 3.093e-4 / 7.734e-5 | <= 4.1e-14 | <= 1.1e-16 |
| two-sided 8 / 16 / 32 / 64 | 88 / 240 / 736 / 2496 | 4.173e-3 (0.25, 0.125) / 1.043e-3 / 2.608e-4 / 6.520e-5 | <= 1.8e-14 | <= 1.1e-16 |
Observed orders: one-sided 2.0000, 2.0000, 2.0000; two-sided 2.0000, 2.0000, 2.0000 (criterion >= 1.5). Acceptance `pass` true, 0 failures.
Interpretation: the quadratic is exact only on the uniform mesh; on transition meshes it is reproduced to second order, not exactly. The
DEVSIM solution equals the independent Voronoi (cotangent / Voronoi-area) solve to 1e-14, so EdgeCouple / NodeVolume on these meshes follow that
convention. Linear precision is exact to rounding. The max error sits at the transition zone in the one-sided family.

## Resource / input contract (`resource_before.json` -> `resource_after.json`, local)
Reproduced before any fix: NaN / inf centre, NaN / zero / negative / inf half width, empty lists all returned a silent identity (or an
inf-band mesh); 60 or 200 rings HUNG (> 60 s, sub-row lists of 2^d); a one-ulp-wide interval returned a mesh of zero-width leaves. After
the fix: invalid requests -> `StructuredRemeshAborted("INVALID_REQUEST")`; rings_60 / rings_200 -> `RESOURCE_CAP` in 0.1 s; one-ulp interval ->
`SUBDIVISION_EXHAUSTED`; 100 x 100 grid with 8 rings (19.6 M planned triangles) -> `RESOURCE_CAP` before any sub-row list / aspect loop (peak 7 MB);
valid request with 377,400 triangles (under the cap) completes (18.3 s, peak 91 MB). Identity is returned only for a valid request whose
bands need no refinement. Stated limits: leaves <= cap/2 and depth <= log2(cap) are enforced during the tree build; sub-row lists are bounded
by the planned triangle count, checked first; the node count is not capped separately (asserted equal to the plan after the build);
the 2:1 balancing is a restart-from-start scan (quadratic in leaves in the worst case, bounded by the cap; 377k-triangle case took 18 s).
Because the cap is now checked before the aspect loop, an input violating both reports `RESOURCE_CAP` rather than `TRANSITION_ASPECT`.
Cap unchanged (400,000); B and F results unchanged.

## Fallback distinction (`test_mesh_implant_refine_fallback_mock.py`)
Supported -> structured mesh equal to a direct builder call, no log; `StructuredRemeshUnsupported` (missing triangle) -> graded path, reason
logged (`NOT_TWO_TRIANGLES_PER_CELL`), output written; `StructuredRemeshAborted` (`TRANSITION_ASPECT`) -> propagates, nothing written, no
graded substitute. No doping value, activation state, geometry or DEVSIM internals were touched.

## Changes
Production (`e6h_production.patch`, 170 lines, sha256 `348b9d6201e3917b...`): `mesh_refine.py` (`_validated_request`, budget and exhaustion checks in
`_strip_depths`, reordered cap check and exhausted-midpoint check in `structured_lateral_refine`), `mesh_import.py` (logger, fallback
reason logged). New tests: `tests/unit/test_mesh_conformity_check_mock.py`, `tests/unit/test_mesh_implant_refine_fallback_mock.py`,
`tests/integration/test_mesh_gate_poisson_transition_real.py`; extended `tests/unit/test_mesh_structured_remesh_mock.py` (case C). Remote profile
`e6h_conformity_poisson`, request `e6h-conformity-poisson-001`. Run 36753837606, executed SHA `5e4ff64c2c90fd1f4bb777587ac6c38f09e8aaf1`, DEVSIM 2.11.0,
ViennaPS 4.6.2, numpy 2.4.6, meshio 5.3.5; 6 of 6 steps rc 0. (The driver still names its result file `e6g_result.json`: copied template name.)

## Not verified
Local control-volume accuracy, current and PN / DD behaviour on the B / F meshes; the Poisson controls are small meshes (<= 2720 triangles), not F
scale; the other refinement callers still use red-green; raw ViennaPS slivers; hanging-node / conformity of inputs other than the committed B / F outputs.
