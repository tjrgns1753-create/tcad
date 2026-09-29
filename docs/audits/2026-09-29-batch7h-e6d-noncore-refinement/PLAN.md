# Batch 7H-E6D PLAN: non-core refinement sensitivity of the 0 V Poisson solution, L5 junction core held fixed (audit-only)
(fixed BEFORE any code for this batch is written and BEFORE any mesh generation or DEVSIM execution of this batch; never edited after results)

Execution location: generation of the refined meshes, DEVSIM import and every `devsim.solve` run only on a GitHub-hosted Windows runner
(`claude/remote-runner`), one request. Locally: reading, documents, code, static checks, small synthetic meshes, synthetic judge tests.

## 0. Question, maximum verdict, hard limits
Question: keeping E6A's L5 junction core (|x| <= 0.1 um) exactly as it is, how much does the converged 0 V Poisson solution in that core change when
only the mesh outside it is refined by one and by two closed red-green passes seeded at |x| >= X02? The change is measured at the core's own nodes and on
fixed-width core segments, and compared with the observed initial-condition sensitivity of each mesh.

The experiment is **non-core refinement**, not "outer-only": the production red-green closure can change triangles next to the seeded ones (the last
transition column), and those changes are recorded. **Maximum verdict: `NONCORE_REFINEMENT_SENSITIVITY_ONLY`, or `NONCORE_REFINEMENT_DECREASE_OBSERVED` if the
pre-registered decrease test holds.** Neither means that no outer floor exists, that the solution converges to the 2D continuum, or that the physical
model is validated; any change is not attributed to the far-outer grid alone, because the transition column changes too. Unchanged: the gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`; the verdicts of E4 / E5 / E6A / E6B / E6C (E6C `INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY` is not
promoted). No change to `tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/`, DEVSIM / ViennaPS internals, precision settings, or any earlier raw evidence,
PLAN or verdict. Nothing about current, DD, bias, a 1D reference, oxidation or process order.

## 1. Inputs (hash-gated before any generation or solve; mismatch = `INPUT_IDENTITY_FAIL`, nothing is built or solved)
| input | sha256 | use |
|---|---|---|
| E6A `level_L5.vtu` (`docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/`) | `907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70` | **G0** mesh (points float32, triangles, tag 10); the input of G1 and G2 |
| E6A `level_L5.npz`, `level_L3.npz` | `7d56a93b2dd96e938eab059dbf1e3db605b8371a772e7f8061bc20b293b795ee`, `d61a1555b3daf5aa597dc02f4aa71e454c5adaeb3d08766964f93f269d4b24bf` | G0 construction coordinates, NodeVolume (weights), edge arrays; L3 nodes for the descriptive E6C-definition comparison |
| E6A `level_L5.json` (LF) | `425e956b40f60650b4b02d69159d87d020de952e2bdbdb215ddaff75ed8e6915`; the value used is `X02 = 0.20000000298023224` um (float32 of 0.2, `build.x_lines_um` +/- sides) and `X01 = 0.10000000149011612` um | seed and core boundaries, checked equal to the JSON at run time |
| E6C `run_L5_P_final.npz`, `run_L5_Q_final.npz` (`docs/audits/2026-09-29-batch7h-e6c-initialization-robustness/data/remote_run_36529279171/outputs/e6c_out/`) | `be34ae4a98ceae8b6c9207437df0a66e402fd51ddcc0a38e6139e6b330803d28`, `35d408066a50dd184e0c3853a9df6d33cda0d7c1ec1fde7359741dae22af1c6d` | **G0-P, G0-Q** potentials (reused, not re-solved) |
| E6C `run_L5_P.json`, `run_L5_Q.json` (LF) | `caca0fa5a268fed8947b723dad513b725f8bad2779e9612c17f8a56b76e7db1c`, `2de4d1bc231a74e8346a901d16dc450b5f2fd9c066058029c4fa72cc2d4d8cdc` | converged flags of G0-P / G0-Q |
| E6C `run_L3_P_final.npz`, `run_L4_P_final.npz` | `3c6142d70d8af6893c14eec85f47b86761609acf5d751d0c4c616aadfef120d8`, `54b4987fb1f9637b64d8b2fa8278597b33bebbc3f564e58cdb8d36c542b97971` | E6C `D45` recomputation for the descriptive comparison only |
| E6B `level_L5_static.npz` | `a0243706d029ab9fe7239a1a33bf45bc60aa3de201e5669d1912e8a91724b915` | G0 Donors / Acceptors / NetDoping on the core nodes |
| E6C `PLAN.md` (LF), `judge_e6c.py` (LF), E6B `judge_e6b.py` (LF), E6A `family_e6a.py` (LF) | `3c91c361a6ae445b795890e919f1e1ea26011cc33091423335442b9bd581194e`, `96cc5fc9182be5947984490f791509679a25e5839cab44d4be59ca07f045aec9`, `9f37ad88310b6bac19ff13465a50db0127de9c322dd3cf7c41f3edac98e26bb2`, `3f7c8f0ef5c3ff240a93e02f9846cbd9a09649c2f63e236efcc8ac76f2e9e06a` | reused definitions (metrics, contact-formula Q initial potential, exact geometry / tiling checks), imported read-only |
| production code | `tcad`, `tests`, `tcad_2d_stagewise.py`, `examples` identical to review SHA `023bcb90f8b8a0972d6df84f097ca6387f0ab82a` | else `INPUT_IDENTITY_FAIL` |

## 2. Mesh construction (production `tcad/device/devsim/mesh_refine.py` `refine_mesh_near`, unmodified, called only)
* **G1** = `refine_mesh_near(P0, T0, G0tags, pred, levels=1)`; **G2** = `refine_mesh_near(P0, T0, G0tags, pred, levels=2)`, both from the SAME G0 arrays (G2 is not
  built from G1's files). `P0, T0, G0tags` = E6A `level_L5.npz` `points_um_f32` (441733 x 3, float32), `triangles` (882600 x 3, int64), `tags` (int32, all 10),
  checked equal to the `level_L5.vtu` arrays before use; they are passed with these dtypes, so new midpoints are whatever the production function returns in
  float32, and the refined mesh is written as a float32 `.vtu` with the same `Material` cell data layout. `pred(c) = abs(float(c[0])) >= X02` with `X02 = 0.20000000298023224` (um, float32 of 0.2), evaluated by `refine_mesh_near` on the
  centroids of the triangles present at each pass. In G0 the seed of pass 1 is exactly the 38400 base-region triangles (every triangle with all
  vertices at |x| >= X02; counted locally on the E6A L5 npz).
* **A priori analysis of the closure (exact rational arithmetic on the E6A level-0 template cell, recorded before any run).** With the unit cell of the
  x > 0 level-0 template column `[X015, X02]`, `M = (0, 1/2)`, `LR = (1, 0)`, `UR = (1, 1)`: pass 1 green-splits the template triangle `(M, LR, UR)` at
  `(1, 1/2)`; both children have a right angle there and no obtuse angle. Pass 2 green-splits each child again from the same apex `M` at `(1, 1/4)` and
  `(1, 3/4)`; the triangles `(M, LR, (1,1/4))` and `(M, (1,3/4), UR)` have an obtuse angle (dot product `-1/16` of the unit-cell edge vectors, about 104
  degrees). So G1 is expected to be non-obtuse, and **G2 is expected to contain 2 obtuse triangles per template cell (4 x 100 = 400 in total)** — the same
  green-fan mechanism identified in 7H-E2. With DEVSIM's absolute element-couple NodeVolume (7H-B rule F3) this is expected to make the NodeVolume sum
  exceed the exact area, i.e. G2 may fail the section 3 gate. **The construction is not changed on that account**: if G2 fails a gate it is recorded as
  `GEOMETRY_UNSUPPORTED` with its raw values and no G2 solve is made.
* Predicted sizes (base region 2 x 96 x 100 cells, 100 template cells per side): G1 = 998000 triangles / 499725 nodes, G2 = 1459200 triangles / 730909
  nodes (G0 = 882600 / 441733). A mismatch is `GEOMETRY_UNSUPPORTED` (construction count mismatch).
* **Core identity (`CORE_IDENTITY_FAIL`, no comparison and no solve for that mesh):** the set of float32 coordinate bit patterns of nodes with
  |x| <= X01 equals G0's (none added, none removed), and the multiset of vertex-coordinate triples of the triangles with all vertices at |x| <= X01 equals
  G0's. Node ids and triangle order are never used.
* **Change record:** the multiset difference of vertex-coordinate triples G0 -> Gk, split by region of the triangle centroid (core, transition
  X01 < |x| < X02, outer): counts of removed and added triangles, the x-range of the changed transition triangles.

## 3. Mesh gates before any solve (per Gk; raw values kept; failure = `GEOMETRY_UNSUPPORTED` or `IMPORT_IDENTITY_FAIL`, no solve on that mesh)
Exact checks on the float32 coordinates (E6A `family_e6a.exact_checks` / tiling conditions, reused read-only):
* single material tag equal to G0's (10); bounding box equal; exact total area equal to G0's exact area (50 um^2);
* every triangle with exact orientation > 0; no duplicate triangle; no unreferenced (isolated) node; no duplicate node coordinate;
* tiling proof conditions (E6A PLAN B4): every edge owned by 1 or 2 triangles, 2-owner edges once in each direction, 1-owner edges only on the outer
  rectangle and forming gap-free CCW chains corner to corner with every node on a side line a chain vertex;
* exact obtuse-triangle count recorded (not a gate by itself; see NodeVolume below).
DEVSIM import (`import_process_result(contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1e-4)`, no refinement), in a subprocess:
* node x, y equal `(P32[:, :2] * 1e-4).astype(float)` node by node; the vertex-set multiset of `get_element_node_list` equals the constructed triangles;
  region `["Si"]`;
* NodeVolume: all > 0, and `|sum NodeVolume / exact area - 1| <= tau`, `tau = (N_nodes + N_triangles) 2^-52 + max b_i`, `b_i = 2^-46 / sin(theta_i)` (E6A
  section 4D definition, exact area from DEVSIM's own cm coordinates);
* EdgeCouple: minimum, number of negative and of zero entries (with the centroid |x| of the zero ones' edges binned by region) recorded; **any negative
  EdgeCouple blocks the solve**; zeros are reported, never altered;
* contacts `Si_xmin` / `Si_xmax` by coordinate: each contact's node set equals the set of all nodes on x = x_min (x_max), it contains the two corner nodes
  (y_min and y_max), and consecutive contact nodes are joined by a contact edge (full vertical coverage). The node count is recorded, not fixed (it grows
  with the refinement);
* J0 doping written as in E6C; on the G0 core nodes Donors / Acceptors / NetDoping equal E6B's L5 static arrays exactly; the x = 0 inventory and the total
  Donors / Acceptors NodeVolume integrals are recorded and not interpreted as implantation or diffusion.
* Resources: 8 GiB peak private bytes, 120 min total, 3600 s per subprocess. Mesh stage envelope (E6A rule) `M = 1 GiB + 4 KiB T + 1 KiB N`: G1 5.28 GiB, G2
  7.26 GiB; solve stage envelope = E6C L5 measured peak private bytes (max of P, Q: 2972852224 B) scaled by T / 882600, + 2 GiB: G1 5.51e9 B, G2 7.06e9 B. Any envelope above 8 GiB, or a
  measured mesh-stage peak of G1 that extrapolated proportionally in T exceeds 8 GiB for G2, is `RESOURCE_PREFLIGHT_FAIL` for G2; G2 is never replaced by
  another mesh.

## 4. Poisson solves (at most 4 new calls)
G1-P, G1-Q, G2-P, G2-Q, each in its own process with a freshly imported device, exactly as E6C: J0 doping, `setup_semiconductor_potential_equation(device,
"Si", ["Si_xmin","Si_xmax"], 300.0)`, biases 0 V, no precision flag, one call `solve(type="dc", absolute_error=1.0, relative_error=1e-6,
maximum_iterations=100, info=True)`. P starts from DEVSIM's default initial Potential; Q from `V_init(x) = V_left + (V_right - V_left) (x - x_min) /
(x_max - x_min)` with the contact-formula `V_left` / `V_right` read from the device (E6C `judge_e6c.contact_potentials` / `affine_init`), set with
`set_node_values` and read back bit-equal before the solve (else `INITIALIZATION_CONTRACT_FAIL`, no solve). Initial arrays, the raw `info` result and one
snapshot batch after the solve are saved; one `devsim.solve` per process (`solve_count` must be 1). A G level enters the comparison only if its P and Q
both report `converged: true` and have finite snapshots; non-convergence, an exception, a failed initialization contract or a missing array is never
treated as a zero change. No retry, no change of tolerance or of anything else after a result. G0 is not re-solved: G0-P / G0-Q are E6C's L5 arrays.
DEVSIM's `absolute_error` / `relative_error` are update norms (DEVSIM command reference, E6C ERRATUM 1), never read as residuals or error bounds.

## 5. Comparison and decision (pre-registered)
Primary common set: the **G0 core nodes** (|x| <= X01, contacts excluded; 412929 nodes), present bit-identically in G1 and G2 by the core-identity gate;
weights = G0 (L5) NodeVolume; fixed-width Ex on the x-adjacent G0 core node pairs of each common row (`Ex = -(psi_j - psi_i)/(x_j - x_i)`, V/cm, width
h_5 = 0.0015625 um). Metrics `psiLinf`, `psiL2`, `ExLinf`, `ExRMS` (E6B / E6C definitions, `judge_e6b.metrics_between`). No nearest-node matching, no
interpolation. For each metric M:
* `F01(M) = M(G0-P, G1-P)`, `F12(M) = M(G1-P, G2-P)`; `A0(M) = M(G0-P, G0-Q)`, `A1(M) = M(G1-P, G1-Q)`, `A2(M) = M(G2-P, G2-Q)`
  (`observed_initialization_shift`, not an error bound).
* With G1 and G2 both valid: (1) `F01 > A0 + A1`; (2) `F12 > A1 + A2`; (3) `F01 - F12 > A0 + 2 A1 + A2`. All three true =>
  `NONCORE_REFINEMENT_DECREASE_OBSERVED` for M. (1) and (2) true, (3) false => `NO_NONCORE_DECREASE`. (1) or (2) false => `NO_RESOLVABLE_NONCORE_CHANGE`
  for that pair (a change at the level of the observed initialization shift is not called "no outer-mesh effect").
* With G1 valid and G2 not valid: only (1); true => `NONCORE_CHANGE_RESOLVED_01`, false => `NO_RESOLVABLE_NONCORE_CHANGE`; the decrease test is not evaluated.
* Overall, in order: a failure state of the input, of G1's gates, core identity or solves => that state; all four metrics
  `NONCORE_REFINEMENT_DECREASE_OBSERVED` => `NONCORE_REFINEMENT_DECREASE_OBSERVED`; all four with (1) true (resolved change from G0 to G1) =>
  `NONCORE_REFINEMENT_SENSITIVITY_ONLY`; all four `NO_RESOLVABLE_NONCORE_CHANGE` => `NO_RESOLVABLE_NONCORE_CHANGE`; otherwise `INCONCLUSIVE`. G2's own
  state (valid, `GEOMETRY_UNSUPPORTED`, `IMPORT_IDENTITY_FAIL`, `CORE_IDENTITY_FAIL`, `RESOURCE_PREFLIGHT_FAIL`, `POISSON_NOT_CONVERGED`,
  `INITIALIZATION_CONTRACT_FAIL`, `CONSISTENCY_FAIL`) is reported beside the overall state.
* **Descriptive comparison with E6C (no threshold):** E6C's last core change `D45 = M(L4-P, L5-P)` was measured on the L3 common nodes with L3 weights and h_3
  segments. For comparability F01 and F12 are ALSO computed with exactly that definition (L3 common nodes, which exist in G0, G1, G2), and the absolute values
  and the ratios `F01 / D45`, `F12 / D45` are reported. No pass criterion is attached to these ratios.
* Region-wise transition / outer potential differences (on G0 nodes) are reported, unclassified.

## 6. Diagnostics (reported; none is a physics approval)
y-uniformity per state (E6B convention 1e-6 V; non-finite values or an empty core => `CONSISTENCY_FAIL`), contact readback next to the boundary formula,
Gauss residual with the E6B Rev.3 definition (non-contact eligible set, |R_i| / s_i, explicit invalid / degenerate states) on every final state, iteration
histories. The E6C L5 arrays enter only as G0; nothing from E6B's invalid control is used.

## 7. Artifacts and integrity
Mesh stage per Gk: `mesh_G<k>.json` (all gate values, change record, counts, memory), `mesh_G<k>.npz` (points float32, triangles, tags), `mesh_G<k>.vtu`
(the imported file), `mesh_G<k>_static.npz` (DEVSIM x, y, elements, NodeVolume, edge n0 / n1, EdgeCouple, EdgeLength). Run per Gk x {P, Q}: JSON with the
raw `info`, `process_id`, `solve_count`, identity, initialization record; `_init.npz` (tag `G<k>-<t>-init`), `_final.npz` (Potential, IntrinsicElectrons,
IntrinsicHoles, IntrinsicCharge, PotentialIntrinsicCharge, ElectricField, PotentialEdgeFlux; tag `G<k>-<t>`), per-array sha256 in the JSON. Mixed or mis-tagged
snapshots, P and Q in one process, `solve_count != 1`, a sha mismatch or a missing file are `ARTIFACT_INCOMPLETE` before any judgement. Strict JSON; no user
path, account or token in any committed or uploaded file. The E6A `.vtu` CRLF `git diff --check` hygiene item is unchanged and is not a failure of this batch.

## 8. Meaning
A positive result says only that, with the L5 core fixed, one and two non-core refinement passes changed the core potential / field by amounts larger than the
observed initialization sensitivity, and (for the DECREASE state) that the second change was smaller. It does not show that an outer floor is absent, that the
2D solution converged, or that the model is physically validated; a small result is not "2D TCAD validated".
