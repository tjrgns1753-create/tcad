#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arbitrary multi-span mask (`mask_spans_um`) — real ViennaPS 4.6.2,
through the real production entry point (registry -> ProcessStep.run()).

`MakeTrench` can only build one pattern: `opaque | open | opaque`, a
single centred window. A MOSFET source/drain implant mask is the
COMPLEMENT — `open | opaque(gate/channel) | open`, one central opaque
span — which `MakeTrench` cannot express at all. This is the geometry
gap that made `implant_windows` doping numbers float free of any real
mask feature.

Checks, all measured from the real exported mesh:
  1. a single CENTRAL opaque span builds, and the mask lands exactly
     where the recipe asked (the pattern MakeTrench cannot produce).
  2. it survives a real chained process step with no level set
     destroyed -- the ViennaLS Advect containment precondition that
     the LOCOS chaining bug was caused by violating. A mask-last
     ordering fails this outright (measured: empty export), so this is
     a real guard, not a formality.
  3. two spans covering everything outside a window reproduce real
     MakeTrench's own areas to within one grid cell -- i.e.
     mask_spans_um is a strict generalization, so the existing
     single-window recipe path is not a different geometry.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session
from tcad.process import registry

assert session.is_available(), "ViennaPS must be installed for this test"

GRID = 0.05
X_EXTENT = 6.0
MASK_H = 0.4
GATE = (-0.8, 0.8)          # central opaque span: the MOSFET S/D mask
FLOOR = 1.0

BASE = {
    "grid_delta_um": GRID,
    "x_extent_um": X_EXTENT,
    "y_extent_um": 3.0,
    "mask_left_um": 2.0,      # unused on the mask_spans_um path, kept so
    "mask_right_um": 4.0,     # the recipe shape matches every other test
    "pr_thickness_um": MASK_H,
    "etch_time_s": 2.0,
    "rate": -0.05,
    "mask_material": "Mask",
    "silicon_depth_um": FLOOR,
}


def measure(mesh_path, module):
    """Per-material area, and the mask's x-extent at its own top half."""
    mesh = meshio.read(mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    areas, spans = {}, {}
    for tri, tag in zip(block.data, tags):
        name = str(module.Material(int(tag))).split("'")[1]
        a, b, c = (mesh.points[i][:2] for i in tri)
        areas[name] = areas.get(name, 0.0) + abs(
            (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        ) / 2.0
        for i in tri:
            x, y = float(mesh.points[i][0]), float(mesh.points[i][1])
            if y > MASK_H * 0.5:
                lo, hi = spans.get(name, (1e9, -1e9))
                spans[name] = (min(lo, x), max(hi, x))
    return areas, spans


def main():
    module = session.require_viennaps()
    half_x = X_EXTENT / 2.0

    # --- 1: the pattern MakeTrench cannot build -------------------------
    step = registry.get("etching", "isotropic")()
    geometry = step.prepare_domain({**BASE, "mask_spans_um": [list(GATE)]})
    points_before = [ls.getNumberOfPoints() for ls in geometry.getLevelSets()]
    from tcad.backends.viennaps.io import save_volume_mesh

    with tempfile.TemporaryDirectory() as tmp:
        path = save_volume_mesh(geometry, Path(tmp) / "m", floor_depth_um=FLOOR)
        areas, spans = measure(path, module)

    assert "Mask" in areas and "Si" in areas, f"materials missing: {sorted(areas)}"
    mask_lo, mask_hi = spans["Mask"]
    assert abs(mask_lo - GATE[0]) < GRID and abs(mask_hi - GATE[1]) < GRID, (
        f"central mask span landed at ({mask_lo:.4f}, {mask_hi:.4f}), "
        f"recipe asked for {GATE}"
    )
    expected_mask_area = (GATE[1] - GATE[0]) * MASK_H
    assert abs(areas["Mask"] - expected_mask_area) < GRID * MASK_H * 2, (
        f"mask area {areas['Mask']:.5f} vs expected "
        f"{expected_mask_area:.5f} (span width x mask height)"
    )
    print(f"[1/3] central opaque span built: mask x=({mask_lo:.4f}, {mask_hi:.4f}) "
          f"== requested {GATE}, area={areas['Mask']:.5f} "
          f"(expected {expected_mask_area:.5f}) -- the 'open|opaque|open' "
          f"pattern MakeTrench cannot produce")

    # --- 2: survives a real chained step (Advect precondition) ----------
    chained = registry.get("etching", "isotropic")(inherited_domain=geometry)
    with tempfile.TemporaryDirectory() as tmp:
        result = chained.run(dict(BASE), tmp)
        chained_areas, _ = measure(result["final_mesh"], module)
    points_after = [ls.getNumberOfPoints() for ls in geometry.getLevelSets()]

    assert 0 not in points_after, (
        f"a level set was destroyed by the chained step: {points_before} -> "
        f"{points_after} -- Advect's containment precondition is violated"
    )
    assert "Mask" in chained_areas and "Si" in chained_areas, (
        f"chained export lost a material: {sorted(chained_areas)}"
    )
    assert chained_areas["Si"] < areas["Si"], (
        "the chained etch must actually remove Si -- preserving materials "
        "by making the step a no-op would not count"
    )
    print(f"[2/3] chained etch OK: level sets {points_before} -> {points_after} "
          f"(none destroyed), Si {areas['Si']:.5f} -> "
          f"{chained_areas['Si']:.5f} (real etch), Mask preserved")

    # --- 3: strict generalization of MakeTrench -------------------------
    window = (-0.8, 0.8)
    trench_step = registry.get("etching", "isotropic")()
    trench_geom = trench_step.prepare_domain({
        **BASE, "mask_left_um": 2.0, "mask_right_um": 2.0 + (window[1] - window[0]),
    })
    spans_step = registry.get("etching", "isotropic")()
    spans_geom = spans_step.prepare_domain({
        **BASE,
        "mask_spans_um": [[-half_x, window[0]], [window[1], half_x]],
    })
    with tempfile.TemporaryDirectory() as tmp:
        t_areas, _ = measure(
            save_volume_mesh(trench_geom, Path(tmp) / "t", floor_depth_um=FLOOR), module)
        s_areas, _ = measure(
            save_volume_mesh(spans_geom, Path(tmp) / "s", floor_depth_um=FLOOR), module)

    for name in ("Mask", "Si"):
        t, s = t_areas[name], s_areas[name]
        # One grid cell of area is the discretization floor for two
        # constructions that rasterize the same shape differently.
        assert abs(t - s) < GRID * GRID * 4, (
            f"{name}: MakeTrench={t:.5f} vs mask_spans_um={s:.5f} -- "
            f"differ by more than grid discretization"
        )
    print(f"[3/3] strict generalization confirmed: "
          f"Mask {t_areas['Mask']:.5f} vs {s_areas['Mask']:.5f}, "
          f"Si {t_areas['Si']:.5f} vs {s_areas['Si']:.5f} "
          f"(MakeTrench vs equivalent 2-span)")

    print()
    print("MULTI-SPAN MASK (arbitrary opaque spans, MOSFET-shaped "
          "open|opaque|open pattern, chain-safe, strict MakeTrench "
          "generalization) VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
