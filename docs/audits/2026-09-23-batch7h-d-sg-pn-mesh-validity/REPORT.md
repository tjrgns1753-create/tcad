# Batch 7H-D: Scharfetter-Gummel PN junction on DEVSIM default vs signed-override geometry

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, nothing staged or committed.
Audit only: `tcad/`, `tests/`, `tcad_2d_stagewise.py` unchanged (194 tracked + 110 dirty files, sha256 re-verified);
all 2031 pre-existing `docs/audits/` files byte-identical, no file added or removed outside this folder.
Pre-registration (`REPORT_DRAFT.md`, `data/prereg_sha256.txt`, 09:06:34 UTC) re-verified: 7/8 files OK; `sg_lib.py`
differs only by the disclosed DEVIATIONS item 1 line (reverting that line reproduces the registered sha256
`80230ff5...`, `data/sg_lib_deviation_proof.txt`). Gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` unchanged.

**Verdicts: A `NONOBTUSE_DEFAULT_SG_DD_VALIDATED` (scope below), C
`SIGNED_OVERRIDE_BREAKS_MONOTONICITY_WITH_NEGATIVE_TRANSMISSIBILITY`, D `DEFAULT_OBTUSE_GEOMETRY_CAUSES_PN_ERROR`,
F `PUBLIC_OVERRIDE_NOT_STABLE_FOR_PRODUCTION`.** B not selected (M3 D1 fails the registered potential criterion).
E not selected (1D reference converges; residual uncertainty quantified). No production integration approved.
**Production direction: option 1 (DEVSIM default assembly + non-obtuse mesh requirement, everything else fail-closed).**

## 1. Sources (what each actually guarantees)
* Scharfetter & Gummel, IEEE TED 16(1) 1969: `FULL_TEXT_NOT_OBTAINED` (IEEE closed, no OA copy). Not used as evidence.
* Sanchez & Chen, "Element Edge Based Discretization for TCAD Device Simulation" (TechRxiv v3, CC-BY; PDF sha256
  `0c3b9ccd...333cf`, not redistributed; the IEEE TED 68(11) published version was not read): gives the element-edge
  assembly (eqs 3-12). States its scope excludes time integration and boundary conditions. Sec. II-B.3 requires the
  element circumcenter inside the element (3D; the 2D sentence says "inside the circumcircle", apparently meaning
  the triangle) and notes other FVM simulators may be less strict. Its Ferrocap example: poor TetGen elements gave a
  3D/2D discrepancy until refined. It contains no statement on negative couples, M-matrix or stability, so it does
  not guarantee stability of a signed Cartesian override.
* Farrell et al., WIAS preprint 2263 (2016; sha256 `79147212...6c3`): admissible (boundary-conforming Delaunay)
  partitions give edge-orthogonal Voronoi interfaces; conditions: opposite angles of an interior edge sum <= 180 deg,
  a boundary-edge opposite angle <= 90 deg (Sec. 6.1). SG flux vanishes when quasi-Fermi potentials are equal
  (thermodynamic consistency, eq. 19). Central differences violate the maximum principle / positivity. Full-system
  convergence theory is missing; existence results are limited (Gaertner); convergence estimates exist on Delaunay
  grids.
* DEVSIM 2.11.0 manual (`data/manual/`, fetched 09:01:28 UTC): EdgeCouple = "length of the perpendicular bisector";
  bulk and contact equations take edge/node models; `contact_equation(edge_current_model=...)` defines contact
  current. The seven geometry parameters (`node_volume_model`, `edge_couple_model`, ...) are documented only in
  Sec. 5.6 "Cylindrical coordinate systems". No statement on obtuse elements, negative couples or stability.
* Observed here only (not claimed by any source): default EdgeCouple = |signed| (7H-B F3) gives a monotone but
  inconsistent scheme on obtuse meshes; the signed override reproduces it where couples are >= 0 and breaks sign
  structure where they are < 0.

## 2. Production SG path (public helpers captured, `data/production_sg_path.json`, DEVSIM 2.11.0)
| item | location | expression / behaviour |
|---|---|---|
| Poisson setup | `tcad/device/devsim/semiconductor_equation.py:50` `setup_semiconductor_potential_equation` | SetSiliconParameters -> CreateSiliconPotentialOnly -> CreateSiliconPotentialOnlyContact per contact |
| DD setup | same file `:83` `setup_drift_diffusion_equation` | CreateSolution Electrons/Holes, init from IntrinsicElectrons/Holes (`:131-132`), CreateSiliconDriftDiffusion, ...AtContact |
| parameters | simple_physics.py:122 | n_i 1e10 cm^-3, V_t 0.025887193 V, eps 9.8235e-13 F/cm, mu_n 400, mu_p 200 cm^2/Vs; taun=taup=1e-8 s (production override of 1e-5) |
| potential | simple_physics.py:144 | ElectricField=(Potential@n0-Potential@n1)*EdgeInverseLength; PotentialEdgeFlux=Permittivity*ElectricField; IntrinsicElectrons=n_i*exp(Potential/V_t); variable_update log_damp |
| DD charge | simple_physics.py:306 CreatePE | PotentialNodeCharge=-ElectronCharge*kahan3(Holes,-Electrons,NetDoping) |
| Bernoulli | simple_dd.py:13-27 | vdiff=(Potential@n0-Potential@n1)/V_t; Bern01=B(vdiff) |
| SG currents | simple_dd.py:48, :69 | Jn=q*mu_n*EdgeInverseLength*V_t*kahan3(n1*Bern01, n1*vdiff, -n0*Bern01); Jp=-q*mu_p*EdgeInverseLength*V_t*kahan3(p1*Bern01,-p0*Bern01,-p0*vdiff) |
| SRH | simple_physics.py:256 | USRH=(np-n_i^2)/(taup(n+n1)+taun(p+p1)) |
| contacts | simple_physics.py:189, :332 | Dirichlet node models; contact current = edge_current_model ElectronCurrent/HoleCurrent |
| NetDoping | caller-provided node model (here: node_model + set_node_values) | |
| PN IV entry | `tcad/characterization/pn_junction_iv_sweep.py:41` (`:88`, `:92`), robust `robust_iv_sweep.py:229` (`:150`, `:271`) | callers: `tcad_2d_stagewise.py:5870,5895`, `tcad/cli/run_pipeline.py:336`, tests (rg list in chat report) |
C1's `run_basic_potential_solve` is not on this path.

## 3. Fixed physics and analytic reference (registered before the first solve)
Abrupt symmetric PN, N_A = N_D = 1e17 cm^-3, fully ionized, junction x = 0 (node at x = 0: NetDoping 0), p side
x < 0; domain x in [-0.5, 0.5] um, H = 0.1 um (L3: x in [-2, 2] um, H = 2 um); T = 300 K; constant mobility; SRH only.
Depletion approximation (sanity only): V_bi 0.83450 V, W 0.14316 um, E_peak 1.1658e5 V/cm, L_D 0.01261 um,
majority 1e17 / minority 1e3 cm^-3. Bias on left (p) contact, steps 0.025 V: forward to +0.10 V, reverse (rebuilt
device) to -0.10 V. Tolerances in `data/fixed_physics.json` (unchanged).

## 4. 1D reference (`data/analysis_synth.json` -> ref1d)
| dx (um) | psi Linf vs finest (V) | E_peak (V/cm) | W (um) | J(-0.10 V) (A/cm^2) | J(+0.05 V) | J(+0.10 V) |
|---|---|---|---|---|---|---|
| 0.02 | 1.457e-3 | 9.701e4 | 0.120 | -1.3819e-7 | 2.6169e-7 | 9.5090e-7 |
| 0.01 | 3.407e-4 | 1.0486e5 | 0.140 | -9.3379e-8 | 1.4532e-7 | 5.2690e-7 |
| 0.005 | 6.884e-5 | 1.0886e5 | 0.130 | -9.5012e-8 | 1.1643e-7 | 4.1383e-7 |
| 0.0025 | 0 | 1.1088e5 | 0.135 | -9.5039e-8 | 1.1462e-7 | 4.0527e-7 |
Potential differences shrink by 4.28x and 4.95x per halving (about second order). Finest-pair current differences:
0.028 % (-0.10 V), 1.57 % (+0.05 V), 2.11 % (+0.10 V); forward ratios 3.75, 13.2 (not yet asymptotic). V_bi numeric
0.834505 V at every level (contact BC). 0 V: currents <= 8.0e-11 A/cm^2, quasi-Fermi <= 8.9e-15 V, mass action
<= 3.4e-13. U_psi = 1.457e-3 V, U_I = 0.454 / 1.283 / 1.346 -> registered 2D tolerances: potential 4.372e-3 V;
current 1.362 / 3.849 / 4.039 relative. **The current tolerance has almost no discriminating power at dx = 0.02 um**
(pre-registration design weakness; disclosed, not changed). The L3 1D reference over [-2, 2] um gives the same U
values (U_psi 1.457e-3 V).

## 5. Meshes (`data/fixtures_7hd.json`, dx = dy = 0.02 um)
| mesh | nodes/tri | acute/right/obtuse | angles (deg) | Delaunay viol. | bnd Gabriel viol. | signed couple neg/zero/pos (min) | signed NV neg (min) | DEVSIM sum NV/area |
|---|---|---|---|---|---|---|---|---|
| M1 | 312/510 | 490/20/0 | 26.57-90.00 | 0 | 0 | 0/0/821 (5.0e-7 cm) | 0 | 1.000000 |
| M2 | 306/500 | 0/500/0 | 45.00-90.00 | 0 | 0 | 0/250/555 (0) | 0 | 1.000000 |
| M3 | 306/500 | 226/220/54 | 21.37-114.44 | 0 | 0 | 0/106/699 (0) | 0 | 1.041676 |
| M4 | 306/500 | 82/6/412 | 1.63-176.63 | 246 | 0 | 246/0/559 (-3.52e-5 cm) | 50 (-2.48e-11 cm^2) | 5.532641 |
| L3_after (7H-C) | 2921 | - | - | - | - | 6 negative, all boundary | 2 (-3.906e-12 cm^2) | - |
M5 not built (M3 has 0 boundary Gabriel violations). Connectivity/coordinate hashes in the fixture file.

## 6. Variants
D0 default; D1 signed couple + signed node volume + edge-node / element-couple / element-node volumes from the same
dual (DEVSIM-held coordinates, negative values kept); D2 couples only; D3 volumes only. Each configuration in its own
subprocess.

## 7. Results (registered runs `data/results_*.json`, analysis `data/analysis_*.{json,txt}`, supplementary
`data/diag_*`)
Newton: every configuration converged at every step except **M4 D1** (Poisson: 50 iterations, RelError oscillating
6.2e-2 ... 1.04, AbsError 2.5e-2 ... 1.4e-1 V; `data/M4_D1_newton_log.txt`). M4 D2 needed 8-10 iterations per DD step
(others 1 at 0 V, 4 per bias step).

Experiment A (equilibrium Poisson; tolerance 4.372e-3 V):
| config | psi Linf vs 1D (V) | y-variation (V) | max edge field (V/cm) | psi overshoot (V) | PE sign violations |
|---|---|---|---|---|---|
| M1 D0-D3 | 1.000e-3 | 5.6e-17 | 1.0448e5 | 5.6e-17 | 0 |
| M2 D0-D3 | 1.457e-3 (= 1D dx 0.02 to 6.6e-16 V) | <= 5.6e-17 | 9.701e4 | 5.6e-17 | 0 |
| M3 D0 | **3.835e-2** | 2.08e-2 | 1.037e5 | 5.6e-17 | 0 |
| M3 D1 | **7.528e-3** | 4.62e-3 | 9.72e4 | 5.6e-17 | 0 |
| M3 D2 / D3 | 1.592e-2 / 2.526e-2 | 5.2e-3 / 1.45e-2 | 9.90e4 / 1.011e5 | 5.6e-17 | 0 |
| M4 D0 | **2.427e-1** | 4.23e-1 | 2.607e5 | 5.6e-17 | 0 |
| M4 D1 | not converged | - | - | - | 482 (at restored state) |
| M4 D2 / D3 | 1.730e-1 / 2.110e-1 | 1.13e-1 / 2.59e-1 | 1.985e5 / 1.376e5 | **6.31e-3** / 5.6e-17 | **482** / 0 |
V_bi numeric 0.834505 V everywhere (contact-imposed). Max edge field is the edge-projected field (a lower bound on |E|).

Experiment B (0 V DD; I_scale = 1.657e-2 A/cm, equilibrium tolerance 1.66e-12 A/cm):
every converged configuration has n, p > 0 and finite, |I| <= 1.5e-15 A/cm, conservation OK, contact
majority 1.0000e17 / minority 1.0000e3 cm^-3, max |edge J| <= 2.9e-10 A/cm^2. Exceptions: **M4 D2** quasi-Fermi
deviation 2.39e-6 V (> 1e-6 V), mass action 9.24e-5 (> 1e-6), n up to +27.6 % above the contact maximum and p up to
+23.2 %, psi 6.31e-3 V outside the contact range. M4 D0: quasi-Fermi 3.4e-9 V, mass action 1.3e-7 (pass) with psi
error 0.243 V: a silent error.

Experiment C (currents A/cm of depth, 1D reference = J_1D,finest x H):
| config | I(-0.10 V) | I(+0.05 V) | I(+0.10 V) |
|---|---|---|---|
| 1D dx 0.02 x H | -1.3819e-12 | 2.6169e-12 | 9.5090e-12 |
| 1D finest x H | -9.5039e-13 | 1.1462e-12 | 4.0527e-12 |
| M1 D0 (= D1-D3) | -1.1839e-12 | 1.9927e-12 | 7.2299e-12 |
| M2 D0 (= D1-D3, = 1D 0.02 to 3.3e-16 rel) | -1.3819e-12 | 2.6169e-12 | 9.5090e-12 |
| M3 D0 / D1 / D2 / D3 | -1.3414 / -1.3995 / -1.3860 / -1.3724 e-12 | 2.2256 / 2.6227 / 2.5129 / 2.4379 e-12 | 8.0472 / 9.5331 / 9.1275 / 8.8351 e-12 |
| M4 D0 / D2 / D3 | -9.790e-13 / **-5.845e-12** / -1.178e-12 | 6.287e-13 / **6.180e-12** / 1.170e-12 | 2.297e-12 / 2.022e-11 / 4.077e-12 |
All conserve current. Registered agreement passes everywhere except M4 D2 at -0.10 V and +0.05 V (rel 5.15, 4.39).
Descriptive only (not a registered criterion): at equal nominal resolution M3 D1 is within 0.25 % (+0.10 V) of the
1D dx 0.02 current, M3 D0 is -15.4 %.

M-matrix / sign audit (`get_matrix_and_rhs`, blocks separated by `get_equation_numbers`; expected signs from M2 D0:
PE off-diagonal -, ECE +, HCE -): 0 violations in every D0/D3 configuration and every M1-M3 configuration.
M4 D2: 482 violations in each block; **every violating entry lies on a negative signed couple edge and every one of
the 246 negative edges produces violations (236 interior edges x 2 + 10 contact-touching edges x 1 = 482)**
(`data/diag_m4_D2.json`). M4 D1: identical 482 PE entries at the restored state; PE diagonal is positive at all
47 non-contact negative-volume nodes there. Node-level overshoot on M4 is not a discriminating spatial test (287 of
306 nodes are negative-edge endpoints). Contact current uses the assembled couple: M4 D2 left ECE current
1.840165e-15 A/cm = sum J x OvEdgeCouple (default couple would give 1.995e-14); M4 D0 equals sum J x EdgeCouple.

## 8. L3_after (default D0, signed D1 only)
Both converge (Poisson 10, DD 1/4 iterations). psi Linf vs 1D: D0 1.401e-1 V (y-variation 2.80e-1 V), D1 2.444e-2 V
(4.89e-2 V); both fail 4.372e-3 V. D0: 0 sign violations, no overshoot. D1: 12 PE / 12 ECE / 12 HCE violations = the 6
negative boundary edges x 2 (midpoints x = +-0.025, +-0.075, +-0.15 um on y = -2.0 and 0.0 um); psi overshoot
1.44e-5 V at 4 nodes (hop 0: 2, hop 1: 2 from a negative-edge endpoint), n and p +5.56e-4 relative at 6 nodes
(hops 0/1/2: 2/2/2); endpoint base rate 8/2921 = 0.27 %. Equilibrium currents <= 1.2e-28 A/cm; I(+0.10 V) D0
1.1960e-10, D1 1.2287e-10 A/cm (1D finest x H 8.061e-11).

## 9. Meaning
* Non-obtuse meshes: DEVSIM default = signed geometry; SG DD matches the equal-resolution 1D DEVSIM result exactly (M2)
  and the converged 1D potential within the registered tolerance (M1, M2).
* Obtuse Delaunay meshes: the default (absolute-value) geometry is monotone and converges but is wrong: 38 mV
  potential error and 21 mV artificial y-variation in a y-independent junction (M3); 243 mV / 423 mV on a
  non-Delaunay mesh with every equilibrium diagnostic passing (silent).
* Signed override: consistent where transmissibility >= 0 (large error reduction on M3, still 7.5 mV > tolerance);
  where transmissibility < 0 it produces exactly located sign violations, a discrete maximum-principle violation with
  carriers outside physical bounds, or Newton divergence.

## 10. Production direction (proposal only; no code)
Option 1: DEVSIM default + non-obtuse mesh requirement. Invariant: every triangle has all angles <= 90 deg (exact
integer dot-product test, 7H-A style), single region. Import check before any solve; reason-code candidates
`DEVSIM_MESH_OBTUSE_TRIANGLE_UNSUPPORTED`, `DEVSIM_MESH_INTERFACE_GEOMETRY_UNVERIFIED`,
`DEVSIM_MESH_REFINEMENT_UNVERIFIED`, `DEVSIM_GEOMETRY_CONTRACT_VERSION_UNVERIFIED`. Pin DEVSIM 2.11.0 (default
geometry rule measured on this version only). Contact current: default couple used consistently (verified).
Interfaces: untested -> fail-closed. Refinement: dx 0.02 um is 45-135 % off the converged 1D current; a per-device
refinement study is required. Proofs still needed: a non-obtuse mesh generator for ViennaPS-derived geometry (L3 is
obtuse), multi-region interfaces, asymmetric/high doping, a y-dependent 2D reference, and the gate may only be relaxed
by a separate approved batch.

## 11. Limitations
Current criterion non-discriminating at dx 0.02 um; M3 D1 failure not attributed (override vs local resolution);
one doping case, one region, 300 K, one DEVSIM version, override order-dependence untested; M4 D1 divergence mechanism
(negative volume flipping the charge Jacobian diagonal at high carrier density) is inference; W is node-quantized;
SG 1969 not read; solver relative criterion relaxed to 1e-6 (DEVIATIONS item 1).
