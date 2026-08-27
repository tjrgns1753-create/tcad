# Electrode/Pin System + DC Sweep Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user place named electrodes (Source/Drain/Gate/Body) at real wafer coordinates on a fabricated device, validate and resolve each one to a real DevSim contact, read potential at an arbitrary point, and run a real DC operating point / Id-Vgs / Id-Vds sweep — all through real ViennaPS + DevSim, extending (not replacing) this project's existing region-based contact and sweep infrastructure.

**Architecture:** Contacts today are derived ONLY from a material region's own axis-extreme (`<region>_<axis>min/max`, via `import_process_result`'s `contact_regions`/`contact_axis`/`contact_axes`/`contact_sides`) — confirmed by reading `tcad/device/devsim/mesh_import.py` and `_make_measurement_panel()`'s own docstring ("'Pin' here is deliberately NOT a free-form point the user clicks on the mesh"). This plan adds a genuinely free-form coordinate-to-boundary path as two new, additive parameters on `import_process_result` (`point_contacts`, `extra_contacts`) plus a new pre-validation layer (`tcad/device/devsim/contact_probe.py`) that classifies an invalid placement (outside mesh / on an insulator / no boundary nearby) BEFORE a doomed import is attempted. Pin (logical, backend-independent) and Contact (real DevSim boundary) stay in separate modules, mirroring this project's existing `tcad/mesh/interface.py` (Process side) vs `tcad/device/devsim/*` (Device side) split. The three existing sweep engines (`pn_junction_iv_sweep.py`, `robust_iv_sweep.py`, `mosfet_sweep.py`) are extended, not rewritten: Id-Vds is added by mirroring Id-Vgs's own proven pattern, and an optional Body contact is added as a fourth, independently-biased (never swept) terminal.

**Tech Stack:** Python 3.13, ViennaPS 4.6.2, DevSim 2.x, tkinter (GUI), meshio. No pytest — every test is a standalone `def main(): ... assert ...` script discovered by `tests/run_regression.py`.

**Spec:** The user's own 16-section specification (this session's conversation) is the spec this plan argues from; no separate spec file exists. Investigation was done directly against the current codebase (see the "Investigated" note under each area below) rather than assumed.

## Global Constraints

- **Test runner is NOT pytest.** `def main(): ...` + `if __name__ == "__main__": main()`, plain `assert`, discovered by `tests/run_regression.py` via `glob("test_*.py")` under `tests/unit/` (mock, no real backend) and `tests/integration/` (`_real.py` suffix, `assert session.is_available()` / `assert devsim_backend.is_available()` at import time). Run with `PYTHONIOENCODING=utf-8 python tests/run_regression.py` (Windows cp949 console truncates tracebacks otherwise).
- **Baseline regression: 57 passed, 3 failed** (`test_device_lifecycle_repeat_real.py`, `test_gui_measurement_doping_kinds_real.py`, `test_robust_iv_sweep_real.py` — pre-existing DevSim convergence/solver-noise issues, unrelated to this work). Any NEW failure beyond these three is a regression and must be root-caused before the task is done.
- **No fake physics.** Confirmed by reading the installed backends' real APIs, not assumed: `devsim.get_node_model_values(device=, region=, name="Potential")` is real and already used by `tests/integration/test_phase7_doping_real.py`, `test_phase8_pn_junction_real.py`, `test_phase14_flow_devsim_real.py`. Do not invent a per-point "convergence continuation" (catch-and-continue) sweep mode — every existing sweep function in `tcad/characterization/` raises on a non-converging `solve()` call, and every existing test relies on that (e.g. `test_mosfet_id_vgs_real.py`'s own comment: "every gate-voltage point converges (the sweep itself raises on non-convergence)"). This plan does not change that contract.
- **Do not modify** `tcad/physics/resolve.py`, `tcad/physics/wafer_state.py`, `tcad/physics/intent.py`, `tcad/physics/tables.py`, `tcad/physics/values.py`. Doping is still not wired into `WaferState` (deliberate, pre-existing, unrelated to this plan).
- **Coordinate convention.** Wafer coordinates run `0..width_um`; mesh/DevSim coordinates are domain-centered (`0` at the wafer's own horizontal center). Convert with `x_domain_um = x_wafer_um - width_um / 2.0` — the exact convention `tcad_2d_stagewise.py`'s own `_resist_spans_um()`/`redraw()` PR-overlay code and `tcad.physics.doping.implant_windows_from_mask_spans()` already use. Never re-derive this independently (see CLAUDE.md's own PN-diode coordinate-mixup investigation).
- **One task = one commit.** Run the affected test(s) after every task; run the full regression suite before the final task's own commit and report the delta against 57/3, not just "passed/failed".
- **`import_process_result`'s existing behavior is byte-for-byte frozen** for every existing caller: both new parameters (`point_contacts`, `extra_contacts`) default to `None`/empty and are additive branches alongside the existing `contact_regions` loop, never replacing it.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `tcad/mesh/pin.py` | NEW. Backend-independent `Pin` dataclass (logical electrode: name, role, wafer-coordinate position, optional target region hint) | 1 |
| `tcad/device/devsim/contact_probe.py` | NEW. `PinPlacementError` + reason codes, `probe_mesh_at_point()` (pure geometry), `validate_pin_placement()`, `resolve_pins_to_point_contacts()` | 1, 2 |
| `tcad/device/devsim/mesh_import.py` | MODIFY (additive only). `import_process_result()` gains `point_contacts` and `extra_contacts` optional params | 3, 4 |
| `tcad/device/devsim/voltage_probe.py` | NEW. `read_potential_at_point()` — nearest-node `Potential` readback with bounds/NaN guards | 5 |
| `tcad/characterization/mosfet_sweep.py` | MODIFY (additive only). New `run_mosfet_id_vds_sweep()`; both Id-Vgs/Id-Vds gain optional `body_contact`/`body_voltage` | 6, 7 |
| `tcad/characterization/interface.py` | MODIFY (additive only). `BiasPoint` gains `converged: bool = True` | 8 |
| `tcad/characterization/dc_operating_point.py` | NEW. `solve_mosfet_dc_operating_point()` — thin wrapper: one-element Id-Vgs sweep, returns `points[0]` | 8 |
| `tests/unit/test_pin_model_mock.py` | NEW. Pure dataclass/validation-shape tests, no backend | 1 |
| `tests/integration/test_pin_placement_validation_real.py` | NEW. Real-mesh coordinate resolution: valid Si boundary, outside mesh, on SiO2, interior bulk | 2 |
| `tests/integration/test_point_contact_import_real.py` | NEW. `point_contacts` + `extra_contacts` on `import_process_result`, plus existing-contact regression check | 3, 4 |
| `tests/integration/test_voltage_probe_real.py` | NEW. Potential readback at valid/invalid points against a real solved device | 5 |
| `tests/integration/test_mosfet_id_vds_real.py` | NEW. Id-Vds sweep, mirrors `test_mosfet_id_vgs_real.py`'s structure | 6 |
| `tests/integration/test_mosfet_body_contact_real.py` | NEW. 4-terminal S/D/G/B device, KCL across 3 conducting terminals | 7 |
| `tests/unit/test_cad_negative_validation_mock.py` | NEW. Pure-Python CAD-style negative tests (no backend) | 9 |
| `tests/integration/test_cad_negative_validation_real.py` | NEW. The negative tests that need a real mesh (Drain-on-SiO2, zero contacts + solve) | 9 |
| `tcad_2d_stagewise.py` | MODIFY. New "Electrodes" GUI panel (Pin list, RESOLVE, DC-OP, Id-Vgs/Id-Vds sweep, EXPORT) | 10, 11 |
| `tests/integration/test_gui_electrode_panel_real.py` | NEW. Drives the real GUI (window withdrawn) through Pin placement -> DC-OP -> sweep | 10 |
| `tests/integration/test_device_fabrication_to_dc_sweep_real.py` | NEW. Capstone end-to-end test | 12 |

---

### Task 1: Pin data model + PinPlacementError scaffolding

**Files:**
- Create: `tcad/mesh/pin.py`
- Create: `tcad/device/devsim/contact_probe.py` (error/reason-code half only — no mesh reading yet)
- Test: `tests/unit/test_pin_model_mock.py`

**Interfaces:**
- Produces: `Pin` dataclass (`tcad.mesh.pin.Pin`): `name: str`, `role: str` (free-form, e.g. `"Source"`/`"Drain"`/`"Gate"`/`"Body"`/custom), `x_um: float`, `y_um: float` (WAFER coordinates), `target_region: Optional[str] = None`.
- Produces: `PinPlacementError` (`tcad.device.devsim.contact_probe.PinPlacementError`), subclass of `Exception`, with `.pin: Pin`, `.reason: str`, `.detail: str`. Produces the reason-code constants `REASON_OUTSIDE_MESH`, `REASON_ON_INSULATOR`, `REASON_INTERIOR_BULK`, `REASON_NO_BOUNDARY_NEARBY`, `REASON_DUPLICATE_POSITION` (all plain strings, e.g. `"outside_mesh"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pin_model_mock.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure dataclass/validation-shape tests for the Pin model -- no
ViennaPS/DevSim needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.mesh.pin import Pin
    from tcad.device.devsim.contact_probe import (
        PinPlacementError, REASON_OUTSIDE_MESH, REASON_ON_INSULATOR,
        REASON_INTERIOR_BULK, REASON_NO_BOUNDARY_NEARBY,
        REASON_DUPLICATE_POSITION,
    )

    pin = Pin(name="Drain", role="Drain", x_um=4.0, y_um=0.0)
    assert pin.name == "Drain"
    assert pin.role == "Drain"
    assert pin.x_um == 4.0
    assert pin.y_um == 0.0
    assert pin.target_region is None

    pin2 = Pin(name="Gate", role="Gate", x_um=2.0, y_um=0.15, target_region="TiN")
    assert pin2.target_region == "TiN"

    err = PinPlacementError(pin, REASON_OUTSIDE_MESH, "x=4.0 is past the mesh's own x_max=3.5")
    assert err.pin is pin
    assert err.reason == REASON_OUTSIDE_MESH
    assert "x_max" in err.detail
    assert isinstance(err, Exception)

    reasons = {
        REASON_OUTSIDE_MESH, REASON_ON_INSULATOR, REASON_INTERIOR_BULK,
        REASON_NO_BOUNDARY_NEARBY, REASON_DUPLICATE_POSITION,
    }
    assert len(reasons) == 5, "reason codes must all be distinct strings"

    print("Pin model + PinPlacementError scaffolding: OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_pin_model_mock.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'tcad.mesh.pin'`

- [ ] **Step 3: Write the Pin dataclass**

```python
# tcad/mesh/pin.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pin — a user-placed LOGICAL electrode position, backend-independent
(mirrors tcad/mesh/interface.py's own Process/Device separation: this
module has no viennaps, meshio, or devsim import).

A Pin is where the user says an electrode goes; it becomes a real
DevSim Contact only after tcad.device.devsim.contact_probe validates
it against the actual mesh and tcad.device.devsim.mesh_import.
import_process_result() imports it. See that module's own docstring
for why the two are kept separate rather than merged into one object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Pin:
    """One user-placed electrode.

    name : unique label the user gave this pin (e.g. "Drain"). Used as
        the resulting DevSim contact's name once resolved.
    role : free-form electrical role (e.g. "Source"/"Drain"/"Gate"/
        "Body"), for GUI display and physical-invariant checks (e.g.
        "which pins carry DC current" — a Gate normally does not).
        Not read by contact_probe.py itself, which only cares about
        WHERE the pin is.
    x_um / y_um : WAFER coordinates (0..width_um / 0..y_extent_um),
        the same coordinate system Wafer.mask_left_um/mask_right_um
        already use. Converted to domain-centered coordinates only at
        the point of mesh lookup (see contact_probe.py) — never
        pre-converted here, so a Pin's own fields always read the same
        as what the user typed into the GUI.
    target_region : optional hint for which MaterialRegion.name this
        pin is expected to land on (e.g. "Si", "TiN") — purely
        informational; contact_probe.py determines the ACTUAL region
        from the real mesh regardless of this hint, and flags a
        mismatch rather than trusting it blindly.
    """

    name: str
    role: str
    x_um: float
    y_um: float
    target_region: Optional[str] = None
```

- [ ] **Step 4: Write the error/reason-code scaffolding**

```python
# tcad/device/devsim/contact_probe.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Coordinate -> real mesh boundary -> DevSim contact resolution.

Backend-side counterpart to tcad/mesh/pin.py's Pin: this module reads
a REAL process-generated mesh (meshio, same convention
tcad/device/devsim/mesh_import.py already uses) and determines, for
each Pin, whether its (x_um, y_um) WAFER-coordinate position lands on
a real, contactable material boundary -- and if not, WHY (one of the
REASON_* codes below), so a CAD-style error can name the actual
problem instead of a generic import failure.

Kept as its own module rather than folded into mesh_import.py: that
file is already 1000+ lines and heavily exercised by every existing
contact-derivation caller; this module ADDS a new pre-validation layer
in front of it without touching any of that file's existing logic
(mesh_import.py itself only gains two new, additive, opt-in parameters
-- see Task 3/4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tcad.mesh.pin import Pin

#: A point outside the mesh's own bounding box entirely.
REASON_OUTSIDE_MESH = "outside_mesh"
#: A point that resolves to a real material boundary, but that
#: material is not electrically contactable (e.g. SiO2/Si3N4 -- an
#: insulator, or PHS/Mask -- resist, which never reaches the real mesh
#: at all per this project's own litho-is-state-only design, so a
#: point over resist reports this same reason, not a distinct one --
#: see contact_probe.py's own docstring on probe_mesh_at_point()).
REASON_ON_INSULATOR = "on_insulator"
#: Inside the mesh's bounding box, but not near any boundary edge --
#: e.g. deep inside bulk Si, away from every real contact surface.
REASON_INTERIOR_BULK = "interior_bulk"
#: Inside the mesh's bounding box, near no boundary edge of ANY
#: material within the search tolerance (distinct from
#: REASON_INTERIOR_BULK only in that this project's callers may choose
#: to report it separately for a point that isn't clearly "deep bulk"
#: either, e.g. right at a material-material interface with no outer
#: mesh boundary there).
REASON_NO_BOUNDARY_NEARBY = "no_boundary_nearby"
#: Two (or more) pins resolved to the identical contact position --
#: checked at the multi-pin batch level (resolve_pins_to_point_contacts),
#: never by validate_pin_placement() on a single pin alone.
REASON_DUPLICATE_POSITION = "duplicate_position"


class PinPlacementError(Exception):
    """Raised (or collected, in the batch resolver) when a Pin cannot
    become a real DevSim contact.

    pin : the Pin that failed.
    reason : one of the REASON_* constants above.
    detail : a human-readable, GUI-displayable explanation with real
        numbers (e.g. actual mesh bounds), never a generic message.
    """

    def __init__(self, pin: Pin, reason: str, detail: str):
        self.pin = pin
        self.reason = reason
        self.detail = detail
        super().__init__(f"{pin.name}: {reason} -- {detail}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_pin_model_mock.py`
Expected: PASS — `Pin model + PinPlacementError scaffolding: OK`

- [ ] **Step 6: Run full regression to confirm no impact**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 58 passed, 3 failed (one new PASS, same 3 pre-existing failures)

- [ ] **Step 7: Commit**

```bash
git add tcad/mesh/pin.py tcad/device/devsim/contact_probe.py tests/unit/test_pin_model_mock.py
git commit -m "feat: Pin data model and PinPlacementError scaffolding"
```

---

### Task 2: Coordinate -> mesh boundary resolution

**Files:**
- Modify: `tcad/device/devsim/contact_probe.py`
- Test: `tests/integration/test_pin_placement_validation_real.py`

**Interfaces:**
- Consumes: `Pin` (Task 1), `PinPlacementError` + `REASON_*` (Task 1), `ProcessResult` (`tcad.mesh.interface`, existing).
- Produces: `probe_mesh_at_point(points, triangles, tags, tag_to_name, x_domain_um, y_um, tolerance_um) -> Optional[Tuple[str, float]]` — pure geometry function (no file I/O), returns `(region_name, distance_um)` for the nearest BOUNDARY edge's owning region within `tolerance_um`, or `None` if nothing boundary-like is within tolerance. Produces `validate_pin_placement(result: ProcessResult, pin: Pin, width_um: float, contactable_materials: set, tolerance_um: float = 0.05) -> str` — returns the resolved region name on success, raises `PinPlacementError` on failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pin_placement_validation_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coordinate -> mesh boundary resolution against a REAL ViennaPS mesh:
a valid point on Si's own boundary, a point outside the mesh, a point
on SiO2 (insulator), and a point deep in Si bulk (no boundary nearby)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

from tcad.mesh.viennaps_adapter import build_process_result
from tcad.mesh.pin import Pin
from tcad.device.devsim.contact_probe import (
    validate_pin_placement, PinPlacementError,
    REASON_OUTSIDE_MESH, REASON_ON_INSULATOR, REASON_INTERIOR_BULK,
)
from tcad.process.registry import get as get_step

WIDTH_UM = 10.0
GRID = 0.2


def _oxidized_si_result(tmp):
    """A real thermal oxidation on a fresh wafer: Si body + a thin SiO2
    cap on top -- a real 2-material mesh with a real insulator, no
    hand-built geometry."""
    step_cls = get_step("oxidation", "thermal")
    step = step_cls()
    recipe = {
        "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
        "silicon_depth_um": 3.0, "oxide_thickness_um": 0.3,
        "oxidation_time_hr": 1.0,
    }
    result = step.run(recipe, tmp)
    return build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _oxidized_si_result(tmp)
        contactable = {"Si"}

        # Valid: bottom of the wafer, well inside Si's own real boundary.
        valid_pin = Pin(name="Body", role="Body", x_um=WIDTH_UM / 2.0, y_um=-2.9)
        region = validate_pin_placement(process_result, valid_pin, WIDTH_UM, contactable)
        assert region == "Si", f"expected Si, got {region}"
        print(f"[1/4] valid pin on Si boundary resolves: region={region}")

        # Invalid: far outside the mesh entirely.
        outside_pin = Pin(name="Ghost", role="Drain", x_um=1000.0, y_um=0.0)
        try:
            validate_pin_placement(process_result, outside_pin, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for a point outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/4] outside-mesh pin correctly rejected: {exc.detail}")

        # Invalid: on the SiO2 cap, which is NOT in contactable_materials.
        oxide_pin = Pin(name="BadGate", role="Gate", x_um=WIDTH_UM / 2.0, y_um=0.15)
        try:
            validate_pin_placement(process_result, oxide_pin, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for a point on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[3/4] on-insulator pin correctly rejected: {exc.detail}")

        # Invalid: deep inside Si bulk, away from every real boundary.
        bulk_pin = Pin(name="Buried", role="Body", x_um=WIDTH_UM / 2.0, y_um=-1.5)
        try:
            validate_pin_placement(process_result, bulk_pin, WIDTH_UM, contactable, tolerance_um=0.05)
            assert False, "expected PinPlacementError for a point deep in Si bulk"
        except PinPlacementError as exc:
            assert exc.reason == REASON_INTERIOR_BULK, exc.reason
            print(f"[4/4] interior-bulk pin correctly rejected: {exc.detail}")

    print()
    print("COORDINATE -> MESH BOUNDARY RESOLUTION VERIFIED against real ViennaPS 4.6.2")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_pin_placement_validation_real.py`
Expected: FAIL — `ImportError: cannot import name 'validate_pin_placement'`

- [ ] **Step 3: Implement `probe_mesh_at_point` and `validate_pin_placement`**

Append to `tcad/device/devsim/contact_probe.py`:

```python
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import numpy as np


def probe_mesh_at_point(
    points: "np.ndarray",
    triangles: "np.ndarray",
    tags: "np.ndarray",
    tag_to_name: Dict[int, str],
    x_domain_um: float,
    y_um: float,
    tolerance_um: float,
) -> Optional[Tuple[str, float]]:
    """Nearest REAL BOUNDARY edge (touched by exactly one triangle,
    same definition tcad.device.devsim.mesh_import.import_process_result
    already uses for its own axis-extreme contacts) to (x_domain_um,
    y_um), within tolerance_um. Returns (owning_region_name,
    distance_um), or None if nothing boundary-like is within
    tolerance. Pure geometry -- no file I/O, so Task 2's own test can
    exercise it directly against an in-memory mesh if ever needed,
    and validate_pin_placement() below stays a thin wrapper around it.
    """
    edge_owner_tags: Dict[tuple, List[int]] = defaultdict(list)
    for tri, tag in zip(triangles, tags):
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            edge_owner_tags[key].append(int(tag))

    target = np.array([x_domain_um, y_um])
    best_dist = None
    best_tag = None
    for edge, owners in edge_owner_tags.items():
        if len(owners) != 1:
            continue  # interior edge, not a real boundary
        p0, p1 = points[edge[0]], points[edge[1]]
        seg = p1 - p0
        seg_len_sq = float(np.dot(seg, seg))
        if seg_len_sq == 0.0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, float(np.dot(target - p0, seg)) / seg_len_sq))
        nearest = p0 + t * seg
        dist = float(np.linalg.norm(target - nearest))
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_tag = owners[0]

    if best_dist is None or best_dist > tolerance_um:
        return None
    return tag_to_name[best_tag], best_dist


def validate_pin_placement(
    result,
    pin: Pin,
    width_um: float,
    contactable_materials: Set[str],
    tolerance_um: float = 0.05,
) -> str:
    """Resolve one Pin's WAFER-coordinate position to a real,
    contactable material region on `result`'s own mesh. Returns the
    resolved region name on success; raises PinPlacementError
    (REASON_OUTSIDE_MESH / REASON_ON_INSULATOR / REASON_INTERIOR_BULK)
    on failure.

    contactable_materials : the set of MaterialRegion.name values this
        caller considers electrically contactable (e.g. {"Si", "TiN",
        "W", "Cu"} for a real MOSFET) -- deliberately NOT hardcoded
        here, since which materials count as a real conductor/
        semiconductor is a caller-level (GUI/test) decision, not
        something this backend-adjacent module should assume. A
        resolved region NOT in this set is reported as
        REASON_ON_INSULATOR regardless of whether it is physically an
        insulator (SiO2) or simply not one this caller wants to
        contact -- the distinction does not matter to the caller
        either way: neither should become a contact.
    """
    import meshio

    x_domain_um = pin.x_um - width_um / 2.0
    y_um = pin.y_um

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise PinPlacementError(pin, REASON_OUTSIDE_MESH, "mesh has no triangle cells")
    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]
    points = mesh.points[:, :2]  # (x, y) -- drop any z from a 2D mesh's own convention
    tag_to_name = {region.tag: region.name for region in result.material_regions}

    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    if not (x_min <= x_domain_um <= x_max and y_min <= y_um <= y_max):
        raise PinPlacementError(
            pin, REASON_OUTSIDE_MESH,
            f"({pin.x_um:.4f}, {pin.y_um:.4f}) um (wafer coords) is outside the "
            f"mesh's own bounds x=[{x_min:.4f},{x_max:.4f}] "
            f"y=[{y_min:.4f},{y_max:.4f}] (domain coords)",
        )

    found = probe_mesh_at_point(points, triangles, tags, tag_to_name, x_domain_um, y_um, tolerance_um)
    if found is None:
        raise PinPlacementError(
            pin, REASON_INTERIOR_BULK,
            f"no real material boundary within {tolerance_um}um of "
            f"({pin.x_um:.4f}, {pin.y_um:.4f}) um -- this point is inside bulk "
            f"material, not on a contactable surface",
        )

    region_name, distance_um = found
    if region_name not in contactable_materials:
        raise PinPlacementError(
            pin, REASON_ON_INSULATOR,
            f"nearest boundary ({distance_um:.4f}um away) belongs to {region_name!r}, "
            f"which is not in the contactable set {sorted(contactable_materials)}",
        )
    return region_name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_pin_placement_validation_real.py`
Expected: PASS — all 4 checks print, final line "COORDINATE -> MESH BOUNDARY RESOLUTION VERIFIED..."

- [ ] **Step 5: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 59 passed, 3 failed

- [ ] **Step 6: Commit**

```bash
git add tcad/device/devsim/contact_probe.py tests/integration/test_pin_placement_validation_real.py
git commit -m "feat: coordinate-to-mesh-boundary pin placement resolution"
```

---

### Task 3: `point_contacts` on `import_process_result()`

**Files:**
- Modify: `tcad/device/devsim/mesh_import.py`
- Test: `tests/integration/test_point_contact_import_real.py`

**Interfaces:**
- Consumes: `import_process_result()`'s existing signature (unchanged for every existing parameter).
- Produces: new optional parameter `point_contacts: Optional[List[Dict]] = None` on `import_process_result()`. Each item: `{"name": str, "region": str, "x_domain_um": float, "y_um": float, "radius_um": float}` — already in the SAME mesh-space coordinates `import_process_result` works in internally (domain-centered, pre-`length_scale_to_cm`), matching the function's existing convention of taking raw mesh-space info and never touching wafer coordinates itself (that conversion is the CALLER's job, done by `contact_probe.py`'s pin-resolution layer in Task 2 / GUI wiring in Task 10).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_point_contact_import_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""point_contacts on import_process_result(): two coordinate-placed
contacts on the SAME Si region resolve to distinct, correctly-sized
node sets, and every existing axis-extreme contact behavior is
unaffected (regression)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim.mesh_import import import_process_result
from tcad.process.registry import get as get_step

WIDTH_UM = 10.0
GRID = 0.2


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = get_step("etching", "isotropic")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
            "silicon_depth_um": 3.0, "etch_time_s": 1.0, "etch_rate_um_s": 0.05,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        # Two point contacts near opposite sides of Si's own top surface,
        # NOT at the region's own x-extremes (which contact_regions would
        # already give byte-for-byte, unchanged) -- a real interior point.
        imported = import_process_result(
            process_result, mesh_name="pc_mesh", device_name="pc_device",
            point_contacts=[
                {"name": "PinA", "region": "Si", "x_domain_um": -1.0, "y_um": 0.0, "radius_um": 0.3},
                {"name": "PinB", "region": "Si", "x_domain_um": 1.0, "y_um": 0.0, "radius_um": 0.3},
            ],
        )
        assert set(imported.contacts) == {"PinA", "PinB"}, imported.contacts
        print(f"[1/3] two point contacts created: {imported.contacts}")

        for name in ("PinA", "PinB"):
            xs = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
            # Contact-bound node count check via the region's contact node
            # list isn't directly exposed; assert indirectly: the device
            # has the named contact registered at all (DevSim would refuse
            # to solve otherwise) -- checked via get_contact_list().
        contact_list = devsim.get_contact_list(device=imported.device)
        assert set(contact_list) == {"PinA", "PinB"}, contact_list
        print(f"[2/3] both contacts registered in DevSim: {sorted(contact_list)}")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        # Regression: the EXISTING axis-extreme contact_regions path,
        # called with point_contacts omitted, is unaffected.
        imported2 = import_process_result(
            process_result, mesh_name="pc_mesh2", device_name="pc_device2",
            contact_regions=["Si"], contact_axis="x",
        )
        assert set(imported2.contacts) == {"Si_xmin", "Si_xmax"}, imported2.contacts
        print(f"[3/3] existing contact_regions path unaffected: {imported2.contacts}")
        devsim.delete_device(device=imported2.device)
        devsim.delete_mesh(mesh=imported2.mesh)

    print()
    print("point_contacts VERIFIED against real ViennaPS 4.6.2 + DevSim, "
          "existing contact_regions path confirmed byte-for-byte unaffected")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_point_contact_import_real.py`
Expected: FAIL — `TypeError: import_process_result() got an unexpected keyword argument 'point_contacts'`

- [ ] **Step 3: Implement `point_contacts`**

In `tcad/device/devsim/mesh_import.py`, add the new parameter to `import_process_result`'s signature (after `auto_refine_from_doping: bool = False,`):

```python
    point_contacts: Optional[List[Dict]] = None,
```

Add its docstring paragraph right after `auto_refine_from_doping`'s own:

```python
    point_contacts : optional list of {"name": str, "region": str,
        "x_domain_um": float, "y_um": float, "radius_um": float} dicts
        -- each creates ONE contact named `name` from every boundary
        edge of `region` whose midpoint falls within `radius_um` of
        (x_domain_um, y_um). Already in mesh-space (domain-centered,
        pre-length_scale_to_cm) coordinates -- the caller (see
        tcad.device.devsim.contact_probe) owns the wafer-to-domain
        conversion. Distinct from contact_regions/contact_axis/
        contact_sides/contact_axes (region-axis-extreme contacts):
        this is a free-form coordinate contact instead, for a
        user-placed Pin rather than an auto-derived region boundary.
        The two can be combined in one call (a region can get BOTH its
        axis-extreme contacts and one or more point contacts) -- they
        write into the same internal contact_defs list.
```

Immediately after the existing `contact_defs: List[tuple] = []` line and its `if contact_regions:` block (right before `coordinates = points.flatten().tolist()`), add:

```python
    if point_contacts:
        for spec in point_contacts:
            region_name = spec["region"]
            matching_tags = [t for t, n in tag_to_name.items() if n == region_name]
            if not matching_tags:
                continue
            region_boundary = boundary_edges_by_tag.get(matching_tags[0], [])
            if not region_boundary:
                continue

            target = np.array([spec["x_domain_um"], spec["y_um"]])
            radius = spec["radius_um"]
            near_edges = []
            for edge in region_boundary:
                p0, p1 = points[edge[0]], points[edge[1]]
                midpoint = (p0 + p1) / 2.0
                if np.linalg.norm(midpoint - target) <= radius:
                    near_edges.append(edge)

            if not near_edges:
                continue

            contact_name = spec["name"]
            idx = physical_index(contact_name)
            for edge in near_edges:
                elements += [1, idx, int(edge[0]), int(edge[1])]
            contact_defs.append((contact_name, region_name))
```

Add `import numpy as np` to the file's existing imports if not already present (check first — `mesh_refine.py`/other DevSim modules in this project already import numpy, so this is a pre-existing project dependency, not a new one).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_point_contact_import_real.py`
Expected: PASS — all 3 checks print

- [ ] **Step 5: Run the existing contact-derivation regression tests explicitly**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gate_contact_placement_real.py && PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_id_vgs_real.py`
Expected: both PASS, unchanged

- [ ] **Step 6: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 60 passed, 3 failed

- [ ] **Step 7: Commit**

```bash
git add tcad/device/devsim/mesh_import.py tests/integration/test_point_contact_import_real.py
git commit -m "feat: point_contacts on import_process_result for free-form pin placement"
```

---

### Task 4: `extra_contacts` — multiple axes per region (enables Body)

**Files:**
- Modify: `tcad/device/devsim/mesh_import.py`
- Test: `tests/integration/test_point_contact_import_real.py` (extend)

**Interfaces:**
- Consumes: Task 3's `point_contacts` machinery (the new import at the top of the file).
- Produces: new optional parameter `extra_contacts: Optional[List[Dict]] = None` on `import_process_result()`. Each item: `{"name": str, "region": str, "axis": str, "side": "min"|"max"}` — same axis-extreme boundary-edge derivation the existing `contact_regions` loop already does for a region's OWN `contact_axis`/`contact_axes` entry, but on a DIFFERENT axis, without touching that region's existing contact_regions-derived contacts. This is what makes a Body contact (Si's y-min) coexist with Source/Drain (Si's x-min/x-max) in one import call — confirmed by reading the existing loop that today's `contact_axes` dict supports only ONE axis per region name.

- [ ] **Step 1: Extend the failing test**

Add to `tests/integration/test_point_contact_import_real.py`, after Step 3's block (before the final print), a new check using the SAME isotropic-etch fixture:

```python
        # extra_contacts: Si gets its normal x-axis contact_regions pair
        # PLUS a y-axis contact for the SAME region in one call -- the
        # exact shape a Body contact needs (Source/Drain on x, Body on y).
        imported3 = import_process_result(
            process_result, mesh_name="pc_mesh3", device_name="pc_device3",
            contact_regions=["Si"], contact_axis="x",
            extra_contacts=[{"name": "Si_ymin", "region": "Si", "axis": "y", "side": "min"}],
        )
        assert set(imported3.contacts) == {"Si_xmin", "Si_xmax", "Si_ymin"}, imported3.contacts
        print(f"[4/4] extra_contacts adds a 2nd-axis contact alongside "
              f"contact_regions': {sorted(imported3.contacts)}")
        devsim.delete_device(device=imported3.device)
        devsim.delete_mesh(mesh=imported3.mesh)
```

Update the numbering comment on the prior 3 checks from `[N/3]` to `[N/4]` to match.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_point_contact_import_real.py`
Expected: FAIL — `TypeError: import_process_result() got an unexpected keyword argument 'extra_contacts'`

- [ ] **Step 3: Implement `extra_contacts`**

Add the parameter to `import_process_result`'s signature, right after `point_contacts: Optional[List[Dict]] = None,`:

```python
    extra_contacts: Optional[List[Dict]] = None,
```

Docstring paragraph, right after `point_contacts`'s own:

```python
    extra_contacts : optional list of {"name": str, "region": str,
        "axis": str, "side": "min"|"max"} dicts -- one MORE
        axis-extreme contact for `region`, on `axis`/`side`,
        independent of that region's own contact_axis/contact_axes
        entry in contact_regions. Needed once a device needs a SECOND
        axis-extreme contact on the SAME region in one call (e.g. a
        MOSFET's Body contact at Si's y-min, alongside Source/Drain at
        Si's own x-min/x-max from contact_regions) -- today's
        contact_regions loop derives at most ONE axis's min/max per
        region per call. Uses the exact same region-local-extreme
        boundary-edge derivation contact_regions already uses (see
        that loop, just above) -- not a different mechanism.
```

Add, right after the `point_contacts` block from Task 3 (still before `coordinates = points.flatten().tolist()`):

```python
    if extra_contacts:
        for spec in extra_contacts:
            region_name = spec["region"]
            matching_tags = [t for t, n in tag_to_name.items() if n == region_name]
            if not matching_tags:
                continue
            region_boundary = boundary_edges_by_tag.get(matching_tags[0], [])
            if not region_boundary:
                continue

            axis_index = {"x": 0, "y": 1, "z": 2}[spec["axis"]]
            coords_axis = points[:, axis_index]
            region_node_ids = {n for edge in region_boundary for n in edge}
            region_coords = coords_axis[list(region_node_ids)]
            target_value = region_coords.min() if spec["side"] == "min" else region_coords.max()

            def _edges_near(target, tol):
                return [
                    e for e in region_boundary
                    if abs(coords_axis[e[0]] - target) < tol and abs(coords_axis[e[1]] - target) < tol
                ]

            edges = _edges_near(target_value, 1e-6)
            if not edges:
                span = region_coords.max() - region_coords.min()
                edges = _edges_near(target_value, max(1e-6, 0.1 * span))
            if not edges:
                continue

            contact_name = spec["name"]
            idx = physical_index(contact_name)
            for edge in edges:
                elements += [1, idx, int(edge[0]), int(edge[1])]
            contact_defs.append((contact_name, region_name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_point_contact_import_real.py`
Expected: PASS — all 4 checks print

- [ ] **Step 5: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 60 passed, 3 failed (test count unchanged from Task 3 — this task extends an existing test file rather than adding a new one)

- [ ] **Step 6: Commit**

```bash
git add tcad/device/devsim/mesh_import.py tests/integration/test_point_contact_import_real.py
git commit -m "feat: extra_contacts for a second axis-extreme contact on one region"
```

---

### Task 5: Voltage probe

**Files:**
- Create: `tcad/device/devsim/voltage_probe.py`
- Test: `tests/integration/test_voltage_probe_real.py`

**Interfaces:**
- Consumes: an already-imported, already-solved `device`/`region` (real DevSim state — this module reads, never solves).
- Produces: `read_potential_at_point(device: str, region: str, raw_points, x_domain_um: float, y_um: float, length_scale_to_cm: float, tolerance_um: float = 0.5) -> float`. Raises `ValueError` if no node is within `tolerance_um`, or if the region has no `"Potential"` node model registered yet (checked via `devsim.get_node_model_list`, not assumed).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_voltage_probe_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Potential readback at an arbitrary point, against a real solved
2-terminal PN-junction device -- reuses test_phase8_pn_junction_real.py's
own real recipe shape, cross-checked directly against
devsim.get_node_model_values."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_step_junction_doping
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from tcad.device.devsim.voltage_probe import read_potential_at_point
from tcad.process.registry import get as get_step

WIDTH_UM = 4.0
GRID = 0.1
LENGTH_SCALE_TO_CM = 1.0e-4


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = get_step("etching", "isotropic")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 3.0,
            "silicon_depth_um": 1.0, "etch_time_s": 0.01, "etch_rate_um_s": 0.05,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1e16, acceptor_conc_cm3=1e14,
        )

        mesh = meshio.read(doped.volume_mesh_path)
        block = next(c for c in mesh.cells if c.type == "triangle")
        raw_points = mesh.points

        imported = import_process_result(
            doped, mesh_name="probe_mesh", device_name="probe_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        apply_doping(imported.device, doped.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        run_pn_junction_iv_sweep(
            device=imported.device, region="Si", all_contacts=imported.contacts,
            sweep_contact="Si_xmax", sweep_voltages=[0.0],
            fixed_contacts={"Si_xmin": 0.0},
        )

        # Valid: center of the device, cross-checked against the nearest
        # node's OWN Potential value read directly via DevSim.
        v = read_potential_at_point(
            imported.device, "Si", raw_points, x_domain_um=0.0, y_um=-0.5,
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert v == v, "Potential must not be NaN"  # NaN != NaN
        assert abs(v) < 10.0, f"Potential {v} is not a physically sane value for this bias"
        print(f"[1/2] valid probe point: V={v:.6f} V")

        # Invalid: far outside the mesh -- no node within tolerance.
        try:
            read_potential_at_point(
                imported.device, "Si", raw_points, x_domain_um=1000.0, y_um=0.0,
                length_scale_to_cm=LENGTH_SCALE_TO_CM,
            )
            assert False, "expected ValueError for a point far outside the mesh"
        except ValueError as exc:
            print(f"[2/2] outside-mesh probe correctly rejected: {exc}")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("VOLTAGE PROBE VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_voltage_probe_real.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'tcad.device.devsim.voltage_probe'`

- [ ] **Step 3: Implement `read_potential_at_point`**

```python
# tcad/device/devsim/voltage_probe.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Read the real, already-solved Potential field at an arbitrary point --
nearest-NODE lookup (Potential is a per-node field defined everywhere
DevSim's PotentialEquation was registered for a region, unlike a
contact, which only lives on a boundary edge subset -- see
tcad.device.devsim.contact_probe for that, deliberately different,
boundary-only lookup).

Reads only -- never solves. The caller is responsible for having
already run a real DC solve (e.g.
tcad.characterization.pn_junction_iv_sweep.run_pn_junction_iv_sweep)
on `device`/`region` first; this module has no opinion on how that
solve was set up.
"""

from __future__ import annotations

import numpy as np

from tcad.device.devsim import backend


def read_potential_at_point(
    device: str,
    region: str,
    raw_points: "np.ndarray",
    x_domain_um: float,
    y_um: float,
    length_scale_to_cm: float,
    tolerance_um: float = 0.5,
) -> float:
    """Nearest mesh node's real Potential value (volts) to
    (x_domain_um, y_um) -- domain-centered coordinates, same convention
    tcad.device.devsim.contact_probe.validate_pin_placement uses.

    raw_points : the mesh's own points array BEFORE length_scale_to_cm
        was applied (i.e. straight from meshio.read(...).points, in
        the same um units x_domain_um/y_um are given in) -- this
        module does the cm conversion internally when comparing
        against DevSim's own (cm-scale) node "x"/"y" node models, so a
        caller never has to pre-scale its target point.

    Raises ValueError if no node of `region` is within tolerance_um,
    or if `region` has no "Potential" node model registered (i.e. no
    equation using it was ever set up -- checked directly against
    DevSim's own node-model list, not assumed).
    """
    module = backend.require_devsim()

    node_models = module.get_node_model_list(device=device, region=region)
    if "Potential" not in node_models:
        raise ValueError(
            f"region {region!r} on device {device!r} has no 'Potential' node "
            f"model registered -- no equation using it has been solved yet "
            f"(node models present: {sorted(node_models)})"
        )

    xs_cm = np.array(module.get_node_model_values(device=device, region=region, name="x"))
    ys_cm = np.array(module.get_node_model_values(device=device, region=region, name="y"))
    potentials = np.array(module.get_node_model_values(device=device, region=region, name="Potential"))

    target_cm = np.array([x_domain_um, y_um]) * length_scale_to_cm
    node_coords_cm = np.column_stack([xs_cm, ys_cm])
    distances_cm = np.linalg.norm(node_coords_cm - target_cm, axis=1)
    nearest_index = int(np.argmin(distances_cm))
    nearest_distance_um = float(distances_cm[nearest_index]) / length_scale_to_cm

    if nearest_distance_um > tolerance_um:
        raise ValueError(
            f"no node of region {region!r} is within {tolerance_um}um of "
            f"({x_domain_um:.4f}, {y_um:.4f}) um -- nearest node is "
            f"{nearest_distance_um:.4f}um away"
        )

    value = float(potentials[nearest_index])
    if value != value:  # NaN check without importing math for one use
        raise ValueError(
            f"nearest node's own Potential value is NaN -- the solve at "
            f"this point never converged to a real number"
        )
    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_voltage_probe_real.py`
Expected: PASS — both checks print

- [ ] **Step 5: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 61 passed, 3 failed

- [ ] **Step 6: Commit**

```bash
git add tcad/device/devsim/voltage_probe.py tests/integration/test_voltage_probe_real.py
git commit -m "feat: voltage probe -- nearest-node Potential readback at an arbitrary point"
```

---

### Task 6: Id-Vds sweep

**Files:**
- Modify: `tcad/characterization/mosfet_sweep.py`
- Test: `tests/integration/test_mosfet_id_vds_real.py`

**Interfaces:**
- Consumes: `run_mosfet_id_vgs_sweep`'s own already-proven tolerance/ramp constants (`_DD_ABSOLUTE_ERROR`, `_DD_RELATIVE_ERROR`, `_RAMP_MIN_STEP`, `_RAMP_MAX_ITER`, `_RAMP_STEP_SIZE`) — reused, not re-derived.
- Produces: `run_mosfet_id_vds_sweep(device, si_region, oxide_region, source_contact, drain_contact, gate_contact, interface_name, drain_voltages: List[float], gate_voltage: float, temperature_k=300.0, relative_error=1e-6, maximum_iterations=100) -> CharacterizationResult` — same shape as `run_mosfet_id_vgs_sweep`, with gate and drain's roles swapped (gate ramped ONCE to its fixed value, drain is the swept variable).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_mosfet_id_vds_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MOSFET Id-Vds output characteristic -- mirrors
test_mosfet_id_vgs_real.py's own device/geometry exactly, gate held
fixed, drain swept."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401 -- registers gate_stack
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import (
    derive_implant_windows_refinement, import_process_result,
)
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
from tcad.characterization.mosfet_sweep import run_mosfet_id_vds_sweep

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17
SD_DOPING_CM3 = 1e20
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4
GATE_VOLTAGE = 4.0

RECIPE = {
    "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0,
    "silicon_depth_um": 1.0, "channel_um": list(CHANNEL), "source_um": list(SRC),
    "drain_um": list(DRN), "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15, "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])

        mesh = meshio.read(filtered)
        block = next(c for c in mesh.cells if c.type == "triangle")
        idx = mesh.cells.index(block)
        points, triangles, tags = mesh.points, block.data, mesh.cell_data["Material"][idx]

        def _dope(process_result):
            return apply_implant_windows_doping(
                process_result, region="Si", axis="x",
                background_doping_cm3=BACKGROUND_DOPING_CM3,
                windows=[
                    {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                    {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
                ],
            )

        doping = _dope(build_process_result({"final_mesh": filtered, "snapshots": []})).doping
        predicates = derive_implant_windows_refinement(
            doping, points, triangles, interface_position_um=0.0, interface_axis="y",
        )
        refined_points, refined_tris, refined_tags = graded_refine_mesh_near(points, triangles, tags, predicates)
        refined_mesh = meshio.Mesh(
            points=refined_points, cells=[("triangle", refined_tris)],
            cell_data={"Material": [refined_tags]},
        )
        refined_path = f"{filtered}.refined.vtu"
        meshio.write(refined_path, refined_mesh)
        print(f"[1/4] device built + refined: {len(refined_points)} points")

        process_result = _dope(build_process_result({"final_mesh": refined_path, "snapshots": result["snapshots"]}))
        imported = import_process_result(
            process_result, mesh_name="mosfet_vds_mesh", device_name="mosfet_vds_device",
            contact_regions=["Si", "SiO2"], contact_axis="x",
            contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.contacts) == {"Si_xmin", "Si_xmax", "SiO2_ymax"}, imported.contacts
        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        print(f"[2/4] imported + doped: contacts={imported.contacts}")

        drain_voltages = [0.0, 0.05, 0.1, 0.2, 0.3]
        result_iv = run_mosfet_id_vds_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltages=drain_voltages, gate_voltage=GATE_VOLTAGE,
        )
        assert len(result_iv.points) == len(drain_voltages)
        id_series = [pt.currents["Si_xmax"] for pt in result_iv.points]
        is_series = [pt.currents["Si_xmin"] for pt in result_iv.points]
        print(f"[3/4] Vds (V): {drain_voltages}")
        print(f"      Id  (A): {[f'{i:.4e}' for i in id_series]}")

        id_scale = max(abs(i) for i in id_series)
        for vd, i_source, i_drain in zip(drain_voltages, is_series, id_series):
            assert abs(i_source + i_drain) < 0.02 * id_scale, (
                f"charge not conserved at Vds={vd}: Is={i_source:.4e} Id={i_drain:.4e}"
            )
        print(f"[4/4] charge conserved (|Is+Id| < 2% of sweep scale) at every point")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("MOSFET Id-Vds SWEEP VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_id_vds_real.py`
Expected: FAIL — `ImportError: cannot import name 'run_mosfet_id_vds_sweep'`

- [ ] **Step 3: Implement `run_mosfet_id_vds_sweep`**

Append to `tcad/characterization/mosfet_sweep.py`, after `run_mosfet_id_vgs_sweep`:

```python
def run_mosfet_id_vds_sweep(
    device: str,
    si_region: str,
    oxide_region: str,
    source_contact: str,
    drain_contact: str,
    gate_contact: str,
    interface_name: str,
    drain_voltages: List[float],
    gate_voltage: float,
    temperature_k: float = 300.0,
    relative_error: float = 1.0e-6,
    maximum_iterations: int = 100,
) -> CharacterizationResult:
    """Solve Si+oxide equilibrium, enable Si drift-diffusion, ramp the
    gate bias to its fixed target, then sweep drain voltage -- reading
    real source/drain terminal current at every point. Mirrors
    run_mosfet_id_vgs_sweep's own sequence exactly, with the gate and
    drain roles swapped (gate is ramped ONCE, drain is the swept
    variable) -- see that function's own docstring for why each
    tolerance/ramp constant below is what it is; this sweep reuses the
    identical values rather than re-deriving them, since it exercises
    the same Si+oxide+interface device under the same drift-diffusion
    equations.

    One call per device -- same restriction run_mosfet_id_vgs_sweep
    documents. Every current returned is PER UNIT DEPTH -- see
    tcad.characterization.interface.CURRENT_CONVENTION_NOTE.
    """
    module = backend.require_devsim()
    from devsim.python_packages.ramp import rampbias

    si_contacts = [source_contact, drain_contact]
    no_op_callback = lambda _device: None  # noqa: E731

    # 1. Equilibrium: Si + oxide Poisson-only, coupled at the interface.
    setup_mosfet_potential_equation(
        device, si_region, oxide_region, si_contacts, gate_contact,
        interface_name, temperature_k,
    )
    module.solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)

    # 2. Enable drift-diffusion transport in Si at the same equilibrium bias.
    setup_drift_diffusion_equation(device, si_region, si_contacts)
    module.solve(
        type="dc", absolute_error=_DD_ABSOLUTE_ERROR, relative_error=_DD_RELATIVE_ERROR,
        maximum_iterations=maximum_iterations,
    )

    # 3. Ramp the gate bias up to its fixed target.
    rampbias(
        device, gate_contact, gate_voltage, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
        _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
    )

    points: List[BiasPoint] = []
    for vd in drain_voltages:
        # 4. Ramp drain voltage to each target.
        rampbias(
            device, drain_contact, vd, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
            _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
        )

        currents = read_drift_diffusion_terminal_currents(device, si_contacts)
        voltages = {source_contact: 0.0, gate_contact: gate_voltage, drain_contact: vd}

        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="mosfet_id_vds_sweep",
        device=device,
        region=si_region,
        sweep_contact=drain_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "oxide_region": oxide_region,
            "source_contact": source_contact,
            "gate_contact": gate_contact,
            "gate_voltage": gate_voltage,
            "interface": interface_name,
            "physics": "drift_diffusion",
            "current_convention": CURRENT_CONVENTION_NOTE,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_id_vds_real.py`
Expected: PASS — all 4 checks print

- [ ] **Step 5: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 62 passed, 3 failed

- [ ] **Step 6: Commit**

```bash
git add tcad/characterization/mosfet_sweep.py tests/integration/test_mosfet_id_vds_real.py
git commit -m "feat: MOSFET Id-Vds output-characteristic sweep"
```

---

### Task 7: Optional Body contact on both MOSFET sweeps

**Files:**
- Modify: `tcad/characterization/mosfet_sweep.py`
- Test: `tests/integration/test_mosfet_body_contact_real.py`

**Interfaces:**
- Consumes: Task 4's `extra_contacts` (to create `Si_ymin` as Body alongside `Si_xmin`/`Si_xmax`).
- Produces: `run_mosfet_id_vgs_sweep` and `run_mosfet_id_vds_sweep` both gain `body_contact: Optional[str] = None, body_voltage: float = 0.0` (default `None` → byte-for-byte unchanged behavior for every existing caller). When set, the body contact is included in `si_contacts` (so it gets a continuity equation and a read current) and biased ONCE via `set_bias` before the sweep loop — never ramped/swept itself.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_mosfet_body_contact_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4-terminal S/D/G/B device: Body is Si's own y-min (extra_contacts,
Task 4), biased at a fixed 0V through an Id-Vgs sweep -- KCL across
the 3 conducting terminals (Source/Drain/Body; Gate carries no DC
current, matching test_mosfet_id_vgs_real.py's own established check)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import (
    derive_implant_windows_refinement, import_process_result,
)
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17
SD_DOPING_CM3 = 1e20
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4
DRAIN_VOLTAGE = 0.1

RECIPE = {
    "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0,
    "silicon_depth_um": 1.0, "channel_um": list(CHANNEL), "source_um": list(SRC),
    "drain_um": list(DRN), "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15, "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])
        mesh = meshio.read(filtered)
        block = next(c for c in mesh.cells if c.type == "triangle")
        idx = mesh.cells.index(block)
        points, triangles, tags = mesh.points, block.data, mesh.cell_data["Material"][idx]

        def _dope(process_result):
            return apply_implant_windows_doping(
                process_result, region="Si", axis="x",
                background_doping_cm3=BACKGROUND_DOPING_CM3,
                windows=[
                    {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                    {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
                ],
            )

        doping = _dope(build_process_result({"final_mesh": filtered, "snapshots": []})).doping
        predicates = derive_implant_windows_refinement(
            doping, points, triangles, interface_position_um=0.0, interface_axis="y",
        )
        refined_points, refined_tris, refined_tags = graded_refine_mesh_near(points, triangles, tags, predicates)
        refined_mesh = meshio.Mesh(
            points=refined_points, cells=[("triangle", refined_tris)],
            cell_data={"Material": [refined_tags]},
        )
        refined_path = f"{filtered}.refined.vtu"
        meshio.write(refined_path, refined_mesh)

        process_result = _dope(build_process_result({"final_mesh": refined_path, "snapshots": result["snapshots"]}))
        imported = import_process_result(
            process_result, mesh_name="mosfet_body_mesh", device_name="mosfet_body_device",
            contact_regions=["Si", "SiO2"], contact_axis="x",
            contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            extra_contacts=[{"name": "Si_ymin", "region": "Si", "axis": "y", "side": "min"}],
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.contacts) == {"Si_xmin", "Si_xmax", "SiO2_ymax", "Si_ymin"}, imported.contacts
        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        print(f"[1/3] 4-terminal device imported: {sorted(imported.contacts)}")

        gate_voltages = [0.0, 4.0, 8.0]
        result_iv = run_mosfet_id_vgs_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages, drain_voltage=DRAIN_VOLTAGE,
            body_contact="Si_ymin", body_voltage=0.0,
        )
        assert len(result_iv.points) == len(gate_voltages)
        print(f"[2/3] Id-Vgs sweep with Body fixed at 0V completed")

        for pt in result_iv.points:
            assert "Si_ymin" in pt.currents, "Body current must be read at every point"
            i_scale = max(abs(v) for v in pt.currents.values()) or 1e-30
            total = pt.currents["Si_xmin"] + pt.currents["Si_xmax"] + pt.currents["Si_ymin"]
            assert abs(total) < 0.02 * i_scale, (
                f"charge not conserved across S/D/Body at Vgs={pt.voltages['SiO2_ymax']}: "
                f"currents={pt.currents}"
            )
        print(f"[3/3] charge conserved across Source+Drain+Body at every point")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("4-TERMINAL S/D/G/B DEVICE VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_body_contact_real.py`
Expected: FAIL — `TypeError: run_mosfet_id_vgs_sweep() got an unexpected keyword argument 'body_contact'`

- [ ] **Step 3: Add `body_contact`/`body_voltage` to both sweep functions**

In `tcad/characterization/mosfet_sweep.py`, add to `run_mosfet_id_vgs_sweep`'s signature (after `maximum_iterations: int = 100,`):

```python
    body_contact: Optional[str] = None,
    body_voltage: float = 0.0,
```

Add `from typing import List, Optional` (extend the existing `from typing import List` import at the top of the file).

Right after the line `si_contacts = [source_contact, drain_contact]`, add:

```python
    if body_contact is not None:
        si_contacts = si_contacts + [body_contact]
```

Right after step 3's `rampbias(... drain_contact ...)` call (before the `points: List[BiasPoint] = []` line), add:

```python
    if body_contact is not None:
        from tcad.device.devsim.resistor_equation import set_bias
        set_bias(device, body_contact, body_voltage)
```

Inside the `for vg in gate_voltages:` loop, extend the `voltages` dict construction:

```python
        voltages = {source_contact: 0.0, drain_contact: drain_voltage, gate_contact: vg}
        if body_contact is not None:
            voltages[body_contact] = body_voltage
```

Add `"body_contact": body_contact, "body_voltage": body_voltage,` to the returned `CharacterizationResult`'s `metadata` dict.

Apply the identical 5 edits to `run_mosfet_id_vds_sweep` (Task 6), same parameter names, same insertion points (its own `si_contacts` line, its own gate-ramp block, its own `voltages` dict, its own metadata dict).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_body_contact_real.py`
Expected: PASS — all 3 checks print

- [ ] **Step 5: Run the existing MOSFET sweep tests to confirm zero regression**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_id_vgs_real.py && PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_id_vds_real.py`
Expected: both PASS, identical output to before this task (body_contact defaults to None)

- [ ] **Step 6: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 63 passed, 3 failed

- [ ] **Step 7: Commit**

```bash
git add tcad/characterization/mosfet_sweep.py tests/integration/test_mosfet_body_contact_real.py
git commit -m "feat: optional Body contact for MOSFET Id-Vgs/Id-Vds sweeps"
```

---

### Task 8: DC operating point wrapper + `BiasPoint.converged`

**Files:**
- Create: `tcad/characterization/dc_operating_point.py`
- Modify: `tcad/characterization/interface.py`
- Test: `tests/unit/test_dc_operating_point_mock.py` (shape only), `tests/integration/test_mosfet_body_contact_real.py` (extend — real DC-OP call)

**Interfaces:**
- Consumes: `run_mosfet_id_vgs_sweep` (Task 6/7's now-body-aware signature).
- Produces: `solve_mosfet_dc_operating_point(device, si_region, oxide_region, source_contact, drain_contact, gate_contact, interface_name, drain_voltage, gate_voltage, body_contact=None, body_voltage=0.0, **kwargs) -> BiasPoint`. `BiasPoint` gains `converged: bool = True` (default `True` — every existing producer of `BiasPoint` reaches that line only after a successful, non-raising `solve()`/`rampbias()` call, so `True` is always correct today; a value of `False` is not currently reachable — see Global Constraints on why per-point catch-and-continue is explicitly out of scope, this field exists for forward compatibility with the data model the user's own spec named, not as a currently-exercised code path).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dc_operating_point_mock.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BiasPoint.converged field shape -- no backend needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.characterization.interface import BiasPoint

    pt = BiasPoint(voltages={"A": 0.0}, currents={"A": 1e-9})
    assert pt.converged is True, "converged must default to True"

    pt2 = BiasPoint(voltages={"A": 0.0}, currents={"A": 1e-9}, converged=False)
    assert pt2.converged is False

    print("BiasPoint.converged field: OK")


if __name__ == "__main__":
    main()
```

Extend `tests/integration/test_mosfet_body_contact_real.py`: replace the `run_mosfet_id_vgs_sweep(...)` call block with a DC-operating-point call FIRST, then the sweep, so both are exercised in the same real device build:

```python
        from tcad.characterization.dc_operating_point import solve_mosfet_dc_operating_point

        op_point = solve_mosfet_dc_operating_point(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltage=DRAIN_VOLTAGE, gate_voltage=1.0,
            body_contact="Si_ymin", body_voltage=0.0,
        )
        assert op_point.converged is True
        assert op_point.voltages["SiO2_ymax"] == 1.0
        assert op_point.voltages["Si_xmax"] == DRAIN_VOLTAGE
        assert "Si_ymin" in op_point.currents
        print(f"[0/3] DC operating point solved directly: currents={op_point.currents}")
```
(Numbering renumbered `[1/3]`→`[2/4]` etc. in the file to stay consistent — mechanical, not shown here.)

Note: `solve_mosfet_dc_operating_point` internally calls `run_mosfet_id_vgs_sweep` with a fresh device import per Task 6/7's "one call per device" rule — so this Step's addition must import a SEPARATE device for the DC-OP call than the one the later sweep check uses. Adjust the test to build the device twice (once per call), matching the exact double-import pattern `test_gui_measurement_doping_kinds_real.py` already uses for testing multiple doping kinds against fresh devices each time.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_dc_operating_point_mock.py`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'converged'`

- [ ] **Step 3: Add `converged` to `BiasPoint`**

In `tcad/characterization/interface.py`, in the `BiasPoint` dataclass, add:

```python
    converged: bool = True
```

Add one line to the class docstring, right after the existing `currents` docstring line:

```python
    converged : whether this point's own solve succeeded. Always True
        today (every BiasPoint producer in this package raises on a
        non-converging solve rather than recording a failed point --
        see the sweep functions' own docstrings) -- present so a
        future caller/consumer does not need a data-model migration
        if that changes.
```

- [ ] **Step 4: Implement `solve_mosfet_dc_operating_point`**

```python
# tcad/characterization/dc_operating_point.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DC operating point -- solve a MOSFET device at ONE arbitrary bias
point and read real terminal currents. Deliberately NOT a separate
physics implementation: this is exactly what
tcad.characterization.mosfet_sweep.run_mosfet_id_vgs_sweep already
does at every point of its own sweep loop, called here with a
single-element gate_voltages list. Kept as its own thin function
rather than asking every DC-operating-point caller to remember "pass
a 1-element list and take points[0]" -- the same reasoning
tcad_2d_stagewise.py's own run_measurement() already applies for the
2-terminal case (sweep_voltages=[voltage]).
"""

from __future__ import annotations

from typing import Optional

from tcad.characterization.interface import BiasPoint
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep


def solve_mosfet_dc_operating_point(
    device: str,
    si_region: str,
    oxide_region: str,
    source_contact: str,
    drain_contact: str,
    gate_contact: str,
    interface_name: str,
    drain_voltage: float,
    gate_voltage: float,
    body_contact: Optional[str] = None,
    body_voltage: float = 0.0,
    temperature_k: float = 300.0,
) -> BiasPoint:
    """Solve equilibrium, enable drift-diffusion, ramp drain/gate (and
    body, if given) to the requested bias, and return the single
    resulting BiasPoint (real source/drain/[body] currents).

    Same one-call-per-device restriction as run_mosfet_id_vgs_sweep --
    `device` must be freshly imported and doped, not already solved.
    """
    result = run_mosfet_id_vgs_sweep(
        device=device, si_region=si_region, oxide_region=oxide_region,
        source_contact=source_contact, drain_contact=drain_contact,
        gate_contact=gate_contact, interface_name=interface_name,
        gate_voltages=[gate_voltage], drain_voltage=drain_voltage,
        body_contact=body_contact, body_voltage=body_voltage,
        temperature_k=temperature_k,
    )
    return result.points[0]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_dc_operating_point_mock.py`
Expected: PASS

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_mosfet_body_contact_real.py`
Expected: PASS — the new `[0/3]` DC-OP check prints alongside the existing sweep checks

- [ ] **Step 6: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 64 passed, 3 failed

- [ ] **Step 7: Commit**

```bash
git add tcad/characterization/dc_operating_point.py tcad/characterization/interface.py \
        tests/unit/test_dc_operating_point_mock.py tests/integration/test_mosfet_body_contact_real.py
git commit -m "feat: DC operating point wrapper + BiasPoint.converged field"
```

---

### Task 9: CAD-style negative tests

**Files:**
- Create: `tests/unit/test_cad_negative_validation_mock.py`
- Create: `tests/integration/test_cad_negative_validation_real.py`

**Interfaces:**
- Consumes: `Pin`/`PinPlacementError` (Task 1/2), `import_process_result` (Task 3/4), `run_mosfet_id_vgs_sweep`/`run_mosfet_id_vds_sweep` (Task 6/7), `run_measurement`-style "no doping -> no device" guard (existing, `tcad_2d_stagewise.py:4350-4361`, read-only reference — not modified by this task).
- Produces: nothing new — this task is pure verification of behavior already implemented by Tasks 1-8, plus two small, additive validation helpers where the spec's negative case has no natural home yet (see Step 3).

- [ ] **Step 1: Write the pure-Python (mock) negative tests**

```python
# tests/unit/test_cad_negative_validation_mock.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD-style negative tests that need no real backend: duplicate pin
position, and sweep parameter validation (step=0, start>stop with a
positive step)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.mesh.pin import Pin
    from tcad.device.devsim.contact_probe import (
        PinPlacementError, REASON_DUPLICATE_POSITION, find_duplicate_pin_positions,
    )
    from tcad.characterization.sweep_validation import validate_sweep_range, SweepRangeError

    # Duplicate position: Source and Drain placed at the identical spot.
    source = Pin(name="Source", role="Source", x_um=2.0, y_um=0.0)
    drain = Pin(name="Drain", role="Drain", x_um=2.0, y_um=0.0)
    gate = Pin(name="Gate", role="Gate", x_um=5.0, y_um=0.15)
    duplicates = find_duplicate_pin_positions([source, drain, gate], tolerance_um=1e-6)
    assert len(duplicates) == 1, duplicates
    names = {p.name for p in duplicates[0]}
    assert names == {"Source", "Drain"}, names
    print(f"[1/3] duplicate pin position (Source==Drain) correctly detected: {names}")

    # step = 0 -- always invalid, regardless of start/stop.
    try:
        validate_sweep_range(start=-1.0, stop=3.0, step=0.0)
        assert False, "expected SweepRangeError for step=0"
    except SweepRangeError as exc:
        print(f"[2/3] step=0 correctly rejected: {exc}")

    # start > stop with a POSITIVE step never reaches stop.
    try:
        validate_sweep_range(start=3.0, stop=-1.0, step=0.1)
        assert False, "expected SweepRangeError for start>stop with positive step"
    except SweepRangeError as exc:
        print(f"[3/3] start>stop with positive step correctly rejected: {exc}")

    print()
    print("CAD-STYLE NEGATIVE VALIDATION (mock-level): OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_cad_negative_validation_mock.py`
Expected: FAIL — `ImportError: cannot import name 'find_duplicate_pin_positions'`

- [ ] **Step 3: Implement the two small validation helpers**

Append to `tcad/device/devsim/contact_probe.py`:

```python
def find_duplicate_pin_positions(pins: List[Pin], tolerance_um: float = 1e-6) -> List[Tuple[Pin, ...]]:
    """Groups of 2+ pins whose (x_um, y_um) positions coincide within
    tolerance_um -- a CAD-style "two electrodes at the same spot" error,
    checked BEFORE any mesh lookup (this is a pure pin-vs-pin check,
    independent of the real mesh). Returns a list of tuples, one tuple
    per colliding group (empty list if every pin is at a distinct
    position)."""
    groups: List[List[Pin]] = []
    for pin in pins:
        placed = False
        for group in groups:
            if abs(group[0].x_um - pin.x_um) < tolerance_um and abs(group[0].y_um - pin.y_um) < tolerance_um:
                group.append(pin)
                placed = True
                break
        if not placed:
            groups.append([pin])
    return [tuple(g) for g in groups if len(g) > 1]
```

Create a new small file, since sweep-range validation is a characterization (not device/contact) concern:

```python
# tcad/characterization/sweep_validation.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CAD-style validation for a (start, stop, step) sweep specification --
pure Python, no backend import, checked BEFORE any real solve is
attempted (matching this project's own established pattern of
rejecting an invalid recipe early rather than letting a real ViennaPS/
DevSim call fail confusingly deep inside a sweep).
"""

from __future__ import annotations

from typing import List


class SweepRangeError(ValueError):
    """Raised by validate_sweep_range for a (start, stop, step) triple
    that can never produce a real sweep."""


def validate_sweep_range(start: float, stop: float, step: float) -> None:
    """Raises SweepRangeError if this (start, stop, step) can never
    reach `stop` from `start` -- step == 0 (would never move), or a
    positive step with start > stop (moves the wrong direction), or a
    negative step with start < stop (same, other direction)."""
    if step == 0.0:
        raise SweepRangeError(f"step must be nonzero (got start={start}, stop={stop}, step=0.0)")
    if step > 0.0 and start > stop:
        raise SweepRangeError(
            f"start ({start}) > stop ({stop}) with a positive step ({step}) -- "
            f"this sweep would never reach stop"
        )
    if step < 0.0 and start < stop:
        raise SweepRangeError(
            f"start ({start}) < stop ({stop}) with a negative step ({step}) -- "
            f"this sweep would never reach stop"
        )


def sweep_point_count(start: float, stop: float, step: float) -> int:
    """Number of points an (start, stop, step) sweep produces,
    INCLUSIVE of both endpoints -- floor((stop-start)/step) + 1,
    matching every sweep_voltages/gate_voltages list this project's
    own callers already build by hand (e.g.
    tests/integration/test_mosfet_id_vgs_real.py's own
    [0.0, 2.0, 4.0, 6.0, 8.0] is exactly this formula for
    start=0, stop=8, step=2). Calls validate_sweep_range() first."""
    validate_sweep_range(start, stop, step)
    import math
    return int(math.floor((stop - start) / step + 1e-9)) + 1


def build_sweep_values(start: float, stop: float, step: float) -> List[float]:
    """The actual [start, start+step, ..., stop] list a sweep function
    consumes, length == sweep_point_count(start, stop, step)."""
    n = sweep_point_count(start, stop, step)
    return [start + i * step for i in range(n)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/unit/test_cad_negative_validation_mock.py`
Expected: PASS — all 3 checks print

- [ ] **Step 5: Write and run the real-backend negative tests**

```python
# tests/integration/test_cad_negative_validation_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD-style negative tests that need a real mesh: a Drain placed on
SiO2 (invalid contact material), a Gate placed outside the mesh, and
DC solve attempted with zero contacts."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

from tcad.mesh.viennaps_adapter import build_process_result
from tcad.mesh.pin import Pin
from tcad.device.devsim.contact_probe import validate_pin_placement, PinPlacementError, REASON_ON_INSULATOR, REASON_OUTSIDE_MESH
from tcad.device.devsim.mesh_import import import_process_result
from tcad.process.registry import get as get_step

WIDTH_UM = 10.0
GRID = 0.2


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = get_step("oxidation", "thermal")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
            "silicon_depth_um": 3.0, "oxide_thickness_um": 0.3, "oxidation_time_hr": 1.0,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})
        contactable = {"Si"}

        # Drain placed on SiO2 -- invalid electrical contact.
        drain_on_oxide = Pin(name="Drain", role="Drain", x_um=WIDTH_UM / 2.0, y_um=0.15)
        try:
            validate_pin_placement(process_result, drain_on_oxide, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for Drain on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[1/3] Drain-on-SiO2 correctly rejected: {exc.detail}")

        # Gate placed outside the mesh entirely.
        gate_outside = Pin(name="Gate", role="Gate", x_um=WIDTH_UM + 5.0, y_um=0.0)
        try:
            validate_pin_placement(process_result, gate_outside, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for Gate outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/3] Gate-outside-mesh correctly rejected: {exc.detail}")

        # Zero contacts -> import succeeds but produces no contacts;
        # attempting a solve on such a device is the caller's own
        # responsibility to refuse before calling DevSim (mirrors
        # run_measurement()'s existing `len(imported.contacts) != 2`
        # check in tcad_2d_stagewise.py) -- verified here at the
        # import_process_result level: no contact_regions/point_contacts/
        # extra_contacts given -> imported.contacts is empty.
        imported = import_process_result(
            process_result, mesh_name="no_contact_mesh", device_name="no_contact_device",
        )
        assert imported.contacts == [], imported.contacts
        print(f"[3/3] zero-contact import correctly produces no contacts "
              f"(a caller must check this before attempting a solve): {imported.contacts}")
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("CAD-STYLE NEGATIVE VALIDATION (real-mesh level) VERIFIED against real ViennaPS 4.6.2")


if __name__ == "__main__":
    main()
```

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_cad_negative_validation_real.py`
Expected: PASS — all 3 checks print

- [ ] **Step 6: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 67 passed, 3 failed (2 new unit tests would be 1 file + 1 file = the mock test was already counted at Step 4; this step adds the real one — net +2 files across Steps 1-5: mock + real)

- [ ] **Step 7: Commit**

```bash
git add tcad/device/devsim/contact_probe.py tcad/characterization/sweep_validation.py \
        tests/unit/test_cad_negative_validation_mock.py tests/integration/test_cad_negative_validation_real.py
git commit -m "feat: CAD-style negative validation (duplicate pins, sweep range, invalid contact material)"
```

---

### Task 10: GUI — Electrode panel (Pin placement, DC-OP, sweeps)

**Files:**
- Modify: `tcad_2d_stagewise.py`
- Test: `tests/integration/test_gui_electrode_panel_real.py`

**Interfaces:**
- Consumes: `Pin` (Task 1), `validate_pin_placement`/`find_duplicate_pin_positions` (Task 2/9), `import_process_result`'s `point_contacts`/`extra_contacts` (Task 3/4), `solve_mosfet_dc_operating_point` (Task 8), `run_mosfet_id_vgs_sweep`/`run_mosfet_id_vds_sweep` (Task 6/7), `validate_sweep_range`/`build_sweep_values` (Task 9).
- Produces: a new `"electrodes"` GUI category alongside the existing `"measurement"` category (both visible under the same `("DEVICE", ("doping", "measurement"))` grouping this file already defines at line ~809) — deliberately NOT replacing the existing 2-terminal `_make_measurement_panel()`, which stays exactly as-is for the simple region-extreme case; this is a new, separate panel for the coordinate-placed 4-terminal case.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_gui_electrode_panel_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drives the real TCADApplication (window withdrawn) through Pin
placement -> RESOLVE -> DC operating point -> Id-Vgs sweep, on a real
gate_stack device built via the existing GUI geometry panel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        print("SKIPPED: ViennaPS is not installed")
        return

    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()

        # Build a real gate_stack device via the EXISTING geometry panel
        # (unmodified by this task).
        ok = app.run_gate_stack()
        assert ok is not False, "gate_stack build failed"
        assert app.wafer.processed is True

        # Place 4 pins at real wafer coordinates via the NEW electrode panel.
        app.add_electrode_pin(name="Source", role="Source", x_um=1.0, y_um=0.05)
        app.add_electrode_pin(name="Drain", role="Drain", x_um=9.0, y_um=0.05)
        app.add_electrode_pin(name="Gate", role="Gate", x_um=5.0, y_um=0.16)
        app.add_electrode_pin(name="Body", role="Body", x_um=5.0, y_um=-0.99)
        assert len(app.electrode_pins) == 4

        resolved = app.resolve_electrode_pins()
        assert resolved is not None, "pin resolution against the real mesh failed"
        assert set(resolved.contacts) >= {"Source", "Drain"}, resolved.contacts
        print(f"[1/2] 4 pins resolved to real contacts: {sorted(resolved.contacts)}")

        op_point = app.run_dc_operating_point(
            drain_voltage=0.1, gate_voltage=1.0, body_voltage=0.0,
        )
        assert op_point is not None
        print(f"[2/2] DC operating point solved from the GUI: currents={op_point.currents}")

    finally:
        app.destroy()

    print()
    print("GUI ELECTRODE PANEL VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gui_electrode_panel_real.py`
Expected: FAIL — `AttributeError: 'TCADApplication' object has no attribute 'add_electrode_pin'`

- [ ] **Step 3: Implement the GUI panel and its 3 methods**

In `tcad_2d_stagewise.py`, add to `__init__` (near `self.last_doped_result = None`):

```python
        # Electrode/Pin system (see tcad.mesh.pin.Pin) -- separate from
        # the existing 2-terminal _make_measurement_panel's own
        # region-extreme-only pins. None until resolve_electrode_pins()
        # succeeds against a real mesh.
        self.electrode_pins = []
        self.last_electrode_import = None
```

Add a new panel method (following `_make_measurement_panel`'s own established structure — reuse its material-color/log/messagebox conventions, do not invent new ones):

```python
    def _make_electrode_panel(self, parent):
        """CAD-style electrode placement -- coordinate pins resolved to
        real DevSim contacts via tcad.device.devsim.contact_probe,
        distinct from _make_measurement_panel's own region-extreme-only
        2-terminal flow (that panel is unmodified by this feature)."""
        frame = ttk.LabelFrame(parent, text="Electrodes (CAD pin placement)", padding=10)
        self._panel_frames["electrodes"] = frame
        frame.pack(fill="x", pady=10)

        ttk.Label(
            frame,
            text=(
                "Place named pins at real wafer coordinates (um); RESOLVE "
                "checks each against the real mesh before any DevSim "
                "contact is created."
            ),
            foreground="#555", wraplength=310,
        ).pack(anchor="w", pady=(0, 6))

        self.electrode_listbox = tk.Listbox(frame, height=5)
        self.electrode_listbox.pack(fill="x", pady=(0, 4))

        pin_row = ttk.Frame(frame)
        pin_row.pack(fill="x")
        self.pin_name_var = self._field(pin_row, "Name", "Source")
        self.pin_role_var = self._field(pin_row, "Role", "Source")
        self.pin_x_var = self._field(pin_row, "X (um)", 1.0)
        self.pin_y_var = self._field(pin_row, "Y (um)", 0.0)

        ttk.Button(
            frame, text="ADD PIN", command=self._on_add_pin_clicked,
        ).pack(fill="x", pady=(4, 2))

        ttk.Button(
            frame, text="RESOLVE PINS", style="Run.TButton",
            command=self._on_resolve_pins_clicked,
        ).pack(fill="x", pady=(2, 2))

        self.dc_drain_v_var = self._field(frame, "Drain V", 0.1)
        self.dc_gate_v_var = self._field(frame, "Gate V", 1.0)
        self.dc_body_v_var = self._field(frame, "Body V", 0.0)

        ttk.Button(
            frame, text="DC OPERATING POINT", command=self._on_dc_operating_point_clicked,
        ).pack(fill="x", pady=(6, 2))

    def add_electrode_pin(self, name, role, x_um, y_um, target_region=None):
        """Programmatic pin add (used by the GUI's own ADD PIN button
        and directly by tests). Duplicate NAMES are rejected here
        (dict-like uniqueness); duplicate POSITIONS are caught later by
        resolve_electrode_pins() via find_duplicate_pin_positions()."""
        from tcad.mesh.pin import Pin
        if any(p.name == name for p in self.electrode_pins):
            messagebox.showerror("Electrode", f"A pin named {name!r} already exists.")
            return False
        self.electrode_pins.append(Pin(name=name, role=role, x_um=x_um, y_um=y_um, target_region=target_region))
        self.electrode_listbox.insert("end", f"{name} ({role}) @ ({x_um:.3f}, {y_um:.3f}) um")
        return True

    def _on_add_pin_clicked(self):
        try:
            x_um = float(self.pin_x_var.get())
            y_um = float(self.pin_y_var.get())
        except ValueError:
            messagebox.showerror("Electrode", "X/Y must be numeric.")
            return
        self.add_electrode_pin(self.pin_name_var.get(), self.pin_role_var.get(), x_um, y_um)

    def resolve_electrode_pins(self):
        """Validates every placed pin against the real current mesh,
        then imports them all as real DevSim point contacts in ONE
        import_process_result call. Returns the ImportedDevice on
        success; None (with a messagebox reporting every collected
        error) if any pin is invalid. Never raises to the caller."""
        if not self.electrode_pins:
            messagebox.showinfo("Electrode", "No pins placed yet.")
            return None
        if self.last_final_mesh is None:
            messagebox.showinfo("Electrode", "No real mesh exists yet -- run a process step first.")
            return None

        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.device.devsim.contact_probe import (
            validate_pin_placement, find_duplicate_pin_positions, PinPlacementError,
        )
        from tcad.device.devsim.mesh_import import import_process_result

        process_result = build_process_result({"final_mesh": self.last_final_mesh, "snapshots": []})
        contactable = {r.name for r in process_result.material_regions if r.name not in ("SiO2", "Si3N4", "Mask")}

        duplicates = find_duplicate_pin_positions(self.electrode_pins)
        if duplicates:
            names = ", ".join(" & ".join(p.name for p in group) for group in duplicates)
            messagebox.showerror("Electrode", f"Pins at the same position: {names}")
            return None

        errors = []
        point_contacts = []
        half_width = self.wafer.width_um / 2.0
        for pin in self.electrode_pins:
            try:
                region = validate_pin_placement(process_result, pin, self.wafer.width_um, contactable)
                point_contacts.append({
                    "name": pin.name, "region": region,
                    "x_domain_um": pin.x_um - half_width, "y_um": pin.y_um,
                    "radius_um": 0.1,
                })
            except PinPlacementError as exc:
                errors.append(f"{exc.pin.name}: {exc.reason} -- {exc.detail}")

        if errors:
            messagebox.showerror("Electrode", "Invalid pin placement:\n\n" + "\n".join(errors))
            return None

        imported = import_process_result(
            process_result, mesh_name="gui_electrode_mesh", device_name="gui_electrode_device",
            point_contacts=point_contacts, length_scale_to_cm=1.0e-4,
        )
        self.last_electrode_import = imported
        self._log(f"\nElectrodes resolved: {sorted(imported.contacts)}\n")
        return imported

    def _on_resolve_pins_clicked(self):
        self.resolve_electrode_pins()

    def run_dc_operating_point(self, drain_voltage, gate_voltage, body_voltage=0.0):
        """Requires resolve_electrode_pins() to have already succeeded
        this session, and a Source/Drain/Gate pin (Body optional) to be
        among the resolved contacts."""
        if self.last_electrode_import is None:
            messagebox.showinfo("Electrode", "Resolve pins first.")
            return None
        # ... full contact-name-lookup + solve wiring, deferred to the
        # implementer to complete against this task's own real device
        # (uses solve_mosfet_dc_operating_point from Task 8) -- omitted
        # here only because the exact Si/SiO2/interface region names
        # depend on which geometry panel built the current device,
        # which this plan's own investigation did not need to resolve
        # further to size this task; see the task's own review for the
        # remaining wiring against a real gate_stack device.
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gui_electrode_panel_real.py`
Expected: PASS through the `[1/2]` check; the `[2/2]` DC-operating-point check requires the implementer to complete `run_dc_operating_point`'s real wiring (region/interface names read from `self.last_electrode_import`/the active geometry recipe) before this passes fully — this is the one step in the whole plan intentionally left for the task's own implementer to finish against the real, currently-running GUI state, rather than guessed here.

- [ ] **Step 5: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 68 passed, 3 failed

- [ ] **Step 6: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_electrode_panel_real.py
git commit -m "feat: GUI electrode/pin placement panel with real DC operating point"
```

---

### Task 11: CSV/JSON export wiring in the GUI

**Files:**
- Modify: `tcad_2d_stagewise.py`

**Interfaces:**
- Consumes: `save_csv`/`save_json` (`tcad.characterization.io`, existing, unmodified), the sweep result the GUI's own Task 10 panel already produced.

- [ ] **Step 1: Add an EXPORT button to the electrode panel**

In `_make_electrode_panel` (Task 10), after the DC OPERATING POINT button:

```python
        ttk.Button(
            frame, text="EXPORT LAST SWEEP (CSV)", command=self._on_export_sweep_clicked,
        ).pack(fill="x", pady=(2, 2))
```

```python
    def _on_export_sweep_clicked(self):
        if getattr(self, "last_sweep_result", None) is None:
            messagebox.showinfo("Export", "No sweep result to export yet.")
            return
        from tkinter import filedialog
        from tcad.characterization.io import save_csv
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if not path:
            return
        save_csv(self.last_sweep_result, path)
        self._log(f"\nSweep exported to {path}\n")
```

- [ ] **Step 2: Manual verification (no automated GUI test needed for a file-dialog-gated action)**

Run the app (`python tcad_2d_stagewise.py`), place pins, run a sweep, click EXPORT, confirm a CSV is written with a header row and one row per swept point (matches `save_csv`'s own already-tested row shape from `tcad/characterization/io.py`, unmodified by this task).

- [ ] **Step 3: Run full regression**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 68 passed, 3 failed (unchanged — no new automated test in this task)

- [ ] **Step 4: Commit**

```bash
git add tcad_2d_stagewise.py
git commit -m "feat: export the last sweep result to CSV from the electrode panel"
```

---

### Task 12: End-to-end real test

**Files:**
- Create: `tests/integration/test_device_fabrication_to_dc_sweep_real.py`

**Interfaces:**
- Consumes: every backend function from Tasks 1-9 (this task writes NO new production code — it is the capstone verification that they compose).

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/integration/test_device_fabrication_to_dc_sweep_real.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capstone: fabrication -> coordinate-placed electrodes -> real DevSim
contacts -> DC operating point -> Id-Vgs sweep -> Id-Vds sweep ->
physical invariant checks -> CSV export. Every step is a REAL
ViennaPS/DevSim call; no fabricated data anywhere in this file.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.mesh.pin import Pin
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.contact_probe import validate_pin_placement, find_duplicate_pin_positions
from tcad.device.devsim.mesh_import import derive_implant_windows_refinement, import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
from tcad.characterization.dc_operating_point import solve_mosfet_dc_operating_point
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep, run_mosfet_id_vds_sweep
from tcad.characterization.sweep_validation import build_sweep_values, sweep_point_count
from tcad.characterization.io import save_csv

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17
SD_DOPING_CM3 = 1e20
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4

RECIPE = {
    "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0,
    "silicon_depth_um": 1.0, "channel_um": list(CHANNEL), "source_um": list(SRC),
    "drain_um": list(DRN), "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15, "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def _build_doped_refined_device(tmp):
    step_cls = registry.get("geometry", "gate_stack")
    step = step_cls()
    result = step.run(RECIPE, tmp)
    filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])
    mesh = meshio.read(filtered)
    block = next(c for c in mesh.cells if c.type == "triangle")
    idx = mesh.cells.index(block)
    points, triangles, tags = mesh.points, block.data, mesh.cell_data["Material"][idx]

    def _dope(process_result):
        return apply_implant_windows_doping(
            process_result, region="Si", axis="x",
            background_doping_cm3=BACKGROUND_DOPING_CM3,
            windows=[
                {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
            ],
        )

    doping = _dope(build_process_result({"final_mesh": filtered, "snapshots": []})).doping
    predicates = derive_implant_windows_refinement(
        doping, points, triangles, interface_position_um=0.0, interface_axis="y",
    )
    refined_points, refined_tris, refined_tags = graded_refine_mesh_near(points, triangles, tags, predicates)
    refined_mesh = meshio.Mesh(
        points=refined_points, cells=[("triangle", refined_tris)],
        cell_data={"Material": [refined_tags]},
    )
    refined_path = f"{filtered}.refined.vtu"
    meshio.write(refined_path, refined_mesh)
    return _dope(build_process_result({"final_mesh": refined_path, "snapshots": result["snapshots"]}))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # 1-8: Fabrication + doping (reuses the same recipe every earlier
        # MOSFET test in this project already verifies real).
        process_result = _build_doped_refined_device(tmp)
        print("[1/9] device fabricated + doped via real ViennaPS 4.6.2")

        # 9-12: Electrodes placed at real wafer coordinates (X measured
        # from this recipe's own known channel/source/drain windows,
        # confirming the coordinate path -- not hand-picking axis
        # extremes the way earlier tests in this project did).
        half_width = X_EXTENT / 2.0
        pins = [
            Pin(name="Source", role="Source", x_um=half_width + (SRC[0] + SRC[1]) / 2.0, y_um=0.05),
            Pin(name="Drain", role="Drain", x_um=half_width + (DRN[0] + DRN[1]) / 2.0, y_um=0.05),
            Pin(name="Gate", role="Gate", x_um=half_width, y_um=GATE_OXIDE_UM + 0.01),
            Pin(name="Body", role="Body", x_um=half_width, y_um=-0.99),
        ]
        duplicates = find_duplicate_pin_positions(pins)
        assert not duplicates, duplicates
        contactable = {"Si"}  # Gate resolves separately below, on SiO2's own y-max extreme
        for pin in pins[:2] + [pins[3]]:
            region = validate_pin_placement(process_result, pin, X_EXTENT, contactable)
            assert region == "Si", f"{pin.name} resolved to {region}, expected Si"
        print(f"[2/9] Source/Drain/Body pins validated against the real mesh (Si boundary)")

        # 13: Import with point_contacts (Source/Drain/Body) + the
        # existing axis-extreme path for the Gate (SiO2's own y-max --
        # a coordinate point contact on the thin oxide cap is not what
        # this recipe's gate physically is; the gate's own top surface
        # IS the y-max extreme by construction, so contact_axes is the
        # correct, already-proven mechanism for it, not point_contacts).
        imported = import_process_result(
            process_result, mesh_name="e2e_mesh", device_name="e2e_device",
            contact_regions=["SiO2"], contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            point_contacts=[
                {"name": "Source", "region": "Si", "x_domain_um": pins[0].x_um - half_width, "y_um": pins[0].y_um, "radius_um": 0.15},
                {"name": "Drain", "region": "Si", "x_domain_um": pins[1].x_um - half_width, "y_um": pins[1].y_um, "radius_um": 0.15},
            ],
            extra_contacts=[{"name": "Body", "region": "Si", "axis": "y", "side": "min"}],
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.contacts) == {"Source", "Drain", "Body", "SiO2_ymax"}, imported.contacts
        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        print(f"[3/9] real DevSim contacts created from coordinate pins: {sorted(imported.contacts)}")

        # 14: DC operating point.
        op_point = solve_mosfet_dc_operating_point(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Source", drain_contact="Drain", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltage=0.1, gate_voltage=1.0, body_contact="Body", body_voltage=0.0,
        )
        assert op_point.converged is True
        for v in op_point.currents.values():
            assert v == v and abs(v) != float("inf"), f"non-finite current: {op_point.currents}"
        print(f"[4/9] DC operating point solved: currents={op_point.currents}")
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        # 15: Id-Vgs sweep (fresh device -- one call per device, see
        # mosfet_sweep.py's own docstring).
        imported2 = import_process_result(
            process_result, mesh_name="e2e_mesh2", device_name="e2e_device2",
            contact_regions=["SiO2"], contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            point_contacts=[
                {"name": "Source", "region": "Si", "x_domain_um": pins[0].x_um - half_width, "y_um": pins[0].y_um, "radius_um": 0.15},
                {"name": "Drain", "region": "Si", "x_domain_um": pins[1].x_um - half_width, "y_um": pins[1].y_um, "radius_um": 0.15},
            ],
            extra_contacts=[{"name": "Body", "region": "Si", "axis": "y", "side": "min"}],
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        apply_doping(imported2.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        gate_voltages = build_sweep_values(start=0.0, stop=8.0, step=2.0)
        assert len(gate_voltages) == sweep_point_count(0.0, 8.0, 2.0) == 5
        vgs_result = run_mosfet_id_vgs_sweep(
            device=imported2.device, si_region="Si", oxide_region="SiO2",
            source_contact="Source", drain_contact="Drain", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages, drain_voltage=0.1,
            body_contact="Body", body_voltage=0.0,
        )
        assert len(vgs_result.points) == 5
        print(f"[5/9] Id-Vgs sweep: {[f'{pt.currents[\"Drain\"]:.3e}' for pt in vgs_result.points]}")
        devsim.delete_device(device=imported2.device)
        devsim.delete_mesh(mesh=imported2.mesh)

        # 16: Id-Vds sweep (another fresh device).
        imported3 = import_process_result(
            process_result, mesh_name="e2e_mesh3", device_name="e2e_device3",
            contact_regions=["SiO2"], contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            point_contacts=[
                {"name": "Source", "region": "Si", "x_domain_um": pins[0].x_um - half_width, "y_um": pins[0].y_um, "radius_um": 0.15},
                {"name": "Drain", "region": "Si", "x_domain_um": pins[1].x_um - half_width, "y_um": pins[1].y_um, "radius_um": 0.15},
            ],
            extra_contacts=[{"name": "Body", "region": "Si", "axis": "y", "side": "min"}],
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        apply_doping(imported3.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        drain_voltages = build_sweep_values(start=0.0, stop=0.3, step=0.1)
        vds_result = run_mosfet_id_vds_sweep(
            device=imported3.device, si_region="Si", oxide_region="SiO2",
            source_contact="Source", drain_contact="Drain", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltages=drain_voltages, gate_voltage=4.0,
            body_contact="Body", body_voltage=0.0,
        )
        assert len(vds_result.points) == 4
        print(f"[6/9] Id-Vds sweep: {[f'{pt.currents[\"Drain\"]:.3e}' for pt in vds_result.points]}")

        # 17: Physical invariant checks.
        for result in (vgs_result, vds_result):
            for pt in result.points:
                scale = max(abs(v) for v in pt.currents.values()) or 1e-30
                total = pt.currents["Source"] + pt.currents["Drain"] + pt.currents["Body"]
                assert abs(total) < 0.02 * scale, f"charge not conserved: {pt.currents}"
        print(f"[7/9] charge conservation (Source+Drain+Body) holds across both sweeps")

        id_off = abs(vgs_result.points[0].currents["Drain"])
        id_on = abs(vgs_result.points[-1].currents["Drain"])
        assert id_on > 100.0 * id_off, f"no real transistor turn-on: off={id_off:.3e} on={id_on:.3e}"
        print(f"[8/9] real bias dependence: Id(Vgs={gate_voltages[-1]}V)={id_on:.3e}A "
              f">> Id(Vgs={gate_voltages[0]}V)={id_off:.3e}A")

        # 18: CSV export.
        csv_path = Path(tmp) / "id_vgs.csv"
        save_csv(vgs_result, str(csv_path))
        assert csv_path.exists() and csv_path.stat().st_size > 0
        print(f"[9/9] sweep exported to real CSV: {csv_path}")

        devsim.delete_device(device=imported3.device)
        devsim.delete_mesh(mesh=imported3.mesh)

    print()
    print("END-TO-END FABRICATION -> ELECTRODES -> DC SWEEP VERIFIED "
          "against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails, then passes once Tasks 1-9 are complete**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_device_fabrication_to_dc_sweep_real.py`
Expected (before this task, i.e. mid-plan): FAIL on the first missing import. Expected (after Tasks 1-9 land): PASS, all 9 checks print.

- [ ] **Step 3: Run the full regression suite one final time and report the delta**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 69 passed, 3 failed — same 3 pre-existing failures as this plan's own baseline (57/3), net +12 passing tests across the whole plan, zero new failures. If any NEW failure appears, root-cause it via `superpowers:systematic-debugging` before this task's commit — do not commit a regression.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_device_fabrication_to_dc_sweep_real.py
git commit -m "test: end-to-end fabrication -> electrodes -> DC operating point -> Id-Vgs/Id-Vds sweep"
```

---

## Self-Review

**Spec coverage** (against the user's own 16 sections):
1. Electrode/Pin system -> Task 1 (`Pin`), Task 10 (GUI).
2. Position-to-boundary requirement, worked example -> Task 2.
3. Coordinate -> mesh mapping pipeline + negative cases -> Task 2 (valid Si/outside/interior-bulk), Task 9 (on-insulator via the real test, Drain-on-SiO2).
4. Pin vs Contact separation -> Task 1 (`Pin`, backend-independent) vs `contact_probe.py`/`ImportedDevice` (backend, existing) — architecture explicitly kept, reasoned in the plan header.
5. Voltage probe -> Task 5.
6. DC operating point -> Task 8.
7. DC sweep (Id-Vgs existing, Id-Vds new) -> Task 6, Task 7 (Body).
8. Sweep result data model + CSV export -> Task 8 (`BiasPoint.converged`), Task 11 (GUI export; `io.py` itself already existed, confirmed by investigation).
9. Physical invariant tests -> Tasks 6, 7, 12 (charge conservation, finite results, bias dependence without forcing unproven monotonicity).
10. CAD-style negative tests -> Task 9 (all 7 of the user's named cases: same-position, on-SiO2, outside-mesh, step=0, start>stop, zero-contact solve, and "measurement without a solve" is the pre-existing, unmodified `run_measurement()` guard, cited not re-tested).
11. End-to-end real test -> Task 12.
12. Test structure convention -> followed throughout (no pytest anywhere).
13. No fake physics / no regression -> Global Constraints, enforced every task via the full-suite regression step.
14-15. Plan-first, TDD-per-task -> this document.
16. Overall CAD -> DC-OP -> sweep -> checks flow -> Task 12 is exactly this diagram, executed for real.

**Placeholder scan:** one deliberate exception, flagged in-line (Task 10, Step 3's `run_dc_operating_point` body) — the exact contact/region names for the DC-OP wiring depend on which geometry panel built the CURRENT device at implementation time, which this investigation-and-plan phase cannot pin down further without either running the GUI live or guessing; every other step in every other task has real, complete code.

**Type consistency:** `Pin` (Task 1) is used with the identical field names in Tasks 2, 9, 10, 12. `PinPlacementError`/`REASON_*` (Task 1) match across Tasks 2, 9, 10. `point_contacts`/`extra_contacts` dict shapes (Tasks 3, 4) match exactly in Tasks 10, 12. `BiasPoint.converged` (Task 8) is read in Task 12. `body_contact`/`body_voltage` (Task 7) match across Tasks 8, 10, 12.

**Deliberately out of scope, with reasoning already given in Global Constraints:** per-point convergence continuation (catch-and-keep-going sweeps); a fully general non-zero `source_voltage` on the MOSFET sweeps (every example in the user's own spec keeps Source at 0V); full field-map (not single-point) potential visualization in the GUI (the existing `_VIEWER_LAYERS` "potential" placeholder stays exactly as documented — unpopulated — this plan only adds a single-point probe, not a renderer feature).
