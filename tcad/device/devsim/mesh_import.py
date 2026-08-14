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

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from tcad.device.devsim import backend
from tcad.device.devsim.mesh_refine import refine_mesh_near
from tcad.mesh.interface import DopingProfile, ProcessResult

#: Refinement half-width, in multiples of the local Debye length,
#: used by auto_refine_from_doping. Chosen to match this project's own
#: real-execution-verified Phase 8 value: at 1e18 cm^-3 (Debye length
#: ~3.99nm using DevSim's own eps_si/eps_0/q/k constants — see
#: _debye_length_um), refine_half_width_um=0.1um was found to converge
#: (see this module's refine_half_width_um docstring below), a ratio of
#: ~25x. This also lines up with the physical picture: a step
#: junction's depletion width is roughly Debye_length *
#: sqrt(4*V_bi/V_t), and V_bi/V_t is typically ~25-35 at real doping
#: levels, so 25x Debye length is roughly "cover the depletion region
#: plus margin", not an arbitrary constant.
_AUTO_REFINE_DEBYE_MULTIPLE = 25.0

#: Floor on refine_half_width_um as a multiple of the mesh's own local
#: spacing (see _estimate_mesh_spacing_um) — a window narrower than
#: this catches zero triangle centroids and silently refines nothing
#: (a real, documented failure mode: CLAUDE.md records half-width 0.05
#: at grid_delta_um=0.15, a ratio of ~0.33x, as "caught zero triangles",
#: while 0.08-0.1 (~0.53-0.67x) converged). 0.7x sits just above that
#: verified-working range with a small safety margin, without
#: over-refining the way a 1x or 2x floor does (measured directly this
#: session: a 2x floor drove the Phase 8 recipe from ~10.3k Si nodes to
#: 100k+ equations for no convergence benefit — see CLAUDE.md).
_SPACING_FLOOR_MULTIPLE = 0.7

#: Target ratio of post-refinement local edge length to Debye length,
#: used to auto-derive refine_levels. Chosen to match this project's
#: own real-execution-verified Phase 8 value: at 1e18 cm^-3
#: (grid_delta_um=0.15, Debye length ~3.99nm), 4 refinement levels
#: (0.15um / 2^4 = 9.4nm final edge length, a ratio of ~2.35x) was
#: found to converge, while 3 levels (~8.4x finer, 18.75nm final edge,
#: ratio ~4.7x) did not (see mesh_refine.py / this module's
#: refine_levels docstring). 2.5x sits between those two verified
#: points.
_AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO = 2.5

#: Hard cap on auto-derived refine_levels. Each level is NOT a cheap
#: linear cost — measured directly this session: going from 4 to 6
#: levels (same fixed refine_half_width_um) took the Phase 8 recipe's
#: equation count from ~44k to ~588k (~13x for 2 extra levels, close
#: to the 4^2=16x a pure "every level ~4x's the local triangle count"
#: model predicts). A cap of 10 was tried first and is NOT usable in
#: practice; capped much lower instead. Doping levels needing more
#: refinement than this cap allows are NOT guaranteed to converge with
#: auto_refine_from_doping — see CLAUDE.md's "mesh-refinement
#: generalization" investigation for exactly which doping levels this
#: was verified to work vs not.
_AUTO_REFINE_MAX_LEVELS = 5


def _debye_length_um(concentration_cm3: float, temperature_k: float = 300.0) -> float:
    """Debye length (um) for a given net carrier concentration (cm^-3),
    using DevSim's OWN real Permittivity/ElectronCharge/kT constants
    (devsim.python_packages.simple_physics — the exact values
    SetSiliconParameters() sets on a real device, read directly, not
    re-derived from textbook constants that might not match what
    DevSim's own solve actually uses).
    """
    from devsim.python_packages.simple_physics import eps_si, eps_0, q, k

    v_t = k * temperature_k / q
    l_d_cm = math.sqrt(eps_si * eps_0 * v_t / (q * abs(concentration_cm3)))
    return l_d_cm * 1.0e4  # cm -> um


def _estimate_mesh_spacing_um(points: np.ndarray, triangles: np.ndarray) -> float:
    """Median triangle edge length (um) — a spacing proxy standing in
    for the mesh's original grid_delta_um, which import_process_result()
    has no direct access to (it only ever sees the already-written mesh,
    not the recipe that produced it). Used as a practical floor
    alongside the physical Debye-length target: a refinement window
    narrower than the ALREADY-EXISTING local mesh spacing catches zero
    triangle centroids and silently refines nothing (a real failure
    mode this project already found and documented — see
    refine_half_width_um's docstring below).
    """
    sample = triangles[:2000]
    p = points[:, :2]
    lengths = []
    for tri in sample:
        v0, v1, v2 = p[int(tri[0])], p[int(tri[1])], p[int(tri[2])]
        lengths.append(np.linalg.norm(v0 - v1))
        lengths.append(np.linalg.norm(v1 - v2))
        lengths.append(np.linalg.norm(v2 - v0))
    return float(np.median(lengths)) if lengths else 0.0


def _derive_refine_from_doping(
    doping: DopingProfile, points: np.ndarray, triangles: np.ndarray
) -> Optional[Tuple[float, str, float, int]]:
    """Derive (refine_near_um, refine_axis, refine_half_width_um,
    refine_levels) from a ProcessResult's doping profile, or None if no
    region has a determinable junction/peak position.

    Takes the FIRST DopingRegion with a position set (junction_position_um
    for "step_junction", peak_position_um for "gaussian_implant") —
    ambiguous for a doping profile with multiple distinct junctions;
    only ever exercised with one active junction per device so far (see
    CLAUDE.md).
    """
    for region in doping.regions:
        if region.junction_position_um is not None:
            position = region.junction_position_um
            concentration = max(
                abs(region.donor_conc_cm3 or 0.0), abs(region.acceptor_conc_cm3 or 0.0)
            )
        elif region.peak_position_um is not None:
            position = region.peak_position_um
            concentration = abs(region.peak_conc_cm3 or 0.0)
        else:
            continue

        if concentration <= 0.0 or region.junction_axis is None:
            continue

        debye_um = _debye_length_um(concentration)
        spacing_um = _estimate_mesh_spacing_um(points, triangles)
        half_width_um = max(_AUTO_REFINE_DEBYE_MULTIPLE * debye_um, _SPACING_FLOOR_MULTIPLE * spacing_um)

        # How many halvings bring the LOCAL edge length (starting from
        # the mesh's own existing spacing) within
        # _AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO x the Debye length —
        # not just widening the window (refine_half_width_um above),
        # which alone does NOT increase local resolution. Verified
        # necessary by real execution (this session): auto-deriving
        # only refine_half_width_um and leaving refine_levels fixed at
        # 4 converged at 1e18 cm^-3 (matching the recipe that value was
        # tuned against) but FAILED to converge at 1e19/1e20 cm^-3 at
        # the same grid_delta_um=0.15 mesh — the fixed final edge
        # length (0.15/2^4 = 9.4nm) is only ~2.35x the Debye length at
        # 1e18 but 7.4x/23.5x too coarse at 1e19/1e20.
        target_edge_um = _AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO * debye_um
        if target_edge_um > 0.0 and spacing_um > target_edge_um:
            levels = int(math.ceil(math.log2(spacing_um / target_edge_um)))
        else:
            levels = 0
        levels = max(1, min(levels, _AUTO_REFINE_MAX_LEVELS))

        return position, region.junction_axis, half_width_um, levels

    return None


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
    refine_near_um: Optional[float] = None,
    refine_axis: str = "x",
    refine_half_width_um: Optional[float] = None,
    refine_levels: Optional[int] = None,
    auto_refine_from_doping: bool = False,
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
    refine_near_um : optional. When set, locally refines mesh triangles
        (tcad.device.devsim.mesh_refine, red-green/conforming
        refinement — no hanging nodes, far-field mesh untouched) whose
        centroid falls within `refine_half_width_um` of this position
        along `refine_axis`, applied `refine_levels` times (each level
        ~halves the local edge length). Default None: no refinement,
        bit-for-bit identical behavior to every existing caller.

        Motivation (found by real execution, not guessed): ViennaPS's
        uniform grid_delta_um mesh can be far coarser than the Debye
        length at real doping levels near a step junction — confirmed
        this project's own Phase 8 PN-junction drift-diffusion sweep
        (donor=acceptor=1e18 cm^-3, grid_delta_um=0.15um -> Debye
        length ~4nm, mesh ~37x too coarse) stalls in a persistent
        Newton residual oscillation, while the SAME mesh at a lower,
        better-resolved doping level (1e16/1e14 cm^-3) converges
        cleanly. DEVSIM's own official diode example
        (examples/diode/diode_common.py) grades its mesh down to
        sub-nm/few-nm right at the junction for exactly this reason.
        Pass the doping junction's position here (same units/axis as
        the doping region) rather than lowering doping or refining the
        whole mesh uniformly (measured separately to be both far more
        expensive and not reliably better, since ViennaPS's triangle
        quality is not a monotonic function of grid_delta_um).
    refine_axis : "x", "y", or "z" — axis `refine_near_um` is measured
        along. Independent of `contact_axis` (usually the same value,
        not required to be).
    refine_half_width_um : half-width of the refinement window. Default
        (None) resolves to 0.1 — real-execution-verified minimum
        working value for this project's own Phase 8 recipe
        (grid_delta_um=0.15, donor=acceptor=1e18 cm^-3): 0.05 caught
        zero triangles (smaller than one original grid cell, so nothing
        was actually refined — the sweep failed identically to no
        refinement at all) while 0.08-0.1 both converged the full
        8-point sweep at similar, modest node counts (~10.3k Si nodes,
        ~15s for the whole sweep vs. a uniformly-refined whole-mesh
        alternative measured separately at ~50k nodes / 260s+ and STILL
        not fully converging). Widening further (0.15/0.25/0.4) also
        converges but costs more nodes for no additional benefit at
        this recipe. Should cover at least the depletion region at the
        doping level used (a few Debye lengths) plus margin — a
        different doping level or grid_delta_um will need a different
        value, or see `auto_refine_from_doping` below to derive one.
    refine_levels : number of refinement passes (each ~halves the
        local edge length inside the window). Default (None) resolves
        to 4 (~16x finer locally) — real-execution-verified against
        this project's own 1e18 cm^-3 step-junction Phase 8 recipe:
        3 passes (~8x) got the sweep through V=+0.3 but failed at the
        last point, V=+0.4; 4 passes converged all 8 points. A
        different doping level needs a different value — verified by
        real execution (not just assumed) that 4 stays right for 1e18
        but is NOT enough at 1e19/1e20 cm^-3 at the same mesh (the
        fixed final edge length doesn't shrink with doping): see
        `auto_refine_from_doping` below to derive one instead.
    auto_refine_from_doping : opt-in (default False). When True, and
        `refine_near_um` was NOT explicitly passed, derives
        `refine_near_um`/`refine_axis` from the first DopingRegion in
        `result.doping` that has a determinable position
        (`junction_position_um` for "step_junction",
        `peak_position_um` for "gaussian_implant") — so a caller no
        longer has to compute/pass the junction position by hand,
        mirroring how `silicon_depth_um` already flows from `Wafer`
        through the recipe automatically (this was this project's own
        named "next smallest experiment" after the mesh-refinement fix
        first shipped — see CLAUDE.md).

        Also derives `refine_half_width_um` (only when that argument
        was itself left at its default None) as
        `max(25 * debye_length_um, 0.7 * local_mesh_spacing_um)`: 25x
        the Debye length at the region's own doping concentration
        (using DevSim's own real Permittivity/kT/q constants, not
        re-derived textbook ones — see `_debye_length_um`) covers the
        depletion region plus margin (matches the hand-picked 0.1um
        value above, which is ~25x the ~4nm Debye length at that
        recipe's 1e18 cm^-3 doping); the `0.7*local_mesh_spacing_um`
        floor (spacing estimated directly from the mesh's own median
        triangle edge length, since this function has no access to the
        recipe's grid_delta_um) exists because a window narrower than
        the EXISTING mesh spacing catches zero triangle centroids and
        silently refines nothing — the same failure mode the 0.1um
        value above was hand-tuned to avoid (0.7x, not e.g. 2x, was
        itself real-execution-verified: an earlier 2x floor drove the
        Phase 8 recipe's node count from ~10.3k to 100k+ equations for
        no convergence benefit, before being corrected to 0.7x — see
        CLAUDE.md).

        And derives `refine_levels` (only when that argument was
        itself left at its default None) as however many halvings
        bring the mesh's local edge length within 2.5x the Debye
        length, capped at 10 — REQUIRED, not optional, for this to
        generalize beyond 1e18 cm^-3: verified by real execution that
        deriving `refine_half_width_um` alone while leaving
        `refine_levels` fixed at 4 converges at 1e18 cm^-3 (matching
        the recipe that value was tuned against) but FAILS to converge
        at 1e19/1e20 cm^-3 at the same grid_delta_um=0.15 mesh, because
        widening the refinement WINDOW doesn't increase local
        RESOLUTION — only more halvings do.

        Does nothing (silently) if `result.doping` is None, or if no
        region has a determinable position — matching every prior
        caller's behavior exactly if this project's doping-free
        callers ever pass this flag by accident. Ambiguous for a
        doping profile with more than one distinct junction (only the
        FIRST positioned region is used) — not yet a scenario this
        project's own recipes produce.
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
    raw_points = mesh.points

    if auto_refine_from_doping and refine_near_um is None and result.doping is not None:
        derived = _derive_refine_from_doping(result.doping, raw_points, triangles)
        if derived is not None:
            refine_near_um, refine_axis, derived_half_width_um, derived_levels = derived
            if refine_half_width_um is None:
                refine_half_width_um = derived_half_width_um
            if refine_levels is None:
                refine_levels = derived_levels

    if refine_half_width_um is None:
        refine_half_width_um = 0.1
    if refine_levels is None:
        refine_levels = 4

    if refine_near_um is not None:
        axis_index = {"x": 0, "y": 1, "z": 2}[refine_axis]

        def _near_refine_target(centroid):
            return abs(centroid[axis_index] - refine_near_um) < refine_half_width_um

        raw_points, triangles, tags = refine_mesh_near(
            raw_points, triangles, tags, _near_refine_target, levels=refine_levels
        )

    points = raw_points * length_scale_to_cm

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
