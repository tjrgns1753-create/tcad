# E6K PLAN (proposal, not executed): first production-path PN diode verification -- 1D reference device

Status: a PLAN only. No PN solve was run and no gate was changed in E6J. Numbers below were computed from the production constants
(`simple_physics.py` q = 1.6e-19, k = 1.3806503e-23, n_i = 1e10, mu_n = 400, mu_p = 200, eps_si = 11.1, eps_0 = 8.85e-14; project taun = taup = 1e-8 s,
`semiconductor_equation.py:126-127`) with a scratch calculation (kept in this plan, to be recomputed by the test from the constants read from the device).

## 1. Production entry and current blocks (read, file:line)
- Entry: `run_pn_junction_iv_sweep` (`pn_junction_iv_sweep.py:88-103`: Poisson-only equilibrium solve with abs 1.0 / rel 1e-6, DD enable + solve (abs 1e10 / rel 1e-6, 100 it), one solve per bias)
  after `apply_doping` (`doping_mapping.py:711-718`). Robust path: `run_robust_pn_junction_iv_sweep` (continuation; only needed for ~1e20).
- Blocks in `canonical_node_doping` (`doping_mapping.py`, region-level, after the per-node checks): (a) `COMPENSATED_TRANSPORT_MODEL_MISSING` when an ACTIVE donor and acceptor attachment share positive area
  (`wafer_state_v2.py:778`); (b) `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` for an ACTIVE `step_junction_v1` attachment on a device with `devsim.get_dimension(device) == 2` (`wafer_state_v2.py:815`, `doping_mapping.py:344`).
- Consequence, established by the existing `tests/integration/test_step_junction_2d_gate_real.py` (scenario C, lines 176-226): the SAME canonical ACTIVE step-junction state on a real public 1D DEVSIM device is NOT blocked
  (Donors/Acceptors written, both polarities fire on the junction node, the official `step()` convention). A 2D abrupt junction is blocked and stays blocked.

## 2. Execution route that needs no gate bypass
Stage 1 (E6K, in-gate): 1D reference device built with public DEVSIM calls (`create_1d_mesh`, `add_1d_mesh_line`, `add_1d_contact`, `add_1d_region`, as in the gate test), doped through the production path
`apply_step_junction_doping(..., chemical_state="ACTIVE")` -> `advance_wafer_state(initial_wafer_state_from_recipe(...))` -> `apply_doping` -> `run_pn_junction_iv_sweep`.
Stage 2 (2D): NOT executed. Representing the same abrupt junction as two adjacent `uniform` attachments would sidestep the gate's intent (the 7D Rev.2 study found the 2D step-junction current does not converge)
and is forbidden. A 2D candidate may only be studied after a Codex/user decision, as an audit-only script that builds the 2D device directly with public DEVSIM calls (clearly not the production path), on the E6G/E6H
structured transition meshes with a fixed physical junction position, to decide whether the 7D non-convergence persists. No production gate is lifted by it.

## 3. Device and models (fixed in the plan)
Abrupt 1D p+n-symmetric junction: N_A = N_D = 1e17 cm^-3, ACTIVE, T = 300 K, junction at x = 0, domain x in [-20, +20] um (W_p = W_n = 20 um), ohmic contacts at both ends (production `CreateSiliconPotentialOnlyContact` /
`CreateSiliconDriftDiffusionAtContact`), Boltzmann statistics, full ionisation, constant mobilities, SRH with n1 = p1 = n_i and taun = taup = 1e-8 s (as production sets), no Auger, no tunnelling, 1D.
Derived: V_t = 0.025887 V; D_n = 10.355, D_p = 5.177 cm^2/s; L_n = 3.218 um, L_p = 2.275 um (W/L >= 6.2, so a finite-length coth correction is 1e-5); V_bi = V_t ln(N_A N_D / n_i^2) = 0.8345 V;
depletion width W(0) = 0.1432 um; Debye length 12.6 nm; E_max(0) = 1.166e5 V/cm, E_max(-1 V) = 1.729e5 V/cm.
Polarity: donors where x > 0, so Si_xmax is the n side; forward bias = positive voltage on Si_xmin (p side). By the E6I sign convention (DEVSIM: positive contact current = into the device), forward bias gives I(Si_xmin) > 0.

## 4. Biases and sweeps
0 V; forward 0.3, 0.5, 0.6 V; reverse -0.5, -1.0 V. Low injection n_p/N_A = 1.1e-9 / 2.4e-6 / 1.2e-4 at 0.3 / 0.5 / 0.6 V (<= 1e-3 is reached near 0.655 V, so nothing above 0.6 V is judged).
Two fresh devices per mesh, because `run_pn_junction_iv_sweep` cannot ramp the opposite direction on a used device: forward `sweep_voltages = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]` (steps <= 0.1 V), reverse `[-0.25, -0.5, -0.75, -1.0]`.
Series resistance of the neutral regions: < 3e-5 V at 0.1 A/cm^2, negligible.

## 5. Mesh family (physical junction fixed at x = 0 with a node exactly on it)
Lines at x = -20, -2, -0.3, 0, +0.3, +2, +20 um with spacing ps = 500, 100, 8, 4, 8, 100, 500 nm divided by 2^k for k = 0, 1, 2 (L0, L1, L2). Junction spacing 4 / 2 / 1 nm against a 12.6 nm Debye length.
Node counts to be recorded; abort if > 20,000 nodes.

## 6. What the ideal-diode formula can and cannot decide (applicability)
Shockley's long-diode result with finite-length coth factors gives J_s = q n_i^2 [D_n coth(W_p/L_n)/(N_A L_n) + D_p coth(W_n/L_p)/(N_D L_p)] = 8.789e-12 A/cm^2 and J_diff(V) = J_s (e^{V/V_t} - 1):
2.149e-3 A/cm^2 at 0.5 V, 0.1023 at 0.6 V. It is NOT the exact answer for this device: with tau = 1e-8 s and n_i = 1e10 the SRH generation-recombination current in the depletion region is large -- the generation scale
q n_i W / (2 tau) = 1.1e-6 A/cm^2 at 0 V (1.4e-6 at -0.5 V, 1.7e-6 at -1 V) is 1e5 times J_s, so the reverse current is generation-dominated, and at 0.5 / 0.6 V the recombination term is of the order of
60 % / 10 % of J_diff (Sah-Noyce-Shockley estimate) -- i.e. the diffusion and recombination regimes overlap and no bias exists where the pure Shockley law is applicable and low injection still holds.
Therefore J_diff alone is NOT a pass/fail reference. The reference is J_model = J_diff(V) + J_SRH(V), with J_SRH = q * integral of U dx evaluated by numerical quadrature (not the closed-form SNS approximation) using
n p = n_i^2 exp(V/V_t) (flat quasi-Fermi levels) and the depletion-approximation potential, valid to some percent. The tolerance below already includes that model error.
Literature for the formulas: W. Shockley, Bell Syst. Tech. J. 28, 435 (1949); C.-T. Sah, R. N. Noyce, W. Shockley, Proc. IRE 45, 1228 (1957); S. M. Sze, K. K. Ng, Physics of Semiconductor Devices, 3rd ed., ch. 2.
Code side: DEVSIM's own `examples/diode/diode_1d.py` / `diode_common.py` (the flow `pn_junction_iv_sweep.py` states it follows) for the equations; the project's 1D gate control for the device construction.

## 7. Independent checks vs identities (what is counted)
Counted as independent physics checks (pre-registered before the run, tolerances as stated, NaN-safe judge like E6I):
1. Equilibrium electrostatics: peak |E| and depletion width from the SOLVED potential vs the abrupt-junction formulas at 0 V and -1 V: within 3 % on L2 (the contact BC does not set these).
2. Terminal current J(V) vs J_model at 0.5, 0.6, -0.5, -1.0 V: within 10 % (model error of the quadrature; J_diff-only and J_SRH-only reported separately, with the SRH share). 0.3 V is reported, not judged (both terms comparable, model error largest).
3. Quasi-neutral minority-carrier profile at 0.6 V: p_n(x) - p_n0 against p_n0 (e^{V/V_t} - 1) sinh((W_n - x)/L_p) / sinh(W_n / L_p) at x = 3, 5, 8 um past the depletion edge: within 5 %.
4. Sign and antisymmetry of regime: I(Si_xmin) > 0 forward, < 0 reverse; forward current increases monotonically with V; reverse |I| increases with |V| (generation with W(V)).
5. Mesh sensitivity: J(0.6 V) L1 vs L2 within 1 %; E_max within 2 %; J(-1 V) within 2 %.
Reported but NOT counted as independent evidence: equilibrium n p = n_i^2 and the built-in potential V_bi (set by the contact boundary condition), Newton / solve convergence, equilibrium zero current, terminal KCL
(|I_l + I_r| / |I| <= 1e-6 is a conservation consistency check of the discretisation, listed once as such).
Unit: a 1D DEVSIM device's current is not assumed to be A or A/cm^2. Step 0 of E6K is a 1D uniform-resistor control (N_D = 1e16, length 2 um, V = 1 mV, theory I = sigma V / L with an explicit 1 cm^2 area)
that establishes the 1D unit before the PN numbers are interpreted; only then `current_unit_metadata(1)` may be given a unit (today it is None). The GUI never builds 1D devices.

## 8. Budget, timeout and stop rules
Solves: per mesh forward 2 + 6 = 8 and reverse 2 + 4 = 6, three meshes = 42, plus the 1D resistor control 3 = 45 (+1 equilibrium read per device, 0 extra solves). Remote, one profile, timeout 1800 s.
Stop rules: the first `Convergence failure` or NaN / inf on a device ends that device; it is recorded as FAIL and not retried with changed tolerances, steps or order; a failed mesh level is reported and the later levels still run only if independent.
No solver / tolerance / model change after a result; no gate removal; no DEVSIM internals, NodeVolume / EdgeCouple or signed override. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the PN/DD gates stay.

## 9. Open decisions for Codex / user
(a) Whether to accept the 1D reference as the only in-gate PN check, with the 2D comparison deferred; (b) whether the 2D audit-only study of section 2 is wanted and on which mesh family;
(c) accept J_model = J_diff + J_SRH(quadrature) with a 10 % tolerance, or require a second, independent numerical reference (e.g. the official diode_1d.py run on the same mesh, which is an implementation cross-check, not independent physics).
