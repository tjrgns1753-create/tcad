# Batch 7H-D pre-registration (fixed BEFORE the first semiconductor solve)

Hashed with `data/fixed_physics.json`, `data/fixtures_7hd.json`, `data/production_sg_path.json`,
`scripts/fixed_physics.py`, `scripts/meshes_7hd.py`, `scripts/build_fixtures_7hd.py`, `scripts/sg_lib.py` in
`data/prereg_sha256.txt` before any `devsim.solve` of this batch. Later findings go to `REPORT.md` only.

## Physics (all values in data/fixed_physics.json)
* T = 300 K; abrupt symmetric PN, N_A = N_D = 1e17 cm^-3, fully ionized; junction at x = 0; p-side x < 0.
* Node exactly at x = 0: NetDoping = 0 (same rule for every mesh and for 1D).
* Domain x in [-0.5, 0.5] um; 2D height H = 0.1 um (2D currents are A/cm of depth; 1D currents A/cm^2;
  comparison I_2D = J_1D * H).
* DEVSIM 2.11.0 SetSiliconParameters values: n_i = 1e10 cm^-3, V_t = 0.025887193 V, eps = 9.8235e-13 F/cm,
  mu_n = 400, mu_p = 200 cm^2/(V s). Production setup_drift_diffusion_equation sets taun = taup = 1e-8 s.
  Constant mobility; SRH recombination/generation only.
* Analytic reference ranges (depletion approximation, sanity only): V_bi = 0.83450 V, W = 0.14316 um
  (x_p = x_n = 0.07158 um), E_peak = 1.1658e5 V/cm, L_D = 0.01261 um; contact potentials -/+0.41725 V;
  majority 1e17, minority 1e3 cm^-3. Quasi-neutral length per side / W = 2.99.
* Equations: registered only by the unmodified production functions setup_semiconductor_potential_equation and
  setup_drift_diffusion_equation (public simple_physics helpers). Contacts left (p) and right (n), ohmic.
* Solver: Poisson abs 1e-10 / rel 1e-10 / 50 it; DD abs 1e30 / rel 1e-10 / 50 it. No change after results.
* Bias on the left (p) contact: forward 0.025, 0.05, 0.075, 0.10 V from the 0 V DD state; reverse on a rebuilt
  device -0.025, -0.05, -0.075, -0.10 V. Recorded targets -0.10, 0, +0.05, +0.10 V.

## Meshes (data/fixtures_7hd.json), dx = dy = 0.02 um, x = 0 column unperturbed in all
| mesh | nodes / tri | acute / right / obtuse | angle range (deg) | Delaunay viol. | boundary Gabriel viol. | signed couple neg / zero / pos (min) | signed node vol. neg (min) | DEVSIM sum NV / area |
|---|---|---|---|---|---|---|---|---|
| M1 non-obtuse irregular | 312 / 510 | 490 / 20 / 0 | 26.57-90.00 | 0 | 0 | 0 / 0 / 821 (5.0e-7 cm) | 0 | 1.000000 |
| M2 right structured | 306 / 500 | 0 / 500 / 0 | 45.00-90.00 | 0 | 0 | 0 / 250 / 555 (0) | 0 | 1.000000 |
| M3 Delaunay + obtuse | 306 / 500 | 226 / 220 / 54 | 21.37-114.44 | 0 | 0 | 0 / 106 / 699 (0) | 0 | 1.041676 |
| M4 non-Delaunay (points of M3) | 306 / 500 | 82 / 6 / 412 | 1.63-176.63 | 246 | 0 | 246 / 0 / 559 (-3.52e-5 cm) | 50 (-2.48e-11 cm^2) | 5.532641 |

M5 is not built: M3 already has zero boundary Gabriel violations and no negative combined signed couple.

## Variants
D0 default; D1 consistent signed (edge couple + node volume + edge-node volume + element couple + element-node
volume, all from DEVSIM-held coordinates); D2 edge/element couple only; D3 volumes only. Negative values are kept.

## Tolerances
As `data/fixed_physics.json` -> spec.tolerances (positivity, equilibrium current 1e-10 * I_scale, conservation,
quasi-Fermi 1e-6 V, mass action 1e-6, M2 identity vs 1D dx = 0.02, agreement 3U + 1e-6, overshoot, block sign).
