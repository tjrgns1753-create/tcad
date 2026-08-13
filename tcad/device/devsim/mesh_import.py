#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Import a canonical ProcessResult into DevSim as a device.

This module only ever imports ProcessResult (tcad.mesh.interface) and
devsim — it never imports viennaps or any other process backend. That
boundary is intentional: swapping the process backend that produced
ProcessResult, or adding a different device backend alongside DevSim,
should not require touching this file's counterpart on the other side.

Real API used (verified against installed DevSim 2.10.1 — confirmed by
running this exact sequence against a real ViennaPS-generated mesh, not
guessed from docs):

    devsim.create_gmsh_mesh(mesh=, coordinates=, elements=, physical_names=)
    devsim.add_gmsh_region(gmsh_name=, mesh=, region=, material=)
    devsim.add_gmsh_contact(gmsh_name=, mesh=, name=, material=, region=)
    devsim.finalize_mesh(mesh=)
    devsim.create_device(mesh=, device=)

Two things confirmed only by real execution (not documented anywhere):
  - `coordinates` and `elements` are FLAT lists, not nested — e.g. a
    triangle element is 5 flat entries [2, physical_index, n0, n1, n2]
    (2 = triangle, per create_gmsh_mesh's own docstring), not a tuple
    or sub-list. Verified by successfully creating a device this way
    and reading back get_region_list()/get_dimension().
  - A boundary edge may only be added to a contact if EVERY triangle
    touching it belongs to that contact's region — mixing regions on
    one contact edge causes DevSim to segfault (reproduced once,
    fixed by grouping boundary edges by their owning triangle's
    material tag before building contacts, not just by geometric
    position).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tcad.device.devsim import backend
from tcad.mesh.interface import ProcessResult


@dataclass
class ImportedDevice:
    device: str
    mesh: str
    regions: List[str] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)


def import_process_result(
    result: ProcessResult,
    mesh_name: str,
    device_name: str,
    material_map: Optional[Dict[str, str]] = None,
    contact_regions: Optional[List[str]] = None,
    contact_axis: str = "x",
    length_scale_to_cm: float = 1.0,
    interface_region_pairs: Optional[List[tuple]] = None,
    contact_sides: Optional[Dict[str, str]] = None,
) -> ImportedDevice:
    """Import a ProcessResult's volume mesh into DevSim as a device.

    material_map : optional {region_name: devsim_material_name} override.
        Defaults to using the region name itself as the DevSim material
        label (e.g. region "Si" -> material "Si") — DevSim's own
        set_material()/add_gmsh_region() docstrings only require this
        to be a string with no fixed vocabulary at this API level, so
        no default mapping to e.g. "Silicon" is invented here.
    contact_regions : optional list of region names to auto-derive
        boundary contacts for (one "<region>_<axis>min" and one
        "<region>_<axis>max" contact per region, wherever that region
        actually touches the domain's bounding-box extreme along
        `contact_axis`). Omit for mesh/region import only, with no
        contacts — the minimal case.
    contact_axis : "x", "y", or "z".
    length_scale_to_cm : multiplies every mesh coordinate before import.
        Default 1.0 (no conversion) — matches every existing caller's
        behavior from Phases 5-7 exactly, so it's not a breaking change.
        DevSim's own official silicon parameters (permittivity,
        mobility — see tcad.device.devsim.semiconductor_equation) are
        calibrated assuming coordinates in cm; ProcessResult.units is
        "um" (see tcad/mesh/interface.py), so real semiconductor-physics
        callers (Phase 8) should pass 1e-4 here. Confirmed necessary by
        real execution: with um-scale coordinates, a real doping-based
        Poisson equilibrium solve on a ViennaPS-imported mesh failed to
        converge; converting to cm fixed it — see
        tests/test_phase8_pn_junction_real.py.
    interface_region_pairs : optional list of (region_a, region_b)
        name tuples (Phase 9). For each pair, edges touched by exactly
        two triangles — one from each region — are registered as a
        DevSim interface named "{region_a}_{region_b}_interface" (real
        API: devsim.add_gmsh_interface(gmsh_name=, mesh=, name=,
        region0=, region1=), confirmed against installed DevSim 2.10.1
        and matches devsim_data/examples/mobility/gmsh_mos2d.py's own
        usage). Needed for e.g. a real Oxide/Si MOS interface — omit
        for single-material devices (every prior phase).
    contact_sides : optional {region_name: "min"|"max"|"both"} — which
        side(s) along contact_axis to build a contact for. Default
        "both" (matches every existing caller's behavior). A curved
        real growth front (e.g. thermal oxidation's top surface) can
        put a few boundary edges near the *other* region's extreme too
        (found by real execution, near a triple point where two
        regions and the domain boundary meet) — restricting to the one
        physically-real side avoids registering that spurious contact.
    """
    module = backend.require_devsim()

    try:
        import meshio
    except ImportError as exc:
        raise RuntimeError(
            "meshio is required to import process meshes into DevSim.\n"
            "Install it first:\n"
            "python -m pip install meshio"
        ) from exc

    mesh = meshio.read(result.volume_mesh_path)

    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise ValueError(f"No triangle cells found in mesh: {result.volume_mesh_path}")

    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]
    points = mesh.points * length_scale_to_cm

    tag_to_name = {region.tag: region.name for region in result.material_regions}

    # Group boundary edges (touched by exactly one triangle) by that
    # triangle's material tag, so a contact never spans two regions.
    edge_owner_tags: Dict[tuple, List[int]] = defaultdict(list)
    for tri, tag in zip(triangles, tags):
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            edge_owner_tags[key].append(int(tag))

    boundary_edges_by_tag: Dict[int, List[tuple]] = defaultdict(list)
    for edge, owners in edge_owner_tags.items():
        if len(owners) == 1:
            boundary_edges_by_tag[owners[0]].append(edge)

    physical_names: List[str] = []
    name_to_index: Dict[str, int] = {}

    def physical_index(name: str) -> int:
        if name not in name_to_index:
            name_to_index[name] = len(physical_names)
            physical_names.append(name)
        return name_to_index[name]

    elements: List[float] = []
    for tri, tag in zip(triangles, tags):
        idx = physical_index(tag_to_name[int(tag)])
        elements += [2, idx, int(tri[0]), int(tri[1]), int(tri[2])]

    contact_defs: List[tuple] = []  # (contact_name, region_name)
    if contact_regions:
        axis_index = {"x": 0, "y": 1, "z": 2}[contact_axis]
        coords_axis = points[:, axis_index]

        for region_name in contact_regions:
            matching_tags = [t for t, n in tag_to_name.items() if n == region_name]
            if not matching_tags:
                continue
            region_boundary = boundary_edges_by_tag.get(matching_tags[0], [])
            if not region_boundary:
                continue

            # Region-local extremes (not the whole mesh's bounding box):
            # a region's own top/bottom surface is a contact candidate
            # even if it doesn't reach the overall domain boundary (e.g.
            # a thin oxide layer grown well inside a larger simulation
            # box — confirmed necessary by real execution: with the
            # mesh's global extremes, a real ViennaPS oxide layer's top
            # contact was missed entirely; Phase 5-8 behavior is
            # unaffected since those regions' own extremes always
            # coincided with the mesh's global extremes anyway).
            region_node_ids = {n for edge in region_boundary for n in edge}
            region_coords = coords_axis[list(region_node_ids)]
            axis_min, axis_max = region_coords.min(), region_coords.max()

            # A real grown surface (e.g. thermal oxidation's growth
            # front) is curved at mesh resolution, not perfectly flat
            # like MakeTrench's mask edges. Try an exact-float
            # tolerance first (matches every prior phase's flat
            # surfaces byte-for-byte, so their contact edge sets — and
            # everything downstream, e.g. Phase 6's Ohmic currents —
            # are unaffected); only widen it if that finds nothing,
            # which is what a curved real growth front needs.
            def _edges_near(target, tol):
                return [
                    e for e in region_boundary
                    if abs(coords_axis[e[0]] - target) < tol and abs(coords_axis[e[1]] - target) < tol
                ]

            lo_edges = _edges_near(axis_min, 1e-6)
            hi_edges = _edges_near(axis_max, 1e-6)
            if not lo_edges and not hi_edges:
                widened_tol = max(1e-6, 0.1 * (axis_max - axis_min))
                lo_edges = _edges_near(axis_min, widened_tol)
                hi_edges = _edges_near(axis_max, widened_tol)

            for edges, suffix in ((lo_edges, f"{contact_axis}min"), (hi_edges, f"{contact_axis}max")):
                if not edges:
                    continue
                side = contact_sides.get(region_name, "both") if contact_sides else "both"
                if side == "min" and suffix != f"{contact_axis}min":
                    continue
                if side == "max" and suffix != f"{contact_axis}max":
                    continue
                contact_name = f"{region_name}_{suffix}"
                idx = physical_index(contact_name)
                for edge in edges:
                    elements += [1, idx, int(edge[0]), int(edge[1])]
                contact_defs.append((contact_name, region_name))

    coordinates = points.flatten().tolist()

    interface_defs: List[tuple] = []  # (interface_name, region_a, region_b)
    if interface_region_pairs:
        for region_a, region_b in interface_region_pairs:
            tags_a = [t for t, n in tag_to_name.items() if n == region_a]
            tags_b = [t for t, n in tag_to_name.items() if n == region_b]
            if not tags_a or not tags_b:
                continue
            tag_a, tag_b = tags_a[0], tags_b[0]
            shared_edges = [
                edge for edge, owners in edge_owner_tags.items()
                if len(owners) == 2 and set(owners) == {tag_a, tag_b}
            ]
            if not shared_edges:
                continue
            interface_name = f"{region_a}_{region_b}_interface"
            idx = physical_index(interface_name)
            for edge in shared_edges:
                elements += [1, idx, int(edge[0]), int(edge[1])]
            interface_defs.append((interface_name, region_a, region_b))

    module.create_gmsh_mesh(
        mesh=mesh_name,
        coordinates=coordinates,
        elements=elements,
        physical_names=physical_names,
    )

    material_map = material_map or {}
    for region_name in tag_to_name.values():
        module.add_gmsh_region(
            gmsh_name=region_name,
            mesh=mesh_name,
            region=region_name,
            material=material_map.get(region_name, region_name),
        )

    for contact_name, region_name in contact_defs:
        module.add_gmsh_contact(
            gmsh_name=contact_name,
            mesh=mesh_name,
            name=contact_name,
            material="metal",
            region=region_name,
        )

    for interface_name, region_a, region_b in interface_defs:
        module.add_gmsh_interface(
            gmsh_name=interface_name,
            mesh=mesh_name,
            name=interface_name,
            region0=region_a,
            region1=region_b,
        )

    module.finalize_mesh(mesh=mesh_name)
    module.create_device(mesh=mesh_name, device=device_name)

    return ImportedDevice(
        device=device_name,
        mesh=mesh_name,
        regions=list(tag_to_name.values()),
        contacts=[name for name, _ in contact_defs],
        interfaces=[name for name, _, _ in interface_defs],
    )
