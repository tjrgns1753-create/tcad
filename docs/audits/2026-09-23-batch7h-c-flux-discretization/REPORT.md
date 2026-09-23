# Batch 7H-C: DEVSIM flux discretization on obtuse meshes and public-API correction capability

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, nothing staged or committed.
Audit only: no change to `tcad/`, `tests/` or `tcad_2d_stagewise.py`; all 1982 pre-existing `docs/audits/` files
byte-identical. Pre-registration (`REPORT_DRAFT.md`, `data/fixtures_7hc.json`, `scripts/meshes.py`,
`scripts/build_fixtures.py`, addendum `scripts/interface_fixture.py`, `data/fixture_IF4.json`) hashed before the
first registered solve and re-verified unchanged. One disclosed deviation: solver stopping rule
(`DEVIATIONS.md`).

**Verdict: A. FLUX_ERROR_MECHANISM_CONFIRMED_AND_PUBLIC_OVERRIDE_PROVEN (scope: linear Laplace / Ohmic /
Poisson on controlled fixtures), together with D. CURRENT_PRODUCTION_DOUBLE_EDGECOUPLE_CONFIRMED (skeleton path
`tcad/device/devsim/solve.py::run_basic_potential_solve` only).** No production change. Gate unchanged.

## Findings

1. **Assembly contract confirmed by the assembled matrix** (`get_matrix_and_rhs`): an edge model F is assembled
   with weight EdgeCouple. E1 `(V0-V1)*EdgeInverseLength` gives w = EdgeCouple/EdgeLength (max rel dev 2.6e-16);
   E2 `(V0-V1)*EdgeCouple` gives w = EdgeCouple^2 exactly (rel dev 0) on all 7 meshes.
2. **Production `run_basic_potential_solve` (called unmodified)** assembles w = EdgeCouple^2 on M1-M4 (rel dev 0).
   On the non-obtuse M1 its potential deviates from phi = x/L by 2.22e-2 V (E1: 1.1e-16 V). It is called only by
   `tests/integration/test_phase5_devsim_real.py:73`; the semiconductor, MOS, MOSFET and resistor paths use the
   E1 form (official `simple_physics` helpers and `resistor_equation.py`).
3. **Flux error on obtuse triangles** (E1, sigma = 1 S/cm, dV = 1 V, analytic I = 0.5 A/cm of depth):
   M1/M2 exact (phi error <= 1.1e-16 V, I error <= 4.4e-16 rel); M3 (Delaunay, 7 obtuse) I = 0.523059 A/cm
   (+4.61 %), phi Linf 3.29e-2 V; M4 (32 non-Delaunay edges) I = 0.701526 A/cm (+40.3 %), phi Linf 4.79e-2 V.
   Mirror/rot180/scale2 controls: identical current (spread 3.2e-16 rel). The interior residual at the analytic
   potential equals sum_j (w_abs - w_signed)(phi_i - phi_j) to <= 7.8e-16 (prediction P3).
4. **Poisson** (phi = (x^2+y^2)/l^2): source part of the residual = Z*NodeVolume (<= 1.8e-14 rel); total residual
   = the linear-precision defect prediction P5 (<= 2.3e-15). Error: M1/M2 4.4e-16 V; M3 0.117 V; M4 0.225 V (of 5 V).
5. **Public override**: all seven documented parameters take effect in Cartesian 2D (x2 models double the
   current or the source). A signed circumcentric `edge_couple_model` (edge_solution + set_edge_values) makes
   Laplace/Ohmic exact on M3, M4, mirror, scale2, the two-region interface fixture IF4 and the element-edge path
   (signed `element_edge_couple_model`), with contact current exactly 0.5 A/cm; `simple_physics`
   CreateSiliconPotentialOnly's Jacobian uses the override (w/eps = signed C/L, 2.9e-16). Poisson becomes exact only
   when BOTH signed edge couple and signed node volume are used (M3, M4: 4.4e-16 V); either alone is not
   (0.022 / 0.136 V on M3).
6. **L3** (7H-A mesh regenerated read-only, hash + flip history identical): E1 Ohmic current error +6.76 % before
   flip, +3.07 % after; phi Linf 5.57e-2 / 1.44e-2 V; 100 % of the residual on obtuse-incident nodes, concentrated in
   the ring zone. Signed edge-couple override: exact (1.1e-16 V, I = 0.5 A/cm). E2: phi error 0.44 V.

## Scope limits

Not tested: drift-diffusion / Scharfetter-Gummel (excluded by the prompt), contact node-current/charge models,
time terms, interface with volume sources, negative signed node volumes (none occurred in M3/M4), and the
consequence of NEGATIVE signed edge couples (32 in M4, 75 in L3 before, 6 boundary edges in L3 after) for
nonlinear or SG discretizations. The override values are computed in Python from DEVSIM-held coordinates;
production integration was not attempted.
