# E6M PLAN (fixed before any 2D solve): limited 2D-1D consistency of the E6K p-n problem

Base HEAD `2ea7d3c` (E6L CORRECTION_1), branch `claude/remote-runner`. One simple structure, three meshes, fixed physics, the preserved E6K 1D data as the reference (run 36815925901; no 1D re-run).
This does NOT approve: any other 2D PN structure, any process sequence, a fabricated device, oxidation / diffusion / activation models, the production GUI PN measurement, or `PN_PHYSICS_VALIDATED`. Agreement of two discretisations of the same model is a consistency result, not an independent proof that either is physically right.

## 1. Question
If the E6K 1D problem is extended uniformly in y, does the 2D calculation (same equations, same solver settings) reproduce the preserved 1D result?

## 2. Structure, physics, boundary conditions (all fixed now)
- Single Si rectangle, explicit verification geometry (NOT produced by any process step, no positive-time oxidation): x in [-20, +20] um, y in [-H, 0], **H = 0.1 um = 1.0e-5 cm** (the only um -> cm conversion of H: `H_CM = H_UM * 1.0e-4` in `scripts/e6m_metrics.py`).
- Doping exactly as E6K: N_A = N_D = 1e17 cm^-3 ACTIVE, abrupt junction at x = 0, E6K step convention (acceptors where x <= 0, donors where x >= 0, so the junction nodes carry both and NetDoping 0).
- T = 300 K and the production constants set by `setup_semiconductor_potential_equation` / `setup_drift_diffusion_equation` (q 1.6e-19, n_i 1e10, mu_n 400, mu_p 200, taun = taup = 1e-8, eps 11.1 x 8.85e-14), Boltzmann statistics, full ionisation, SRH with n1 = p1 = n_i; read back from the device and required equal to E6K's.
- Contacts: `Si_xmin` (x = -20 um, p side) and `Si_xmax` (x = +20 um, n side) created by the production importer over the FULL height (`import_process_result(contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1e-4)`); ohmic contact equations exactly as production (`CreateSiliconPotentialOnlyContact`, `CreateSiliconDriftDiffusionAtContact`).
- Top (y = 0) and bottom (y = -H): no contact and no interface equation. In DEVSIM's finite-volume assembly a boundary without a contact/interface equation contributes no flux, i.e. zero normal electric flux and zero normal electron / hole current -- the y-extension of the 1D problem.
  Code basis: production adds equations only on the region and on the two contacts (`semiconductor_equation.py:69-80, 129-136`); preserved evidence: E6I (same importer, same boundary treatment) reproduced I = sigma (H/L) V to 1e-13, which requires insulating top/bottom. No surface recombination, interface charge, contact resistance or any term absent from the 1D reference is added.
- Bias as E6K: sweep contact = p side (`Si_xmin`; E6K `l`), `Si_xmax` grounded; forward `[0.1, 0.2, 0.3, 0.4, 0.5, 0.6]`, reverse `[-0.25, -0.5, -0.75, -1.0]`, each direction on a fresh device; production `run_pn_junction_iv_sweep` with its shipped defaults (relative_error 1e-6, abs 1.0 / 1e10, 100 iterations): equilibrium Poisson solve, DD enable + solve, one solve per bias.

## 3. Meshes
For each E6K level L0 / L1 / L2 the x lines are the node coordinates STORED in the E6K `states.npz` (345 / 685 / 1371 lines), converted cm -> um by `x_um = x_cm * 1e4`; y lines at -0.1, -0.05, 0.0 um (two rows, three node lines so that a y variation can be seen).
Each rectangle cell is split into two right triangles. Triangles are strongly anisotropic (0.9 nm x 50 nm near the junction, 500 nm x 50 nm far away) but right-angled, hence non-obtuse.
The mesh is written as a `.vtu` (float64) and imported by the production importer (`create_gmsh_mesh` public API, production area / NodeVolume gate). Requested equality of x lines is NOT assumed: the node coordinates DEVSIM reports are stored and compared with the 1D ones, and the junction-adjacent edge lengths are recorded.

## 4. Audit path vs production path
The production measurement entry (`apply_doping` -> `canonical_node_doping`) refuses this input: an ACTIVE `step_junction_v1` attachment on a 2D device -> `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`. That gate is NOT changed, disabled or bypassed in production. Step 1 of every mesh calls the real `apply_doping` on the 2D device and records the refusal (reason code, 0 doping writes, 0 solves).
The audit model then writes `Donors` / `Acceptors` / `NetDoping` node models directly with the public DEVSIM API using the step convention above (values cross-checked against the canonical `WaferStateV2.net_doping_at` query at every node where that query resolves; any mismatch stops the run), and calls the unmodified production equation setup and sweep.
| item | production | this audit |
|---|---|---|
| mesh import, contacts, area / NodeVolume gate | `import_process_result` | same function |
| doping source | canonical state through the central gate (`apply_doping`) | same numbers, written directly; the gate is recorded as REFUSING |
| equations, contact BCs, SRH, tolerances, sweep | `run_pn_junction_iv_sweep` | same function, unmodified |
| GUI | `run_measurement` | not used; nothing about the GUI PN measurement is claimed |
| status of a 2D PN result | UNSUPPORTED_BY_MODEL | audit evidence only |
No DEVSIM / ViennaPS internal, installed file, NodeVolume, EdgeCouple or signed override is touched; no numeric fallback hides a failure.

## 5. Units
- 2D contact current: A per cm of out-of-plane depth (E6I measurement, E6J contract; the production sweep's metadata must say `current_unit = "A/cm"`, `per_out_of_plane_depth`, dimension 2). `J_2D = I_2D / H_CM` [A/cm^2].
- 1D reference: the E6K raw contact current. Its unit is NOT declared by production metadata (`current_unit` None for dimension 1). The basis for comparing it with A/cm^2 is the E6K 1D resistor control (raw current / (sigma V / L) = 1.0000000000010), re-verified here by the E6L strict judge on the preserved evidence.
- If either basis does not hold, the current comparison is BLOCKED (not evaluated).

## 6. Solve budget
Per mesh: forward 2 + 6 = 8, reverse 2 + 4 = 6; three meshes: **42 solves** (the gate-refusal step runs 0 solves). E6K scale was 45. One remote profile, timeout 1800 s, artifact <= 60 MB.
A device whose solve fails (convergence, NaN/inf) is recorded as failed and not retried; nothing (tolerance, step, lifetime, mobility, mesh, H) is changed after a result.

## 7. Checks, comparison rules and limits
All limits are engineering criteria fixed for this experiment (those marked E6K reuse E6K's pre-registered numbers); none is a physical law. Every number must be a finite int/float (no bool, numeric string, None, NaN, inf); a missing mesh / device / bias / array is `EVIDENCE_INTEGRITY_FAIL`; summary values must equal the values recomputed from the raw JSON and the stored arrays.
- **G1 GEOMETRY_AND_IMPORT** (must pass before any solve of that mesh): sum of triangle areas = 40e-4 cm x H_CM to 1e-12 relative; the importer's area gate passes (NodeVolume sum vs area); every triangle non-obtuse; the E6H exact conformity check passes; regions == [Si];
  `Si_xmin` and `Si_xmax` each have 3 nodes spanning y in [-H, 0] at x = -+20 um; DEVSIM x lines equal the E6K 1D node coordinates to 1e-12 relative (max difference recorded; no interpolation fallback).
- **G2 PRODUCTION_GATE_HELD**: `apply_doping` raises `UnsupportedDopingState` with reason `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, 0 doping writes, 0 solves; audit doping equals the canonical query wherever it resolves.
- **G3 UNIT**: section 5.
- **G4 CONVERGENCE_AND_CONSERVATION**: all six devices return every sweep point with finite currents and exactly 2 + #voltages solves; |I(Si_xmin) + I(Si_xmax)| / |I(Si_xmin)| <= 1e-3 at every sweep bias
  (basis: with the same solver settings the preserved 1D evidence shows up to 7.2e-5; one order of magnitude above that; the currents judged are non-zero. No equilibrium current is produced by the sweep, so no near-zero quantity is divided).
- **G5 Y_INVARIANCE** (biases 0, 0.5, 0.6, -0.5, -1.0 V): over the three y nodes of every x line, potential spread <= 1e-5 V (absolute; ~10x the Newton update bound 1e-6 x max |psi| ~ 0.9 V) and carrier spread (max - min)/mean <= 1e-3 (the same bound through n ~ exp(psi/V_t)); max |E| on non-horizontal edges is reported.
- **G6 CURRENT_2D_VS_1D** (same level, I(Si_xmin)/H vs E6K I(l)): relative difference <= 1 % at 0.5 and 0.6 V, <= 2 % at -0.5 and -1.0 V (E6K mesh-sensitivity limits); sign equal. All other sweep biases reported.
- **G7 PROFILE_2D_VS_1D** (same biases as G5, all nodes, no interpolation because the x lines coincide): max |psi_2D - psi_1D| <= 0.01 V_t = 2.59e-4 V and max relative carrier difference <= 1 % (the potential shift that changes an exponential current by 1 %).
- **G8 JUNCTION_FIELD_2D_VS_1D** (0 V and -1.0 V): on the HORIZONTAL edges adjacent to x = 0 (left and right, each of the three y lines; edge end points taken from the DEVSIM edge models `x@n0, x@n1, y@n0, y@n1`), the x component of `ElectricField` vs the E6K 1D value of the edge with the same end points: <= 2 % (E6K E_max limit).
  Never the maximum over edges of all directions. The depletion approximation and the PB centre / edge-mean values are different references and are reported as diagnostics only (PB at 0 V only; PB is not used at reverse bias); E6K's 3 % depletion criterion is not re-judged here.
- **G9 MESH_SENSITIVITY_2D** (E6K limits): J(0.6 V) L1 vs L2 <= 1 %, J(-1.0 V) <= 2 %, junction-edge E_x(-1.0 V) <= 2 %.
Separate verdicts PASS / FAIL / BLOCKED / NOT_EVALUATED / EVIDENCE_INTEGRITY_FAIL; no combined PASS, no `PN_PHYSICS_VALIDATED`. RC = 0 or Newton convergence is not a physics verdict.

## 8. Evidence stored
Per mesh: node coordinates (input um and DEVSIM cm), triangles, element node list, edge end-point models, EdgeLength, NodeVolume, Donors / Acceptors / NetDoping; per device at the biases 0, 0.3, 0.5, 0.6 (forward) and 0, -0.5, -1.0 (reverse): Potential, Electrons, Holes, ElectricField; all contact currents; per-solve record (index, biases); device parameters; versions, source SHA, PLAN SHA, judge file hash; the native solver log.

## 9. Stop conditions
Engine or production-gate change needed; G1 fails (no solve for that mesh); contacts / boundaries do not correspond to the 1D extension; unit basis fails; raw evidence cannot be stored; budget exceeded; a physical parameter would have to change; an unexplained contract difference to the preserved evidence. Audit-script syntax or synthetic-fixture errors may be fixed within this scope, with the failed run kept.
