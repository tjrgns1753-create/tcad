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
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near, refine_mesh_near
from tcad.mesh.interface import DopingProfile, ProcessResult

#: Target ratio of post-refinement local edge length to Debye length,
#: used to derive how many graded rings auto_refine_from_doping needs
#: (see _derive_refine_from_doping). Chosen to match this project's own
#: real-execution-verified Phase 8 value: at 1e18 cm^-3
#: (grid_delta_um=0.15, Debye length ~3.99nm), a final local edge length
#: of 9.4nm (ratio ~2.35x) was found to converge, while 18.75nm
#: (ratio ~4.7x) did not (see mesh_refine.py / this module's
#: refine_levels docstring). 2.5x sits between those two verified
#: points.
_AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO = 2.5

#: Hard cap on the number of graded refinement rings (see
#: _derive_refine_from_doping / graded_refine_mesh_near). Each ring is
#: cheap (only ~1 level, only over its own — progressively narrower —
#: window), unlike the single-window-many-levels approach this replaced
#: (where going from 4 to 6 uniform levels took the Phase 8 recipe's
#: equation count from ~44k to ~588k for a doping level that still
#: didn't converge in reasonable time — see CLAUDE.md's
#: "mesh-refinement generalization" investigation). Verified directly
#: that graded rings reach 1e20 cm^-3 (100x the originally-tuned
#: doping) at 8 rings, 61725 Si nodes, full convergence — a doping
#: level the OLD single-window approach could not reach at all within
#: a comparable node budget. 20 leaves real headroom beyond that
#: verified point without being unbounded.
_AUTO_REFINE_MAX_RINGS = 20

#: Cap on graded rings per family for derive_implant_windows_refinement().
#: Lower than _AUTO_REFINE_MAX_RINGS because that one refines a single
#: POINT-centred window in 1D, while this refines a horizontal interface
#: STRIP spanning the whole device as well — each extra ring there costs
#: far more nodes. Real-execution-verified sufficient on this project's
#: own MOSFET: 4 rings gave Id = 5.68e-05 A at 23788 nodes, and 6 rings
#: gave 5.78e-05 A at 79126 nodes — a 1.7% change for 3.3x the mesh, so
#: the answer is converged at 4 (see CLAUDE.md).
_IMPLANT_WINDOWS_MAX_RINGS = 4


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


def _telescoping_ring_half_widths(
    spacing_um: float, concentration_cm3: float, max_rings: int
) -> List[float]:
    """Telescoping window half-widths for graded_refine_mesh_near():
    start at the mesh's own existing local spacing (already resolvable,
    so a safe outermost window) and halve until the LOCAL edge length is
    within _AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO x the real Debye
    length at `concentration_cm3` (DevSim's own Permittivity/kT/q — see
    _debye_length_um), capped at `max_rings`.

    Returns at least one ring: a concentration already resolved at the
    mesh's own spacing still gets a single refinement pass, matching the
    pre-existing "at least 1 level" behavior every caller relied on.
    """
    target_edge_um = _AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO * _debye_length_um(
        concentration_cm3
    )
    rings: List[float] = []
    half_width = spacing_um
    edge = spacing_um
    while edge > target_edge_um and len(rings) < max_rings:
        rings.append(half_width)
        half_width /= 2.0
        edge /= 2.0
    return rings or [spacing_um]


#: Cap on graded rings for derive_mos_gate_interface_refinement(). Found
#: real-execution-verified (this project's own MOS gate-stack C-V audit,
#: see CLAUDE.md) that the accumulation-charge capacitance measured at a
#: gate_stack device's abrupt lateral gate edge does NOT converge to a
#: fixed value as refinement increases -- it keeps climbing (102% of the
#: correctly-computed ideal C_ox at 0 rings, 128% at 2, 142% at 4) because
#: an idealized gate with no field plate / no gradual taper has a real
#: conductor-edge field singularity there (the same category of "not
#: fixable by refinement at this layer" idealization limit already
#: documented for the KOH V-groove apex). 2 rings is a modest, cheap
#: (+15% node count on the project's own reference device) improvement
#: over zero refinement that still comfortably clears a 0.8x-C_ox
#: accumulation-capacitance target -- going further chases a singularity
#: rather than buying real accuracy.
_MOS_GATE_MAX_RINGS = 2


def derive_mos_gate_interface_refinement(
    channel_min_um: float,
    channel_max_um: float,
    points: np.ndarray,
    triangles: np.ndarray,
    interface_position_um: float = 0.0,
    interface_axis: str = "y",
    lateral_axis: str = "x",
    max_rings: int = _MOS_GATE_MAX_RINGS,
) -> List[Any]:
    """Graded-refinement predicates for the Si-SiO2 interface UNDER A
    GATE — e.g. `gate_stack`'s own oxide/channel geometry — restricted
    to `channel_min_um < lateral_axis-coordinate < channel_max_um` so
    only the real gate/channel interface is refined, not the whole
    `interface_position_um` plane.

    WHY THE LATERAL RESTRICTION MATTERS (found by direct measurement,
    not assumed): `gate_stack` devices commonly have bare Si exposed at
    y=0 OUTSIDE the gate window (the oxide/gate stack is laterally
    confined to `channel_um`, but Si spans the full device width) —
    refining the ENTIRE y=0 plane there also refines that open Si
    boundary, whose own triple-point corner (where the oxide's lateral
    edge meets bare Si) is a separate, unrelated field concentration.
    Restricting to strictly inside the channel window (minus one mesh
    spacing of margin, so the gate's own edge corner is also excluded)
    isolates the region this function is actually meant to resolve: the
    real Si-SiO2 interface directly under the gate, where accumulation/
    inversion charge physically forms.

    Returns an empty list (rather than a single always-refine-everything
    predicate) if the margin leaves no interior window — a channel
    narrower than 2 mesh spacings has no interior region to refine.
    """
    axis_index = {"x": 0, "y": 1, "z": 2}
    lateral_i = axis_index[lateral_axis]
    vertical_i = axis_index[interface_axis]

    spacing_um = _estimate_mesh_spacing_um(points, triangles)
    margin = spacing_um
    lo = channel_min_um + margin
    hi = channel_max_um - margin
    if lo >= hi:
        return []

    half_widths: List[float] = []
    half_width = spacing_um
    for _ in range(max_rings):
        half_widths.append(half_width)
        half_width /= 2.0

    return [
        (
            lambda centroid, hw=hw, lo=lo, hi=hi, li=lateral_i, vi=vertical_i,
            p=interface_position_um: (lo < centroid[li] < hi) and abs(centroid[vi] - p) < hw
        )
        for hw in half_widths
    ]


def refine_process_result_for_mos_gate(
    result: ProcessResult,
    channel_min_um: float,
    channel_max_um: float,
    refined_mesh_path: Optional[str] = None,
    interface_position_um: float = 0.0,
    interface_axis: str = "y",
) -> Optional[ProcessResult]:
    """Return a ProcessResult whose mesh is graded-refined at the real
    Si-SiO2 interface under a gate (see
    `derive_mos_gate_interface_refinement`'s own docstring for why the
    refinement is laterally restricted to the channel window), or None
    if the channel window is too narrow to refine.

    Same refine-then-reimport shape as
    `refine_process_result_for_implant_windows` — refinement has to
    happen on the raw MESH before DevSim import, so this writes a
    refined mesh next to the original and returns a ProcessResult
    pointing at it, carrying the same doping/material regions.
    """
    import dataclasses

    try:
        import meshio
    except ImportError as exc:  # pragma: no cover - same guard as import path
        raise RuntimeError(
            "meshio is required to refine process meshes.\n"
            "Install it first:\n"
            "python -m pip install meshio"
        ) from exc

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise ValueError(f"No triangle cells found in mesh: {result.volume_mesh_path}")

    block_index = mesh.cells.index(triangle_block)
    points, triangles = mesh.points, triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]

    predicates = derive_mos_gate_interface_refinement(
        channel_min_um, channel_max_um, points, triangles,
        interface_position_um=interface_position_um,
        interface_axis=interface_axis,
    )
    if not predicates:
        return None

    refined_points, refined_triangles, refined_tags = graded_refine_mesh_near(
        points, triangles, tags, predicates
    )

    if refined_mesh_path is None:
        refined_mesh_path = f"{result.volume_mesh_path}.mos_gate_refined.vtu"

    meshio.write(
        refined_mesh_path,
        meshio.Mesh(
            points=refined_points,
            cells=[("triangle", refined_triangles)],
            cell_data={result.material_field: [refined_tags]},
        ),
    )

    return dataclasses.replace(result, volume_mesh_path=refined_mesh_path)


def refine_process_result_for_implant_windows(
    result: ProcessResult,
    refined_mesh_path: Optional[str] = None,
    interface_position_um: Optional[float] = None,
    interface_axis: str = "y",
) -> Optional[ProcessResult]:
    """Return a ProcessResult whose mesh is graded-refined at every
    implant-window edge, or None if no refinement could be derived.

    `implant_windows` is the one doping kind `import_process_result`'s
    own `auto_refine_from_doping` cannot serve: the profile carries
    neither `junction_position_um` nor `peak_position_um`, so
    `_derive_refine_from_doping()` returns None for it. It is also the
    kind that needs refinement most, because its windows are typically
    the highest concentration in the device (1e20 source/drain on a
    1e17 body -> a ~1.2nm Debye length against a 0.2um process grid).

    Measured on this project's own GUI measurement path, one doping
    kind per process so no leaked device could fake the result: the
    unrefined solve fails outright with "Convergence failure!", while
    the same recipe refined here converges (622 -> 13543 mesh points,
    16 predicates, terminal currents equal and opposite to 4e-16).

    Refinement must happen on the MESH, before import, so this writes a
    refined mesh next to the original and returns a ProcessResult
    pointing at it — carrying the SAME DopingProfile and the same
    material regions, since graded refinement subdivides triangles
    without introducing or removing a material. Same refine-then-
    reimport shape as tests/integration/test_mosfet_id_vgs_real.py,
    factored out here so the GUI and the regression test drive one
    implementation rather than two copies of it.

    interface_position_um / interface_axis : forwarded to
        `derive_implant_windows_refinement()` to add vertical rings at
        a horizontal interface (a MOSFET's Si-SiO2 boundary, where the
        inversion layer forms). Omit for a plain 2-terminal device,
        which has no such interface to resolve.
    """
    import dataclasses

    try:
        import meshio
    except ImportError as exc:  # pragma: no cover - same guard as import path
        raise RuntimeError(
            "meshio is required to refine process meshes.\n"
            "Install it first:\n"
            "python -m pip install meshio"
        ) from exc

    if result.doping is None:
        return None

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise ValueError(f"No triangle cells found in mesh: {result.volume_mesh_path}")

    block_index = mesh.cells.index(triangle_block)
    points, triangles = mesh.points, triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]

    predicates = derive_implant_windows_refinement(
        result.doping, points, triangles,
        interface_position_um=interface_position_um,
        interface_axis=interface_axis,
    )
    if not predicates:
        return None

    refined_points, refined_triangles, refined_tags = graded_refine_mesh_near(
        points, triangles, tags, predicates
    )

    if refined_mesh_path is None:
        refined_mesh_path = f"{result.volume_mesh_path}.implant_refined.vtu"

    meshio.write(
        refined_mesh_path,
        meshio.Mesh(
            points=refined_points,
            cells=[("triangle", refined_triangles)],
            cell_data={result.material_field: [refined_tags]},
        ),
    )

    return dataclasses.replace(result, volume_mesh_path=refined_mesh_path)


def derive_implant_windows_refinement(
    doping: DopingProfile,
    points: np.ndarray,
    triangles: np.ndarray,
    interface_position_um: Optional[float] = None,
    interface_axis: str = "y",
    max_rings: int = _IMPLANT_WINDOWS_MAX_RINGS,
) -> List[Any]:
    """Graded-refinement predicates for an `implant_windows` device —
    every one of them derived from the doping profile itself, so a
    caller never hand-picks a refinement scale for its own doping level.

    Returns a predicate list ready for
    `tcad.device.devsim.mesh_refine.graded_refine_mesh_near()`:
      - LATERAL telescoping rings, ONE PREDICATE PER RING WIDTH, each
        predicate matching a triangle near ANY implant-window edge — a
        UNION across edges at each ring depth, not a separate full
        telescope per edge. VERTICAL (when `interface_position_um` is
        given) telescoping rings centred on a horizontal interface —
        for a MOSFET, the Si-SiO2 interface at y=0, where the inversion
        channel forms — stay a separate per-level family, since an
        interface spans the whole device on a different axis and
        legitimately overlaps a lateral edge's own window on purpose
        (the channel region under the gate, verified by the MOSFET
        Id-Vgs test).

    WHY ONE PREDICATE PER RING WIDTH, NOT PER EDGE (found this session,
    real-execution-verified, not assumed): looping per-edge with each
    edge's own full widest-to-narrowest telescope — what this function
    did before — works fine when window edges are far enough apart that
    their refined regions never overlap (every case this project had
    tested until now). But `refine_mesh_near()` unconditionally
    subdivides any triangle matching its predicate regardless of that
    triangle's CURRENT size, so when two regions DO overlap — e.g. two
    window edges placed close together — applying one source's full
    telescope and then another source's full telescope on top
    ACCUMULATES rather than taking the union of what's needed: a
    triangle already refined to one source's finest ring gets the other
    source's full depth of halving applied AGAIN, unconditionally.
    Confirmed directly: adding one extra 0.2um-half-width ring at a
    position 0.1um from an existing window edge alone tripled node
    count (12049 -> 36407); re-ordering the combined predicate list
    (interleaved-by-width vs. one full telescope then the other) barely
    helped (~9%), ruling out ORDER as the cause — only true union
    composition (this restructuring) fixes it. For DISJOINT edges (the
    passing cases before this change), one-predicate-per-ring-width
    still applies exactly `len(rings)` total halvings to each edge's
    own neighborhood, in a different order but with an identical final
    mesh, since disjoint regions cannot interact through the red-green
    closure rule — see mesh_refine.py's own `_refine_once`.

    THIS RESTRUCTURING ALONE DOES NOT FIX THE implant_windows
    GEOMETRY-DEPENDENT CONVERGENCE FAILURE (see CLAUDE.md's OPEN item):
    a follow-up experiment fed this SAME union composition the EXACT,
    hand-confirmed position of the etched sidewall that triggers that
    failure (not an auto-detector — the real x=+-1.5um coordinates) and
    it still failed to converge at 4 rings (0.025um half-width) and 6
    rings (69274 Si nodes, 0.00625um half-width); 8 rings (0.0016um
    half-width, 303530 Si nodes) did not even finish a solve attempt
    within 300s. This rules out "refine harder at the sidewall" —
    however the refinement is composed or targeted — as a complete fix
    within practical mesh sizes; automatic geometric-anomaly detection
    was tried on top of this restructuring and removed again once the
    hand-picked-center version above showed the underlying refinement
    approach itself doesn't reach convergence. See CLAUDE.md's OPEN
    item 2 for the full investigation and what to try next (a solve
    STRATEGY change — e.g. continuation/homotopy on doping level, or
    damped Newton — rather than more mesh refinement).

    THE PHYSICALLY LOAD-BEARING POINT, measured rather than assumed:
    BOTH ring families are sized from the profile's PEAK concentration
    (the implant windows' own, e.g. 1e20 cm^-3 source/drain), NOT from
    the background/body doping. For the lateral junctions that is
    obvious — the junction's own carriers are at the peak level. For the
    INTERFACE it is the whole point of this function: an inversion layer
    reaches carrier densities on the order of the peak doping, not the
    body doping, so its physical thickness is the Debye length at the
    PEAK (a couple of nm), not at the body (tens of nm).

    Sizing the interface rings from the body doping instead — the
    natural-looking choice, and what this project did before this
    function existed — leaves the inversion layer spanned by a SINGLE
    mesh node and throttles the simulated drain current catastrophically.
    Measured directly on this project's own MOSFET (1e17 body / 1e20
    source-drain, Vgs=8V, Vds=0.1V): body-derived interface spacing
    (25nm) gave Id = 1.49e-12 A, while peak-derived spacing (3.1nm) gave
    Id = 5.68e-05 A on the same device — a factor of 3.8e7, and the
    vertical electron profile went from a 7-orders-per-node cliff to a
    properly resolved ~2nm decay. Confirmed converged, not merely
    changed: halving twice more (0.78nm, 79126 nodes) moved Id only to
    5.78e-05 A, a 1.7% change. See CLAUDE.md.

    max_rings : cap on rings per family. Defaults to
        `_IMPLANT_WINDOWS_MAX_RINGS` — real-execution-verified sufficient
        (see above); each additional ring roughly triples total node
        count for this device, for no further change in the answer.

    Returns an empty list if `doping` holds no usable `implant_windows`
    region, so a caller can fall back rather than crash.
    """
    axis_index = {"x": 0, "y": 1, "z": 2}
    predicates: List[Any] = []

    for region in doping.regions:
        windows = region.implant_windows
        if not windows or region.junction_axis is None:
            continue

        peak_cm3 = max(
            [abs(region.net_doping_cm3 or 0.0)]
            + [abs(w.get("conc_cm3", 0.0)) for w in windows]
        )
        if peak_cm3 <= 0.0:
            continue

        spacing_um = _estimate_mesh_spacing_um(points, triangles)
        rings = _telescoping_ring_half_widths(spacing_um, peak_cm3, max_rings)

        lateral = axis_index[region.junction_axis]
        # A window edge is only a real JUNCTION where the doping actually
        # steps. An edge sitting at the device's own boundary is not: the
        # implant simply runs off the end, doping is uniform right up to
        # it. Refining there buys nothing and actively hurts — that
        # boundary is where the Ohmic contacts live, and refining into a
        # contact measurably wrecked the drain-bias ramp's convergence
        # (observed directly: rampbias crawling in ~1e-4 V steps and
        # stalling around Vds=0.039V, versus reaching the full 0.1V
        # target without incident once these edges are skipped).
        axis_min = float(points[:, lateral].min())
        axis_max = float(points[:, lateral].max())
        boundary_tol = spacing_um
        centers: List[float] = []
        for window in windows:
            for edge_um in (window["min_um"], window["max_um"]):
                if (edge_um - axis_min) < boundary_tol or (axis_max - edge_um) < boundary_tol:
                    continue
                centers.append(edge_um)
        centers = sorted(set(round(c, 6) for c in centers))

        if centers:
            for half_width in rings:
                predicates.append(
                    lambda centroid, cs=tuple(centers), hw=half_width, i=lateral: any(
                        abs(centroid[i] - c) < hw for c in cs
                    )
                )

        if interface_position_um is not None:
            vertical = axis_index[interface_axis]
            for half_width in rings:
                predicates.append(
                    lambda centroid, p=interface_position_um, hw=half_width,
                    i=vertical: abs(centroid[i] - p) < hw
                )
        return predicates

    return predicates


def derive_barrier_covered_windows(
    result: ProcessResult,
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

    result : ProcessResult with volume_mesh_path and material_regions.
    doped_region : material name (e.g., "Si") in result.material_regions.
    barrier_material : material name (e.g., "SiO2") in result.material_regions.

    Returns [{"min_um": float, "max_um": float}, ...] in the same
    coordinate convention mask_spans_um/implant_windows already use.
    Empty list if `doped_region` or `barrier_material` is absent from
    the mesh, or nowhere sufficiently covered.
    """
    import meshio

    # Build name -> tag mapping from ProcessResult (backend-independent).
    tag_to_name = {region.tag: region.name for region in result.material_regions}
    name_to_tag = {region.name: region.tag for region in result.material_regions}

    if doped_region not in name_to_tag or barrier_material not in name_to_tag:
        return []

    doped_tag = name_to_tag[doped_region]
    barrier_tag = name_to_tag[barrier_material]

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None or result.material_field not in mesh.cell_data:
        return []
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data[result.material_field][block_index]
    points = mesh.points

    axis_idx = 0 if axis == "x" else 1
    depth_idx = 1 if axis == "x" else 0

    doped_tris = [t for t, tag in zip(triangle_block.data, tags) if int(tag) == doped_tag]
    barrier_tris = [t for t, tag in zip(triangle_block.data, tags) if int(tag) == barrier_tag]
    if not doped_tris or not barrier_tris:
        return []

    axis_vals = [points[n][axis_idx] for t in doped_tris for n in t]
    axis_min, axis_max = min(axis_vals), max(axis_vals)
    if axis_max <= axis_min:
        return []

    # Ground bucket_width_um in the actual mesh spacing, not domain extent.
    if bucket_width_um is None:
        spacing_um = _estimate_mesh_spacing_um(points, triangle_block.data)
        bucket_width_um = spacing_um  # ponytail: buckets match mesh density; finer if needed

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
            windows.append({
                "min_um": float(start),
                "max_um": float(axis_min + b * bucket_width_um),
            })
            start = None
    if start is not None:
        windows.append({
            "min_um": float(start),
            "max_um": float(axis_max),
        })
    return windows


def _derive_refine_from_doping(
    doping: DopingProfile, points: np.ndarray, triangles: np.ndarray
) -> Optional[Tuple[float, str, List[float]]]:
    """Derive (refine_near_um, refine_axis, ring_half_widths) from a
    ProcessResult's doping profile, or None if no region has a
    determinable junction/peak position.

    Takes the FIRST DopingRegion with a position set (junction_position_um
    for "step_junction", peak_position_um for "gaussian_implant") —
    ambiguous for a doping profile with multiple distinct junctions;
    only ever exercised with one active junction per device so far (see
    CLAUDE.md).

    ring_half_widths is a telescoping sequence for
    graded_refine_mesh_near(): starting at the mesh's own existing
    local spacing (already resolvable, so it's a safe starting window —
    see _estimate_mesh_spacing_um) and halving each step, until the
    LOCAL edge length reaches within
    _AUTO_REFINE_TARGET_EDGE_TO_DEBYE_RATIO x the real Debye length at
    this region's doping concentration (using DevSim's own real
    Permittivity/kT/q constants — see _debye_length_um).

    Superseded an earlier (single-window, many-levels) formula — kept
    here only in this docstring for context: that approach widened a
    SINGLE window via a Debye-length multiple and applied N levels
    across the WHOLE window, which meant the entire window's node count
    grew by close to 4^N. Confirmed by real execution to reach ~588k
    equations for one doping level while still not converging within
    reasonable time. The graded/telescoping version reaches the SAME
    final local resolution — only the innermost (narrowest) ring gets
    the full cumulative halving, outer rings get progressively fewer —
    with far fewer total nodes (verified: 16025 vs 51239 Si nodes at
    1e19 cm^-3, both converging; 1e20 cm^-3 converges at all with 8
    rings / 61725 nodes, which the old single-window approach could not
    reach in comparable time — see CLAUDE.md).
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

        spacing_um = _estimate_mesh_spacing_um(points, triangles)
        ring_half_widths = _telescoping_ring_half_widths(
            spacing_um, concentration, _AUTO_REFINE_MAX_RINGS
        )

        return position, region.junction_axis, ring_half_widths

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
    contact_axes: Optional[Dict[str, str]] = None,
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
    contact_axes : optional {region_name: "x"|"y"|"z"} — per-region
        override of `contact_axis`. Default (key absent, or this whole
        parameter omitted) uses the single global `contact_axis` for
        every region, byte-for-byte the same behavior every existing
        caller already gets. Needed once a device has regions whose
        natural contact sits on genuinely different axes in the SAME
        import call — e.g. a MOSFET's source/drain contacts at Si's own
        x-extremes, while its gate contact sits at the oxide's y-extreme
        (see tests/integration/test_mosfet_id_vgs_real.py).
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
        `refine_near_um` was NOT explicitly passed, derives the
        junction position AND applies GRADED refinement directly —
        entirely bypassing `refine_half_width_um`/`refine_levels`
        (those two stay meaningful only for the manual/explicit
        `refine_near_um` path below; a caller combining
        `auto_refine_from_doping=True` with an explicit
        `refine_half_width_um`/`refine_levels` gets those ignored,
        since a single window+level count has no direct equivalent in
        the graded scheme).

        Position: derived from the first `DopingRegion` in
        `result.doping` with a determinable position
        (`junction_position_um` for "step_junction",
        `peak_position_um` for "gaussian_implant") — so a caller no
        longer has to compute/pass it by hand, mirroring how
        `silicon_depth_um` already flows from `Wafer` through the
        recipe automatically.

        Refinement: uses `tcad.device.devsim.mesh_refine.
        graded_refine_mesh_near()` — a TELESCOPING sequence of
        refinement rings (see `_derive_refine_from_doping`), starting
        at the mesh's own existing local spacing (estimated from its
        median triangle edge length, since this function only sees the
        already-written mesh, never the recipe's `grid_delta_um`) and
        halving repeatedly until the LOCAL edge length is within 2.5x
        the real Debye length at the region's own doping concentration
        (using DevSim's own real Permittivity/kT/q constants, not
        re-derived textbook ones — see `_debye_length_um`), each ring
        applied with exactly 1 refinement level. This SUPERSEDES an
        earlier (single-window, many-levels) formula that widened one
        fixed window and applied N levels across the WHOLE window —
        real-execution-verified to need far more nodes for the same
        final local resolution (51239 vs graded's 16025 Si nodes at
        1e19 cm^-3, both converging) and to fail entirely at 1e20 cm^-3
        (100x the originally-tuned 1e18 cm^-3 doping) within reasonable
        time, where the graded version converges the full sweep at
        61725 Si nodes — see CLAUDE.md's "mesh-refinement
        generalization" investigation for the full comparison. This
        also settled an open question from that investigation: 1e20's
        earlier non-convergence was a pure MESH-RESOLUTION limit, not a
        sign the underlying Boltzmann-statistics physics model breaks
        down at that doping — graded refinement converges it cleanly
        with no other change.

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

    graded_refinement_applied = False
    if auto_refine_from_doping and refine_near_um is None and result.doping is not None:
        derived = _derive_refine_from_doping(result.doping, raw_points, triangles)
        if derived is not None:
            derived_near_um, derived_axis, ring_half_widths = derived
            axis_index = {"x": 0, "y": 1, "z": 2}[derived_axis]
            predicates = [
                (lambda centroid, hw=hw: abs(centroid[axis_index] - derived_near_um) < hw)
                for hw in ring_half_widths
            ]
            raw_points, triangles, tags = graded_refine_mesh_near(
                raw_points, triangles, tags, predicates
            )
            graded_refinement_applied = True

    if refine_half_width_um is None:
        refine_half_width_um = 0.1
    if refine_levels is None:
        refine_levels = 4

    if refine_near_um is not None and not graded_refinement_applied:
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
        for region_name in contact_regions:
            matching_tags = [t for t, n in tag_to_name.items() if n == region_name]
            if not matching_tags:
                continue
            region_boundary = boundary_edges_by_tag.get(matching_tags[0], [])
            if not region_boundary:
                continue

            # Per-region axis override (contact_axes), else the single
            # global contact_axis — see contact_axes' own docstring
            # below for why one axis for every region isn't always
            # enough (e.g. a MOSFET's source/drain contacts naturally
            # sit at Si's own x-extremes while its gate contact sits at
            # the oxide's y-extreme, in the SAME import call).
            region_axis = (contact_axes or {}).get(region_name, contact_axis)
            axis_index = {"x": 0, "y": 1, "z": 2}[region_axis]
            coords_axis = points[:, axis_index]

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

            for edges, suffix in ((lo_edges, f"{region_axis}min"), (hi_edges, f"{region_axis}max")):
                if not edges:
                    continue
                side = contact_sides.get(region_name, "both") if contact_sides else "both"
                if side == "min" and suffix != f"{region_axis}min":
                    continue
                if side == "max" and suffix != f"{region_axis}max":
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
