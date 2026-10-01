# E6L REPORT: strict re-judge of the E6K evidence and separation of the equilibrium electric-field difference

Local re-analysis only: 0 new solves, 0 DEVSIM/ViennaPS imports (checked: no `devsim`/`viennaps`/`viennals` module after importing the E6L scripts), 0 production / gate / parameter / engine changes, no remote run.
E6K originals (PLAN, judge, REPORT, JSON, NPZ, logs) are untouched (sha256 unchanged: `pn_1d_diagnostic.json` 97e7e4845796b289, `states.npz` 65c1a938a6521a14, `summary.json` b896595d3c984546, `PN_PLAN_v2.md` c126a0e6e939d828, `judge_e6k.py` efaf2177bef9d78d, E6K `REPORT.md` 6afcc7c97bd1b35c).
The E6K D FAIL stands; nothing below changes an E6K tolerance or turns an E6K result into a PASS.

## 1. Original judge defects (reproduced, `repro_old_judge.json`)
All four reproduce with the committed evidence and `judge_e6k.py`: (A) minority reduced from 3 to 1 point -> F still PASS; (B) `L0_fwd` deleted -> B still PASS; (C) numeric strings in `J` and `Emax` -> accepted (float('...') parses them), verdicts unchanged;
(D) `control_ratio = NaN` with `established_by_control = True` -> C..F still evaluated. Causes: `zip` silently truncates, B iterates over whatever devices exist, `float()` accepts strings, the unit gate trusts the stored flag.

## 2. Strict judge (`scripts/judge_e6l.py`) and its tests (`tests/unit/test_pn_judge_integrity_mock.py`)
Evidence contract checked before any comparison: required devices `control, L0_fwd, L0_rev, L1_fwd, L1_rev, L2_fwd, L2_rev` (raw records and metrics copies), the planned voltages, levels L0..L2, J biases 0.3/0.5/0.6/-0.5/-1.0, E biases 0/-1, minority positions exactly [3, 5, 8] um with 3 + 3 values;
numbers must be finite int/float (no bool, str incl. numeric strings, None, NaN, inf); counts non-negative int (no bool); duplicated values must agree (device record vs metrics vs result table; E_max / W_E / minority recomputed from `states.npz` with the node/edge correspondence checked;
the reference record recomputed field by field from `reference_parameters`, which must equal the device parameters); the unit control is recomputed from the raw contact currents and sigma V / L, and the stored ratio, currents and flag must agree with it.
Any violation -> `EVIDENCE_INTEGRITY_FAIL` for every category; a consistent but failed unit control -> C..F `BLOCKED_UNIT_NOT_ESTABLISHED`. Physics tolerances imported unchanged from E6K. No overall PASS.
Tests (all pass): each device deleted (raw and metrics copy), each level and bias deleted, a raw current point / planned voltage deleted, each minority array shortened / extended, a position moved / added, 8 bad values (`"1.0"`, `"0.116"`, True, False, None, NaN, +-inf) in 12 numeric fields,
bad counts (True, -1, 8.0, "8"), ratio NaN or altered with the flag True, raw control current altered, a fully consistent tamper with the flag still True (fails), the same with the flag False (C..F BLOCKED, never PASS), wrong contact sign, raw vs metrics vs table mismatches, a bool replaced by 1,
E_max or minority values replaced by the reference values, missing NPZ; finally a generic test deletes each of 279 leaves (all of `metrics`, the judged device fields, the result table, the reference parameters) and requires that NONE keeps the original verdicts.
That generic test first exposed one more gap of my own new judge (only `J_model` of the stored reference record was checked) and three informational unit copies; all are now checked and the tolerated set is empty.
Re-judge of the untouched evidence (`rejudge_e6k.json`): EVIDENCE_INTEGRITY PASS; A PASS, B PASS, C PASS, **D FAIL**, E PASS, F PASS -- identical to E6K.

## 3. Equilibrium field: derivation and sources
Derived here (not quoted from a paper): equilibrium, Boltzmann carriers n = n_i e^{psi/V_T}, p = n_i e^{-psi/V_T}, Poisson d2psi/dx2 = -(q/eps)(p - n + N_D - N_A), E = -dpsi/dx. On the n side multiply by dpsi/dx and integrate to an infinite neutral region (E -> 0, psi -> psi_n, 2 n_i sinh(psi_n/V_T) = N):
(1/2) E(psi)^2 = (q/eps)[N(psi_n - psi) - 2 n_i V_T (cosh(psi_n/V_T) - cosh(psi/V_T))]; by symmetry (N_A = N_D) psi(0) = 0, so E_PB(0)^2 = (2 q V_T/eps)[N a - 2 n_i (cosh a - 1)], a = asinh(N/(2 n_i)) -- the expression given in the prompt, reproduced (closed form and first integral agree to 1e-14; d(E^2/2)/dpsi checked against the Poisson right-hand side).
Edge reference: x(s) = Int_0^s du / E(u) (Gauss-Legendre, Newton for s(d)); the PB mean field over an edge of length d from the junction is s(d)/d. No stored Potential/carrier array enters the reference.
DEVSIM side (read from `simple_physics.py`, not derived): `IntrinsicElectrons = n_i*exp(Potential/V_t)`, `IntrinsicHoles = n_i^2/IntrinsicElectrons`, `ElectricField = (Potential@n0-Potential@n1)*EdgeInverseLength`, `PotentialEdgeFlux = Permittivity*ElectricField`.
Applicability: equilibrium only; Boltzmann statistics; full ionisation; abrupt symmetric doping; infinite neutral regions in the reference vs E6K's 20 um with the contact potential fixed at the neutral value (stored contact potentials +-0.417252254924 V = +-V_T a): the difference is the neutral-region exponential tail, decay length ~12.6 nm vs 20 um -- argued negligible, NOT computed.
No literature was read in this batch; no paper is claimed as the source of these formulas.

## 4. Same quantity compared with the same quantity (stored equilibrium snapshots `L{k}_rev__2__bias+0.000`)
Node order verified (x strictly increasing), lengths n_edges = n_nodes - 1, and each stored `ElectricField` equals (V_i - V_{i+1})/(x_{i+1} - x_i) of the stored Potential to 1.3e-16 relative (checked element by element, not assumed from the lengths).
| level | max edge (left of x = 0) | length | DEVSIM edge E | PB edge mean | 1st order E_PB(0) - (qN/eps) d/2 | right edge length | PB right-edge mean | psi_DEVSIM(0) |
|---|---|---|---|---|---|---|---|---|
| L0 | [-3.780723273e-7, 0] cm | 3.780723 nm | 109766.7737 | 109831.2052 | 109831.2048 | 4.000 nm | 109652.6320 | -6.19e-4 V |
| L1 | [-1.863507301e-7, 0] | 1.863507 nm | 111343.1738 | 111392.5351 | 111392.5351 | 2.000 nm | 111281.3791 | -3.85e-4 V |
| L2 | [-9.040947809e-8, 0] | 0.904095 nm | 112136.3558 | 112173.8554 | 112173.8554 | 1.000 nm | 112095.7527 | -2.71e-4 V |
Centre values: depletion approximation E_dep(0) = 116584.6063 V/cm; PB E_PB(0) = 112910.1264 V/cm. The first-order estimate equals the PB edge mean to <= 4e-4 V/cm, so the 37.5 V/cm at L2 is not a first-order truncation; it is the difference between the DEVSIM edge value and the PB edge mean.

## 5. Error separation (V/cm; left = the max edge)
| term | L0 | L1 | L2 | mesh-dependent? |
|---|---|---|---|---|
| 1 model: E_dep(0) - E_PB(0) | 3674.48 | 3674.48 | 3674.48 | no (3.15 % of E_dep, 3.25 % of E_PB) |
| 2 measurement: E_PB(0) - PB mean over the max edge | 3078.92 | 1517.59 | 736.27 | yes, ~ (qN/eps) d/2 |
| 3 discretisation: PB edge mean - DEVSIM edge (left / right edge) | +64.43 / -114.14 | +49.36 / -61.79 | +37.50 / -40.60 | yes |
| 3' same, both junction edges together: DEVSIM - PB mean over [-d_L, d_R] | +27.37 | +8.18 | +3.52 | yes, decreasing |
| 4 reference quadrature (n = 32 vs 64) | 4e-11 | 4e-11 | 3e-11 | -- |
| 5 finite domain / contact BC | not computed; argued negligible (Section 3) | | | |
Sum check at L2: 116584.61 - 3674.48 - 736.27 - 37.50 = 112136.36 = the stored E_max.
So the E6K L2 gap to the depletion approximation (-3.82 %) = model (-3.15 %) + edge-averaging measurement (-0.63 %) + discretisation (-0.03 %). E6K's sentence "not a mesh effect" is WITHDRAWN: the change of E_max with refinement (+2.2 % L0 -> L2) is almost entirely term 2, which is mesh-dependent through the edge length, plus the small mesh-dependent term 3;
only term 1 is independent of the mesh. (E6K's Richardson-style extrapolation, 1.129e5, coincides with E_PB(0) = 112910, consistent with this separation.)
Observed, interpretation is a hypothesis: DEVSIM gives both junction edges the same field (109766.773692 / 109766.773662 at L0); the junction node has NetDoping 0 under the step() convention and psi ~ 0, so its control-volume charge is ~0 and the two edge fluxes balance.
The left and right edges differ in length (3.78 vs 4.00 nm at L0), the continuum means differ, so the per-edge residuals have opposite signs; measured against the PB mean over both edges the residual is +27.4 / +8.2 / +3.5 V/cm and shrinks with refinement. The non-zero psi(0) (-6.2e-4 -> -2.7e-4 V) also shrinks; the mesher's asymmetric edge lengths around x = 0 are the likely source (not tested).

## 6. W_E is not independent of E_max
`int |E| dx` over the stored solution telescopes to the end-to-end potential drop, which the contact boundary condition fixes: 0.834504509847 V at every level (= V_bi). Hence W_E = 2 V_bi / E_max and W_E / W_dep = E_dep / E_max exactly (1.062112 / 1.047075 / 1.039668 at L0 / L1 / L2).
E6K's two D items per bias are one quantity, counted once here; the W_E item is reported but not as separate evidence. The strict judge still evaluates it (same E6K tolerance) and labels it as dependent.

## 7. Conclusions (facts vs hypotheses)
Facts: the original judge accepted the four defects; the strict judge blocks them and 279 single deletions, and reproduces A..F on the untouched evidence (D FAIL kept). The DEVSIM equilibrium edge field is the potential difference over the edge (checked);
the gap to the depletion approximation splits into a mesh-independent model term (3674.48 V/cm) and mesh-dependent measurement (736.27 at L2) and discretisation (37.50 at L2) terms; the reference quadrature error is ~1e-11 V/cm; W_E duplicates E_max.
Hypotheses (not tested): the per-edge opposite-sign residuals come from the zero-charge junction node with unequal neighbouring edges; the non-zero psi(0) comes from the mesher's edge asymmetry; the finite 20 um domain is negligible.
Out of scope and not claimed: PN_PHYSICS_VALIDATED, 2D PN, any solver error (the remaining differences are explained without one at the stated precision; that is not a proof of solver correctness).

## Files
`scripts/repro_old_judge.py` -> `repro_old_judge.json`; `scripts/judge_e6l.py` -> `rejudge_e6k.json`; `scripts/pb_equilibrium.py` -> `pb_equilibrium.json`, `pb_equilibrium.log`; tests `tests/unit/test_pn_judge_integrity_mock.py`, `tests/unit/test_pb_equilibrium_mock.py`.
