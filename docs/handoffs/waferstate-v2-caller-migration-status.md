# WaferState v2 caller migration — intermediate status

Branch `claude/waferstate-v2`. This documents the explicit-initial-geometry
threading structure and the per-caller classification. It is an
**intermediate** submission: test 7/8 rewrites and CE-2/CE-3 expectation
rewrites are deliberately **not** done yet. (The thermal-anneal path is
now a fail-closed transition, row 6; every electrical measurement passes
the central canonical-state gate, rows 3/5/7 and
`docs/audits/2026-09-17-tier1-1*/`.)

## The threading structure

`initialize_wafer_state()` (in `tcad/physics/wafer_state_v2.py`) builds a
MODELLED initial `WaferStateV2` from explicit
`(material, exact_bounds_um, instance_id)` tuples. It raises `ValueError`
on non-positive-area bounds or a duplicate instance id, and tags each
cell with an `"initial_geometry"` `ADDED` `SpatialEvent`.

`initial_wafer_state_from_recipe(recipe)` (in
`tcad/physics/wafer_state_accumulation.py`) is the production adapter: it
reads `x_extent_um` / `silicon_depth_um` / `grid_delta_um` straight from
the recipe a caller is about to hand ViennaPS and builds the virgin
substrate box at exactly the coordinates
`tcad.backends.viennaps.session.create_domain` / `make_mask_spans`
construct — `x ∈ [−x_extent/2, +x_extent/2]`, `y ∈ [−silicon_depth, 0]`.
**None of the four bounds is read back from an exported mesh, a `y_max`
heuristic, or a material name.** The exported mesh is used only as
validation evidence (see `test_wafer_state_v2_initial_geometry_devsim_real.py`,
`_assert_mesh_matches_recipe_bounds`).

`advance_wafer_state(prior_state, result, category, transform=None)`:

- `prior_state=None` → still migrates the step's own mesh geometry as
  `LEGACY_UNRESOLVED` (fail-closed, design doc Sec 7.0). This is the
  Group-B fallback, not the initialisation path.
- `category` falsy (no process actually ran, e.g. the GUI's
  `_materialize_current_wafer`) → returns the state **unchanged** (no
  process ⇒ no state transition; it no longer fail-closes a materialise).
- `category` a real geometry category with `transform=None` → `v2.advance`
  fail-closes (a real ViennaPS curved etch / Deal–Grove oxidation front
  has no representable transform → `UNSUPPORTED_BY_MODEL`, the honest
  outcome).
- `category == "doping"` → `attach_dopant` per profile; attaches a real
  numeric inventory only over an ACTIVE + MODELLED instance.

The initial MODELLED state is created once and threaded as `prior_state`;
callers do **not** re-init with `advance_wafer_state(None, …)` per call.

## Per-caller classification

| # | Caller | Explicit initial geometry? | Group | Status |
|---|--------|---------------------------|-------|--------|
| 1 | `tcad_2d_stagewise.py` `_materialize_current_wafer` (virgin wafer export, no resist) | **Yes** — `self.wafer.width_um` / `silicon_depth_um` | **A** | **Wired.** Seeds `self.wafer_state` via `initial_wafer_state_from_recipe(...)` before `_sync_wafer_state_geometry({}, result)`; the empty-category sync is now identity. |
| 2 | `tcad_2d_stagewise.py` `run_doping` → `advance_wafer_state(self.wafer_state, doped_result, "doping")` | Inherits #1 | **A** when prior is MODELLED (virgin); **B** after a real process step | **Wired** (threads prior state). Virgin → attach succeeds; post-real-etch/ox → attach refused → `UnsupportedDopingState` at measure (correct Branch B). |
| 3 | `tcad_2d_stagewise.py` `run_measurement` → `apply_doping(device, region, self.wafer_state)`; Implant Windows → `run_robust_pn_junction_iv_sweep(state=self.wafer_state)` | Inherits #1/#2 | **A**/**B** | **Wired, gated (Tier 1-1).** Both branches pass `self.wafer_state` (None included) to the central gate `canonical_node_doping()` -- the robust branch no longer solves `doped_result.doping`, and no fallback state is rebuilt. The gate requires exactly one ACTIVE + MODELLED owning cell of the region's material per node before trusting `net_doping_at()`; a blocked state logs `UNSUPPORTED_BY_MODEL` with node diagnostics and reports no current. Verified with real DevSim: `test_measurement_canonical_state_gate_real.py`, `test_gui_implant_windows_overlay_note_real.py`. |
| 4 | `tcad_2d_stagewise.py` `_sync_wafer_state_geometry(recipe, result)` after a real oxidation/etch/deposition | No — real ViennaPS front, no exact post-step `y_min` | **B** | Fail-closes to `UNRESOLVED` (correct). Downstream doping → `UnsupportedDopingState`. |
| 5 | `tcad_2d_stagewise.py` `run_dc_operating_point` (gate-stack DC operating point) | No | **B** | **Fallback removed (Tier 1-1).** The synthetic-intrinsic `advance_wafer_state(None, …, "doping")` fallback is gone; `apply_doping(device, "Si", self.wafer_state)` runs the central gate first, and a blocked state logs `UNSUPPORTED_BY_MODEL` and returns None before `solve_mosfet_dc_operating_point`. Covered by `tests/unit/test_measurement_entry_point_gate_mock.py`. |
| 6 | `tcad_2d_stagewise.py` thermal-anneal handler `_on_thermal_anneal_clicked` | n/a | — | **Fail-closed transition (P0-B).** `advance_wafer_state(self.wafer_state, None, "anneal", transform=None)`: attachments move to the unresolved ledger, cells go UNRESOLVED; the v1 `replace(..., dopant_profiles=…)` write is gone. |
| 7 | `tcad/cli/run_pipeline.py` `_apply_device_doping` | Recipe `x_extent_um`/`silicon_depth_um` → `_initial_state_for_process` | **A** start, **B** after the process step | The explicit initial state is fail-closed by the (always present) process category, so doping attaches nowhere and the gate raises; with no doping configured, `pn_junction_iv`/`mos_cv` are gated on no canonical state. `UnsupportedDopingState` propagates out of `run_pipeline()`. Covered by `tests/unit/test_measurement_entry_point_gate_mock.py`. |
| 8 | `tests/integration/test_phase7_doping_real.py`, `test_phase8_pn_junction_real.py` (`advance_wafer_state(None, doped_result, "doping")`) | Recipe has `x_extent_um`/`y_extent_um`; **but** they run a real masked isotropic etch first (curved front) | **B** as written | **Deferred** (explicitly out of scope). Their doping is x-only with no y-dependence, so a Branch-A rewrite that skips the incidental etch and threads `initial_wafer_state_from_recipe` is possible — that is the deferred "test 7/8" work. Until then these two fail closed. |
| 9 | `tcad/process/etching/isotropic.py` `WaferState.query(geometry, dopant_profiles=())` | n/a | — | Not a v2 threading caller. v1 geometric-only query feeding `resolve()`; carries no doping state. Unchanged. |

New Branch-A proof (not a rewrite of an existing test):
`tests/integration/test_wafer_state_v2_initial_geometry_devsim_real.py`
— explicit-rectangle virgin Si → `initial_wafer_state_from_recipe` →
`advance_wafer_state(state, …, "doping")` → `apply_doping` writes real
numeric NetDoping → real DevSim:

- uniform 1e17: solved Potential 0.4173 V vs analytic 0.4167 V. PASS
- step junction ±1e18: real sweep, `|I|` 1.98e-11 A (blocking) vs
  6.45e-09 A (conducting) — a real diode knee. PASS
- Branch B guard: `advance_wafer_state(state, …, "etching", transform=None)`
  → `apply_doping` raises `UnsupportedDopingState`, no NetDoping node
  model created. PASS

## Barrier exclusion (P0-C)

`apply_doping()` has no `exclude_windows` any more: zeroing the
accumulated NetDoping inside a barrier window also erased pre-existing
dopant. A barrier now carves only the NEW attachment's support region at
attach time (`advance_wafer_state(..., barrier_windows=...)`). Covered by
`tests/unit/test_wafer_state_v2_barrier_physics_mock.py` and
`tests/unit/test_wafer_state_v2_apply_doping_barrier_mock.py`:

- unknown node → blocks, writes nothing
- MODELLED-virgin known-undoped 0 stays distinct from LEGACY unknown None
- a real attachment's value reaches every node it covers

## Known pre-existing failure (not caused by this branch)

`test_gui_doping_donor_acceptor_real.py` scenario 4 (SiO2-barrier
sub-scenario) asserts `derive_barrier_covered_windows()` returns a
non-empty window list; it returns `None` on a **clean HEAD** too
(verified by `git stash`). Unrelated to the v2 migration —
`derive_barrier_covered_windows` reads the mesh directly and never
touched `wafer_state`.
