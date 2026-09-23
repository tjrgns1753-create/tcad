#!/usr/bin/env python3
"""Tier 1-2 Rev.3.1: positive-time LOCOS pad-oxide resolution probe.

This is an audit-only executable.  It calls the production
``LocosOxidation.run`` path with a real ViennaPS 4.6.2 backend and uses a
temporary ``vps.Process`` spy only to export the domain immediately before
and after ``Process.apply``.  No production module is modified.

Run one grid per process so a stalled/failed coarse-grid case cannot erase
the fine-grid controls::

    python investigate_rev3_1_locos_positive_time.py OUT_DIR GRID_UM

The physical recipe is otherwise identical in all cases: explicit 20 nm
pad oxide, dry O2, 1000 C, and 0.5 h oxidation.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tcad.backends.viennaps import session  # noqa: E402
from tcad.backends.viennaps.io import save_locos_volume_mesh  # noqa: E402
import viennaps as vps  # noqa: E402


COMPLETE_RE = re.compile(
    r"Oxidation: LOCOS complete — (\d+) substep\(s\), ([\d.]+) hr simulated"
)
BA_RE = re.compile(r"B=([\d.eE+-]+) µm²/hr, B/A=([\d.eE+-]+) µm/hr")
SEED_RE = re.compile(r"no SiO₂ layer found; seeding ([\d.]+) µm native oxide")

FIELD_X_UM = 0.0
PAD_OXIDE_UM = 0.02
TIME_HOURS = 0.5


def _native_report(domain) -> dict:
    materials = sorted(str(m).split("'")[1] for m in domain.getMaterialsInDomain())
    return {
        "materials_native": materials,
        "num_level_sets": int(domain.getNumberOfLevelSets()),
    }


def _vertical_triangle_interval(points, x_um: float, tol: float = 1.0e-10):
    """Return the non-zero y interval cut from one triangle by x=x_um."""
    xs = [float(p[0]) for p in points]
    if x_um < min(xs) - tol or x_um > max(xs) + tol:
        return None

    ys = []
    for index in range(3):
        p0 = points[index]
        p1 = points[(index + 1) % 3]
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
        if abs(x1 - x0) <= tol:
            if abs(x_um - x0) <= tol:
                ys.extend((y0, y1))
            continue
        if x_um < min(x0, x1) - tol or x_um > max(x0, x1) + tol:
            continue
        fraction = (x_um - x0) / (x1 - x0)
        if -tol <= fraction <= 1.0 + tol:
            ys.append(y0 + fraction * (y1 - y0))

    unique = []
    for value in sorted(ys):
        if not unique or abs(value - unique[-1]) > tol:
            unique.append(value)
    if len(unique) < 2 or unique[-1] - unique[0] <= tol:
        return None
    return unique[0], unique[-1]


def _material_summary(mesh, material_tag: int, x_um: float) -> dict | None:
    triangle_block = next(c for c in mesh.cells if c.type == "triangle")
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data["Material"][block_index]

    point_ids = set()
    intervals = []
    for tag, triangle in zip(tags, triangle_block.data):
        if int(tag) != material_tag:
            continue
        point_ids.update(int(i) for i in triangle)
        cut = _vertical_triangle_interval([mesh.points[int(i)] for i in triangle], x_um)
        if cut is not None:
            intervals.append(cut)

    if not point_ids:
        return None
    xs = [float(mesh.points[i][0]) for i in point_ids]
    ys = [float(mesh.points[i][1]) for i in point_ids]
    cross_section = None
    if intervals:
        cross_section = {
            "x_um": x_um,
            "y_min_um": min(value[0] for value in intervals),
            "y_max_um": max(value[1] for value in intervals),
            "intersected_triangles": len(intervals),
        }
    return {
        "bounds_um": {
            "x_min": min(xs),
            "x_max": max(xs),
            "y_min": min(ys),
            "y_max": max(ys),
        },
        "point_count": len(point_ids),
        "field_cross_section": cross_section,
    }


def snapshot_locos(domain, output_base: Path, module) -> dict:
    import meshio

    materials = [module.Material.Si, module.Material.SiO2, module.Material.Mask]
    wrap_flags = [False, True, False]
    mesh_path = save_locos_volume_mesh(
        domain,
        materials,
        wrap_flags,
        output_base,
        floor_depth_um=0.5,
    )
    mesh = meshio.read(mesh_path)
    summaries = {
        name: _material_summary(mesh, int(getattr(module.Material, name)), FIELD_X_UM)
        for name in ("Si", "SiO2", "Mask")
    }
    return {
        **_native_report(domain),
        "mesh_path": str(mesh_path),
        "materials": summaries,
    }


@contextmanager
def process_spy(captures: dict, output_dir: Path, label: str, module):
    original_process = vps.Process

    class _SpyProcess:
        def __init__(self, domain, model):
            self._domain = domain
            self._real = original_process(domain, model)

        def apply(self):
            captures["before_apply"] = snapshot_locos(
                self._domain, output_dir / f"{label}_before", module
            )
            result = self._real.apply()
            captures["after_apply"] = snapshot_locos(
                self._domain, output_dir / f"{label}_after", module
            )
            return result

    vps.Process = _SpyProcess
    try:
        yield
    finally:
        vps.Process = original_process


@contextmanager
def capture_native_stdout():
    """Capture the C++ backend's file-descriptor-level stdout."""
    sys.stdout.flush()
    stdout_fd = sys.stdout.fileno()
    saved_fd = os.dup(stdout_fd)
    temporary = tempfile.TemporaryFile(mode="w+b")
    os.dup2(temporary.fileno(), stdout_fd)
    try:
        yield temporary
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, stdout_fd)
        os.close(saved_fd)
        temporary.seek(0)


def deal_grove_final_thickness(
    b_um2_per_hour: float,
    b_over_a_um_per_hour: float,
    initial_thickness_um: float,
    time_hours: float,
) -> float:
    a_um = b_um2_per_hour / b_over_a_um_per_hour
    rhs = (
        initial_thickness_um**2
        + a_um * initial_thickness_um
        + b_um2_per_hour * time_hours
    )
    return (-a_um + math.sqrt(a_um**2 + 4.0 * rhs)) / 2.0


def _cross_section(snapshot: dict, material: str) -> dict:
    value = snapshot["materials"][material]
    if value is None or value["field_cross_section"] is None:
        raise RuntimeError(f"No {material} cross-section at x={FIELD_X_UM} um")
    return value["field_cross_section"]


def run_case(output_dir: Path, grid_delta_um: float) -> dict:
    from tcad.process import registry
    import importlib

    importlib.import_module("tcad.process.oxidation.locos")
    locos_class = registry.get("oxidation", "locos")
    module = session.require_viennaps()

    recipe = {
        "grid_delta_um": grid_delta_um,
        "x_extent_um": 3.0,
        "y_extent_um": 2.0,
        "mask_left_um": 1.0,
        "mask_right_um": 2.0,
        "pr_thickness_um": 0.5,
        "pad_oxide_thickness_um": PAD_OXIDE_UM,
        "oxidant": "Dry",
        "temperature_c": 1000.0,
        "mask_material": "Mask",
        "silicon_depth_um": 1.0,
        "time_hours": TIME_HOURS,
    }
    label = f"grid_{grid_delta_um:.3f}".replace(".", "p")
    captures = {}
    started = time.time()
    error = None
    native_log = ""
    with tempfile.TemporaryDirectory() as process_output:
        step = locos_class()
        try:
            with capture_native_stdout() as buffer:
                with process_spy(captures, output_dir, label, module):
                    step.run(recipe, process_output)
            native_log = buffer.read().decode("utf-8", errors="replace")
        except Exception as exc:  # retained as audit evidence, not hidden
            error = f"{type(exc).__name__}: {exc}"
            try:
                native_log = buffer.read().decode("utf-8", errors="replace")
            except Exception:
                pass
    elapsed = time.time() - started

    (output_dir / f"{label}_native.log").write_text(native_log, encoding="utf-8")
    complete_match = COMPLETE_RE.search(native_log)
    ba_match = BA_RE.search(native_log)
    seed_match = SEED_RE.search(native_log)
    parsed_log = {
        "substeps": int(complete_match.group(1)) if complete_match else None,
        "hours_simulated": float(complete_match.group(2)) if complete_match else None,
        "b_um2_per_hour": float(ba_match.group(1)) if ba_match else None,
        "b_over_a_um_per_hour": float(ba_match.group(2)) if ba_match else None,
        "native_seed_message_um": float(seed_match.group(1)) if seed_match else None,
        "completion_log_found": complete_match is not None,
    }

    result = {
        "audit": "Tier 1-2 Rev.3.1 positive-time LOCOS pad-oxide resolution",
        "status": "ERROR" if error else "COMPLETED",
        "error": error,
        "elapsed_seconds": elapsed,
        "recipe": recipe,
        "field_x_um": FIELD_X_UM,
        "parsed_native_log": parsed_log,
        "before_apply": captures.get("before_apply"),
        "after_apply": captures.get("after_apply"),
    }

    if error is None:
        before_si = _cross_section(captures["before_apply"], "Si")
        before_oxide = _cross_section(captures["before_apply"], "SiO2")
        after_si = _cross_section(captures["after_apply"], "Si")
        after_oxide = _cross_section(captures["after_apply"], "SiO2")

        # The wrapped SiO2 export's tagged lower bound is not the moved
        # Si/SiO2 interface after LOCOS advection.  The physical thickness at
        # one x is bounded by the ambient-facing oxide top and the Si top,
        # both sampled at that same x.  At grid=0.02, for example, the oxide
        # tag still starts at y=0 while the real Si top is at y=-0.00826 um;
        # using the tag span would violate the exact geometric identity
        # oxide_growth = ambient_displacement + silicon_consumed.
        initial_oxide = before_oxide["y_max_um"] - before_si["y_max_um"]
        final_oxide = after_oxide["y_max_um"] - after_si["y_max_um"]
        oxide_growth = final_oxide - initial_oxide
        ambient_displacement = after_oxide["y_max_um"] - before_oxide["y_max_um"]
        silicon_consumed = before_si["y_max_um"] - after_si["y_max_um"]
        ratio = oxide_growth / silicon_consumed if silicon_consumed > 0.0 else None

        predicted = None
        if parsed_log["b_um2_per_hour"] and parsed_log["b_over_a_um_per_hour"]:
            predicted = deal_grove_final_thickness(
                parsed_log["b_um2_per_hour"],
                parsed_log["b_over_a_um_per_hour"],
                PAD_OXIDE_UM,
                TIME_HOURS,
            )
        result["field_measurement"] = {
            "initial_oxide_thickness_um": initial_oxide,
            "final_oxide_thickness_um": final_oxide,
            "initial_exported_oxide_tag_span_um": (
                before_oxide["y_max_um"] - before_oxide["y_min_um"]
            ),
            "final_exported_oxide_tag_span_um": (
                after_oxide["y_max_um"] - after_oxide["y_min_um"]
            ),
            "oxide_growth_um": oxide_growth,
            "ambient_surface_displacement_um": ambient_displacement,
            "silicon_consumed_um": silicon_consumed,
            "growth_identity_residual_um": (
                oxide_growth - ambient_displacement - silicon_consumed
            ),
            "oxide_growth_over_silicon_consumed": ratio,
            "deal_grove_final_thickness_um": predicted,
            "deal_grove_error_um": final_oxide - predicted if predicted is not None else None,
            "deal_grove_relative_error_percent": (
                100.0 * (final_oxide - predicted) / predicted
                if predicted not in (None, 0.0)
                else None
            ),
        }
    return result


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} OUT_DIR GRID_DELTA_UM")
    output_dir = Path(sys.argv[1]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    grid_delta_um = float(sys.argv[2])
    result = run_case(output_dir, grid_delta_um)
    label = f"grid_{grid_delta_um:.3f}".replace(".", "p")
    result_path = output_dir / f"rev3_1_{label}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "result_path": str(result_path),
        "status": result["status"],
        "elapsed_seconds": result["elapsed_seconds"],
        "parsed_native_log": result["parsed_native_log"],
        "field_measurement": result.get("field_measurement"),
    }, indent=2))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
