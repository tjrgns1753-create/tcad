# WaferState v2 — 2D material-cell identity, lineage, provenance, conservative dopant transfer

Base commit: `3ba9404`. Branch: `claude/waferstate-v2`. This design is
step 2 of the task's own `[실행 절차]`; the implementation follows it.

## 0. Purpose, in one sentence

Make the wafer's material and dopant STATE survive any user-chosen
process order without vanishing or resurrecting — so that when real
diffusion / implant / segregation models are added later, they attach
to a state that is already geometrically and provenance-correct.

This is **not** a physics-model task. No new diffusion coefficient,
segregation coefficient, implant range/straggle, or activation ratio
is created here.

## 1. What v2 solves

- **2D geometry identity.** A MODELLED material cell gains `y_min` (the
  v1 `_Cell` has only `x_min/x_max/y_max`), so a cell is a real 2D
  rectangle with a real area, not an x-interval with a top edge —
  **but only when all four bounds are explicitly known** (§7.0); a
  cell migrated without a real `y_min` is `LEGACY_UNRESOLVED`, not a
  rectangle with a guessed floor.
- **Material-instance identity.** Every deposition / regrowth creates a
  new `material_instance_id`. "Si" deposited after an etch is a
  DIFFERENT instance from the original "Si" even though the material
  name is identical.
- **Lineage.** Each cell records which prior instance(s) or conversion
  event it descends from.
- **Spatial provenance events.** Every process transformation writes a
  `SpatialEvent` (`PRESERVED / REMOVED / ADDED / CONVERTED / REPLACED /
  UNSUPPORTED_BY_MODEL`) with input/output ids and spatial extent. The
  single flat `last_step_category` field is removed from every physics
  / doping-transfer / measurement decision path.
- **Conservative dopant transfer, where geometry permits it.** A
  dopant attachment binds to a specific `material_instance_id` and a 2D
  support region. When a step removes part of that support, only the
  removed sub-region's inventory is removed; the rest is preserved,
  clipped to the surviving geometry. Where the current geometry
  representation cannot support an exact clip, the event is
  `UNSUPPORTED_BY_MODEL` — never an invented clip.

## 2. What v2 does NOT solve (explicit)

- **2D diffusion PDE.** No `∂C/∂t = ∇·(D∇C)` solve. `thermal_history`
  is still just a raw `ThermalEvent` list; no model consumes it here.
- **Energy/dose-based implantation.** No projected range, no straggle
  from energy, no oxide-screening of an implant. The existing
  shape-placement implant models (`gaussian_v1`, `implant_windows_v1`)
  are unchanged; a real dose/energy implant is a later task gated on
  the ViennaPS spike in §8.
- **Oxidation dopant redistribution / segregation / pile-up.** When a
  real oxidation consumes Si that carried dopant, v2 records the
  conversion and moves the affected attachment to an *unresolved
  chemical inventory ledger*. It does NOT place that dopant into the
  new SiO2 or the new Si/SiO2-interface Si. Any device query that
  would depend on it returns `UNSUPPORTED_BY_MODEL`.
- **Dopant activation.** Chemical concentration vs electrically-active
  concentration are kept as separate fields; where no activation model
  exists the active value is `UNKNOWN`, never silently "100% active".
- **Epitaxy / in-situ doping of a new layer.** A newly deposited or
  regrown layer has zero dopant attachment unless the user explicitly
  supplied an in-situ doping input AND a model to evaluate it — out of
  scope here, so: zero.

## 3. Role separation for literature (per `[문서 요구]`)

- **Fabrication papers** (e.g. Villani et al. n-on-p diode,
  arXiv:2407.13705) are **process-sequence validation cases**: they
  tell us which real steps ran in which order and what device result
  came out. They are the end-to-end acceptance target, not a source of
  constitutive equations.
- **Constitutive-equation papers** (Deal–Grove for oxide growth;
  Christensen et al. 2003 for B/P equilibrium diffusivity;
  Grove–Leistiko–Sah for oxidation-boundary dopant behaviour) are the
  **numerical-model basis**: a diffusion coefficient or a segregation
  coefficient is only ever taken from one of these, within its stated
  validity range, never from a fabrication paper and never invented.
- v2 itself needs **neither** — it moves numbers around conservatively
  and marks the rest unsupported. The literature split is documented
  here so the next task starts from the right place.

## 4. Backend capability blockers (verified this session, not assumed)

Introspection of the installed `viennaps` module (version reported:
`4.6.2`) and `viennals`:

| Needed for | ViennaPS 4.6.2 Python binding provides | Blocker |
|---|---|---|
| ion implant with real dose/energy | **nothing** — `dir(viennaps)` has no `Implant`/`Implantation`/`Anneal`/`Diffusion` class; only `DenseCellSet` (a cell grid with `addScalarData`/`getScalarData`/`readCellSetData` slots) and `SurfaceDiffusionParameters` (a surface-diffusion parameter struct, not a dopant model) | **HARD.** No volume-process model reads a dopant field, diffuses/implants it, and writes it back. `DenseCellSet` is infrastructure with no model attached. |
| per-material-instance identity | material is by NAME/index only (`Domain.getMaterialMap()`, `Material` enum). A re-deposited `Si` level set is indistinguishable from the original `Si`. | **HARD at the ViennaPS layer.** v2 must assign and thread instance ids itself (TCAD layer), not read them from ViennaPS. |
| which Si volume an oxidation consumed | `Oxidation` returns a new domain via `saveVolumeMesh()`; there is no "consumed region" or "converted cells" output. `getGeometricModel()` returns the input model. | **HARD.** The binding exposes no consumed region. A pre/post mesh comparison may *suggest* one, but it is NOT an admissible source for a MODELLED v2 transition. Without an explicit representable `GeometryTransform`, v2 records `UNSUPPORTED_BY_MODEL`. |
| pre-step ↔ post-step cell correspondence | each `WaferState.query()` / `from_process_result()` is a fresh voxel/triangle mesh of the CURRENT geometry. Nothing computes overlap against the prior decomposition. `Domain.addMetaData()`/`getMetaData()` exists but the GUI runs every step in a `worker_main()` subprocess, so a live domain (and any metadata written on it) does not round-trip across GUI steps — only the `.vpsd` level sets and the exported mesh file do. | **HARD.** v2 retains the prior state, but does not derive overlap from meshes. It performs clipping only from an explicitly supplied, exact, representable `GeometryTransform`. Without that transform, the transition is `UNSUPPORTED_BY_MODEL`. |

**Consequence for this task:** the tractable rules (§6 A/B/D/E for
rectangular decompositions, and the material-name-vs-instance
distinction) are implementable now in pure Python from the v2 state
object plus an **explicit `GeometryTransform` (§5.5)** — never from the
exported mesh alone, which is only ever validation evidence. The
oxidation-conversion rule (§6 C) and any non-rectangular etch clip are
implemented as *explicit `UNSUPPORTED_BY_MODEL` events with a recorded
unresolved-inventory ledger entry* — not as a guess.

## 5. Data model

Coordinates are micrometres (`_um` suffix on every field). Inventory
is computed in cm: `area_cm2 = (x_max-x_min)*(y_max-y_min) * 1e-8`
(1 um² = 1e-8 cm²), and for a cell of uniform concentration `C`
[cm⁻³], the inventory per unit out-of-plane depth is `C * area_cm2`
[cm⁻¹]. This formula is stated in the docstring of the inventory
function and asserted by test 1.

### 5.1 `MaterialCell`

```
cell_id: str                      # stable within one WaferState
material: str                     # real material name ("Si", "SiO2", ...)
bounds_um: (x_min, x_max, y_min, y_max)
material_instance_id: str         # NEW per deposition/regrowth; stable across PRESERVED steps
lineage: tuple[str, ...]          # parent material_instance_id(s) and/or conversion event id(s)
lifecycle: "ACTIVE" | "REMOVED" | "CONVERTED" | "LEGACY_UNRESOLVED" | "UNRESOLVED"
          # LEGACY_UNRESOLVED: migrated from a source without an exact y_min /
          #   material lower boundary (§7.0). Never usable as active doping.
          # UNRESOLVED: an unmodelled (fail-closed) step ran on this cell, so
          #   its geometry is no longer trusted. `is_modelled` is False for
          #   both LEGACY_UNRESOLVED and UNRESOLVED; a later concrete
          #   deposition still adds real ACTIVE cells.
provenance_event_ids: tuple[str, ...]
```

### 5.2 `DopantAttachment`

```
attachment_id: str
species: str | None               # "B", "P", ... ; None when the source never named one
polarity: "donor" | "acceptor"
chemical_state: "CHEMICAL" | "ACTIVE" | "UNKNOWN"   # which the concentration represents
concentration_at: (x_um, y_um) -> cm^-3            # magnitude, >= 0
support_instance_id: str          # the material_instance_id this attachment lives in
support_region_um: (x_min, x_max, y_min, y_max)    # 2D support
creation_event_id: str
provenance: Source | None
model: str                        # "uniform_v1" | ... (carried from DopantProfile)
model_params: dict                # opaque outside that model
inventory_cm_per_depth: float | None   # conserved value, or None -> compute from concentration_at over support
```

A v1 `DopantProfile` is x-only. v2 preserves that honestly: the
attachment's `concentration_at` ignores `y_um` (the x-only profile is
applied over the full 2D support). **No y distribution is invented.**

**`attach_dopant()` creates an ACTIVE (queryable) attachment ONLY when
all of (review P0):**

- `support_instance_id` is an `ACTIVE` + MODELLED instance *right now*;
- `support_region_um` is an exact rectangle (not `None`);
- an exact `inventory_integral` callable is supplied (uniform / step /
  windowed / Gaussian — a profile with no closed-form integral is
  rejected, never numerically integrated);
- `support_region_um` lies entirely within that instance's known
  geometry.

Any other request (`LEGACY_UNRESOLVED` / `UNRESOLVED` / nonexistent
instance; unknown or out-of-bounds support; no exact integral) creates
NO active attachment. It records an `UNSUPPORTED_BY_MODEL` doping
`SpatialEvent` and an `unresolved_inventory` entry
(`total_cm_per_depth = None`, `quantity_status =
"UNKNOWN_GEOMETRIC_SUPPORT"`), so nothing downstream — including
`net_doping_at()` — can read an electrical doping number for it.

Symmetrically, `net_doping_at()` returns all-`None` (not a number, not
0) for a point covered by an attachment whose `support_region_um`,
`inventory_integral`, or `inventory_cm_per_depth` is `None` — "I don't
know the inventory but here's an electrical number anyway" is not an
allowed path.

### 5.3 `SpatialEvent`

```
event_id: str
category: "PRESERVED" | "REMOVED" | "ADDED" | "CONVERTED" | "REPLACED" | "UNSUPPORTED_BY_MODEL"
process_category: str             # "etching", "deposition", "oxidation", "doping", "remesh", ...
input_cell_ids: tuple[str, ...]
output_cell_ids: tuple[str, ...]
input_attachment_ids: tuple[str, ...]
output_attachment_ids: tuple[str, ...]
extent_um: (x_min, x_max, y_min, y_max) | None
model_status: "MODELLED" | "UNSUPPORTED_BY_MODEL"
note: str
```

### 5.4 `WaferStateV2`

```
cells: tuple[MaterialCell, ...]                  # ACTIVE + historical (REMOVED/CONVERTED kept for provenance)
attachments: tuple[DopantAttachment, ...]
events: tuple[SpatialEvent, ...]
unresolved_inventory: tuple[UnresolvedInventory, ...]   # dopant whose fate a real conversion made unknown
grid_delta_um: float
# deprecated, serialization only, read by NOTHING in the physics/doping/measure path:
last_step_category: str | None = None
```

`UnresolvedInventory`:

```
species: str | None
polarity: "donor" | "acceptor"
total_cm_per_depth: float | None      # a NUMBER only when the source attachment had an EXACT 2D support
quantity_status: "KNOWN_EXACT" | "UNKNOWN_GEOMETRIC_SUPPORT"
origin_attachment_id: str
conversion_event_id: str
note: str
```

- Only a **MODELLED** attachment with an exact 2D support region (all
  four bounds known) can record a numeric `total_cm_per_depth`
  (`quantity_status = "KNOWN_EXACT"`).
- An attachment that came from a v1 state or a `LEGACY_UNRESOLVED`
  cell (no `y_min`, so no area, so `C[cm⁻³]` cannot be turned into a
  `total_cm_per_depth`) is recorded with `total_cm_per_depth = None`
  and `quantity_status = "UNKNOWN_GEOMETRIC_SUPPORT"`.
- This ledger entry is **not** "the full total, preserved". What is
  preserved is the *provenance* and the *fact that the amount is now
  unresolved* — never a claim about a computable atom count that the
  geometry never supported.
- Either way, a device-active-doping query against the affected region
  returns `UNSUPPORTED_BY_MODEL`.

### 5.5 `GeometryTransform` — the explicit transition contract (필수 보완 2)

`ProcessResult` / the exported mesh alone CANNOT safely decide a
modelled etch / deposition / conversion: it carries no
`material_instance_id`, no oxidation consumed-volume, and no pre/post
cell correspondence (§4). Approximating a real ViennaPS mesh with
voxels or rectangles and calling the result an "exact etch/oxidation
transfer" is forbidden.

So `advance_wafer_state()` does **not** infer the transition from
`(prior_state, ProcessResult, category)` alone. It requires an explicit
`GeometryTransform` (a.k.a. `ProcessDelta`) that the process layer must
supply, or the step is recorded as `UNSUPPORTED_BY_MODEL`:

```
GeometryTransform:
  process_category: str
  representable: bool          # True ONLY if every extent below is an EXACT axis-aligned rectangle
                               # with all four bounds explicitly known -- never inferred from y_max alone
  removed_extents_um:  tuple[(x_min,x_max,y_min,y_max), ...]   # exact, or ()
  added_cells: tuple[(material, (x_min,x_max,y_min,y_max), new_instance_id), ...]  # exact known additions
  converted_extents_um: tuple[(x_min,x_max,y_min,y_max), ...]  # exact Si->oxide consumed regions, or ()
  input_instance_ids:  tuple[str, ...]
  output_instance_ids: tuple[str, ...]
  note: str
```

- `representable == False` (or a `GeometryTransform` not supplied at
  all) → `advance_wafer_state()` records an `UNSUPPORTED_BY_MODEL`
  `SpatialEvent` for the whole step, moves every affected attachment to
  `unresolved_inventory` (with a numeric total only where its own 2D
  support was already exact — §5.4 `quantity_status`), and produces NO
  modelled clip / split / conversion. This is the default, fail-closed
  path.
- `representable == True` → the transform is still **structurally
  validated** before any modelled rule runs (review P1), and any of
  the following also fails closed: extents with non-positive area or
  that overlap; `input_instance_ids` empty, or naming an instance that
  is not `ACTIVE` + MODELLED now; an oxidation target whose material is
  not Si; a deposition `added_cell` with non-positive area, a
  `new_instance_id` that collides with an existing instance or repeats
  within the transform, or an `output_instance_ids` that does not match
  the instances actually added.
- Once validated, the §6 modelled rules run. Every etch / deposition /
  conversion extent is read **only** from the transform's
  `removed_extents_um` / `added_cells` / `converted_extents_um`. No
  extent is estimated, approximated, widened, rounded, or generated
  from a mesh. Each `SpatialEvent` owns one exact intersection
  rectangle, and each clipped attachment piece's `creation_event_id`
  is the event for the rectangle that actually clipped THAT piece —
  never the instance's first or last event.
- Whether a real process can currently produce a `representable=True`
  transform is itself a capability question. Today: a blanket
  (full-width) etch or deposition on an axis-aligned wafer CAN
  (the extent is the whole domain or a known mask span); a curved
  isotropic-etch front, a Bosch scallop, a real oxidation front,
  and any masked partial etch whose sidewall ViennaPS advected to a
  non-grid position CANNOT, and go through the fail-closed path.

## 6. Preservation rules per process

Every rule below runs **only** when a `GeometryTransform` with
`representable == True` is supplied (§5.5). Otherwise the step is the
fail-closed `UNSUPPORTED_BY_MODEL` event and none of the modelled
splitting/clipping/conversion happens.

### A. Etch (`process_category == "etching"`)

- The removed extent is read **only** from
  `GeometryTransform.removed_extents_um` (§5.5). The pre/post mesh is
  used only as evidence to *validate* that transform (e.g. confirm the
  material really is gone there); it is never the source the extent is
  estimated or generated from.
- For each removed rectangle: an ACTIVE cell fully inside it becomes
  `REMOVED`; a cell partly inside is split into a surviving
  `MaterialCell` (same `material_instance_id`, lineage unchanged,
  `PRESERVED`) and a `REMOVED` remainder, both being exact rectangles
  from the intersection of two exact rectangles.
- A `DopantAttachment` on that instance is clipped to the surviving
  sub-rectangle. `removed_inventory = C * removed_area_cm2`,
  `remaining_inventory = C * remaining_area_cm2`, and the event asserts
  `initial == removed + remaining` (test 1).
- An attachment whose support does not intersect any removed rectangle
  is untouched (`PRESERVED`).
- **Blocked case:** `GeometryTransform.representable == False` (curved
  front, re-entrant profile, non-grid sidewall) → the §5.5 fail-closed
  path: `UNSUPPORTED_BY_MODEL` event; the attachment goes to
  `unresolved_inventory` (numeric total only if its own support was
  exact, else `total=None` / `UNKNOWN_GEOMETRIC_SUPPORT`); no clipped
  value is produced.

### B. Deposition (`process_category == "deposition"`)

- Always mints a fresh `material_instance_id` for the deposited
  material.
- The new cell's `attachments` are empty. Inventory 0.
- No prior attachment is auto-connected to the new instance even if
  its x-range or material name coincides. Event category `ADDED`.
- In-situ doped deposition is out of scope — not added.

### C. Oxidation / material conversion (`process_category == "oxidation"`)

- The converted extent is read **only** from
  `GeometryTransform.converted_extents_um` (§5.5) — never inferred from
  a mesh. For each converted rectangle the original Si cell becomes
  `lifecycle = "CONVERTED"` with a `CONVERTED` event, and a new SiO2
  cell is added with a new instance id and lineage `= (converted event
  id,)`.
- Any `DopantAttachment` whose support intersects a converted rectangle
  has that intersecting portion moved to `unresolved_inventory`
  (`note = "Si consumed by oxidation; B/P redistribution + segregation
  not modelled"`; numeric total only if the support was exact). It is
  **NOT** placed into the SiO2 or the remaining Si. `model_status =
  "UNSUPPORTED_BY_MODEL"`.
- Non-intersecting attachments (protected by a real oxidation mask, so
  their x-position stayed real Si) are `PRESERVED` with their real
  value — the partial-aggregate contract, matching CE-2.
- **Blocked case:** `representable == False`, or no
  `converted_extents_um` supplied → the §5.5 fail-closed path. Do NOT
  claim "doping preserved through oxidation"; emit an
  `UNSUPPORTED_BY_MODEL` event for the affected region and ledger the
  affected attachments (numeric total only where the support was
  exact).

### D. Redeposition / regrowth

- New Si after an etch of doped Si: new `material_instance_id`,
  different from the etched Si's.
- The old Si's `DopantAttachment` must NOT auto-connect to the new Si
  instance (test 2, test 3). Lineage/provenance distinguish them.
- Epitaxy dopant / re-doping unsupported until a model exists.

### E. Remesh / geometry sync

- A `PRESERVED` event. `material_instance_id` and lineage are
  unchanged. Preserved active chemical inventory is bit-unchanged
  regardless of a different node count or cell subdivision (test 5).
- **Blocked case:** if the two geometries cannot be matched cell-to-
  cell well enough for an exact transfer, return an explicit
  unsupported status — do not claim preservation.

## 7. Migration path

### 7.0 v1 → v2 is fail-closed (필수 보완 1)

The v1 `_Cell` has `x_min/x_max/y_max` and **no `y_min`** and no
material-lower-boundary. Therefore:

- A **MODELLED** v2 `MaterialCell` is created ONLY when an exact
  `(x_min, x_max, y_min, y_max)` is explicitly provided (from a
  `GeometryTransform` with `representable == True`, §5.5, or from a
  future geometry source that genuinely carries all four bounds).
  `y_min` is NEVER set to 0, to the domain floor, or to any other
  inferred value.
- When an existing v1 `WaferState` (or a bare exported mesh) is
  auto-migrated and `y_min` / the material's lower boundary is not
  available, the resulting cell is `lifecycle = "LEGACY_UNRESOLVED"`
  and every `SpatialEvent` touching it is `UNSUPPORTED_BY_MODEL`.
- A `DopantAttachment` whose support is a `LEGACY_UNRESOLVED` cell is
  **not** silently usable as electrical active doping: a
  device-active-doping query against it returns `UNSUPPORTED_BY_MODEL`.
  It is recorded in `unresolved_inventory` with `total_cm_per_depth =
  None` and `quantity_status = "UNKNOWN_GEOMETRIC_SUPPORT"` (§5.4) — a
  numeric atom count is **not** invented, because there was never a
  real area to compute one from. What is kept is the provenance and
  the fact that the amount is unresolved.
- There is **no** "one-line construction change" that turns existing
  v1 information into a physically complete v2 state. The compatibility
  methods (§7.3) let old call sites keep running; they do not upgrade
  the underlying state's completeness.

### 7.1 module

New module `tcad/physics/wafer_state_v2.py` holds the dataclasses in §5
and the pure transfer functions in §6. No ViennaPS/DevSim import at
module top level.

### 7.2 threading point

`advance_wafer_state()` (`wafer_state_accumulation.py`) becomes the
single v2 threading point: it takes the prior `WaferStateV2` (or None),
the new `ProcessResult`, the process category, **and a
`GeometryTransform` (§5.5)**. With no transform, or a non-representable
one, it records the fail-closed `UNSUPPORTED_BY_MODEL` event.

### 7.3 compatibility surface

The v1 query methods real consumers use — `net_doping_at(x, y)`,
`exposed_material_at(x)`, `exposed_materials()`, `under_resolved_x()` —
are provided by `WaferStateV2` computed from v2 `cells` / `attachments`
/ `events`, so `doping_mapping.apply_doping()`, `resolve.resolve()`,
and the GUI overlay keep working. A `LEGACY_UNRESOLVED` cell or an
`UNSUPPORTED_BY_MODEL` region surfaces through `net_doping_at()`'s
existing `physics_status` channel exactly as the v1
`UNSUPPORTED_BY_MODEL` path already does — never as a silent number.

### 7.4 last_step_category removal

`last_step_category` is removed from `_polarity_sum()` and from
`doping_mapping.apply_doping()`'s change-kind branch. The
removal/conversion decision instead reads the v2 `events` /
`unresolved_inventory` for the queried region.
`MATERIAL_CHANGE_KIND_BY_CATEGORY` is retired from the decision path
(kept only if a test still needs the table for constructing a fixture,
and then only in test code).

### 7.5 static check

Test 6 asserts no production module under `tcad/` reads
`last_step_category` for a physics / doping / measurement decision.

## 8. Next step — ViennaPS implant/anneal binding capability spike

Before ANY implant/anneal model spec is written:

1. Enumerate the installed `viennaps` module for implant/anneal/
   diffusion volume-process classes (done here: none in 4.6.2).
2. Test whether `DenseCellSet` can carry a concentration scalar field,
   be written, and be read back (`addScalarData` / `setFillingFraction`
   / `getScalarData` / `readCellSetData` round-trip) — a minimal real
   run, not documentation reading.
3. Check whether the documented cell-based implant/anneal is a
   development-branch feature vs the installed release, and whether a
   dimension-specific submodule (`viennaps.d2` / `viennaps.d3`) exposes
   anything the top-level module does not.

**The output of this task, regardless of the spike's result, is:**
keep the affected transitions `UNSUPPORTED_BY_MODEL`, and record the
capability evidence (what the introspection and the round-trip
experiment actually showed). This task does **not** pre-decide to
"implement an implant source term on the DevSim mesh" — that is a
separate physics model requiring its own literature grounding and its
own approval, out of scope here. If the spike shows no usable binding,
that fact is documented and the transition stays unsupported; nothing
is built to fill the gap in this task.

## 9. Tests (map to `[이 작업에서 반드시 구현할 테스트]`)

| # | file | backend | asserts |
|---|---|---|---|
| 1 | `tests/unit/test_wafer_state_v2_etch_conservation_mock.py` | none | remaining + removed == initial inventory; support-outside doping survives |
| 2 | `tests/unit/test_wafer_state_v2_redeposit_no_resurrection_mock.py` | none | new instance id; new cell inventory 0; old attachment not linked; lineage distinguishes |
| 3 | `tests/unit/test_wafer_state_v2_instance_not_name_mock.py` | none | a name-only attachment lookup FAILS (is made to fail) |
| 4 | `tests/unit/test_wafer_state_v2_oxidation_unsupported_mock.py` | none | no invented active dopant; unresolved ledger entry present; device-active query returns UNSUPPORTED_BY_MODEL |
| 5 | `tests/unit/test_wafer_state_v2_remesh_preserved_mock.py` | none | inventory unchanged; PRESERVED provenance; lineage intact |
| 6 | `tests/unit/test_wafer_state_v2_no_last_step_category_mock.py` | none | AST scan of production `tcad/` + `tcad_2d_stagewise.py`: 0 code references to `last_step_category` / `MATERIAL_CHANGE_KIND_BY_CATEGORY`; v2 etch/deposition/oxidation decisions driven only by SpatialEvent / GeometryTransform / unresolved ledger |
| 7 | `tests/integration/test_wafer_state_v2_order_counterexample_real.py` | real ViennaPS | see §9.1 — representability first (NOT YET IMPLEMENTED — deferred with the caller-migration full-regression phase) |
| 8 | `tests/integration/test_wafer_state_v2_viennaps_real.py` | real ViennaPS | see §9.1 — representability first (NOT YET IMPLEMENTED — deferred) |
| 9 | `tests/unit/test_wafer_state_v2_legacy_migration_fail_closed_mock.py` | none | a v1 source with no `y_min` is NOT promoted to a MODELLED `MaterialCell` (stays `LEGACY_UNRESOLVED`); `attach_dopant()` on it creates NO active attachment (ledger entry, `total is None`, `UNKNOWN_GEOMETRIC_SUPPORT`); device query returns `UNSUPPORTED_BY_MODEL`, all three values `None` |

### 9.2 Review-added unit tests (all implemented and passing)

| file | asserts |
|---|---|
| `test_wafer_state_v2_exact_inventory_mock.py` | uniform inventory over a non-lattice rectangle is EXACT (`==`, not "within a cell"); no sample grid |
| `test_wafer_state_v2_unsupported_returns_none_mock.py` | LEGACY / UNSUPPORTED query → donor/acceptor/net ALL `None` (never 0); a supported un-doped point still returns 0 |
| `test_wafer_state_v2_fail_closed_no_resurrection_mock.py` | a fail-closed step drops the attachment permanently; a later valid transform never resurrects it as numeric doping |
| `test_wafer_state_v2_transform_targets_instance_mock.py` | etch changes only the `input_instance_ids` instance; an untargeted instance is PRESERVED bit-for-bit despite spatial overlap; invalid targeting → fail-closed |
| `test_wafer_state_v2_no_numeric_without_exact_integral_mock.py` | no exact integral / no exact support → `net_doping_at()` three values `None`; `attach_dopant()` onto an UNRESOLVED instance → 0 active attachments |
| `test_wafer_state_v2_multi_extent_provenance_mock.py` | each surviving attachment piece's `creation_event_id` is the exact-intersection event that clipped THAT piece; removed inventory attributed per event rectangle |
| `test_wafer_state_v2_transform_structural_validation_mock.py` | non-positive/overlapping extents, non-ACTIVE+MODELLED target, non-Si oxidation target, deposition area/id-collision/id-duplicate/output-mismatch → each fail-closed |
| `test_wafer_state_v2_devsim_mapping_gate_mock.py` | `apply_doping()` writes NetDoping only for a representable+exact state; LEGACY / fail-closed / oxidation-converted / any `None` node → `UnsupportedDopingState`, NOTHING written; no RECOVERY path |

### 9.1 Integration-test verdict rule (필수 보완 3)

Tests 7 and 8 are **not** allowed to demand a modelled-conservation
result merely because a real ViennaPS run was involved.
**Representability is checked first.** Each relevant region / transform
extent from the real run is classified, and exactly one branch is
asserted:

**Branch A — the real backend run proved every relevant region and
transform extent is an EXACT axis-aligned rectangle with all four
bounds known** (e.g. a blanket full-width etch/deposition on an
axis-aligned wafer):
- assert numeric inventory conservation (`remaining + removed ==
  initial`, to a stated tolerance)
- assert `material_instance_id` lineage (new instance after deposition;
  same instance across a PRESERVED step; distinct instances for the two
  process orders in test 7)

**Branch B — a curved etch/oxidation front, a Bosch scallop, a
non-grid-aligned advected sidewall, or an uncorrespondable mesh**
(i.e. `GeometryTransform.representable == False`):
- assert a `SpatialEvent` with `category == "UNSUPPORTED_BY_MODEL"` for
  the affected region
- assert an `unresolved_inventory` ledger entry exists, and split the
  assertion by whether its total was geometrically computable:
  - the affected attachment's own 2D support was already exact
    (`KNOWN_EXACT`) → assert the entry's `total_cm_per_depth` equals
    that exact total
  - the affected attachment came from a v1 state / `LEGACY_UNRESOLVED`
    cell / any support with an unknown area → assert
    `total_cm_per_depth is None` and `quantity_status ==
    "UNKNOWN_GEOMETRIC_SUPPORT"`
- assert a device-active-doping query against that region is blocked
  (returns `UNSUPPORTED_BY_MODEL` via `physics_status`, not a number)
- assert **zero** invented active dopant anywhere (count of modelled
  attachments created for the unsupported region == 0)

The oxidation-redistribution case in test 8 is always Branch B with
this project's current geometry sources.

## 10. Completion criteria — see the task's own `[완료 판정]`

`git diff --check` 0 lines; existing files stay LF; **all 9 tests
PASS** (the 8 in `[이 작업에서 반드시 구현할 테스트]` plus test 9, the
legacy-migration fail-closed test added by review); zero production
`last_step_category` reads in a decision path; no-resurrection
counterexample PASS; oxidation redistribution exposed as
`UNSUPPORTED_BY_MODEL`; v1/`LEGACY_UNRESOLVED` inventory never
numericised (`total is None`, `quantity_status ==
"UNKNOWN_GEOMETRIC_SUPPORT"`); full regression baseline-separated;
changed-file list + commit hash + `git status` reported; commit only
after all of the above.
