# Batch 7H-E6D REPORT: non-core refinement sensitivity of the L5 core 0 V Poisson solution

**Overall verdict: `NO_RESOLVABLE_NONCORE_CHANGE`** (G1 valid; G2 = `GEOMETRY_UNSUPPORTED`, decrease test not evaluated).
Meaning, exactly: one closed red-green pass of production `refine_mesh_near` seeded at |x| >= X02 changed the converged core potential /
fixed-width field of the E6A L5 device by less than the observed initialization shift of the two meshes (F01 <= A0 + A1 for all four metrics).
It does **not** mean that the outer mesh has no effect, that an outer floor is absent, that the 2D solution converged, or that the physics is
validated; the second pass (G2) could not be judged. The gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and all earlier verdicts are unchanged.

## 1. Identity
| item | value |
|---|---|
| PLAN | `PLAN.md` LF sha256 `fb389c5df1f011f02dc7e42f23de46fd3cbe61b86e5d5dece9d6f094e2b52f9c`, committed alone in `44c426b828d28941e3a6690fbf0236ecf63a5b3d` (before any code or result) |
| code commit | `45450b6` (scripts, synthetic results) |
| profile / request commit (exec SHA) | `5477c09b3810bcf18136ac00b885b2e95c7a43ad`, request `e6d-noncore-refinement-001`, profile `e6d_noncore_refinement` |
| run | https://github.com/tjrgns1753-create/tcad/actions/runs/36538742843 (GitHub-hosted Windows; one run; workflow `success`, remote-run status `PASS`) |
| inputs | all 21 hash-gated inputs equal (`input_identity_ok: true`); `git diff --quiet 023bcb90... -- tcad tests tcad_2d_stagewise.py examples` rc 0 on the runner |
| solves | 2 (`G1-P`, `G1-Q`), budget 4; mesh stages 0 solve calls each (trapped) |
| E6C ERRATUM | `docs/audits/2026-09-29-batch7h-e6c-initialization-robustness/ERRATUM.md` (commit `cc0e0ef`): DEVSIM `absolute_error` is an update norm; E6C REPORT not edited |

## 2. Meshes
| | G0 (E6A L5, reused) | G1 = `refine_mesh_near(levels=1)` | G2 = `refine_mesh_near(levels=2)` |
|---|---|---|---|
| seed (pass 1) | - | 38400 triangles (centroid |x| >= 0.20000000298023224) | same |
| nodes / triangles | 441733 / 882600 | 499725 / 998000 (= predicted) | 730909 / 1459200 (= predicted) |
| core nodes / core triangles (|x| <= X01) | 412929 / 819200 | 412929 / 819200, node set and vertex-triple multiset **equal** | equal |
| triangles removed / added (core, transition, outer) | - | (0, 200, 38400) / (0, 400, 153600) | (0, 200, 38400) / (0, 800, 614400) |
| changed transition triangles | - | all at |centroid x| = 0.18333333730697632 um (the template triangles (M, LR, UR) of column [X015, X02], 100 per side) | same x |
| exact area | 50 um^2 | 50/1 = G0 | 50/1 = G0 |
| orientation / duplicates / isolated / duplicate nodes / T2 / T3 | ok | all ok | all ok |
| exact obtuse triangles | 0 | **0** | **400** (all in the transition column; float count by region: core 0, transition 400, outer 0) |
| NodeVolume min / sum ratio / tau | - | 1.2205e-14 cm^2 / **1.0** (abs dev 0.0) / 3.326e-10: **pass** | 1.2205e-14 / **1.0031249951791816** / 4.864e-10: **fail** |
| EdgeCouple edges / min / negative / zero (core, transition, outer) | 1324332 / 0.0 / 0 / - | 1497724 / 0.0 / 0 / 229332 (159522, 2079, 67731) | 2190108 / 0.0 / 0 / 422767 (159522, 1679, 261566) |
| contacts Si_xmin / Si_xmax | 101 / 101 | 201 nodes, 200 edges each; line complete, both corners, 0 gaps | 401 / 400 each; complete |
| import identity (xy node by node, element multiset, region Si) | - | ok | ok |
| mesh-stage peak private bytes / wall | - | 1929195520 B / 66.6 s | 2758709248 B / 100.9 s |
| state | OK (E6C) | **OK** | **`GEOMETRY_UNSUPPORTED`** (`nodevolume_sum_within_tau`) — no solve |

G2's failure is the outcome the PLAN (section 2) predicted in advance from exact arithmetic on the template cell: the second green split from
apex M produces 2 obtuse triangles per template cell (400 in all), and DEVSIM's absolute element-couple NodeVolume over-integrates there. The
construction was not changed after the result. The G2 mesh-stage measured memory gate passed (predicted 2.82e9 B), so this is a geometry
state, not a resource one.

## 3. Solves (G1 only)
Arguments identical to E6C: `absolute_error=1.0, relative_error=1e-6, maximum_iterations=100, info=True`; biases 0 V; J0 doping; no precision flag
(`extended_*` unset).
| run | process | initial Potential | converged | iterations | final rel. update | final abs. update | peak private bytes |
|---|---|---|---|---|---|---|---|
| G1-P | 1584 | default: min 0.0, max 0.0 | true | 10 | 3.433680132098044e-07 | 5.2702066330080866e-17 | 3565338624 |
| G1-Q | 6776 | affine, V_left -0.4768597199126637, V_right 0.4768597199126637; readback bit-equal (contract ok) | true | 8 | 4.932928785807721e-07 | 2.5462187632152147e-08 | 3571109888 |

(The DEVSIM "error" fields are update norms, not residuals or error bounds.) Both runs: import identity ok, NodeVolume bit-equal to the mesh
stage, edge arrays equal, J0 read back equal to what was written, Donors / Acceptors / NetDoping on the G0 core nodes equal to E6B's L5 static
arrays, x = 0 has 3201 nodes with Donors = Acceptors = 1e18 and NetDoping = 0, devices left 0, `solve_count` 1.
Dopant inventory (reported, not interpreted): total Donors x NodeVolume = Acceptors x NodeVolume = 250039028037.38702 vs continuum N x area / 2 =
249999965541.06592.

## 4. Comparison (primary: 412929 G0 core nodes, G0 NodeVolume weights, h_5 core segments)
| metric | F01 = M(G0-P, G1-P) | A0 = M(G0-P, G0-Q) | A1 = M(G1-P, G1-Q) | F01 > A0 + A1 | state |
|---|---|---|---|---|---|
| psiLinf [V] | 5.551115123125783e-17 | 4.440892098500626e-16 | 4.440892098500626e-16 | 5.55e-17 > 8.881784197001252e-16: **false** | NO_RESOLVABLE_NONCORE_CHANGE |
| psiL2 [V] | 1.3129438786827381e-17 | 1.54781725670888e-16 | 1.579053973559269e-16 | 1.31e-17 > 3.126871230268149e-16: **false** | NO_RESOLVABLE_NONCORE_CHANGE |
| ExLinf [V/cm] | 3.5561242839321494e-10 | 7.130438461899757e-10 | 7.130438461899757e-10 | 3.56e-10 > 1.4260876923799515e-09: **false** | NO_RESOLVABLE_NONCORE_CHANGE |
| ExRMS [V/cm] | 1.0909513600354076e-10 | 2.5059544204897306e-10 | 2.2766069686240246e-10 | 1.09e-10 > 4.782561389113755e-10: **false** | NO_RESOLVABLE_NONCORE_CHANGE |

F12, A2 and inequalities (2), (3) do not exist (G2 not solved). Region-wise F01 (G0 nodes, unclassified): transition psiLinf 2.7755575615628914e-16,
psiL2 1.4169508690135166e-16; outer psiLinf 5.551115123125783e-17, psiL2 3.8310020109841895e-17.

**Descriptive comparison with E6C (no threshold).** On E6C's own D45 definition (L3 common nodes, L3 weights, h_3 segments):
| metric | E6C D45 (recomputed) | F01 (same definition) | F01 / D45 |
|---|---|---|---|
| psiLinf | 2.5791697788185575e-04 | 5.551115123125783e-17 | 2.152e-13 |
| psiL2 | 9.0383171939044e-05 | 1.339284266415894e-17 | 1.482e-13 |
| ExLinf | 387.29503120037407 | 1.4551915228366852e-10 | 3.757e-13 |
| ExRMS | 123.76018639069537 | 2.921855321377067e-11 | 2.361e-13 |

## 5. Diagnostics (reported only)
y-spread (G0 core / transition / outer): G1-P 2.2127e-13 / 1.6037e-13 / 5.55e-17 V; G1-Q 2.2121e-13 / 1.6037e-13 / 5.55e-17 V. Contact readback
+/-0.4768597199126638 V (both runs). Gauss residual (E6B Rev.3 definition, 176047 eligible non-contact nodes, no invalid / degenerate state):
max |R|/s = 4.45e-13 (P), 6.49e-13 (Q); alternatives edgecouple_omitted 6.58e6, edgecouple_twice 0.161, charge_sign_flipped 0.322.

## 6. Fail-closed states observed
`GEOMETRY_UNSUPPORTED` for G2 (NodeVolume sum), no G2 solve; no other failure. No `CORE_IDENTITY_FAIL`, `IMPORT_IDENTITY_FAIL`,
`RESOURCE_PREFLIGHT_FAIL`, `POISSON_NOT_CONVERGED`, `INITIALIZATION_CONTRACT_FAIL`, `ARTIFACT_INCOMPLETE`.

## 7. Synthetic tests (local, before the run)
`synthetic_e6d_test.py` -> `synthetic_e6d_results.json`, 13 cases all PASS: core triangle changed with same core nodes -> CORE_IDENTITY_FAIL;
hidden transition flip (2 removed / 2 added recorded) and real G1 closure change recorded; negative EdgeCouple -> GEOMETRY_UNSUPPORTED; missing
contact edge -> IMPORT_IDENTITY_FAIL (control ok); NodeVolume total off -> GEOMETRY_UNSUPPORTED (1-ulp control within tau); Q not converged with P/Q
arrays equal -> POISSON_NOT_CONVERGED at G1 (no metric classified) and, at G2, decrease test not evaluated; empty core -> CONSISTENCY_FAIL; only
the third inequality failing -> NO_NONCORE_DECREASE / SENSITIVITY_ONLY; positive control -> DECREASE_OBSERVED; tiny F -> NO_RESOLVABLE; missing checks
fail closed; green-of-green obtuse count 0 / 0 / 16 (G0 / G1 / G2) on the synthetic E6A-like mesh. Disclosure: the first local run had 3 failures
in case L because the synthetic fixture placed the template midpoint M with a double-precision midpoint instead of the production float32 midpoint
(the E6A construction uses the float32 one); the fixture was corrected, the expectations were not changed.

## 8. Artifacts (`data/remote_run_36538742843/`, sha256; local recheck: all 14 output shas equal, 0 missing, runner and local judgement identical)
| file | sha256 |
|---|---|
| outputs/e6d_out/e6d_result.json | 6551ed4709e1b341df50eb39b916c5a54d1bb3efe616badbfcfd29f197472ea0 |
| outputs/e6d_out/mesh_G1.json | 2c85a053b0db186e60c3fdddf3f7a1d886383ff84f05e5dbd31aceacd992db4c |
| outputs/e6d_out/mesh_G1.npz | 328232c10ebbd5e337eababb22c93877f20aafc315eb66279c6aa37ce870f0e5 |
| outputs/e6d_out/mesh_G1.vtu | 48bcf8ea231c5c59a09a2c7089bd6e61af8688c57b73c723d6753305753f4f02 |
| outputs/e6d_out/mesh_G1_static.npz | 117b2837550167078007acdbfe19ce20424af1b3f081c0979af1825be3d650b2 |
| outputs/e6d_out/mesh_G2.json | 1e798be0e350c3638000717d8b2d92725376b7d58b5753843e6b891dba0a5db5 |
| outputs/e6d_out/mesh_G2.npz | 32f287ed64454dc809adea7217ce6bb868ad216df85e7c7a73709890456fdd3c |
| outputs/e6d_out/mesh_G2.vtu | d9229e8378eb3348523875825dbaf5e9479c968d444c3888dc157a78586c7dae |
| outputs/e6d_out/mesh_G2_static.npz | 30fbf90d0401829f6891d25c8a8c02e0f61e92fb4688db02f02e11989d6ddc4c |
| outputs/e6d_out/run_G1_P.json | 0162c78d2e8eae199bd7af487ec51f78800eba2fc36aacae1b94df1b2204627e |
| outputs/e6d_out/run_G1_P_final.npz | 24510e9c311f5af36401b86d2617b1bcc84cbfc61d6c53d3189b46ef4b145fa7 |
| outputs/e6d_out/run_G1_P_init.npz | 73c9d17a0bf01bb4c3a22b02b81d3b506b06f065b6199dd8ab7cc78469c2a649 |
| outputs/e6d_out/run_G1_Q.json | 0b78da2769736278806dd32fab907939095e0442b725113e6f7cd80fb272169e |
| outputs/e6d_out/run_G1_Q_final.npz | bd52596e655a0cc125f4fffc266d0d49321e481bf5b3662f83e393182ab3b210 |
| outputs/e6d_out/run_G1_Q_init.npz | becf4dc410aae44fab0b3c8f0f1016e4b3f9bda20cfe9068c983e7eda898f872 |
| run.log | b1982e6bb82e9a9781a017710c3488d4e00acae6b5afe962d80d36cc6bc094c7 |
| summary.json | 9397561fb706c30fca65529653e63790016678e2dc5aa5f78202f108cec82b1d |

Sensitive scan: no user path, account or token; the only match is the public repository name in `summary.json` (`"repository"` field, present in
earlier committed summaries). No outputs omitted by the size budget.

## 9. Change evidence
Code / profile / request diff from the PLAN commit (`git diff -U1 44c426b 5477c09`, 1586 lines, 6 new files + `remote/profiles.py` +41 lines,
`remote/request.json` 3 lines changed): `e6d_code.patch`, sha256 `48c12aa27f8495f4bc864b45830365831128cd751ae0881c943a41edb01171c2`
(`git apply --check -R` ok). Production `tcad`, `tests`, `tcad_2d_stagewise.py`, `examples` identical to `023bcb90...` (rc 0); E4 / E5 / E6A / E6B raw
evidence and E6C REPORT / raw evidence unchanged (only the separate E6C ERRATUM added).
