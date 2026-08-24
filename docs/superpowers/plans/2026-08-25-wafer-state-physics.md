# WaferState-Driven Physics Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each process step compute its result from the wafer's real current state instead of from recipe parameters alone, without ever constraining the order the user runs processes in.

**Architecture:** A new read-only `tcad/physics/` package provides `WaferState` (queried from the live ViennaPS domain at each step) and a pure `resolve(intent, state)` function that has no history parameter. `ProcessStep.run()` queries state after `prepare_domain()`, resolves, then builds the backend model. Migration lands in stages where stages 0-2 change no results.

**Tech Stack:** Python 3.13, ViennaPS 4.6.2, ViennaLS, DevSim, meshio. Tests are standalone scripts with a `main()`, run as subprocesses by `tests/run_regression.py` — **not pytest**.

**Spec:** `docs/superpowers/specs/2026-08-25-wafer-state-physics-design.md`

## Global Constraints

- **The top-level invariant:** any order runs; results differ by *state*, never by a rule inspecting which process ran before. `resolve()` must never gain a history parameter.
- **No blocking:** no disabled button, no "run X first", no modal confirm that gates execution, no advice steering the user to a different step.
- **No invented constants.** The physics table ships empty. ViennaPS defaults are `Provenance.BACKEND_DEFAULT` + `Resolution.UNVERIFIED`, never VERIFIED.
- **`Resolution` and `Provenance` stay separate enums.**
- **`UNDER_RESOLVED` is a separate axis** from physics status, never merged into it.
- **Physics wins** over previously-recorded numbers; tests are re-measured, never reverted.
- **`materials` vs `exposed_materials()` are different concepts.** Physical results come from what is *spatially exposed*, never from the full material set.
- 2D only. Do not expand to 3D.
- Tests: standalone scripts, `tests/unit/test_*.py` (no backend) or `tests/integration/test_*.py` (real backends), each with `main()` and `if __name__ == "__main__": main()`.
- Regression command on Windows: `PYTHONIOENCODING=utf-8 python tests/run_regression.py` (the runner crashes on cp949 while printing a failing test's traceback).
- Baseline before this plan: **39 passed, 3 failed** — the 3 are pre-existing DevSim failures (`test_device_lifecycle_repeat_real`, `test_robust_iv_sweep_real`, `test_gui_measurement_doping_kinds_real`), confirmed failing at clean HEAD. Any *other* failure is a regression.

---

## File Structure

| File | Responsibility |
|---|---|
| `tcad/physics/values.py` (new) | `Resolution`, `Provenance`, `UnknownPolicy`, `Conditions`, `Source`, `PhysicalValue`. Pure data, no backend import. |
| `tcad/physics/wafer_state.py` (new) | `WaferState` + `query(domain)`. Reads the live domain. Only file here that imports ViennaPS. |
| `tcad/physics/intent.py` (new) | `ProcessIntent`, `intent_from(recipe)`. Pure data. |
| `tcad/physics/tables.py` (new) | `MATERIAL_PROPERTIES`, `INTERACTION_COEFFICIENTS`, lookup helpers. **Ships empty of interaction constants.** |
| `tcad/physics/resolve.py` (new) | `resolve(intent, state) -> ResolvedRecipe`. Pure. No history parameter. |
| `tcad/mesh/interface.py` (modify) | `ProcessResult` gains `physics_status`, `numerical_status`. |
| `tcad/mesh/viennaps_adapter.py` (modify) | `build_process_result` passes the two new fields through. |
| `tcad/process/etching/isotropic.py` (modify) | First step wired to the resolver. |
| `tcad_2d_stagewise.py` (modify) | Stage-0 stale-state fixes; worker payload + GUI log carry status. |

`tcad/physics/doping.py` already exists in that package and is untouched by this plan.

---

## Stage 0 — foundations, no result change

### Task 1: Fix the gate-stack domain-state leak

`run_gate_stack` clears `completed_steps` but not `last_domain_state`, so a later RUN resumes the **pre-gate-stack** wafer. This violates "read the current state".

**Files:**
- Modify: `tcad_2d_stagewise.py` (in `run_gate_stack`, the block that clears `self.completed_steps`)
- Test: `tests/unit/test_gui_gate_stack_state_mock.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces: nothing (behavioral fix only)

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A gate-stack build must not leave the previous wafer resumable.

run_gate_stack() clears completed_steps because a gate stack is
terminal, but last_domain_state was added later and was not cleared
with it — so the next RUN click resumed the pre-gate-stack wafer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    try:
        app.withdraw()
        app.update_idletasks()

        # Pretend a previous step left an accumulated wafer behind.
        app.completed_steps = [{"_process_category": "oxidation"}]
        app.last_domain_state = "C:/nonexistent/previous_wafer.vpsd"
        app.flow_step_meshes = ["C:/nonexistent/previous.vtu"]

        # The success tail of run_gate_stack, isolated from the worker.
        gui.TCADApplication._clear_state_for_gate_stack(app)

        assert app.completed_steps == [], "gate stack left completed_steps behind"
        assert app.flow_step_meshes == [], "gate stack left step meshes behind"
        assert app.last_domain_state is None, (
            "gate stack left last_domain_state set, so the next RUN would "
            "resume the PRE-gate-stack wafer")
    finally:
        app.destroy()

    print("GATE STACK STATE CLEARED: completed_steps, step meshes, domain state")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_gui_gate_stack_state_mock.py`
Expected: FAIL with `AttributeError: ... has no attribute '_clear_state_for_gate_stack'`

- [ ] **Step 3: Extract the clearing into a named method and add the missing line**

In `tcad_2d_stagewise.py`, replace the inline clearing inside `run_gate_stack` with a call to a new method, and add `last_domain_state`:

```python
    def _clear_state_for_gate_stack(self):
        """Gate stack is terminal and builds its own geometry from
        scratch, so nothing from the previous wafer may survive it.

        last_domain_state is the one that was missed: it was added when
        RUN clicks started resuming an accumulated .vpsd, and without
        clearing it here the next RUN resumes the PRE-gate-stack wafer.
        """
        self.completed_steps = []
        self.flow_step_meshes = []
        self.last_domain_state = None
```

Then in `run_gate_stack`, where `self.completed_steps = []` and
`self.flow_step_meshes = []` currently sit, call
`self._clear_state_for_gate_stack()` instead.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_gui_gate_stack_state_mock.py`
Expected: PASS, printing `GATE STACK STATE CLEARED: ...`

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_gui_gate_stack_state_mock.py tcad_2d_stagewise.py
git commit -m "fix: clear last_domain_state on gate stack build

A gate stack is terminal and builds its own geometry, so run_gate_stack
cleared completed_steps. last_domain_state was added later for RUN-click
state carry and was not cleared with it, so the next RUN resumed the
pre-gate-stack wafer."
```

---

### Task 2: Re-attach doping to the current mesh

`self.last_doped_result` holds a `ProcessResult` built from the mesh that existed when doping ran. A later etch moves `last_final_mesh` on, but measurement still reads the old object and solves the **pre-etch** geometry with no warning.

**Files:**
- Modify: `tcad_2d_stagewise.py` (`run_measurement`, near `doped_result = self.last_doped_result`)
- Test: `tests/integration/test_doping_follows_geometry_real.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces: `TCADApplication._doping_is_stale() -> bool`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doping must not keep pointing at a mesh a later step replaced.

last_doped_result is set once when doping runs and cleared only by NEW
WAFER. After a later process step, measurement read that stale object
and solved the geometry as it was BEFORE the step.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    try:
        app.withdraw()
        app.update_idletasks()

        class _Stub:
            pass

        doped = _Stub()
        doped.volume_mesh_path = "C:/meshes/step_A.vtu"

        app.last_doped_result = doped
        app.last_final_mesh = "C:/meshes/step_A.vtu"
        assert app._doping_is_stale() is False, (
            "doping on the current mesh must not read as stale")

        # A later process step produced a new mesh.
        app.last_final_mesh = "C:/meshes/step_B.vtu"
        assert app._doping_is_stale() is True, (
            "doping still points at the mesh from before the last step, so "
            "a measurement would solve the wrong geometry")

        app.last_doped_result = None
        assert app._doping_is_stale() is False, "no doping cannot be stale"
    finally:
        app.destroy()

    print("DOPING STALENESS DETECTED against the current mesh")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_follows_geometry_real.py`
Expected: FAIL with `AttributeError: ... has no attribute '_doping_is_stale'`

- [ ] **Step 3: Add the check and use it in run_measurement**

In `tcad_2d_stagewise.py`:

```python
    def _doping_is_stale(self) -> bool:
        """True when the doping profile describes a mesh a later step replaced.

        Doping attaches to the mesh that existed when it ran. Any process
        step afterwards produces a new mesh, and the old profile then
        describes geometry that no longer exists — measurement would
        silently solve the wafer as it was BEFORE that step.
        """
        if self.last_doped_result is None:
            return False
        attached = getattr(self.last_doped_result, "volume_mesh_path", None)
        return bool(attached and attached != self.last_final_mesh)
```

Then in `run_measurement`, immediately after `doped_result = self.last_doped_result`, re-attach rather than solving stale geometry:

```python
        if self._doping_is_stale():
            # Re-apply the SAME doping specification to the CURRENT mesh
            # instead of solving the geometry as it was before the last
            # process step. Not a prerequisite: nothing is refused, and
            # the user is told what happened.
            self._log(
                "\nNOTE: the doping profile was attached to an earlier mesh. "
                "Re-applying the same doping to the current geometry before "
                "measuring.\n"
            )
            if not self.run_doping():
                return
            doped_result = self.last_doped_result
```

`run_doping()` must return `True` on success and `False` on any early
return, so `run_measurement` can tell whether re-attachment worked. Add
`return True` at its success tail and `return False` at each existing
early `return`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_follows_geometry_real.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_doping_follows_geometry_real.py tcad_2d_stagewise.py
git commit -m "fix: re-attach doping to the current mesh before measuring

last_doped_result held the mesh from when doping ran and was cleared
only by NEW WAFER, so measuring after a later step solved the pre-step
geometry with no warning."
```

---

### Task 3: Physics value types

**Files:**
- Create: `tcad/physics/values.py`
- Test: `tests/unit/test_physics_values_mock.py`

**Interfaces:**
- Produces:
  - `Resolution` (`VERIFIED`, `UNVERIFIED`, `PARTIAL`, `UNKNOWN`, `UNSUPPORTED_BY_MODEL`)
  - `Provenance` (`LITERATURE`, `BACKEND_DEFAULT`, `USER_SUPPLIED`, `DERIVED`)
  - `UnknownPolicy` (`OMIT`, `BACKEND_DEFAULT`, `INERT`)
  - `Coverage` (`INSIDE`, `OUTSIDE`, `UNSTATED`)
  - `Range(low: float, high: float)` with `contains(v) -> bool`
  - `Conditions(temperature_c, pressure_pa, rf_power_w, gas_ratio, notes)` with `covers(requested: Mapping[str, float]) -> Coverage`
  - `Source(reference: str, kind: Provenance)`
  - `PhysicalValue(value, unit, material, chemistry, conditions, source, resolution, provenance)`
  - `combine(resolutions: Iterable[Resolution]) -> Resolution`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Physics value types: two orthogonal axes, condition windows, combination."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.values import (
    Conditions, Coverage, Provenance, Range, Resolution, combine,
)


def main():
    # --- condition windows -------------------------------------------
    window = Conditions(temperature_c=Range(20.0, 60.0), pressure_pa=None,
                        rf_power_w=None, gas_ratio=None, notes="")
    assert window.covers({"temperature_c": 40.0}) is Coverage.INSIDE
    assert window.covers({"temperature_c": 90.0}) is Coverage.OUTSIDE
    assert window.covers({"pressure_pa": 5.0}) is Coverage.INSIDE, (
        "a condition the window does not constrain must not read as OUTSIDE")

    unstated = Conditions(None, None, None, None, notes="source states no conditions")
    assert unstated.covers({"temperature_c": 40.0}) is Coverage.UNSTATED, (
        "a source with no stated conditions can never be confirmed INSIDE")

    # --- combination rule --------------------------------------------
    assert combine([Resolution.VERIFIED, Resolution.VERIFIED]) is Resolution.VERIFIED
    assert combine([Resolution.VERIFIED, Resolution.UNVERIFIED]) is Resolution.UNVERIFIED
    assert combine([Resolution.VERIFIED, Resolution.UNKNOWN]) is Resolution.PARTIAL
    assert combine([Resolution.UNKNOWN, Resolution.UNKNOWN]) is Resolution.UNKNOWN
    assert combine([]) is Resolution.UNKNOWN
    assert combine([Resolution.VERIFIED, Resolution.UNSUPPORTED_BY_MODEL]) \
        is Resolution.UNSUPPORTED_BY_MODEL, (
        "a material the model cannot represent dominates: the user's fix is "
        "different from supplying a missing constant")

    # --- the axes are orthogonal -------------------------------------
    assert not hasattr(Resolution, "LITERATURE")
    assert not hasattr(Provenance, "VERIFIED")

    print("PHYSICS VALUE TYPES OK")
    print("  condition windows: INSIDE / OUTSIDE / UNSTATED")
    print("  combination: VERIFIED / UNVERIFIED / PARTIAL / UNKNOWN / UNSUPPORTED")
    print("  Resolution and Provenance are separate axes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_physics_values_mock.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tcad.physics.values'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Physics value types.

Two axes, deliberately not merged into one enum:

  Resolution  — how settled a resolution is
  Provenance  — where the number came from

They are orthogonal because LITERATURE + UNVERIFIED is a real and
important state: a cited constant used outside the conditions it was
measured at. A single enum cannot express it.

Nothing here imports a backend. These are plain data types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional


class Resolution(Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED_BY_MODEL = "UNSUPPORTED_BY_MODEL"


class Provenance(Enum):
    LITERATURE = "LITERATURE"
    BACKEND_DEFAULT = "BACKEND_DEFAULT"
    USER_SUPPLIED = "USER_SUPPLIED"
    DERIVED = "DERIVED"


class UnknownPolicy(Enum):
    """What is passed to the backend when no value exists.

    Every option is itself a physical claim — INERT asserts the material
    does not react — so whichever applies, the result still carries
    UNKNOWN and records which policy was used. Which policy each
    parameter uses is declared in the table, never chosen at call time.
    """

    OMIT = "OMIT"
    BACKEND_DEFAULT = "BACKEND_DEFAULT"
    INERT = "INERT"


class Coverage(Enum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    UNSTATED = "UNSTATED"


@dataclass(frozen=True)
class Range:
    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class Conditions:
    """The window a value was measured in.

    A single number is not an absolute material property: the same
    chemistry gives different rates at different pressure, power,
    temperature and gas ratio. A value used outside its window is
    downgraded to UNVERIFIED for that use.
    """

    temperature_c: Optional[Range] = None
    pressure_pa: Optional[Range] = None
    rf_power_w: Optional[Range] = None
    gas_ratio: Optional[Mapping[str, Range]] = None
    notes: str = ""

    _SCALARS = ("temperature_c", "pressure_pa", "rf_power_w")

    def covers(self, requested: Mapping[str, float]) -> Coverage:
        """INSIDE only if every constrained condition is satisfied.

        A source that states no conditions at all yields UNSTATED and is
        never promoted to INSIDE — "we do not know where this applies"
        is not the same as "it applies everywhere".
        """
        constrained = [name for name in self._SCALARS
                       if getattr(self, name) is not None]
        if not constrained and not self.gas_ratio:
            return Coverage.UNSTATED

        for name in constrained:
            if name in requested and not getattr(self, name).contains(requested[name]):
                return Coverage.OUTSIDE

        for gas, window in (self.gas_ratio or {}).items():
            key = f"gas_ratio.{gas}"
            if key in requested and not window.contains(requested[key]):
                return Coverage.OUTSIDE

        return Coverage.INSIDE


@dataclass(frozen=True)
class Source:
    reference: str
    kind: Provenance


@dataclass(frozen=True)
class PhysicalValue:
    value: Optional[float]        # None means UNKNOWN
    unit: str
    material: str
    chemistry: Optional[str]
    conditions: Conditions
    source: Optional[Source]
    resolution: Resolution
    provenance: Provenance


def combine(resolutions: Iterable[Resolution]) -> Resolution:
    """Fold many lookups into one status for the step.

    UNDER_RESOLVED is deliberately absent: it is a numerical warning
    from WaferState, travels on its own axis, and is never merged here.
    """
    items = list(resolutions)
    if not items:
        return Resolution.UNKNOWN
    if Resolution.UNSUPPORTED_BY_MODEL in items:
        return Resolution.UNSUPPORTED_BY_MODEL
    if all(r is Resolution.UNKNOWN for r in items):
        return Resolution.UNKNOWN
    if Resolution.UNVERIFIED in items or Resolution.PARTIAL in items:
        return Resolution.UNVERIFIED
    if Resolution.UNKNOWN in items:
        return Resolution.PARTIAL
    return Resolution.VERIFIED
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_physics_values_mock.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/values.py tests/unit/test_physics_values_mock.py
git commit -m "feat: physics value types with separate Resolution and Provenance axes

LITERATURE + UNVERIFIED (a cited constant used outside its measured
conditions) cannot be expressed on a single enum, so status and origin
are kept orthogonal. Conditions are windows, not points."
```

---

### Task 4: WaferState

**Files:**
- Create: `tcad/physics/wafer_state.py`
- Test: covered by Task 5 (needs a real domain)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `LayerInfo(material: str, index: int)`
  - `WaferState.query(domain) -> WaferState`
  - `WaferState.materials -> tuple[str, ...]`
  - `WaferState.exposed_material_at(x: float) -> str | None`
  - `WaferState.exposed_materials() -> frozenset[str]`
  - `WaferState.under_resolved_x() -> tuple[float, ...]`

- [ ] **Step 1: Write the implementation**

This task's test is Task 5 (it needs real ViennaPS geometry), so the
implementation comes first here.

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The wafer as it actually is, queried from the live ViennaPS domain.

A QUERY, not a stored object. Recomputed at each process step from the
domain that step is about to process. Never cached as an independent
source of truth — the domain is mutated in place (measured: a step's
`last_domain` and the next step's `_inherited_domain` are the same
object), so a WaferState held across steps would describe geometry that
has since changed underneath it.

Exposed material is read from a VOXEL mesh, not from surface meshes plus
a tolerance. Every voxel carries a 'Material' scalar holding the
level-set index, and voxels tile space, so there is no x-sampling window
and no layer-thickness threshold: a zero-thickness layer simply has no
voxels. The only discretization parameter left is the grid the user
already chose.

Verified against an independent ground truth (topmost material in the
exported volume mesh) on bare Si, Si/SiO2, Si/SiO2/Si3N4, a patterned
resist wafer, an etched-through wafer, LOCOS, a 5-material gate stack,
and a wafer with different materials exposed along x. All agree at grid
0.02um. At grid 0.1um the two cases whose layer was thinner than one
cell disagree — which is what under_resolved_x() reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class LayerInfo:
    material: str
    index: int          # level-set index, innermost first


@dataclass(frozen=True)
class _Cell:
    x_min: float
    x_max: float
    y_max: float
    material: str


@dataclass(frozen=True)
class WaferState:
    materials: Tuple[str, ...]
    stack: Tuple[LayerInfo, ...]
    grid_delta_um: float
    _cells: Tuple[_Cell, ...]
    _thin_x: Tuple[float, ...]

    @staticmethod
    def query(domain: Any) -> "WaferState":
        import viennals as vls

        material_map = domain.getMaterialMap()
        names = tuple(
            str(material_map.getMaterialAtIdx(i)).split("'")[1]
            for i in range(material_map.size())
        )
        stack = tuple(LayerInfo(material=n, index=i) for i, n in enumerate(names))
        grid = domain.getGridDelta()

        mesh = vls.Mesh()
        converter = vls.ToVoxelMesh(mesh)
        for level_set in domain.getLevelSets():
            converter.insertNextLevelSet(level_set)
        converter.apply()

        nodes = mesh.getNodes()
        elements = mesh.getHexas() or mesh.getTetras() or mesh.getTriangles()
        cell_data = mesh.getCellData()
        labels = [cell_data.getScalarDataLabel(i)
                  for i in range(cell_data.getScalarDataSize())]
        tags = cell_data.getScalarData(labels.index("Material"))

        cells = []
        for element, tag in zip(elements, tags):
            points = [nodes[i] for i in element]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            index = int(round(tag))
            cells.append(_Cell(
                x_min=min(xs), x_max=max(xs), y_max=max(ys),
                material=names[index] if 0 <= index < len(names) else f"?{index}",
            ))

        return WaferState(
            materials=names,
            stack=stack,
            grid_delta_um=grid,
            _cells=tuple(cells),
            _thin_x=WaferState._thin_layer_positions(domain, grid),
        )

    @staticmethod
    def _thin_layer_positions(domain: Any, grid: float) -> Tuple[float, ...]:
        """x positions where some layer is thinner than one grid cell.

        A numerical diagnostic, NOT missing physics. Below one cell the
        level set cannot resolve the interface — the same limit
        thermal.py already respects by flooring its seed oxide at
        gridDelta — so the voxel answer at those x cannot be trusted.
        """
        import viennals as vls

        tops = []
        for level_set in domain.getLevelSets():
            mesh = vls.Mesh()
            vls.ToSurfaceMesh(level_set, mesh).apply()
            heights = {}
            for nx, ny, _ in mesh.getNodes():
                key = round(nx / grid)
                heights[key] = max(heights.get(key, ny), ny)
            tops.append(heights)

        thin = []
        for key in set().union(*(set(t) for t in tops)) if tops else ():
            heights = [t.get(key) for t in tops]
            for lower, upper in zip(heights, heights[1:]):
                if lower is None or upper is None:
                    continue
                if 0.0 < (upper - lower) < grid:
                    thin.append(key * grid)
                    break
        return tuple(sorted(thin))

    def exposed_material_at(self, x: float) -> Optional[str]:
        """The material at the surface at x. No tolerance involved."""
        best: Optional[_Cell] = None
        for cell in self._cells:
            if cell.x_min <= x <= cell.x_max:
                if best is None or cell.y_max > best.y_max:
                    best = cell
        return best.material if best is not None else None

    def exposed_materials(self) -> frozenset:
        """Materials spatially present at the surface RIGHT NOW.

        Different from `materials`: a fully-etched layer keeps a
        zero-thickness level set and stays declared, but nothing is
        exposed of it. Physical results must come from THIS set — acting
        on `materials` would compute physics for material that is no
        longer there. `materials` is for backend model registration,
        where an unregistered material makes the model fail.
        """
        surface = {}
        for cell in self._cells:
            key = cell.x_min
            if key not in surface or cell.y_max > surface[key].y_max:
                surface[key] = cell
        return frozenset(cell.material for cell in surface.values())

    def under_resolved_x(self) -> Tuple[float, ...]:
        return self._thin_x
```

- [ ] **Step 2: Verify it imports**

Run: `PYTHONIOENCODING=utf-8 python -c "from tcad.physics.wafer_state import WaferState; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add tcad/physics/wafer_state.py
git commit -m "feat: WaferState queried from the live domain

Voxel-based exposed-material lookup: cells tile space and carry the
level-set index, so no x-sampling window and no thickness threshold are
needed. under_resolved_x() reports where a layer is thinner than one
grid cell, as a numerical diagnostic separate from physics status."
```

---

### Task 5: WaferState verification on eight geometries

**Files:**
- Test: `tests/integration/test_wafer_state_real.py` (create)

**Interfaces:**
- Consumes: `WaferState.query`, `exposed_material_at`, `materials`, `exposed_materials`

- [ ] **Step 1: Write the test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState against real ViennaPS geometry, checked against the mesh.

Ground truth is read independently, from the topmost material in the
EXPORTED volume mesh, so agreement means two different data paths agree
rather than one path agreeing with itself.

Grid is 0.02um because two of these stacks contain layers thinner than
0.1um; at 0.1 those layers are sub-grid and under_resolved_x() reports
them (checked separately below).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
import tcad.process.geometry  # noqa: F401
from tcad.process import registry
from tcad.physics.wafer_state import WaferState

GRID = 0.02
BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=GRID,
            x_extent_um=10.0, y_extent_um=8.0)
XS = (-4.0, -2.0, -1.0, 0.0, 1.0, 2.0, 4.0)


def _topmost_in_mesh(mesh_path, x, half_window):
    import viennaps as vps

    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        value = getattr(vps.Material, attr)
        if isinstance(value, vps.Material):
            names.setdefault(int(value), attr)

    mesh = meshio.read(mesh_path)
    points = mesh.points
    best = None
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            values = np.asarray(values).ravel()
            for cell, tag in zip(cells.data, values):
                corners = points[cell]
                if (corners[:, 0].min() - half_window <= x
                        <= corners[:, 0].max() + half_window):
                    top = corners[:, 1].max()
                    if best is None or top > best[0]:
                        best = (top, names.get(int(tag), str(int(tag))))
    return best[1] if best else None


def _chain(specs):
    domain, mesh = None, None
    for category, model, recipe in specs:
        step = registry.get(category, model)(inherited_domain=domain)
        result = step.run(recipe, tempfile.mkdtemp(prefix="ws_"))
        domain, mesh = step.last_domain, result.get("final_mesh")
    return domain, mesh


def _oxidation(hours=0.5, **extra):
    return ("oxidation", "thermal",
            {**BASE, "oxidant": "Dry", "temperature_c": 1000.0,
             "time_hours": hours, **extra})


def _deposition(material, seconds=0.5, **extra):
    return ("deposition", "isotropic",
            {**BASE, "rate": 0.1, "deposition_time_s": seconds,
             "material": material, **extra})


def _bare_wafer():
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    domain = session.make_mask_spans(
        grid_delta_um=GRID, x_extent_um=10.0, y_extent_um=8.0,
        spans_um=[], mask_height_um=0.1, substrate_depth_um=6.0,
    )
    mesh = save_volume_mesh(domain, tempfile.mkdtemp(prefix="ws_") + "/bare",
                            floor_depth_um=5.0)
    return domain, mesh


CASES = {
    "bare Si": None,
    "Si/SiO2": [_oxidation(mask_spans_um=[])],
    "Si/SiO2/Si3N4": [_oxidation(mask_spans_um=[]), _deposition("Si3N4")],
    "patterned resist": [
        _oxidation(mask_spans_um=[]),
        _deposition("Si3N4", 0.3, remask_spans_um=[[-5.0, -1.5], [1.5, 5.0]],
                    mask_material="Mask"),
    ],
    "etched through": [
        _oxidation(mask_spans_um=[]),
        ("etching", "isotropic",
         {**BASE, "remask_spans_um": [[-5.0, -1.5], [1.5, 5.0]],
          "mask_material": "Mask",
          "material_rates": {"SiO2": -0.2, "Si": 0.0, "Mask": 0.0},
          "default_rate": 0.0, "etch_time_s": 0.5}),
    ],
    "LOCOS": [
        ("oxidation", "thermal",
         {**BASE, "mask_left_um": 3.5, "mask_right_um": 6.5,
          "mask_spans_um": [[-5.0, -1.5], [1.5, 5.0]], "mask_material": "Mask",
          "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5}),
    ],
    "gate stack": [
        ("geometry", "gate_stack",
         {"grid_delta_um": GRID, "x_extent_um": 10.0, "y_extent_um": 8.0,
          "silicon_depth_um": 2.0, "channel_um": (-1.0, 1.0),
          "source_um": (-4.0, -1.5), "drain_um": (1.5, 4.0),
          "gate_oxide_thickness_um": 0.05, "gate_height_um": 0.5,
          "pad_height_um": 0.4}),
    ],
    "mixed exposure": [
        _deposition("W", 0.4, mask_spans_um=[]),
        ("etching", "isotropic",
         {**BASE, "remask_spans_um": [[-5.0, -1.5], [1.5, 5.0]],
          "mask_material": "Mask",
          "material_rates": {"W": -0.3, "Si": 0.0, "Mask": 0.0},
          "default_rate": 0.0, "etch_time_s": 0.5}),
    ],
}


def test_exposed_material_matches_the_mesh():
    print("\n[A] exposed_material_at() vs the exported mesh, 8 geometries")
    for label, specs in CASES.items():
        domain, mesh = _bare_wafer() if specs is None else _chain(specs)
        state = WaferState.query(domain)
        for x in XS:
            got = state.exposed_material_at(x)
            want = _topmost_in_mesh(mesh, x, GRID)
            assert got == want, (
                f"{label}: at x={x} WaferState says {got!r} but the mesh's "
                f"topmost material is {want!r}")
        print(f"    {label:18s} stack={list(state.materials)} — all x agree")


def test_exposed_is_not_the_same_as_declared():
    print("\n[B] a fully etched layer stays declared but stops being exposed")
    domain, _ = _chain(CASES["mixed exposure"])
    state = WaferState.query(domain)
    assert "W" in state.materials, (
        "the etched-away layer should still be declared in the domain")
    assert "W" not in state.exposed_materials(), (
        "a layer removed by etching must not count as exposed — physics "
        "would then be computed for material that is no longer there")
    print(f"    declared={sorted(state.materials)} "
          f"exposed={sorted(state.exposed_materials())}")


def test_under_resolved_is_reported():
    print("\n[C] a layer thinner than one grid cell is reported, not hidden")
    coarse = dict(BASE, grid_delta_um=0.1)
    steps = [
        ("oxidation", "thermal",
         {**coarse, "mask_spans_um": [], "oxidant": "Dry",
          "temperature_c": 1000.0, "time_hours": 0.5}),
        ("etching", "isotropic",
         {**coarse, "remask_spans_um": [[-5.0, -1.5], [1.5, 5.0]],
          "mask_material": "Mask",
          "material_rates": {"SiO2": -0.2, "Si": 0.0, "Mask": 0.0},
          "default_rate": 0.0, "etch_time_s": 0.5}),
    ]
    domain, _ = _chain(steps)
    state = WaferState.query(domain)
    thin = state.under_resolved_x()
    assert thin, (
        "the residual oxide in the window is a fraction of a grid cell, so "
        "at least one x must be reported under-resolved")
    assert any(abs(x) < 1.5 for x in thin), (
        f"the under-resolved x should be inside the etched window: {thin[:8]}")
    print(f"    {len(thin)} under-resolved x positions, e.g. {thin[:5]}")


def main():
    test_exposed_material_matches_the_mesh()
    test_exposed_is_not_the_same_as_declared()
    test_under_resolved_is_reported()
    print()
    print("WAFERSTATE VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_wafer_state_real.py`
Expected: PASS on all three checks. If `[C]` fails, `_thin_layer_positions` is wrong — do **not** loosen the assertion; fix the diagnostic.

- [ ] **Step 3: Run the full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 3 more passes than baseline, still exactly the 3 pre-existing DevSim failures.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_wafer_state_real.py
git commit -m "test: WaferState against real geometry on eight stacks

Ground truth read independently from the exported mesh. Also pins that
a fully etched layer stays declared but stops being exposed, and that a
sub-grid layer is reported rather than silently mis-answered."
```

---

## Stage 1 — status plumbing, no result change

### Task 6: Carry physics and numerical status to the GUI

Proves the propagation path end to end **before** any physics depends on it.

**Files:**
- Modify: `tcad/mesh/interface.py` (`ProcessResult`)
- Modify: `tcad/mesh/viennaps_adapter.py` (`build_process_result`)
- Modify: `tcad_2d_stagewise.py` (`worker_main` flow branch payload; `_run_single_step` and the three `run_*` success paths; `_log`)
- Test: `tests/integration/test_status_propagation_real.py` (create)

**Interfaces:**
- Consumes: `Resolution` from Task 3
- Produces:
  - `ProcessResult.physics_status: dict | None`
  - `ProcessResult.numerical_status: dict | None`
  - worker payload keys `"physics_status"`, `"numerical_status"`
  - `TCADApplication.last_physics_status`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Status must survive the worker's JSON boundary.

Physics status and the numerical (under-resolved) warning travel on
separate axes and must both reach the GUI. This is proven while
everything still reports empty/UNKNOWN, so the path is trusted before
any physics depends on it.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad_2d_stagewise as gui


def main():
    output = tempfile.mkdtemp(prefix="status_")
    config = {
        "_flow_steps": [{
            "_process_category": "deposition", "_process_model_key": "isotropic",
            "mask_spans_um": [], "pr_thickness_um": 1.0, "silicon_depth_um": 5.0,
            "grid_delta_um": 0.05, "x_extent_um": 10.0, "y_extent_um": 8.0,
            "rate": 0.05, "deposition_time_s": 0.3, "material": "SiO2",
        }],
        "output_dir": output,
    }
    config_file = os.path.join(output, "recipe.json")
    result_file = os.path.join(output, "result.json")
    Path(config_file).write_text(json.dumps(config), encoding="utf-8")

    gui.worker_main(config_file, result_file)
    result = json.loads(Path(result_file).read_text(encoding="utf-8"))
    assert result.get("success"), result.get("error")

    assert "physics_status" in result, (
        "physics status did not cross the worker's JSON boundary")
    assert "numerical_status" in result, (
        "the numerical warning must travel on its own key, not merged into "
        "physics status")

    # Whatever they hold must be JSON data, not live objects.
    json.dumps(result["physics_status"])
    json.dumps(result["numerical_status"])

    print("STATUS PROPAGATION OK")
    print(f"  physics_status   = {result['physics_status']}")
    print(f"  numerical_status = {result['numerical_status']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_status_propagation_real.py`
Expected: FAIL with `AssertionError: physics status did not cross the worker's JSON boundary`

- [ ] **Step 3: Add the fields**

In `tcad/mesh/interface.py`, add to `ProcessResult` (additive, defaulting
to `None`, exactly as `domain_state_path` and `structure` were added):

```python
    physics_status: Optional[dict] = None
    numerical_status: Optional[dict] = None
```

In `tcad/mesh/viennaps_adapter.py`, change `build_process_result` to
forward them from the step result:

```python
        physics_status=step_result.get("physics_status"),
        numerical_status=step_result.get("numerical_status"),
```

In `tcad_2d_stagewise.py`'s `worker_main`, in the `_flow_steps` branch,
add to `payload`:

```python
                # Physics status and the numerical (under-resolved)
                # warning are separate axes and stay separate all the
                # way to the GUI. Plain JSON only: this crosses a
                # subprocess boundary.
                "physics_status": results[-1].physics_status,
                "numerical_status": results[-1].numerical_status,
```

In each success path that already sets `self.last_domain_state` (the
three `run_*` methods and `_run_single_step`), add:

```python
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
```

and add the reporter plus its initialiser:

```python
    def _log_physics_status(self, result):
        """Report what the physics did and did not know.

        Never blocks and never hides: an UNKNOWN result still ran, and
        the log says which parameter was unknown and what was passed
        instead.
        """
        physics = result.get("physics_status")
        if physics:
            self._log(f"\nPHYSICS: {physics.get('resolution', 'UNKNOWN')}\n")
            for entry in physics.get("entries", []):
                self._log(
                    f"  {entry.get('parameter')} [{entry.get('material')}]: "
                    f"{entry.get('resolution')} / {entry.get('provenance')}"
                    f" — {entry.get('note', '')}\n"
                )
        numerical = result.get("numerical_status")
        if numerical and numerical.get("under_resolved_x"):
            count = len(numerical["under_resolved_x"])
            self._log(
                f"\nNUMERICAL: {count} x positions carry a layer thinner than "
                f"one grid cell; the geometry there is under-resolved. "
                f"Reduce grid delta to resolve it.\n"
            )
```

In `__init__` and `reset`, add `self.last_physics_status = None`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_status_propagation_real.py`
Expected: PASS, both values printing as `None` (nothing produces status yet).

- [ ] **Step 5: Run the full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: one more pass than after Task 5, same 3 pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add tcad/mesh/interface.py tcad/mesh/viennaps_adapter.py tcad_2d_stagewise.py tests/integration/test_status_propagation_real.py
git commit -m "feat: carry physics and numerical status to the GUI

Both axes plumbed end to end while still empty, so the path is proven
before any physics depends on it. Numerical (under-resolved) status
travels on its own key and is never merged into physics status."
```

---

## Stage 2 — resolver on the real path, table empty, no result change

### Task 7: ProcessIntent and the empty tables

**Files:**
- Create: `tcad/physics/intent.py`
- Create: `tcad/physics/tables.py`
- Test: `tests/unit/test_physics_tables_mock.py`

**Interfaces:**
- Consumes: `Conditions`, `PhysicalValue`, `Provenance`, `Resolution`, `UnknownPolicy` from Task 3
- Produces:
  - `ProcessIntent(category, method, chemistry, target_material, parameters)`
  - `intent_from(recipe: Mapping) -> ProcessIntent`
  - `material_property(material: str, name: str) -> PhysicalValue | None`
  - `interaction(material: str, chemistry: str, parameter: str, requested: Mapping) -> PhysicalValue`
  - `policy_for(parameter: str) -> UnknownPolicy`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The physics tables ship empty, and say so honestly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.intent import ProcessIntent, intent_from
from tcad.physics.tables import interaction, material_property, policy_for
from tcad.physics.values import Provenance, Resolution, UnknownPolicy


def main():
    # --- intent carries no per-material rates ------------------------
    intent = intent_from({
        "_process_category": "etching", "_process_model_key": "isotropic",
        "chemistry": "SF6O2", "rate": -0.2, "etch_time_s": 1.0,
    })
    assert isinstance(intent, ProcessIntent)
    assert intent.category == "etching"
    assert intent.method == "isotropic"
    assert intent.chemistry == "SF6O2"
    assert "material_rates" not in intent.parameters, (
        "ProcessIntent must not carry per-material rates — those are the "
        "resolver's job, derived from the wafer state")

    # --- unknown combinations stay unknown ---------------------------
    value = interaction("W", "SF6O2", "etch_rate", {"temperature_c": 25.0})
    assert value.value is None, "no constant may be invented for an unknown pair"
    assert value.resolution is Resolution.UNKNOWN
    assert value.source is None

    # --- every parameter declares its policy in advance --------------
    assert isinstance(policy_for("etch_rate"), UnknownPolicy)

    # --- a material property that is genuinely known -----------------
    oxidizable = material_property("Si", "oxidizable")
    assert oxidizable is not None and oxidizable.value == 1.0
    assert oxidizable.provenance is Provenance.LITERATURE

    assert material_property("W", "oxidizable") is None or \
        material_property("W", "oxidizable").resolution is Resolution.UNKNOWN

    print("PHYSICS TABLES OK — empty of interaction constants, honest about it")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_physics_tables_mock.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tcad.physics.intent'`

- [ ] **Step 3: Write `intent.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the user asked for — a request, not a result.

Deliberately carries no per-material rates. A user says "SF6/O2 for
30 s", not "SiO2 at 0.02 um/s"; turning the first into the second is the
resolver's job and depends on what is actually on the wafer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

#: Recipe keys that describe geometry or bookkeeping rather than the
#: physical request.
_NON_PHYSICAL_KEYS = frozenset({
    "_process_category", "_process_model_key", "chemistry", "material",
    "material_rates", "mask_spans_um", "remask_spans_um", "mask_left_um",
    "mask_right_um",
})


@dataclass(frozen=True)
class ProcessIntent:
    category: str
    method: str
    chemistry: Optional[str] = None
    target_material: Optional[str] = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


def intent_from(recipe: Mapping[str, Any]) -> ProcessIntent:
    return ProcessIntent(
        category=recipe.get("_process_category", ""),
        method=recipe.get("_process_model_key", ""),
        chemistry=recipe.get("chemistry"),
        target_material=recipe.get("material"),
        parameters={k: v for k, v in recipe.items()
                    if k not in _NON_PHYSICAL_KEYS},
    )
```

- [ ] **Step 4: Write `tables.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Material properties and interaction coefficients.

TWO tables, because the values differ in kind. `rho` is a property of a
material; `k_sigma` depends on the chemistry AND the conditions. Merging
them would make condition-dependent coefficients look like material
properties.

INTERACTION_COEFFICIENTS SHIPS EMPTY. Filling it is a separate research
step where each entry arrives with a citation and the conditions it was
measured at. Nothing here may be filled with an estimate, and a ViennaPS
default is never promoted to VERIFIED — it is the library author's
choice, which is not a guarantee for this material at these conditions.

A side effect worth having: with the table empty, the UNKNOWN path is
the most-exercised path rather than a rare branch.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from tcad.physics.values import (
    Conditions, Coverage, PhysicalValue, Provenance, Resolution, Source,
    UnknownPolicy,
)

_NO_CONDITIONS = Conditions(notes="not applicable — intrinsic property")

#: Intrinsic, condition-free. Only entries with an unambiguous basis.
MATERIAL_PROPERTIES: Dict[Tuple[str, str], PhysicalValue] = {
    ("Si", "oxidizable"): PhysicalValue(
        value=1.0, unit="bool", material="Si", chemistry=None,
        conditions=_NO_CONDITIONS,
        source=Source("thermal oxidation forms SiO2 from Si", Provenance.LITERATURE),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
    ("SiO2", "oxidizable"): PhysicalValue(
        value=0.0, unit="bool", material="SiO2", chemistry=None,
        conditions=_NO_CONDITIONS,
        source=Source("SiO2 is the oxide; it is not further oxidised",
                      Provenance.LITERATURE),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
}

#: (material, chemistry, parameter) -> PhysicalValue.
#: EMPTY ON PURPOSE. See the module docstring.
INTERACTION_COEFFICIENTS: Dict[Tuple[str, str, str], PhysicalValue] = {}

#: What is passed to the backend when a value is unknown. Declared per
#: parameter here, never decided at call time. Each option is itself a
#: physical claim, so the result carries UNKNOWN regardless.
_UNKNOWN_POLICIES: Dict[str, UnknownPolicy] = {
    "etch_rate": UnknownPolicy.OMIT,
    "deposition_rate": UnknownPolicy.OMIT,
}
_DEFAULT_POLICY = UnknownPolicy.OMIT


def policy_for(parameter: str) -> UnknownPolicy:
    return _UNKNOWN_POLICIES.get(parameter, _DEFAULT_POLICY)


def material_property(material: str, name: str) -> Optional[PhysicalValue]:
    return MATERIAL_PROPERTIES.get((material, name))


def interaction(material: str, chemistry: str, parameter: str,
                requested: Mapping[str, Any]) -> PhysicalValue:
    """Look up a coefficient, downgrading it if used outside its window.

    A cited value applied outside the conditions it was measured at is
    UNVERIFIED for that use, and a source that states no conditions is
    never promoted to VERIFIED. This is what stops a single number being
    treated as an absolute material property.
    """
    found = INTERACTION_COEFFICIENTS.get((material, chemistry, parameter))
    if found is None:
        return PhysicalValue(
            value=None, unit="", material=material, chemistry=chemistry,
            conditions=_NO_CONDITIONS, source=None,
            resolution=Resolution.UNKNOWN, provenance=Provenance.DERIVED,
        )

    coverage = found.conditions.covers(requested)
    if coverage is Coverage.INSIDE and found.provenance is Provenance.LITERATURE:
        return found
    return PhysicalValue(
        value=found.value, unit=found.unit, material=found.material,
        chemistry=found.chemistry, conditions=found.conditions,
        source=found.source, resolution=Resolution.UNVERIFIED,
        provenance=found.provenance,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_physics_tables_mock.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tcad/physics/intent.py tcad/physics/tables.py tests/unit/test_physics_tables_mock.py
git commit -m "feat: ProcessIntent and the (empty) physics tables

Two tables so condition-dependent coefficients cannot masquerade as
material properties. Interaction constants ship empty; filling them is a
separate research step with citations and conditions."
```

---

### Task 8: The resolver

**Files:**
- Create: `tcad/physics/resolve.py`
- Test: `tests/unit/test_resolver_mock.py`

**Interfaces:**
- Consumes: `ProcessIntent`, `WaferState`, `interaction`, `policy_for`, `combine`
- Produces:
  - `ResolvedValue(parameter, material, value, resolution, provenance, note)`
  - `ResolvedRecipe(backend_kwargs, resolution, entries, under_resolved_x, notes)`
  - `resolve(intent, state, user_supplied=None) -> ResolvedRecipe`
  - `ResolvedRecipe.as_status_dict() -> dict` / `as_numerical_dict() -> dict`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The resolver: pure, history-free, honest about what it does not know."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.intent import ProcessIntent
from tcad.physics.resolve import resolve
from tcad.physics.values import Provenance, Resolution


class _FakeState:
    """Only what the resolver reads — no ViennaPS needed."""

    def __init__(self, exposed, declared=None, thin=()):
        self._exposed = frozenset(exposed)
        self.materials = tuple(declared or exposed)
        self._thin = tuple(thin)

    def exposed_materials(self):
        return self._exposed

    def under_resolved_x(self):
        return self._thin


def test_no_history_channel():
    """T1: order cannot influence a function that cannot see it."""
    parameters = list(inspect.signature(resolve).parameters)
    assert parameters[:2] == ["intent", "state"], parameters
    forbidden = {"history", "previous", "previous_step", "completed_steps",
                 "process_stage", "last_step"}
    assert not forbidden.intersection(parameters), (
        f"resolve() gained a history channel: {parameters}")
    print("[T1] resolve(intent, state) has no history parameter")


def test_unknown_still_resolves():
    """An empty table must not stop the step from running."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si", "SiO2"}))
    assert resolved.resolution is Resolution.UNKNOWN
    assert resolved.entries, "the resolver must say WHICH lookups were unknown"
    assert {e.material for e in resolved.entries} == {"Si", "SiO2"}
    print(f"[unknown] {resolved.resolution.value}, "
          f"{len(resolved.entries)} entries recorded")


def test_user_supplied_is_its_own_provenance():
    """A caller-specified rate is honoured, and labelled as unverified."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si", "SiO2"}),
                       user_supplied={"material_rates": {"Si": -0.3}})
    assert resolved.backend_kwargs["materialRates"]["Si"] == -0.3
    supplied = [e for e in resolved.entries if e.material == "Si"][0]
    assert supplied.provenance is Provenance.USER_SUPPLIED
    assert supplied.resolution is Resolution.UNVERIFIED, (
        "USER_SUPPLIED means this project has not verified the value, not "
        "that the value is wrong")
    print("[compat] caller rates honoured as USER_SUPPLIED / UNVERIFIED")


def test_same_state_same_result():
    """T2: identical (state, intent) must resolve identically."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    first = resolve(intent, _FakeState({"Si", "SiO2"}))
    second = resolve(intent, _FakeState({"SiO2", "Si"}))
    assert first.backend_kwargs == second.backend_kwargs
    assert first.resolution is second.resolution
    print("[T2] same exposed materials + same intent -> same resolution")


def test_numerical_axis_stays_separate():
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si"}, thin=(0.0, 0.1)))
    assert resolved.under_resolved_x == (0.0, 0.1)
    assert "UNDER_RESOLVED" not in resolved.resolution.value, (
        "the numerical warning must not be folded into physics status")
    print("[axes] under_resolved_x carried separately from resolution")


def main():
    test_no_history_channel()
    test_unknown_still_resolves()
    test_user_supplied_is_its_own_provenance()
    test_same_state_same_result()
    test_numerical_axis_stays_separate()
    print()
    print("RESOLVER OK — pure, history-free, UNKNOWN-safe")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_resolver_mock.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tcad.physics.resolve'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn "what the user asked for" plus "what the wafer is" into a recipe.

PURE. Stateless. Does not touch the domain, does not run a process, does
not write files.

There is NO history parameter, and that is the design's central
guarantee: order cannot influence the result because no channel exists
to carry it. Two different orders may still produce different results —
often they must — but only because the wafer state differs when the
second process runs, never because anything here asked what ran before.

Physical decisions read `state.exposed_materials()`, never
`state.materials`: a fully etched layer keeps a zero-thickness level set
and stays declared, and computing physics for it would be computing for
material that is no longer there. `state.materials` is for backend model
registration, where an unregistered material makes the model fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from tcad.physics.intent import ProcessIntent
from tcad.physics.tables import interaction, policy_for
from tcad.physics.values import (
    Provenance, Resolution, UnknownPolicy, combine,
)

#: Which coefficient each category needs per exposed material.
_PARAMETER_FOR_CATEGORY = {
    "etching": "etch_rate",
    "deposition": "deposition_rate",
}


@dataclass(frozen=True)
class ResolvedValue:
    parameter: str
    material: str
    value: Optional[float]
    resolution: Resolution
    provenance: Provenance
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "material": self.material,
            "value": self.value,
            "resolution": self.resolution.value,
            "provenance": self.provenance.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class ResolvedRecipe:
    backend_kwargs: Mapping[str, Any] = field(default_factory=dict)
    resolution: Resolution = Resolution.UNKNOWN
    entries: Tuple[ResolvedValue, ...] = ()
    under_resolved_x: Tuple[float, ...] = ()
    notes: Tuple[str, ...] = ()

    def as_status_dict(self) -> dict:
        return {
            "resolution": self.resolution.value,
            "entries": [e.as_dict() for e in self.entries],
            "notes": list(self.notes),
        }

    def as_numerical_dict(self) -> dict:
        return {"under_resolved_x": list(self.under_resolved_x)}


def resolve(intent: ProcessIntent, state: Any,
            user_supplied: Optional[Mapping[str, Any]] = None) -> ResolvedRecipe:
    parameter = _PARAMETER_FOR_CATEGORY.get(intent.category)
    if parameter is None:
        # Nothing to resolve for this category yet. Not a refusal: the
        # step runs on whatever the recipe already carries.
        return ResolvedRecipe(
            resolution=Resolution.UNKNOWN,
            under_resolved_x=tuple(state.under_resolved_x()),
            notes=(f"no resolver mapping for category {intent.category!r}",),
        )

    supplied_rates = dict((user_supplied or {}).get("material_rates") or {})
    rates: dict = {}
    entries = []

    for material in sorted(state.exposed_materials()):
        if material in supplied_rates:
            rates[material] = supplied_rates[material]
            entries.append(ResolvedValue(
                parameter=parameter, material=material,
                value=supplied_rates[material],
                resolution=Resolution.UNVERIFIED,
                provenance=Provenance.USER_SUPPLIED,
                note="supplied by the caller; not verified by this project",
            ))
            continue

        found = interaction(material, intent.chemistry or "", parameter,
                            intent.parameters)
        if found.value is None:
            policy = policy_for(parameter)
            if policy is UnknownPolicy.INERT:
                rates[material] = 0.0
            entries.append(ResolvedValue(
                parameter=parameter, material=material, value=None,
                resolution=Resolution.UNKNOWN, provenance=found.provenance,
                note=f"no verified constant; policy {policy.value}",
            ))
            continue

        rates[material] = found.value
        entries.append(ResolvedValue(
            parameter=parameter, material=material, value=found.value,
            resolution=found.resolution, provenance=found.provenance,
            note=found.source.reference if found.source else "",
        ))

    backend_kwargs = {"materialRates": rates} if rates else {}
    return ResolvedRecipe(
        backend_kwargs=backend_kwargs,
        resolution=combine(e.resolution for e in entries),
        entries=tuple(entries),
        under_resolved_x=tuple(state.under_resolved_x()),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_resolver_mock.py`
Expected: PASS on all five checks

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/resolve.py tests/unit/test_resolver_mock.py
git commit -m "feat: pure history-free physics resolver

resolve(intent, state) has no history parameter, which is what makes
order-independence structural rather than a convention. Physics reads
exposed_materials(), never the declared material set."
```

---

### Task 9: Wire the resolver into the isotropic etch

**Files:**
- Modify: `tcad/process/etching/isotropic.py`
- Test: `tests/integration/test_resolver_wired_real.py` (create)

**Interfaces:**
- Consumes: `WaferState.query`, `resolve`, `intent_from`
- Produces: step results carrying `physics_status` / `numerical_status`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The resolver is on the real path, and changes nothing yet.

The table is empty, so resolution is UNKNOWN and the step must still
run. A recipe that specifies material_rates keeps working unchanged —
that is the migration bridge — and is reported as USER_SUPPLIED.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.process import registry

BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=0.05,
            x_extent_um=10.0, y_extent_um=8.0)


def test_unknown_still_runs():
    print("\n[A] empty table: UNKNOWN, and the step still runs")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [], "chemistry": "SF6O2",
                       "rate": -0.2, "etch_time_s": 0.3},
                      tempfile.mkdtemp(prefix="rw_"))
    assert Path(result["final_mesh"]).exists(), "the etch did not produce a mesh"
    status = result.get("physics_status")
    assert status is not None, "the step produced no physics status"
    assert status["resolution"] == "UNKNOWN"
    assert status["entries"], "the step must record WHICH lookups were unknown"
    print(f"    resolution={status['resolution']} "
          f"entries={[e['material'] for e in status['entries']]}")


def test_caller_rates_still_honoured():
    print("\n[B] a recipe that specifies rates keeps working")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [],
                       "material_rates": {"Si": -0.2}, "default_rate": 0.0,
                       "etch_time_s": 0.3},
                      tempfile.mkdtemp(prefix="rw_"))
    assert Path(result["final_mesh"]).exists()
    entries = result["physics_status"]["entries"]
    supplied = [e for e in entries if e["material"] == "Si"]
    assert supplied and supplied[0]["provenance"] == "USER_SUPPLIED", (
        f"caller-specified rate not reported as USER_SUPPLIED: {entries}")
    print(f"    Si reported as {supplied[0]['provenance']} / "
          f"{supplied[0]['resolution']}")


def main():
    test_unknown_still_runs()
    test_caller_rates_still_honoured()
    print()
    print("RESOLVER WIRED — UNKNOWN runs, caller rates still honoured")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_resolver_wired_real.py`
Expected: FAIL with `AssertionError: the step produced no physics status`

- [ ] **Step 3: Wire it in**

In `tcad/process/etching/isotropic.py`, immediately after
`geometry = self.prepare_domain(recipe)`:

```python
        # Queried AFTER prepare_domain(): a remask inserts the resist
        # level set, and the resist is part of the state physics must
        # see. Once per step — the domain is mutated in place, so a
        # state held any longer would describe geometry that has since
        # changed.
        from tcad.physics.intent import intent_from
        from tcad.physics.resolve import resolve
        from tcad.physics.wafer_state import WaferState

        state = WaferState.query(geometry)
        resolved = resolve(intent_from(recipe), state, user_supplied=recipe)
```

Keep the existing model construction exactly as it is — the table is
empty, so `resolved.backend_kwargs` adds nothing yet and behavior is
unchanged. Then attach the status to the returned dict:

```python
        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.paths,
            "physics_status": resolved.as_status_dict(),
            "numerical_status": resolved.as_numerical_dict(),
        }
```

(Adjust the existing return statement rather than adding a second one;
keep whatever keys it already returns.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_resolver_wired_real.py`
Expected: PASS

- [ ] **Step 5: Run the full regression — this is the critical gate**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: **no new failures.** Stage 2 must change no results. If an etch
test changed numbers, the resolver is overriding caller rates — fix the
resolver, do not update the test.

- [ ] **Step 6: Commit**

```bash
git add tcad/process/etching/isotropic.py tests/integration/test_resolver_wired_real.py
git commit -m "feat: wire the resolver into the isotropic etch

State is queried after prepare_domain so the resist is visible, once per
step. The table is empty so behaviour is unchanged; caller-specified
rates keep working and are reported as USER_SUPPLIED."
```

---

### Task 10: Permutation sweep (T4)

**Files:**
- Test: `tests/integration/test_order_independence_real.py` (create)

**Interfaces:**
- Consumes: `WaferState.query`, `resolve`, `intent_from`

- [ ] **Step 1: Write the test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Order independence, checked by fuzzing the order.

THE PERMUTATIONS BELOW ARE NOT A PROCESS-ORDER SPECIFICATION. They are a
generator used to find states that recur across different orders. No
permutation is a "normal" or "supported" order; the simulator imposes no
order at all.

What is asserted: whenever the same (exposed_materials, intent) pair
occurs — no matter which order produced it — the resolver returns the
same thing. A difference would mean history is leaking into physics.

Cost control: exhaustive for a small number of steps; for more, switch
to deterministic seeded sampling so failures reproduce.
"""

import itertools
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.physics.intent import intent_from
from tcad.physics.resolve import resolve
from tcad.physics.wafer_state import WaferState

BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=0.05,
            x_extent_um=6.0, y_extent_um=6.0)

#: Deliberately fast steps — a sweep runs many flows.
STEPS = [
    ("deposition", "isotropic",
     {**BASE, "rate": 0.1, "deposition_time_s": 0.2, "material": "SiO2"}),
    ("deposition", "isotropic",
     {**BASE, "rate": 0.1, "deposition_time_s": 0.2, "material": "Si3N4"}),
    ("etching", "isotropic",
     {**BASE, "chemistry": "SF6O2", "rate": -0.05, "etch_time_s": 0.2}),
]

SEED = 20260825
MAX_EXHAUSTIVE = 3


def _permutations(steps):
    if len(steps) <= MAX_EXHAUSTIVE:
        return list(itertools.permutations(range(len(steps))))
    rng = random.Random(SEED)
    orders = {tuple(range(len(steps)))}
    while len(orders) < 12:
        order = list(range(len(steps)))
        rng.shuffle(order)
        orders.add(tuple(order))
    return sorted(orders)


def main():
    observations = {}
    orders = _permutations(STEPS)
    print(f"sweeping {len(orders)} orders of {len(STEPS)} steps "
          f"(generator, not a spec)")

    for order in orders:
        domain = None
        for index in order:
            category, model, recipe = STEPS[index]
            first = domain is None
            step_recipe = dict(recipe)
            if first:
                step_recipe["mask_spans_um"] = []
            step = registry.get(category, model)(inherited_domain=domain)
            geometry = step.prepare_domain(step_recipe)

            state = WaferState.query(geometry)
            resolved = resolve(intent_from(step_recipe), state,
                               user_supplied=step_recipe)
            key = (frozenset(state.exposed_materials()), category, model,
                   step_recipe.get("chemistry"))
            fingerprint = (repr(sorted(resolved.backend_kwargs.items())),
                           resolved.resolution.value)
            if key in observations:
                assert observations[key] == fingerprint, (
                    f"same exposed materials {sorted(key[0])} and same intent "
                    f"({category}/{model}) resolved differently depending on "
                    f"the order taken to get there:\n"
                    f"  {observations[key]}\n  {fingerprint}")
            else:
                observations[key] = fingerprint

            step.run(step_recipe, tempfile.mkdtemp(prefix="perm_"))
            domain = step.last_domain

    print(f"{len(observations)} distinct (exposed_materials, intent) pairs seen")
    print()
    print("ORDER INDEPENDENCE HELD — equal state and intent resolved equally")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_order_independence_real.py`
Expected: PASS. A failure names the two differing resolutions — that is
history leaking, and the fix belongs in the resolver, never in the test.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_order_independence_real.py
git commit -m "test: order independence by permutation fuzzing

The permutations are a generator for finding recurring states, not a
supported-order list. Asserts that equal (exposed_materials, intent)
resolves equally regardless of the order that produced it."
```

---

## Stage 3 — first real physics

### Task 11: Independent physics references (T3a) and the transmission split (T3b)

**Files:**
- Test: `tests/integration/test_physics_references_real.py` (create)

**Interfaces:**
- Consumes: nothing new

- [ ] **Step 1: Write the test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent physical references, and a clearly-labelled fidelity check.

T3a — INDEPENDENT PHYSICS. These relations hold regardless of any
constant this project chooses, so they test physics rather than
bookkeeping:

  * Si consumed / oxide grown = 0.44, from the molar volumes of Si and
    SiO2. Not a rate constant. Measured 0.434 / 0.437 / 0.439 at
    0.5 / 1.0 / 2.0 hr — stable across time, the signature of a real
    constraint rather than a fitted value.
  * Time additivity: oxidising t then t again equals oxidising 2t once.
    A property of a time-invariant ODE, independent of any coefficient.
    Measured agreement 0.39%.

T3b — TRANSMISSION FIDELITY ONLY. THIS DOES NOT VERIFY THE RESOLVER'S
NUMERICAL CORRECTNESS. It verifies only that the number the resolver
produced is the number the backend applied.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry

GRID = 0.02
BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=GRID,
            x_extent_um=6.0, y_extent_um=6.0)
STOICHIOMETRIC_RATIO = 0.44     # molar volume ratio of Si to SiO2


def _tops(mesh_path):
    import viennaps as vps

    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        value = getattr(vps.Material, attr)
        if isinstance(value, vps.Material):
            names.setdefault(int(value), attr)

    mesh = meshio.read(mesh_path)
    points = mesh.points
    found = {}
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            values = np.asarray(values).ravel()
            for tag in set(values.tolist()):
                selected = cells.data[values == tag]
                if len(selected) == 0:
                    continue
                name = names.get(int(tag), str(int(tag)))
                top = float(points[np.unique(selected)][:, 1].max())
                found[name] = max(found.get(name, top), top)
    return found


def _oxidise(hours, domain=None):
    step = registry.get("oxidation", "thermal")(inherited_domain=domain)
    recipe = {**BASE, "oxidant": "Dry", "temperature_c": 1000.0,
              "time_hours": hours}
    if domain is None:
        recipe["mask_spans_um"] = []
    result = step.run(recipe, tempfile.mkdtemp(prefix="ref_"))
    tops = _tops(result["final_mesh"])
    return step.last_domain, tops["Si"], tops["SiO2"]


def test_t3a_stoichiometry():
    print("\n[T3a] Si consumed / oxide grown = 0.44 (molar volumes)")
    seed = max(0.002, GRID)     # thermal.py inserts, not grows, this seed
    for hours in (0.5, 1.0, 2.0):
        _, si_top, oxide_top = _oxidise(hours)
        grown = (oxide_top - si_top) - seed
        consumed = -si_top
        ratio = consumed / grown
        assert abs(ratio - STOICHIOMETRIC_RATIO) < 0.03, (
            f"t={hours}hr: consumed/grown={ratio:.3f}, expected "
            f"{STOICHIOMETRIC_RATIO} from the Si/SiO2 molar volume ratio")
        print(f"    t={hours}hr  consumed/grown = {ratio:.3f}")


def test_t3a_time_additivity():
    print("\n[T3a] oxidising t then t equals oxidising 2t once")
    domain, si_a, ox_a = _oxidise(0.5)
    _, si_chained, ox_chained = _oxidise(0.5, domain=domain)
    _, si_single, ox_single = _oxidise(1.0)
    chained = ox_chained - si_chained
    single = ox_single - si_single
    relative = abs(chained - single) / single
    assert relative < 0.05, (
        f"chained {chained:.4f} vs single {single:.4f} differ by "
        f"{relative*100:.1f}% — oxidation is not reading the existing oxide")
    print(f"    chained={chained:.4f} single={single:.4f} "
          f"diff={relative*100:.2f}%")


def test_t3b_transmission_only():
    """DOES NOT VERIFY PHYSICAL CORRECTNESS — transmission fidelity only."""
    print("\n[T3b] the rate the resolver produced is the rate applied")
    print("      (this check does NOT verify the rate is physically right)")
    step = registry.get("etching", "isotropic")()
    before = None
    result = step.run({**BASE, "mask_spans_um": [],
                       "material_rates": {"Si": 0.0}, "default_rate": 0.0,
                       "etch_time_s": 0.5},
                      tempfile.mkdtemp(prefix="ref_"))
    tops = _tops(result["final_mesh"])
    assert abs(tops["Si"]) < 0.5 * GRID, (
        f"a material given rate 0 moved to {tops['Si']:.4f} — the resolved "
        f"value is not the value the backend applied")
    print(f"    rate 0 -> Si surface at {tops['Si']:+.4f} (unmoved)")


def main():
    test_t3a_stoichiometry()
    test_t3a_time_additivity()
    test_t3b_transmission_only()
    print()
    print("PHYSICS REFERENCES OK — independent checks pass, fidelity labelled")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_physics_references_real.py`
Expected: PASS

- [ ] **Step 3: Run the full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: no new failures.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_physics_references_real.py
git commit -m "test: independent physics references and a labelled fidelity check

T3a asserts relations that hold regardless of our constants (Si/SiO2
molar volume ratio, oxidation time additivity). T3b states in the file
that it checks transmission only, so no test verifies its own numbers
against itself."
```

---

## Self-review

**Spec coverage.** §1 WaferState -> Tasks 4, 5. §2 ProcessIntent -> Task 7.
§3 Resolver -> Task 8. §4 schema -> Tasks 3, 7. §5 integration -> Task 9.
§6 propagation and tests -> Tasks 6, 8 (T1, T2), 10 (T4), 9 (T5), 11 (T3a/T3b).
§7 migration stages -> task ordering; §7.5 stale-state fixes -> Tasks 1, 2.

Not covered by design, deferred to their own steps: filling
`INTERACTION_COEFFICIENTS` (physics-data research), wiring the resolver
into oxidation/deposition/metallization/doping (stage 4+), mapping the
remaining registered models onto the four backend shapes.

**Placeholders.** None. Every code step carries the actual content.

**Type consistency.** `resolve(intent, state, user_supplied=None)` is used
with that signature in Tasks 8, 9, 10. `as_status_dict()` /
`as_numerical_dict()` are defined in Task 8 and consumed in Task 9, and
their output shape (`resolution`, `entries`, `notes`;
`under_resolved_x`) matches what Task 6's `_log_physics_status` reads and
what Task 9's test asserts. `WaferState.query` / `exposed_materials()` /
`under_resolved_x()` are defined in Task 4 and used in Tasks 5, 9, 10.
`policy_for` / `interaction` are defined in Task 7 and used in Task 8.

## Expected regression points

| Where | Why | Action if it fires |
|---|---|---|
| Task 9 full regression | Resolver now on the etch path | Behaviour must be unchanged (empty table). A changed number means the resolver is overriding caller rates — fix the resolver. |
| Task 6 | `ProcessResult` gained fields | Positional construction anywhere would break; the fields are keyword-with-default, so only positional callers are at risk. |
| Task 2 | `run_doping()` now returns bool | Existing callers ignore the return value, so they are unaffected; verify no caller tests `if self.run_doping()` with inverted meaning. |
| Task 10 | Permutation sweep is new and runs many flows | If it is slow, reduce `STEPS` rather than skipping the test. |
| Task 11 | Oxidation timings | 2.0 hr oxidation at grid 0.02 is the slowest step in the suite; if too slow, drop to 0.5/1.0 hr and keep both ratios. |

Pre-existing failures that are **not** regressions:
`test_device_lifecycle_repeat_real`, `test_robust_iv_sweep_real`,
`test_gui_measurement_doping_kinds_real`.
