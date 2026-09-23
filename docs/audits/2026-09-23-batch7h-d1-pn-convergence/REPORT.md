# Batch 7H-D1: PN junction support representation and mesh convergence

**Supersedes 7H-D verdict A** (`NONOBTUSE_DEFAULT_SG_DD_VALIDATED`, withdrawn; interim
`NONOBTUSE_DEFAULT_SG_DD_DISCRETELY_CONSISTENT_BUT_NOT_CONVERGED`). 7H-D verdicts C, D, F stand. The 7H-D folder is
preserved unchanged as the historical record (60 files, sha256 re-verified).

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, nothing staged or committed.
Audit only: `tcad/`, `tests/`, `tcad_2d_stagewise.py` unchanged (194 tracked + 110 dirty, sha256 re-verified); all 2091
pre-existing `docs/audits/` files byte-identical, none added or removed outside this folder. Pre-registration
(`data/prereg_sha256.txt`, 10:42:23 UTC, 11 files) re-verified OK. No deviation from the registered solver or
tolerances. Gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` unchanged.

## Verdicts
* **A `NONOBTUSE_DEFAULT_SG_DD_CONVERGENCE_VALIDATED` - PROVISIONAL.** The registered rule returns A. However the
  registered current observable (`get_contact_current`) was shown AFTER the registered runs to be quantized by float64
  resolution of Potential (below); its apparent reference convergence (finest pair 1.7e-8 / 8.4e-8 / 3.5e-3) is a
  quantization coincidence. Substituting the precision-robust junction-crossing current (post-hoc observable, same
  thresholds) M1/M2 D0 still pass. Because that substitution is post hoc, A stands only if Codex accepts it.
* **E `REFERENCE_CURRENT_NOT_CONVERGED` - for the contact-current observable.** Extended 1D levels change the contact
  current by 5.7 % (-0.10 V, h 0.00125 -> 0.000625 um) and 1.4 % (+0.10 V, 0.000625 -> 0.0003125 um); one current
  quantum reaches 25 % of the current. The junction-crossing reference converges (finest-pair change <= 1.4e-4).
* Not selected: B (H5 inconclusive), C (H4 inconclusive), D (H1/H2 inconclusive), F (M1/M2 errors decrease), G.

## Production path facts (Serena + rg)
`tcad/device/devsim/doping_mapping.py:858-872` (`apply_doping_symbolic`, step_junction) and the documented
`apply_doping` form (`:786-792`): `Donors = N_D*step(x - x_j)`, `Acceptors = N_A*step(x_j - x)`, DEVSIM step(0) = 1
(`tcad/physics/dopant_profile.py:134` `_step`, `wafer_state_v2.py:743`). A node exactly on the junction therefore
gets NetDoping = N_D - N_A (0 for a symmetric junction): the J0 representation exists in production. Terminal
currents are read with `get_contact_current` (`semiconductor_equation.py:156-157`
`read_drift_diffusion_terminal_currents`). Not changed.

## J0 stripe (`data/j0_stripe.json`, no solve)
1D: the x = 0 node's NodeVolume is exactly h (0.02, 0.01, 0.005, 0.0025, 0.00125 um), i.e. an intrinsic stripe of
width h, missing N_A h/2 + N_D h/2 (fraction h / 0.5 um of each side's inventory). 7H-D 2D fixtures (h = 0.02 um):
x = 0 CV / domain area M1 1.44 %, M2 2.00 %, M3 2.04 % default / 2.03 % signed, M4 10.4 % default / 0.88 % signed;
signed exact split M3: acceptor 9.73e5, donor 1.05e6 cm^-1 missing (asymmetric).

## J1 / J2 and fixtures (`data/fixtures_d1.json`)
J1: columns +-(2k+1)h/2 and contacts +-0.5 um, strip |x| < h/2 of right triangles. Exact rational clipping of every
signed dual piece near x = 0: 0 nodes whose CV crosses x = 0 on all 12 meshes, so **J2 = J1 exactly** (J2 not run
separately). Zero-doped junction nodes 0; inventory asymmetry 0 (default and signed). M1: 0 obtuse, max 90 deg;
M2: all right; M3: 82 / 230 / 1092 / 3600 obtuse (h 0.02 ... 0.0025), max 114.78 deg, 0 Delaunay and 0 boundary
Gabriel violations, 0 negative signed couples, 0 negative signed node volumes; default sum NV / area 1.052, 1.041,
1.041, 1.037 (does not tend to 1 under refinement).

## 1D reference (registered, `data/analysis_d1.json`)
All J1 solves accepted (`info` converged, final relative update <= 9.7e-11). Potential change vs next level 5.52e-3,
1.45e-3, 3.73e-4, 9.43e-5 V (ratio 3.8-3.95, second order); U_ref_potential 9.43e-5 V; E_peak 1.12127e5 ... 1.12907e5
V/cm; equilibrium qf <= 1.6e-14 V, mass action <= 6.1e-13. **J0 1D: Poisson not accepted at any h** (absolute update
3.5e-17 V, relative oscillating 5.8e-9 / 6.2e-9 at the psi = 0 node for 50 iterations).
Registered contact current J(+0.10 V): 7.867e-8, 2.807e-7, 3.911e-7, 4.0309e-7, 4.0451e-7 A/cm^2.

## Contact-current precision defect (supplementary, `data/diag_precision.json`, `data/diag_ref1d.json`)
Near an ohmic contact the current is majority drift, J = q mu N dpsi/L. Measured contact-edge dpsi: 429 ... 36 ulp
(+0.10 V) and 116 ... 4 ulp (-0.10 V), ulp(0.4173 V) = 5.55e-17 V. The readout moves in quanta q mu N ulp / L that grow
as L shrinks: 0.2 % -> 2.8 % (+0.10 V) and 0.9 % -> 25 % (-0.10 V) of the current from h = 0.02 to 0.0003125 um.
Consequences: identical contact currents on different meshes (e.g. left hole current 4.0274000236741e-7 A/cm^2 at
h = 0.00125 and 0.000625), left/right mismatch up to 0.98 %, and Jn + Jp spread along the device up to +-12 %. The
registered conservation check could not see it: its floor 1e-10 * I_scale = 1.66e-7 A/cm^2 (1D) is of the order of
the currents (a pre-registration weakness).

## Junction-crossing current (supplementary, precision-robust; `data/analysis_junction.json`)
I_junc = sum over edges crossing x = 0 of (Jn + Jp) x couple. 1D successive-change ratios reach 4.39, 4.04, 4.01
(second order); reference (h = 0.0003125 um) 1.146113e-7 / 4.051221e-7 / -9.533054e-8 A/cm^2 at +0.05 / +0.10 / -0.10 V,
finest-pair change 1.28e-4 / 1.36e-4 / 7.4e-5. Signed relative error of I_junc / H vs reference:
| variant | h 0.02 | 0.01 | 0.005 | 0.0025 | decreasing | finest <= 2 % |
|---|---|---|---|---|---|---|
| M1 D0 (+0.10 V) | -0.806 | -0.309 | -0.0404 | -0.0067 | yes (all V) | yes (max 0.67 %) |
| M2 D0 (+0.10 V) | -0.806 | -0.307 | -0.0347 | -0.0032 | yes (all V) | yes (max 0.32 %) |
| M3 D0 (+0.10 V) | -0.810 | -0.332 | -0.0647 | -0.0203 | yes (all V) | no (2.0-2.0 %) |
| M3 D1 (+0.10 V) | -0.807 | -0.307 | -0.0313 | +0.0024 | no at -0.10 V (3.6e-4 -> 2.7e-3) | yes (max 0.28 %) |
M2 equals 1D at the same h to <= 3.8e-9 rel.

## Registered layers (contact-current based; `data/analysis_d1.txt`)
Layer A: M2(h) = 1D(h): |dpsi| <= 5.6e-17 V, |d ln c| <= 5.5e-13, current <= 3.9e-14 rel at every h: pass.
Layer B/C (finest h = 0.0025 um; tol psi 4.71e-4 V, current 2 %):
| variant | e_psi (V) h 0.02 -> 0.0025 | yvar_psi (V) finest | E_peak err | layer C |
|---|---|---|---|---|
| M1 D0 | 7.39e-3, 1.92e-3, 4.68e-4, 9.61e-5 | 8.2e-6 (decreasing) | 6.4e-3 -> 4.0e-5 | pass |
| M2 D0 | 7.33e-3, 1.91e-3, 4.66e-4, 9.43e-5 | <= 2.8e-17 | 6.9e-3 -> 8.1e-5 | pass |
| M3 D0 | 1.05e-2, 1.94e-2, 1.39e-2, 7.96e-3 (ratio 0.57) | 3.95e-3 (4.9, 10.9, 11.5, 3.95 mV: not decreasing) | 0.47 %, 2.35 %, 4.93 %, 4.24 % (not decreasing) | psi fail, I(-0.10 V) fail |
| M3 D1 | 7.59e-3, 1.99e-3, 5.01e-4, 1.04e-4 | 4.2e-5 (decreasing) | 4.6e-3, 3.8e-4, 1.15e-4, 1.41e-4 (not decreasing) | pass |
Every 2D solve accepted (relative update <= 1.0e-10), 11 / 1 / 4-5 Newton iterations; positivity, equilibrium,
qf (<= 1e-6 V) and mass action pass everywhere; M3 D0/D1 contact-current consistency pass at every h.

## Hypotheses (registered rules)
H1 INCONCLUSIVE (J0 solves not accepted; the stripe itself is exactly h wide). H2 INCONCLUSIVE (same).
H3 CONFIRMED by the registered rule (contact-current part invalidated; junction current also passes -> provisional).
H4 INCONCLUSIVE (M3 D0 errors still decrease, ratios 0.57 psi / 0.3-0.7 current; E_peak error 4.2 % and yvar
non-monotone, but no registered failing metric stagnates at >= 0.8). H5 INCONCLUSIVE (E_peak error 1.15e-4 ->
1.41e-4 not strictly decreasing; junction current at -0.10 V crosses zero error).

## Production direction (candidate list only; A is provisional)
Not "validated as the production solution". If Codex accepts the junction-current observable: non-obtuse mesh
invariant with an exact import-time angle check; ViennaPS geometry -> non-obtuse mesh capability; no node on a
doping discontinuity (or an exact conservative split, J2) since production step() writes the J0 form; doping
inventory check; a refinement estimator on psi and on a precision-robust current; and a terminal-current readout that
is not ulp-limited (reason-code candidate `TERMINAL_CURRENT_BELOW_FLOAT64_RESOLUTION`) before any small-current claim.

## Limitations
Contact-current defect found after registration (post-hoc observable); registered conservation floor too loose;
J0 never accepted so H1/H2 undecided; M3 D0 limit (different or slower) undecided within 4 levels; one symmetric
1e17 junction, one region, 300 K, DEVSIM 2.11.0.
