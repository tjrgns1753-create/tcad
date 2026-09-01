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

from tcad.physics.dopant_profile import DopantProfile


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
    dopant_profiles: Tuple[DopantProfile, ...] = ()

    @staticmethod
    def query(domain: Any, dopant_profiles: Tuple[DopantProfile, ...] = ()) -> "WaferState":
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
            dopant_profiles=dopant_profiles,
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

    def donor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> float:
        return sum(
            p.concentration_at(x_um, depth_um)
            for p in self.dopant_profiles if p.polarity == "donor"
        )

    def acceptor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> float:
        return sum(
            p.concentration_at(x_um, depth_um)
            for p in self.dopant_profiles if p.polarity == "acceptor"
        )

    def net_doping_at(self, x_um: float, depth_um: float = 0.0) -> float:
        """Derived, always -- never a stored field (spec 2026-09-01,
        section 2: process-layer state stays donor/acceptor-separated;
        only a query like this one collapses it to a signed net)."""
        return self.donor_concentration_at(x_um, depth_um) - self.acceptor_concentration_at(x_um, depth_um)
