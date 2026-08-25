# Litho/Doping/Renderer Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four independently-verified GUI/physics gaps in the TCAD project — SiO2 doesn't block doping, litho placeholder visuals disappear once any real mesh exists, Oxidation→PR→Etch gives no feedback about whether the target material was reached, and doping only accepts a single net concentration instead of independent donor/acceptor — without touching the WaferState → resolve() → ResolvedRecipe → ViennaPS architecture.

**Architecture:** Each of the 4 problems lives in a different layer (doping.py's model, the GUI renderer's gating logic, the etch success-log path, and doping.py's input surface) and is fixed independently in that layer. No task modifies `tcad/physics/resolve.py`, `tcad/physics/wafer_state.py`, or `tcad/physics/intent.py` — confirmed during investigation that none of the four problems touch the resolver (doping never goes through WaferState at all; the etch path's `resolve()` call only populates report-only metadata).

**Tech Stack:** Python 3.13, ViennaPS 4.6.2, DevSim 2.x, tkinter (GUI), meshio (mesh introspection). No pytest — see Global Constraints.

**Spec:** This plan implements the findings from the investigation delivered in-conversation (no separate spec file); the investigation itself is preserved in this session's transcript and in `docs/investigation_log.md` once Task 0 records it.

## Global Constraints

- **Test runner is NOT pytest.** This project's convention: every test is a standalone script with `def main(): ...` + `if __name__ == "__main__": main()`, using plain `assert`, discovered by `tests/run_regression.py` via `glob("test_*.py")` under `tests/unit/` (Tk-only, no ViennaPS/DevSim, `_mock.py` suffix) and `tests/integration/` (`_real.py` suffix, needs real ViennaPS/DevSim, asserted with `assert session.is_available()` at import time). Run the full suite with `PYTHONIOENCODING=utf-8 python tests/run_regression.py` (Windows cp949 console truncates tracebacks otherwise).
- **Baseline regression: 49 passed, 3 pre-existing failures** — `test_device_lifecycle_repeat_real.py`, `test_gui_measurement_doping_kinds_real.py`, `test_robust_iv_sweep_real.py` (all DevSim convergence-noise issues, unrelated to this work). Any NEW failure beyond these three is a regression and must be fixed before the task is considered done.
- **Do not modify** `tcad/physics/resolve.py`, `tcad/physics/wafer_state.py`, `tcad/physics/intent.py`, `tcad/physics/tables.py`, `tcad/physics/values.py`. `resolve(intent, state, user_supplied=None)` must keep its history-free signature.
- **No fake physics parameters.** Confirmed by direct introspection of the installed ViennaPS 4.6.2 (`dir(vps)`) and DevSim: neither has any ion-implant or dopant-diffusion model. `IonBeamEtching`/`IBEParameters.meanEnergy` governs sputter-etch yield, not implant depth — never repurpose it as "implant energy." Do not add implant energy/dose/beam-voltage/diffusion-time/temperature fields to the GUI in this plan (see Task Group 4's explicit scope exclusion).
- **One task = one commit.** Run the real regression suite after every task; report the delta against the 49/3 baseline, not just "passed/failed."
- Every fix must be checked at BOTH levels, never conflated: (a) real ViennaPS/DevSim domain/mesh state (via meshio or `.vpsd` independent copies), and (b) what the GUI actually renders/logs. A task is not done until both are verified.

---

## File Structure

| File | Responsibility | Task Group |
|---|---|---|
| `tcad/device/devsim/mesh_import.py` | NEW `derive_barrier_covered_windows()` — real-mesh-derived x-ranges where a barrier material covers the doped region | 1 |
| `tcad/device/devsim/doping_mapping.py` | `apply_doping()` gains optional `exclude_windows` param, wraps NetDoping in a mask expression | 1 |
| `tcad_2d_stagewise.py` | Doping barrier GUI wiring; `_material_surface_profile()` (new, pure) + doping-tint renderer fix; `real_mesh_available` litho-pending gate; `_MATERIAL_COLORS["PHS"]`; `_log_etch_material_summary()` (new); doping panel donor/acceptor fields for Gaussian/Implant Windows | 1, 2, 3, 4 |
| `tcad/mesh/interface.py` | `DopingRegion` gains `donor_peak_conc_cm3`, `acceptor_peak_conc_cm3`, `donor_species`, `acceptor_species` (all optional, backward compatible) | 4 |
| `tcad/physics/doping.py` | `apply_uniform_doping`, `apply_gaussian_implant_doping`, `apply_implant_windows_doping` gain optional donor/acceptor keyword params; `apply_step_junction_doping` unchanged (already correct) | 4 |
| `tests/integration/test_doping_barrier_windows_real.py` | NEW — pins SiO2 barrier exclusion at the DevSim/mesh level | 1 |
| `tests/integration/test_doping_overlay_surface_profile_real.py` | NEW — pins the renderer's per-x surface profile against real mesh data | 1 |
| `tests/integration/test_gui_litho_placeholder_visibility_real.py` | NEW — pins the `real_mesh_available` gate fix | 2 |
| `tests/integration/test_oxidation_pr_etch_reaches_si_real.py` | NEW — pins insufficient-budget (Si untouched) vs sufficient-budget (Si genuinely removed, PR-protected area intact) | 3 |
| `tests/integration/test_doping_donor_acceptor_all_kinds_real.py` | NEW — pins donor/acceptor input + net computation for all 4 kinds | 4 |

---

## Task Group 1: SiO2 doping barrier

**원인**: `tcad/physics/doping.py`'s `DopingRegion` has no concept of "what material sits above this point" — a doped region's concentration is uniform (or a pure function of x/y position) regardless of whether SiO2 covers it. DevSim's own region isolation is already correct (SiO2 never receives `NetDoping`) — the gap is that Si UNDER SiO2 gets the identical dose as exposed Si. Independently, `tcad_2d_stagewise.py`'s `_draw_real_mesh_result()` draws the doping color tint using the GLOBAL min/max y of the doped material across the WHOLE mesh, not the real per-x surface — confirmed to over-paint ~1um above the true surface in a trench test case.

**수정 파일**: `tcad/device/devsim/mesh_import.py` (new function), `tcad/device/devsim/doping_mapping.py` (`apply_doping`), `tcad_2d_stagewise.py` (`run_measurement`, `_draw_real_mesh_result`, new `_material_surface_profile`, `_make_doping_panel`).

**수정 함수**: `derive_barrier_covered_windows()` (new), `apply_doping()` (extended, backward compatible), `run_measurement()` (wire barrier exclusion in), `_material_surface_profile()` (new, pure/testable), `_draw_real_mesh_result()` (doping-tint loop rewritten to use per-x segments).

**테스트**: `tests/integration/test_doping_barrier_windows_real.py` (DevSim-level: NetDoping is genuinely zero under sufficient SiO2, nonzero in the open window), `tests/integration/test_doping_overlay_surface_profile_real.py` (renderer-level: `_material_surface_profile()` never returns a segment whose y_top exceeds the real local surface by more than one grid cell).

**회귀 위험**: LOW for `apply_doping()` (new param is optional, default `None`, every existing call site — `pn_junction_iv_sweep.py`, `robust_iv_sweep.py`, `test_phase7/8_*_real.py`, this session's `test_gui_doping_donor_acceptor_real.py` — passes it unset and is byte-identical). LOW-MEDIUM for the renderer rewrite (visual-only, no return value consumed elsewhere, but replaces the single-rectangle draw with a multi-segment loop — verify no perf regression on typical mesh sizes ~1-15k nodes, well within Tk canvas's normal draw budget). MEDIUM for the GUI wiring in `run_measurement()` (touches the doping/measurement path all 4 kinds share — must re-run `test_gui_doping_donor_acceptor_real.py` and `test_gui_measurement_doping_kinds_real.py`, the latter already a pre-existing-fail baseline so watch that it doesn't fail for a NEW reason).

### Task 1: `derive_barrier_covered_windows()` + real regression test

**Files:**
- Modify: `tcad/device/devsim/mesh_import.py`
- Test: Create `tests/integration/test_doping_barrier_windows_real.py`

**Interfaces:**
- Produces: `derive_barrier_covered_windows(volume_mesh_path: str, doped_region: str, barrier_material: str, axis: str = "x", min_barrier_thickness_um: float = 0.0, bucket_width_um: Optional[float] = None) -> List[Dict[str, float]]` — returns `[{"min_um": float, "max_um": float}, ...]` in the same coordinate convention as `mask_spans_um`/`implant_windows`.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
derive_barrier_covered_windows() must find the real x-range where SiO2
covers Si with real ViennaPS geometry (blanket oxidation -> litho
developed -> selective SiO2 etch through the opening), not assume it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps import session
from tcad.device.devsim.mesh_import import derive_barrier_covered_windows

assert session.is_available(), "ViennaPS must be installed for this test"

WIDTH = 10.0
HALF = WIDTH / 2.0

BASE = dict(grid_delta_um=0.1, x_extent_um=WIDTH, y_extent_um=8.0,
            silicon_depth_um=5.0, pr_thickness_um=0.5)


def main():
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [],
        "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 1.0,
    }
    etch = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        **BASE,
        "remask_spans_um": [[-HALF, -1.5], [1.5, HALF]],
        "mask_material": "PHS",
        "material_rates": {"SiO2": -0.3, "Si": 0.0, "PHS": 0.0},
        "default_rate": 0.0, "etch_time_s": 1.0,
    }
    tmp1 = tempfile.mkdtemp(prefix="tbw_ox_")
    ox_result = registry.get("oxidation", "thermal")().run(oxidation, tmp1)

    tmp2 = tempfile.mkdtemp(prefix="tbw_etch_")
    etch_step = registry.get("etching", "isotropic")()
    etch_domain = session.load_domain_state(ox_result["domain_state"])
    etch_step._inherited_domain = etch_domain
    etch_result = etch_step.run(etch, tmp2)

    windows = derive_barrier_covered_windows(
        etch_result["final_mesh"], doped_region="Si",
        barrier_material="SiO2", axis="x", min_barrier_thickness_um=0.01,
    )
    print("Barrier-covered windows:", windows)

    # The open window (etched clear of SiO2) must NOT be covered.
    for w in windows:
        assert not (w["min_um"] < 0.0 < w["max_um"]), (
            f"the open window (x=0, SiO2 etched away) must not be marked "
            f"barrier-covered: {windows}")

    # The protected region (x=-4, SiO2 intact) MUST be covered.
    assert any(w["min_um"] <= -4.0 <= w["max_um"] for w in windows), (
        f"the SiO2-protected region (x=-4) must be marked barrier-covered: "
        f"{windows}")

    print("derive_barrier_covered_windows() correctly separates the "
          "SiO2-covered region from the etched-open one.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_barrier_windows_real.py`
Expected: FAIL with `ImportError: cannot import name 'derive_barrier_covered_windows'`

- [ ] **Step 3: Write the implementation**

Add to `tcad/device/devsim/mesh_import.py` (near the other `derive_*` helpers, e.g. next to `derive_implant_windows_refinement` if present in this file, else at module scope):

```python
def derive_barrier_covered_windows(
    volume_mesh_path: str,
    doped_region: str,
    barrier_material: str,
    axis: str = "x",
    min_barrier_thickness_um: float = 0.0,
    bucket_width_um: Optional[float] = None,
) -> List[Dict[str, float]]:
    """Real-mesh-derived x (or y) ranges where `doped_region`'s real top
    surface sits directly under >= min_barrier_thickness_um of
    `barrier_material` -- so a doping call can exclude dopant there
    instead of applying it uniformly regardless of what is stacked
    above (see docs/investigation_log.md, "SiO2 doesn't block doping").

    Derives windows from the ACTUAL exported mesh (same technique
    already used for derive_implant_windows_refinement -- see
    CLAUDE.md's Development Rules: "Prefer deriving refinement scale
    from the doping profile programmatically ... over a caller
    hand-picking one"), not from a caller's assumption about where the
    barrier is.

    Returns [{"min_um": float, "max_um": float}, ...] in the same
    coordinate convention mask_spans_um/implant_windows already use.
    Empty list if `doped_region` or `barrier_material` is absent from
    the mesh, or nowhere sufficiently covered.
    """
    import meshio
    from tcad.backends.viennaps import session

    module = session.require_viennaps()
    mesh = meshio.read(volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None or "Material" not in mesh.cell_data:
        return []
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data["Material"][block_index]
    points = mesh.points

    axis_idx = 0 if axis == "x" else 1
    depth_idx = 1 if axis == "x" else 0

    doped_tag = int(getattr(module.Material, doped_region))
    barrier_tag = int(getattr(module.Material, barrier_material))

    doped_tris = [t for t, tag in zip(triangle_block.data, tags) if int(tag) == doped_tag]
    barrier_tris = [t for t, tag in zip(triangle_block.data, tags) if int(tag) == barrier_tag]
    if not doped_tris or not barrier_tris:
        return []

    axis_vals = [points[n][axis_idx] for t in doped_tris for n in t]
    axis_min, axis_max = min(axis_vals), max(axis_vals)
    if axis_max <= axis_min:
        return []
    if bucket_width_um is None:
        bucket_width_um = max((axis_max - axis_min) / 200.0, 0.01)
    n_buckets = max(1, int((axis_max - axis_min) / bucket_width_um) + 1)

    def bucket_of(v: float) -> int:
        idx = int((v - axis_min) / bucket_width_um)
        return min(max(idx, 0), n_buckets - 1)

    doped_top = [None] * n_buckets
    for t in doped_tris:
        for n in t:
            b = bucket_of(points[n][axis_idx])
            v = points[n][depth_idx]
            if doped_top[b] is None or v > doped_top[b]:
                doped_top[b] = v

    barrier_top = [None] * n_buckets
    barrier_bot = [None] * n_buckets
    for t in barrier_tris:
        for n in t:
            b = bucket_of(points[n][axis_idx])
            v = points[n][depth_idx]
            if barrier_top[b] is None or v > barrier_top[b]:
                barrier_top[b] = v
            if barrier_bot[b] is None or v < barrier_bot[b]:
                barrier_bot[b] = v

    covered = []
    for b in range(n_buckets):
        if doped_top[b] is None or barrier_top[b] is None or barrier_bot[b] is None:
            covered.append(False)
            continue
        thickness = barrier_top[b] - barrier_bot[b]
        sits_above = barrier_bot[b] >= doped_top[b] - 1e-6
        covered.append(sits_above and thickness >= min_barrier_thickness_um)

    windows: List[Dict[str, float]] = []
    start = None
    for b in range(n_buckets):
        if covered[b] and start is None:
            start = axis_min + b * bucket_width_um
        elif not covered[b] and start is not None:
            windows.append({"min_um": start, "max_um": axis_min + b * bucket_width_um})
            start = None
    if start is not None:
        windows.append({"min_um": start, "max_um": axis_max})
    return windows
```

Add `Optional` to the file's existing `typing` import line if not already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_barrier_windows_real.py`
Expected: PASS, prints the barrier-covered window list and the two assertions succeed.

- [ ] **Step 5: Commit**

```bash
git add tcad/device/devsim/mesh_import.py tests/integration/test_doping_barrier_windows_real.py
git commit -m "feat: derive real barrier-covered doping windows from mesh geometry"
```

---

### Task 2: Wire barrier exclusion into `apply_doping()`

**Files:**
- Modify: `tcad/device/devsim/doping_mapping.py`
- Test: Extend `tests/integration/test_doping_barrier_windows_real.py`

**Interfaces:**
- Consumes: `derive_barrier_covered_windows()` from Task 1 (same return shape).
- Produces: `apply_doping(device, doping, length_scale_to_cm=1.0, window_scale=1.0, exclude_windows: Optional[List[Dict[str, float]]] = None, exclude_axis: str = "x")` — when `exclude_windows` given, every kind's NetDoping equation is multiplied by `(1 - excluded_indicator)`.

- [ ] **Step 1: Add a failing assertion to the existing test**

Task 1's real implementation differs from this plan's original draft in two
ways the appended code below already accounts for: `etch_result` (from
`run_flow()`) is ALREADY a real `ProcessResult` — do not rebuild one via
`build_process_result()`. And the whole test body runs inside
`with tempfile.TemporaryDirectory() as tmp_dir:` (auto-deletes on exit), so
this append MUST go INSIDE that block, at the same indentation as the
existing lines, directly after the existing
`print("derive_barrier_covered_windows() correctly separates ...")` call —
`import_process_result()` below needs `etch_result.volume_mesh_path` to
still exist on disk. Read the current file
(`tests/integration/test_doping_barrier_windows_real.py`) before editing to
confirm the exact indentation and the line to append after; do not assume
this snippet's own indentation is correct without checking.

Append to `tests/integration/test_doping_barrier_windows_real.py`, inside `main()`'s `with` block, after the existing checks:

```python
        from tcad.physics.doping import apply_uniform_doping
        from tcad.device.devsim import backend as devsim_backend
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.device.devsim.doping_mapping import apply_doping

        doped = apply_uniform_doping(etch_result, {"Si": 1.0e17})

        module_ds = devsim_backend.require_devsim()
        imported = import_process_result(
            doped, mesh_name="tbw_mesh", device_name="tbw_device",
            contact_regions=["Si"], contact_axis="x",
        )
        apply_doping(imported.device, doped.doping, exclude_windows=windows)

        node_x = module_ds.get_node_model_values(device="tbw_device", region="Si", name="x")
        net = module_ds.get_node_model_values(device="tbw_device", region="Si", name="NetDoping")
        covered_vals = [n for x, n in zip(node_x, net) if any(w["min_um"] <= x <= w["max_um"] for w in windows)]
        open_vals = [n for x, n in zip(node_x, net) if not any(w["min_um"] <= x <= w["max_um"] for w in windows)]

        module_ds.delete_device(device="tbw_device")
        module_ds.delete_mesh(mesh="tbw_mesh")

    assert covered_vals and max(abs(v) for v in covered_vals) < 1.0, (
        f"NetDoping must be ~0 under the SiO2 barrier, got max |v|="
        f"{max(abs(v) for v in covered_vals):.3e}")
    assert open_vals and min(abs(v) for v in open_vals) > 1.0e16, (
        f"NetDoping must still be the full 1e17 in the open window, got "
        f"min |v|={min(abs(v) for v in open_vals):.3e}")
    print("apply_doping(exclude_windows=...) correctly zeroes NetDoping "
          "under the barrier while leaving the open window at 1e17.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_barrier_windows_real.py`
Expected: FAIL with `TypeError: apply_doping() got an unexpected keyword argument 'exclude_windows'`

- [ ] **Step 3: Write the implementation**

In `tcad/device/devsim/doping_mapping.py`, change the signature and add the exclusion-factor helper:

```python
def apply_doping(
    device: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    window_scale: float = 1.0,
    exclude_windows: Optional[List[Dict[str, float]]] = None,
    exclude_axis: str = "x",
) -> None:
```

`doping_mapping.py` currently has no `typing` import at all (only `from __future__ import annotations`, `from tcad.device.devsim import backend`, `from tcad.mesh.interface import DopingProfile` — verified directly, do not assume otherwise) — add a new line `from typing import Dict, List, Optional` near the top, alongside the existing imports.

Add a module-level helper right above `apply_doping`:

```python
def _exclusion_factor_expr(
    exclude_windows: Optional[List[Dict[str, float]]],
    axis: str,
    length_scale_to_cm: float,
) -> str:
    """DevSim equation string: 1 everywhere, 0 inside any exclusion
    window. Windows are assumed non-overlapping (derive_barrier_covered_
    windows() only ever emits merged, disjoint windows), so summing
    each window's step()*step() indicator and subtracting from 1 is
    safe -- same step()-based windowing mechanism implant_windows
    already uses (see this module's own docstring), reused rather than
    inventing a second one.
    """
    if not exclude_windows:
        return "1"
    terms = []
    for w in exclude_windows:
        lo = w["min_um"] * length_scale_to_cm
        hi = w["max_um"] * length_scale_to_cm
        terms.append(f"step({axis}-({lo}))*step(({hi})-{axis})")
    return "(1 - (" + " + ".join(terms) + "))"
```

Then wrap every kind's final `NetDoping` equation. Replace each of the four `module.node_model(device=..., region=..., name="NetDoping", equation=...)` calls' `equation=` argument to multiply by the exclusion factor, computed once at the top of the function body (right after `module = backend.require_devsim()`):

```python
    module = backend.require_devsim()
    exclusion = _exclusion_factor_expr(exclude_windows, exclude_axis, length_scale_to_cm)
```

- "uniform": `equation=f"({region_doping.net_doping_cm3})*{exclusion}"`
- "step_junction": the `NetDoping` node_model's equation becomes `equation=f"(Donors-Acceptors)*{exclusion}"` (Donors/Acceptors themselves stay unchanged — only the FINAL NetDoping gets excluded, so the two intermediate node models remain diagnostic-readable at full value)
- "gaussian_implant": wrap the existing exp(...) equation string in `f"({...})*{exclusion}"`
- "implant_windows": wrap the existing `" + ".join(terms)` equation in `f"({...})*{exclusion}"`

When `exclude_windows` is `None` (every existing caller), `exclusion == "1"`, so `(expr)*1` is algebraically identical to the un-wrapped expression — DevSim's parser evaluates it to the same value; this preserves every existing caller byte-for-byte (verify in Step 4 via the pre-existing `test_phase7/8_*_real.py`).

- [ ] **Step 4: Run test to verify it passes, then confirm no regression on existing doping tests**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_barrier_windows_real.py`
Expected: PASS.

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_phase7_doping_real.py && PYTHONIOENCODING=utf-8 python tests/integration/test_phase8_pn_junction_real.py`
Expected: both PASS, identical output to before this change (exclusion defaults to `None`/`"1"`).

- [ ] **Step 5: Commit**

```bash
git add tcad/device/devsim/doping_mapping.py tests/integration/test_doping_barrier_windows_real.py
git commit -m "feat: apply_doping() can exclude NetDoping under a barrier material"
```

---

### Task 3: Renderer per-x surface profile (fixes the global-bbox over-paint)

**Files:**
- Modify: `tcad_2d_stagewise.py` (`_draw_real_mesh_result`, new `_material_surface_profile`)
- Test: Create `tests/integration/test_doping_overlay_surface_profile_real.py`

**Interfaces:**
- Produces: `_material_surface_profile(triangle_data, points, tags, material_tag: int, x_min: float, x_max: float, n_buckets: int = 60) -> List[Tuple[float, float, float, float]]` — pure function (no Tk/canvas dependency), returns `[(x_lo, x_hi, y_top, y_bot), ...]`, one entry per non-empty bucket, sorted by x.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_material_surface_profile() must track the REAL local surface height,
not a global bounding box -- pinned with an etched-trench mesh where
the Si top genuinely differs by ~1um between the mesa and the trench
floor (see docs/investigation_log.md, "renderer draws doping color
using a global bounding box").
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 10.0, "y_extent_um": 8.0,
    "mask_spans_um": [[-1.5, 1.5]], "mask_material": "PHS",
    "pr_thickness_um": 0.5, "silicon_depth_um": 5.0,
    "rate": -1.0, "etch_time_s": 1.0,
}


def main():
    import tcad_2d_stagewise as gui
    import meshio

    tmp = tempfile.mkdtemp(prefix="tsp_")
    step_cls = registry.get("etching", "isotropic")
    result = step_cls().run(RECIPE, tmp)

    module = session.require_viennaps()
    mesh = meshio.read(result["final_mesh"])
    tri = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(tri)]
    points = mesh.points
    si_tag = int(module.Material.Si)

    profile = gui.TCADApplication._material_surface_profile(
        tri.data, points, tags, si_tag, -5.0, 5.0, n_buckets=100,
    )
    assert profile, "profile must not be empty for a mesh containing Si"

    # x=-4..-2.5 is the ETCHED region (protected span is [-1.5,1.5], so
    # everything outside it was etched -1.0um deep); x=-1..1 is
    # PROTECTED (inside the mask span), still near the original surface.
    etched_tops = [seg[2] for seg in profile if -4.0 <= seg[0] <= -2.5]
    protected_tops = [seg[2] for seg in profile if -1.0 <= seg[0] <= 1.0]
    assert etched_tops and protected_tops, "expected buckets in both x ranges"

    etched_top = max(etched_tops)
    protected_top = max(protected_tops)
    print(f"Etched-region top: {etched_top:.4f}  Protected-region top: {protected_top:.4f}")
    assert protected_top - etched_top > 0.5, (
        f"the profile must show the real ~1um step between the etched "
        f"and protected regions, got {protected_top - etched_top:.4f}um "
        f"-- a global bounding box would report the SAME top for both")

    print("_material_surface_profile() tracks the real per-x surface, "
          "not a global bounding box.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_overlay_surface_profile_real.py`
Expected: FAIL with `AttributeError: type object 'TCADApplication' has no attribute '_material_surface_profile'`

- [ ] **Step 3: Write the implementation**

Add a new method to `TCADApplication` in `tcad_2d_stagewise.py`, directly above `_draw_real_mesh_result` (so it reads as that method's own helper):

```python
    @staticmethod
    def _material_surface_profile(triangle_data, points, tags, material_tag, x_min, x_max, n_buckets=60):
        """Per-x (bucketed) (x_lo, x_hi, y_top, y_bot) for one material
        tag, from real mesh triangle/point data. Pure function -- no
        canvas, no Tk -- so it is unit-testable without a display and
        reusable for both the doping-tint overlay and, later, any
        other per-x-aware drawing.

        Replaces computing ONE global (min, max) over every node of
        the material and drawing a single rectangle across the WHOLE
        x-range, which over-paints wherever the real surface height
        varies across x (see docs/investigation_log.md, "renderer
        draws doping color using a global bounding box").
        """
        if x_max <= x_min:
            return []
        bucket_width = (x_max - x_min) / n_buckets
        tops = [None] * n_buckets
        bots = [None] * n_buckets

        def bucket_of(x):
            idx = int((x - x_min) / bucket_width)
            return min(max(idx, 0), n_buckets - 1)

        for tri, tag in zip(triangle_data, tags):
            if int(tag) != material_tag:
                continue
            for n in tri:
                x, y = points[n][0], points[n][1]
                b = bucket_of(x)
                if tops[b] is None or y > tops[b]:
                    tops[b] = y
                if bots[b] is None or y < bots[b]:
                    bots[b] = y

        segments = []
        for b in range(n_buckets):
            if tops[b] is None:
                continue
            segments.append(
                (x_min + b * bucket_width, x_min + (b + 1) * bucket_width, tops[b], bots[b])
            )
        return segments
```

Then in `_draw_real_mesh_result`, replace the doping-tint block (the loop starting `for region_name in {r.region for r in self.last_doped_result.doping.regions}:`) — specifically replace the `region_y_top`/`region_y_bot` global computation and the single `canvas.create_rectangle(cx_lo, cy_top, cx_hi, cy_bot, ...)` call with a per-segment draw:

```python
                for region_name in {r.region for r in self.last_doped_result.doping.regions}:
                    region_tag = next(
                        (t for t, n in material_names.items() if n == region_name),
                        None,
                    )
                    if region_tag is None:
                        continue
                    profile = self._material_surface_profile(
                        triangle_data, points, tags, region_tag, x_min, x_max,
                    )
                    if not profile:
                        continue

                    for x_lo_um, x_hi_um, color in self._doping_color_segments(
                        region_name, x_min, x_max
                    ):
                        if x_hi_um <= x_lo_um:
                            continue
                        for seg_x_lo, seg_x_hi, seg_y_top, seg_y_bot in profile:
                            # Intersect this surface bucket with the
                            # doping color segment's own x-range (e.g.
                            # step_junction only tints one side).
                            lo = max(seg_x_lo, x_lo_um)
                            hi = min(seg_x_hi, x_hi_um)
                            if hi <= lo:
                                continue
                            cx_lo = x0 + (lo - x_min) * x_scale
                            cx_hi = x0 + (hi - x_min) * x_scale
                            cy_top = surface_y - seg_y_top * y_scale
                            cy_bot = surface_y - seg_y_bot * y_scale
                            canvas.create_rectangle(
                                cx_lo, cy_top, cx_hi, cy_bot,
                                fill=color, outline="", stipple="gray50",
                            )
```

Note `tags` here refers to the same `tags = [int(t) for t in mesh.cell_data["Material"][block_index]]` list already built earlier in `_draw_real_mesh_result` — confirm the variable name matches (read the surrounding ~40 lines before editing to use the exact existing local variable name for the per-triangle material tag list, likely already called `tags` per the earlier-read code at line ~5488).

- [ ] **Step 4: Run test to verify it passes, then a visual smoke check**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_overlay_surface_profile_real.py`
Expected: PASS.

Run the full doping-related regression subset to confirm the renderer change doesn't crash any existing doping/measurement path:
`PYTHONIOENCODING=utf-8 python tests/integration/test_gui_doping_donor_acceptor_real.py`
Expected: PASS (this test drives the real GUI's `run_doping()` + `redraw()`, so it exercises the new drawing code path end-to-end).

- [ ] **Step 5: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_doping_overlay_surface_profile_real.py
git commit -m "fix: doping color overlay follows the real per-x surface, not a global bbox"
```

---

### Task 4: Wire barrier exclusion into the GUI's `run_measurement()` + threshold field

**Files:**
- Modify: `tcad_2d_stagewise.py` (`_make_doping_panel`, `run_measurement`)
- Test: `tests/integration/test_gui_doping_donor_acceptor_real.py` (extend)

**Interfaces:**
- Consumes: `derive_barrier_covered_windows()` (Task 1), `apply_doping(..., exclude_windows=...)` (Task 2).

- [ ] **Step 1: Add the threshold field to the doping panel**

In `_make_doping_panel`, near the other shared (not per-kind) doping fields, add:

```python
        # SiO2-barrier exclusion -- see docs/investigation_log.md,
        # "SiO2 doesn't block doping". A REAL geometric threshold
        # (measured directly from the mesh), not a fake energy-derived
        # number -- see CLAUDE.md's "no fake physics parameters" rule.
        # Default 0.0 = any measurable SiO2 above the doped region
        # blocks doping there (the most conservative reading available
        # without a real implant-energy model to compute an actual
        # penetration depth).
        ttk.Label(
            doping_params_container, text="SiO2 barrier min thickness (µm)",
            style="Caption.TLabel",
        ).pack(anchor="w", padx=12, pady=(6, 1))
        self.dope_barrier_threshold_var = self._field(
            doping_params_container, "SiO2 barrier min thickness (µm)", 0.0,
        )
```

(Remove the duplicate `ttk.Label` above if `_field()` already renders its own caption label — check `_field()`'s body, which it does per Task Group's earlier reading of the helper; drop the standalone `ttk.Label` call and keep only the `self._field(...)` call.)

- [ ] **Step 2: Wire it into `run_measurement()`**

In `run_measurement()`, right before the `try:` block that calls `import_process_result`, compute exclusion windows and pass them into the later `apply_doping()` call:

```python
        exclude_windows = None
        try:
            exclude_windows = derive_barrier_covered_windows(
                self.last_final_mesh, doped_region=region,
                barrier_material="SiO2", axis=axis,
                min_barrier_thickness_um=float(self.dope_barrier_threshold_var.get()),
            )
        except Exception:
            # Barrier detection is best-effort: if it fails (material
            # absent, mesh unreadable), fall back to no exclusion --
            # never let a diagnostic feature block the actual measurement.
            exclude_windows = None
```

Add the import at the top of the function or module level (module-level preferred, alongside the other `from tcad.device.devsim...` imports already inside `run_measurement()`):

```python
        from tcad.device.devsim.mesh_import import import_process_result, derive_barrier_covered_windows
```

Then find the existing `apply_doping(imported.device, doped_result.doping, length_scale_to_cm=length_scale_to_cm)` call (the non-`implant_windows` branch) and add `exclude_windows=exclude_windows, exclude_axis=axis` to it. For the `implant_windows` branch (which calls `run_robust_pn_junction_iv_sweep`, not `apply_doping` directly), leave it UNCHANGED in this task — `run_robust_pn_junction_iv_sweep` registers NetDoping itself via its own ramping mechanism, and threading barrier exclusion through that ramp is a separate, higher-risk change not required by this plan's scope (implant_windows already gets barrier-window DATA computed above; wiring it into the ramp path can be a follow-up if the user asks for it explicitly).

- [ ] **Step 3: Extend the GUI regression test**

Add to `tests/integration/test_gui_doping_donor_acceptor_real.py` a new scenario function (or extend `main()`) that: runs a real Oxidation, then a real windowed SiO2-clearing Etch (mirroring Task 1's fixture), then Uniform doping on `"Si"`, then MEASURE, and asserts (via `devsim.get_node_model_values`, reached the same way `test_gui_doping_donor_acceptor_real.py` already reaches into the DevSim device before `delete_device` is called in `run_measurement()`'s `finally`) that `NetDoping` differs meaningfully between the barrier-covered and open-window contact regions. Since `run_measurement()` deletes the device in `finally`, capture the values via a temporary monkeypatch of `devsim.solve` or by reading `get_node_model_values` from inside a wrapped `import_process_result`/`apply_doping` call before `run_measurement()`'s own cleanup — simplest: call the SAME sequence (`_materialize_current_wafer`-equivalent via the oxidation+etch fixture, `app.run_doping()`, then directly call `app.dope_barrier_threshold_var.set(0.0)` and invoke the barrier-derivation + `apply_doping` path manually as Task 2's test already does) rather than trying to intercept `run_measurement()`'s internal cleanup — reuse Task 2's test body almost verbatim, just start from the real GUI's `app.last_final_mesh`/`app.wafer` state instead of a hand-built recipe, to prove the GUI wiring (field read, `derive_barrier_covered_windows` call args) is correct end-to-end.

- [ ] **Step 4: Run and verify**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gui_doping_donor_acceptor_real.py`
Expected: PASS, including the new barrier scenario.

Run the full suite: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: 49+ passed (baseline 49 plus this task group's new tests), same 3 pre-existing failures, zero new failures.

- [ ] **Step 5: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_doping_donor_acceptor_real.py
git commit -m "feat: wire SiO2 barrier exclusion into the real MEASURE path"
```

---

## Task Group 2: Mask Alignment / Exposure / PR display

**원인**: `redraw()`'s `real_mesh_available` gate becomes `True` the instant `wafer.processed` is `True` (set by ANY earlier real process step), which suppresses the litho placeholder (PR film / mask box / UV rays) for PR Coat, Mask Alignment, Exposure, and Develop — even though none of those four state-only steps produce a new real mesh. `_MATERIAL_COLORS` has no `"PHS"` entry, so resist falls back to a generic gray once a real mesh renders it.

**수정 파일**: `tcad_2d_stagewise.py` (`__init__`, `reset`, the 5 litho methods, the 8 `last_final_mesh` assignment sites, `redraw`'s `real_mesh_available` computation, `_MATERIAL_COLORS`).

**수정 함수**: `process_pr_coat`, `process_mask_alignment`, `process_exposure`, `process_develop`, `process_pr_strip` (each gets one new line); `redraw` (the `real_mesh_available` boolean expression).

**테스트**: `tests/integration/test_gui_litho_placeholder_visibility_real.py`.

**회귀 위험**: LOW. The gate becomes MORE restrictive only in the specific new case (litho state changed since the last real mesh) — every other case (`real_mesh_available` already `False`, or litho never changed) is byte-identical to today. The 8 assignment-site edits are mechanical (add one line after an existing, already-confirmed-identical line at 8 locations) — verified via `grep -n "self\.last_final_mesh = "` before editing so no site is missed.

### Task 5: `_litho_pending_since_last_mesh` flag + gate fix + PHS color

**Files:**
- Modify: `tcad_2d_stagewise.py`

**Interfaces:**
- Produces: `self._litho_pending_since_last_mesh: bool` instance attribute.

- [ ] **Step 1: Add the flag's init and reset**

In `__init__`, right after `self.last_final_mesh = None` (near the `_viewer_depth_budget_um` init added this session):

```python
        # True from the moment a litho state changes (PR COAT / MASK
        # ALIGNMENT / EXPOSURE / DEVELOP / PR STRIP) until the next
        # REAL process step produces a mesh that reflects it. Litho
        # methods are state-only (no ViennaPS call), so "a real mesh
        # already exists" does NOT mean it shows the CURRENT litho
        # state -- see docs/investigation_log.md, "Mask Alignment/
        # Exposure placeholder disappears once any real mesh exists".
        self._litho_pending_since_last_mesh = False
```

In `reset()` (NEW WAFER), alongside `self.last_final_mesh = None`:

```python
        self._litho_pending_since_last_mesh = False
```

- [ ] **Step 2: Mark litho actions as pending**

In each of `process_pr_coat`, `process_mask_alignment`, `process_exposure`, `process_develop`, `process_pr_strip`, add one line immediately before the trailing `self.redraw()` call:

```python
        self._litho_pending_since_last_mesh = True
```

(`process_exposure`'s no-resist early-return branch and `process_develop`'s/`process_pr_strip`'s no-resist early-return branches already `return` before reaching their own trailing `redraw()` — leave those unchanged; only add the line at each method's NORMAL, state-changing path, i.e. once per method, right before its own final `self.redraw()`.)

- [ ] **Step 3: Clear the flag at every real-mesh-producing site**

At each of the 8 locations found by `grep -n "self\.last_final_mesh = result.get(\"final_mesh\")" tcad_2d_stagewise.py` (lines 1299, 2335, 2884, 2947, 3009, 3307, 3640, 5466 as of this session — re-grep before editing since line numbers shift), add immediately below:

```python
        self._litho_pending_since_last_mesh = False
```

- [ ] **Step 4: Fix the gate itself**

In `redraw()`, change:

```python
        real_mesh_available = bool(
            self.wafer.processed
            and display_mesh
            and Path(display_mesh).exists()
        )
```

to:

```python
        real_mesh_available = bool(
            self.wafer.processed
            and display_mesh
            and Path(display_mesh).exists()
            and not self._litho_pending_since_last_mesh
        )
```

This single added clause makes `real_mesh_available` fall back to `False` while litho is pending — which correctly re-enables the Si-substrate placeholder rectangle (already gated on `not real_mesh_available`), the PR/mask/exposure placeholder blocks (already gated the same way), and skips the stale `_draw_real_mesh_result()` call (already gated on `if real_mesh_available:`) — no other code changes needed.

- [ ] **Step 5: Add the PHS color**

In `_MATERIAL_COLORS`, add:

```python
        "PHS": "#e8a0bd",         # photoresist -- same pink as the litho placeholder, see _RESIST_MATERIAL
```

- [ ] **Step 6: Write the regression test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The litho placeholder (Mask Alignment / Exposure) must not disappear
just because an EARLIER, unrelated real process step already ran --
see docs/investigation_log.md, "Mask Alignment/Exposure placeholder
disappears once any real mesh exists". Drives the real TCADApplication
(window withdrawn) through a real Oxidation, then Litho, checking the
STATE FLAG that drives the rendering decision (the same technique
tests/unit/test_gui_litho_lifecycle_mock.py already uses for the
resist-spans state, extended here to the render-gate state).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
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

        assert app._litho_pending_since_last_mesh is False, (
            "a fresh wafer must not start with litho marked pending")

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"
        assert app._litho_pending_since_last_mesh is False
        assert app.wafer.processed is True

        # Litho actions AFTER a real mesh already exists -- this is
        # exactly the reported scenario (Oxidation, then PR Coat /
        # Mask Alignment / Exposure).
        app.process_pr_coat()
        assert app._litho_pending_since_last_mesh is True, (
            "PR COAT after an earlier real mesh must mark litho pending "
            "so the placeholder draws instead of the stale real mesh")

        app.process_mask_alignment()
        assert app._litho_pending_since_last_mesh is True

        app.process_exposure()
        assert app._litho_pending_since_last_mesh is True

        # The gate itself: real_mesh_available must now be False even
        # though wafer.processed is True and last_final_mesh exists.
        real_mesh_available = bool(
            app.wafer.processed
            and app.last_final_mesh
            and Path(app.last_final_mesh).exists()
            and not app._litho_pending_since_last_mesh
        )
        assert real_mesh_available is False, (
            "real_mesh_available must be False while litho is pending, "
            "so the placeholder actually draws")

        app.process_develop()
        assert app._litho_pending_since_last_mesh is True

        # A REAL step (Etch) consumes the pending litho state.
        app.etch_model.set("Isotropic etch")
        app.grid_var.set(0.2)
        app.isotropic_rate_var.set(0.05)
        app.etch_time_var.set(1.0)
        ok = app.run_etch()
        assert app._litho_pending_since_last_mesh is False, (
            "a real Etch must clear the pending flag -- it consumed "
            "the current litho state into a new real mesh")

        print("Litho placeholder gate: pending after PR Coat/Align/"
              "Expose/Develop even with an earlier real mesh present; "
              "cleared by the next real process step.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run test to verify it fails, then passes after the fix**

Run BEFORE Steps 1-5 (to confirm the test catches the bug): `PYTHONIOENCODING=utf-8 python tests/integration/test_gui_litho_placeholder_visibility_real.py`
Expected (pre-fix): FAIL on the `real_mesh_available is False` assertion.

Run AFTER Steps 1-5: same command.
Expected: PASS.

- [ ] **Step 8: Run the full regression suite**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: baseline 49 (+ this task's new test) passed, same 3 pre-existing failures, zero new failures. Pay particular attention to `test_gui_litho_lifecycle_mock.py`, `test_litho_lifecycle_state_real.py`, `test_gui_process_state_chaining_real.py`, and `test_physics_rules_real.py` — all touch litho/mesh state and are the most likely to catch a missed assignment site.

- [ ] **Step 9: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_litho_placeholder_visibility_real.py
git commit -m "fix: litho placeholder no longer hidden by an earlier unrelated real mesh"
```

---

## Task Group 3: Oxidation → PR → Etch clarity (informational only — physics unchanged)

**원인**: Not a bug — confirmed by `.vpsd`-independent-copy comparison that Etch behaves exactly as documented (`material_rates` absent ⇒ every exposed material etches at the same rate). The GUI default Oxidation (0.5hr) produces 0.0652um of SiO2; the GUI default Etch (0.05um/s × 1.0s) has a 0.05um budget — insufficient to punch through, so Si genuinely does not move. The user cannot currently see this from the GUI (compounded by Task Group 2's gate bug hiding the intermediate litho state too).

**수정 파일**: `tcad_2d_stagewise.py` (`run_etch`, new `_log_etch_material_summary`).

**수정 함수**: `_log_etch_material_summary()` (new), `run_etch()` (one new call in the success path).

**테스트**: `tests/integration/test_oxidation_pr_etch_reaches_si_real.py`.

**회귀 위험**: LOW. Purely additive logging; no existing return value, recipe, or physics call is touched. Worst case is a log-formatting exception, which must be caught so a diagnostic feature can never break a real etch run (mirrors Task 4's `try/except` around barrier detection).

### Task 6: `_log_etch_material_summary()` + wiring

**Files:**
- Modify: `tcad_2d_stagewise.py`

**Interfaces:**
- Produces: `_log_etch_material_summary(self, pre_mesh_path: str, post_mesh_path: str, open_windows_um: List[List[float]]) -> None` — logs via `self._log(...)`, no return value.

- [ ] **Step 1: Write the implementation**

Add near `run_etch()` (directly above it):

```python
    def _log_etch_material_summary(self, pre_mesh_path, post_mesh_path, open_windows_um):
        """Log, per material, how much moved in the OPEN (unmasked)
        window(s) between two real exported meshes -- so the user can
        see whether an etch reached a given material without having to
        infer it from the render alone. Never changes what the etch
        DID (see docs/investigation_log.md, "Etch is correct, GUI
        gives no feedback about whether the target material was
        reached") -- this is diagnostic only.
        """
        if not open_windows_um:
            self._log("\n(No open window -- resist fully covers the wafer, nothing exposed to etch.)\n")
            return
        try:
            import meshio

            def read(path):
                m = meshio.read(path)
                tri = next(c for c in m.cells if c.type == "triangle")
                tags = m.cell_data["Material"][m.cells.index(tri)]
                names = {}
                for attr in dir(viennaps_session.require_viennaps().Material):
                    if attr.startswith("_"):
                        continue
                    v = getattr(viennaps_session.require_viennaps().Material, attr)
                    if isinstance(v, viennaps_session.require_viennaps().Material):
                        names[int(v)] = attr
                pts = m.points
                by_mat = {}
                for t, tag in zip(tri.data, tags):
                    by_mat.setdefault(names.get(int(tag), str(tag)), []).append(t)
                return pts, by_mat

            def top_in_window(pts, by_mat, material, lo, hi):
                node_idxs = set()
                for t in by_mat.get(material, []):
                    node_idxs.update(t)
                ys = [pts[n][1] for n in node_idxs if lo <= pts[n][0] <= hi]
                return max(ys) if ys else None

            pts_pre, by_mat_pre = read(pre_mesh_path)
            pts_post, by_mat_post = read(post_mesh_path)
            materials = sorted(set(by_mat_pre) | set(by_mat_post))
            noise_floor_um = 0.001

            lines = ["\nETCH RESULT BY MATERIAL (open window only):"]
            for lo, hi in open_windows_um:
                lines.append(f"  Window x=[{lo:.3f}, {hi:.3f}]:")
                for material in materials:
                    before = top_in_window(pts_pre, by_mat_pre, material, lo, hi)
                    after = top_in_window(pts_post, by_mat_post, material, lo, hi)
                    if before is None and after is None:
                        continue
                    if after is None:
                        lines.append(f"    {material}: fully cleared (was present, now gone here)")
                    elif before is None:
                        lines.append(f"    {material}: newly exposed here (top={after:.4f})")
                    else:
                        moved = before - after
                        if abs(moved) < noise_floor_um:
                            status = "unchanged (not yet reached)" if material == "Si" else "unchanged"
                            lines.append(f"    {material}: {status} (top={after:.4f})")
                        else:
                            lines.append(f"    {material}: etched {moved:.4f}um (top {before:.4f} -> {after:.4f})")
            self._log("\n".join(lines) + "\n")
        except Exception as exc:
            # Diagnostic-only: never let this block or corrupt a real
            # etch result.
            self._log(f"\n(Could not compute the etch material summary: {exc!r})\n")
```

- [ ] **Step 2: Wire it into `run_etch()`'s success path**

In `run_etch()`, after `result = json.loads(result_file.read_text(encoding="utf-8"))` and the existing success checks, right before (or right after) the `self.last_final_mesh = result.get("final_mesh")` line (Task 2's line 5466 area), add:

```python
        pre_snapshots = result.get("snapshots") or []
        if pre_snapshots and result.get("final_mesh"):
            self._log_etch_material_summary(
                pre_snapshots[0], result["final_mesh"], self.wafer.mask_openings_um,
            )
```

Place this call AFTER `self._litho_pending_since_last_mesh = False` (Task 5 Step 3's new line) so both additions coexist cleanly at this site.

- [ ] **Step 3: Write the test — verifies the LOG, not a physics change**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_etch() must log a per-material summary that correctly distinguishes
"Si not yet reached" (insufficient etch budget) from "Si genuinely
removed" (sufficient budget) -- exercising _log_etch_material_summary()
directly against two real .vpsd-independent-copy scenarios, and
confirming the underlying GEOMETRY behaves as previously verified (this
task changes NO physics -- see docs/investigation_log.md).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

WIDTH = 10.0
HALF = WIDTH / 2.0
BASE = dict(grid_delta_um=0.05, x_extent_um=WIDTH, y_extent_um=8.0,
            silicon_depth_um=5.0, pr_thickness_um=1.0)
DEVELOPED_SPANS = [[-HALF, -1.5], [1.5, HALF]]
OPEN_WINDOW = [-1.5, 1.5]


def _oxidize():
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [],
        "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5,
    }
    tmp = tempfile.mkdtemp(prefix="etchsi_ox_")
    ox_step = registry.get("oxidation", "thermal")()
    result = ox_step.run(oxidation, tmp)
    return result


def _etch(domain_state, rate, etch_time_s):
    etch_domain = session.load_domain_state(domain_state)
    etch_recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        **BASE,
        "remask_spans_um": DEVELOPED_SPANS, "mask_material": "PHS",
        "rate": rate, "etch_time_s": etch_time_s,
    }
    etch_step = registry.get("etching", "isotropic")()
    etch_step._inherited_domain = etch_domain
    tmp = tempfile.mkdtemp(prefix="etchsi_etch_")
    return etch_step.run(etch_recipe, tmp)


def _si_top(mesh_path, x_lo, x_hi):
    import meshio
    module = session.require_viennaps()
    m = meshio.read(mesh_path)
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    si_tag = int(module.Material.Si)
    pts = m.points
    ys = [pts[n][1] for t, tag in zip(tri.data, tags) if int(tag) == si_tag
          for n in t if x_lo <= pts[n][0] <= x_hi]
    return max(ys) if ys else None


def main():
    ox_result = _oxidize()

    # --- Case 1: insufficient budget (GUI defaults) -- Si must NOT move ---
    insufficient = _etch(ox_result["domain_state"], rate=-0.05, etch_time_s=1.0)
    si_before = _si_top(ox_result["final_mesh"], *OPEN_WINDOW)
    si_after_insufficient = _si_top(insufficient["final_mesh"], *OPEN_WINDOW)
    moved_insufficient = si_before - si_after_insufficient
    print(f"Insufficient budget: Si moved {moved_insufficient:.5f}um in the open window")
    assert moved_insufficient < 0.001, (
        f"with the GUI's default etch budget (< SiO2 thickness), Si must "
        f"NOT move -- moved {moved_insufficient:.5f}um")

    # PR-protected region must be fully untouched regardless.
    si_protected_before = _si_top(ox_result["final_mesh"], -4.0, -3.0)
    si_protected_after = _si_top(insufficient["final_mesh"], -4.0, -3.0)
    assert abs(si_protected_before - si_protected_after) < 0.001, (
        "PR-protected Si must be untouched")

    # --- Case 2: sufficient budget -- Si MUST genuinely move; PR-protected
    #     region must STILL be untouched. ---
    sufficient = _etch(ox_result["domain_state"], rate=-0.05, etch_time_s=4.0)
    si_after_sufficient = _si_top(sufficient["final_mesh"], *OPEN_WINDOW)
    moved_sufficient = si_before - si_after_sufficient
    print(f"Sufficient budget: Si moved {moved_sufficient:.5f}um in the open window")
    assert moved_sufficient > 0.01, (
        f"with enough etch budget to punch through SiO2, Si MUST genuinely "
        f"move in the open window -- moved only {moved_sufficient:.5f}um")

    si_protected_after_2 = _si_top(sufficient["final_mesh"], -4.0, -3.0)
    assert abs(si_protected_before - si_protected_after_2) < 0.001, (
        "PR-protected Si must STILL be untouched even when the open "
        "window's Si was genuinely etched")

    # --- The log summary itself ---
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()
        logged = []
        app._log = lambda msg: logged.append(msg)
        app._log_etch_material_summary(
            ox_result["snapshots"][0] if ox_result.get("snapshots") else ox_result["final_mesh"],
            insufficient["final_mesh"], [OPEN_WINDOW],
        )
        combined = "".join(logged)
        assert "Si" in combined and "not yet reached" in combined, (
            f"insufficient-budget log must say Si was not reached: {combined!r}")
    finally:
        app.destroy()

    print("Etch physics unchanged (confirmed by direct geometry measurement); "
          "log summary correctly distinguishes 'not yet reached' from "
          "'genuinely removed', and PR protection holds in both cases.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it fails (before Steps 1-2), then passes**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_oxidation_pr_etch_reaches_si_real.py`
Expected (pre-fix): FAIL on `AttributeError: 'TCADApplication' object has no attribute '_log_etch_material_summary'`.
Expected (post-fix): PASS.

- [ ] **Step 5: Run the full regression suite**

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: baseline 49 (+ new tests from Task Groups 1-3) passed, same 3 pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_oxidation_pr_etch_reaches_si_real.py
git commit -m "feat: log per-material etch progress in the open window (diagnostic only)"
```

---

## Task Group 4: Doping input model — donor/acceptor for all 4 kinds

**원인**: `apply_uniform_doping`, `apply_gaussian_implant_doping`, `apply_implant_windows_doping` each accept only a single signed net concentration; `apply_step_junction_doping` already takes independent donor/acceptor (spatially split, unchanged). No backend (ViennaPS 4.6.2 or DevSim) has any real ion-implant/diffusion physics — confirmed by direct `dir()` introspection — so implant energy/dose/beam-voltage/diffusion-time/temperature are explicitly OUT OF SCOPE for this plan (see Global Constraints).

**수정 파일**: `tcad/mesh/interface.py` (`DopingRegion`), `tcad/physics/doping.py` (3 of 4 `apply_*` functions), `tcad_2d_stagewise.py` (`_make_doping_panel`, `run_doping`).

**수정 함수**: `apply_uniform_doping`, `apply_gaussian_implant_doping`, `apply_implant_windows_doping` (all backward-compatible additive signature changes); `apply_step_junction_doping` unchanged.

**테스트**: `tests/integration/test_doping_donor_acceptor_all_kinds_real.py`.

**회귀 위험**: LOW. Every new parameter is keyword-only with a default that preserves the exact current signature and behavior for every existing caller (`pn_junction_iv_sweep.py`, `robust_iv_sweep.py`, `test_phase7/8_*_real.py`, `test_gaussian_implant_doping_real.py`, `test_implant_windows_doping_real.py`, `test_physics_rules_real.py`). The GUI panel changes touch only the Gaussian Implant and Implant Windows frames — Uniform (already done this session) and Step Junction (already correct) are untouched.

### Task 7: `DopingRegion` new fields + `doping.py` donor/acceptor parameters

**Files:**
- Modify: `tcad/mesh/interface.py`, `tcad/physics/doping.py`
- Test: Create `tests/integration/test_doping_donor_acceptor_all_kinds_real.py`

**Interfaces:**
- Produces (on `DopingRegion`): `donor_peak_conc_cm3: Optional[float] = None`, `acceptor_peak_conc_cm3: Optional[float] = None`, `donor_species: Optional[str] = None`, `acceptor_species: Optional[str] = None`.
- Produces (on `doping.py`): `apply_uniform_doping(result, doping_by_region_cm3=None, *, donor_by_region_cm3=None, acceptor_by_region_cm3=None, species_by_region=None)`; `apply_gaussian_implant_doping(result, region, junction_axis, peak_position_um, straggle_um, peak_conc_cm3=None, *, donor_peak_conc_cm3=None, acceptor_peak_conc_cm3=None, donor_species=None, acceptor_species=None)`; `apply_implant_windows_doping(result, region, axis, background_doping_cm3=None, windows=(), *, donor_background_cm3=None, acceptor_background_cm3=None)` — each window dict may carry `"donor_conc_cm3"`/`"acceptor_conc_cm3"` as an alternative to `"conc_cm3"`.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All 4 doping kinds must accept independent donor/acceptor concentrations
and compute net = donor - acceptor internally, while PRESERVING the raw
donor/acceptor values on the DopingRegion (not just collapsing to net).
Every EXISTING net-only call shape must still work unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)


def _base_result():
    return ProcessResult(
        final_mesh="dummy.vtu", snapshots=[],
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def main():
    # --- Backward compatibility: old net-only call shapes unchanged ---
    r = apply_uniform_doping(_base_result(), {"Si": 1.0e17})
    assert r.doping.regions[0].net_doping_cm3 == 1.0e17
    assert r.doping.regions[0].donor_conc_cm3 is None

    r = apply_gaussian_implant_doping(_base_result(), "Si", "x", 0.0, 0.5, 1.0e17)
    assert r.doping.regions[0].peak_conc_cm3 == 1.0e17

    r = apply_implant_windows_doping(_base_result(), "Si", "x", -1.0e17, [
        {"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20},
    ])
    assert r.doping.regions[0].net_doping_cm3 == -1.0e17
    assert r.doping.regions[0].implant_windows[0]["conc_cm3"] == 1.0e20

    # --- New donor/acceptor shapes ---
    r = apply_uniform_doping(
        _base_result(),
        donor_by_region_cm3={"Si": 1.0e16}, acceptor_by_region_cm3={"Si": 5.0e15},
    )
    region = r.doping.regions[0]
    assert region.net_doping_cm3 == 5.0e15, f"net must be donor-acceptor, got {region.net_doping_cm3}"
    assert region.donor_conc_cm3 == 1.0e16, "raw donor value must be preserved"
    assert region.acceptor_conc_cm3 == 5.0e15, "raw acceptor value must be preserved"

    r = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", 0.0, 0.3,
        donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=3.0e17,
        donor_species="P", acceptor_species="B",
    )
    region = r.doping.regions[0]
    assert abs(region.peak_conc_cm3 - (2.0e18 - 3.0e17)) < 1.0, (
        f"gaussian net peak must be donor-acceptor, got {region.peak_conc_cm3}")
    assert region.donor_peak_conc_cm3 == 2.0e18
    assert region.acceptor_peak_conc_cm3 == 3.0e17
    assert region.donor_species == "P" and region.acceptor_species == "B"

    r = apply_implant_windows_doping(
        _base_result(), "Si", "x",
        donor_background_cm3=1.0e15, acceptor_background_cm3=1.0e16,
        windows=[
            {"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1.0e20, "acceptor_conc_cm3": 0.0},
        ],
    )
    region = r.doping.regions[0]
    assert region.net_doping_cm3 == 1.0e15 - 1.0e16, (
        f"background net must be donor-acceptor, got {region.net_doping_cm3}")
    window = region.implant_windows[0]
    assert window["conc_cm3"] == 1.0e20, f"window net must be donor-acceptor, got {window['conc_cm3']}"
    assert window["donor_conc_cm3"] == 1.0e20 and window["acceptor_conc_cm3"] == 0.0

    # --- step_junction unchanged (already correct) ---
    r = apply_step_junction_doping(_base_result(), "Si", "x", 0.0, 1.0e18, 1.0e18)
    assert r.doping.regions[0].donor_conc_cm3 == 1.0e18
    assert r.doping.regions[0].acceptor_conc_cm3 == 1.0e18

    print("All 4 doping kinds accept independent donor/acceptor input, "
          "compute net=donor-acceptor internally, preserve the raw "
          "values, and every existing net-only call shape is unchanged.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_donor_acceptor_all_kinds_real.py`
Expected: FAIL with `TypeError: apply_uniform_doping() got an unexpected keyword argument 'donor_by_region_cm3'`

- [ ] **Step 3: Extend `DopingRegion`**

In `tcad/mesh/interface.py`, add to `DopingRegion` (after the existing `implant_windows` field):

```python
    donor_peak_conc_cm3: Optional[float] = None
    acceptor_peak_conc_cm3: Optional[float] = None
    donor_species: Optional[str] = None
    acceptor_species: Optional[str] = None
```

Extend the class docstring with one paragraph:

```
    donor_peak_conc_cm3 / acceptor_peak_conc_cm3 : gaussian_implant
        case, donor/acceptor input variant — both profiles share the
        SAME peak_position_um/straggle_um (this project has no
        implant-energy model to give them independently-derived
        shapes; see CLAUDE.md's "no fake physics parameters" rule).
        peak_conc_cm3 is computed as donor - acceptor and is what
        every downstream consumer (doping_mapping.py, the renderer)
        continues to read. None when the region was built from a
        plain signed peak_conc_cm3 instead.
    donor_species / acceptor_species : label-only metadata (e.g. "P",
        "B", "As") for the process log and any future report — never
        read by doping_mapping.py or ViennaPS/DevSim, since neither
        backend has any species-dependent physics. None if unset.
```

- [ ] **Step 4: Extend `apply_uniform_doping`**

In `tcad/physics/doping.py`:

```python
def apply_uniform_doping(
    result: ProcessResult,
    doping_by_region_cm3: Optional[Dict[str, float]] = None,
    *,
    donor_by_region_cm3: Optional[Dict[str, float]] = None,
    acceptor_by_region_cm3: Optional[Dict[str, float]] = None,
    species_by_region: Optional[Dict[str, tuple]] = None,
) -> ProcessResult:
    """Return a new ProcessResult with uniform doping attached.

    Two mutually additive input shapes, so every existing caller stays
    unchanged:
      - doping_by_region_cm3: {region_name: net_doping_cm3} (original
        shape — net only, donor/acceptor stay None on the region).
      - donor_by_region_cm3 / acceptor_by_region_cm3: {region_name:
        concentration_cm3}, both >= 0. net_doping_cm3 is computed as
        donor - acceptor and the raw donor/acceptor values are kept on
        the DopingRegion. species_by_region, if given, is
        {region_name: (donor_species, acceptor_species)} — label only.

    A region present in BOTH dicts uses the donor/acceptor value (the
    net_doping_cm3-only dict is a fallback for regions not covered by
    the donor/acceptor one, not a second independent source of truth).
    """
    regions = [
        DopingRegion(region=name, net_doping_cm3=value)
        for name, value in (doping_by_region_cm3 or {}).items()
    ]
    donor_regions = set(donor_by_region_cm3 or {}) | set(acceptor_by_region_cm3 or {})
    regions = [r for r in regions if r.region not in donor_regions]
    for name in donor_regions:
        donor = (donor_by_region_cm3 or {}).get(name, 0.0)
        acceptor = (acceptor_by_region_cm3 or {}).get(name, 0.0)
        species = (species_by_region or {}).get(name, (None, None))
        regions.append(
            DopingRegion(
                region=name, net_doping_cm3=donor - acceptor,
                donor_conc_cm3=donor, acceptor_conc_cm3=acceptor,
                donor_species=species[0], acceptor_species=species[1],
            )
        )
    doping = DopingProfile(kind="uniform", regions=regions)
    return replace(result, doping=doping)
```

- [ ] **Step 5: Extend `apply_gaussian_implant_doping`**

```python
def apply_gaussian_implant_doping(
    result: ProcessResult,
    region: str,
    junction_axis: str,
    peak_position_um: float,
    straggle_um: float,
    peak_conc_cm3: Optional[float] = None,
    *,
    donor_peak_conc_cm3: Optional[float] = None,
    acceptor_peak_conc_cm3: Optional[float] = None,
    donor_species: Optional[str] = None,
    acceptor_species: Optional[str] = None,
) -> ProcessResult:
    """Return a new ProcessResult with a 1D Gaussian implant doping
    profile attached to one region.

    Either pass peak_conc_cm3 directly (original shape, signed net),
    or donor_peak_conc_cm3/acceptor_peak_conc_cm3 (both >= 0) -- both
    profiles share peak_position_um/straggle_um (see DopingRegion's
    own docstring for why: no implant-energy model exists to derive
    independent shapes). peak_conc_cm3 is computed as donor - acceptor
    when the donor/acceptor form is used, and is what every downstream
    consumer keeps reading.
    """
    if donor_peak_conc_cm3 is not None or acceptor_peak_conc_cm3 is not None:
        donor = donor_peak_conc_cm3 or 0.0
        acceptor = acceptor_peak_conc_cm3 or 0.0
        peak_conc_cm3 = donor - acceptor
    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        peak_position_um=peak_position_um,
        straggle_um=straggle_um,
        peak_conc_cm3=peak_conc_cm3,
        donor_peak_conc_cm3=donor_peak_conc_cm3,
        acceptor_peak_conc_cm3=acceptor_peak_conc_cm3,
        donor_species=donor_species,
        acceptor_species=acceptor_species,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[doping_region])
    return replace(result, doping=doping)
```

- [ ] **Step 6: Extend `apply_implant_windows_doping`**

```python
def apply_implant_windows_doping(
    result: ProcessResult,
    region: str,
    axis: str,
    background_doping_cm3: Optional[float] = None,
    windows: Optional[List[Dict[str, float]]] = None,
    *,
    donor_background_cm3: Optional[float] = None,
    acceptor_background_cm3: Optional[float] = None,
) -> ProcessResult:
    """Return a new ProcessResult with a background doping plus zero or
    more laterally-windowed implants SUPERPOSED on top, all in one
    region.

    Background: either background_doping_cm3 (original shape, signed
    net) or donor_background_cm3/acceptor_background_cm3 (both >= 0,
    net computed as donor - acceptor).

    Each window dict: either {"min_um", "max_um", "conc_cm3"} (original
    shape, signed net) or {"min_um", "max_um", "donor_conc_cm3",
    "acceptor_conc_cm3"} (both >= 0) -- "conc_cm3" is filled in as
    donor - acceptor either way, so doping_mapping.py and the renderer
    keep reading the same key unchanged.
    """
    if donor_background_cm3 is not None or acceptor_background_cm3 is not None:
        background_doping_cm3 = (donor_background_cm3 or 0.0) - (acceptor_background_cm3 or 0.0)

    resolved_windows = []
    for window in windows or []:
        window = dict(window)
        if "donor_conc_cm3" in window or "acceptor_conc_cm3" in window:
            window["conc_cm3"] = window.get("donor_conc_cm3", 0.0) - window.get("acceptor_conc_cm3", 0.0)
        resolved_windows.append(window)

    doping_region = DopingRegion(
        region=region, junction_axis=axis,
        net_doping_cm3=background_doping_cm3,
        donor_conc_cm3=donor_background_cm3,
        acceptor_conc_cm3=acceptor_background_cm3,
        implant_windows=resolved_windows,
    )
    doping = DopingProfile(kind="implant_windows", regions=[doping_region])
    return replace(result, doping=doping)
```

Check the current signature's parameter ORDER before editing (`background_doping_cm3`/`windows` may currently be required positionals, not defaulted) — adjust existing callers (`tcad_2d_stagewise.py::run_doping`'s Implant Windows branch, `tests/integration/test_implant_windows_doping_real.py`, `tests/unit/test_implant_windows_from_mask_mock.py`) to keep passing them positionally or by keyword exactly as today; giving them `= None` defaults here does not break positional callers as long as the parameter ORDER is unchanged.

- [ ] **Step 7: Run test to verify it passes, then confirm no regression**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_doping_donor_acceptor_all_kinds_real.py`
Expected: PASS.

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gaussian_implant_doping_real.py && PYTHONIOENCODING=utf-8 python tests/integration/test_implant_windows_doping_real.py && PYTHONIOENCODING=utf-8 python tests/unit/test_implant_windows_from_mask_mock.py`
Expected: all PASS, unchanged.

- [ ] **Step 8: Commit**

```bash
git add tcad/mesh/interface.py tcad/physics/doping.py tests/integration/test_doping_donor_acceptor_all_kinds_real.py
git commit -m "feat: independent donor/acceptor input for all 4 doping kinds"
```

---

### Task 8: GUI panel — donor/acceptor fields for Gaussian Implant and Implant Windows

**Files:**
- Modify: `tcad_2d_stagewise.py` (`_make_doping_panel`, `run_doping`)
- Test: Extend `tests/integration/test_gui_doping_donor_acceptor_real.py`

- [ ] **Step 1: Replace the Gaussian Implant panel's single conc field**

In `_make_doping_panel`, in `gaussian_frame`, replace:

```python
        self.dope_gauss_conc_var = self._field(
            gaussian_frame, "Peak conc (cm^-3, signed)", 1.0e17,
        )
```

with:

```python
        self.dope_gauss_donor_var = self._field(
            gaussian_frame, "Donor peak conc (cm^-3, >= 0)", 1.0e17,
        )
        self.dope_gauss_acceptor_var = self._field(
            gaussian_frame, "Acceptor peak conc (cm^-3, >= 0)", 0.0,
        )
        self.dope_gauss_donor_species_var = self._field(
            gaussian_frame, "Donor species (label only, not used in the physics model)", "P",
        )
        self.dope_gauss_acceptor_species_var = self._field(
            gaussian_frame, "Acceptor species (label only, not used in the physics model)", "B",
        )
```

- [ ] **Step 2: Replace the Implant Windows panel's conc fields**

In `windows_frame`, replace the "Background doping (cm^-3, signed)" field and the two "...window conc (cm^-3)" fields with donor/acceptor pairs (background, source, drain), mirroring Step 1's pattern:

```python
        self.dope_iw_donor_bg_var = self._field(
            windows_frame, "Background donor conc (cm^-3, >= 0)", 0.0,
        )
        self.dope_iw_acceptor_bg_var = self._field(
            windows_frame, "Background acceptor conc (cm^-3, >= 0)", 1.0e17,
        )
        # (Source window position fields unchanged)
        self.dope_iw_source_donor_var = self._field(
            windows_frame, "Source window donor conc (cm^-3, >= 0)", 1.0e20,
        )
        self.dope_iw_source_acceptor_var = self._field(
            windows_frame, "Source window acceptor conc (cm^-3, >= 0)", 0.0,
        )
        # (Drain window position fields unchanged)
        self.dope_iw_drain_donor_var = self._field(
            windows_frame, "Drain window donor conc (cm^-3, >= 0)", 1.0e20,
        )
        self.dope_iw_drain_acceptor_var = self._field(
            windows_frame, "Drain window acceptor conc (cm^-3, >= 0)", 0.0,
        )
```

Read the exact current field names/order for the position fields (`Source window min/max`, `Drain window min/max`, lines ~3846-3861 as of this session) before editing, and keep them unchanged — only the three `*_conc_var` fields (background, source, drain) are being split into donor/acceptor pairs.

- [ ] **Step 3: Update `run_doping()`'s Gaussian Implant and Implant Windows branches**

Gaussian branch — replace the single `conc = float(self.dope_gauss_conc_var.get())` read and `apply_gaussian_implant_doping(..., conc)` call with:

```python
            elif kind == "Gaussian Implant":

                region = self.dope_gauss_region_var.get()
                axis = self.dope_gauss_axis_var.get()
                position = float(self.dope_gauss_position_var.get())
                straggle = float(self.dope_gauss_straggle_var.get())
                donor = float(self.dope_gauss_donor_var.get())
                acceptor = float(self.dope_gauss_acceptor_var.get())
                donor_species = self.dope_gauss_donor_species_var.get()
                acceptor_species = self.dope_gauss_acceptor_species_var.get()
                doped_result = apply_gaussian_implant_doping(
                    process_result, region, axis, position, straggle,
                    donor_peak_conc_cm3=donor, acceptor_peak_conc_cm3=acceptor,
                    donor_species=donor_species, acceptor_species=acceptor_species,
                )
                summary = (
                    f"region={region!r} axis={axis!r} position={position} "
                    f"straggle={straggle} donor={donor:.3e}({donor_species}) "
                    f"acceptor={acceptor:.3e}({acceptor_species}) -> "
                    f"peak_net_cm3={donor - acceptor:.3e}"
                )
```

Implant Windows branch — replace the background/source/drain `conc` reads with donor/acceptor pairs, computing each window's `conc_cm3` for the summary string but passing the raw donor/acceptor into `apply_implant_windows_doping`:

```python
            elif kind == "Implant Windows":

                region = self.dope_iw_region_var.get()
                axis = self.dope_iw_axis_var.get()
                donor_bg = float(self.dope_iw_donor_bg_var.get())
                acceptor_bg = float(self.dope_iw_acceptor_bg_var.get())
                source_min = float(self.dope_iw_source_min_var.get())
                source_max = float(self.dope_iw_source_max_var.get())
                source_donor = float(self.dope_iw_source_donor_var.get())
                source_acceptor = float(self.dope_iw_source_acceptor_var.get())
                drain_min = float(self.dope_iw_drain_min_var.get())
                drain_max = float(self.dope_iw_drain_max_var.get())
                drain_donor = float(self.dope_iw_drain_donor_var.get())
                drain_acceptor = float(self.dope_iw_drain_acceptor_var.get())
                windows = [
                    {"min_um": source_min, "max_um": source_max,
                     "donor_conc_cm3": source_donor, "acceptor_conc_cm3": source_acceptor},
                    {"min_um": drain_min, "max_um": drain_max,
                     "donor_conc_cm3": drain_donor, "acceptor_conc_cm3": drain_acceptor},
                ]
                doped_result = apply_implant_windows_doping(
                    process_result, region, axis,
                    donor_background_cm3=donor_bg, acceptor_background_cm3=acceptor_bg,
                    windows=windows,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"background_net={donor_bg - acceptor_bg:.3e} "
                    f"source_net={source_donor - source_acceptor:.3e} "
                    f"drain_net={drain_donor - drain_acceptor:.3e}"
                )
```

Read the EXACT existing variable names for `dope_iw_region_var`/`dope_iw_axis_var`/`dope_iw_source_min_var`/etc. from the current `run_doping()` Implant Windows branch (lines ~4020-4050 as of this session) before writing this replacement, since this plan's names must match the panel's actual field-creation code from Step 2 (which reuses the existing position-field variable names unchanged).

- [ ] **Step 4: Extend the GUI regression test**

Add to `tests/integration/test_gui_doping_donor_acceptor_real.py` two new scenario checks (Gaussian Implant and Implant Windows), mirroring the existing Uniform scenario: set the new donor/acceptor fields, call `app.run_doping()`, assert the resulting `net_doping_cm3`/`peak_conc_cm3` on `app.last_doped_result.doping.regions[0]` equals donor-acceptor, and assert `donor_peak_conc_cm3`/`donor_conc_cm3` etc. are preserved (not just collapsed).

- [ ] **Step 5: Run and verify**

Run: `PYTHONIOENCODING=utf-8 python tests/integration/test_gui_doping_donor_acceptor_real.py`
Expected: PASS, including the two new scenarios.

Run: `PYTHONIOENCODING=utf-8 python tests/run_regression.py`
Expected: baseline 49 (+ this plan's new tests) passed, same 3 pre-existing failures, zero new failures.

- [ ] **Step 6: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_doping_donor_acceptor_real.py
git commit -m "feat: GUI donor/acceptor input for Gaussian Implant and Implant Windows"
```

---

## Explicit scope exclusions (documented, not implemented in this plan)

- **Implant energy, dose, beam voltage/current, tilt/rotation.** No real model in ViennaPS 4.6.2 or DevSim (confirmed by direct introspection). Adding these fields without real computation would either be decorative (violates YAGNI) or require inventing a fake formula (explicitly forbidden). If wanted later, this needs a SEPARATE investigation into whether an approximate textbook model (e.g. LSS-theory-derived Gaussian range/straggle from energy) is worth building as new, clearly-labeled approximate physics — not a backend capability that already exists.
- **Diffusion temperature/time/ambient.** Same reasoning — no backend model. A real Fickian-diffusion approximation (erfc-based profile from D(T)*t) is mathematically implementable without ViennaPS/DevSim support, but is a new physics feature, not part of "donor/acceptor input expansion," and needs its own decision.
- **`implant_windows`'s robust/ramped solve path** (`run_robust_pn_junction_iv_sweep`) does not receive barrier-exclusion windows in Task 4 — it registers NetDoping through its own doping-level-continuation mechanism, and threading exclusion through that ramp safely is separable follow-up work.
- **Doping color overlay concentration-magnitude shading** (vs. today's binary N/P sign color) — not requested with enough specificity to design now; Task 3's per-x accuracy fix stands on its own value.

---

## Self-Review

**Spec coverage:** All 4 numbered problems from the user's approval message have a task group. The 10 "중요한 구현 원칙" are satisfied: (1) plan-first, no code yet; (2) test convention confirmed (`tests/run_regression.py`, no pytest) and stated in Global Constraints; (3) no task touches `resolve.py`/`wafer_state.py`/`intent.py`; (4) no fake parameters — explicit scope-exclusion section; (5) every task group states 원인/수정파일/수정함수/테스트/회귀위험; (6) writing-plans skill used for this document; (7) tasks are single-commit sized; (8) every task ends with a real regression run distinguishing new failures from the 49/3 baseline; (9) every task separates "renders differently" from "geometry is different" — Task 1 has two SEPARATE tests (DevSim-level Task 2, renderer-level Task 3); Task 3's test measures raw mesh geometry independent of the log string; (10) this document is the plan-only deliverable, awaiting approval before execution.

**Placeholder scan:** No TBD/TODO. Two spots explicitly ask the implementer to re-read current line numbers/variable names before editing (Task 5 Step 3, Task 8 Step 3) rather than assuming stale ones — this is intentional given the size of `tcad_2d_stagewise.py` and this session's own edits shifting line numbers repeatedly; it names exactly which grep/read to run, not "figure it out."

**Type consistency:** `derive_barrier_covered_windows()`'s return shape (`List[Dict[str,float]]` with `"min_um"/"max_um"` keys) is used identically in Tasks 1, 2, and 4. `_material_surface_profile()`'s tuple shape `(x_lo, x_hi, y_top, y_bot)` is used identically in its test and in Task 3's renderer integration. `apply_doping()`'s new `exclude_windows`/`exclude_axis` params match between Task 2's implementation and Task 4's call site. `DopingRegion`'s new field names (`donor_peak_conc_cm3`, etc.) match between Task 7's dataclass and its test.
