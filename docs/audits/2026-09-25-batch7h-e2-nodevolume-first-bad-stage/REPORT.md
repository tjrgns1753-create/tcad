# Batch 7H-E2 REPORT: first stage and minimal cause of the production-mesh NodeVolume excess

**First bad stage:** refinement pass 1 (S0 ratio 1.0 exactly; S1 1.0050000000000825, tau 1.43e-11).
**Cause established (within this scope):** yes, as a two-part mechanism. The red-green closure (green bisection) of 200
right triangles in the column |x| = 0.10-0.15 um produces obtuse triangles (one per green split, re-bisected every pass).
DEVSIM's NodeVolume rule F3 (absolute element couples) then counts their negative dual pieces as positive volume.
Neither part alone produces the excess: the signed dual F2 sums to the area exactly at every stage.
**Still unknown:** whether the orientation control had any power (the stored mesh is already 100 % CCW, so C_ccw changed
nothing); the effect of the excess on any physical result (no solve by design); whether any mesh treatment fixes it (the one
candidate was rejected).

PLAN `PLAN.md` sha256 (LF) `92e87eadb6c2317b3edab7c4e51b88653cc5cf5050fc87fcd97f304782b41c6b` (runner checkout CRLF form
`f0c8574b...`, same content), committed alone in `d60182beec71602c2a148e8eb1131283dcd6571f`. Code, profile and request:
`026102d0a8f3f5d519ba20dccd59a7cccd3fab36`. Run: https://github.com/tjrgns1753-create/tcad/actions/runs/36129959490
(request `e2-nodevolume-first-bad-stage-001`), PASS, exit 0, 766 s, GitHub-hosted Windows, DEVSIM 2.11.0,
`code_paths_identical_to_review_sha = true`. `devsim.solve` calls 0 (trapped); no doping written to DEVSIM; devices left 0.
Artifact: 11 outputs + log + summary, sha256 in `data/artifact_remote_run_36129959490.sha256`, all matching `summary.json`;
strict JSON parse OK; sensitive-pattern scan clean. Local work: static checks and the synthetic test
(`data/synthetic_e2_results_pre_run.json`, ALL_OK) only.

## 1. Identities (PLAN section 2)
Input mesh regenerated remotely: sha256 `cfae97d4...` = E1 (equal). Traced passes 4.
| Stage | I1 trace = production `refine_mesh_near(levels=k)` | I2 DEVSIM x, y bit-equal | I2 elements | I3 (S4 = E1) |
|---|---|---|---|---|
| S0-S3 | true | true | multiset of sorted triples | - |
| S4 | true | true | multiset of sorted triples | **true** (x / y / element sha256, NodeVolume array element-wise, contacts, regions) |
I4: exact area identical at every stage (18446741531089 / 2^65 cm^2 = 4.999999310821319e-07 cm^2), contact node sets
identical (`Si_xmin`, `Si_xmax`, 101 nodes each, from `get_element_node_list(contact=...)`), region `["Si"]` only.
DEVSIM returns elements in its own order and vertex order (equal only as a multiset of sorted triples), see section 4.

## 2. Comparison table (areas in cm^2 per unit depth; ratio = sum NodeVolume / exact area)
| | S0 | S1 | S2 | S3 | S4 | C_ccw | candidate |
|---|---|---|---|---|---|---|---|
| nodes / triangles | 20301 / 40000 | 21605 / 42600 | 26613 / 52600 | 46229 / 91800 | 123861 / 247000 | 123861 / 247000 | 123861 / 247000 |
| sum NodeVolume | 4.999999310821319e-07 | 5.024999307375838e-07 | 5.064843040490548e-07 | 5.140819593259176e-07 | 5.291259043686336e-07 | same as S4 | 5.100829509335998e-07 |
| ratio | 1.0 | 1.0050000000000825 | 1.0129687477214029 | 1.0281640603695854 | 1.0582519546022044 | 1.0582519546022044 | 1.0201660424825372 |
| tau (PLAN s. 4) | 1.341e-11 | 1.430e-11 | 1.769e-11 | 3.086e-11 | 8.279e-11 | 8.279e-11 | 8.263e-11 |
| within tau | yes | **no** | no | no | no | no | no |
| sum(F3 - F2) / area | 0.0 | 0.005000000000082644 | 0.012968747721402817 | 0.02816406036958547 | 0.058251954602204704 | same | 0.02016604248253709 |
| sum F2 / area (signed dual) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| max per-node NodeVolume vs F3 (rel) | 0.0 | 2.1e-16 | 3.2e-16 | 2.2e-16 | 4.0e-16 | 4.0e-16 | 3.9e-16 |
| nodes beyond budget b_i | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| acute / right / obtuse (exact) | 0 / 40000 / 0 | 0 / 42400 / 200 | 0 / 52000 / 600 | 0 / 90400 / 1400 | 0 / 244000 / 3000 | same | 200 / 244000 / 2800 |
| min / max angle (deg) | 44.9995 / 90.0 | 18.435 / 116.565 | 8.130 / 126.870 | 3.814 / 131.186 | 1.847 / 133.153 | same | 2.935 / 113.630 |
| exact Delaunay violations | 0 | 200 | 200 | 200 | 200 | 200 | 0 |
| signed couple / node-volume negatives | 0 / 0 | 200 / 0 | 200 / 0 | 200 / 200 | 200 / 200 | same | 0 / 0 |
| boundary Gabriel / exact overlaps | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| nodes with F3 > F2 (all obtuse vertices) | 0 | 400 (yes) | 800 (yes) | 1600 (yes) | 3200 (yes) | same | 2802 (yes) |
| where (|x| um) | - | 0.10, 0.15 | 0.10, 0.15 | 0.10, 0.15 | 0.10, 0.15 | same | 0.10, 0.15 |
| contact nodes | 101 / 101 | 101 / 101 | 101 / 101 | 101 / 101 | 101 / 101 | 101 / 101 | 101 / 101 |
C_rt (writer round trip of the S4 arrays, no refinement): writer round trip exact, reproduces S4 exactly (x, y, elements,
NodeVolume), 0 nodes beyond budget. The float64 triangle-area sums differ from the exact area by at most 2.9e-12 relative (S4), inside tau.

## 3. Lineage of the defects (audit trace copy, proven equal to production by I1)
| Stage | obtuse triangles | distinct S0 origins | split history of every obtuse triangle | Delaunay-violating edge pairs |
|---|---|---|---|---|
| S1 | 200 | 200 | right S0 triangle -> green | 200 x (right, unchanged) + (right, green) |
| S2 | 600 | 200 | right -> green, green | 200 x (right, unchanged x2) + (right, green x2) |
| S3 | 1400 | 200 | right -> green x3 | 200 x (right, unchanged x3) + (right, green x3) |
| S4 | 3000 | 200 | right -> green x4 | 200 x (right, unchanged x4) + (right, green x4) |
The same 200 S0 right triangles (legs 0.05 um, vertices at |x| = 0.10 and 0.15, e.g. S0 triangle 594 with vertices
(-0.15, -4.95), (-0.10, -4.95), (-0.10, -4.90) um) are green-bisected at every pass: 2^k - 1 obtuse descendants each after k
passes (1, 3, 7, 15). Example at pass 1: splitting the leg on x = -0.10 at its midpoint (-0.10, -4.925) from the apex
(-0.15, -4.95) gives one right child and one child with a 116.57 deg angle at the midpoint. No red child and no pre-existing
obtuse triangle is involved.

## 4. Orientation control (PLAN section 5) - no power in this mesh
`C_ccw` reoriented **0** triangles: every stored triangle is already counter-clockwise (40000 / 40000 in the ViennaPS file,
247000 / 247000 after refinement; `data/posthoc_orientation_check.txt`, post-hoc, descriptive). `C_ccw.vtu` is byte-identical
to `C_rt.vtu` (sha256 `82fa87b0...`). So `NO_ORIENTATION_EFFECT`, although mechanically satisfied, came from a control that
changed nothing and cannot separate orientation from shape. The `all_ccw: false` reported by E1 (123500 positive / 123500
negative) comes from the vertex order DEVSIM returns in `get_element_node_list`, not from the mesh supplied to it. What does
bear on orientation: DEVSIM NodeVolume equals the orientation-independent rule F3 (its cotangent sign comes from a dot
product) at every node of every stage, to at most 4.0e-16 relative.

## 5. EdgeCouple readback (public API: `edge_from_node_model(node_index)`, `EdgeCouple`, `EdgeLength`)
At every stage with G1 < 0 (S1-S4: 200 edges, the same pairs as the Delaunay violations), DEVSIM's EdgeCouple is
**positive at all 200** (negative 0, zero 0). It equals G2 (sum of absolute element couples) to at most 8.5e-17 of max |G2|,
and differs from the signed prediction G1 by up to 1.064 x max |G2|. DEVSIM never produces a negative EdgeCouple anywhere
(0 of 370860 edges at S4). NodeVolume = sum of 0.25 x EdgeCouple x EdgeLength to at most 2.7e-16 relative.

## 6. Verdicts (PLAN section 6)
`FIRST_BAD_STAGE=1`, `NO_ORIENTATION_EFFECT` (vacuous control, section 4), `SHAPE_CAUSE`. Not `PRE_EXISTING` (S0 ratio 1.0,
0 obtuse, 0 negative couples). Nothing withheld; I1-I4 and C_rt all held.

## 7. Repair candidate (PLAN section 7) - `CANDIDATE_REJECTED`
7H-A `exact_flip` on the S4 arrays, boundary and x = 0 edges protected: 1600 flips in 9 passes, terminated with no exact
violation left. Exact invariants all held: identical points, boundary / interface / x = 0 edge sets, tag counter, exact
area; no duplicate, zero-area or non-manifold triangle; 0 exact positive-area overlaps; same contacts and region. It removed
all 200 Delaunay violations and all negative signed couples / node volumes, but **2800 obtuse triangles remain** (max
113.63 deg), and DEVSIM's F3 rule still inflates: ratio 1.0201660 (tau 8.3e-11) and dopant inventory 2.551196e11 cm^-1 per
species against 2.500781e11 for the exact dual F2 (continuum N x 25 um^2 = 2.5e11). Failed checks: `ratio_within_tau`,
`inventory_donor_within_tau`, `inventory_acceptor_within_tau`. The phenomenon stays `UNSUPPORTED_BY_MODEL`; nothing is
applied to production, and no DEVSIM EdgeCouple or NodeVolume was overwritten.

## 8. No-change confirmation
Production / tests byte-identical to the start (`data/start_hashes_prod_tests.txt`) and to review SHA `023bcb90`; E1 tracked
files and every pre-existing audit file unchanged (`data/start_hashes_e1_tracked.txt`, `data/start_hashes_all_audits.txt`);
gate code untouched and not exercised (no doping written); no precision flag set; no full regression, no PN / DD solve, no
GUI run; `origin/claude/waferstate-v2` and `origin/main` unchanged.

## 9. Files
`PLAN.md`, `PLAN.sha256` (d60182be); `scripts/{run_e2,stage_e2,trace_refine_e2,verdicts_e2,synthetic_e2_test}.py`,
`remote/profiles.py`, `remote/request.json`, `data/start_*`, `data/synthetic_e2_results_pre_run.json` (026102d0); `REPORT.md`,
`data/posthoc_orientation_check.txt`, `data/artifact_remote_run_36129959490.sha256`,
`data/remote_run_36129959490/{summary.json,run.log,outputs/e2_out/*}`, `data/batch_e2_code.patch`.
