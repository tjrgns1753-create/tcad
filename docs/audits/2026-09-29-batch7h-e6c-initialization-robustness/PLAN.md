# Batch 7H-E6C PLAN: initialization robustness of the local junction-refinement change, 0 V Poisson, E6A L3 / L4 / L5 (audit-only)
(fixed BEFORE any code for this batch is written and BEFORE any DEVSIM execution of this batch; never edited after results)

Execution location: every DEVSIM import and `devsim.solve` call runs only on a GitHub-hosted Windows runner
(`claude/remote-runner`), one request. Locally: reading, documents, code writing, synthetic judge tests (no DEVSIM, no ViennaPS).

## 0. Question, maximum verdict, hard limits
Question: on the same L3 / L4 / L5 meshes, J0 doping, Poisson equation, contacts, material parameters, precision setting and
`solve` arguments, do two independent runs that differ ONLY in the initial potential — **P** (DEVSIM's default initial
`Potential`, as in E6B) and **Q** (a linear potential between the two contact values) — both converge, and if so, does the
level-to-level change observed on the P solutions remain larger than the observed P-versus-Q difference, with a decreasing
level-to-level change, for all four core metrics?

**Maximum verdict: `INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY`.** It goes no further than "the observed local
refinement change exceeds the observed initial-condition sensitivity of the converged solutions". It is not a solver-error
bound, not 2D continuum convergence, not PN current / DD / I-V accuracy, not production step-junction support, not a statement
about a 1D reference, floor, oxidation or process order. That two initial states reach the same solution is a statement about
the solver's basin of attraction; it is not evidence that the solution is physically accurate. Unchanged: the gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, 7H-E4 `GEOMETRY_CANDIDATE_ONLY`, 7H-E5 `EQUILIBRIUM_PILOT_ONLY`, 7H-E6A
`GEOMETRY_FAMILY_CANDIDATE_ONLY`, 7H-E6B `SOLVER_CONTROL_INVALID` (its `S3/S4/S5` stay invalid and are never reused or
reclassified; `ERRATUM.md` of E6B narrows one sentence of its report). No change to `tcad/`, `tests/`, `tcad_2d_stagewise.py`,
`examples/`, DEVSIM / ViennaPS internals, E4 / E5 / E6A / E6B raw evidence or PLANs, precision flags.

## 1. Inputs and what they are used for (hash-gated before any solve; a mismatch is `INPUT_IDENTITY_FAIL`, 0 solves)
| input | sha256 | use |
|---|---|---|
| E6A `level_L3.vtu` / `level_L4.vtu` / `level_L5.vtu` (`docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/`) | `5820d1d27443c0862df3b14634aa0fa8753f20895e2204a650256e98862a1734` / `85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297` / `907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70` | the meshes |
| E6A `level_L3.npz` / `level_L4.npz` / `level_L5.npz` | `d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf` / `d274564968f2de0501fb932c474e127d0ae1d38878d66361b3e93add87ece9d4` / `7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee` | construction coordinates (float32), triangles, DEVSIM NodeVolume, edge arrays, x / y; import identity and the common node set |
| E6A `e6a_result.json`, E6A `PLAN.md` (LF) | `882ed0fbc87f5ede0fcdaacafb5eaffab0d6915aee3b897509e05b8ff30ed3bc`, `5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba` | provenance |
| E6B `PLAN.md` (LF) | `6a8d674e3548de32007f90f8a1368f9e2b31835f13d5b54eecc52da041c72e51` | metric / region / weight definitions reused unchanged |
| E6B `level_L3_state_P.npz` / `level_L4_state_P.npz` / `level_L5_state_P.npz` (`docs/audits/2026-09-28-batch7h-e6b-poisson-junction-refinement/data/remote_run_36527372624/outputs/e6b_out/`) | `3c6142d70d8af6893c14eec85f47b86761609acf5d751d0c4c616aadfef120d8` / `54b4987fb1f9637b64d8b2fa8278597b33bebbc3f564e58cdb8d36c542b97971` / `be34ae4a98ceae8b6c9207437df0a66e402fd51ddcc0a38e6139e6b330803d28` | ONLY a separate reproducibility diagnostic (section 5); they never replace E6C's own P or Q |
| E6B `judge_e6b.py` (LF), the reused metric code | `9f37ad88310b6bac19ff13465a50db0127de9c322dd3cf7c41f3edac98e26bb2` | imported read-only |
| production `tcad/` | identical to review SHA `023bcb90f8b8a0972d6df84f097ca6387f0ab82a` for `tcad`, `tests`, `tcad_2d_stagewise.py`, `examples` (`git diff --quiet`) | else `INPUT_IDENTITY_FAIL` |

Equations (source read in E6B section 1 and unchanged here; DEVSIM `python_packages/simple_physics.py:144-186`
`CreateSiliconPotentialOnly`, `:189-213` `CreateSiliconPotentialOnlyContact`; `tcad/device/devsim/semiconductor_equation.py:50-80`;
`tcad/device/devsim/mesh_import.py:989` coordinate scaling): Boltzmann Poisson with the Dirichlet-type ohmic contact
`Potential - bias + ifelse(NetDoping>0, -V_t*log(celec/n_i), V_t*log(chole/n_i)) = 0`, `bias = 0`. The contact potential is a
boundary-formula value and is never used as a convergence or physics metric (7H-E5 ERRATUM 1 D1, 2 section 1).

## 2. The two runs (identical except the initial `Potential`)
* **P:** a freshly imported device in its own process; J0 doping written as in E6B (Donors `1e18` where `x >= 0`, Acceptors `1e18` where
  `x <= 0`, NetDoping their difference; x = 0 carries both, net 0); `setup_semiconductor_potential_equation(device, "Si",
  ["Si_xmin","Si_xmax"], 300.0)`; **no** change to `Potential`; the initial `Potential` array is read back and saved BEFORE the
  solve; then exactly one call `solve(type="dc", absolute_error=1.0, relative_error=1e-6, maximum_iterations=100, info=True)`.
* **Q:** the same, in a different freshly imported device / process, except that after the setup and before the solve the
  `Potential` of every Si node is set with the public `devsim.set_node_values(device, region="Si", name="Potential", values=...)` to
  `V_init(x) = V_left + (V_right - V_left) * (x - x_min) / (x_max - x_min)` evaluated in float64 on the device's own node `x`
  (cm), with `x_min`, `x_max` the extreme node coordinates and
  `V_right = +V_t * ln(celec / n_i)`, `V_left = -V_t * ln(chole / n_i)`, `celec = 1e-10 + 0.5*|N + sqrt(N^2 + 4 n_i^2)|` with
  `N = +1e18`, `chole = 1e-10 + 0.5*|-N + sqrt(N^2 + 4 n_i^2)|` with `N = -1e18` — the contact boundary formula
  (`simple_physics.py:31-32,211-213`) at bias 0 for the doping actually written on the two contact nodes; `V_t`
  and `n_i` are read back from the device (`get_parameter`), not typed. The numerical values (about +-0.4769 V) are read
  from the constructed device, checked to be finite, never adjusted after a result.
* **Initialization contract (`INITIALIZATION_CONTRACT_FAIL`, stop before that Q solve, no workaround):** the `Potential` array
  read back with `get_node_model_values` after `set_node_values` must be bit-equal to the intended float64 array; the node
  coordinates used must equal the device's `x`; the contact-node doping must be `+1e18` at `x_max` and `-1e18` (net) at
  `x_min`; and the intended Q array must differ from P's read-back initial array (at least one node, `max|Q_init - P_init| > 0`),
  else Q would not be an independent initial condition. The verdict never depends on the size of the difference; it is recorded.
* Solve budget: six calls, `{L3, L4, L5} x {P, Q}`, run in the order L3-P, L3-Q, L4-P, L4-Q, L5-P, L5-Q, each in its own
  subprocess, one `devsim.solve` per process, counted by a wrapper. No control solve, no 1D reference, no retry, no change of
  tolerance, iteration limit, precision flag or initial function after a result; a failed call is recorded with its raw `info`.
* Resources: 8 GiB peak private bytes, 120 min total, 3600 s per subprocess. Envelope per level = E6B's measured process peak
  (0.377 / 0.928 / 3.114 GB) + 2 GiB; measured gate before L5 as in E6B PLAN section 6.5 (proportional and linear extrapolation of
  the L3 / L4 P-run peaks and the L4 time). Exceeding it: `RESOURCE_PREFLIGHT_FAIL`, L5 is not replaced.

## 3. Import identity, doping identity (per run, before its solve; failure = `IMPORT_IDENTITY_FAIL`)
As E6B PLAN 6.2: node count; node `x, y` equal `(P32[:, :2] * 1e-4).astype(float)` node by node; the vertex-set multiset of
`get_element_node_list` equals the E6A triangles (the multiset itself, not the count); NodeVolume bit-equal to E6A; region `["Si"]`;
contacts `Si_xmin` / `Si_xmax` by coordinate (x.min, x.max), 101 nodes each. Doping: the x = 0 nodes have Donors = Acceptors =
`1e18`, NetDoping = 0, with counts and volume-weighted sums recorded. Edge arrays (`node_index@n0/n1`, `EdgeCouple`, `EdgeLength`) are
compared with E6A and recorded; the Gauss diagnostic below is computed only if they are equal.

## 4. Observables and the pre-registered decision (reused from E6B, renamed)
Common nodes: the 48033 L3 nodes, bit-identical (float32 construction coordinates) in L4 and L5; contact nodes (|x| = 5 um) excluded from every
metric; regions by construction coordinate: core |x| <= float32(0.1) um, transition, outer; weights = L3 `NodeVolume`; fixed-width Ex on
the core segments of the common nodes (`Ex = -(psi_j - psi_i)/(x_j - x_i)`, V/cm). For two solved states X, Y:
`psiLinf(X,Y)`, `psiL2(X,Y)` (NodeVolume-weighted RMS), `ExLinf(X,Y)`, `ExRMS(X,Y)`, called generically `M`.
* `D34(M) = M(L3-P, L4-P)` (core), `D45(M) = M(L4-P, L5-P)` (core), both on the P solutions only.
* `A3(M) = M(L3-P, L3-Q)`, `A4(M) = M(L4-P, L4-Q)`, `A5(M) = M(L5-P, L5-Q)` (core): the OBSERVED difference between two independent
  initial conditions at the same level, named **`observed_initialization_shift`** everywhere. It is not E6B's invalid `S`, not a solver-error
  bound, not a discretization-error bound.
* Three inequalities per metric M: (1) `D34 > A3 + A4`; (2) `D45 > A4 + A5`; (3) `D34 - D45 > A3 + 2*A4 + A5`.
  All three true => `INITIALIZATION_ROBUST_DECREASE_OBSERVED` for M. (1) or (2) false => `INITIALIZATION_SHIFT_INDISTINGUISHABLE`.
  (1) and (2) true, (3) false => `NO_REFINEMENT_TREND`. The inequalities are operational and are not an error analysis.
* `A = 0` with both solves converged is reported as "no observed difference between the two initial conditions", never as zero solver error
  or as proof of accuracy. `A` is invalid (and no trend is judged) whenever either P or Q of that level did not converge, raised, or is
  missing — even if the arrays happen to be bit-equal; an invalid `A` is never promoted to 0.
* Transition / outer region psi metrics are computed and stored for P-P and P-Q pairs, unclassified.

## 5. Diagnostics (reported; none is a pass / fail gate, none is a physics approval)
* y-uniformity of each P and Q state: max spread of psi along each common x-line per region, the E6B convention `<= 1e-6 V` (a convention,
  not derived); non-finite values anywhere in a saved array => `CONSISTENCY_FAIL`; an empty core region => `CONSISTENCY_FAIL`, no number.
* Gauss-law residual on each P and Q FINAL state, exactly the E6B Rev.3 definition (real `PotentialIntrinsicCharge`, `PotentialEdgeFlux`,
  `NodeVolume` and `EdgeCouple` once each; sign +1 at n0 / -1 at n1 stated as a hypothesis; `max_i |R_i|/s_i` on the non-contact eligible
  nodes `s_i >= 1e-3 max(s_nc)`; three wrong variants; separate contact block; the `DIAG_INVALID_*` / `DIAG_DEGENERATE_*` states, no 0 or pass
  from an empty or zero-denominator case). Diagnostic only; E6B's numbers are not reused as approval.
* Contact readback of each final state next to the boundary formula value (reported only).
* Initialization record per run: sha256 and node count of the saved initial `Potential`, its min / max, and for Q the pair `(V_left, V_right)`
  and `max|Q_init - P_init|` (proof that Q started from a different potential).
* **E6B-P reproducibility diagnostic (separate, unclassified):** the new P final `Potential` versus E6B's `level_L<L>_state_P.npz`
  (sha above) on all nodes: bit equality and the four core metrics. It does not stand in for E6C's P or Q and does not enter the verdict.

## 6. Artifacts and execution contract
Per run: `run_L<L>_<P|Q>.json` (identity, doping, initialization record, the RAW `solve` `info` result — `converged`, the full iteration list with the
per-device and per-equation errors and any problem-node fields DEVSIM returns —, flags, memory, counts), `run_L<L>_<P|Q>_init.npz` (the
initial `Potential` read back BEFORE the solve, tag `L<L>-<tag>-init`), `run_L<L>_<P|Q>_final.npz` (Potential, IntrinsicElectrons, IntrinsicHoles,
IntrinsicCharge, PotentialIntrinsicCharge, ElectricField, PotentialEdgeFlux read in ONE batch immediately after the solve, tag `L<L>-<tag>`),
per-array sha256 in the JSON. Each run JSON records `process_id`, `device_name` and `solve_count` (must be 1); a P and a Q of the same level
with the same `process_id`, a `solve_count != 1`, a snapshot tag that does not match, a sha256 that does not match, or a missing file are
`ARTIFACT_INCOMPLETE` before any judgement. All JSON strict (no NaN / Inf); no user path, account or token in any committed or uploaded file.
`git diff --check` on the E6A evidence commit is rc 2 only for E6A's `level_L3/L4/L5.vtu` (CRLF header lines of meshio's XML, hash-pinned
`-text` raw artifacts); this hygiene item is not a geometry or physics failure and those files are never rewritten.

## 7. Verdict table (per core metric M, and overall)
| state | condition |
|---|---|
| `ARTIFACT_INCOMPLETE` | section 6 |
| `INPUT_IDENTITY_FAIL` / `IMPORT_IDENTITY_FAIL` | section 1 / 3 |
| `INITIALIZATION_CONTRACT_FAIL` | section 2 contract (any Q of any level) |
| `RESOURCE_PREFLIGHT_FAIL` | section 2 resources |
| `POISSON_NOT_CONVERGED` | any of the six calls not `converged`, raised or missing (raw `info` kept; that level's `A` invalid) |
| `CONSISTENCY_FAIL` | non-finite values, empty core, or y-uniformity above the convention |
| `INITIALIZATION_SHIFT_INDISTINGUISHABLE` (per M) | inequality (1) or (2) false |
| `NO_REFINEMENT_TREND` (per M) | (1),(2) true, (3) false |
| `INITIALIZATION_ROBUST_DECREASE_OBSERVED` (per M) | (1),(2),(3) true |
| `INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY` (overall) | no failure state above and all four core metrics `INITIALIZATION_ROBUST_DECREASE_OBSERVED` |
| `INCONCLUSIVE` (overall) | any other combination |
Failure states are evaluated in the order of the table's first rows; when one holds, the four metric states are `NOT_CLASSIFIED` but every raw
number that exists is still stored. Always attached: `L3_BELOW_DEBYE_SCALE` (`L_D/h_3 = 0.638`, a priori). No tolerance, weight, region, initial
function or criterion is added or changed after results are seen.

## 8. What a positive or negative outcome would and would not mean
Positive: on these three meshes at 0 V, two initial conditions gave converged solutions whose difference is smaller than the observed
level-to-level change, and that change shrank from (L3,L4) to (L4,L5). Not meant: that either solution is physically or numerically accurate, that
the shrinking continues, that a fixed outer mesh does not limit it, or anything about current or bias. Negative or failed: reported with the raw
values; no rerun with other settings and no reinterpretation.
