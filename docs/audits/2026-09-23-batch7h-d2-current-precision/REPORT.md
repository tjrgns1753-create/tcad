# Batch 7H-D2: DEVSIM contact-current precision and junction-cut current verification

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, nothing staged or committed.
Audit only: `tcad/`, `tests/`, `tcad_2d_stagewise.py` unchanged (194 tracked + 110 dirty, sha256 re-verified);
2158 pre-existing `docs/audits/` files byte-identical (7H-D / 7H-D1: 127 files), none added or removed outside this
folder. Pre-registration `data/prereg_sha256.txt` (12:23:13 UTC, 10 files) re-verified OK. 86/86 registered runs
completed, every solve accepted (`info` converged, relative update < 1e-10). Gate unchanged.
Carried in: 7H-D1 verdict A PROVISIONAL; float64 cause `HYPOTHESIS_SUPPORTED_BY_ULP_CORRELATION`.

## Verdicts (scope: symmetric abrupt 1e17 cm^-3 PN, one region, 300 K, DEVSIM 2.11.0 Windows x64)
* **Float64 cause CONFIRMED by controlled intervention, jointly in model evaluation + equation assembly.**
  Registered rule: no single flag restores, P4 restores -> "float64 causal, single-flag attribution INCONCLUSIVE".
  Supplementary pairs (1D, `data/diag_pairs.json`): model+equation restores exactly at h 0.005/0.00125/0.0003125 um;
  model+solver and equation+solver do not; P3 (solver alone) is bit-identical to P0. So
  `FLOAT64_MODEL_CANCELLATION_CONFIRMED` + `FLOAT64_EQUATION_ASSEMBLY_CONFIRMED` hold jointly (neither alone);
  `FLOAT64_SOLVER_PRECISION_CONFIRMED` is not supported.
* **`INTERIOR_CUT_CURRENT_CERTIFIED` in P4 - conditional.** Registered result is INCONCLUSIVE only because the mirror
  mutation failed; that failure is a worker bug (below). With the corrected bias pairing every P4 check passes.
* Not selected: `NONOBTUSE_DEFAULT_SG_DD_CONVERGENCE_VALIDATED` (M1 finest e_psi 3.031e-5 V > 2.975e-5 V),
  `SIGNED_OVERRIDE_CONVERGENCE_VALIDATED_...` (same criterion, 3.244e-5 V), `TERMINAL_CURRENT_REMAINS_NUMERICALLY_UNRESOLVED`
  (P4 restores it; it remains unresolved in the default P0 mode production uses).

## Official capability (`data/manual/solver.txt` section 9.3, `data/devsim_info.txt`)
`get_parameter("info")`: version 2.11.0, extended_precision true, direct_solver mkl_pardiso, math_libraries
mkl_rt.3.dll. Manual: extended precision on all binaries; Windows x64 uses boost `cpp_bin_float_quad`; flags
`extended_solver` (Newton/linear solver matrix), `extended_model` (model evaluation), `extended_equation` (equation
assembly), set globally with `set_parameter(name=..., value=True)`; default geometric models also extended;
kahan3/kahan4 use Kahan summation in extended_model mode. No statement on Bernoulli under extended precision found.
Flags are unset by default ("Cannot find parameter"); every run read them back at start (unset), after setting and at
the end.

## Production current path (Serena + rg)
`read_drift_diffusion_terminal_currents` `tcad/device/devsim/semiconductor_equation.py:138-159`: get_contact_current
(ECE) + (HCE) per contact (`:156-158`); callers `pn_junction_iv_sweep.py:102`, `robust_iv_sweep.py:284`,
`mosfet_sweep.py:190`, `:296`; GUI shows `point.currents[...]` at `tcad_2d_stagewise.py:5936-5959`. Contact equations
(`simple_physics.CreateSiliconDriftDiffusionAtContact`) integrate `edge_current_model` ElectronCurrent / HoleCurrent.
No `extended_*` anywhere in `tcad/`, `tests/`, `tcad_2d_stagewise.py` (rg rc=1): production runs P0.

## Mechanism (DEVSIM-evaluated edge models, `data/ulp_cancellation_summary.txt`)
At the contact edges the three SG kahan3 terms exceed the net current by 1.3e13-1.2e14 (1D h 0.00125-0.0003125 um);
x float64 eps 1.1e-16 -> 1.5e-3-1.3e-2 relative, the size of the observed left/right mismatch (2.4e-3-1.3e-2 in P0).
At the junction cut the ratio is 7e5-2e7 (error ~1e-10). Contact dpsi is 4-143 ulp. In P4 (and P12) DEVSIM's own
`Potential@n0-Potential@n1` edge model differs from the double difference of the returned node values by up to 7 %,
i.e. the solution is carried beyond double internally; in P0-P3 the difference is exactly 0.

## P0-P4 (worst over all runs and biased points)
| P | left/right mismatch | 5-cut spread | contact vs cut(0) | C3 total |
|---|---|---|---|---|
| P0 | 1.3e-2 | 9.7e-2 | 4.6e-2 | 1.9e-1 |
| P1 model | 1.2e-2 | 5.4e-2 | 6.9e-2 | 4.4e-2 |
| P2 equation | 2.0e-1 | 1.1e-1 | 1.9e-1 | 1.9e-1 |
| P3 solver | 1.0e-2 | 1.0e-1 | 4.6e-2 | 1.9e-1 |
| P4 all | 3.2e-16 | 2.6e-16 | 4.8e-16 | 2.6e-16 |
1D contact-current successive changes (h 0.0025 -> 0.0003125): P4 1.01e-9, 2.23e-10, 5.50e-11 (+0.10 V), second
order; P0 1.42e-9, 1.84e-14, 5.68e-9 (quantized). P4 1D reference contact = cut current at h = 0.0003125 um:
-9.533054171e-8, 1.146112922e-7 (+0.05 V), 4.051220715e-7 A/cm^2 - equal to the 7H-D1 P0 junction-cut values to 9
digits. Cost at h = 0.00125 um 2D: P0 87-228 s, P4 344-446 s per run (1.5-5x).

## Junction-cut certification (P4)
5-cut spread <= 2.6e-16; contacts vs cut(0) <= 4.8e-16; C3 (per-species dI vs +-q int U V) <= 3.2e-16 and total
<= 2.6e-16 of |I|; C1 contact reconstruction = C0 with the couple actually assembled (EdgeCouple / OvEdgeCouple);
zero-bias currents <= 1e-6 |I(-0.10 V)|; M2 vs 1D same h <= 1.7e-16. Mirror: `worker_d2` applied `-v` to the p
contact in mirror mode (double sign flip), so the mirror state "C+0.100" is the p contact at -0.10 V. Paired
correctly (`data/mirror_bias_mapping_check.txt`), P4 gives |I_m(-x) + I(x)| / |I| = 0.0 at all 5 cuts and the p-contact
current identical, for 1D and M1 h = 0.005 um (P0: 7e-5 to 7.2e-3). The certification stands if Codex accepts this
re-pairing.

## A / B re-evaluation (P4, reference 1D h = 0.0003125 um; U_ref 7.4e-5 / 1.28e-4 / 1.36e-4; U_psi 5.95e-6 V)
| variant | e_psi (V) h 0.02 / 0.005 / 0.00125 | max current error all cuts | finest e_psi <= 2.975e-5 V |
|---|---|---|---|
| M2 D0 | 7.358e-3, 4.948e-4, 2.964e-5 | 0.808, 0.0347, 6.87e-4 | pass |
| M1 D0 | 7.416e-3, 4.971e-4, 3.031e-5 | 0.809, 0.0404, 1.13e-3 | **fail (1.9 %)** |
| M3 D1 | 7.616e-3, 5.291e-4, 3.244e-5 | 0.810, 0.0313, 2.00e-3 | **fail (9 %)** |
Every other registered check passes for all three (decreasing e_psi, e_logc, every cut current; spread; positivity;
qf 5.6e-17 V; mass action 2.2e-16; zero bias; Newton; E_peak and y-variation decreasing for M3 D1). The failing
criterion is structurally marginal: with e ~ C h^2, e(0.00125) / U_psi = 0.00125^2 / (0.000625^2 - 0.0003125^2) = 5.33,
so 5 U_psi is below the expected second-order error of a grid 4x coarser than the reference (M2 = 1D at the same h
gives 4.98). Pre-registration weakness; not changed after the fact.
M3 D1 -0.10 V sign crossing (cut 0): +0.603, -3.57e-4, -2.66e-3 (h 0.0025), -3.03e-4; P0 and P4 agree to 1e-10 ->
not precision noise; magnitude falls from h 0.0025 to 0.00125 -> spatial discretization error crossing zero, no
sign of an override defect (+0.10 V likewise -0.807, -0.0313, +2.0e-3).

## Production impact (proposal only)
Case A: `extended_model` + `extended_equation` restore the terminal current; `extended_solver` is not needed
(1D evidence); cost 1.5-5x in 2D. A capability check could read `get_parameter("info")["extended_precision"]` and the
two flags back, pinned to DEVSIM 2.11.0; without it, terminal currents whose contact-edge cancellation ratio x 1.1e-16
exceeds the required accuracy should fail closed (reason-code candidate `TERMINAL_CURRENT_BELOW_NUMERIC_RESOLUTION`).
Not implemented.

## Limitations
Pairs tested in 1D only; mirror check needed a post-hoc bias re-pairing; A/B finest-potential tolerance structurally
marginal; one doping case, one region; runs folder 181 MB (2D states stored).
