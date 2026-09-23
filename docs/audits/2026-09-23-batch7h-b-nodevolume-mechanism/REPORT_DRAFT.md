# Batch 7H-B Phase A: public contract, analytical rules and tolerances (fixed BEFORE any DEVSIM run)

Written and hashed before the first DEVSIM import in this batch (`data/draft_sha256_before_devsim.txt`).
Nothing below may be changed after results are seen; later findings go to `REPORT.md`.

## 1. Public DEVSIM contract (devsim.net/models.html, fetched 2026-09-23, copy in `data/manual/`)

Paraphrased from the official manual, section "Equation and models", with short quotes:

* DEVSIM assembles PDEs by the control-volume approach. In 2D, the shaded area around a node is "the node
  volume"; edge fluxes are integrated "with respect to the perpendicular bisectors" crossing each triangle edge.
* `NodeVolume` (node model): "The volume of the node", used for volume integration of node models.
* `EdgeCouple` (edge model): "The length of the perpendicular bisector of an element edge", used for surface
  integration of edge models.
* `EdgeNodeVolume` (edge model): "The volume for each node on an edge".
* `EdgeLength` (edge model): the distance between the two nodes of an edge.
* `ElementEdgeCouple` (element edge model): perpendicular-bisector length for one element edge.
* `ElementNodeVolume` (element edge model): "The node volume at either end of each element edge".
* Public `EdgeNodeVolume` example in the manual ("Edge volume model"): the user-defined model
  `0.5*EdgeCouple*EdgeLength` is set as both `edge_node0_volume_model` and `edge_node1_volume_model`.
* `element_from_node_model(node_model)` creates `nmodel@en0/@en1` (the element edge's nodes) and `nmodel@en2`
  (the opposite node in 2D); `edge_from_node_model` creates `nmodel@n0/@n1`. With the public `node_index` node
  model these give the endpoint mapping of every edge and element-edge value.
* The manual does NOT state how a node volume is formed from a triangle whose circumcenter lies outside it.

## 2. Analytical rules (implemented in `scripts/formulas.py`, units cm and cm^2)

Triangle (i, j, k), theta_v the angle at v, cot sign from the dot product only.

| Rule | Per-(triangle, node) area at i |
|---|---|
| F1 barycentric | area / 3 |
| F2 signed circumcentric | A_i = (\|ij\|^2 cot theta_k + \|ik\|^2 cot theta_j) / 8 |
| F3 per-edge absolute | same with \|cot theta_k\|, \|cot theta_j\| |
| F4 per-(triangle,node) absolute | \|A_i\| |
| F4b per-node absolute | \| sum over triangles of A_i \| |
| F5 mixed Voronoi (Meyer et al. 2003) | non-obtuse: F2; obtuse: area/2 at the obtuse vertex, area/4 at the others |
| F6a | sum over edges at the node of built-in `EdgeNodeVolume` (documented "volume for each node on an edge") |
| F6b | sum over edges of `0.5*EdgeCouple*EdgeLength` (manual example expression, per node) |
| F6c | sum over edges of `0.25*EdgeCouple*EdgeLength` (region node - edge midpoint - bisector segment: base = couple, height = L/2) |
| F6d | sum over element edges at the node of built-in `ElementNodeVolume` |
| F6e | sum over element edges of `0.25*ElementEdgeCouple*L` |

Edge couples: G1 = sum over the edge's triangles of the SIGNED element couple (L/2) cot theta_opp;
G2 = the same with \|cot\|. `EdgeCouple` and `ElementEdgeCouple` are compared against both.

Relations fixed a priori: F6b = 2 x F6c identically, so F6b cannot also match if F6c matches.
Pure-math check before DEVSIM (`test_formulas.py`, 30/30): the first draft of one test summed 0.25*c*L once
per element edge and failed at area/2; each element edge contributes 0.25*c*L to EACH endpoint. The test was
corrected before any DEVSIM run; no DEVSIM rule was involved.

## 3. Expected sign and total per triangle class

| Class | F1 | F2 | F3 | F4 / F4b | F5 |
|---|---|---|---|---|---|
| acute | sum = area | all A_i > 0, sum = area | = F2 | = F2 | = F2 |
| right | sum = area | right-angle cot = 0, sum = area, circumcenter on hypotenuse | = F2 | = F2 | = F2 |
| obtuse | sum = area | the edge opposite the obtuse angle carries a negative term; sum = area | sum > area (T4: 1.714x, T5: 24x of area) | sum >= area | sum = area |

Analytic predictions on the input coordinates: `data/analytic_predictions.json`,
sha256 `83d074f7ca69c2bd662af87d104cc2b6596488a4a15db380d69026558e328653`.

## 4. Comparison tolerance (fixed)

```
EPS          = 2.220446049250313e-16   (float64 machine epsilon)
ABS_FACTOR   = 256
REL_TOL      = 1e-11
abs_tol      = ABS_FACTOR * EPS * max(domain_area_cm2, 1e-300)
match(d, p)  : |d - p| <= abs_tol + REL_TOL * |p|      (per node, per edge, and for sums)
```

Coordinate representation: synthetic fixtures are passed to DEVSIM as float64 `um * 1e-4`; the L3 mesh is
passed as float64 copies of float32 `um * 1e-4` products (the Batch 7F import helper). Every analytical
prediction is evaluated on the coordinates read BACK from DEVSIM's public `x`/`y` node models, after asserting
they equal the input bit-for-bit, so coordinate representation contributes zero to the comparison. The
separate float32 question (H6) is tested by intervention: the same fixture with coordinates rounded to float32.

## 5. Pre-declared decision rules

* A rule is "reproduced" on a fixture if every node matches within the tolerance above.
* A rule is accepted as DEVSIM's geometric rule only if it is reproduced on ALL of T1-T9 and P1-P7, including
  the mirror, rotation and scale controls T6-T9.
* Phase E (L3) runs only for an accepted rule.
