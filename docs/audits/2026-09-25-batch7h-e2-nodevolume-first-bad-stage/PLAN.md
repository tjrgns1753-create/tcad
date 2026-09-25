# Batch 7H-E2 PLAN: first stage and minimal cause of the production-mesh NodeVolume excess
(fixed BEFORE any ViennaPS / DEVSIM execution of this batch; never edited after results)

Execution location: everything that runs ViennaPS or DEVSIM (mesh regeneration, DEVSIM import, model reads) runs on a
GitHub-hosted Windows runner (`claude/remote-runner`, profile `e2_nodevolume_first_bad_stage`). Locally: code reading and
writing, static checks, pure-array / synthetic-input tests of the audit helpers only.

## 0. Question and limits
E1 found DEVSIM sum(NodeVolume) / triangle area = 1.05825195 on the production GUI mesh, with 3000 obtuse triangles and 200
non-Delaunay edges at |x| = 0.10-0.15 um. E2 asks: at which refinement pass does the excess first appear, and is it caused by
triangle orientation, by triangle shape, or was it already present before refinement? Only mesh geometry and DEVSIM's own
default geometric models (NodeVolume, EdgeCouple, EdgeLength) are read. No Poisson, drift-diffusion or any `devsim.solve`
call runs; no doping is written to any DEVSIM device. Production code, tests, the gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, precision flags and DEVSIM internals are not changed. Mesh convergence is not
addressed. A candidate that passes its audit checks is still not applied to production.

## 1. Fixed input (the E1 wafer mesh)
The raw wafer mesh is regenerated with the exact E1 calls (`tcad.backends.viennaps.session.make_mask_spans` with the GUI
defaults of E1 `common_e1.GUI`, then `tcad.backends.viennaps.io.save_volume_mesh(floor 5 um)`), then
`build_process_result` and `apply_step_junction_doping` exactly as E1 `prod_build_e1.build()` (doping only rides on the
ProcessResult; it is never written to DEVSIM here). The file's sha256 must equal the E1 value
`cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a`. If it differs: `MESH_INPUT_IDENTITY_FAIL`, every causal
verdict is withheld, the run stops after recording the difference. The mesh file is kept as an artifact.

## 2. Stages S0-S4 (production path, only the pass count varies)
The production call is `import_process_result(result, contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1e-4,
refine_near_um=0.0, refine_axis="x")`; with `refine_half_width_um` and `refine_levels` unset it uses 0.1 um and 4
(`tcad/device/devsim/mesh_import.py:974-987`), i.e. `refine_mesh_near(points, triangles, tags, |cx - 0| < 0.1, levels=4)`
(`tcad/device/devsim/mesh_refine.py:157-186`), whose loop is deterministic, so pass k of the 4-pass run is the same array as
`levels=k`. Stage Sk (k = 0..3) is the same production call with the public argument `refine_levels=k`; S4 is the E1 call
verbatim (argument omitted, E1 mesh / device names). Each stage is imported into its own DEVSIM device, read, and deleted
(`delete_device` + `delete_mesh`); `get_device_list()` must be empty at the end.

Identities (each recorded; a failure withholds every causal verdict that depends on that stage):
* I1 (trace): an audit copy of `_refine_once` (verbatim logic plus parent / split-kind recording) run for k passes must give
  points, triangles and tags array-equal to production `refine_mesh_near(..., levels=k)` for every k = 0..4.
* I2 (import): DEVSIM node x, y equal `refined_points * 1e-4` computed exactly as production does, node by node, bit for bit;
  DEVSIM element list equal to the refined triangle list (exact order; if only equal as a multiset of sorted triples, that is
  recorded and the mapping used).
* I3 (E1 match): S4 x / y / element sha256 equal E1 `prod.json` (`f9353f60...`, `3818a0b5...`, `4bb0d371...`); S4 NodeVolume
  array equals the E1 `prod_arrays.npz` NodeVolume array element by element; contacts and regions equal E1. If I3 fails,
  STOP: nothing is interpreted as a cause experiment.
* I4 (cross-stage): exact total area (exact rational sum of |orient| over the exact binary values of the coordinates) equal at
  every stage; contact node coordinate sets (`Si_xmin`, `Si_xmax`) equal at every stage; all triangles carry the Si tag; the
  region list is `["Si"]`. A difference stops the causal comparison of the stages it involves.

## 3. Recorded per stage (and per control)
sha256 of x, y, elements, triangle tags; node / triangle counts; contact names and node counts; float64 triangle-area sum
and exact area (from the DEVSIM coordinates); DEVSIM sum NodeVolume and ratio sum NodeVolume / exact area; 7H-D `quality()`
(angle classes, min / max angle, exact Delaunay violations, boundary Gabriel violations, exact positive overlaps, signed
edge-couple and signed node-volume negatives, orientation); 7H-B per-node rules F2 (signed circumcentric dual, sums to the
area) and F3 (DEVSIM rule identified in 7H-B: absolute element couples) evaluated on the DEVSIM coordinates, and
max |NodeVolume - F3| / F3 per node; excess sum(NodeVolume) - area versus sum(F3 - F2); the distinct |x| (um, 6 decimals)
of nodes with F3 - F2 above the per-node budget and of obtuse-triangle vertices; the lineage of every obtuse triangle and of
both triangles of every Delaunay-violating edge (origin S0 triangle index, its S0 class and coordinates, and the split kind
at each pass: unchanged / red corner child / red centre child / green child).

EdgeCouple readback (public API only): `edge_from_node_model(node_model="node_index")` to obtain `node_index@n0/@n1`, then
`EdgeCouple` and `EdgeLength`. Compared per edge with the 7H-B predictions G1 (signed sum of element couples) and G2 (sum of
absolute element couples). Reported for every edge with G1 < 0: how many DEVSIM values are negative, exactly zero, positive,
and max |EdgeCouple - G2| and |EdgeCouple - G1| relative to max |G2|. Also checked: NodeVolume equals
sum over incident edges of 0.25 * EdgeCouple * EdgeLength. If the edge models cannot be read: `EDGECOUPLE_UNKNOWN`.

## 4. Error budgets (fixed now)
Coordinates: every quantity above is computed from the coordinates DEVSIM itself holds (read back), so float32 serialization
of the ViennaPS file enters both sides of every comparison identically and contributes zero. u = 2^-53.
* Per node: |NodeVolume_i - F3_i| <= b_i * F3_i with b_i = 2^-46 / sin(theta_i), theta_i = smallest interior angle of the
  triangles incident to node i (128 u for a <= 64-operation element-local computation, times the first-order conditioning
  1 / sin(theta) of the cotangent). All F3 contributions are non-negative, so F3_i is the sum of their magnitudes.
* Per stage: |sum NodeVolume / area - 1| <= tau_k = (N_nodes + N_triangles) * 2^-52 + max_i b_i (recursive summation of both
  sums plus the worst per-node term). The same tau_k bounds |(sum NodeVolume - area) - sum(F3 - F2)| / area.
These are not adjusted after results.

## 5. Controls
* C_rt (writer round trip): the S4 refined arrays written unchanged (same dtype, same order, cell data `Material`) with
  meshio to a new `.vtu`, re-read (array-equal check), and imported with the same production call but `refine_near_um`
  unset (no refinement). Must reproduce S4's x, y, elements and NodeVolume exactly; otherwise the orientation and
  candidate comparisons are `INCONCLUSIVE`.
* C_ccw (orientation only): the same as C_rt, but each triangle whose exact orientation is negative has two vertices swapped
  so every triangle is counter-clockwise. Coordinates and the triangle vertex sets are unchanged; this is the same mesh, not a
  new mesh. Compared node by node with C_rt.

## 6. Verdicts (all that hold are reported; none is merged into another)
* `PRE_EXISTING`: S0 ratio outside tau_0.
* `FIRST_BAD_STAGE = k`: S0..S(k-1) within their tau, Sk outside tau_k, and I1, I2, I4 hold for S(k-1) and Sk (and I3).
* `ORIENTATION_EFFECT`: C_ccw NodeVolume differs from C_rt at any node beyond b_i. `ORIENTATION_CAUSE`: that, and C_ccw's
  ratio is within tau. `NO_ORIENTATION_EFFECT`: C_ccw equals C_rt within b_i at every node.
* `SHAPE_CAUSE` (at the first bad stage and at S4): NodeVolume equals F3 within b_i at every node, the excess equals
  sum(F3 - F2) within tau, every node with F3 - F2 > b_i F3 is a vertex of an obtuse triangle, and `NO_ORIENTATION_EFFECT`.
* `INCONCLUSIVE`: any required identity fails, C_rt fails, or the excess is not explained by F3.

## 7. Optional repair candidate (at most one, audit copy only)
Runs only if `FIRST_BAD_STAGE` is determined, `SHAPE_CAUSE` holds and `NO_ORIENTATION_EFFECT` holds; otherwise
`CANDIDATE_NOT_RUN`. Candidate: 7H-A `exact_flip` (exact incircle, exact convexity / area / overlap checks, Lawson
termination) on the S4 arrays, protected edges = every boundary edge (outer boundary, contacts) plus every edge with both
end points exactly on x = 0 (junction line); only interior edges between two Si triangles are eligible. Nodes and
coordinates are never moved. Accepted as `CANDIDATE_PASSES_AUDIT_CHECKS` only if all hold:
(a) exact invariants versus S4: identical point array, boundary edge set, interface set (empty), x = 0 edge set, tag
counter and exact total area; no duplicate, zero-area or non-manifold triangle; exact positive-area overlaps 0; flip loop
terminated with no exact violation left; (b) DEVSIM import through the C_rt writer path: same contacts with the same node
sets, same region; (c) |sum NodeVolume / area - 1| <= tau; (d) dopant inventory: with the E1 canonical per-node Donors /
Acceptors arrays (same node order, proven by I3 and the identical point array), sum(N x NodeVolume) equals sum(N x F2) of the
candidate mesh within tau, per species; also reported against the continuum N x 25 um^2 per side. Any failure:
`CANDIDATE_REJECTED`, the phenomenon stays `UNSUPPORTED_BY_MODEL`. No DEVSIM EdgeCouple or NodeVolume is overwritten, and
nothing is applied to production.

## 8. JSON, artifacts, stop conditions
New JSON is written with `allow_nan=False` (non-finite values become null plus an explicit status) and re-read with a strict
parser. Artifact: summary, sanitized log, all JSON, per-stage node arrays (npz), the regenerated wafer `.vtu`, the C_ccw and
candidate `.vtu` files, with sha256. Stop / withhold conditions: sections 1, 2 (I3), 5 (C_rt). No physics solve on any mesh.
No threshold, budget, stage definition or candidate is changed after a result is seen.
