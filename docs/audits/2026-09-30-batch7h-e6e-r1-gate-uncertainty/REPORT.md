# Batch 7H-E6E-R1 REPORT: certification-uncertainty limit, and cause of the ViennaPS Mask / Si area mismatches

**Result**
- **P0 defect: fixed.** Before the change, a 100 % area error on a sliver triangle passed (B/A 2.842). It is now refused as
  `MESH_AREA_UNCERTAINTY_TOO_LARGE`.
- **Blocking still holds.** G2 is refused, no number is produced, cleanup succeeds, and a same-name retry works (E6E targeted test
  16/16).
- **A normal physical computation is still possible.** A small non-obtuse mesh passes the gate. A real Laplace solve then ran once and
  matched the exact solution with a maximum error of 0.0 V (tolerance 1e-9 V).
- **Cause of the mismatches, for both representative meshes.** DEVSIM's NodeVolume equals the 7H-B F3 rule (absolute element couples)
  at every node. F3 over-counts every obtuse triangle.
  - In A (raw ViennaPS etch mesh, no refinement), two near-180-degree slivers at the Mask/Si interface give Mask +17.9x. Si is also
    +0.28 %.
  - In B, the raw mesh is exact. The implant-windows green refinement adds 120 obtuse (116.565 degree) triangles, which give Si +30 %.
  - Export, tags, importer, transfer and readback are excluded as causes.
- **Not established.** None of this is mesh convergence, current accuracy or PN physics. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`
  stays.

## 1. Start state and rules
- **Repository state:**
  - HEAD `599530eb87dd022b2451b560719d5533de98f216` = origin, branch `claude/remote-runner`, tracked dirty 0, staged 0.
  - No remote run was in progress (last run: 36668767301, completed).
  - Hashes before this batch: `mesh_conservation.py` 10a647e0…, `mesh_import.py` e0635b22…, unit test ad5b06b5…, real test ed5ecf73….
  - E6E: PLAN 2e366a06…, REPORT 21482529…, patch 413dc144…; hash of the data-tree listing b837047b….
- **Instructions:** the only CLAUDE.md that applies is the repository one (no global or parent CLAUDE.md). The rules applied: THE
  INVARIANT, fail-closed `UNSUPPORTED_BY_MODEL`, no threshold change after results, Serena-first with a fallback, the change-diff
  evidence rule, and remote execution for long computations.
- **Serena:** the MCP server failed to connect (CONNECT_TIMEOUT), so facts come from `rg` and direct reading.
  - Symbols: `triangle_terms`, `check_mesh_input`, `check_nodevolume` and `verify_device` live in `tcad/device/devsim/mesh_conservation.py`.
  - The importer calls them at `mesh_import.py` (check_mesh_input after `tag_to_name`; verify_device after `create_device`).
  - Callers: GUI `run_measurement` (`tcad_2d_stagewise.py:5822`), `resolve_electrode_pins` (`:6121`), CLI `run_pipeline` ->
    `_import_device` (`tcad/cli/run_pipeline.py:228/432`), and `examples/build_pn_diode.py`.
  - Neither the GUI nor the CLI inspects reason codes. Both catch or propagate the exception class `MeshAreaConservationError`, so any
    new reason code travels the same path (from reading the code).

## 2. P0 before the change (`p0_before.json`; the actual function on HEAD 599530e)
The counterexample is one triangle (0,0), (1,0), (2,1e-14), with NodeVolume 2A/3 on each node.

| quantity | value |
|---|---|
| A | 5e-15 |
| theta_min | 5e-15 rad |
| orientation / degenerate check | accepted (o_t 1e-14 > e_t 4.44e-30) |
| E_A | 2.7755575615628925e-30 |
| E_S | 1.1102230246251565e-30 |
| E_NV | 1.4210854715202004e-14 |
| B | 1.4210854715202007e-14 |
| B/A | 2.842170943040401 |
| S/A - 1 | 1.0 |
| check_nodevolume result | **PASS** |

This matches Codex's arithmetic.

## 3. Contract (PLAN `853d400`, LF sha256 `380267d53ca2c1fdc82560a3d345384b907f65f07ce1d2545787c1abc811c3d3`)
Checked per region, in this order:
1. The element count matches.
2. A is finite and > 0; otherwise `MESH_AREA_INVALID`.
3. The NodeVolume values are valid; otherwise `MESH_NODEVOLUME_INVALID`.
4. S, E_A, E_S, E_NV, B and B/A are all finite; otherwise `MESH_AREA_BUDGET_NONFINITE`. Overflow of o_t is also refused here, in the
   input check.
5. **B/A <= 1e-8**; otherwise `MESH_AREA_UNCERTAINTY_TOO_LARGE`. This is decided before, and independently of, the comparison of S with A.
6. |S - A| <= B; otherwise `MESH_AREA_NOT_CONSERVED`.

What the limit 1e-8 is and is not:
- It is a pre-registered engineering limit on the rounding budget that may still be called certified.
- It is **not** a proven DEVSIM error bound.
- It is **not** a physical material-loss threshold.
- It is **not** a widening of the area tolerance: a certified region is still compared with its own B (normally about 2e-14 relative).
- B is never clipped.

The budget basis is recorded in every status as `ASSUMED_BOUND`: the 128 u / sin(theta_min) term is inherited from 7H-E2 and was not
derived from DEVSIM source.

The pure `check_nodevolume` itself enforces the contract, and the importer uses that same function, so a direct caller cannot skip it.
The status carries: resolution, reason_code, first_failing_region, A, S, relative_difference, E_A, E_S, E_NV, B, relative_uncertainty,
certification_limit, budget_basis, device, mesh and cleanup.

## 4. After the change
Local run, then the remote run 36690617723 at exec SHA `8915754689dd548c38780c4ec065156cfdd9de2c` (DEVSIM 2.11.0, ViennaPS 4.6.2,
ViennaLS 5.8.5, numpy 2.4.6, meshio 5.3.5, Python 3.11.9). All five commands returned rc 0.

**P0 after the change** (`p0_after.json`): `REFUSED MESH_AREA_UNCERTAINTY_TOO_LARGE` with relative_uncertainty 2.842170943040401 and
certification_limit 1e-08. The same triangle with S = A is also refused.

Unit-test cases (from `tests/unit/test_mesh_area_conservation_mock.py`):
- The non-finite E_NV, the S overflow (1e308 + 1e308) and the o_t overflow (coordinates x 1e200) each give `MESH_AREA_BUDGET_NONFINITE`.
- A = 0 gives `MESH_AREA_INVALID`.
- Limit boundary at S = A = 1: B/A = 1e-8(1 - 2^-10) passes; B/A = 1e-8(1 + 2^-10) is refused.
- Area boundary at E_NV = 1e-9: S = 1 + 1e-9(1 -/+ 2^-10) passes / gives `MESH_AREA_NOT_CONSERVED`.
- A normal shape with S = A + 0.01 gives `MESH_AREA_NOT_CONSERVED`.
- Opposite errors in two regions are refused per region.
- The single-material, two-material and large-coordinate controls pass.
- On the old code the new unit test fails at import, because the new constant is missing. That is not a behavioural proof; the
  behavioural proof is `p0_before.json` (PASS) against `p0_after.json` (refused).

E6E targeted real test: 16/16 (G2 refused as `MESH_AREA_NOT_CONSERVED`, same as before).

**Small Laplace control** (`tests/integration/test_mesh_gate_small_laplace_control_real.py`):
- Mesh: the 7H-C1 geometry, 12 nodes and 12 triangles, imported through `import_process_result`.
- Gate: A 2.0000000000000004e-08, S 2e-08, relative -1.11e-16, B/A 2.618e-14; pass.
- `run_basic_potential_solve` ran 1 solve.
- Maximum error against (x - x_min)/(x_max - x_min) was 0.000e+00 V, against a tolerance of 1e-9 V inherited from EXACT_V.

## 5. Representative inputs: every region (diagnostic bypass in the audit process only)
All six imports (one production import and one bypass import for each of A, B raw and B refined) made **0 calls** to each of
solve / node_model / edge_model / set_node_values / set_node_value / equation / contact_equation / node_solution. Devices left: 0. The
production refusal was observed first.

| mesh | region | triangles | file area (um^2) | transfer = readback area | NodeVolume sum | S/A - 1 | F2 sum | F3 sum | max \|NV - F3\|/F3 | triangles > 90 / >150 / >179 deg | max angle | min angle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A (phase5 etch, scale 1.0) | Mask | 132 | 1.4892715397655807 | same | 28.19998569250985 | **+17.93542241259017** | 1.48927153976558 | 28.199985692509852 | 1.99e-16 | 10 / 2 / 2 | 179.914 | 0.0286 |
| A | Si | 1004 | 19.978690159677335 | same | 20.034247472896915 | **+0.0027808286116630665** | 19.978690159677335 | 20.034247472896915 | 1.90e-16 | 3 / 0 / 0 | 135.30 | 0.196 |
| B raw (GUI wafer, 1e-4) | Si | 200 | 4.0 | 3.999999797903004e-08 cm^2 | 3.999999797903004e-08 | 0.0 | = A | = A | 0 | 0 / 0 / 0 | 90.0 | 45.0 |
| B refined | Si | 1040 | 4.0 | 3.999999797903004e-08 cm^2 | 5.1999997372740956e-08 | **+0.30000000000004756** | = A | 5.1999997372740956e-08 | 0 | 120 / 0 / 0 | 116.565 | 18.435 |

**Largest contributions**

A, Mask — two mirror-image slivers:
- Vertices (-0.6, 0), (-0.4, -0.0002), (-0.533333, 0) and the mirror at +x.
- Angles 0.057 / 0.029 / 179.914 degrees; area 6.67e-6 um^2.
- F3 - F2 excess 13.3334 each, which is 26.667 of the region's total excess of 26.711.
- They sit on the Mask/Si interface at y = 0, at the mask-edge positions x = +/-0.4..0.6.

A, Si — three triangles with 131-135 degree angles near the same mask edges, excess 0.0556 in total.

B refined — 120 triangles with angles 18.435 / 45 / 116.565 degrees; excess 2.0e-10 cm^2 each, 1.2e-8 in total, which is exactly 0.3 A.

**Refinement (B)**
- Triangle count 200 -> 1040: 120 removed, 960 added. Nodes 126 -> 562.
- Region area 4/1 -> 4/1 (exact).
- Boundary edge length 10.0 -> 10.0. Edge-owner histogram {1: 50, 2: 275} -> {1: 82, 2: 1519}: no edge has more than 2 owners.
- Material and contact boundaries did not change in length. Contacts are 6 nodes each after refinement.

**Correspondence (all meshes)**
- The coordinates passed to `create_gmsh_mesh` equal the importer's file x scale, computed in float32 before the list conversion.
- The transferred triangles equal the file's triangles, and each triangle's physical name equals its file region.
- Every DEVSIM readback node was found in the transfer (the map is injective).
- The per-region element multiset equals the source.
- The file, transfer and readback areas are equal, with the unit scale 1e-8 kept separate for B.

## 6. Cause candidates
| candidate | verdict | evidence |
|---|---|---|
| export coordinates / unit conversion | **EXCLUDED** | file area = transfer area = readback area in every region; the transfer is bitwise file x scale |
| tag / region split | **EXCLUDED** | triangle physical names = file regions; element multisets equal; edge owners <= 2 |
| importer elements / physical names | **EXCLUDED** | transferred triangles = file triangles; physical names [Mask, Si, Si_xmin, Si_xmax] / [Si, Si_xmin, Si_xmax] |
| raw mesh shape vs DEVSIM integration | **CONFIRMED for A** | NodeVolume = F3 at every node (<= 2e-16); F2 sums to A; the excess is concentrated in 2 Mask slivers (179.914 deg) plus 3 obtuse Si triangles |
| refinement-added elements | **CONFIRMED for B** | raw: 0 obtuse and S = A exactly; refined: 120 triangles at 116.565 deg, excess = 0.3 A exactly, NodeVolume = F3 |
| gate area / readback computation | **EXCLUDED** | readback area = transfer area; S = F3 sum; F2 sum = A |

Scope of the "CONFIRMED" verdicts:
- The identification NodeVolume = F3 is **empirical** (a node-by-node match on these meshes). The DEVSIM 2.11.0 source was not read, so
  why DEVSIM uses absolute couples is not established from source.
- The general limit of element-edge-based integration for obtuse elements (Sanchez-Chen, devsim.net models) is consistent with this
  result but was not used as proof.

**Participation (read-only, phase5 path).**
- `run_basic_potential_solve` builds `PotentialEquation` on region Si only.
- The contacts Si_xmin and Si_xmax are on Si.
- No interface is created (no `interface_region_pairs`).
- Mask carries no equation, contact or interface on this path.

This is recorded, not used. No Mask exclusion is implemented or proposed, and in A the Si region fails on its own anyway.

## 7. Cleanup, retry, GUI / CLI
- From the E6E targeted test in this run: G2 cleanup gives `{"delete_device": "ok", "delete_mesh": "ok"}`, and the same-name
  re-import of G1 succeeds.
- The GUI refusal checks for measurement, electrodes and dc-op, and the CLI refusal check, all pass. Each had 0 solve and 0 doping
  writes.
- The new reason codes use the same exception class. No end-to-end GUI/CLI test exercised `MESH_AREA_UNCERTAINTY_TOO_LARGE` itself;
  that path is established by reading the code only.

## 8. Changes (commit `f2bd558`; profile/request `8915754`; `r1_code.patch`, 669 lines, sha256 `e8bad6c6299d846bf66df50ef565a0176e41b0b0d327778a7786105c40aafa4f`, `git apply --check -R` ok)
**Production — `tcad/device/devsim/mesh_conservation.py` only.** The hunks:
- `@@ -28` adds `BUDGET_BASIS` and `MAX_AREA_RELATIVE_UNCERTAINTY = 1e-8`.
- `@@ -85` adds a non-finite o_t / e_t refusal in `check_mesh_input`.
- `@@ -98` and `@@ -105` make the E_NV computation overflow-safe (inf -> refused later).
- `@@ -109` restructures `check_nodevolume` into the ordered checks of section 3, with new status fields.

**Unchanged:** `mesh_import.py`, `tcad_2d_stagewise.py`, the CLI, `mesh_refine.py`, `tcad/physics`, examples and DEVSIM. `git diff
--quiet 599530e HEAD` on these gave rc 0.

**Tests:**
- Unit test updated to the contract.
- New `tests/integration/test_mesh_gate_small_laplace_control_real.py`.

**Audit files:** `scripts/p0_counterexample.py` (with a small key-compatibility change after `p0_before.json` was produced), `diag_r1.py`
and `run_r1.py`.

**E6E:** a separate `SUPPLEMENT_1.md` records the correction. The E6E PLAN, REPORT and data are unchanged (`git diff --quiet` rc 0).

## 9. Hygiene
`git diff --check` over the code range `853d400..8915754`: rc 0 in the normal environment, rc 0 in the clean environment.

An observation from the previous batch was re-explained. `core.autocrlf=true` comes from the system gitconfig, which the clean
environment (`GIT_CONFIG_NOSYSTEM=1`) disables. Staged-file `--cached` checks in that environment falsely reported CRLF working copies;
the committed blobs are LF (`git ls-files --eol` gives i/lf). Committed-range checks are the authoritative ones.

Raw evidence: `data/remote_run_36690617723/` (sha256 listed in the final chat report). No user path or token was found in it.

## 10. Next step (proposal only, for Codex review)
**Scope of the problem.** Two different mesh sources produce obtuse elements that DEVSIM over-integrates:
- (a) raw ViennaPS level-set meshes: near-degenerate slivers at material interfaces;
- (b) production green refinement: 116.565-degree triangles, every pass.

**Candidate (b):** use a non-obtuse refinement for the refined paths, such as the 7H-E4 quadtree candidate, instead of green
bisection.

**Candidate (a):** a local interface-preserving repair of the raw ViennaPS mesh, such as edge flips that keep the material boundary.
It could also be a ViennaPS meshing option, if one exists.

**Verification either needs:**
- the per-region gate passing at the unchanged contract;
- material-interface and boundary lengths preserved exactly;
- a small electrical control with an analytic answer;
- then a controlled re-run of the E6E-failing paths.

Neither is implemented here.
