# Batch 7H-E1 PLAN (fixed BEFORE any ViennaPS / DEVSIM execution of this batch; never edited after results)

Execution location: everything that runs ViennaPS or DEVSIM (production mesh generation, control, shadow) runs on a
GitHub-hosted Windows runner (`claude/remote-runner`, profile `e1_production_step_junction`). Locally only code reading,
code writing, static checks and synthetic-input analyzer tests.

## 0. Question and limits
Is the production 2D step-junction path (what a user builds) physically equivalent to the D2/D4 benchmark fixtures?
Precision-flag comparison is not repeated. D4's approved result (P12 == P4 on three synthetic non-obtuse fixtures) does not
extend to the production mesh. Nothing here releases `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, changes production
flags or code, or merges anything. A shadow result is never "supported in production".

## 1. Production path followed (read-only mapping; full file:line table in REPORT)
The one production path that reaches the 2D step-junction gate today (the CLI `run_pipeline()` stops earlier, documented in
`tests/integration/test_step_junction_2d_gate_real.py` module docstring): GUI materialize wafer
(`tcad_2d_stagewise.py:254-285`, `make_mask_spans` + `save_volume_mesh`) -> `run_doping` (`:5028`, `build_process_result`,
`apply_step_junction_doping` at `:5110`, `advance_wafer_state(..., "doping", barrier_windows, "x")` at `:5278`, initial state
`initial_wafer_state_from_recipe` at `:3854`) -> `run_measurement` (`:5704`, `import_process_result` at `:5822` with
`refine_near_um` = junction position, `apply_doping` at `:5891`, `run_pn_junction_iv_sweep` at `:5895`).
The run reproduces this sequence by calling the same library functions with the GUI default arguments (the GUI itself is not
executed): Wafer width 10 um, silicon depth 5 um, y extent 8 um, grid 0.05 um (`tcad/core/models.py:22-23,100`), no resist
spans, mask height max(pr 1.0, 0.1) = 1.0 um, substrate depth 6 um, floor 5 um; step junction region Si, axis x, position
0 um, donor = acceptor = 1e18 cm^-3, ACTIVE (`tcad_2d_stagewise.py:4823-4837`); barrier windows from
`derive_barrier_covered_windows(..., "SiO2", "x", min 0.0)` (`:5228-5236`, threshold default `:4938-4940`); import mesh
`gui_measure_mesh`, device `gui_measure_device`, contact regions [Si], axis x, length scale 1e-4, refine near 0.0 on x
(half width 0.1 um, 4 levels = import defaults); measurement source pin max, 0.3 V, other contact 0 V (`:5583-5624`).

## 2. Control (production gate, must hold)
On the production device, `apply_doping` is called unmodified. Instrumented without changing behaviour: counts of
`devsim.solve`, and of `node_model` / `set_node_values` / `edge_model` calls naming Donors, Acceptors or NetDoping; every
`WaferStateV2.net_doping_at` return value is recorded in call order (observation of the values the gate computes before it
raises). `GATE_HELD` iff `UnsupportedDopingState` with reason_code `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, 0 solves,
0 doping writes, and NetDoping absent afterwards. Otherwise `GATE_NOT_HELD` and STOP (no shadow).

## 3. Pre-checks on the production mesh (recorded before any shadow solve)
Node / triangle counts; exact angle classes, min/max angle, exact Delaunay and boundary-Gabriel violations, signed edge-couple
and signed node-volume negatives (7H-D `quality()`); DEVSIM default sum NodeVolume / exact area; nodes with x = 0 exactly and
the doping written there (J0 / J1); regions, materials and contact node sets with their x positions; dopant inventory
sum(Donors x NodeVolume), sum(Acceptors x NodeVolume) versus the exact area integral N x area(side); recorded canonical values
versus a direct `state.net_doping_at` query at every node (count of differences). Nothing here is graded as PASS; it is the
equivalence table. A benchmark property is called "same" only if the numbers / hashes match.

## 4. Shadow (audit-only, never production)
Only if `GATE_HELD` and identity holds: the same mesh file (sha256), imported with the same arguments into a new device whose
node coordinates and element list sha256 equal the control device's; Donors / Acceptors / NetDoping written with the public
DEVSIM API from the recorded canonical per-node arrays (sha256 recorded; node order proven by coordinate equality with the
recorded query coordinates). Any mismatch: `SHADOW_IDENTITY_FAIL`, no shadow solve, INCONCLUSIVE.
Then the unmodified production routine `run_pn_junction_iv_sweep(device, "Si", contacts, sweep_contact = max-x contact,
[0.3], fixed_contacts = {min-x contact: 0.0})` runs exactly as the GUI calls it (its own tolerances: Poisson abs 1.0 / rel 1e-6,
drift-diffusion abs 1e10 / rel 1e-6, 100 iterations, single bias jump). Two shadow runs, each its own subprocess:
* S0: no precision flag set (production default; flags left unset, read back);
* S12: `extended_model` = `extended_equation` = True, `extended_solver` unset-default False (audit variant; D4's result does
  not cover this mesh, so everything is recorded independently).
`devsim.solve` is wrapped only to snapshot after each call; after the second call (0 V drift-diffusion) and after the bias
solve: contact currents per species, the five 7H-D2 cuts (x = -0.25, -0.10, 0, +0.10, +0.25 um; node on a cut to the R side),
C3 residuals, carrier positivity / finiteness, max |ElectricField| on edges, contact potentials, material parameters read back.

## 5. Shadow verdicts (per run; thresholds reused unchanged from 7H-D1/D2/D3, none new)
* `NOT_CONVERGED` if the production routine raises.
* positivity: n, p > 0 and finite at 0 V and 0.3 V.
* equilibrium (0 V): |I_contact| and |I_cut| <= 1e-6 x |I(0.3 V)| of the same run; quasi-Fermi flatness <= 1e-6 V; max |n p / n_i^2 - 1| <= 1e-6.
* conservation (0.3 V): |I_L + I_R| / |I_L|, five-cut spread, |I_L - I_cut(0)|, |I_R + I_cut(0)| (relative) <= 1e-5; C3 species and total <= 1e-5 |I_cut(0)|.
* denominator rule: a relative comparison with |reference| < 1e-6 x max cut |I| is UNDECIDABLE (INCONCLUSIVE, never PASS).
`SHADOW_CONSISTENT` iff converged and all hold; `SHADOW_INCONSISTENT` iff converged and any fails; `INCONCLUSIVE` iff only
undecidable. Analytic depletion-approximation values are reported as reference ranges only, not graded (n_i 1e10 cm^-3,
eps 9.8235e-13 F/cm, T 300 K, V_T 0.025887 V, N_A = N_D = 1e18 cm^-3, abrupt junction, full depletion, infinite neutral
regions): V_bi 0.95372 V, W(0 V) 0.0484 um, W(0.3 V reverse) 0.0555 um, E_peak 3.94e5 / 4.52e5 V/cm, L_D 0.0040 um.
They are not the exact solution of a finite-domain drift-diffusion problem.
Mesh convergence: only one production mesh is run, so it is `UNVERIFIED` by construction; no convergence claim is made.

## 6. JSON and artifacts
New JSON is written with `allow_nan=False`; a non-finite diagnostic is stored as null with an explicit status field, and every
new JSON file is re-read with a strict parser. D4's original files are not touched. Artifact: summary, sanitized log, all JSON,
node arrays (npz) with sha256; budget 200 MB, anything omitted is listed with its sha256 and the regeneration note.

## 7. Stop conditions (report UNSUPPORTED_BY_MODEL grounds, do not adapt)
Geometry / doping support not exactly mappable; shadow and production mesh node / element or doping inventory mismatch;
flag / parameter / contact readback mismatch; non-convergence, conservation failure or non-physical carriers are reported as
results (not repaired); anything that would need a DEVSIM internal change or a numerical correction. No threshold, mesh,
material parameter or bias is changed after a result is seen.
