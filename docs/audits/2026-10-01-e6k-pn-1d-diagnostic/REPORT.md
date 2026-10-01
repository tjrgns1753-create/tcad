# E6K REPORT: 1D symmetric p-n junction diagnostic (production path) + unit-unknown display fix

Six separate verdicts (no overall PASS, `PN_PHYSICS_VALIDATED` is not declared). Plan fixed before the run: `PN_PLAN_v2.md` (sha256 `c126a0e6e939d828...`, commit df5d5d3); v1 kept unchanged, `PN_PLAN_v1_to_v2.diff`.
Remote run 36815925901, executed SHA `1fcf745a97795451e50a6fc272e0ee9ce5f67f3e`, DEVSIM 2.11.0, ViennaPS 4.6.2, numpy 2.4.6, meshio 5.3.5; 4 of 4 steps rc 0; 45 `devsim.solve` calls (control 3 + 6 PN devices x (8 forward | 6 reverse) x 3 meshes), 0 leaked devices, no failed device.

| category | verdict | basis |
|---|---|---|
| A CURRENT_UNIT_CONTRACT | PASS | 1D result: `current_unit` None, `device_dimension` 1, no 2D note attached, `format_current` -> "3.200000e+00 (unit not established)"; E6J preserved GUI evidence: 17 checks, 0 failed (the earlier "16/16" wording was a miscount: the JSON array has 17 entries); local mock tests (unknown never A) pass, also in the remote run |
| B PRODUCTION_PATH_EXECUTED | PASS | for all 7 devices: production `run_pn_junction_iv_sweep` called once, solves = 2 + #voltages (3 for the control), dimension 1, Donors/Acceptors written {0, 1e17} (control {1e16}/{0}), no exception, doping gate not blocked |
| C NUMERICAL_CONVERGENCE_AND_MESH_SENSITIVITY | PASS | all devices converged (finite currents); J(0.6 V) L1 vs L2 5.3e-5; J(-1 V) 4.8e-5; E_max(-1 V) 4.7e-3 (limits 1 % / 2 % / 2 %) |
| D ANALYTICAL_ELECTROSTATICS_COMPARISON | **FAIL** | E_max(0 V) deviates 3.82 % from the depletion approximation (limit 3 %); the other three items pass |
| E APPROXIMATE_SRH_DIFFUSION_REFERENCE_COMPARISON | PASS (comparison level only) | sign right and within 10 % at 0.5 / 0.6 / -0.5 / -1.0 V (5.06 / 1.85 / 2.66 / 2.24 %) |
| F MINORITY_CARRIER_PROFILE_COMPARISON | PASS | hole excess within 0.6 % of the sinh solution at s = 3, 5, 8 um (limit 10 %) |
E passing does not validate PN physics: the 10 % is a first-diagnostic comparison level, the reference is an approximation of unquantified error, and the near-agreement is with one device, one mobility/lifetime model and these biases.

## 1D unit evidence (control, not a production unit)
Uniform N_D = 1e16, x in [-1, 1] um, V = +1 mV on `l`, production path: I(l) = +3.2000000000080e0, I(r) = -3.2000000000077e0; sigma V / L = 3.2000000000048 (sigma 0.6400000000009599 S/cm, L 2e-4 cm); ratio 1.0000000000010 (criterion |ratio - 1| <= 1e-6, KCL 1e-6).
So the raw 1D number equals sigma V / L, i.e. the current per 1 cm^2 cross-section (current density A/cm^2 numerically); DEVSIM exposes no area setting that this batch could find. Production code still reports 1D currents as "unit not established" (`current_unit_metadata(1)` is None); promoting it needs a separate decision.

## Results (raw, reference, relative error; I(l), positive = into the device, forward = positive on the p side)
Reference J_model = J_diff + J_SRH (`pn_reference.py`, independent depletion approximation; the 0.3 V row is reported, not judged):
| V | I_raw L0 | L1 | L2 | J_diff | J_SRH | J_model | rel. err (L2) |
|---|---|---|---|---|---|---|---|
| 0.3 | 2.704234e-05 | 2.691786e-05 | 2.689618e-05 | 9.482e-07 | 2.443e-05 | 2.538066e-05 | 5.97 % (reported) |
| 0.5 | 3.899362e-03 | 3.895850e-03 | 3.895090e-03 | 2.149e-03 | 1.559e-03 | 3.707418e-03 | 5.06 % |
| 0.6 | 1.182396e-01 | 1.182121e-01 | 1.182059e-01 | 1.023e-01 | 1.378e-02 | 1.160606e-01 | 1.85 % |
| -0.5 | -3.387513e-07 | -3.386873e-07 | -3.386731e-07 | -8.79e-12 | -3.299e-07 | -3.298928e-07 | 2.66 % |
| -1.0 | -5.927063e-07 | -5.926779e-07 | -5.926495e-07 | -8.79e-12 | -5.797e-07 | -5.796687e-07 | 2.24 % |
(units: raw number only, not labelled; numerically equal to A per 1 cm^2.) The SRH share of J_model is 96 % / 42 % / 12 % at 0.3 / 0.5 / 0.6 V and ~100 % in reverse. L2 forward points 0.1-0.4 V: 4.03e-7, 3.35e-6, 2.69e-5, 2.52e-4; reverse -0.25 / -0.75: -1.928e-7, -4.708e-7. Terminal sums |I_l + I_r| are consistent to the printed digits (listed, not counted as independent evidence).
Electrostatics (from the solved `ElectricField`): E_max(0 V) L0 / L1 / L2 = 1.0977e5 / 1.1134e5 / 1.1214e5 V/cm vs depletion approximation 1.1658e5 (L2 -3.82 %); E_max(-1 V) 1.6725e5 / 1.6883e5 / 1.6963e5 vs 1.7286e5 (-1.87 %);
W_E (2 int|E|dx / E_max) at 0 V 1.488e-5 cm vs 1.432e-5 (+3.97 %); at -1 V 2.163e-5 vs 2.123e-5 (+1.91 %). Minority holes at 0.6 V, s = 3 / 5 / 8 um: 3.095e12 / 1.285e12 / 3.439e11 vs 3.114e12 / 1.293e12 / 3.459e11 cm^-3.

## D: the failure, kept as is
E_max(0 V) misses the pre-registered 3 % by 0.8 points; no tolerance was changed. It is not a mesh effect: E_max increases monotonically with refinement (L0 -> L2: +2.2 %, steps 1.6e3 then 0.8e3 V/cm), and a Richardson-style extrapolation of those steps (inference, not a run) puts the limit near 1.129e5 V/cm, still ~3.2 % below the approximation.
The residual is therefore best read as the difference between the abrupt depletion approximation and the solved Poisson solution (smooth edge, mobile-carrier tails) at 0 V where the depletion width (0.143 um) is only ~11 Debye lengths (12.6 nm); this attribution was not tested separately (no second solver, no extra run). At -1 V (width 0.212 um) the difference is 1.87 %.

## Scope, limits, not verified
Single 1D symmetric abrupt junction, 1e17 / 1e17, 300 K, constant mobility, SRH tau = 1e-8 s, Boltzmann statistics, ohmic contacts 20 um from the junction, one mesh family, forward <= 0.6 V, reverse >= -1.0 V. Not verified: 2D PN (the 2D step-junction gate stays), other doping, high injection, other lifetimes / mobility models, temperature dependence, the comparison against independent measurements.
The 1D unit is established only numerically by a control on this meshing path; production still labels it "unit not established". The E6J GUI check was not rerun after the unit fix (display strings for 2D unchanged: same unit text, same convention note, now delivered through `current_unit_metadata`).
Remaining consumers with the legacy behaviour (not migrated): `iv_sweep.py`, `cv_sweep.py`, `mosfet_sweep.py`, `vth_extraction.py` still attach the 2D convention note to results without unit metadata; the DC operating-point/electrode result (`tcad_2d_stagewise.py` ~6331-6350) carries no unit metadata and exports with the `unit_unknown` header.

## Changes
Production (all in `tcad/characterization/`): `interface.py` (new `established_current_unit`; `current_unit_metadata(2)` also carries the 2D convention note, other dimensions do not; `BiasPoint` docstring now dimension-independent), `io.py` (`save_csv` header `I_<c>_unit_unknown` when no unit is established), `plotting.py` (axis "Current (unit not established)"),
`pn_junction_iv_sweep.py` / `robust_iv_sweep.py` (docstring and metadata only; the explicit `current_convention` key now comes from `current_unit_metadata` for 2D only). Raw numbers, signs, solver settings, doping mapping, gates, physical parameters, DEVSIM/ViennaPS internals: unchanged.
Tests: `tests/unit/test_current_unit_contract_mock.py` (unknown -> never A; established A allowed), `test_pn_reference_mock.py`, `test_pn_judge_mock.py`, `tests/integration/test_pn_1d_diagnostic_real.py`. Remote profile `e6k_pn_1d_diagnostic`, request `e6k-pn-1d-001`.
Evidence (sha256, first 16 hex): `pn_1d_diagnostic.json` 97e7e4845796b289, `states.npz` 65c1a938a6521a14, `summary.json` b896595d3c984546, `e6k_result.json` c01b92d578aac111; E7A supplement `docs/audits/2026-10-01-e7a-official-material-extraction/SUPPLEMENT_REVIEW.md` (wording only, originals untouched).
