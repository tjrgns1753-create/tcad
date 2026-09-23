# Batch 7H-D1 pre-registration (fixed BEFORE the first registered semiconductor solve)

**7H-D verdict A (`NONOBTUSE_DEFAULT_SG_DD_VALIDATED`) is withdrawn pending this re-verification**; interim status
`NONOBTUSE_DEFAULT_SG_DD_DISCRETELY_CONSISTENT_BUT_NOT_CONVERGED`. 7H-D verdicts C, D, F stand. The 7H-D report
(`docs/audits/2026-09-23-batch7h-d-sg-pn-mesh-validity/`) is preserved unchanged as the historical record.

Hashed in `data/prereg_sha256.txt` together with `data/fixed_d1.json`, `data/fixtures_d1.json`,
`data/j0_stripe.json`, `data/solver_smoke_pre_registration.txt` and every script in `scripts/`.

## Disclosed before registration
* Solver-mechanics smoke test (`data/solver_smoke_pre_registration.txt`): one J1 1D h = 0.02 um Poisson + 0 V DD
  solve to learn the `info=True` structure and whether relative update 1e-10 is reachable (it reached 1.4e-12 and
  1.2e-12). No comparison metric was computed from it.
* J0 stripe quantification and all fixture geometry (no solve).

## Physics, runs, solver, tolerances, hypotheses, verdict rules
Exactly as in `data/fixed_d1.json`. Summary: 7H-D physics unchanged; J1 junction (no node on x = 0, nearest
columns +-h/2, dual boundary exactly on x = 0, verified in exact arithmetic, so J2 = J1 on every fixture);
1D J1 and J0 at h = 0.02, 0.01, 0.005, 0.0025, 0.00125 um; 2D M1 D0, M2 D0, M3 D0, M3 D1 at h = 0.02, 0.01,
0.005, 0.0025 um; solver rel 1e-10 with `info=True` acceptance; layer A same-h identity (1e-9 V, 1e-9 log, 1e-8 rel
current); layer B strictly decreasing over >= 3 consecutive levels or at floor; layer C finest agreement
psi <= max(5 U_ref, 1e-6 V), current <= max(5 U_ref, 2 %), current approval only if U_ref_current <= 1 %.

## Fixtures (`data/fixtures_d1.json`)
| mesh | nodes / tri (h = 0.02 / 0.01 / 0.005 / 0.0025) | obtuse | max angle | Delaunay / Gabriel viol. | neg. signed couple / NV | x = 0 nodes | inventory asym. | default sum NV / area |
|---|---|---|---|---|---|---|---|---|
| M1 | 312/510, 1122/2020, 4242/8040, 16482/32080 | 0 | 90.00 | 0 / 0 | 0 / 0 | 0 | 0 | 1.000000 |
| M2 | same counts | 0 (all right) | 90.00 | 0 / 0 | 0 / 0 | 0 | 0 | 1.000000 |
| M3 | same counts | 82, 230, 1092, 3600 | 114.78 | 0 / 0 | 0 / 0 | 0 | 0 | 1.0521, 1.0408, 1.0413, 1.0366 |
J2 exact check: 0 nodes whose signed CV crosses x = 0 on all 12 meshes -> `J2 == J1` (J2 not run separately).

## J0 stripe (`data/j0_stripe.json`, no solve)
1D: one x = 0 node, NodeVolume = h exactly (0.02 ... 0.00125 um); zero-doped fraction of the domain = h / 1 um;
missing acceptor = missing donor = NA h / 2. 7H-D 2D fixtures (h = 0.02 um): x = 0 CV area / domain area
M1 1.44 %, M2 2.00 %, M3 2.04 % (default) / 2.03 % (signed), M4 10.4 % (default) / 0.88 % (signed).
