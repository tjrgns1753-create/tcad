# E6K PLAN v2 (fixed before the run): first production-path 1D symmetric p-n junction diagnostic

Supersedes the proposal `docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/PN_PLAN.md` (v1 is kept unchanged as historical evidence; the line diff is `PN_PLAN_v1_to_v2.diff`).
Base HEAD of this plan: `26bb753` (unit contract fix) on branch `claude/remote-runner`. This is one bounded diagnostic; it does not validate PN physics and it keeps every gate.

## 1. What changed from v1 (corrections)
1. Device name: **symmetric abrupt p-n junction** (N_A = N_D = 1e17), not "p+n-symmetric".
2. 1D raw current unit: not assumed. DEVSIM's own documentation read for E6J (CommandReference, models page, `simple_physics.py`) gives no cross-section setting for a 1D device, so no area parameter is claimed to exist.
   The unit is established (or not) only by a 1D uniform-resistor control through the same production path: I_raw / (sigma V / L) must equal 1 within 1e-6 at both contacts (sign convention of E6I). If it does not, the PN numbers are not judged (stop rule). Even when it does,
   `current_unit_metadata(1)` stays `None` in production in this batch: the PN currents are shown as "unit not established" and the control ratio is reported as evidence only. No PN current is labelled A or A/cm^2 by production code.
3. The 2D per-unit-depth note is attached only to results with `current_normalization == per_out_of_plane_depth` (done in E6K unit fix, `26bb753`); nothing 2D-specific is attached to 1D output.
4. Reference model rewritten (section 4): J_diff formula, finite-length correction and constants explicit; J_SRH computed from an independent depletion-approximation potential with explicit n(x), p(x); no solved DEVSIM array enters the reference.
5. The v1 sentences "10 % already includes the model error" and "no bias exists where the Shockley law is applicable" are withdrawn. 10 % is only the comparison level of this first diagnostic; the Shockley law is not applicable to this device at the **tested** biases with the accuracy asked here
   (SRH share 42 % at 0.5 V and 12 % at 0.6 V, 96 % at 0.3 V by the section-4 reference), which is a statement about this device, these biases and this accuracy, not about all diodes.
6. The generation scale q n_i W / (2 tau) (= 1.1e-6 A/cm^2 at 0 V) is a bound of the reverse generation current, not an equilibrium current: the net SRH rate at V = 0 is exactly zero (synthetic test).
7. The minority-carrier solution is anchored at the depletion edge x_n(V) (depletion approximation) and uses the actual neutral length W_n' = x_contact - x_n.

## 2. Device, models, production path (kept from v1)
Single Si region, official public 1D mesher (`create_1d_mesh`, `add_1d_mesh_line`, `add_1d_contact`, `add_1d_region`, as `tests/integration/test_step_junction_2d_gate_real.py` scenario C), 40 um long, junction at x = 0 with a mesh node on it, ohmic contacts `l` (x = -20 um, p side) and `r` (x = +20 um, n side).
Doping through the production path: `apply_step_junction_doping(..., chemical_state="ACTIVE")` (N_D right, N_A left, 1e17 each) -> `advance_wafer_state(initial_wafer_state_from_recipe(...), doped, "doping")` -> `apply_doping` (the central gate; 1D is not blocked by `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, and donor/acceptor rectangles abut without area overlap so `COMPENSATED_TRANSPORT_MODEL_MISSING` does not fire)
-> `run_pn_junction_iv_sweep` (equilibrium Poisson solve, DD enable + solve, bias solves, relative_error 1e-6, abs 1e10 / 1.0 as shipped, 100 iterations). T = 300 K; production constants read from the device (q 1.6e-19, n_i 1e10, mu_n 400, mu_p 200, taun = taup = 1e-8, eps = 11.1 x 8.85e-14); constant mobility, Boltzmann statistics, full ionisation, SRH with n1 = p1 = n_i.
Gates stay: 2D step-junction gate, compensation gate, `UNSUPPORTED_BY_MODEL` behaviour. No DEVSIM/ViennaPS internals, NodeVolume, EdgeCouple or signed override.
Polarity: forward bias = positive voltage on `l` (p side); positive contact current = into the device (E6I): forward gives I(l) > 0.

## 3. Mesh family and solves
Lines at x = -20, -2, -0.3, 0, +0.3, +2, +20 um with spacing 500, 100, 8, 4, 8, 100, 500 nm divided by 2^k, k = 0, 1, 2 (L0, L1, L2; junction spacing 4 / 2 / 1 nm vs L_D 12.6 nm). Abort a mesh if > 20,000 nodes.
Per mesh two fresh devices (the sweep cannot ramp the opposite direction on a used device): forward `[0.1, 0.2, 0.3, 0.4, 0.5, 0.6]` (8 solves) and reverse `[-0.25, -0.5, -0.75, -1.0]` (6 solves). Plus the 1D resistor control (uniform N_D = 1e16, x in [-1, 1] um, V = +1 mV on `l`, 3 solves).
Budget: 3 x 14 + 3 = **45 solves**, remote timeout 1800 s, one profile. First convergence failure / NaN / inf on a device: that device is recorded as failed (message, solves done) and is not retried; no tolerance, step, lifetime, mobility or mesh change after any result.
Read-only observation: `devsim.solve` is wrapped by a pass-through that calls the original and afterwards reads `x`, `Potential`, `Electrons`, `Holes` (node models) and `ElectricField` (edge model) and the two `<contact>_bias` parameters; every record stores the solve index, the biases and which arrays were read. The production sweep is called unmodified; no audit solver.

## 4. Independent analytic reference (`scripts/pn_reference.py`, self-checked by `tests/unit/test_pn_reference_mock.py`)
Constants read from the device after the DD setup; V_bi = V_t ln(N_A N_D / n_i^2) = 0.8345 V; D = mu V_t; L = sqrt(D tau): L_n = 3.218 um, L_p = 2.275 um; contacts 20 um away (neutral lengths 20 um minus the depletion half-width).
- Depletion approximation: W(V) = sqrt(2 eps (V_bi - V)(1/N_A + 1/N_D)/q); x_p = W N_D/(N_A + N_D); x_n = W N_A/(N_A + N_D); E_max = q N_A x_p / eps.
- Potential: intrinsic-level potential Psi(x) (piecewise quadratic, continuous at x = 0) measured from the mid-point of the quasi-Fermi levels; flat quasi-Fermi levels separated by V across the depletion region:
  n = n_i exp((Psi + V/2)/V_t), p = n_i exp((-Psi + V/2)/V_t), Psi(-x_p) = V/2 - V_t ln(N_A/n_i), Psi(x_n) = -V/2 + V_t ln(N_D/n_i); n p = n_i^2 exp(V/V_t).
- J_diff (minority diffusion in the finite neutral regions with ohmic contacts, neutral recombination included through L): J_diff = q n_i^2 [ D_n coth(W_p'/L_n)/(N_A L_n) + D_p coth(W_n'/L_p)/(N_D L_p) ] (exp(V/V_t) - 1), W' = neutral length - depletion half-width.
- J_SRH = q int_{-x_p}^{x_n} U dx, U = (n p - n_i^2)/(tau_p (n + n_i) + tau_n (p + n_i)), integrated ONLY over the depletion region (the neutral-region recombination is inside J_diff, not added twice), composite Simpson on [-x_p, 0] and [0, x_n]; the numerator is n_i^2 expm1(V/V_t), so V = 0 gives exactly 0.
  The Simpson refinement difference (N = 2048 vs 4096 panels; < 1e-11 in the self-check) is reported separately and says nothing about the model error.
- J_model = J_diff + J_SRH; sign: positive forward (into the device at `l`). Charge storage / modulation of the depletion region, neutral-region voltage drop, high injection, field-dependent mobility, Auger, band-gap narrowing, tunnelling and QFL splitting inside the depletion region are not modelled.
  Reference values (self-check run): V = 0.3 / 0.5 / 0.6 / -0.5 / -1.0 V: J_diff 9.48e-7 / 2.149e-3 / 0.1023 / -8.8e-12 / -8.8e-12; J_SRH 2.44e-5 / 1.559e-3 / 1.378e-2 / -3.30e-7 / -5.80e-7 A/cm^2; E_max(0) = 1.166e5, E_max(-1) = 1.729e5 V/cm; W(0) = 0.1432 um, W(-1) = 0.2123 um.
- Literature: W. Shockley, Bell Syst. Tech. J. 28, 435 (1949); C.-T. Sah, R. N. Noyce, W. Shockley, Proc. IRE 45, 1228 (1957); S. M. Sze, K. K. Ng, Physics of Semiconductor Devices, 3rd ed., ch. 2. Code side: the DEVSIM equations of `simple_physics.py` (`CreateSiliconPotentialOnly`, `CreateSiliconDriftDiffusion`, SRH `CreateSRH`, contact BCs) as used by `semiconductor_equation.py` / `pn_junction_iv_sweep.py`.
  Reference limits stated up front: the depletion approximation has a smooth-edge error of the order of a few Debye lengths; the SRH integral rests on flat QFLs; low injection (n_p/N <= 1.2e-4 up to 0.6 V) holds; the formulas are approximations whose error for this device is not established here.

## 5. Extraction rules (fixed)
- E_max: maximum of |`ElectricField`| over the edges of the solved device (V/cm) at the solve with `l_bias` equal to the target and Electrons present (the last such solve).
- Operational depletion width: W_E = 2 int |E| dx / E_max over the whole device (trapezoid over edge mid-points; exact for the triangular field of the depletion approximation). Limit: the real field has smooth edges and a small neutral-region field, so W_E and the depletion-approximation W differ by a model-dependent amount; D compares them with a tolerance, not equality.
- Minority carriers: `Holes` interpolated linearly at x = x_n(V) + s, s in {3, 5, 8} um, V = 0.6 V; reference p_n0 expm1(V/V_t) sinh((W_n' - s)/L_p)/sinh(W_n'/L_p) with x_n(V) and W_n' from the depletion approximation; the excess is `Holes - p_n0`, p_n0 = n_i^2/N_D. Origin uncertainty (the actual edge differs from x_n by a few Debye lengths = ~1-3 % of the profile) is part of the tolerance.
- Current: `result.points[i].currents["l"]` of the production sweep (electron + hole, E6I convention). Near-zero true values are never judged by relative error: V = 0 is reported only (net current should vanish; this is an initialisation identity, not evidence).
- Finite rule for every number: `finite and value <= limit`; NaN / inf / None / string fails.

## 6. Pre-registered categories and limits (separate verdicts; no overall PASS; `PN_PHYSICS_VALIDATED` is never declared)
- **A CURRENT_UNIT_CONTRACT**: 1D result metadata `current_unit` is None and shows "unit not established"; the E6J preserved GUI evidence has 0 failed checks of 17; the 1D resistor control ratio is recorded as unit evidence (not a production unit).
- **B PRODUCTION_PATH_EXECUTED**: per device the production sweep was called once, solves equal 2 + number of voltages (3 for the control), device dimension 1, Donors/Acceptors written as {0, 1e17} (control {1e16} / {0}), no exception.
- **C NUMERICAL_CONVERGENCE_AND_MESH_SENSITIVITY**: every device converged; J(0.6 V) L1 vs L2 <= 1 %, J(-1.0 V) <= 2 %, E_max(-1.0 V) <= 2 % (L0 -> L1 -> L2 differences reported).
- **D ANALYTICAL_ELECTROSTATICS_COMPARISON** (L2): E_max within 3 % at 0 and -1.0 V; W_E within 5 % at 0 and -1.0 V.
- **E APPROXIMATE_SRH_DIFFUSION_REFERENCE_COMPARISON** (L2): J at 0.5, 0.6, -0.5, -1.0 V has the reference sign and is within 10 % of J_model. 0.3 V reported only. The 10 % is the first-diagnostic comparison level only, not a model-error bound; being inside it does not validate PN physics.
- **F MINORITY_CARRIER_PROFILE_COMPARISON** (L2, 0.6 V): hole excess within 10 % of the sinh solution at s = 3, 5, 8 um (10 % because of the origin uncertainty above; fixed now).
Not counted as independent physics: equilibrium n p = n_i^2, the V_bi equality set by the contact condition, Newton convergence, equilibrium zero current, terminal KCL. Official `diode_1d.py` is not rerun (an implementation cross-check on the same engine, not independent physics).
Stop rules: the 1D unit control fails -> categories C-F are `NOT_EVALUATED` and no PN solve is run; synthetic reference/judge self-checks fail -> no run; the device cannot be built inside the production contract -> blocker, no gate change.
