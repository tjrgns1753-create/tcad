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
from typing import Any, Dict, List, Optional, Tuple

from tcad.physics.dopant_profile import DopantProfile

# Which material-change kind a process category's own physics is known to
# perform, for the purpose of deciding a dopant's fate when its declared
# host_material is no longer exposed at a query point (spec Sec3/Sec6).
# A category absent from this table (e.g. "deposition", "doping", or
# anything not yet classified) defaults to UNSUPPORTED_BY_MODEL, NEVER to
# a silent zero -- see WaferState._polarity_sum.
MATERIAL_CHANGE_KIND_BY_CATEGORY: Dict[str, str] = {
    "etching": "removal",
    "oxidation": "conversion",
}


@dataclass(frozen=True)
class DopingQueryResult:
    donor_concentration: float
    acceptor_concentration: float
    net_doping: float
    physics_status: Optional[dict]


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
    # The MOST RECENTLY run process step's category only -- NOT a
    # per-location/per-profile provenance record (final-review Fix 7,
    # 2026-09-03 dopant-state-unification). Consequence: if an
    # unclassified-category step (e.g. "doping", which has no entry in
    # MATERIAL_CHANGE_KIND_BY_CATEGORY) runs AFTER a removal-causing
    # etch, a query against THIS state cannot recall that the earlier
    # removal is still real and permanent -- _polarity_sum() will report
    # UNSUPPORTED_BY_MODEL for that profile instead of the correct
    # "genuinely removed, zero" (safe/conservative, never silently
    # wrong, but it does lose real information). First characterized in
    # tests/integration/test_ce1_order_sensitive_geometry_real.py's own
    # "Problem 3" docstring section -- see that test for the fuller
    # writeup.
    last_step_category: Optional[str] = None

    @staticmethod
    def query(domain: Any, dopant_profiles: Tuple[DopantProfile, ...] = (),
              last_step_category: Optional[str] = None) -> "WaferState":
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
            last_step_category=last_step_category,
        )

    @staticmethod
    def from_process_result(
        result: "ProcessResult", dopant_profiles: Tuple[DopantProfile, ...] = (),
        last_step_category: Optional[str] = None,
    ) -> "WaferState":
        """Build WaferState geometry from a real exported mesh FILE via
        ProcessResult (volume_mesh_path/material_field/material_regions)
        instead of a live ViennaPS Domain -- the real construction path
        for the GUI's doping flow (run_doping() never holds a live
        domain; it only ever has a mesh file path, per this task's own
        read of the real production code). Reuses the EXACT real
        triangle-tag-to-name-resolution pattern
        tcad/device/devsim/mesh_import.py's
        derive_barrier_covered_windows() already uses.

        SAFETY CONTRACT (user's own final review, point 1): this
        constructor is GEOMETRY-ONLY -- it has no memory of any prior
        WaferState and does NOT know about "the accumulated dopant
        list" by itself. Calling it directly with the default
        `dopant_profiles=()` silently produces a state with NO dopant
        profiles at all, even if a real prior state existed. This is
        safe ONLY for throwaway, geometry-only diagnostics (e.g.
        checking exposed_material_at at some x) whose result is NEVER
        assigned back to the real accumulating state variable
        (`app.wafer_state`, or any `stateN` a test keeps building on).
        The ONLY sanctioned way to build/advance the real accumulating
        state is `advance_wafer_state()` (in
        tcad/physics/wafer_state_accumulation.py), which explicitly
        threads `prior_state.dopant_profiles + this_step_profiles`
        through this constructor -- never call this constructor
        directly for that purpose. (The tag->name resolution itself is
        `tag_to_name = {region.tag: region.name for region in
        result.material_regions}`, verbatim from that function.)
        """
        import meshio

        tag_to_name = {region.tag: region.name for region in result.material_regions}
        mesh = meshio.read(result.volume_mesh_path)
        triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)

        cells = []
        if triangle_block is not None and result.material_field in mesh.cell_data:
            block_index = mesh.cells.index(triangle_block)
            tags = mesh.cell_data[result.material_field][block_index]
            points = mesh.points
            for triangle, tag in zip(triangle_block.data, tags):
                corners = points[triangle]
                name = tag_to_name.get(int(tag), f"?{int(tag)}")
                cells.append(_Cell(
                    x_min=corners[:, 0].min(), x_max=corners[:, 0].max(),
                    y_max=corners[:, 1].max(), material=name,
                ))

        materials = tuple(sorted({c.material for c in cells}))
        return WaferState(
            materials=materials,
            stack=tuple(LayerInfo(m, i) for i, m in enumerate(materials)),
            # grid_delta_um is not derivable from a bare exported mesh
            # file (no recipe/domain object to read it from here) --
            # confirmed by reading net_doping_at()/exposed_material_at()
            # (Task 2): neither reads grid_delta_um at all, only
            # _cells/dopant_profiles. 0.0 is a real, inert value for
            # this construction path, not a guess standing in for
            # missing logic -- _thin_layer_positions (the ONLY consumer
            # of grid_delta_um) is a live-domain-only diagnostic and is
            # never computed here (_thin_x=() below, matching that this
            # constructor has no level-set access to derive it from).
            grid_delta_um=0.0,
            _cells=tuple(cells), _thin_x=(),
            dopant_profiles=dopant_profiles, last_step_category=last_step_category,
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

    def _polarity_sum(
        self, x_um: float, depth_um: float, polarity: str, exposed: Optional[str],
    ) -> Tuple[float, List[dict]]:
        """`exposed` is `self.exposed_material_at(x_um)`, computed ONCE
        by the caller (net_doping_at, final-review Fix 6) -- it depends
        only on x_um, not on which profile/polarity is being checked, so
        recomputing it per profile (the old behavior) meant up to
        2 * len(dopant_profiles) redundant full linear scans over
        self._cells per net_doping_at() call. Passed in, never
        recomputed here."""
        total = 0.0
        entries: List[dict] = []
        change_kind = MATERIAL_CHANGE_KIND_BY_CATEGORY.get(self.last_step_category or "")
        for p in self.dopant_profiles:
            if p.polarity != polarity:
                continue
            if exposed == p.host_material:
                total += p.concentration_at(x_um, depth_um)
                continue
            # host_material absent here -- three-way test, spec Sec3.
            if change_kind == "removal":
                # A real, physically meaningful geometry-gated zero
                # (spec Sec6 state A) -- ONLY for a category explicitly
                # known to only ever take material away.
                continue
            # Default is UNSUPPORTED_BY_MODEL, not zero -- covers both
            # "conversion" (oxidation) AND any category with no table
            # entry at all. Never silently assume an unclassified
            # category means removal; that would be exactly the kind
            # of undisclosed guess CLAUDE.md's Core Physics Requirement
            # forbids. A future category genuinely needing "removal"
            # semantics gets added to MATERIAL_CHANGE_KIND_BY_CATEGORY
            # explicitly, not by falling through a default.
            entries.append({
                "parameter": "dopant_fate_at_material_change",
                "material": p.species, "resolution": "UNSUPPORTED_BY_MODEL",
                "provenance": "DERIVED",
                "note": f"{p.host_material} no longer exposed at this point "
                        f"(category={self.last_step_category!r}, classified as "
                        f"a {change_kind or 'UNCLASSIFIED'} material change) and "
                        f"no dopant segregation/fate model is registered -- "
                        f"contribution excluded, NOT zero",
            })
        return total, entries

    def net_doping_at(self, x_um: float, depth_um: float = 0.0) -> DopingQueryResult:
        """The ONE public doping query. Read .donor_concentration /
        .acceptor_concentration / .net_doping / .physics_status off the
        result -- there is no separate donor-only or acceptor-only
        method (removed: their names promised a scalar float, but the
        real computation and the UNSUPPORTED_BY_MODEL disclosure
        requirement (spec Sec6) apply identically to every one of
        those values, so splitting them apart either duplicates the
        work or hides the same status three different callers would
        otherwise have to remember to check separately)."""
        # Computed ONCE here, not once per profile inside _polarity_sum
        # (final-review Fix 6) -- exposed_material_at() is a full linear
        # scan over self._cells and depends only on x_um.
        exposed = self.exposed_material_at(x_um)
        donor, donor_gaps = self._polarity_sum(x_um, depth_um, "donor", exposed)
        acceptor, acceptor_gaps = self._polarity_sum(x_um, depth_um, "acceptor", exposed)
        entries = donor_gaps + acceptor_gaps
        physics_status = None
        if entries:
            physics_status = {"resolution": "UNSUPPORTED_BY_MODEL", "entries": entries, "notes": []}
        return DopingQueryResult(
            donor_concentration=donor, acceptor_concentration=acceptor,
            net_doping=donor - acceptor, physics_status=physics_status,
        )
