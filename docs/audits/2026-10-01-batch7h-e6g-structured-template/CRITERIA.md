# Batch 7H-E6G criteria: structured-grid transition-template remeshing for the implant-windows refinement (fixed before implementation)

**Base.** HEAD `cff5350d190ad80a181f0e771492a50b0c3f60bb`, tracked dirty 0. Production `mesh_refine.py` equals `0ef6dd2` (rc 0; LF blob
`e6b35668…`). No TCAD evaluation process was running.

**Serena** (session a99b0b38, project tcad):
- `refine_process_result_for_implant_windows` is called in production only by GUI `TCADApplication._refine_for_implant_windows`, and in
  tests by `test_gui_measurement_doping_kinds_real` and `test_robust_iv_sweep_real`.
- `derive_implant_windows_refinement` is also called directly by 5 MOSFET tests (with interface rings) and by audit scripts.
- `graded_refine_mesh_near` is called by the importer (auto refinement), by `refine_process_result_for_mos_gate`, and by the MOSFET tests.
- Contacts are rebuilt by the importer from boundary edges by coordinate, and pins resolve by coordinate
  (`contact_probe.resolve_pins_to_point_contacts`). No caller keeps a node ID across refinement.
- Doping is looked up per DEVSIM node from the canonical state (`canonical_node_doping`); nothing is interpolated from old nodes.

## Supported input (all must hold, else the structured builder refuses with a reason and the caller keeps the existing path)
- One material region, named `Si`; every triangle carries that tag; z = 0.
- The node set equals the full tensor product of its distinct x values and distinct y values, compared exactly. So the domain is an
  axis-aligned rectangle and there are no missing or extra nodes.
- The triangle count is 2 x (cells). Every triangle is half of exactly one grid cell: its vertices are 3 of that cell's 4 corners. Every
  cell has exactly two triangles, which share a diagonal. This excludes holes, overlaps and missing areas without guessing from the
  point pattern.
- The request is an implant-windows request along x only: `junction_axis == "x"` and no interface rings. The centers and ring half
  widths come from the same derivation production uses; nothing is hard-coded.

## Construction
- Each original column is partitioned by a 1D binary tree (midpoint splits, float64).
- A leaf interval at depth d is a strip one sub-cell wide. Each of its rows is split into 2^d sub-rows by recursive midpoints of that
  row's own y interval.
- Depth rule: a strip is split while some ring k with `strip ∩ {|x - c| < hw_k} != ∅` requires depth >= k + 1. Neighbouring strips are
  then 2:1 balanced by splitting the coarser one.
- Sub-cells are split into two right triangles.
- A coarser strip next to a finer one uses a transition template in each sub-cell: the midpoint M of the edge on the finer side gives
  three triangles, or four when both sides are finer (a horizontal split through both midpoints).
- The one-sided template is non-obtuse iff w >= h / 2, where w and h are that sub-cell's own width and height. This is checked exactly
  with rational arithmetic on the actual coordinates. A failing sub-cell aborts the construction explicitly; there is no fallback to
  global refinement.
- Original nodes keep their indices and coordinates (they come first); new nodes are appended. The output is independent of the input
  node and triangle order.

## Acceptance
- **A-D** (2-cell counterexample; small uniform grid with a local window; float32 coordinates with slightly anisotropic cells; a
  shifted center and two separate windows), full exact check:
  - 0 obtuse, 0 degenerate, a single orientation;
  - no duplicate triangles or coordinates;
  - edge owners <= 2 with opposite directions, and 0 hanging nodes (exact point-in-edge test);
  - exact area equal to the input;
  - outer boundary segments exactly covered;
  - original nodes kept;
  - target resolution: every output triangle whose centroid lies in ring k's band has x-extent <= column width / 2^(k+1) and y-extent
    <= row height / 2^(k+1), checked exactly. Its max edge is also compared with the old module's triangles in the same band.
- **Order control:** the same geometry with permuted node and triangle order gives the same canonical output (sorted coordinate triples).
- **E** (B_raw at 1e16) and **F** (GUI wafer at 1e20):
  - triangle and node counts are computed before allocation, with the 400,000-triangle cap;
  - target resolution and boundary are checked;
  - exact obtuse / area are checked where the size allows; any skipped check is marked NOT_VERIFIED.
- **G:** two materials, a non-rectangular domain, a missing triangle, y-axis windows, interface rings and a failing aspect condition are
  each refused with a reason.

## Remote (one profile)
- B_raw at 1e16 through the production caller: the real importer, per-region NodeVolume against triangle area (area gate).
- The GUI wafer at 1e20 through the production caller: size, importer and area gate.
- The small Laplace control and the manufactured Poisson control (-eps psi'' = rho; tolerance fixed in the test before running).

## What this does not show
Non-obtuse elements and total-area equality are necessary conditions only. They do not show local control-volume accuracy, current
accuracy or PN convergence. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the PN/DD gates stay. No full regression and no PN/DC
sweep are run.
