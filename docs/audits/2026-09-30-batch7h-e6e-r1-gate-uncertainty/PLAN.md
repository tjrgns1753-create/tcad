# Batch 7H-E6E-R1 PLAN: certification-uncertainty limit for the area-conservation gate, and cause of the ViennaPS Mask / Si mismatches
(fixed after the step-3 counterexample run and BEFORE any production edit or remote run of this batch; never edited after results)

Base: HEAD `599530eb87dd022b2451b560719d5533de98f216` (E6E, partially approved). E6E PLAN / REPORT / raw data are not edited; corrections
go into this batch's documents. Serena MCP was not connected in this session (CONNECT_TIMEOUT); symbol and caller facts come from `rg`
and direct reading.

## 0. P0 defect, measured on the unmodified functions (local, pure; `scripts/p0_counterexample.py` -> `p0_before.json`)
Input (fixed by the Codex prompt): points (0,0), (1,0), (2,1e-14); one triangle; tag 1 -> "Si"; NodeVolume 2A/3 on each node (S = 2A).
| quantity | value |
|---|---|
| area A (from o_t) | 5e-15 |
| theta_min (rad) = sin(theta_min) | 5e-15 |
| check_mesh_input | accepted (sign certified: o_t 1e-14 > e_t 4.44e-30) |
| E_A / E_S / E_NV | 2.7755575615628925e-30 / 1.1102230246251565e-30 / 1.4210854715202004e-14 |
| B / B/A | 1.4210854715202007e-14 / **2.842170943040401** |
| S/A - 1 | **1.0** |
| check_nodevolume | **PASS** |
A 100 % area error is accepted because E_NV = 128 u sum A_t / sin(theta_min,t) grows without bound as theta_min -> 0 and nothing
refuses an uncertainty that large. Same as Codex's independent arithmetic (relative 1.0, tolerance ~2.842, pass).

## 1. Certification contract (replaces the comparison step of E6E PLAN section 1; everything else there is unchanged)
Per region r, in this order; the first failure refuses (resolution `UNSUPPORTED_BY_MODEL`):
1. **A_r** (fsum of |o_t|/2 over the region) finite and > 0, else `MESH_AREA_INVALID`.
2. NodeVolume values: present, finite, > 0, else `MESH_NODEVOLUME_INVALID` (unchanged).
3. **S_r, E_A, E_S, E_NV, B_r = E_A + E_S + E_NV and u_r = B_r / A_r** all finite, else `MESH_AREA_BUDGET_NONFINITE`. This is an
   explicit check, never left to the outcome of a comparison with NaN / Inf. The same code also refuses non-finite o_t or e_t in
   `check_mesh_input` before the degenerate-triangle test.
4. **u_r <= MAX_AREA_RELATIVE_UNCERTAINTY = 1e-8**, else `MESH_AREA_UNCERTAINTY_TOO_LARGE`. This refusal is decided BEFORE and
   INDEPENDENTLY of whether S_r happens to equal A_r (a sliver region with S = A is still refused). B is never clipped to the limit.
5. |S_r - A_r| <= B_r with the unchanged B_r, else `MESH_AREA_NOT_CONSERVED`.
Meaning of 1e-8, stated exactly: a fixed, pre-registered engineering limit on how large a relative rounding budget this gate may use and
still call a region certified. It is **not** a proven DEVSIM error bound, **not** a physical threshold for acceptable material loss, and
**not** a widening of the area tolerance: a region that passes step 4 is still compared with its own B_r (normally ~2e-14 relative, E6E
section 5), never with 1e-8.
Budget basis (recorded in every status): `ASSUMED_BOUND` -- E_NV = 128 u sum_t A_t / sin(theta_min,t) is inherited from 7H-E2 PLAN
section 4 and was NOT derived from DEVSIM's source; E_A (gamma4 bound of the two-product difference) and E_S (correctly rounded fsum)
are standard floating-point bounds. Nothing here states that area conservation is mathematically proven.
Refusal status fields: resolution, reason_code, region (`first_failing_region`) and per-region `A`, `S`, `relative_difference`, `E_A`,
`E_S`, `E_NV`, `B`, `relative_uncertainty`, `certification_limit`, `budget_basis`, plus `device`, `mesh`, `cleanup` (unchanged
public-API delete). The pure function `check_nodevolume` itself enforces steps 1-5, so a caller that bypasses the importer cannot skip
the limit; the importer calls the same function. The limit and the tolerance are not raised after any result.

## 2. Tests (expectations fixed here)
`tests/unit/test_mesh_area_conservation_mock.py` (pure; updated, the E6E cases kept with their meaning):
1. sliver triangle above, S = 2A: refused `MESH_AREA_UNCERTAINTY_TOO_LARGE` (before the change it PASSED -- `p0_before.json`).
2. same sliver, S = A: refused `MESH_AREA_UNCERTAINTY_TOO_LARGE`.
3. non-finite budget: region terms with E_NV = inf -> `MESH_AREA_BUDGET_NONFINITE`; NodeVolume [1e308, 1e308] (S overflows) ->
   `MESH_AREA_BUDGET_NONFINITE`; a triangle with coordinates 1e200 (o_t overflows) -> `MESH_AREA_BUDGET_NONFINITE` in check_mesh_input.
4. structured single material: passes. 5. structured two materials: both regions pass. 6. large coordinates (+1e4): passes.
7. normal shape, S = A + 0.01: `MESH_AREA_NOT_CONSERVED`. 8. opposite errors in two regions: refused per region.
9. limit boundary, fixed inputs: region terms area 1.0, E_A 0, E_NV = 1e-8 (1 - 2^-10) with S = 1.0 passes; E_NV = 1e-8 (1 + 2^-10)
   with S = 1.0 refused `MESH_AREA_UNCERTAINTY_TOO_LARGE`. The old E6E boundary case (E_NV = 1e-6) is now above the limit and is
   replaced by E_NV = 1e-9 with S = 1 + 1e-9 (1 -/+ 2^-10): inside passes, outside `MESH_AREA_NOT_CONSERVED`.
10. (remote) E6D G2 refused `MESH_AREA_NOT_CONSERVED`, cleanup ok, same-name re-import of G1 succeeds -- the existing
    `tests/integration/test_mesh_area_conservation_gate_real.py`, unchanged in intent.

## 3. Two representative ViennaPS inputs (remote, import-only diagnosis)
* **A** (Mask mismatch, no refinement): `tests/integration/test_phase5_devsim_real.py` production path -- `registry.get("etching",
  "isotropic")` with recipe {grid_delta_um 0.2, x_extent_um 4.0, y_extent_um 3.0, mask_left_um 1.5, mask_right_um 2.5, pr_thickness_um
  0.5, etch_time_s 0.5, rate -0.05, mask_material "Mask"} -> `build_process_result` -> `import_process_result(contact_regions=["Si"],
  contact_axis="x")` (length_scale_to_cm default 1.0, no refinement). E6E regression: region Mask relative +17.935.
* **B** (Si mismatch after refinement): `tests/integration/test_measurement_canonical_state_gate_real.py` case B1 -- headless GUI,
  width 4.0, silicon depth 1.0, grid 0.2, `_materialize_current_wafer()`, `apply_implant_windows_doping(... donor background 1e16, two
  windows at the GUI's default source/drain spans, 1e16, chemical_state ACTIVE)` -> `refine_process_result_for_implant_windows()` ->
  import (the GUI's `run_measurement` arguments: contact_regions [Si], axis x, length_scale_to_cm 1e-4). E6E regression: Si +0.30. The
  unrefined wafer of the same recipe (B raw) is diagnosed too (its uniform measurement B2 solved in E6E).
Both are regenerated on the runner with these exact production calls (no raw mesh of them was kept).
For each mesh (A, B raw, B refined): (1) export -- point dtype / units, cell blocks, tag -> region, per-region triangle count and
exact (Fraction) area of the file coordinates; (2) refinement (B) -- region areas / counts before and after, triangles added / removed,
material-interface and domain-boundary edge sets before / after; (3) transfer -- the coordinates, elements and physical names actually
passed to `create_gmsh_mesh` (captured by a pass-through wrapper), their dtype and scaling, per-region area on those coordinates;
(4) readback -- per region DEVSIM x, y, element node list, area on readback coordinates, NodeVolume min / max / sum, S/A, and the
source -> DEVSIM node / element correspondence by coordinates; DEVSIM NodeVolume compared node by node with the 7H-B rules F2 (signed
circumcentric dual, sums to the area) and F3 (absolute element couples); (5) shape -- min / max angle distribution, counts of triangles
with max angle > 90 / 120 / 150 / 170 deg, duplicate coordinates / triangles, degenerate elements, edge ownership (tiling T2), edges
shared by two regions, per-region F3 - F2 excess. File area, transferred area and readback area are reported separately.
**Diagnostic bypass (audit script only):** the production refusal is observed first (import raises); then, in the audit process only,
`tcad.device.devsim.mesh_import.verify_device` is replaced by a recorder that reads NodeVolume and elements of EVERY region and returns
without refusing. No production option is added. Traps: devsim.solve, node_model, edge_model, set_node_values, set_node_value,
equation, contact_equation -- 0 calls each (NodeVolume is only read). Devices and meshes are deleted with the public API afterwards;
nothing is returned as a measurement.
**Cause candidates**, each marked CONFIRMED / EXCLUDED / UNRESOLVED with the numbers: export coordinates / unit conversion; tag / region
split; importer elements / physical names; raw mesh shape vs DEVSIM's integration rule; refinement-added elements; gate area /
readback computation. Mask exclusion is not implemented and not proposed from material name or equation absence.

## 4. Normal electrical control (remote, one solve path)
The 7H-C1 fixture geometry (single Si rectangle 2 um x 1 um, x lines 0, 0.6, 1.5, 2.0 um, y lines 0, 0.4, 1.0 um, each cell split by its
bottom-left-to-top-right diagonal: non-obtuse, non-uniform) written as a `.vtu` with tag Si, imported through `import_process_result`
(contact_regions [Si], axis x, length_scale_to_cm 1e-4) -- the gate runs -- then `run_basic_potential_solve` with Si_xmin 0 V, Si_xmax
1 V. Analytic solution Potential = (x - x_min) / (x_max - x_min). Tolerance: max |error| <= 1e-9 V, inherited unchanged from
`tests/integration/test_basic_potential_linear_precision_real.py` (EXACT_V). Recorded: solve call count (expected >= 1), max error,
area report. Call counters are kept separately for this control and for the problem-mesh diagnostics.

## 5. Remote budget
One remote run: unit test, the E6E targeted real test, A / B diagnostics, the control. No full regression, no migration of the 41 E6E
failures, no mesh / refinement / doping / equation / oxidation change.
