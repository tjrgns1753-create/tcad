# Batch 7H-E6B PLAN Rev.2: 0 V Poisson junction-refinement trend on the E6A L3 / L4 / L5 family (audit-only)
(fixed BEFORE any code for this batch is written and BEFORE any DEVSIM execution of this batch; never edited after
results. Rev.2 corrects four defects found in Rev.1 before any execution — see `PLAN_REVISION.md` for the full
before/after record and Rev.1's own hash `50555b7d9eec55515d6183a224fd1c88a783e3249667eeeaf89e1a89ba070cdf`, kept as
history, not deleted.)

Execution location: every DEVSIM import and `devsim.solve` call runs only on a GitHub-hosted Windows runner
(`claude/remote-runner`), under a profile and request that are written only after this PLAN is reviewed. Locally:
reading source, the DEVSIM manual and existing artifacts, and writing documents. No E5 or E6A number is reused as an E6B
result; E6B produces its own solutions.

## 0. Question, maximum verdict, hard limits
Question: on the fixed planar Si wafer (x in [-5, 5] um, y in [-5, 0] um), with a straight step junction at x = 0, the
same contacts and doping, at 0 V, does refining ONLY the junction region (E6A L3 -> L4 -> L5; |x| > 0.2 um identical at
every level) reduce the level-to-level change of the interior Poisson potential and of a fixed-width electric field?

**Maximum verdict: `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY`.** It can never mean 2D continuum convergence, a convergence
order, current accuracy, a biased I-V, production step-junction support, or process-order support. Results that cannot be
separated from solver sensitivity, input problems or the fixed outer mesh get the specific states of section 9, and
anything not decidable is `INCONCLUSIVE`. Unchanged: the gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` (not called,
not bypassed, not reasoned around), 7H-E4 `GEOMETRY_CANDIDATE_ONLY`, 7H-E5 `EQUILIBRIUM_PILOT_ONLY`, 7H-E6A
`GEOMETRY_FAMILY_CANDIDATE_ONLY`. No change to `tcad/`, `tests/`, `tcad_2d_stagewise.py`, DEVSIM / ViennaPS internals,
precision flags, E4 / E5 / E6A PLANs or raw artifacts.

## 1. Equations and existing evidence, traced to source (read directly this session; Serena MCP unavailable, `rg` + reading)

| # | item | source (file:line) | what it establishes for E6B |
|---|---|---|---|
| 1 | E6A inputs | `docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/level_L3.vtu` sha256 `5820d1d27443c0862df3b14634aa0fa8753f20895e2204a650256e98862a1734`; `level_L4.vtu` `85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297`; `level_L5.vtu` `907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70`; `level_L3/4/5.npz` `d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf` / `d274564968f2de0501fb932c474e127d0ae1d38878d66361b3e93add87ece9d4` / `7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee`; `e6a_result.json` `882ed0fbc87f5ede0fcdaacafb5eaffab0d6915aee3b897509e05b8ff30ed3bc`; E6A `PLAN.md` LF `5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba` | 95400 / 255400 / 882600 triangles, 48033 / 128067 / 441733 nodes, single tag 10 (Si), contacts `Si_xmin` / `Si_xmax` 101 nodes each on x = -5 / +5; E6A verdict `GEOMETRY_FAMILY_CANDIDATE_ONLY` (geometry and default NodeVolume only) |
| 2 | L4 = E4 | E6A `level_L4.json` `l4_reproduction.ok = true` (node set, triangle coordinate multiset, tags, boundary, contacts); `level_L4.vtu` sha256 = `candidate_e4.vtu` | L4 is the E4/E5 mesh |
| 3 | node sets nested | read-only check this session on the E6A npz `points_um_f32` (float32 bit patterns): L3 subset of L4 subset of L5; the common set is all 48033 L3 nodes | same-coordinate comparison needs no nearest-node matching and no interpolation (section 3) |
| 4 | element order | E6A `REPORT.md` section 7 (`data/recheck_e6a_local.json`): DEVSIM reorders elements; vertex-set multiset equal. The E6A remote check D2 compared only the element COUNT; multiset equality was shown afterwards by separate local code | E6B checks the multiset fail-closed before any solve (section 6.2) |
| 5 | Poisson model | DEVSIM `python_packages/simple_physics.py:144-186` `CreateSiliconPotentialOnly`: `IntrinsicElectrons = n_i*exp(Potential/V_t)` (:151), `IntrinsicHoles = n_i^2/IntrinsicElectrons` (:152), `IntrinsicCharge = kahan3(IntrinsicHoles, -IntrinsicElectrons, NetDoping)` (:153), `PotentialIntrinsicCharge = -ElectronCharge*IntrinsicCharge` (:154), `ElectricField = (Potential@n0-Potential@n1)*EdgeInverseLength` (:170), `PotentialEdgeFlux = Permittivity*ElectricField` (:171), `equation(node_model=PotentialIntrinsicCharge, edge_model=PotentialEdgeFlux, variable_update="log_damp")` (:178-186) | Boltzmann Poisson; E carries `EdgeInverseLength` only; the flux model contains NO `EdgeCouple`. `PotentialIntrinsicCharge` and `PotentialEdgeFlux` are the REAL models DEVSIM assembles — used directly in section 7's residual, not reconstructed from scratch |
| 6 | integration weights | DEVSIM Manual 2.10.0, "5. Equation and models", 5.2.6 Equation assembly (https://devsim.net/models.html, downloaded 2026-09-28, page sha256 `86c93d23ec2b822b31cd2a5e86b3d3786796158cbfd48f5689d28e9de7f78cc1`): "Node models are integrated with respect to the node volume. Edge models are integrated with the perpendicular bisectors along the edge onto the nodes on either end."; Table 5.2: EdgeCouple "The length of the perpendicular bisector of an element edge. Used to perform surface integration of edge models" | DEVSIM multiplies `PotentialEdgeFlux` by `EdgeCouple` and the charge by `NodeVolume` itself; each exactly once. The manual states WHICH quantities are integrated against WHICH weight, but does not state the per-node SIGN with which an edge's contribution enters node i vs node j, or how a boundary node with no contact equation is numerically treated (section 8 marks both as hypotheses, not manual-confirmed facts). The manual is 2.10.0, the runner has 2.11.0: recorded, not assumed identical beyond this rule |
| 7 | parameters | `simple_physics.py:34-44` (q 1.6e-19, k 1.3806503e-23, eps_0 8.85e-14, eps_si 11.1, n_i 1e10), `:122-141` `SetSiliconParameters` (Permittivity, ElectronCharge, n_i, T, V_t = kT/q) | eps = 9.8235e-13 F/cm, V_t = 0.025887193125 V at 300 K (computed this session from those lines) |
| 8 | contact BC | `simple_physics.py:31-32` (`celec`/`chole`), `:189-253` `CreateSiliconPotentialOnlyContact`, `:211-213` `Potential - bias + ifelse(NetDoping>0, -V_t*log(celec/n_i), V_t*log(chole/n_i))` | Dirichlet-type ohmic contact; the contact value is this formula (7H-E5 ERRATUM 1 D1): read back only, never a convergence or physics metric |
| 9 | setup calls | `tcad/device/devsim/semiconductor_equation.py:50-80` (`SetSiliconParameters` :69, `CreateSiliconPotentialOnly` :70, `{contact}_bias = 0.0` :79, contact :80); production solve `tcad/characterization/pn_junction_iv_sweep.py:89` `solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)` with defaults 1e-6 / 100 (:49-50) | the E5 / production Poisson call, reused unchanged |
| 10 | length units | `tcad/device/devsim/mesh_import.py:989` `points = raw_points * length_scale_to_cm` (float32 array x Python float -> float32, then float64 in DEVSIM) | DEVSIM x, y (cm) = `(P32[:, :2] * 1e-4).astype(float)`, the identity E6A verified node by node |
| 11 | contact names | `mesh_import.py:1051` (axis min/max), `:1067-1068`, `:1074` (min edges -> suffix `xmin`, max -> `xmax`), `:1082` | `Si_xmin` is x = -5 (acceptor side), `Si_xmax` is x = +5. E6B names contacts from coordinates, never from `sorted(contacts)[0]` (the 7H-E5 ERRATUM 1 B2 label swap) |
| 12 | J0 doping rule | current production path: `tcad/device/devsim/doping_mapping.py:677-720` `apply_doping` writes node arrays from `canonical_node_doping()` (:711); the step rule is `tcad/physics/wafer_state_v2.py:758-763` (donor support `[pos, xmax]`, acceptor `[xmin, pos]`, closed, both include x = pos) documented at `:743-744`. `doping_mapping.py:858-869` (`step()` equations, cited by the 7H-E5 PLAN as the production rule) is inside `apply_doping_symbolic`, which `doping_mapping.py:70-75` marks as the OLD writer that no production measurement may call. The DEVSIM manual (https://devsim.net/symdiff.html, sha256 `0d9cc74178d7cb03023331837a148f00f9774117f96ef1e78edd12ae04e9becf`) says only "step(exp1) unit step function" and does not state step(0). Raw evidence: 7H-E1 production capture `prod_arrays.npz` (sha256 `feac96436528b8ecf9f184c4a0fbb44ea25e427cb7467dfc35c7395009eab64f`): all 1601 x = 0 nodes have Donors = Acceptors = 1e18, NetDoping = 0 | J0: the x = 0 node carries both species at full strength, net 0. E6B writes exactly that rule (as 7H-E5 `devices_e5.py:62-75`, J0 branch :71) with `node_model` + `set_node_values`; `apply_doping` is not called (2D ACTIVE step_junction transport is refused there by the gate) |
| 13 | 7H-E5 limits | E5 `ERRATUM_1.md` D1 (contact value = BC identity), D3 (C0/C2 are aggregates); `ERRATUM_2.md` section 1 (DD residual and 1-iteration DD convergence are the algebraic result of `init_from="Intrinsic*"` for ANY potential), section 2 (`qf_dev_V`, `mass_action_dev` = same identity) | none of: contact potential vs V_bi/2, mass action, quasi-Fermi flatness, DD residual or DD iteration count is a metric in E6B |
| 14 | analytic references | Sze & Ng, Physics of Semiconductor Devices, 3rd ed., ch. 2 (abrupt junction, depletion approximation, full ionization, Boltzmann statistics, infinite 1D). Computed this session from row 7's parameters: V_bi = V_t ln(N_A N_D / n_i^2) = 0.953719 V; W(0 V) = sqrt(2 eps V_bi (N_A+N_D) / (q N_A N_D)) = 0.048396 um; L_D = sqrt(eps V_t / (q N)) = 0.003987 um; W / h = 7.74 / 15.49 / 30.97 and L_D / h = 0.638 / 1.276 / 2.552 at L3 / L4 / L5 | scale and direction only. Differences from the model: finite domain with Dirichlet ohmic contacts, carrier tails (ignored by the depletion approximation), J0 node on the junction, DEVSIM's q = 1.6e-19 and eps_si = 11.1. Never used as the exact answer of this discrete 2D problem |

## 2. Why Poisson-only
DD is not solved. By 7H-E5 ERRATUM 2 section 1, after `init_from="Intrinsic*"` every edge current is exactly zero for any
potential array, so a DD solve at 0 V adds no information about the potential; no other DD observable at 0 V is known
that would. Solve calls in this batch are Poisson solves only.

## 3. What is compared, and where (fixed before results) — unified pair notation

* **Common nodes.** C = the 48033 L3 nodes, which also exist bit-identically (float32 construction coordinates) in L4 and
  L5 (section 1 row 3). Every comparison uses the SAME node of each level, located through the E6A `points_um_f32` arrays
  and confirmed by DEVSIM's own x, y after import (section 6.2). No nearest-node matching, no interpolation between 2D
  levels. Contact nodes (x = +-5) are excluded from every comparison metric.
* **Regions** (by construction coordinate): core |x| <= X01 (the float32 0.1 um line; 26433 common nodes, including the
  801 common nodes on x = 0); transition X01 < |x| < X02 (2006); outer |x| >= X02 without contacts (19392). Reported
  separately; only the core enters the trend verdict.
* **Metric definitions.** For any two SOLVED STATES X, Y (a state = one converged or attempted `devsim.solve()` call on
  one device) and a node region R, four metrics are defined, referred to generically as M:
  - `psiLinf(X,Y;R)` = max over i in R of `|psi_X(i) - psi_Y(i)|` (V).
  - `psiL2(X,Y;R)` = `sqrt( sum_i w_i (psi_X(i)-psi_Y(i))^2 / sum_i w_i )` (V), `w_i` = the L3 DEVSIM NodeVolume of node i
    from E6A `level_L3.npz` (the L3 dual areas partition the rectangle exactly, E6A section 4) — the SAME weights for
    every pair and every level, so weighting never changes what is being compared.
  - `ExLinf(X,Y;R)` = max over core x-adjacent common-node segments (i,j) of `|Ex_X(i,j) - Ex_Y(i,j)|` (V/cm), with
    `Ex(i,j) = -(psi(j) - psi(i)) / (x_j - x_i)` in DEVSIM cm, the same physical segment (width h_3 = 0.00625 um in the
    core) compared at every level — never a native edge of one level against a native edge of another.
  - `ExRMS(X,Y;R)` = unweighted RMS of the same over core segments (all core segments have equal length and row
    spacing, so uniform weights equal area weights).
* **Level-pair and control-pair instantiation — THE ONLY NAMES USED FROM HERE ON, replacing Rev.1's inconsistent
  `d_23`/`d_34`/`s_L`/`t_L`:**
  - `D34(M)` = `M(L3-P, L4-P; core)` — same-location difference between the L3 and L4 PRIMARY solves.
  - `D45(M)` = `M(L4-P, L5-P; core)` — same-location difference between the L4 and L5 PRIMARY solves.
  - `S3(M)`, `S4(M)`, `S5(M)` = `M(L<n>-P, L<n>-C; core)` for n = 3, 4, 5 — the change between a level's primary solve
    and its own tighter-tolerance control solve on the SAME mesh (section 7). Called `observed_solver_shift(M, level)`
    everywhere in this PLAN and any future report; it is an OBSERVED quantity, never a proven upper bound on the
    distance between the primary solve and the true discretized solution (DEVSIM's relative-update figure is a
    convergence diagnostic, not an a priori error bound, and quadratic Newton convergence is not assumed — same caution
    already recorded project-wide).
  - The four metrics M are always one of `psiLinf`, `psiL2`, `ExLinf`, `ExRMS`; `D34`, `D45`, `S3`, `S4`, `S5` are always
    written with an explicit metric, e.g. `D34(psiLinf)`.
* **Discriminant inequalities** (operational, pre-registered, used only where section 9 says so):
  `D34(M) > S3(M) + S4(M)`; `D45(M) > S4(M) + S5(M)`; `D34(M) - D45(M) > S3(M) + 2 S4(M) + S5(M)`. Satisfying all three
  supports only the narrow statement "the level-to-level change is larger than the observed solver change, and that
  change shrinks from the (L3,L4) pair to the (L4,L5) pair" — it is never read as proof of convergence to a true
  solution or as an error bound, because `S3`/`S4`/`S5` are themselves observed shifts, not bounds (section 7).
* **Profiles reported:** psi and Ex at the 33 core nodes of the row y = -2.5 um (exact float32 -2.5; 233 common nodes on
  that row, 33 in the core) for each level's P and C states; psi(X01) - psi(-X01) on each common row. DEVSIM's native
  `ElectricField` and its peak are recorded as diagnostics only; native edges of different length are never paired.
* **y-uniformity.** For each common x-line, max - min of psi over its common nodes on the P state; the maximum per
  region is reported. Required only as a consistency condition (section 7), never as proof of correctness.

## 4. Synthetic verification of the D34/D45/S-discriminant (numbers only; no DEVSIM, no ViennaPS)
Illustrative values in volts, chosen only to exercise the discriminant of section 3, not measured from any real solve.
`section 9` names are the verdict-table states this PLAN defines below.

| case | D34 | D45 | S3 | S4 | S5 | D34 > S3+S4 ? | D45 > S4+S5 ? | D34-D45 > S3+2S4+S5 ? | resulting per-metric state (section 9) |
|---|---|---|---|---|---|---|---|---|---|
| (a) clear decrease | 1.0e-3 | 2.0e-4 | 1e-6 | 1e-6 | 1e-6 | yes (1e-3 > 2e-6) | yes (2e-4 > 2e-6) | yes (8e-4 > 4e-6) | trend observed |
| (b) large solver change at L4 | 1.0e-3 | 2.0e-4 | 1e-6 | 5.0e-4 | 1e-6 | yes (1e-3 > 5.01e-4) | no (2e-4 <= 5.01e-4) | n/a (fails above) | `SOLVER_NOISE_INDISTINGUISHABLE` |
| (c) only D45 small | 1.0e-3 | 1.0e-6 | 1e-6 | 1e-6 | 1e-6 | yes | no (1e-6 <= 2e-6) | n/a | `SOLVER_NOISE_INDISTINGUISHABLE` |
| (d) both differences equal | 5.0e-4 | 5.0e-4 | 1e-6 | 1e-6 | 1e-6 | yes | yes | no (0 <= 4e-6) | `NO_REFINEMENT_TREND` |
| (e) L4-C non-convergent, deceptive S4 | 1.0e-3 | 2.0e-4 | 1e-6 | **1e-9 (reported, but L4-C `converged: false`)** | 1e-6 | n/a — not evaluated | n/a — not evaluated | n/a — not evaluated | `SOLVER_CONTROL_INVALID` (overall; section 7 second bullet) |

Case (e) is the required counterexample from item 2: a non-convergent control whose raw potential change happens to be
numerically tiny (1e-9 V) would, if `S4` were accepted at face value, make `D34 > S3+S4` and `D45 > S4+S5` trivially true
and could produce a false `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY`. The fail-closed rule of section 7 blocks this: an
unconverged control makes its level's `S` invalid for ANY use, and the run reports `SOLVER_CONTROL_INVALID`, not a trend
pass, regardless of what the raw numbers happen to be.

## 5. Doping representation, recorded as data (not attributed)
Per level: the Donors / Acceptors / NetDoping values on the x = 0 nodes; sum over x = 0 nodes of NodeVolume, of
Donors x NodeVolume, Acceptors x NodeVolume, NetDoping x NodeVolume; total NodeVolume integrals of Donors and Acceptors next
to the continuum value N x (5 um x 5 um) = 2.5e11 cm^-1 per unit depth. These are raw numbers of the discrete doping
representation; they are not called a sheet charge, and level-to-level potential differences are not attributed to
Poisson spatial discretization alone: what is measured is the change of the whole discrete model (doping representation at
x = 0 + Poisson discretization + nonlinear termination).

## 6. Execution contract
1. **Input identity (fail-closed, before any solve):** the sha256 values of section 1 row 1 (text files LF-normalized, as
   in E6A); this PLAN's LF sha256; the runner's `code_paths_identical_to_review_sha` for `tcad`, `tests`,
   `tcad_2d_stagewise.py`, `examples` against `023bcb90f8b8a0972d6df84f097ca6387f0ab82a`. Any mismatch: `INPUT_IDENTITY_FAIL`,
   0 solves.
2. **Import identity per level (fail-closed, before that level's solve):** import `level_L<L>.vtu` with
   `import_process_result(contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1e-4)`, no refinement. Required:
   node count; x, y equal `(P32[:, :2] * 1e-4).astype(float)` node by node; the vertex-set multiset of
   `get_element_node_list` equals the E6A triangles; NodeVolume bit-equal to E6A `level_L<L>.npz` `NodeVolume`; contacts by
   coordinate (x.min -> `Si_xmin`, x.max -> `Si_xmax`, 101 nodes each). Any failure: `IMPORT_IDENTITY_FAIL` for that
   level, no solve on it.
3. **Device and settings, identical for L3, L4, L5:** J0 doping written as section 1 row 12 (N_A = N_D = 1e18 cm^-3,
   junction x = 0, ACTIVE); `setup_semiconductor_potential_equation(device, "Si", contacts, 300.0)` unmodified; both
   contact biases 0.0 V; initial Potential = DEVSIM's `CreateSolution` default, as in E5; no precision flag set (each level
   in its own process, flags read back and recorded; E5's cross-run flag carry-over cannot occur).
4. **Solve calls (exact list, 10 at most):**

| ID | device | call | purpose |
|---|---|---|---|
| L3-P, L4-P, L5-P | 2D level | `solve(type="dc", absolute_error=1.0, relative_error=1e-6, maximum_iterations=100, info=True)` | primary (E5 / production values, row 9) |
| L3-C, L4-C, L5-C | same device, right after its P | `solve(type="dc", absolute_error=1e-12, relative_error=1e-12, maximum_iterations=10, info=True)` | solver-sensitivity control (section 7) |
| R6-P, R6-C, R7-P, R7-C | 1D reference, section 8 | same two calls | reference and its control |

   Order L3, L4, L5, R6, R7, each level / reference in its own subprocess, `devsim.solve` counted by a wrapper. A C call is
   made only if its P converged. No other solve; no retry with any changed setting; a failed call is recorded with its raw
   `info` result and never hidden.
5. **Resources:** budget 8 GiB peak private bytes, 120 min total. Envelope per level = E6A measured peak (0.180 / 0.428 /
   1.328 GiB) + 2 GiB solver allowance; time = 3 x 0.77 s per Newton iteration per 128067 nodes (7H-E5 D2D Poisson: 7.711 s
   for 10 iterations) x 110 iterations x N_L / 128067 = 95 / 254 / 877 s. Measured gate before L5 exactly as E6A section 5
   (proportional and linear extrapolation of L3 / L4 peaks and times). Hard timeout 3600 s per subprocess. Exceeding either
   budget: `RESOURCE_PREFLIGHT_FAIL`; L5 is never replaced.
6. **Saved raw arrays (npz per level and per reference, sha256 in the result JSON):** x, y, elements, NodeVolume, Donors,
   Acceptors, NetDoping, Potential, IntrinsicElectrons, IntrinsicHoles, `IntrinsicCharge`, `PotentialIntrinsicCharge`
   (node models), edge n0 / n1, EdgeCouple, EdgeLength, native `ElectricField`, `PotentialEdgeFlux` (edge models),
   contact node lists with names; the solve `info` iteration records in JSON. **State discipline (no mixing, section 7):**
   every Potential-derived node/edge model (Potential, IntrinsicElectrons, IntrinsicHoles, IntrinsicCharge,
   PotentialIntrinsicCharge, ElectricField, PotentialEdgeFlux) is queried in ONE batch immediately after a given solve
   call, before any other solve call on that device runs; the P-state batch and the C-state batch (if C ran) are saved
   under distinct keys (`..._after_P`, `..._after_C`) and never combined in one calculation. NetDoping/Donors/Acceptors,
   node coordinates, EdgeCouple, EdgeLength and NodeVolume do not depend on the solve state and are saved once per level.
   Strict JSON (no NaN / Inf; null plus status). Artifact missing, over budget or hash mismatch after download:
   `ARTIFACT_INCOMPLETE`.

## 7. Consistency and solver-sensitivity checks

* **Gauss-law residual, built from DEVSIM's REAL assembled models (not a reconstruction from Donors/Acceptors/Potential).**
  Computed once on the P-state batch of each level (never on a mixed P/C batch, section 6.6). Using
  `PotentialIntrinsicCharge` (node model, section 1 row 5) and `PotentialEdgeFlux` (edge model, section 1 row 5), and
  reading each edge's `node_index@n0` / `node_index@n1` (as 7H-E1 `shadow_e1.py:47-49` already does) to know, for a given
  node i, whether i is that edge's n0 or n1:

  `R_i = sum over edges (i,j) incident to i of sign(i,j) * PotentialEdgeFlux(i,j) * EdgeCouple(i,j) + NodeVolume_i *
  PotentialIntrinsicCharge_i`, where `sign(i,j) = +1` if i is the edge's n0 (outflow, since `PotentialEdgeFlux` is
  positive when `Potential@n0 > Potential@n1`) and `-1` if i is n1 (inflow). **This sign assignment is the hypothesis
  being tested, not a fact confirmed by the DEVSIM manual** (row 6: the manual states which weight integrates which
  model, not the per-node sign) — it will be checked, not assumed, once real per-edge n0/n1 and `PotentialEdgeFlux`
  values exist; the "sign flipped" variant below is exactly its negation.
  `s_i = sum |PotentialEdgeFlux(i,j) * EdgeCouple(i,j)| + |NodeVolume_i * PotentialIntrinsicCharge_i|`.
  Reported: `max_i R_i / s_i` restricted to nodes with `s_i >= 1e-3 * max(s)` (the correct assembly), and the same ratio
  for three wrong variants (EdgeCouple omitted, EdgeCouple applied twice, the node-charge term sign flipped). Also
  reported as a secondary, independent diagnostic: the SAME formula recomputed from separately-queried
  Donors/Acceptors/NetDoping and IntrinsicElectrons/IntrinsicHoles arrays (own `exp()`/subtraction, not DEVSIM's
  `kahan3`), compared against the real `PotentialIntrinsicCharge`/`PotentialEdgeFlux` values — this checks this batch's
  own external reconstruction against DEVSIM's live-evaluated, Kahan-summed models, a floating-point-consistency check,
  not a second physics check.
  **Node-selection bookkeeping (false-green guard):** record `n_selected` (nodes with `s_i >= 1e-3*max(s)`),
  `n_selected_on_x0` (of those, x = 0), `n_selected_on_boundary` (of those, y = 0 or y = -5, non-contact). If
  `n_selected == 0` or `n_selected_on_x0 == 0` or `n_selected_on_boundary == 0`, the result additionally carries
  `ASSEMBLY_RESIDUAL_SELECTION_DEGENERATE` next to whatever ratio was computed, so an empty or non-representative
  selection can never silently read as a clean pass.
  **Status: `ASSEMBLY_RECONSTRUCTION_DIAGNOSTIC_ONLY`, not a hard gate.** Rev.1's thresholds (`max r/s <= 1e-3` for the
  correct assembly, `>= 0.1` for each wrong variant) have no result-independent derivation found this session (no
  citation, no prior-batch number, no analytic bound was located for these specific figures) — they are reported as
  observations, kept in section 9 as a diagnostic field, and NEVER used to declare `CONSISTENCY_FAIL`, `CONSISTENCY_PASS`,
  or any overall physics approval. If a future batch derives a real bound (e.g. from DEVSIM's own per-equation
  `absolute_error`/`relative_error` figures already returned by `solve(info=True)`, which were not used for this because
  they are a single scalar per equation, not a per-node quantity comparable to `r_i` without a separate derivation), this
  status may be revisited in a PLAN written before that result.
* **y-uniformity:** max spread <= 1e-6 V in every region (the value 7H-E5 PLAN section 5 inherited from 7H-E1; a
  convention, not derived).
* **Finite values; contacts:** all finite; contact potentials read back next to the section 1 row 8 formula, reported
  only.
* Any failure of the y-uniformity or finite-value checks: `CONSISTENCY_FAIL` for that level (its numbers are kept, not
  used for the trend). The Gauss-law reconstruction check above never triggers `CONSISTENCY_FAIL` and never supports a
  `CONSISTENCY_PASS` declaration — it is diagnostic-only, per the status above.
* **Solver sensitivity / observed_solver_shift.** `S3(M)`, `S4(M)`, `S5(M)` (section 3) for all four metrics. **Fail-closed
  rule, corrected from Rev.1: if `L3-C`, `L4-C` or `L5-C` reports `converged: false`, errors, or produces no result, that
  level's `S` values are INVALID for every use in section 3's discriminant and section 9's verdict table — the run
  reports `SOLVER_CONTROL_INVALID` for that level and no `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY` is declared for any
  metric that would have needed that level's `S`.** (Rev.1 wrongly allowed `converged = false` to be "recorded but not
  invalidating" — corrected; see `PLAN_REVISION.md` item 2.) The raw P and C results (converged or not) are always kept
  in the artifact. A converged C's `S` is reported under the name `observed_solver_shift` everywhere (never "error",
  "bound", or "tolerance") and its final device relative error is compared against the primary's only to flag
  `SOLVER_CONTROL_INVALID` if the control's own residual is worse than the primary's.

## 8. 1D reference R: observed reference-refinement change and gap to the 2D levels (separate cost, separate verdict; not a floor proof)
Level-to-level (2D-2D) differences cannot by themselves reveal a floor caused by the identical outer mesh (they compare
solutions that share it), so an external 1D reference is used — but the reference only ever supplies OBSERVED
quantities, never an error bound, and its own agreement with L5 is never read as "no floor."

**Physical-equivalence argument — marked CONDITIONAL, not proven.** The doping depends on x only, and both contacts span
the full height with a y-independent value, so a y-independent (1D) potential solves the same discretized equations
PROVIDED the top/bottom (y = 0, y = -5) boundaries impose zero normal flux. What IS confirmed: no contact equation is
registered on those boundaries, and structurally no mesh edge crosses y = 0 or y = -5 (the domain simply ends there), so
no edge-flux term to outside the domain exists in the assembled equation at those nodes. What is NOT confirmed from the
DEVSIM manual or installed source read this session: an explicit statement that this construction is mathematically
equivalent to an exact homogeneous Neumann condition (as opposed to, e.g., some other default row-scaling at a
reduced-connectivity node). Section 7's Gauss-law reconstruction, even where its ratio is small, does not itself prove
zero normal flux at those nodes — it is diagnostic-only and shares that status here. **The 2D-continuum = 1D-solution
equivalence is therefore labelled `CONDITIONAL`** on this boundary-treatment assumption; no state in this section is
read as validating or invalidating that condition, and no per-node normal-flux measurement outside the domain is
attempted (there is no geometry to measure it on).
* Mesh: the 233 distinct DEVSIM x values (cm) of the L3 node set, each interval split into 2^m equal parts in float64
  (R6: m = 6, 14849 nodes, core spacing 9.8e-5 um; R7: m = 7, 29697 nodes). A new 1D builder takes positions in cm
  (7H-E5 `build_1d`, `devices_e5.py:43-60`, multiplies um by 1e-4 in float64 and would not reproduce the 2D values). Fail
  closed: every 2D x value present bit-exactly among the 1D nodes, node count as planned, else `REFERENCE_1D_UNUSABLE`.
* Same J0 rule, parameters, contacts (named from coordinates), calls R6-P / R6-C / R7-P / R7-C. Units: potentials in V
  only ("psiLinf"/"psiL2" restricted to R); no current or flux is compared between 1D and 2D, and `ExLinf`/`ExRMS` are
  never computed for the 1D reference (1D has no independent row structure to fix a physical width against).
* **Fail-closed, corrected from Rev.1 (item 2):** if either `R6-P` or `R7-P` does not converge, or `R6-C` or `R7-C` does
  not converge (when its P did), the 1D reference is `REFERENCE_1D_UNUSABLE`: no floor-related state below is reported,
  and no 2D-vs-1D gap number is computed. The raw 2D level results (section 3, section 9) are NEVER discarded or
  invalidated by a 1D reference failure — they are reported on their own.
* **Observed quantities (all reported, none an error bound):**
  - `A67(psiLinf)`, `A67(psiL2)` = `psiLinf(R6-P, R7-P; common-x)`, `psiL2(R6-P, R7-P; common-x)` — the reference's OWN
    refinement change, named `observed_reference_refinement_change`. R6 and R7 can share common discretization error
    with each other; their mutual closeness is not evidence about the distance to the true continuum solution.
  - `S_R6(M)`, `S_R7(M)` (M in psiLinf, psiL2) = the same `observed_solver_shift` definition as section 3, applied to
    (R6-P, R6-C) and (R7-P, R7-C).
  - `G_L(M)` for L in {3, 4, 5}, M in {psiLinf, psiL2} = `M(L-P, R7-P; region)` at the common non-contact 2D nodes whose
    x-coordinate is one of the 233 reference x-values — the OBSERVED gap between that 2D level and the finer 1D
    reference, named `observed_reference_gap`, reported per region (core / transition / outer).
* **States (per region; replace Rev.1's `FLOOR_NOT_DETECTED`/`FIXED_OUTER_FLOOR_SUSPECTED`/`FLOOR_INCONCLUSIVE`, which
  used `u_ref` as an unproven uncertainty bound):**
  - `REFERENCE_1D_UNUSABLE`: the fail-closed condition above.
  - `REFERENCE_AGREEMENT_OBSERVED`: `G_L5(M) <= A67(M) + S_R7(M)` for both M — the finest 2D level's gap to the finer 1D
    reference is no larger than the reference's own observed refinement change plus its own observed solver shift. This
    states only that the two independently-built discretizations AGREE within their own observed variability; it is
    explicitly NOT a statement that a fixed-outer-mesh floor is absent (R6/R7's shared discretization error, and the
    CONDITIONAL boundary equivalence above, are exactly what this cannot rule out).
  - `OUTER_FLOOR_SUSPECTED`: `D34(M)` and `D45(M)` (section 3, 2D-2D) both exceed their own noise threshold (i.e. a
    genuine 2D-2D refinement trend per section 9) WHILE `G_L4(M)` and `G_L5(M)` do NOT shrink from L4 to L5 by more than
    `S_R7(M)` — i.e. the 2D levels keep changing relative to each other but stop approaching the 1D reference. Reported
    as a candidate signal for EITHER the fixed outer 2D grid OR a genuine 2D/1D model or boundary-treatment difference
    (the CONDITIONAL item above) — the cause is never narrowed to "fixed outer grid" alone.
  - `REFERENCE_INCONCLUSIVE`: any other combination, including when `A67(M)` or `S_R6(M)`/`S_R7(M)` is itself comparable
    to or larger than `G_L5(M)` (the reference's own uncertainty swamps the question), or when the 2D-2D trend itself is
    `SOLVER_NOISE_INDISTINGUISHABLE` or `NO_REFINEMENT_TREND` (making the outer-grid question moot for this run).
* Cost: 4 solves on <= 29697-node 1D devices, seconds each; included in the 10-call list and budgets of section 6.

## 9. Verdict table (per metric: core psiLinf, core psiL2, core ExLinf, core ExRMS; and overall)

| state | condition |
|---|---|
| `INPUT_IDENTITY_FAIL` / `IMPORT_IDENTITY_FAIL` | section 6.1 / 6.2 |
| `RESOURCE_PREFLIGHT_FAIL` | section 6.5 |
| `POISSON_NOT_CONVERGED` | any of L3-P, L4-P, L5-P reports converged = false (raw residual history kept) |
| `CONSISTENCY_FAIL` | section 7 (y-uniformity or finiteness only — the Gauss-law check is diagnostic-only, never gates this) |
| `SOLVER_CONTROL_INVALID` | any of L3-C, L4-C, L5-C non-convergent/errored/missing (section 7); that level's metrics are not classified below |
| `SOLVER_NOISE_INDISTINGUISHABLE` (per metric) | `D34(M) <= S3(M)+S4(M)` or `D45(M) <= S4(M)+S5(M)` |
| `NO_REFINEMENT_TREND` (per metric) | both exceed noise, and `D34(M) - D45(M) <= S3(M) + 2 S4(M) + S5(M)` |
| trend observed (per metric) | both exceed noise, and `D34(M) - D45(M) > S3(M) + 2 S4(M) + S5(M)` |
| `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY` (overall) | no failure state above for any level, and trend observed in all four core metrics |
| `INCONCLUSIVE` (overall) | any other combination (e.g. metrics disagree) |
| `ARTIFACT_INCOMPLETE` | section 6.6 |

Always attached, not part of the trend verdict: `L3_BELOW_DEBYE_SCALE` (`L_D / h_3` = 0.638, a priori: L3 does not
resolve the Debye length, so `D34` may be dominated by L3 under-resolution); the reference states of section 8 (`
REFERENCE_1D_UNUSABLE` / `REFERENCE_AGREEMENT_OBSERVED` / `OUTER_FLOOR_SUSPECTED` / `REFERENCE_INCONCLUSIVE`); the
Gauss-law reconstruction diagnostic and its `ASSEMBLY_RESIDUAL_SELECTION_DEGENERATE` flag if triggered; the raw ratio
`D34(M) / D45(M)` as an observed number with no convergence order inferred from three levels. No tolerance, weight,
region or criterion is added or changed after results are seen.

## 10. Known hygiene item, not a physics or geometry failure
`git diff --check` on the E6A evidence commit `3292ab9d` returns rc 2 in both git configurations, only for E6A's
`level_L3/L4/L5.vtu` (29 flagged lines each: CRLF line endings of meshio's XML header as written on the runner). These are
`-text`, hash-pinned raw artifacts; E6B reads them by sha256 and never rewrites them.
