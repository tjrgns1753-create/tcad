# Batch 7H-E6I criteria: low-field drift-diffusion current of a uniformly doped Si resistor (fixed before any DEVSIM run of this batch)

**Base.** HEAD `e722aea350e939567de044436c5b5c94d178bcbe`, branch `claude/remote-runner`, tracked dirty 0, no evaluation running.
Only the root `CLAUDE.md` exists in the hierarchy (checked with find). Physics (DEVSIM/ViennaPS) runs only on the GitHub-hosted runner;
locally: source reading, this document, implementation, pure checks (the judge with NaN/inf tests).
Serena (session 14064f89): production DD path = `import_process_result` -> `apply_doping` (central canonical gate `canonical_node_doping`,
`doping_mapping.py:131`, writes `Donors/Acceptors/NetDoping` at `doping_mapping.py:711-718`) -> `run_pn_junction_iv_sweep`
(`pn_junction_iv_sweep.py:88-103`: `setup_semiconductor_potential_equation` + solve, `setup_drift_diffusion_equation` + solve, `set_bias` + solve,
`read_drift_diffusion_terminal_currents`) ; the GUI path `TCADApplication.run_measurement` (`tcad_2d_stagewise.py:5704`, uniform kind goes
through lines 5892-5901, prints the current at 5963-5966). `resistor_equation.py` (constant Conductivity) is NOT used for the result.

## Model and theory (non-degenerate statistics, full ionisation, constant mobility, uniform 1D-equivalent conduction)
Production constants are read from DEVSIM at run time and must equal the values in `devsim/python_packages/simple_physics.py` of the
installed DEVSIM 2.11.0 (file:line in the local venv: `q = 1.6e-19` :34, `n_i = 1.0e10` :41, `mu_n = 400` :43, `mu_p = 200` :44, `SetSiliconParameters`
:122-141 sets Permittivity, ElectronCharge, n_i, T, V_t, mu_n, mu_p, taun = taup = 1e-5) and project `semiconductor_equation.py:126-127`
(taun = taup = 1e-8 s override for drift-diffusion). The theory is computed from the values READ from the device, not from literature
mobilities. Temperature 300 K. Doping: donor 1e16 cm^-3, acceptor 0, declared `ACTIVE` through `apply_uniform_doping(..., chemical_state="ACTIVE")`
and attached by `advance_wafer_state(initial_wafer_state_from_recipe({x_extent_um: 2.0, silicon_depth_um: 0.5, grid_delta_um: 0.25}), doped, "doping")`
(explicit recipe geometry; nothing inferred from the mesh; no LEGACY_UNRESOLVED promotion, no gate bypass).
- n0 - p0 = N_D - N_A and n0 p0 = n_i^2 give, numerically stable: n0 = (N + sqrt(N^2 + 4 n_i^2)) / 2 (N = N_D - N_A > 0), p0 = n_i^2 / n0.
- sigma = q (mu_n n0 + mu_p p0). (Production contact model adds 1e-10 cm^-3 to the electron density: relative 1e-26, recorded, ignored.)
- Geometry: single Si rectangle x in [-1, 1] um, y in [-0.5, 0] um (L = 2e-4 cm, H = 0.5e-4 cm); contacts = the full x = min and x = max sides
  (`import_process_result(contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1e-4)`), top/bottom insulating (natural).
- Current per unit depth: I = sigma (H / L) DeltaV (A per cm of out-of-plane depth). Basis: DEVSIM integrates 2D edge/node models with
  NodeVolume / EdgeCouple in cm^2, i.e. an implicit 1 cm depth; the same statement is the project's `CURRENT_CONVENTION_NOTE`
  (`tcad/characterization/interface.py`). The DEVSIM manual pages read for this batch (devsim.net CommandReference and models pages) do not state
  the depth; if the measured magnitudes disagree with this unit the criterion FAILS and the unit is not re-chosen after the fact.
  The GUI prints the same number as "I = ... A" without multiplying by any depth (`tcad_2d_stagewise.py:5963-5966`): it is per unit depth.
- Sign: DEVSIM manual (devsim.net models page, contact_equation section): "Current models refer to the instantaneous current flowing into the
  device"; CommandReference `edge_current_model`: "the current flowing out of this contact". So a positive contact current is conventional
  current entering the device through that contact. A positive bias on Si_xmax (Si_xmin grounded) makes I(Si_xmax) > 0 and I(Si_xmin) < 0 with
  |I| = G DeltaV. (Earlier production outputs in CLAUDE.md, +4.855 A / -4.855 A for +0.3 V on the source pin, agree with this convention.)

## Cases (all fixed now)
Meshes, all made by `structured_lateral_refine` on the E6H family (domain 2 um x 0.5 um, n/4 rows, h = 2/n um; dyadic coordinates, translated by the
exact binary shift (-1.0, -0.5) um into the canonical frame): `uniform` n = 8; `one_sided` n = 8, 16, 32 (center at the domain middle, rings [h, h/2]);
`two_sided` n = 8, 16, 32 (centers 2h and 5h from the left end, ring [h]). The physical domain is identical for all; the transition zones shrink
with h (one-sided: centered, width ~ 4h; two-sided: near the left end), so this is a sequence of refinement layouts, NOT a proof of convergence for one
fixed layout or for general refinement.
Bias: contact Si_xmax = 0, +1e-3, -1e-3, +2e-3 V, Si_xmin = 0 (volts). Each bias on a FRESH imported device through the production path with
`sweep_voltages=[V]` (exactly the GUI call), `relative_error = 1e-6`, `absolute_error = 1e10`, `maximum_iterations = 100` (the function's own defaults);
the order within a device is the production order (equilibrium Poisson solve, DD enable + solve, bias solve); no continuation, no retry,
no setting changed after a result. Electron and hole terminal currents are read with `get_contact_current` for `ElectronContinuityEquation` and
`HoleContinuityEquation`; the total is their sum (the production reader).

## Acceptance (fixed)
Judge = `scripts/resistor_judge.py`; every comparison has the form `finite and value <= limit`, so NaN / inf can never pass (unit-tested with NaN/inf inputs).
Reference nonzero current I_ref = |I_theory(+1 mV)| = G x 1e-3 V.
1. All currents, carrier, potential and recombination arrays finite.
2. For each mesh and each nonzero bias and each terminal: |I_total - I_theory| / |I_theory| <= 1e-2, with I_theory(Si_xmax) = +G V, I_theory(Si_xmin) = -G V
   (sign included: the wrong sign gives a relative error of 2). Electron current alone also within 1e-2 of I_theory. The hole current is reported; its share
   |I_h| / |I_total| must be <= 1e-6.
3. Conservation: |I(Si_xmax) + I(Si_xmin)| / I_ref <= 1e-6 at every bias (including 0 V).
4. Odd symmetry: |I(+1 mV) + I(-1 mV)| / |I(+1 mV)| <= 1e-2 at each terminal.
5. Linearity: |I(+2 mV) - 2 I(+1 mV)| / |2 I(+1 mV)| <= 1e-2 at each terminal.
6. Mesh: for each family |G(n = 32) - G(n = 16)| / G(n = 32) <= 1e-2 with G = I(Si_xmax, +1 mV) / 1e-3 V; every mesh separately also satisfies 2.
7. Equilibrium (0 V) is an initialisation identity, not an independent validation; only an absolute bound is judged: |I(0 V)| <= 1e-4 x I_ref at each terminal.
   Basis: DEVSIM stops at relative update 1e-6 of the potential scale V_t = 0.02585 V, i.e. a potential error <= 2.6e-8 V, which drives a spurious current
   <= G x 2.6e-8 V = 2.6e-5 I_ref; the bound carries a factor ~4. Not relaxed after the run.
8. States (recorded, judged where stated): electron density uniformity max |n / n0 - 1| <= 1e-4 (judged, all biases); potential linearity
   max |psi - (psi(x_min) + V (x - x_min) / L)| / max(|V|, 1e-3 V) <= 1e-2 at nonzero bias (judged; psi taken from the solved device, interior nodes);
   hole density and SRH recombination (max |USRH|, integral of q USRH over NodeVolume relative to I_ref) recorded only (minority drift changes p by O(V / V_t),
   so no uniformity claim for p).
9. Canonical input: `Donors` = {1e16} and `Acceptors` = {0} written at every node, NetDoping = {1e16}; devsim.solve counted (production 3 per device);
   no device leaked.

## GUI connection (one supported mesh: one_sided n = 8)
`TCADApplication.run_measurement` with `app.last_doped_result = doped`, `app.last_final_mesh = <that mesh>` (so no re-doping), `app.wafer_state` the canonical
state above, `meas_voltage_var = 1e-3`, `meas_axis_var = "x"`, `meas_source_pin = "max"`; messageboxes trapped. Required: the GUI-displayed source and ground currents equal
the direct-path currents at +1 mV to 1e-9 relative (same path, printed with 7 digits: limit 1e-6 on the printed strings), same sign and unit (per unit depth,
printed "A" without a depth factor -- reported as a labelling fact, not changed).
UNSUPPORTED control through the same GUI call: `chemical_state = "CHEMICAL"` and `"UNKNOWN"` with the same mesh: 0 `devsim.solve`, 0 doping writes,
no `DEVSIM MEASUREMENT` block in the log, no info dialog, the earlier ACTIVE value is not shown again, no leaked device, reason code UNSUPPORTED_BY_MODEL.

## On failure
No tolerance, unit, sign, depth, model or order change. The cause is isolated on one small mesh (boundary condition, unit, aggregation, precision) and a clear
project-code bug is fixed minimally with fail-before / pass-after preserved. Ohmic `resistor_equation.py` is never substituted for DD.

## Out of scope
PN junctions, high doping, process-derived devices, the 196,000-triangle F mesh, PN/DC sweeps, full regression, gate changes.
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the PN/DD gates stay; a uniform input is not gated by the step-junction reason (`active_step_junction_instances`
finds no `step_junction_v1` attachment).
