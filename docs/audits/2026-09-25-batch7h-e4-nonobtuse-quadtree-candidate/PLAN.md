# Batch 7H-E4 PLAN: non-obtuse 2:1 quadtree transition candidate (audit-only)
(fixed BEFORE any ViennaPS / DEVSIM execution of this batch; never edited after results)

Execution location: ViennaPS mesh regeneration, DEVSIM import and geometric-model reads run on a GitHub-hosted Windows
runner (`claude/remote-runner`, profile `e4_nonobtuse_quadtree_candidate`). Locally: code reading and writing, static
checks, read-only numpy analysis of existing 7H-E1/E2/E3 arrays (`data/recheck_e2_e3.json`), the exact local-patch proof
(`data/patch_proof.txt`) and synthetic-grid tests only.

## 0. Question, scope, hard limits
7H-E2 and 7H-E3 showed that red-green refinement makes obtuse triangles in its green transition, both with a fixed window
(S4) and with telescoping windows (E3). DEVSIM's NodeVolume rule F3 (7H-B: absolute element couples) then over-integrates.
This batch tests ONE candidate that changes the **transition triangle-generation rule itself**; it does not retune windows.
Question: can the production S4 fine region be kept unchanged, and only its transition band re-triangulated, so that DEVSIM's
default NodeVolume equals the exact area within the float budget, with no loss of junction resolution?
Hard limits: no change to `tcad/`, `tests/`, `tcad_2d_stagewise.py`, the GUI path, DEVSIM, the gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` or any precision flag. DEVSIM NodeVolume / EdgeCouple are read only, never
overwritten or renormalized. `devsim.solve` is trapped (0 calls). No PN / DD / I-V claim. The maximum verdict is
`GEOMETRY_CANDIDATE_ONLY`. Electrical accuracy, 2D mesh convergence, process-order generality and the gate stay separate
follow-ups.
**Scope (stated before results):** only 7H-E1's geometry. That means a single planar Si wafer, one straight junction at
x = 0 spanning the full height, and ViennaPS's structured axis-aligned base grid (MEASURED at S0: 201 x 101 nodes, 40000
right triangles). The construction needs a square base grid and a full-height refinement strip. It is not claimed for
curved surfaces, multiple materials, several or tilted junctions, or unstructured base meshes. Non-obtuse triangulation of
general domains is a harder problem that this batch does not address.

## 1. Mechanism being removed, and the replacement rule (local patch, `data/patch_proof.txt`, exact rational arithmetic)
**Production green cascade.** A base right triangle next to the window has vertices A = (0,0) at x = 0.15 um, and
B = (1,0), C = (1,1) on the x = 0.10 um window edge, in units of grid_delta = 0.05 um. Each pass bisects leg B-C and fans it
to the apex A:

    pass:          1        2        3        4
    fan size:      2        4        8        16
    obtuse:        1        3        7        15
    max angle:  116.565  126.870  131.186  133.152 deg

This reproduces exactly what 7H-E2 measured per origin triangle (1, 3, 7, 15 obtuse; 116.565 / 126.870 / 131.186 /
133.153 deg). The obtuse angle arises because a leg, not a hypotenuse, is bisected from the opposite vertex. Every later
pass re-bisects the same fan.

**Replacement: 2:1-balanced quadtree cells with one fixed transition template.** Coarse triangles are never bisected.
Space is filled with square cells; neighbouring cell sizes differ by at most 2x (2:1 balance). A coarse square whose edge
facing x = 0 carries one hanging midpoint M is split into three triangles. In unit-square coordinates, with the finer
neighbour on the left and LL = (0,0), LR = (1,0), UR = (1,1), UL = (0,1), M = (0,1/2):

    (LL, LR, M)  angles  90.0000 / 26.5651 / 63.4349   exact dots 0, 1, 1/4
    (M, LR, UR)  angles  53.1301 / 63.4349 / 63.4349   exact dots 3/4, 1/2, 1/2
    (M, UR, UL)  angles  63.4349 / 26.5651 / 90.0000   exact dots 1/4, 1, 0

The mirrored template (M = (1,1/2), finer neighbour on the right) has the same angles. Every exact dot product is >= 0, so
no angle exceeds 90 deg. The three areas sum to the square exactly. A cell with no hanging node is split by one diagonal
into two right isosceles triangles.

**Why this removes the mechanism.** In a triangulation with no angle > 90 deg, every element couple (L/2) cot(opposite
angle) is >= 0. DEVSIM's F3 then equals the signed dual F2, which partitions the exact area (7H-B, identified on 18
fixtures). The obtuse-driven over-integration therefore cannot arise, in exact arithmetic. What remains is float rounding,
budgeted in section 5. In this strip only the edge facing x = 0 ever carries a hanging node, so the template above is the
only non-regular pattern.

**Alternatives and why they are not chosen:**

| Alternative | Why not chosen |
|---|---|
| Retune the ring widths | Forbidden. |
| Telescoping red-green (E3) | Measured obtuse. |
| Exact Delaunay flips (E2) | 2800 obtuse triangles remain. |
| x-only column bisection (all right triangles, no transitions) | Leaves the x = 0 line at 0.05 um y-spacing (16x coarser along the junction than S4) and makes aspect-16 elements, so it fails the resolution criteria of section 4. |
| An external quality mesher (Triangle, gmsh) | Min-angle guarantees do not exclude obtuse angles, and no such mesher is installed in this environment. |
| A DEVSIM public-API alternative integration model | Out of scope; a separate design. |

## 2. Input and identity (fail-closed)
1. Regenerate the wafer mesh with 7H-E1/E3's exact calls. sha256 must equal
   `cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a`, else `MESH_INPUT_IDENTITY_FAIL`.
2. S4 is built in-process by the unmodified production `refine_mesh_near(..., |x| < 0.1, levels=4)`. It must reproduce
   7H-E1's S4 x / y sha256 and 7H-E2's `stage_S4.npz` element multiset, the E3 method; else `S4_BASELINE_REUSE_FAIL`.
3. R4 is the sorted y set of S4 nodes on each window-edge line x = +-0.1 um (S0's own float32 value of that line). It must
   have 1601 values, and R4[::16] must equal S0's base rows on that line exactly; else `ROW_NESTING_FAIL`.

## 3. Candidate construction (per side; the negative side mirrors it)
Keep every S4 triangle with all vertices at |x| <= X01, where X01 is S0's own value of the 0.1 um line. This is the fine
region, unchanged. Keep every triangle with all vertices at |x| >= X02 (the 0.2 um line), which is untouched base mesh.
Remove the rest: the 0.1-0.2 um strips, which hold the green fans and one base column.
Fill each strip with square cells.
* x-lines: X01, X0.10625, X0.1125, X0.125, X0.15, X02. The new lines are float32 midpoints of S0 lines:
  X0.125 = mid(X01, X0.15), X0.1125 = mid(X01, X0.125), X0.10625 = mid(X01, X0.1125).
* Rows: R3 = R4[::2], R2 = R4[::4], R1 = R4[::8], R0 = R4[::16].

| sub-column | cell size | rows | split |
|---|---|---|---|
| [X01, X0.10625] | h3 | R3 | template, hanging node from R4 on the fine side |
| [X0.10625, X0.1125] | h3 | R3 | regular, diagonal LL-UR |
| [X0.1125, X0.125] | h2 | R2 | template, from R3 |
| [X0.125, X0.15] | h1 | R1 | template, from R2 |
| [X0.15, X02] | h0 = base | R0 | template, from R1 |

Nodes are deduplicated by exact (x, y). S4 nodes keep their indices; new nodes are appended, and no S4 node is left
unreferenced (checked). Every triangle is emitted counter-clockwise.

## 4. Pass criteria (all required; any failure = `CANDIDATE_REJECTED`, each failed item listed)
**A. Identity.**
* Section 2 items 1-3.
* The candidate's triangles with all vertices at |x| <= X01 equal S4's as a set of vertex-coordinate triples.
* Its triangles with all vertices at |x| >= X02 equal S4's.
* The exact area removed equals the exact area generated.

**B. Geometry.** Exact rational arithmetic on the float coordinates.
* Total area equals S0's, in um^2. The field is named `exact_area_um2`, correcting the E3 unit issue.
* Boundary: 0 original boundary points lost. Every added boundary point lies exactly on an existing boundary line
  (x = +-5 or y = 0 / -5). Bounding box and corners unchanged.
* Contact node coordinate sets at x = +-5 equal S0's. The x = 0 node y-set equals S4's.
* Single Si tag.
* Conforming: every edge has 1 or 2 owner triangles, and every 1-owner edge lies on the outer rectangle.
* Exact orientation > 0 for all triangles: no zero-area or inverted triangle. No duplicate triangle.
* 0 exact positive-area overlaps (7H-A `global_exact_scan`).
* **0 exact obtuse triangles** (exact integer dot products).

**C. Integration (DEVSIM, public API).**
* Import succeeds; contacts `Si_xmin` / `Si_xmax` each have S0's coordinate set.
* **|sum NodeVolume / exact area - 1| <= tau**, with the same tau formula as 7H-E2 / E3: per node
  b_i = 2^-46 / sin(theta_i), and tau = (N_nodes + N_triangles) 2^-52 + max b_i.
* NodeVolume equals F3 within b_i at every node.
* Reported, not gated separately: max |F3 - F2| / F2 per node, and DEVSIM EdgeCouple sign counts (negative / zero /
  positive) against the G1 / G2 predictions.
* A ratio outside tau rejects the candidate whatever else improves.

**D. Junction resolution vs S4.** Exact comparisons of DEVSIM cm coordinates. No single min(edge) is used.
* x = 0 line: node count and y-set equal to S4's, and the y-spacing distribution (min / median / max) reported.
* First node column on each side equal to S4's.
* Bands by edge-midpoint |x|: [0, 0.025), [0.025, 0.05) and [0.05, 0.1) um. In each, the candidate's max edge, max
  horizontal edge and max vertical edge must be <= S4's, and the median is reported.
* Bands [0.1, 0.15) and [0.15, 0.2) um: max edge <= S0's max edge in the same band, and the distributions are reported.

Why these bands, using analytic estimates rather than measurements. The depletion approximation (Sze & Ng, *Physics of
Semiconductor Devices*, 3rd ed., ch. 2) uses:
* V_bi = V_T ln(N_A N_D / n_i^2)
* W = sqrt(2 eps (V_bi - V) / q x (N_A + N_D) / (N_A N_D))
* L_D = sqrt(eps V_T / (q N))

With DEVSIM's parameters (eps 9.8235e-13 F/cm, V_T 0.025887 V, n_i 1e10, N_A = N_D = 1e18 cm^-3), the values already
listed in 7H-E1's PLAN are V_bi 0.95372 V, W 0.0484 um at 0 V, W 0.0555 um at 0.3 V reverse, and L_D 0.0040 um. The bands
cover:
* [0, 0.025): the estimated space-charge half-width at 0 V.
* [0.025, 0.05): the 0.3 V-reverse depletion edge plus a few L_D of carrier tail.
* [0.05, 0.1): the near quasi-neutral region that production S4 refines.
* [0.1, 0.2): the transition to the base mesh.

This batch requires only "no coarser than S4". Whether S4's resolution is itself sufficient is unverified and not claimed.

**E. Doping integrals** (reported, not gated except all finite). Donor and acceptor are recorded separately. Each has three
references, never merged:
* the DEVSIM NodeVolume integral;
* the same-mesh signed-F2 integral;
* the continuum N x 25 um^2.

Also reported: the x = 0 column part, and the formula gap N x H x h / 2 from the 7H-E2 supplementary erratum. Per-node
doping is queried from the production `WaferStateV2.net_doping_at()`. None of these is called the wafer's physical truth.

**F. Cost and hygiene.**
* Triangles <= 500000.
* Expected stage wall time < 2000 s. The subprocess hard timeout is 8000 s. Build and import times are recorded separately.
* All values finite; devices left empty; solve calls 0.
* A globally uniform ultra-fine mesh is not an allowed fallback. The refined region is exactly S4's.

## 5. Artifacts and strictness
Strict JSON (`allow_nan=False`; non-finite -> null plus status; re-read with a strict parser). Artifacts: summary, sanitized
log, all JSON, candidate npz and vtu, and the regenerated wafer vtu, all with sha256. No criterion, band, tau, template or
cost cap in this PLAN is changed after a result is seen.
