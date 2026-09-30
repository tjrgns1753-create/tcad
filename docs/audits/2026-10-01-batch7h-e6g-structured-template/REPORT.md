# Batch 7H-E6G REPORT: structured-grid transition-template remeshing for the implant-window refinement

**Result, limited to the algorithm tested and the inputs tested.**
- Scope: single-Si, axis-aligned structured grids refined in x bands (no interface rings).
- The new builder produced meshes with 0 obtuse and 0 degenerate triangles, exact area, preserved outer boundary segments, kept original
  nodes and the requested band resolution. All of these were checked exactly on the small cases A-D.
- On the real B path (GUI refinement) and the GUI-default 1e20 wafer, the real DEVSIM import passed the unchanged area gate with
  S / A - 1 = 0.0. Both were within the 400,000-triangle cap: F has 196,000 triangles against 124,000 for the old refinement.
- The Laplace and manufactured-Poisson controls each ran one real solve with 0.0 error against the exact solution.
- None of this is PN or device validation. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the PN/DD gates are unchanged. Inputs
  outside the scope keep the existing graded path, whose meshes the area gate still refuses.

## Evidence (separate kinds; none implies another)
| kind | where | result |
|---|---|---|
| process RC | remote run 36737500532 (exec `10e86b6`) | 7 of 7 steps rc 0 |
| non-obtuse (exact) | A-D full (`eval_e6g.json`); B, F exact obtuse / area / orientation / duplicates on the real outputs | obtuse 0, degenerate 0 everywhere; hanging nodes checked exactly on A-E, NOT_VERIFIED on F |
| area conservation (geometry) | same | exact area equal to input in every case |
| DEVSIM import + NodeVolume | real_B.json, real_F.json | B: 1630 triangles, S = A = 4e-08 cm^2, S/A - 1 = 0.0, B/A 2.33e-14, pass. F: 196000 triangles, 98365 nodes, S = A = 5e-07 cm^2, S/A - 1 = 0.0, B/A 2.11e-14, pass. 0 solve / 0 writes; devices left 0 |
| analytic comparison | Laplace and manufactured Poisson tests | 1 solve each; max error 0.000e+00 V (Laplace, tol 1e-9 V); 0.000e+00 relative (Poisson, tol 1e-9 x max) |

## Scope and refusals
**Supported: every condition is proved from the triangles, not from the point pattern.**
- One tag, the region named `Si`, z = 0.
- The node set is the full tensor product of its distinct x and y values.
- There are 2 triangles per cell, and each is half of exactly one cell with the missing corners opposite.
- Orientation is uniform.
- The request comes from `implant_windows_lateral_request` with axis x, at least one center, and no interface rings.

**Refused (local G cases)**, each with a reason code:

| input | refusal |
|---|---|
| two materials | `MULTI_MATERIAL` |
| a missing triangle | `NOT_TWO_TRIANGLES_PER_CELL` |
| a non-rectangular notch | `NOT_TENSOR_PRODUCT_NODES` |
| z != 0 | `NOT_PLANAR` |
| overlapping halves (unit test) | `CELL_HALVES_OVERLAP` |
| w < h/2 | abort `TRANSITION_ASPECT` |
| over the cap (unit test, cap 1000) | abort `RESOURCE_CAP` |

**Production decision.**
- y-axis windows and interface rings keep the graded path; this was measured, e.g. 1040 and 1800 triangles with 120 and 232 obtuse.
- An abort propagates as `StructuredRemeshAborted`, and the GUI `_refine_for_implant_windows` reports it as an error. There is no
  silent fallback.

## Resources
- F: 196,000 triangles and 98,365 nodes. They are counted before allocation; all new nodes are used by triangles, and the node count
  equals the plan.
- Local refinement took 1.7 s; the remote production refine took 1.39 s and the import 3.3 s.
- B: 1630 triangles (old graded 1040, with 120 obtuse).

## Resolution
Every output triangle whose centroid is in ring k's band has x- and y-extent at most its original cell's / 2^(k+1), checked exactly:

| case | triangles in bands | violations |
|---|---|---|
| B | 1180 | 0 |
| F | 150400 | 0 |

The old graded output fails this same check: B 640 of 880, F 58768 of 84800. The old output is coarser than this rule in part of the
band, because its bands are centroid-based.

## Changes
- **Commit `10e86b6`**, production patch `e6g_production.patch` (344 lines, sha256 `0bde57a5…`, `git apply --check -R` ok).
- **`tcad/device/devsim/mesh_refine.py`**, +230 lines. It adds:
  - `STRUCTURED_TRIANGLE_CAP`;
  - `StructuredRemeshUnsupported` and `StructuredRemeshAborted`;
  - `structured_grid_of`;
  - `_strip_depths`;
  - `structured_lateral_refine`.
  The existing red-green functions are unchanged.
- **`tcad/device/devsim/mesh_import.py`**, +60 / -23 lines:
  - it imports the new symbols;
  - `refine_process_result_for_implant_windows` tries the structured builder for supported inputs;
  - the request computation moves into the new `implant_windows_lateral_request`, and `derive_implant_windows_refinement` calls it. Its
    predicates are identical to HEAD's on 8 combinations (2 meshes x 2 doses x interface on/off; 0 mismatches).
- **Tests:** `tests/unit/test_mesh_structured_remesh_mock.py` and `tests/integration/test_mesh_gate_manufactured_poisson_real.py`.
- **Criteria:** `CRITERIA.md`, committed alone in `fc371fd` before implementation.

## Not verified / next
Not verified:
- hanging nodes on F (exact check skipped for size);
- local control-volume accuracy, current accuracy and PN convergence on these meshes;
- the other refinement callers (`refine_near_um`, auto refinement, MOS gate rings): these still use red-green, so their meshes remain
  area-gate refused;
- raw ViennaPS slivers (representative A).

Next, in scope for a physics step: a 2-terminal implant-windows measurement on the B and GUI meshes through the real GUI path, with the
current compared against a pre-registered 1D reference. The step-junction 2D gate stays in place.
