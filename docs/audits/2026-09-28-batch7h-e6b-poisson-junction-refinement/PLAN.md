# Batch 7H-E6B PLAN: 0 V Poisson junction-refinement trend on the E6A L3 / L4 / L5 family (audit-only)
(fixed BEFORE any code for this batch is written and BEFORE any DEVSIM execution of this batch; never edited after results)

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
separated from solver sensitivity, input problems or the fixed outer mesh get the specific states of section 8, and
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
| 4 | element order | E6A `REPORT.md` section 7 (`data/recheck_e6a_local.json`): DEVSIM reorders elements; vertex-set multiset equal. The E6A remote check D2 compared only the element COUNT; multiset equality was shown afterwards by separate local code | E6B checks the multiset fail-closed before any solve (section 5.2) |
| 5 | Poisson model | DEVSIM `python_packages/simple_physics.py:144-186` `CreateSiliconPotentialOnly`: `IntrinsicElectrons = n_i*exp(Potential/V_t)` (:151), `IntrinsicHoles = n_i^2/IntrinsicElectrons` (:152), `IntrinsicCharge = kahan3(IntrinsicHoles, -IntrinsicElectrons, NetDoping)` (:153), `PotentialIntrinsicCharge = -ElectronCharge*IntrinsicCharge` (:154), `ElectricField = (Potential@n0-Potential@n1)*EdgeInverseLength` (:170), `PotentialEdgeFlux = Permittivity*ElectricField` (:171), `equation(node_model=PotentialIntrinsicCharge, edge_model=PotentialEdgeFlux, variable_update="log_damp")` (:178-186) | Boltzmann Poisson; E carries `EdgeInverseLength` only; the flux model contains NO `EdgeCouple` |
| 6 | integration weights | DEVSIM Manual 2.10.0, "5. Equation and models", 5.2.6 Equation assembly (https://devsim.net/models.html, downloaded 2026-09-28, page sha256 `86c93d23ec2b822b31cd2a5e86b3d3786796158cbfd48f5689d28e9de7f78cc1`): "Node models are integrated with respect to the node volume. Edge models are integrated with the perpendicular bisectors along the edge onto the nodes on either end."; Table 5.2: EdgeCouple "The length of the perpendicular bisector of an element edge. Used to perform surface integration of edge models" | DEVSIM multiplies `PotentialEdgeFlux` by `EdgeCouple` and the charge by `NodeVolume` itself. Post-processing flux = edge model x EdgeCouple exactly once (as 7H-E1 `shadow_e1.py:50-51` does for currents); E values themselves are never multiplied by EdgeCouple. The manual is 2.10.0, the runner has 2.11.0: recorded, not assumed identical beyond this rule |
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

## 3. What is compared, and where (fixed before results)
* **Common nodes.** C = the 48033 L3 nodes, which also exist bit-identically (float32 construction coordinates) in L4 and
  L5 (section 1 row 3). Every comparison uses the SAME node of each level, located through the E6A `points_um_f32` arrays
  and confirmed by DEVSIM's own x, y after import (section 5.2). No nearest-node matching, no interpolation between 2D
  levels. Contact nodes (x = +-5) are excluded from every comparison metric.
* **Regions** (by construction coordinate): core |x| <= X01 (the float32 0.1 um line; 26433 common nodes, including the
  801 common nodes on x = 0); transition X01 < |x| < X02 (2006); outer |x| >= X02 without contacts (19594 - 202 = 19392).
  Reported separately; only the core enters the trend verdict.
* **Potential differences.** For levels a, b: d_ab^inf = max over region of |psi_a - psi_b|; d_ab^2 = sqrt(sum w_i
  (psi_a - psi_b)_i^2 / sum w_i) with w_i = the L3 DEVSIM NodeVolume of node i from E6A `level_L3.npz` (the L3 dual areas
  partition the rectangle exactly, E6A section 4), the same weights for every pair. Pairs: (L3, L4) and (L4, L5).
* **Fixed-width field.** On every common row, for every pair of x-adjacent common nodes (i, j), E_x(i, j) = -(psi_j -
  psi_i) / (x_j - x_i) in V/cm, with x in DEVSIM cm. The segment is the same physical segment at all levels (width
  h_3 = 0.00625 um in the core). f_ab^inf = max |E_x,a - E_x,b| over core segments and f_ab^rms their unweighted RMS (all core
  segments have the same length and row spacing, so uniform weights equal area weights). Named diagnostic: the two segments
  adjacent to x = 0 on the row y = -2.5 um (exact float32 -2.5; 233 common nodes, 33 in the core). DEVSIM's native
  `ElectricField` and its peak are recorded as diagnostics only; native edges of different length are never paired.
* **Profiles reported:** psi and E_x at the 33 core nodes of the row y = -2.5 um for each level; psi(X01) - psi(-X01) on
  each common row.
* **y-uniformity.** For each common x-line, max - min of psi over its common nodes; the maximum per region is reported.
  Required only as a consistency condition (section 6), never as proof of correctness.

## 4. Doping representation, recorded as data (not attributed)
Per level: the Donors / Acceptors / NetDoping values on the x = 0 nodes; sum over x = 0 nodes of NodeVolume, of
Donors x NodeVolume, Acceptors x NodeVolume, NetDoping x NodeVolume; total NodeVolume integrals of Donors and Acceptors next
to the continuum value N x (5 um x 5 um) = 2.5e11 cm^-1 per unit depth. These are raw numbers of the discrete doping
representation; they are not called a sheet charge, and level-to-level potential differences are not attributed to
Poisson spatial discretization alone: what is measured is the change of the whole discrete model (doping representation at
x = 0 + Poisson discretization + nonlinear termination).

## 5. Execution contract
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
| L3-C, L4-C, L5-C | same device, right after its P | `solve(type="dc", absolute_error=1e-12, relative_error=1e-12, maximum_iterations=10, info=True)` | solver-sensitivity control (section 6) |
| R6-P, R6-C, R7-P, R7-C | 1D reference, section 7 | same two calls | reference and its control |

   Order L3, L4, L5, R6, R7, each level / reference in its own subprocess, `devsim.solve` counted by a wrapper. A C call is
   made only if its P converged. No other solve; no retry with any changed setting; a failed call is recorded with its raw
   `info` result and never hidden.
5. **Resources:** budget 8 GiB peak private bytes, 120 min total. Envelope per level = E6A measured peak (0.180 / 0.428 /
   1.328 GiB) + 2 GiB solver allowance; time = 3 x 0.77 s per Newton iteration per 128067 nodes (7H-E5 D2D Poisson: 7.711 s
   for 10 iterations) x 110 iterations x N_L / 128067 = 95 / 254 / 877 s. Measured gate before L5 exactly as E6A section 5
   (proportional and linear extrapolation of L3 / L4 peaks and times). Hard timeout 3600 s per subprocess. Exceeding either
   budget: `RESOURCE_PREFLIGHT_FAIL`; L5 is never replaced.
6. **Saved raw arrays (npz per level and per reference, sha256 in the result JSON):** x, y, elements, NodeVolume, Donors,
   Acceptors, NetDoping, Potential after P, Potential after C, IntrinsicElectrons, IntrinsicHoles, edge n0 / n1,
   EdgeCouple, EdgeLength, native ElectricField, contact node lists with names; the solve `info` iteration records in JSON.
   Strict JSON (no NaN / Inf; null plus status). Artifact missing, over budget or hash mismatch after download:
   `ARTIFACT_INCOMPLETE`.

## 6. Consistency and solver-sensitivity checks
* **Gauss-law residual (sign, units, single EdgeCouple).** At every non-contact node i, independent of DEVSIM's edge sign
  convention: r_i = sum over incident edges ij of eps (psi_i - psi_j) / L_ij x EC_ij - q (p_i - n_i + NetDoping_i) x NV_i,
  with n, p from rows 5 / 7 (C/cm per unit depth in 2D). Scale s_i = sum |eps (psi_i - psi_j) / L_ij x EC_ij| + |q (p_i -
  n_i + NetDoping_i) NV_i|; evaluated where s_i >= 1e-3 max s. Also computed with EdgeCouple omitted and applied twice, and
  with the charge sign flipped. Pre-registered as a discriminator of weight / sign / unit errors, not as an accuracy
  measure: pass if max r_i / s_i <= 1e-3 with EdgeCouple once, and each of the three wrong variants gives max r_i / s_i >= 0.1.
  Boundary nodes on y = 0 and y = -5 are included: a nonzero hidden boundary flux would show there (section 7 relies on
  zero normal flux).
* **y-uniformity:** max spread <= 1e-6 V in every region (the value 7H-E5 PLAN section 5 inherited from 7H-E1; a convention,
  not derived).
* **Finite values; contacts:** all finite; contact potentials read back next to the section 1 row 8 formula, reported only.
* Any failure above: `CONSISTENCY_FAIL` for that level (its numbers are kept, not used for the trend).
* **Solver sensitivity.** s_L^inf, s_L^2 = max and L2 (weights of section 3) of |psi_C - psi_P| over the region on level L;
  t_L = the same for E_x. This is an empirical sensitivity of the primary state to further Newton iterations, in volts; it
  is not an error bound (a DEVSIM relative update is never read as a potential error, and quadratic convergence is not
  assumed). The control is `SOLVER_CONTROL_INVALID` if it errors, gives non-finite values, or its final device
  relative error exceeds the primary's; converged = false alone is recorded but not invalidating.

## 7. Fixed-outer-mesh floor: 1D reference R (separate cost, separate verdict)
Level-to-level differences cannot reveal a floor caused by the identical outer mesh (they compare solutions that share
it). An external reference is needed. Physics basis, stated as reasoning: the doping depends on x only; both contacts span
the full height with a y-independent value; the top / bottom boundaries carry no contact equation, so the finite-volume
balance has no flux term there (zero normal flux; checked by section 6's residual at those nodes); the equilibrium
Poisson operator with Boltzmann carriers is strictly monotone, so its solution is unique. Hence the continuum 2D solution is
the 1D solution psi(x). R is therefore a reference for THIS problem's continuum solution, subject to its own
discretization error; it is never called the exact answer.
* Mesh: the 233 distinct DEVSIM x values (cm) of the L3 node set, each interval split into 2^m equal parts in float64
  (R6: m = 6, 14849 nodes, core spacing 9.8e-5 um; R7: m = 7, 29697 nodes). A new 1D builder takes positions in cm
  (7H-E5 `build_1d`, `devices_e5.py:43-60`, multiplies um by 1e-4 in float64 and would not reproduce the 2D values). Fail
  closed: every 2D x value present bit-exactly among the 1D nodes, node count as planned, else `REFERENCE_1D_UNUSABLE`.
* Same J0 rule, parameters, contacts (named from coordinates), calls R6-P / R6-C / R7-P / R7-C. Units: potentials in V
  only; no current or flux is compared between 1D and 2D.
* u_ref = max |psi_R6 - psi_R7| at the 233 x values + the R7 control change.
* e_L = psi_L(i) - psi_R7(x_i) at the common non-contact nodes; E_L = its max per region.
* Floor states per region: `FLOOR_NOT_DETECTED` if E_L3 - E_L4 > s_3 + s_4 + 2 u_ref and E_L4 - E_L5 > s_4 + s_5 + 2 u_ref;
  `FIXED_OUTER_FLOOR_SUSPECTED` if E_L4 - E_L5 <= s_4 + s_5 + 2 u_ref while E_L5 > s_5 + u_ref; otherwise
  `FLOOR_INCONCLUSIVE`. (A change between two such values is taken as resolved only when it exceeds the sum of the
  uncertainties of both terms.)
* Cost: 4 solves on <= 29697-node 1D devices, seconds each; included in the 10-call list and budgets.

## 8. Verdict table (per metric: core psi^inf, core psi^2, core E_x^inf, core E_x^rms; and overall)

| state | condition |
|---|---|
| `INPUT_IDENTITY_FAIL` / `IMPORT_IDENTITY_FAIL` | section 5.1 / 5.2 |
| `RESOURCE_PREFLIGHT_FAIL` | section 5.5 |
| `POISSON_NOT_CONVERGED` | any of L3-P, L4-P, L5-P reports converged = false (raw residual history kept) |
| `CONSISTENCY_FAIL` | section 6 |
| `SOLVER_CONTROL_INVALID` | section 6 |
| `SOLVER_NOISE_INDISTINGUISHABLE` | d_34 <= s_4 + s_5 or d_23 <= s_3 + s_4 (per metric; t for E_x) |
| `NO_REFINEMENT_TREND` | both d exceed noise, and d_34 >= d_23 - (s_3 + 2 s_4 + s_5) |
| trend observed (metric) | both d exceed noise, and d_23 - d_34 > s_3 + 2 s_4 + s_5 |
| `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY` (overall) | no failure state above, and trend observed in all four core metrics |
| `INCONCLUSIVE` | any other combination (e.g. metrics disagree) |
| `ARTIFACT_INCOMPLETE` | section 5.6 |

Always attached, not verdicts: `L3_BELOW_DEBYE_SCALE` (L_D / h_3 = 0.638, a priori: L3 does not resolve the Debye
length, so the (L3, L4) difference may be dominated by L3 under-resolution); the floor state of section 7; the ratio
d_23 / d_34 as an observed number with no convergence order inferred from three levels. No tolerance, weight, region or
criterion is added or changed after results are seen.

## 9. Known hygiene item, not a physics or geometry failure
`git diff --check` on the E6A evidence commit `3292ab9d` returns rc 2 in both git configurations, only for E6A's
`level_L3/L4/L5.vtu` (29 flagged lines each: CRLF line endings of meshio's XML header as written on the runner). These are
`-text`, hash-pinned raw artifacts; E6B reads them by sha256 and never rewrites them.
