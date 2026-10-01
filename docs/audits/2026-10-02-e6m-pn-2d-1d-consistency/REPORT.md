# E6M REPORT: limited 2D-1D consistency of the E6K p-n problem (audit path) + E6L corrections

PLAN `PLAN.md` sha256 `5aeb9dc28bf79f82...` (commit 7f4ebbe, alone, before any solve). Remote run 36904995835, executed SHA `70af9ad3589dee155976ffceb89b82e5d14c7186`, DEVSIM 2.11.0, ViennaPS 4.6.2, numpy 2.4.6, meshio 5.3.5; 3 of 3 steps rc 0; **42** `devsim.solve` calls (6 devices: 8 forward / 6 reverse per mesh), 0 leaked devices, no failed device.
RC = 0 and convergence are not physics verdicts. No combined PASS and no `PN_PHYSICS_VALIDATED`.

## What this result is and is not
Is: for ONE explicit single-Si rectangle (40 um x 0.1 um, full-height ohmic side contacts, no equation on top/bottom), with the E6K doping, constants, bias sequence and solver settings, the 2D calculation on a y-extruded copy of each E6K mesh reproduces the preserved 1D result.
Is not: approval of other 2D PN structures, process sequences, a fabricated device, oxidation / diffusion / activation models, the production GUI PN measurement, or PN physics. Two discretisations of the same model agreeing does not prove either is physically right.
Strength of the test (stated plainly): each cell is split into two right triangles, so the diagonal edges carry no flux and the 2D finite-volume system on a y-invariant state reduces to the 1D one. The observed agreement at round-off level is therefore expected for this construction;
it checks the 2D assembly, importer, contacts, boundaries and unit normalisation on an axis-aligned mesh, and says nothing about non-aligned triangles, y-dependent solutions, or the 7D-Rev.2 non-convergence that motivated the 2D gate.

## Verdicts (remote; reproduced by an independent local re-judge of the downloaded JSON + NPZ, `rejudge_local.json`)
| category | verdict |
|---|---|
| EVIDENCE_INTEGRITY | PASS |
| G1 GEOMETRY_AND_IMPORT | PASS |
| G2 PRODUCTION_GATE_HELD_AND_AUDIT_DOPING | PASS |
| G3 UNIT | PASS |
| G4 CONVERGENCE_AND_CONSERVATION | PASS |
| G5 Y_INVARIANCE | PASS |
| G6 CURRENT_2D_VS_1D | PASS |
| G7 PROFILE_2D_VS_1D | PASS |
| G8 JUNCTION_FIELD_2D_VS_1D | PASS |
| G9 MESH_SENSITIVITY_2D | PASS |
All limits are the PLAN's pre-fixed engineering criteria (several reused from E6K), not physical laws. E6K's D FAIL (depletion approximation, 3 %) is unchanged and was not re-judged.

## Geometry, import, gate
| mesh | nodes / triangles / x lines | junction edges (left / right) | area rel. err | importer area gate (A, S, uncertainty) | max |x_2D - x_1D| | contacts |
|---|---|---|---|---|---|---|
| L0 | 1035 / 1376 / 345 | 3.780723 / 4.000 nm | 0 | pass, 4e-08 / 4.000000000000001e-08 cm^2, 8.3e-14 | 2.2e-19 cm | each 3 nodes, x = -+0.002 cm, y in [-1e-05, 0] |
| L1 | 2055 / 2736 / 685 | 1.863507 / 2.000 nm | 0 | pass, 4.9e-14 | 4.3e-19 cm | same |
| L2 | 4113 / 5480 / 1371 | 0.904095 / 1.000 nm | 0 | pass, 4.0e-14 | 2.2e-19 cm | same |
No obtuse or degenerate triangle; exact conformity check passed (0 hanging nodes); region list [Si]; node grid complete with 3 y lines. The x lines are the stored 1D coordinates (differences at the 1e-19 cm level come from the um <-> cm round trip; no interpolation was needed).
Production gate: the real `apply_doping` on every 2D device raised `UnsupportedDopingState` (resolution UNSUPPORTED_BY_MODEL, reason `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`), 0 doping writes, 0 solves. The audit then wrote the step-convention doping directly;
the canonical `net_doping_at` query resolved at all 1035 / 2055 / 4113 nodes with 0 mismatches.

## Units
2D sweep metadata: `current_unit = "A/cm"`, `per_out_of_plane_depth`, dimension 2 (all six devices). `J_2D = I_2D / H_CM`, `H_CM = 0.1 um x 1e-4 = 1e-5 cm` (`e6m_metrics.py`). 1D reference: E6K raw current; production declares no unit for 1D results (None);
the comparison rests on the E6K resistor control, recomputed from its raw currents by the E6L strict judge (ratio 1.0000000000010).

## Currents: I(Si_xmin)/H vs E6K I(l), same level (A/cm^2 numerically)
| V | L0 2D / 1D | rel | L1 2D / 1D | rel | L2 2D / 1D | rel |
|---|---|---|---|---|---|---|
| +0.1 | 4.064487e-07 / 4.064487e-07 | 0 | 4.034466e-07 | 1.8e-14 | 4.030055e-07 | 1.3e-16 |
| +0.2 | 3.377759e-06 | 0 | 3.355022e-06 | 1.7e-14 | 3.351618e-06 | 1.3e-16 |
| +0.3 | 2.704234e-05 | 1.3e-16 | 2.691786e-05 | 1.8e-14 | 2.689618e-05 | 1.3e-16 |
| +0.4 | 2.527576e-04 | 0 | 2.521085e-04 | 1.7e-14 | 2.519784e-04 | 2.2e-16 |
| +0.5 (judged, 1 %) | 3.899362e-03 | 3.0e-10 | 3.895850e-03 | 1.8e-14 | 3.895090e-03 | 3.2e-10 |
| +0.6 (judged, 1 %) | 1.182396e-01 | 1.2e-16 | 1.182121e-01 | 1.8e-14 | 1.182059e-01 | 0 |
| -0.25 | -1.929053e-07 | 1.4e-16 | -1.928129e-07 | 1.8e-14 | -1.927845e-07 | 0 |
| -0.5 (judged, 2 %) | -3.387513e-07 | 1.6e-16 | -3.386873e-07 | 1.8e-14 | -3.386731e-07 | 1.6e-16 |
| -0.75 | -4.709335e-07 | 0 | -4.708625e-07 | 1.8e-14 | -4.708341e-07 | 0 |
| -1.0 (judged, 2 %) | -5.927063e-07 | 0 | -5.926779e-07 | 1.8e-14 | -5.926495e-07 | 1.8e-16 |
(2D and 1D values coincide to the printed digits; raw 2D currents are I = J x 1e-5 A/cm, e.g. L2 +0.6 V: I(Si_xmin) = +1.182059e-06, I(Si_xmax) = -1.182059e-06 A/cm.) Signs equal the 1D signs everywhere.
Conservation |I_min + I_max| / |I_min|: worst 7.2e-5 (L2, -0.75 V; limit 1e-3) -- the same level as the preserved 1D evidence. 2D mesh sensitivity: J(0.6 V) L1 vs L2 5.3e-5; J(-1 V) 4.8e-5; junction-edge E_x(-1 V) 4.7e-3 (limits 1 % / 2 % / 2 %).

## y invariance and profiles (biases 0, 0.5, 0.6, -0.5, -1.0 V; all nodes)
Potential spread over the three y nodes <= 2.2e-16 V (limit 1e-5 V); electron / hole spread <= 3.7e-15 (limit 1e-3). Against the 1D node values (same x lines, no interpolation): max |psi_2D - psi_1D| <= 2.2e-16 V (limit 0.01 V_t = 2.59e-4 V); carriers <= 1.6e-14 relative (limit 1 %).
Field on VERTICAL edges <= 4.4e-11 V/cm at 0 and -1 V. Diagonal edges show up to 8.8e3 (L0) / 2.2e3 (L2) V/cm at 0 V: that is the projection of the x field on the diagonal direction (same potential difference over a longer edge), not a y variation.

## Junction field (same quantity vs same quantity: x component on the HORIZONTAL edges adjacent to x = 0, three y lines each)
| mesh, bias | left edge 2D (3 values) | 1D | right edge 2D | 1D | max rel |
|---|---|---|---|---|---|
| L0, 0 V | -109766.773692 | -109766.773692 | -109766.773662 | -109766.773662 | 2.7e-16 |
| L1, 0 V | -111343.173829 | -111343.173829 | -111343.173819 | -111343.173819 | 2.6e-16 |
| L2, 0 V | -112136.355833 | -112136.355833 | -112136.355830 | -112136.355830 | 1.3e-16 |
| L0 / L1 / L2, -1 V | -167251.587223 / -168831.795988 / -169625.939213 | same | same to 3e-15 | | 3.4e-15 |
Different references, reported as diagnostics only (0 V, not judged; PB is not used at reverse bias): depletion-approximation centre 116584.6063 V/cm; PB centre 112910.1264; PB mean over the left junction edge 109831.2052 / 111392.5351 / 112173.8554 (L0 / L1 / L2).
The 2D values inherit the 1D relation to these references exactly, so E6M adds no new information about the depletion / PB differences (E6L and its CORRECTION_1 stand).

## Audit path vs production path
See PLAN section 4 (table). In short: mesh import, contact creation, area / NodeVolume gate, equation setup, contact BCs, SRH, tolerances and the sweep are the production functions; only the doping write bypasses nothing in production code -- production refused, and the audit wrote the same step-convention numbers itself.
No production file, gate, physical parameter, installed engine, NodeVolume / EdgeCouple was changed.

## E6L corrections made in this batch (no solve)
`docs/audits/2026-10-01-e6l-judge-integrity-equilibrium/CORRECTION_1.md`, pinned by `tests/unit/test_e6l_correction_mock.py`:
(A) the E6K W_E is the mid-point trapezoid (0.8348742913514126 / 0.8345993964579969 / 0.8345293145189819 V at L0 / L1 / L2), the E6L bookkeeping is the edge sum (0.834504509847162 V at every level); they differ by 4.4e-4 / 1.1e-4 / 3.0e-5 relative, shrinking ~4x per level.
The edge sum equals the end-to-end potential drop because the stored field never changes sign (0 positive edges); "W_E = 2 V_bi / E_max exactly" holds only for the edge-sum quantity, and only approximately for the W_E the E6K judge used.
(B) the 37.50 V/cm at L2 is "(PB edge mean) - (DEVSIM edge)": a residual between the continuum PB reference and the discrete result; discretisation and the junction-node representation are suspected, the individual causes are not separated quantitatively.

## Evidence (sha256, first 16 hex)
`data/remote_run_36904995835/remote-run-32/outputs/e6m_out/pn_2d_consistency.json` 1a0e3fc7f9876119; `arrays.npz` 6ec993c6f5201da4 (node coordinates, triangles, element node list, edge end points, EdgeLength, NodeVolume, Donors / Acceptors / NetDoping, Potential / Electrons / Holes / ElectricField at the planned biases);
`summary.json` e9c526cb774e2fd8; `e6m_result.json` ee668130781964ac; solver log `test_pn_2d_1d_consistency_real.log` b7b5a31cea0f4c43 (298 Newton iteration records, 0 convergence failures); judge `scripts/judge_e6m.py` cbc71de841d7f341 (version e6m-judge-1); metrics `scripts/e6m_metrics.py` 8106d40c3cad4469.

## Limits and the next single step
Limits: one axis-aligned tensor-product mesh family that makes the 2D system equivalent to the 1D one; y-invariant solution only; no production-shaped (ViennaPS, unstructured or refined) 2D mesh; no y-dependent structure; one doping, lifetime, mobility model and temperature; the GUI was not exercised; the 2D gate's original concern (non-convergence on production meshes) is not addressed.
Next single step (proposal, not started): the same problem on a 2D mesh that is NOT equivalent to 1D by construction -- e.g. the production importer's own refinement path for this structure (E6G structured transition templates around the junction, which contain non-axis-aligned edges with non-zero couples) --
with the same pre-registered 2D-1D criteria, still as an audit and with the gate unchanged.
