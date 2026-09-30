# Batch 7H-E6E PLAN: fail-closed region area-conservation gate in the DEVSIM importer
(fixed after the step-1 reproduction and BEFORE any production edit or any gate result; never edited after results)

## 0. Why (step-1 evidence, already measured) and scope
Step 1 (run 36667603273, HEAD `decb8f9`, production code identical to review SHA `023bcb90`, DEVSIM 2.11.0, numpy 2.4.6,
Python 3.11.9) imported the raw, sha-gated E6D meshes through the UNMODIFIED production `import_process_result()` with
`devsim.solve` and every DEVSIM node / edge / equation write API trapped (0 calls in all three):
| mesh | device returned | sum NodeVolume [cm^2] | exact file-area x 1e-8 [cm^2] | relative difference |
|---|---|---|---|---|
| G0 (E6A L5) | yes | 4.999999310821319e-07 | 5.000000000000001e-07 | -1.3783573649117642e-07 |
| G1 | yes | 4.999999310821319e-07 | 5.000000000000001e-07 | -1.3783573649117642e-07 |
| G2 | **yes** | 5.015624284563546e-07 | 5.000000000000001e-07 | **+3.1248569127091397e-03** |
So production creates and returns the G2 device; the only thing that stopped G2 so far was the E6D audit script. (The -1.378e-7 of
G0/G1 is not a DEVSIM error: it is the difference between the exact area of the file's float32 micrometre coordinates times 1e-8 and
the area of the float64 centimetre coordinates DEVSIM actually holds after `points = raw_points * 1e-4`. E6D, which used DEVSIM's own
coordinates, measured G0/G1 ratio 1.0 exactly. Hence rule A1 below: the area is always computed on the exact coordinates DEVSIM holds.)

Scope: a validation-and-refusal step inside `import_process_result()`, and the GUI/CLI handling of its refusal. No change to DEVSIM,
to `NodeVolume`, to the mesh generator / refiner, to the equations, to the doping model, to oxidation, or to any threshold elsewhere.
The gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` is untouched. Passing this gate is **not** mesh convergence and **not** PN-junction
accuracy; it only says the integration weights DEVSIM will use tile each region's area.

## 1. The contract (per import, on exactly the arrays handed to DEVSIM, after any importer refinement)
Notation: `P` = `raw_points * length_scale_to_cm` (the float64 array whose `flatten().tolist()` becomes DEVSIM's coordinates), `T`, `tag`
= the triangle list and tags passed to `create_gmsh_mesh`, `R` = the material regions (`tag_to_name`). u = 2^-53, gamma4 = 4u / (1 - 4u).
For triangle t with vertices a, b, c: p1 = fl(fl(xb-xa) * fl(yc-ya)), p2 = fl(fl(yb-ya) * fl(xc-xa)), o_t = fl(p1 - p2), and the standard
rounding-error bound |o_t - o_t,exact| <= gamma4 (|p1| + |p2|) =: e_t (two subtractions, one product and one difference on each path).

**Before any DEVSIM call** (a failure creates nothing):
| code | condition (fail-closed) |
|---|---|
| `MESH_NONFINITE_COORDINATES` | any non-finite value in `P` |
| `MESH_NOT_PLANAR_2D` | any nonzero z coordinate (the importer and this check are 2D Cartesian only) |
| `MESH_UNSUPPORTED_CELLS` | the source mesh has a cell block of dimension >= 2 other than the one triangle block the importer uses (a second triangle block, quad, polygon, tetra, ...): its area would be silently dropped |
| `MESH_TAG_UNMAPPED` | `len(tags) != len(T)`, or a triangle tag with no material region |
| `MESH_EMPTY_REGION` | a material region with zero triangles |
| `MESH_DUPLICATE_TRIANGLE` | the same (sorted) vertex triple more than once |
| `MESH_DEGENERATE_TRIANGLE` | a triangle whose sign is not certified: \|o_t\| <= e_t (zero or unresolvable area) |
| `MESH_ORIENTATION_MIXED` | certified signs not all equal over the whole mesh (an inverted = negative-area triangle relative to the rest). Risk, stated in advance: a genuinely valid mesh that mixes orientations would be refused; every committed ViennaPS-derived mesh surveyed (14 files) is single-block, z = 0, all positive |

**After `create_device`, before the importer returns** (a failure deletes the device and the mesh with DEVSIM's public
`delete_device()` / `delete_mesh()`):
| code | condition |
|---|---|
| `MESH_REGION_ELEMENT_MISMATCH` | `len(get_element_node_list(region=r))` differs from the number of tagged triangles of r |
| `MESH_NODEVOLUME_INVALID` | region r has no nodes, or a non-finite or non-positive `NodeVolume` |
| `MESH_AREA_NOT_CONSERVED` | **per region**, \|S_r - A_r\| > B_r (below) |
Per region r (never a whole-mesh total, so opposite errors in two regions cannot cancel):
* A_r = fsum over t in r of \|o_t\| / 2 (math.fsum, correctly rounded).
* S_r = fsum of region r's `NodeVolume` values read from DEVSIM.
* B_r = E_A + E_S + E_NV with
  - E_A = 1/2 gamma4 sum_t (\|p1\|+\|p2\|) + u A_r  (triangle rounding + final rounding of the correctly rounded sum);
  - E_S = u S_r  (correctly rounded sum of the values DEVSIM returned);
  - E_NV = 128 u sum_t (\|o_t\|/2) / sin(theta_min,t)  (DEVSIM's own element-local node-volume computation; **an assumption**, inherited
    unchanged from 7H-E2 PLAN section 4 — "128 u for a <= 64-operation element-local computation, times the first-order conditioning
    1/sin theta" — not derived from DEVSIM source). theta_min,t is the smallest angle of t in float64.
* reported: A_r, S_r, relative difference S_r/A_r - 1, tau_r = B_r / A_r, and each of the three budget terms.
Why not E6D's tau: E6D's tau = (N+T) 2^-52 + max_i b_i takes the WORST node's 1/sin theta for the whole mesh, so one sliver (common at
etched sidewalls) would loosen the tolerance for every node; it is also whole-mesh. The rule above keeps E6D's per-element constant but
weights each triangle's conditioning by its own area and applies it per region. Coordinate storage precision contributes zero because
both sides use the same float64 coordinates DEVSIM holds (float32 file values are exact in float64; the x 1e-4 scaling is applied
before, identically for both).
Not supported, refused rather than passed (`UNSUPPORTED_BY_MODEL`): non-planar or 3D meshes, cell blocks other than the single triangle
block, and any axisymmetric/cylindrical volume model — the gate certifies DEVSIM's Cartesian `NodeVolume` only (no cylindrical model is
used anywhere in `tcad/` or the GUI: `rg -i "cylindrical|raxis"` is empty).

Refusal object: `MeshAreaConservationError(RuntimeError)` with `.physics_status = {"resolution": "UNSUPPORTED_BY_MODEL", "reason_code":
..., "device", "mesh", "regions": {r: {triangles, area_cm2, sum_NodeVolume_cm2, relative_difference, tau, budget terms, pass}}, "first
failing region", "cleanup": {"delete_device": "ok"|error, "delete_mesh": "ok"|error}, "notes"}` and a message naming the reason, region,
area, NodeVolume sum, relative difference and tolerance. A cleanup error is added to the same exception (never replaces it, never hidden).

## 2. Callers (must not bypass or convert the refusal into a number)
* GUI `run_measurement()` (`tcad_2d_stagewise.py:5822`): a `MeshAreaConservationError` is caught before `apply_doping` / any sweep,
  `last_physics_status` is set to its `physics_status`, the error names the reason, and it says no doping was written, no solve was run
  and no current is reported. No measurement log line or info dialog with a current is produced.
* GUI `resolve_electrode_pins()` (`:6121`): the same; `last_electrode_import` stays None, so `run_dc_operating_point()` solves nothing.
* CLI `run_pipeline()` (`tcad/cli/run_pipeline.py:432`): the exception propagates before `_apply_device_doping`, characterization and
  output writing; no output file and no summary with numbers.
* Every other caller (tests, examples, characterization helpers) receives the exception from the importer.

## 3. Expected impact, stated before any result
7H-E2 measured that production `refine_mesh_near` near a junction window creates obtuse green triangles and inflates the NodeVolume sum
(S1 1.005, S4 1.058 on the GUI default mesh). Every importer call that refines that way (`refine_near_um`, `auto_refine_from_doping`,
the implant-windows graded path) may therefore now be refused where it used to return a device. Existing tests that depend on such
meshes may fail with `MESH_AREA_NOT_CONSERVED`; they will be reported per file with their actual failure message and **not** edited to
pass. A normal control (G0, G1, the two-material control, the large-coordinate control) failing would mean the gate is wrong.

## 4. Tests (fixtures and expectations fixed here)
Local, pure (no DEVSIM), `tests/unit/test_mesh_area_conservation_mock.py`: exact single-material and two-material meshes pass;
two regions with +d and -d NodeVolume errors (total exact) fail on each region; non-finite coordinate / NodeVolume, nonpositive
NodeVolume, missing region, empty region, unmapped tag, duplicate triangle, degenerate triangle, mixed orientation, extra 2D cell block
and nonzero z each fail with their code; deviation exactly B_r * (1 - 2^-20) passes and B_r * (1 + 2^-20) fails.
Remote (GitHub-hosted runner), `tests/integration/test_mesh_area_conservation_gate_real.py`:
* E6D G0 and G1 (raw, sha-gated): import succeeds, per-region report attached.
* E6D G2: `MeshAreaConservationError` with `MESH_AREA_NOT_CONSERVED`, region Si; solve 0, doping writes (node_model / set_node_values)
  0; device list empty and mesh name free afterwards; re-import of G1 with the SAME mesh / device names succeeds.
* two-material control: a structured right-triangle rectangle split into Si (x < 0) and SiO2 (x > 0): both regions checked, passes.
* large-coordinate control: the same single-material structured mesh shifted by +1e4 um in x and y: passes.
* GUI (`TCADApplication` headless, messageboxes trapped): `run_measurement()` on a uniform-doped G2 result and `resolve_electrode_pins()`
  on G2 end with the refusal recorded in `last_physics_status`, 0 solves, 0 doping writes, no current reported; G1 control reaches the
  importer successfully.
* CLI: `run_pipeline()` with the process stage replaced by the G2 mesh raises the refusal, 0 solves, `_apply_device_doping` not called,
  no output files.
Then the full regression exactly once on the runner (`tests/run_regression.py`), reported per file (PASS/FAIL, and for failures whether
the message carries a `MESH_*` refusal code). No per-file baseline exists for this commit, so failures without a `MESH_*` code are
reported as "cause not classified", not guessed.
