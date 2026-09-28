# Batch 7H-E6A PLAN: non-obtuse conforming mesh family L3 / L4 / L5 (geometry only, audit-only)
(fixed BEFORE any code for this batch is written and BEFORE any ViennaPS / DEVSIM execution; never edited after results)

Execution location: ViennaPS wafer-mesh regeneration, DEVSIM import and DEVSIM geometric-model reads run only on a
GitHub-hosted Windows runner (`claude/remote-runner`, profile `e6a_mesh_family`, one request). Locally: code reading and
writing, static checks, read-only analysis of committed artifacts, and synthetic-rectangle arithmetic tests (no ViennaPS,
no DEVSIM import).

## 0. Question, scope, hard limits
Question: can 7H-E4's non-obtuse 2:1 quadtree candidate be turned into a FAMILY of three meshes that share the exact same
physical structure, doping definition and boundary conditions and differ ONLY in junction-region resolution (target
spacing 0.00625 / 0.003125 / 0.0015625 um), each conforming, non-obtuse, area-exact and imported by DEVSIM with default
NodeVolume equal to the exact area within the float budget? If yes, a later, separately pre-registered batch (E6B) may use
the same three meshes for a Poisson mesh-convergence test. This batch runs NO electrical solve.

Hard limits: no change to `tcad/`, `tests/`, `tcad_2d_stagewise.py`, DEVSIM / ViennaPS internals, any precision flag, the
doping model, or the gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`. DEVSIM NodeVolume / EdgeCouple are read only, never
overwritten, rescaled or corrected. `devsim.solve` is trapped; the required count is exactly 0. **Maximum verdict:
`GEOMETRY_FAMILY_CANDIDATE_ONLY`.** Not claimed, whatever the result: Poisson or current 2D mesh convergence, current
accuracy, biased I-V, production step-junction support, arbitrary process-order support. Contact potentials, mass action,
quasi-Fermi flatness and 1-iteration DD convergence are not used anywhere in this batch (7H-E5 ERRATUM 2).

Scope (stated before results): 7H-E1's structure only — one planar Si region, x in [-5, 5] um, y in [-5, 0] um, one
straight step junction at x = 0 spanning the full height, ViennaPS's structured base grid (grid_delta 0.05 um; 201 x 101
nodes, 40000 right triangles), contacts `Si_xmin` / `Si_xmax` on x = -5 / +5. This is an explicit audit structure, not
general process support; no oxidation, etch or implant model is involved.

## 1. Inputs and identity (fail-closed, before any construction; failure = `INPUT_IDENTITY_FAIL`, stop)
1. Wafer mesh regenerated with the unmodified 7H-E1/E2/E3/E4 calls (`vs.make_mask_spans`, `save_volume_mesh`,
   `build_process_result`, `apply_step_junction_doping` with `common_e1.GUI`, i.e. the same outer size, Si material,
   junction position x = 0, donor = acceptor = 1e18 cm^-3 ACTIVE step profile, contact regions/axis and length scale as
   E4/E5). File sha256 must equal `cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a`.
2. E4 reference candidate (binary evidence; `.gitattributes -text` / binary, so checkout-independent):
   `candidate_e4.vtu` sha256 `85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297` and
   `candidate_e4.npz` sha256 `740a643ed6c965b11ea179993eff2701d87b3c0a9a5990ace71fb2e5df482329` — BOTH checked (the
   7H-E5 gap, ERRATUM 1 E1, is not repeated).
3. Text inputs are compared by LF-normalized sha256 (`sha256(bytes.replace(b"\r\n", b"\n"))`), because the runner's
   checkout converts LF to CRLF (7H-E4 `data/eol_normalization_note.txt`): `e4_result.json` LF sha256
   `3fdf069717fff85b28602bc55ae1294e836aa4d6baf5c223c0b5420de97d2299`.
4. `common_e1.GUI` values actually used are recorded verbatim in the result.
5. S0 shape: 201 x 101 distinct x / y lines, 40000 triangles, one material tag. Otherwise `INPUT_IDENTITY_FAIL`.

## 2. Construction rule for level L (L = 3, 4, 5; general code, no per-level literals)
Notation: h_k = 0.05 * 2^-k um; Ny = 100 base rows of cells; `mid32(a, b)` = float32 `(a + b) / 2`, the production
`_refine_once` midpoint. X01, X015, X02 = S0's own float32 x-lines nearest 0.1, 0.15, 0.2 um (per side, mirrored for x < 0).

**Fine region |x| <= X01.** S_L = unmodified production `refine_mesh_near(P0, T0, G0, |centroid_x| < 0.1, levels=L)`.
Every triangle of S_L with all vertices at |x| <= X01 is kept unchanged. (Reason this is uniform for every L: in each pass
the red set is exactly the triangles with |centroid_x| < 0.1; the only non-red triangles touching it are in the
[0.1, 0.15] column, and each has exactly one broken edge (its x = 0.1 leg), so closure never promotes one; the fine region
is therefore L uniform red passes of the base right triangles and holds only right / acute triangles. The runtime checks
below verify this rather than assume it.)

**Base region |x| >= X02.** Every S_L triangle with all vertices at |x| >= X02 is kept unchanged (bit-identical to S0).

**Transition strip X01 <= |x| <= X02** (the S_L triangles there, i.e. the green fans plus one base column, are removed;
every removed triangle must lie inside the strip, else `NONCONFORMING_MESH`). Filled with square cells:
* x-lines: m_0 = X015; m_k = mid32(X01, m_{k-1}) for k = 1..L-1 (m_k ~ X01 + h_k).
* rows: R_L = sorted y of S_L nodes on x = X01; required |R_L| = Ny 2^L + 1 and R_L[::2^L] == S0 rows on X01 exactly
  (else `ROW_NESTING_FAIL`); R_k = R_L[::2^(L-k)].
* columns from the fine side outward:

| column | x-range | cell level | rows | split |
|---|---|---|---|---|
| 1 | [X01, m_(L-1)] | L-1 | R_(L-1) | template, hanging node from R_L on the fine side |
| 2 | [m_(L-1), m_(L-2)] | L-1 | R_(L-1) | regular, diagonal LL-UR |
| 3 .. L | [m_j, m_(j-1)], j = L-2 .. 1 | j | R_j | template, hanging node from R_(j+1) |
| L+1 | [X015, X02] | 0 | R_0 | template, hanging node from R_1 |

  Widths: h_(L-1) + h_(L-1) + h_(L-2) + ... + h_0 = 2 h_0 = 0.1 um for every L. For L = 4 this is exactly 7H-E4's
  column list (X0106, X01125, X0125 = m_3, m_2, m_1).
* Template (7H-E4 `data/patch_proof.txt`, exact dots, every angle <= 90 deg): x > 0 side, finer neighbour on the left,
  M on x = xa: (LL, LR, M), (M, LR, UR), (M, UR, UL); x < 0 side, finer neighbour on the right, M on x = xb:
  (LL, LR, M), (LL, M, UL), (UL, M, UR). Regular column: (LL, LR, UR), (LL, UR, UL) on both sides. All CCW.
* Nodes deduplicated by exact (x, y); S_L node indices are kept, new nodes appended, unreferenced S_L nodes = 0.
* 2:1 balance holds by construction: every template cell's fine side carries exactly one hanging node R_(k+1)[2j+1].

**Predicted sizes, derived from the rule (base grid 200 x 100 cells, fine region = 4 base columns):**
T(L) = 800 * 4^L + 800 * 2^L + 37800;
N(L) = (4 * 2^L + 1)(Ny 2^L + 1) + 2 * 97 * 101 + 2 * 101 + 2 [Ny (3 * 2^(L-1) - 3) + L - 1].

| level | target h at junction (um) | triangles T(L) | nodes N(L) | nodes on x = 0 |
|---|---|---|---|---|
| L3 | 0.00625 | 95400 | 48033 | 801 |
| L4 | 0.003125 | 255400 | 128067 | 1601 |
| L5 | 0.0015625 | 882600 | 441733 | 3201 |

L4's T and N equal 7H-E4's recorded 255400 / 128067. Actual counts different from T(L), N(L) = `CONSTRUCTION_COUNT_MISMATCH`.

## 3. L4 reproduction contract (L4 is the control; failure = `L4_REPRODUCTION_FAIL`)
The L4 mesh is compared with `candidate_e4.vtu` read with meshio (float32 um coordinates), never by file bytes, npz
bytes or serialization order:
1. node coordinate set: set of exact (x, y) float32 pairs equal, and both have no duplicate coordinate;
2. triangle multiset: Counter of the sorted vertex-coordinate triples equal;
3. material tags: identical single tag value;
4. outer boundary node set and contact node sets (x = min, x = max) equal.
Reported, not gated: whether the arrays are also equal in order; per-node DEVSIM NodeVolume vs `candidate_e4.npz`
NodeVolume matched by coordinate.

## 4. Pass criteria per level (all required; each failed item is listed by name)
**A. Construction and nesting.** Counts equal T(L), N(L). Row nesting (section 2). x-lines m_k equal the mid32 recursion.
S_L fine-region triangles and S0 base-region triangles kept as vertex-coordinate triple sets. Unreferenced nodes 0.
Hanging-midpoint ownership: for every template cell, the long edge (LL, UL) (x > 0) / (LR, UR) (x < 0) is absent from the
mesh, and each of its two halves has exactly 2 owner triangles.

**B. Exact geometry (exact integers X = x 2^K on the float32 coordinates, 7H-A construction).**
* B1 orientation: every triangle has exact orientation > 0.
* B2 non-obtuse: every triangle has all three exact dot products >= 0. Any negative = `OBTUSE_TRIANGLE`.
* B3 duplicates: 0 triangles with the same vertex set.
* B4 tiling proof (replaces the global pairwise overlap scan, which is NOT run at any level). Conditions:
  (T1) = B1; (T2) every undirected edge has 1 or 2 owners, and each 2-owner edge occurs once in each direction;
  (T3) every 1-owner edge lies on the outer rectangle, and on each of the 4 sides the 1-owner edges, directed as in their
  triangle, form one gap-free, overlap-free chain from corner to corner in the counter-clockwise direction (bottom +x,
  right +y, top -x, left -y), and every mesh node lying on that side line is a vertex of that chain.
  Proof: with (T2), the 1-chain sum of all triangle boundaries equals the sum of the 1-owner directed edges, which by (T3)
  equals the CCW boundary of the rectangle traversed once. For any point p not on an edge, the winding numbers add:
  sum over triangles of wind(boundary of triangle, p) = wind(boundary of rectangle, p), i.e. 1 inside and 0 outside. By
  (T1) each triangle contributes 1 if it contains p and 0 otherwise, so every point of the rectangle is covered by exactly
  one triangle: no overlap, no gap, no interior hanging node (a T-junction would create an interior 1-owner edge).
  Any failed condition = `NONCONFORMING_MESH`; a condition that could not be evaluated (exception, missing data) =
  `GEOMETRY_PROOF_INCOMPLETE`.
* B5 area: exact area sum of triangles == exact rectangle area from the corner coordinates == exact S0 area (um^2, exact
  rational string). Mismatch = `AREA_OR_VOLUME_FAIL`.
* B6 boundary/contacts: 0 S0 boundary points lost; bounding box equal to S0's; contact node sets on x = -5 / +5 equal to
  S0's (101 each). Material: one tag, equal to S0's tag (`CONTACT_OR_TAG_FAIL` otherwise).

**C. Junction resolution and stepwise spacing.** e0 = max |spacing - 0.05| over S0's row spacings and x-line spacings,
measured in this run on S0 (reference value from the E4 artifact of the same input sha256: 2.8610229492e-7 um). Rounding
bound (derived, not chosen): each mid32 has absolute error <= 2^-22 um for |coordinate| <= 8 um (|a + b| < 16 so
ulp32 <= 2^-20, halved), so after L passes a spacing deviates from its exact dyadic value by <= L 2^-21 um, and the S0
spacing error scales by 2^-L: **delta_L = e0 2^-L + L 2^-21 um** (reference: 1.466e-6 / 1.925e-6 / 2.393e-6 um).
* C1 x = 0 line: node count Ny 2^L + 1; y-set bit-equal to S_L's x = 0 y-set.
* C2 every consecutive y-spacing on x = 0 satisfies |dy - h_L| <= delta_L.
* C3 fine-region x-lines (|x| <= X01): count 4 2^L + 1, every spacing |dx - h_L| <= delta_L.
* C4 transition: every column of cell level k has width |w - h_k| <= delta_L.
* C5 bands by edge-midpoint |x| on the float32 coordinates (7H-E4 band definition): in [0, 0.025), [0.025, 0.05),
  [0.05, 0.1) um, max horizontal and max vertical edge <= h_L + delta_L and max edge <= sqrt(2)(h_L + delta_L); in
  [0.1, 0.15) and [0.15, 0.2) um, max edge <= S0's max edge in the same band. Distributions (min / median / max) reported.
* C6 (across levels, evaluated after all levels): x = 0 y-set of L[::2] == that of L-1 bit-equal, and the fine x-lines of
  L-1 equal those of L at even indices (L = 4, 5).
Any C failure = `RESOLUTION_FAIL`.

**D. DEVSIM import and integration (public API; 7H-E4 section 4C definitions, unchanged).**
* D1 import of the written vtu (meshio round-trip must be bit-exact) with `import_process_result(contact_regions=["Si"],
  contact_axis="x", length_scale_to_cm=1e-4)`, no internal refinement; failure = `DEVSIM_IMPORT_FAIL`.
* D2 DEVSIM node coordinates, as a multiset, equal `(P32[:, :2] * 1e-4).astype(float)` (the production scaling expression,
  `mesh_import.py:989`); element count = T(L); region list ["Si"]; contacts `Si_xmin` / `Si_xmax` with 101 nodes each and
  `coords_sha256` (7H-E2 `read_device` definition) equal to 7H-E4's recorded values.
* D3 |sum NodeVolume / exact area - 1| <= tau, tau = (N_nodes + N_triangles) 2^-52 + max b_i, b_i = 2^-46 / sin(theta_i),
  theta_i the smallest angle of the triangles incident to node i; exact area from DEVSIM's own cm coordinates.
* D4 every node: |NodeVolume - F3| <= b_i F3 (F3 = 7H-B absolute element-couple rule).
* Reported, not gated: max |F3 - F2| / F2, EdgeCouple sign counts, DEVSIM EdgeCouple vs G1 / G2 predictions.
D3 or D4 failure = `AREA_OR_VOLUME_FAIL`. Identical formulas as 7H-E4 (`trace_refine_e2.exact_area`, `node_budget`,
7H-B `formulas.node_areas` / `edge_couple_predictions`), reused read-only; 7H-E2's `analyze()` is NOT called because it
includes the pairwise overlap and Delaunay scans.

## 5. Resources (`RESOURCE_PREFLIGHT_FAIL`, never a silent downgrade of L5)
Budget for this batch: peak process memory <= 8 GiB (private bytes, measured) on the 4-core runner, and <= 120 min total
geometry wall time.
* Analytic envelope before any level: M(L) = 1 GiB + 4 KiB T(L) + 1 KiB N(L) (per-triangle CPython dict/tuple/list objects of
  the edge-owner and element-couple maps, about 1.3 KiB per triangle at peak, doubled, plus DEVSIM storage; 1 GiB fixed for
  interpreter, numpy, DEVSIM, ViennaPS): 1.41 / 2.10 / 4.79 GiB. Time envelope: 3 x 7H-E4's measured stage time scaled by
  T(L) / 255400 (159.3 s): 179 / 478 / 1652 s. Any M(L) > 8 GiB or total time envelope > 7200 s stops before L3.
* Measured gate before L5 (after L3 and L4 finish): predicted L5 peak = max(peak_L4 T5/T4, two-point linear extrapolation
  from L3/L4 in T); predicted L5 time = 1.5 t_L4 T5/T4. If the peak prediction > 8 GiB or elapsed + time prediction > 7200 s:
  L5 is not run, and L5 is recorded `RESOURCE_PREFLIGHT_FAIL` with the numbers. L5 is never replaced by a coarser level.
* Each level runs in its own subprocess (clean DEVSIM state, own peak-memory reading via Windows `GetProcessMemoryInfo`),
  hard timeout 3600 s per level. Recorded per level: build, exact-check, import and NodeVolume wall times, peak working set,
  peak private bytes. Runner: CPU count, physical memory, OS image.

## 6. Artifacts (`ARTIFACT_INCOMPLETE` if anything below is missing, over budget, or fails its sha256 after download)
Strict JSON (`allow_nan=False`; non-finite -> null plus status; re-read strictly). Per level: `level_L<L>.json` (every
check value above, not only booleans), `level_L<L>.npz` (construction float32 points, triangles, tags; DEVSIM x, y,
elements, NodeVolume, F2, F3, edge n0 / n1 / EdgeCouple / EdgeLength), `level_L<L>.vtu` (the imported file). Also
`wafer_volume.vtu`, `e6a_result.json`, summary with sha256 of every file, sanitized log. Public-repository hygiene: no
user path, account or token in any committed or uploaded file (sanitizer and pattern scan); the sanitizer must not change
any numeric result.

## 7. Verdict
`GEOMETRY_FAMILY_CANDIDATE_ONLY` only if L3, L4 and L5 all pass sections 4A-4D, L4 passes section 3, section 4C6 passes,
solve calls = 0, devices left empty, and no artifact is incomplete. Otherwise every failing level and label is listed; a
partial family is never reported as a pass. Labels: `INPUT_IDENTITY_FAIL`, `L4_REPRODUCTION_FAIL`, `NONCONFORMING_MESH`,
`OBTUSE_TRIANGLE`, `AREA_OR_VOLUME_FAIL`, `RESOURCE_PREFLIGHT_FAIL`, `ARTIFACT_INCOMPLETE`, `GEOMETRY_PROOF_INCOMPLETE`,
`ROW_NESTING_FAIL`, `CONSTRUCTION_COUNT_MISMATCH`, `CONTACT_OR_TAG_FAIL`, `RESOLUTION_FAIL`, `DEVSIM_IMPORT_FAIL`,
`SOLVE_CALLED`. Infrastructure failures (runner, checkout, dependency install, upload) are reported as such, separate from
geometric failures. Exactly one remote run; no parameter, width, tolerance or criterion in this PLAN is changed after a
result is seen, and no rerun is made with adjusted parameters.
