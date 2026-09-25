# Batch 7H-E3 PLAN: one geometric junction-refinement candidate (audit-only)
(fixed BEFORE any ViennaPS / DEVSIM execution of this batch; never edited after results)

Execution location: ViennaPS mesh regeneration and DEVSIM import / geometric-model reads run on a GitHub-hosted Windows
runner (`claude/remote-runner`, profile `e3_junction_refinement_candidate`). Locally: code reading and writing, static
checks, and read-only numpy analysis of already-downloaded 7H-E1/7H-E2 arrays and the corrected control logic's synthetic
test only.

## 0. Question and hard limits
7H-E2 (`ERRATUM.md`) found the production step-junction mesh's DEVSIM NodeVolume excess is caused by green-bisected
boundary triangles turning obtuse under repeated refinement passes at a FIXED window boundary. This batch asks: does
calling the ALREADY-EXISTING, unmodified production function `graded_refine_mesh_near()`
(`tcad/device/devsim/mesh_refine.py:189-222`) with a telescoping (narrowing) window sequence, instead of
`refine_mesh_near()` (`:157-186`) with one fixed window applied 4 times — the exact mechanism its own docstring describes
as avoiding "the ENTIRE window gets N halvings regardless of how close to the target position it is" — produce a mesh
whose real geometric area and DEVSIM's own default integration weight actually agree, at the SAME or better local
resolution near the junction. This is a geometry question only. It does not touch, run, or draw any conclusion about
Poisson, drift-diffusion, PN I-V, doping physics correctness, or `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`. No
production file (`tcad/`, `tests/`, `tcad_2d_stagewise.py`) is modified; the candidate is built and evaluated only from an
audit script that CALLS the existing, untouched `graded_refine_mesh_near()` — it is not a new numerical method.
Whatever this batch finds, the strongest verdict it may register is `GEOMETRY_CANDIDATE_ONLY` (section 6) — never a claim
about electrical accuracy, 2D mesh convergence, or a general-shape guarantee. It never releases the gate, applies anything
to production, or runs a solve.

**Scope limit, stated up front, not after results:** this candidate is investigated ONLY for the exact geometry 7H-E1/E2
used — a single planar Si wafer, one axis-aligned step junction at x = 0, no other material, no mask, no etched or curved
surface. It is not claimed, here or anywhere in this batch's outputs, to generalize automatically to multi-material
interfaces, curved boundaries (e.g. LOCOS bird's-beak), multiple junctions, or non-axis-aligned features — those would need
their own separate investigation.

**Alternatives considered and why this one is investigated first** (not because it is assumed to work): (a) a globally
uniform ultra-fine mesh is explicitly excluded — it does not test the mechanism, only hides it under cost, and CLAUDE.md's
own investigation log already records this approach failing to converge affordably at comparable doping levels; (b) a
smoothed/continuous refinement-density field is a genuinely new numerical method with no prior validation anywhere in this
project — higher-risk for a first, single-batch experiment; (c) hand-built local re-meshing of just the boundary band
bypasses the green-split mechanism entirely but is not an already-validated mechanism and is far more code to audit
correctly in one batch. Telescoping graded refinement is already implemented, untouched, and already used in production
for two OTHER doping kinds (`refine_process_result_for_mos_gate`, `tcad/device/devsim/mesh_import.py:275`;
`refine_process_result_for_implant_windows`, `:363`) — reusing it here is the smallest, best-precedented next experiment.

**The GUI step-junction path does NOT call `graded_refine_mesh_near()` today.** Confirmed by direct reading (not assumed):
`import_process_result()` (`mesh_import.py:732`) only reaches the graded branch (`:960-969`) when
`auto_refine_from_doping=True`; the step-junction measurement call passes `refine_near_um=0.0` explicitly with
`auto_refine_from_doping` left at its default `False` (established in 7H-E1's PLAN section 1 / REPORT.md path table), so
it takes the single-window `refine_mesh_near()` branch at `mesh_import.py:979-986` — exactly the path 7H-E2 traced.

## 1. Input and identity (reusing 7H-E2's own method and SHA, not a new gate)
The raw wafer mesh is regenerated with the identical calls 7H-E1/E2 used (`tcad.backends.viennaps.session.make_mask_spans`
with `docs/audits/2026-09-24-batch7h-e1-production-step-junction-equivalence/scripts/common_e1.py`'s `GUI` defaults, then
`save_volume_mesh(floor 5 um)`), then `build_process_result` + `apply_step_junction_doping`. Its sha256 must equal the same
value 7H-E1/E2 already verified: `cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a`. A mismatch is
`MESH_INPUT_IDENTITY_FAIL`; no causal or comparison verdict is drawn, the run stops after recording the difference.

S4 (production's own single-window result) is NOT re-imported into DEVSIM in this batch — 7H-E2 already built and recorded
it (`docs/audits/2026-09-25-batch7h-e2-nodevolume-first-bad-stage/data/remote_run_36129959490/outputs/e2_out/{e2_result.json,stage_S4.npz}`,
hash-pinned, unmodified). This batch instead reuses those numbers directly as the S4 row of its comparison table, and
proves — cheaply, with plain numpy, no second DEVSIM import — that the S4 it is comparing against is the SAME S4: the raw
refined arrays produced locally in-process by the unmodified production `refine_mesh_near(points, triangles, tags,
|x|<0.1, levels=4)` must (a) have `x * 1e-4`, `y * 1e-4` bit-equal to 7H-E2's recorded S4 `x_sha256` / `y_sha256`
(sha256 `f9353f60d0ac...` / `3818a0b5f258...`, from 7H-E1's `prod.json`, unchanged since), and (b) have its triangle list
equal `stage_S4.npz`'s `elements` array as a multiset of sorted vertex triples (the same I2 equivalence 7H-E2 registered,
since DEVSIM returns its own element order). Any mismatch is `S4_BASELINE_REUSE_FAIL`; the run stops.

## 2. Candidate construction
`predicates = [lambda c: abs(c[0] - 0.0) < w for w in (0.1, 0.05, 0.025, 0.0125)]` (widest to narrowest, axis x, centred on
the junction at x = 0, matching production's own `refine_near_um=0.0` / `refine_axis="x"` exactly — same footprint as S4's
own 0.1 um window, only the internal structure differs). Candidate arrays = unmodified
`graded_refine_mesh_near(raw_points, raw_triangles, raw_tags, predicates)` (`mesh_refine.py:189`, called from a NEW audit
script only, no changes to the function or to any production call site). Four rings, one halving each, chosen to reach the
SAME final local resolution as S4 (section 3) at the junction, not a different target.

## 3. Target resolution (extracted from S4's own raw data, fixed now, not tuned after seeing the candidate)
Read directly from 7H-E2's committed `stage_S4.npz` (`EdgeCouple`/`EdgeLength`/`x`/`y` arrays, unchanged): S4's minimum
edge length anywhere in the mesh, and specifically among edges touching a node within 0.1 um of the junction, is
**0.003124296199530363 um**; S4's node spacing exactly at the junction is 0.003125 um (16x the base grid_delta_um of
0.05 um — 4 halvings). The candidate's own minimum edge length within 0.1 um of x = 0, measured the same way, must be
**<= 0.003124296199530363 um** (not coarser than S4). Achieving ratio-near-1 by under-resolving the junction is a REJECT,
not a pass — this check is independent of and reported alongside the ratio check.

## 4. Geometric invariants — bit-identical vs. geometry-identical (fixed now)
**Must be bit-identical** to the input mesh / to S4 (float64-exact, no tolerance): every outer-domain-boundary vertex
coordinate (the refinement windows, max half-width 0.1 um, never reach the domain boundary at x = +-5 um — the outer
boundary is therefore untouched by construction in both S4 and the candidate, verified, not assumed); every Si material
tag (single region, single tag value); any vertex whose coordinate is exactly 0.0 on one axis, if present, keeps that
coordinate exactly 0.0 (red-green refinement only ever inserts an exact float64 midpoint, so a midpoint of two points
symmetric about 0 is exactly 0.0 — verified per candidate, not assumed).
**Must be geometry-identical (coordinate-set equality, not stored order)**: `Si_xmin` / `Si_xmax` contact node coordinate
sets (must equal S4's contact coordinate sets exactly — see above, untouched boundary); region list `["Si"]`; the exact
total area (rational arithmetic on the exact float64 values, `Fraction`-based, as 7H-B/7H-E2 already use) must equal S0's
and S4's exact area (`18446741531089/2^65 cm^2`) — refinement can only redistribute area among smaller triangles, never
change the total, and this is checked as a HARD invariant, not a numerical tolerance.
**Must hold by direct check (not assumed from the algorithm)**: conforming adjacency (every interior edge has exactly 2
owning triangles, no non-manifold edge); no duplicate, zero-area or inverted (negative exact orientation) triangle; 0 exact
positive-area triangle overlaps (7H-A `exact_geometry.global_exact_scan`).

## 5. Recorded / checked numerically (S0, S4 [reused], candidate — same schema as 7H-E2 section 3)
sha256 of x, y, elements, tags; node / triangle counts; DEVSIM `NodeVolume` sum and ratio vs. the exact area (tau formula
below, identical to 7H-E2 PLAN section 4, restated: per-node budget b_i = 2^-46 / sin(theta_i) with theta_i the smallest
incident-triangle angle, 128 u times 1/sin(theta) conditioning; per-mesh tau_k = (N_nodes + N_triangles) x 2^-52 +
max_i b_i); per-node F2 (signed circumcentric dual, sums to the exact area) and F3 (DEVSIM's own identified rule, 7H-B);
angle classes, min / max angle, exact Delaunay violations, boundary Gabriel violations, signed edge-couple / node-volume
negative counts (7H-D `quality()`); EdgeCouple readback (public API: `edge_from_node_model` + `EdgeCouple` + `EdgeLength`)
compared against the 7H-B G1 (signed) / G2 (absolute) element-couple predictions, exactly as 7H-E2 did; minimum edge length
within 0.1 um of x = 0 (section 3); wall time of mesh construction and of DEVSIM import separately. A candidate that is
geometrically valid (section 4) but numerically worse than S4 on ratio or resolution is still reported in full, not
discarded silently.

## 6. Doping integrals — three separate, never-conflated references, junction-node rule stated exactly
Junction-node rule (read directly from `tcad/device/devsim/doping_mapping.py:864,868`, not inferred): DEVSIM's own
equations are `Donors = donor_conc_cm3 * step(x - x_j)`, `Acceptors = acceptor_conc_cm3 * step(x_j - x)`, using DEVSIM's
`step()`, which returns exactly 1 at argument 0 (confirmed directly from 7H-E1's raw per-node arrays: every one of the 1601
nodes at x = 0 in S4 carries the FULL donor_conc_cm3 = 1e18 AND the full acceptor_conc_cm3 = 1e18 simultaneously, giving
NetDoping = 0 there by cancellation, not by either concentration being zero or split). This rule is a property of the
DEVSIM equation string, identical on every mesh (S0, S4, candidate) — it is not something this batch's mesh choice can
change, and it is stated here so the three references below are read correctly:
* **DEVSIM NodeVolume integral**: sum over nodes of (Donors or Acceptors, as DEVSIM's own node model would evaluate them on
  that mesh) x (DEVSIM's own `NodeVolume` on that mesh) — this is what a real DEVSIM device would actually use.
* **Same-mesh exact F2 integral**: the identical per-node concentration array x F2 (7H-B's exact signed-circumcentric dual,
  which sums to the exact triangle area regardless of triangle shape) — a discrete-mesh reference, not a physical one; it
  differs from the geometric continuum integral below by the x = 0 column's own dual-cell contribution (both species carry
  their full concentration there per the rule above), a small (7H-E2 ERRATUM section 4 measured it at S0: ~0.06 % of the
  continuum reference) but real and now-quantified effect, reported again here for the candidate rather than assumed equal.
* **Geometric continuum integral**: `concentration x (25 um^2)`, the idealized area of one half-domain if the junction were
  a zero-width line — a reference point, not a target either value must exactly hit.
None of the three is called "the correct physical answer" anywhere in this batch's report. A candidate whose DEVSIM
integral moves CLOSER to the same-mesh F2 integral (both computed ON THE CANDIDATE's own mesh) is evidence the shape defect
specifically is reduced; comparison to the continuum figure is reported separately and is not by itself a pass/fail test.

## 7. Verdict and stop / rejection conditions
Maximum verdict this batch may register for the candidate, if every check below holds: **`GEOMETRY_CANDIDATE_ONLY`** —
explicitly meaning geometry and DEVSIM's own default integration weight only; not evidence of electrical accuracy, 2D mesh
convergence at any doping level, or applicability beyond section 0's stated scope. All of the following are required, each
reported individually (a partial pass is `CANDIDATE_REJECTED`, listing exactly which check failed, not a silent downgrade):
section 1 input/baseline identity; section 4's bit-identical and geometry-identical invariants; section 3's resolution
ceiling; DEVSIM `ratio = sum NodeVolume / exact area` within tau of the candidate's own mesh (same formula as S4, not a
looser one); every value in section 5/6 finite (no NaN/Inf — a non-finite result is `CANDIDATE_REJECTED`, never silently
dropped); DEVSIM import completes without error and every device is deleted afterward (`get_device_list()` empty).
`CANDIDATE_NOT_RUN` is not applicable here (unlike 7H-E2, this candidate does not depend on a prior stage's verdict).

## 8. Cost cap (fixed now, not raised after seeing a bad result)
Expected wall time budget: under 2000 s total (comparable to 7H-E2's 766 s for five DEVSIM imports; this batch does only
two: the candidate, plus the wafer-mesh regeneration already needed for the identity check). Hard cap: the candidate mesh
may not exceed 500000 Si triangles (~2x S4's 247000) — if the four fixed ring widths in section 2 exceed this, the
candidate is rejected on cost grounds and reported as such, not silently re-tuned to a coarser ring set to force a smaller
mesh after the fact. A global uniform ultra-fine remesh to force ratio near 1 is excluded by section 0 and is not an
allowed fallback.

## 9. Execution boundaries
Audit script only (`docs/audits/2026-09-25-batch7h-e3-junction-refinement-candidate/scripts/`); no change to `tcad/`,
`tests/`, `tcad_2d_stagewise.py`, or any production call site. DEVSIM's `NodeVolume` / `EdgeCouple` are read only, never
written or overridden; no post-hoc normalization to force the ratio to 1; no negative signed value is silently made
positive. No `devsim.solve` call anywhere in this batch (trapped, as 7H-E2 did) — Poisson, drift-diffusion, PN I-V and any
GUI measurement solve are explicitly out of scope and are not run. A DEVSIM-internal or public-API alternative integration
model is not proposed, designed, or implemented in this batch; if one seems warranted by the results, it is left as a
named, separate follow-up, not started here.

## 10. JSON, artifacts, strictness
New JSON is written with `allow_nan=False` (non-finite -> null + explicit status) and re-read with a strict parser, exactly
as 7H-E1/E2. Artifact: summary, sanitized log, all JSON, node arrays (npz) with sha256, the candidate `.vtu`. No threshold,
ring width, resolution target, or cost cap in this PLAN is changed after a result is seen.
