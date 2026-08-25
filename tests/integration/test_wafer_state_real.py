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
