# Batch 3A — Directional/selective boundary slivers: cause separation (investigation only)

**Scope kept:** new audit directory only. `tcad/`, `tcad_2d_stagewise.py`, `tests/`, and all earlier Batch 2/3 reports/raw
evidence are untouched (§15). No cutoff, no recipe/window/duration/rate change, no exporter/analyzer/etch-model change, no
commit, no full regression. The currently failing `test_etch_selectivity_real.py` is left as it was.

Environment: Python 3.11.9, numpy 2.4.6, ViennaLS 5.8.5, ViennaPS 4.6.2, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`.
Physical inputs are those of `tests/integration/test_etch_selectivity_real.py`, imported unchanged (oxide 0.2 µm; window
[−2, 2] µm; mask 0.5 µm "Mask"; oxide/plain rate 0.20 µm/s; selective Si 0.04 µm/s; T = 4.75 s; 8 × 3 µm domain).
Only the grid varies (0.10, 0.05, 0.025 µm), as fixed in advance.

## 0. Answers in one table (details in the numbered sections)

| # | Question | Finding | Evidence |
|---|---|---|---|
| 1 | Is the sliver in the native level sets? | **Mask: yes.** The Mask level set (the topmost, whole-surface level set) puts Mask-tagged material inside the window in every Directional/selective run: 0.063 / 0.0035 / 0.00025 µm at g = 0.10 / 0.05 / 0.025. **SiO₂: no** (0 in all three). | §2, T3 |
| 2 | Only in `save_volume_mesh()`? | **SiO₂ slivers: yes, export-only** (`EXPORT_ONLY` at all three grids); they first appear at volume-mesh generation, not in the native level sets and not at the floor step. **Mask slivers: not export-only** (`NATIVE_AND_EXPORT`). | §5, §11 |
| 3 | Connected or isolated? | SiO₂ slivers at g = 0.05 / 0.025 are attached to the outer oxide (components of 410 / 1450 triangles). At g = 0.10 they are two **isolated single-triangle islands** lying along a sloped interface. Mask slivers are small separate components (4 / 10 / 13 triangles) that straddle x = ±2, plus a tiny protrusion of the main mask body (802 triangles) at g = 0.05. | §4 |
| 4 | Proportional to the grid? | Mask penetration/g falls 0.63 → 0.07 → 0.01 (not proportional); SiO₂ export penetration/g is 0.00355 vs 0.00348 for the two finer grids (proportional-looking, coarsest not comparable); area/g² is not constant. **Three samples: no conclusion on convergence.** | §6 |
| 5 | Deterministic? | **Yes.** Same baseline, separate copy: `final_mesh`, unfloored export, native surfaces, floored-copy surfaces are byte-/hash-identical. | §7 |
| 6 | Why only Directional/selective? | Not established. Measured difference: only in Directional/selective does the Mask level-set wall wobble (±1.4–3.3e-3 µm) and the Mask/SiO₂/Si level sets separate near the wall foot; Directional/plain has them coincident to ≤ 2e-5 µm, Isotropic runs put no Mask/SiO₂ in the window. Mechanism is a hypothesis, untested. | §8, §9, §18 |
| 7 | Did the rate-0 Mask level set move? | Mask **body** wall (y 0.25–0.65): unchanged in all seven Directional runs (6 matrix runs + the repeat). The Mask **level set at oxide heights** (y < 0.2, where it is the exposed-surface contour) deviates from x = 2 by up to 3.3e-3 µm in Directional/selective (≤ 2e-5 in plain). **Flagged as a candidate defect** (§10). | §10, T7 |
| 8 | Material map / order / topmost decomposition changed? | Material map and level-set order identical pre/post in all 13 runs (Si, SiO₂, Mask = ids 10, 30, 0). Native nesting consistent (no negative thickness). Export **does** label SiO₂ where the native contours give Mask (g = 0.05 strip) — export and native decompositions disagree there. | §2, §11 |

## 1. Execution matrix (all 13 runs)

Each run starts from an independent copy of the saved baseline (`.vpsd` loaded fresh; sha256 verified before each run);
`vps.Oxidation` calls = 0 in every run. Run 9 is the determinism repeat (separate copy of the same g = 0.05 baseline).
Etch wall time per run 0.03–0.46 s.

| # | grid | model / recipe | SiO₂ native-vs-export | Mask native-vs-export |
|---|---|---|---|---|
| 1 | 0.10 | directional / plain | **NATIVE_ONLY** | ABSENT_BOTH |
| 2 | 0.10 | directional / selective | EXPORT_ONLY | NATIVE_AND_EXPORT |
| 3 | 0.10 | isotropic / plain | ABSENT_BOTH | ABSENT_BOTH |
| 4 | 0.10 | isotropic / selective | ABSENT_BOTH | ABSENT_BOTH |
| 5 | 0.05 | directional / plain | ABSENT_BOTH | ABSENT_BOTH |
| 6 | 0.05 | directional / selective | EXPORT_ONLY | NATIVE_AND_EXPORT |
| 7 | 0.05 | isotropic / plain | ABSENT_BOTH | ABSENT_BOTH |
| 8 | 0.05 | isotropic / selective | ABSENT_BOTH | ABSENT_BOTH |
| 9 | 0.05 | directional / selective (**repeat**) | EXPORT_ONLY | NATIVE_AND_EXPORT |
| 10 | 0.025 | directional / plain | ABSENT_BOTH | ABSENT_BOTH |
| 11 | 0.025 | directional / selective | EXPORT_ONLY | NATIVE_AND_EXPORT |
| 12 | 0.025 | isotropic / plain | ABSENT_BOTH | ABSENT_BOTH |
| 13 | 0.025 | isotropic / selective | ABSENT_BOTH | ABSENT_BOTH |

Definitions used for the classification (§5): *native present* = the material's native occupancy inside the window exceeds
1e-9 µm (a float-zero test; the raw profiles are stored, so any other threshold can be applied later); *export present* =
at least one material triangle has positive-area intersection with the window slab.

## 2. Native level-set results (viennals `ToSurfaceMesh`; `Mesh.getLines()` supplies real segment connectivity)

API introspection (real): `vls.Mesh` exposes `getNodes`, `getLines`, `getTriangles`, `getCellData`, …; the domain exposes
`getLevelSets`, `getMaterialMap`, `getNumberOfLevelSets`. Connectivity **is** available, so no native judgment is left as
`UNKNOWN_NATIVE_CONNECTIVITY`.

**Material map and level-set order.** Pre and post identical in all 13 runs: level-set 0 = Si (id 10), 1 = SiO₂ (id 30),
2 = Mask (id 0), 3 level sets, materials-in-domain unchanged.

**Occupancy of SiO₂ / Mask inside the window.** Level sets are nested (LS_k = everything below surface k), so material k
occupies, in a column x, the interval between the highest crossings of LS_{k−1} and LS_k: thickness_k(x) = ymax_k − ymax_{k−1}.
Sampled, per window edge, at offsets s inward from the edge of `g·2⁻ʲ` (j = 0…13, so the smallest is `g/8192`), `k·g/100` (k = 1…100) and
`k·g/2` out to 0.5 µm, plus a `g/10`-step sweep of the whole window; these are descriptive sample positions, not a criterion. Maximum x-penetration from the window edge:

| run | material | penetration (µm) | in units of g | sampled positions with material | upper/lower level-set height at those columns |
|---|---|---|---|---|---|
| 2 (g 0.10 dir/sel) | Mask | **0.063** | 0.63 | 160 | upper y ∈ [−0.099, 0.148], lower y ∈ [−0.099, −0.009] |
| 6 / 9 (g 0.05 dir/sel) | Mask | **0.0035** | 0.070 | 36 | upper y ∈ [−0.049, 0.197], lower y ∈ [−0.049, −0.029] |
| 11 (g 0.025 dir/sel) | Mask | **0.00025** | 0.010 | 16 | upper y ∈ [0.057, 0.124], lower y ∈ [−0.060, −0.057] |
| 2, 6, 9, 11 | SiO₂ | 0 | 0 | 0 | — |
| 1 (g 0.10 dir/plain) | SiO₂ | 1.95e-4 | 0.002 | 10 | upper y ∈ [−0.098, 0.045] |
| all other runs | SiO₂, Mask | 0 | 0 | 0 | — |

The Mask value is the same at every float-zero threshold tried (1e-12, 1e-9, 1e-6, 1e-4; the one exception is 0.062 vs 0.063
at g = 0.10, thr 1e-4) — the threshold does not decide the result. Minimum thickness over all samples is 0 in every run:
the level sets stay nested (no inversion). Central core (fixture core window): SiO₂ and Mask thickness are 0 in every
sampled column in all 13 runs; the material that remains natively is confined to the window edge.

**What the native Mask "sliver" is (raw segments, `raw/matrix_results.json`; `scripts/print_foot.py 0.05 directional_plain directional_selective`).**
Directional/plain, g = 0.05: LS_Mask, LS_SiO₂ and LS_Si coincide along a vertical wall at x = 2.00000 (deviations ≤ 2.5e-5 µm) from the
cavity floor to the mask top. Directional/selective, g = 0.05:
* LS_Mask wall at oxide heights is not straight: x = 2.00171 (y = 0), 1.99857 (y = 0.05), 1.99957 (y = 0.10), 1.99991 (y = 0.15), 2.00000 (y = 0.20);
* LS_SiO₂ at the same heights sits further out: 2.00485, 2.00043, 2.00039, 2.00006, and its top is chamfered ((2.00006, 0.15) → (2.05, 0.20));
* LS_Si rises along a slope ((2.0, −0.0287) → (2.05, 0)), and the cavity edge near the wall is a fillet from (1.90, −0.15) to (2.0, −0.016).
Where LS_Mask lies left of LS_SiO₂ the region between them is "Mask" by nesting; that region reaches into x < 2.
At g = 0.10 the same structure appears as a long thin wedge along the sloped cavity edge: LS_Mask (1.93625, −0.10) → (2.0, −0.00496) versus
LS_SiO₂ (1.93625, −0.10) → (2.0, −0.00886), i.e. 3.9e-3 µm apart at x = 2, converging to 0 by x ≈ 1.936 (the 0.063 µm "penetration").

## 3. Exported volume-mesh triangles (the step's own `final_mesh`)

Positive-area intersection of material triangles with the window slab (x ∈ [−2, 2]); areas are clipped to the window.

| run | material | crossing triangles (area > 0) | total clipped area (µm²) | max x-penetration (µm) | components crossing the window | centre line x = 0 | core columns with material |
|---|---|---|---|---|---|---|---|
| 2 (0.10 d/s) | SiO₂ | 2 | 4.606e-5 | 0 (islands; touch no edge) | 2 | absent | 0/41 |
| 2 | Mask | 2 | 9.962e-5 | 0.0404 | 2 | absent | 0/41 |
| 6, 9 (0.05 d/s) | SiO₂ | 12 | 1.484e-5 | 1.775e-4 | 2 | absent | 0/41 |
| 6, 9 | Mask | 13 | 1.685e-4 | 2.751e-3 | 4 | absent | 0/41 |
| 11 (0.025 d/s) | SiO₂ | 10 | 4.653e-6 | 8.69e-5 | 2 | absent | 0/41 |
| 11 | Mask | 10 | 1.564e-5 | 2.99e-4 | 2 | absent | 0/41 |
| all Directional/plain and all Isotropic runs | SiO₂, Mask | 0 | 0 | 0 | 0 | absent | 0/41 |

Every count above is also the count for "area > ε² and width > ε" (ε = 1.91e-6 µm, four float32 ulps of the largest coordinate):
the slivers are 30–1400 × wider than the geometry epsilon, i.e. they are not float noise. Vertex indices in these meshes are shared
(unique-xy points = points), so triangle adjacency by shared edge is meaningful.

## 4. Component connectivity (shared-edge triangle adjacency over the whole mesh)

| run | material | component (whole-mesh triangles / in window) | clipped x-range | edge? | wholly-outside triangles exist | verdict |
|---|---|---|---|---|---|---|
| 2 | SiO₂ | 1 / 1 (two, left and right) | [1.939, 1.997] | none | no | **isolated island**; near-collinear vertices along the sloped cavity edge (y ∈ [−0.095, −0.012]) |
| 2 | Mask | 4 / 1 (two) | [1.9596, 2.0] | x = 2 | yes | small component straddling the wall |
| 6 | SiO₂ | 410 / 6 (two) | [1.99982, 2.0] | x = 2 | yes | attached to the 410-triangle outer oxide |
| 6 | Mask | 10 / 5–6 (two) | [1.99725, 2.0] | x = 2 | yes | **10-triangle component, separate from the main mask body**, straddling x = 2 (its full extent reaches x ≈ 2.004) |
| 6 | Mask | 802 / 1 (two) | [1.99991, 2.0], y ∈ [0.150, 0.200] | x = 2 | yes | protrusion of the 802-triangle **main mask body** into the window by 9.1e-5 µm |
| 11 | SiO₂ | 1450 / 5 (two) | [1.99991, 2.0] | x = 2 | yes | attached to the 1450-triangle outer oxide |
| 11 | Mask | 13 / 5 (two) | [1.9997, 2.0] | x = 2 | yes | 13-triangle component straddling the wall |

Caveat on the flag `connected_to_material_outside_window`: it is true for a component that merely extends past the window edge,
including the 4-, 10- and 13-triangle wedges; it does **not** mean "attached to the bulk". Read it together with the whole-mesh
triangle count. Connectivity is triangle adjacency only; no bounding-box overlap was used.

## 5. Native versus export classification

Per run, see §1. Summary for the three questions the prompt singled out:

* **Directional/selective Mask sliver: `NATIVE_AND_EXPORT`** at all three grids (native 0.063 / 0.0035 / 0.00025 µm, export 0.0404 / 0.00275 / 0.000299 µm; the export value is smaller at the two coarser grids and larger at 0.025).
* **Directional/selective SiO₂ sliver: `EXPORT_ONLY`** at all three grids. Native SiO₂ occupancy in the window is 0 (thickness ≤ 1e-9 at every sampled column). Example, g = 0.05, y = 0.10: native contours give LS_Mask wall x = 1.99957 and LS_SiO₂ wall x = 2.00039, so the point (1.9998, 0.10) is solid and inside the Mask region but outside SiO₂; the exported triangle (1.99995, 0.10)–(2.0, 0.05)–(2.0, 0.10) is tagged **SiO₂**. (Inference from zero-contours interpolated by `ToSurfaceMesh`, not from the raw grid values `WriteVisualizationMesh` uses — see §18.)
* **The three controls:** Directional/plain and both Isotropic runs have no SiO₂ or Mask in the window in either view at g = 0.05 and 0.025; at g = 0.10 Directional/plain shows a native SiO₂ residue of 1.95e-4 µm (`NATIVE_ONLY`, no exported triangle) — native and export can disagree in either direction.

`EXPORT_ONLY` does not mean the residue may be silently dropped; this audit only separates the cause.

## 6. Grid scaling (dimensionless)

Directional/selective (the only run family with a sliver):

| material | g | native pen/g | export pen/g | export area/g² |
|---|---|---|---|---|
| Mask | 0.10 | 0.63 | 0.404 | 0.00996 |
| Mask | 0.05 | 0.070 | 0.0550 | 0.0674 |
| Mask | 0.025 | 0.010 | 0.0120 | 0.0250 |
| SiO₂ | 0.10 | 0 | 0 (isolated islands, no edge contact) | 0.00461 |
| SiO₂ | 0.05 | 0 | 0.00355 | 0.00594 |
| SiO₂ | 0.025 | 0 | 0.00348 | 0.00745 |

Allowed statements: the Mask penetration measured in grid units **decreases** with refinement (it does not scale proportionally to
g); the SiO₂ export penetration in grid units is nearly equal at the two finer grids (a tendency to scale with g), but the coarsest
grid's SiO₂ residue is a different kind of object (isolated islands), so the three samples are not one family; Mask export area/g²
is not monotone (0.010, 0.067, 0.025). **Three samples: no conclusion on convergence, and grid scaling alone does not establish a
numerical artifact.** All Directional/plain and Isotropic values are 0 (SiO₂ native 0.002 g at g = 0.10 in run 1).

## 7. Determinism (run 6 vs run 9, same baseline `622f178d…`)

| artifact | run 6 | run 9 | equal |
|---|---|---|---|
| `final_mesh` sha256 | `50b576ad6a234a82e9b9989964a2ca739aa4348758d874b5bb80d40492e7e0b2` | same | yes |
| unfloored export sha256 | `620d66487accc134d5d0eac0a5d7552d86919ef30eec20045eef8133732e13a2` | same | yes |
| native post-surface arrays (nodes + lines, all level sets) | `e56aafc4755d9488e724aa292fcd53ed46b7c754f5722ff3e5601224d343ff2a` | same | yes |
| native floored-copy surface arrays | equal | | yes |
| every volume metric incl. all components | identical | | yes |

The sliver is reproduced bit-for-bit; it is not run-to-run noise. (The whole matrix was executed three times while the
measurement code was being corrected — see §18; the classifications, penetrations and determinism results read from each execution were the same;
`raw/matrix_results.json` is from the last one.)

## 8. Directional plain versus selective

Same physical window, same 4.75 s. Differences measured natively at g = 0.05 (raw segments in §2):
* plain: Mask/SiO₂/Si level sets coincide on a vertical wall at x = 2 (≤ 2.5e-5 µm), Si etched 0.75 µm;
* selective: Si etched only 0.15 µm, the cavity edge near the wall is a rounded fillet, the oxide level set is chamfered, and the Mask level set at oxide heights deviates from x = 2 by 1.7e-3 µm outward / 1.4e-3 µm inward (0.034 g), giving the Mask-tagged wedge.
Code fact (read from `tcad/process/etching/directional.py`): plain passes `maskMaterial=Mask` (a binary gate); selective passes
`materialRates` with `(rate, 0.0)` per material and Mask `(0.0, 0.0)` — a different ViennaPS overload in which the mask stays a
material with a zero rate inside the velocity field. That the overload or the rate contrast (0.20 / 0.04 / 0) causes the foot geometry is **not tested** here.

## 9. Directional versus Isotropic

* Isotropic/plain and Isotropic/selective: no SiO₂ or Mask in the window in either view at every grid. Their foot geometry is a large outward undercut beneath the mask (foot deviation 0.02–0.46 µm toward the mask side, from the "nearest wall crossing" measure in `summary_tables.txt` T7, which can pick a different branch of the contour at different heights), i.e. the cavity edge recedes away from the window rather than leaving a wedge inside it.
* Isotropic/selective also uses `materialRates` (Mask 0) yet produces no sliver, so `materialRates` alone is not sufficient.
* Separate observation, **not analysed further:** at g = 0.10 only, both Isotropic runs show the Mask level-set wall 0.043 µm outward at a single height y = 0.25 (0.05 above the oxide top); at y ≥ 0.30 it is 2.0 exactly; at g = 0.05 and 0.025 no such deviation.

## 10. Did the rate-0 Mask move natively? (flagged)

| quantity | Directional/plain | Directional/selective |
|---|---|---|
| Mask top surface at x = ±(2 + 0…1.5 µm) (`max_abs_delta_top_um`, all 13 runs) | 0 | 0 |
| Mask wall x at y = 0.25…0.65 (pre vs post) | 0 change | 0 change |
| Mask level-set wall nodes at y ∈ [0, 0.2) vs x = 2: outward max (µm) | ≤ 5e-14 | 3.33e-3 (g 0.10), 1.71e-3 (0.05), 1.48e-3 (0.025) |
| … inward max (µm) | ≤ 2.1e-5 | 2.4e-5 (0.10), 1.43e-3 (0.05), 3.0e-4 (0.025) |
| max deviation / g | ≤ 2e-4 | 0.033, 0.034, 0.059 |

**Flag:** in Directional/selective the Mask level set deviates from its pre-etch wall at the 1e-3 µm level in the oxide-height
region, and Mask-tagged material exists natively inside the open window (up to 0.063 µm at g = 0.10). A caution about
interpretation: the "Mask" level set in ViennaPS is the topmost, whole-surface level set, so below y = 0.2 its contour is the etched
surface, not a mask face; the audit cannot separate "the mask moved" from "the etch front near the wall is imperfect".
An earlier metric (change of mask thickness between LS_Mask and LS_SiO₂, and nearest-node distance) was **confounded** — an
undercut beneath the mask lowers the lower level sets and inflates it (values up to 0.9 µm in the Isotropic runs while the mask top
is unmoved); it was replaced by wall positions and node coordinates, and is kept in the raw JSON as `mask_body_movement_pre_vs_post__CONFOUNDED`.

## 11. Native level set versus surface mesh versus volume mesh (same post-domain, four stages)

| stage | what | Directional/selective SiO₂ in window | Mask in window |
|---|---|---|---|
| A | native level sets (`ToSurfaceMesh`) | absent (all 3 grids) | present (all 3 grids) |
| B | level sets of the floored export copy (`_floored_copy_for_export`: Expand + Box INTERSECT) | absent | present, same numbers as A |
| C | volume mesh of the **un**floored copy (`saveVolumeMesh`) | **present** (2 / 12 / 10 triangles) | present (2 / 13 / 10) |
| D | volume mesh of the floored copy (= `save_volume_mesh`) | present, same triangle counts as C | present, same as C |

The SiO₂ residue first appears at **volume-mesh generation** (A, B → C); the floor step is not its origin (B has none; C and D have equal counts).
In all 13 runs the step's `final_mesh` is byte-identical to the floored-copy export (D), and exporting did not alter the post
domain (native surface hash unchanged). `Domain.saveSurfaceMesh` (VTP with material ids) was **not** analysed separately; the
level-set surface mesh used here is viennals `ToSurfaceMesh` of each level set (stages A/B).

## 12. `_reach()` midpoint probe (current analyzer, reproduce-and-report)

`raw/synthetic_analyzer_probes.json`, `scripts/synthetic_analyzer_probes.py` (calls `_reach` and `_Ctx.sections` on one isolated
interval; nothing in `tcad/` modified).
* **Valid, non-overlapping meshes:** the overlayer bottom and the Si top are both straight across one common interval (every mesh vertex is a partition breakpoint), so contact at the midpoint implies contact along the interval. A fixed-seed random sweep of 4000 cases (end gaps 0 or 1e-9…1e-1 µm) found **111 disagreements between the midpoint rule and the exact end-gap rule, all with the larger end gap between 1.01 ε and 2.0 ε** (ε = 4.77e-7 µm; ≤ 9.5e-7 µm). No disagreement at any larger gap.
* **Invalid (overlapping) geometry:** Si top rising 0 → 0.0008 µm (inside the 0.001 µm tolerance) with an overlayer bottom flat at 0.0004 µm makes the overlayer penetrate Si on the right half; the midpoint rule returns `overlain`. The analyzer has no overlap check; a ViennaLS material export cannot produce overlapping material triangles, so this is a limit of the description ("whole measured run"), not a reproduced failure on a valid export.
* Whole-run sanity: flush overlayer → `overlain`, none → `exposed`, flush on half only → `cannot_be_inferred`.
**Result: no wrong `reach` reproduced on valid geometry beyond the ε-scale band; one wrong answer reproducible on invalid geometry; the docstring's "whole measured run" overstates what is checked (one midpoint scanline per interval).**

## 13. Same-height component switching (current analyzer)

Synthetic conforming meshes; Si top −0.15 µm in post, pre flat; the post run is built from **two different Si bodies** (different bottoms).

| gap between the bodies | triangle-adjacency components of Si | analyzer result |
|---|---|---|
| 0 (touch at a vertex / T-junction) | 2 | `etched` 0.15, run **[−1.0, 1.0]**, 5 intervals |
| 0.5 ε | 2 | `etched` 0.15, run [−1.0, 1.0] |
| 2 ε | 2 | `etched` 0.15, run [−1.0, 0.3] (stops at the gap) |
| 1e-4 µm | 2 | `etched` 0.15, run [−1.0, 0.3] |

**Reproduced:** when the gap is below about ε the analyzer's x-partition merges the two vertices, the interval carries no material
gap, and the flat run continues from one body into the other — a "paired flat interior" assembled from two triangle components that
only share a height. At ≥ 2 ε the run stops. The analyzer never inspects component identity, and pre/post components are paired
by x position only.

## 14. Raw files and sha256

All under `docs/audits/2026-09-21-batch3-directional-selective-slivers/`. `raw/SHA256SUMS.txt` lists the 37 files of `raw/` and `scripts/`
(sha256, bytes, path) and is the authority (this `REPORT.md` is not in it); the non-mesh files:

```
82151528baccf1019fb3159065f378dab63f3b0a270d01035f4ce42c1c9412d9  2305192  raw/matrix_results.json
1336d9ea2deb1c0b0ea9b4495e85dec6aedcba1544c68067a13809d418f51db3  27994    raw/summary_tables.txt
5a5f94071f0386623b6c37c2934b7c2bc6aa175775d90e305a3b67b3ca47fb01  4489     raw/synthetic_analyzer_probes.json
3f0523aa2c34b9c87dddbbe1b693fbe9edb47e32bdd7128e0219059b05c9b59b  20523    scripts/audit_common.py
25ebdfab08392f7b0b41c12de5756b3943c323818a0449fb9c2d69a7d8dac96f  1462     scripts/print_foot.py
3b637369a806c6809806a1db7c420fc9849208ac6124a077a4b808291a76015f  8424     scripts/run_matrix.py
de90d915d18f6730d9bfa79bd0d5d9878f7a4258a5ad1fe99067480b87ae0d76  10717    scripts/summarize_matrix.py
d6096f0387de0bc8580a39d517adb82c4231c7c84cbc66fe09de02ce075099fa  6592     scripts/synthetic_analyzer_probes.py
```
plus 29 volume meshes in `raw/meshes/` (3 baselines, 13 `*_final_floored.vtu`, 13 `*_unfloored.vtu`); hashes in `raw/SHA256SUMS.txt`.
Reproduce: `python scripts/run_matrix.py` (13 runs, ≈ 90 s), `python scripts/summarize_matrix.py`, `python scripts/synthetic_analyzer_probes.py`,
`python scripts/print_foot.py 0.05 directional_plain directional_selective`. Scripts derive the repo root from their own location.

## 15. Evidence that production and tests were not changed

* Every file under `tcad/` and `tests/` (excluding `__pycache__`/`*.pyc`), `tcad_2d_stagewise.py`, `CLAUDE.md`, `README.md`, `pyproject.toml`
  and every `docs/` file outside this audit directory has a last-write time **earlier** than the creation time of this audit's first file
  (15:20:40); the scan returned no file (0 `.pyc` files newer than that moment either; `__pycache__` is git-ignored).
* `git status --short -- tcad tests tcad_2d_stagewise.py` shows exactly the Batch 3 end state (same modified/added/untracked set as before this audit); the
  only new untracked path from this audit is `docs/audits/2026-09-21-batch3-directional-selective-slivers/` (`docs/audits/` shows as one untracked directory).
* The scripts import and call project code (fixture, `etch_diagnostics`, `io._floored_copy_for_export`) but never write to it. One scratch-only
  substitution: the fixture's `derive_regions` protected-band rule is empty on this 8 µm domain at g = 0.10 (`protected band (-3.2, -3.35) is empty`),
  so `audit_common.py` substitutes regions **for that grid only**, recorded in `derive_regions_fallbacks`; those regions feed only fixture side-measurements, never a verdict here.

## 16. `git diff --check`

```
$env:GIT_CONFIG_GLOBAL='NUL'; $env:GIT_CONFIG_NOSYSTEM='1'; git diff --check
(no output)   rc=0
```
Tracked files only. The new audit files (untracked) were scanned separately: after generating them with LF-only writers and normalizing three CRLF outputs to LF,
0 files contain CRLF and 0 have trailing whitespace.

## 17. HEAD and commits

HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`; `git log 3ba9404..HEAD` is empty; nothing committed, nothing reset/stashed/cleaned/reverted.

## 18. Remaining UNKNOWNs and limits of this audit

1. **Why Directional/selective only.** Facts: overload (`materialRates` vs `maskMaterial`), rate contrast (0.20 / 0.04 / 0), direction dependence. Untested discriminators (not run, because §3 forbids changing recipes): Directional through `materialRates` with equal rates; Isotropic/selective is already a control that uses `materialRates` without a sliver.
2. **What rule `WriteVisualizationMesh` uses to tag a triangle.** The SiO₂-in-Mask-region finding (§5) compares triangle tags with zero contours interpolated by `ToSurfaceMesh`; the exporter uses grid level-set values. Consistent with, but not a proof of, a tagging mismatch inside cut cells.
3. **Native occupancy is derived** from nested level-set crossings; it assumes each level-set surface is single-valued in y at the sampled columns near a vertical wall (columns within a sub-cell of the wall). The g/100- and geometric-offset sampling is dense but finite; slivers narrower than the smallest offset (≈ 6e-6 µm at g = 0.05) would be missed natively (none narrower than that was found in the export either: the narrowest export penetration is 8.7e-5 µm).
4. **The "Mask moved" flag (§10)** cannot separate mask motion from the etch front near the wall, because the Mask level set is the topmost whole-surface level set below y = 0.2.
5. **Single window, single domain, single oxide thickness, one recipe family.** Other windows, oblique directional angles, two-window masks were not run; three grids cannot establish a convergence order.
6. **`Domain.saveSurfaceMesh` (VTP)** not analysed separately (§11).
7. **The 0.043 µm Isotropic wall deviation at g = 0.10, y = 0.25** (§9) not investigated.
8. The matrix was executed three times while measurement code was corrected (a confounded mask-motion metric was replaced; raw wall geometry was added). The values compared across executions were unchanged; only the last execution's raw file is kept.
9. The component flag `connected_to_material_outside_window` is easy to misread (§4).

## 19. Proposed state contract (proposal only — nothing implemented)

The current analyzer knows `CLEARED`, `POST_ONLY`, `ETCHED`, `UNCHANGED`, `ROSE_OR_INDETERMINATE`, `NO_PAIRED_FLAT_INTERIOR`. Proposal, using exactly the vocabulary requested:

| state | definition | what it preserves |
|---|---|---|
| `FULLY_CLEARED_IN_WINDOW` | post has **no** positive-area intersection of the material with the whole window | nothing residual exists |
| `CENTER_CLEARED_RESIDUAL_REMAINS` | material is gone in the paired centre region **and** positive-area residual exists elsewhere in the window | both facts: centre removed, boundary residual present — it neither removes nor ignores the residual |
| `POST_ONLY_RESIDUAL` | pre has no window intersection, post has one; physical creation/exposure **not** proven | presence only; no displacement, no "newly exposed" |
| `PAIRED_VERTICAL_DISPLACEMENT` | the current paired centre-connected flat run (vertical displacement only) | the number, with its run extent |
| `AMBIGUOUS` | the pairing is not proven (multi-component, no flat interior, non-conforming/hairline-merged bodies, node-centred disagreement) | a refusal with the reason |

The states are not exclusive per window: one material can be `PAIRED_VERTICAL_DISPLACEMENT` **and** carry residual metadata. For `…_RESIDUAL…`
states the result should carry, without any cutoff: residual area, x/y extent, which window edge it touches, its whole-mesh
triangle count, whether it is an isolated island, and the evidence source (`export_mesh_only` in the GUI path, since the GUI does not
hold the native domain). How the 12 real observations would read: Directional/selective SiO₂ (all grids) → `CENTER_CLEARED_RESIDUAL_REMAINS`
(the g = 0.10 residue additionally marked isolated-island); Directional/selective Mask → `POST_ONLY_RESIDUAL`; Directional/selective Si →
`PAIRED_VERTICAL_DISPLACEMENT`; the three controls' SiO₂ → `FULLY_CLEARED_IN_WINDOW`, Mask → no line.
Decisions for Codex before any implementation: (a) whether `EXPORT_ONLY` residue may be reported as "residual" when the native domain is not
available to the GUI diagnostic; (b) whether hairline-merged bodies (§13) should become `AMBIGUOUS`; (c) whether the `_reach` docstring
should be narrowed or the check extended to interval ends. No implementation or test change is made in this batch.
