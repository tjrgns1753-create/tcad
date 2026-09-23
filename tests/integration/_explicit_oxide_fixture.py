# -*- coding: utf-8 -*-
"""TEST-ONLY helper: an EXPLICIT INITIAL Si/SiO2 stack for contact / pin
geometry tests.

Provenance: ``DIRECT_EXPLICIT_GEOMETRY``. The SiO2 in this stack is

  * NOT an oxidation growth result,
  * NOT a deposited oxide,
  * a structure the test STATES as an input: a Si half-space whose surface is
    y = 0, covered over the whole width by a SiO2 plane whose top is
    ``oxide_top_um`` (``MakePlane``, ``addToExisting=True``).

It exists to check contact/pin CLASSIFICATION on a real Si/SiO2 mesh boundary.
It is not evidence of oxidation kinetics, of Si consumption, or of an oxide
thickness that any process produced, and no thickness tolerance is asserted on
it. (The plain exporter places the Si/SiO2 interface a grid-proportional
distance from the native level-set position -- an exporter representation
offset with an unidentified cause, see docs/audits/2026-09-20-explicit-oxide-
fixture-spike/REPORT.md EXP 10. It is reported, never interpreted as growth or
Si consumption, and never "fixed" here.)

Nothing in this module may call ``vps.Oxidation()`` (hence never
``setInitialOxideThickness()``) or ``vps.Process(...)``: both are replaced by
independent, counting traps for the whole fixture construction and restored in
a ``finally``. ``MakePlane(...).apply()`` is explicit initial geometry
construction and is allowed.

Every coordinate a test needs (pins, bbox margins) is COMPUTED from the exported
mesh -- never copied from an earlier run's numbers.
"""
from __future__ import annotations

import contextlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROVENANCE = "DIRECT_EXPLICIT_GEOMETRY"
EDGE_EPS_UM = 1.0e-6          # float32 export: "horizontal"/"same y" tolerance for mesh edges


# --------------------------------------------------------------------------- traps
class _Trap:
    """Replacement for `vps.<name>`: counts the attempt, then raises, naming
    which boundary was crossed."""

    def __init__(self, name: str, counts: Dict[str, int]):
        self._name, self._counts = name, counts

    def __call__(self, *args, **kwargs):
        self._counts[self._name] += 1
        raise AssertionError(
            f"vps.{self._name}() was called while building an explicit initial "
            f"Si/SiO2 stack -- oxide must be stated as geometry, never produced by a model")


@contextlib.contextmanager
def forbid_oxidation_and_process(module):
    """`vps.Oxidation` and `vps.Process` are trapped INDEPENDENTLY (two
    separate trap objects with their own counters) and always restored."""
    counts = {"Oxidation": 0, "Process": 0}
    original_oxidation, original_process = module.Oxidation, module.Process
    try:
        module.Oxidation = _Trap("Oxidation", counts)
        module.Process = _Trap("Process", counts)
        yield counts
    finally:
        module.Oxidation = original_oxidation
        module.Process = original_process


# --------------------------------------------------------------------------- data
@dataclass
class ComputedPin:
    """A pin coordinate (WAFER coordinates, x measured from the mesh's own
    minimum x -- the convention `contact_probe.pin_x_domain_um` documents),
    with the measurement it was computed from."""
    name: str
    x_um: float
    y_um: float
    x_domain_um: float
    basis: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplicitSiSiO2Stack:
    """An explicit initial Si/SiO2 stack, its ProcessResult and what was measured.

    NOT an oxidation result, NOT a deposited oxide (see module docstring)."""
    provenance: str
    mesh_path: str
    process_result: Any
    requested: Dict[str, Any]                 # exact input geometry descriptor
    forbidden_call_counts: Dict[str, int]     # Oxidation / Process attempts while building
    native_level_set_top_um: Dict[str, float]  # native (pre-export) top of each level set
    measured: Dict[str, Any]                  # from the EXPORTED mesh
    _mesh: Dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def materials(self) -> List[str]:
        return list(self.measured["materials"])


# ------------------------------------------------------------------ mesh measurement
def _point_segment_distance(p, a, b) -> float:
    ab = b - a
    denom = float(np.dot(ab, ab))
    t = 0.0 if denom == 0.0 else max(0.0, min(1.0, float(np.dot(p - a, ab)) / denom))
    return float(np.linalg.norm(p - (a + t * ab)))


def _read_mesh(mesh_path: str, module) -> Dict[str, Any]:
    import meshio

    mesh = meshio.read(mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    index = mesh.cells.index(block)
    tags = np.asarray(mesh.cell_data["Material"][index]).astype(int)
    points = np.asarray(mesh.points)[:, :2].astype(float)
    triangles = np.asarray(block.data).astype(int)
    names = {int(t): str(module.Material(int(t))).split("'")[1] for t in np.unique(tags)}
    return {"points": points, "triangles": triangles, "tags": tags, "names": names}


def _edge_table(triangles) -> Dict[Tuple[int, int], List[int]]:
    edges: Dict[Tuple[int, int], List[int]] = {}
    for ti, tri in enumerate(triangles):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges.setdefault(tuple(sorted((int(tri[a]), int(tri[b])))), []).append(ti)
    return edges


def measure_exported_mesh(mesh_path: str, module) -> Dict[str, Any]:
    """Everything the tests assert about the EXPORTED mesh, computed here by
    independent code (not by tcad.device.devsim.contact_probe)."""
    m = _read_mesh(mesh_path, module)
    pts, tris, tags, names = m["points"], m["triangles"], m["tags"], m["names"]
    edges = _edge_table(tris)

    external = {}      # material -> list of (a, b) point-index pairs, single-triangle edges
    shared = {}        # "A|B" -> list of edges owned by two triangles of different materials
    for key, owners in edges.items():
        if len(owners) == 1:
            external.setdefault(names[int(tags[owners[0]])], []).append(key)
        elif len(owners) == 2:
            ta, tb = int(tags[owners[0]]), int(tags[owners[1]])
            if ta != tb:
                pair = "|".join(sorted((names[ta], names[tb])))
                shared.setdefault(pair, []).append(key)

    per_material = {}
    for tag, name in names.items():
        used = np.unique(tris[tags == tag])
        per_material[name] = {
            "n_triangles": int((tags == tag).sum()),
            "y_range": [float(pts[used, 1].min()), float(pts[used, 1].max())],
            "x_range": [float(pts[used, 0].min()), float(pts[used, 0].max())],
            "n_external_edges": len(external.get(name, [])),
        }
    rounded = {(round(float(x), 9), round(float(y), 9)) for x, y in pts}
    interface = shared.get("Si|SiO2", [])
    iy = [float(pts[list(e)][:, 1].mean()) for e in interface]
    return {
        "materials": sorted(names.values()),
        "bbox": [float(pts[:, 0].min()), float(pts[:, 0].max()),
                 float(pts[:, 1].min()), float(pts[:, 1].max())],
        "n_points": int(len(pts)), "n_triangles": int(len(tris)),
        "per_material": per_material,
        "shared_edges": {k: len(v) for k, v in shared.items()},
        "duplicate_coordinate_points": int(len(pts) - len(rounded)),
        "sio2_top_y_exported": per_material["SiO2"]["y_range"][1] if "SiO2" in per_material else None,
        "si_bottom_y_exported": per_material["Si"]["y_range"][0] if "Si" in per_material else None,
        "si_sio2_interface_y_exported": ([min(iy), max(iy)] if iy else None),
        "_external": external, "_shared": shared, "_edges": edges,
        "_mesh": m,
    }


# ---------------------------------------------------------------------------- build
def build_explicit_si_sio2_stack(
    out_dir,
    *,
    x_extent_um: float,
    y_extent_um: float,
    silicon_depth_um: float,
    oxide_top_um: float,
    grid_delta_um: float,
    name: str = "explicit_si_sio2",
) -> ExplicitSiSiO2Stack:
    """Build the explicit initial stack (provenance DIRECT_EXPLICIT_GEOMETRY).

    Si:   half-space, surface y = 0, x in [-x_extent/2, +x_extent/2];
          the export floor is the explicit ``silicon_depth_um``.
    SiO2: a plane over the whole width, top at ``oxide_top_um`` (a REQUESTED
          input value, not a measurement).
    No mask, no resist, no oxidation model.

    NOT an oxidation result and NOT a deposited oxide; contact/pin geometry only.
    """
    for label, value in (("x_extent_um", x_extent_um), ("y_extent_um", y_extent_um),
                         ("silicon_depth_um", silicon_depth_um), ("oxide_top_um", oxide_top_um),
                         ("grid_delta_um", grid_delta_um)):
        if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
            raise ValueError(f"{label} must be a finite positive number, got {value!r}")
    if oxide_top_um >= y_extent_um:
        raise ValueError("oxide_top_um must lie inside y_extent_um")

    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result

    module = session.require_viennaps()
    requested = {
        "provenance": PROVENANCE, "note": "explicit initial structure; not grown, not deposited",
        "si": {"x_um": [-x_extent_um / 2.0, x_extent_um / 2.0], "surface_y_um": 0.0,
               "export_floor_um": -float(silicon_depth_um)},
        "sio2": {"top_y_um": float(oxide_top_um), "covers": "whole width"},
        "grid_delta_um": float(grid_delta_um), "y_extent_um": float(y_extent_um),
    }
    with forbid_oxidation_and_process(module) as counts:
        domain = session.create_domain(grid_delta_um, x_extent_um, y_extent_um)
        module.MakePlane(domain, 0.0, module.Material.Si).apply()
        module.MakePlane(domain, float(oxide_top_um), module.Material.SiO2, True).apply()
        native = _native_level_set_tops(module, domain)
        mesh_path = save_volume_mesh(domain, str(Path(out_dir) / name), floor_depth_um=silicon_depth_um)
        process_result = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    measured = measure_exported_mesh(mesh_path, module)
    mesh_data = measured.pop("_mesh")
    private = {k: measured.pop(k) for k in ("_external", "_shared", "_edges")}
    return ExplicitSiSiO2Stack(
        provenance=PROVENANCE, mesh_path=mesh_path, process_result=process_result,
        requested=requested, forbidden_call_counts=dict(counts),
        native_level_set_top_um=native, measured=measured,
        _mesh={"mesh": mesh_data, **private},
    )


def _native_level_set_tops(module, domain) -> Dict[str, float]:
    import viennals as vls

    material_map = domain.getMaterialMap()
    out = {}
    for i, level_set in enumerate(domain.getLevelSets()):
        surface = vls.Mesh()
        vls.ToSurfaceMesh(level_set, surface).apply()
        nodes = np.array(surface.getNodes())
        label = str(material_map.getMaterialAtIdx(i)).split("'")[1]
        out[label] = float(nodes[:, 1].max())
    return out


# ------------------------------------------------------------------------- pins
def _clearance(point, pts, edge_keys) -> float:
    return min(_point_segment_distance(point, pts[a], pts[b]) for a, b in edge_keys)


def _horizontal_edges_at(pts, edge_keys, y) -> List[Tuple[int, int]]:
    return [(a, b) for a, b in edge_keys
            if abs(pts[a][1] - y) < EDGE_EPS_UM and abs(pts[b][1] - y) < EDGE_EPS_UM]


def _central_edge(pts, edge_keys, x_center) -> Tuple[int, int]:
    return min(edge_keys, key=lambda e: abs(0.5 * (pts[e[0]][0] + pts[e[1]][0]) - x_center))


def _point_in_triangle(p, a, b, c) -> bool:
    v0, v1, v2 = c - a, b - a, p - a
    d00, d01, d02 = v0 @ v0, v0 @ v1, v0 @ v2
    d11, d12 = v1 @ v1, v1 @ v2
    inv = 1.0 / (d00 * d11 - d01 * d01)
    u, v = (d11 * d02 - d01 * d12) * inv, (d00 * d12 - d01 * d02) * inv
    return u >= -1e-12 and v >= -1e-12 and u + v <= 1.0 + 1e-12


def compute_pins(stack: ExplicitSiSiO2Stack, *, tolerance_um: float = 0.05,
                 outside_margin_um: float = 1.0, bulk_clearance_factor: float = 10.0
                 ) -> Dict[str, ComputedPin]:
    """The four pins, all computed from the EXPORTED mesh.

    Raises (instead of retuning a number) when the stack cannot support an
    unambiguous pin at this tolerance."""
    mesh = stack._mesh["mesh"]
    pts, tris, tags, names = mesh["points"], mesh["triangles"], mesh["tags"], mesh["names"]
    external, shared, edges = stack._mesh["_external"], stack._mesh["_shared"], stack._mesh["_edges"]
    inverse = {v: k for k, v in names.items()}
    bbox = stack.measured["bbox"]
    x_min, x_max, y_min, y_max = bbox
    x_center = 0.5 * (x_min + x_max)
    interface = shared["Si|SiO2"]
    interface_y = [float(pts[list(e)][:, 1].mean()) for e in interface]
    interface_y_max = max(interface_y)
    other_than = lambda material: [e for m, es in external.items() if m != material for e in es]  # noqa: E731

    def owner(edge):
        (ti,) = edges[edge]
        return names[int(tags[ti])]

    def as_wafer_x(x_domain):
        return float(x_domain - x_min)

    pins: Dict[str, ComputedPin] = {}

    # --- SiO2 external top boundary (SiO2 / vacuum), NOT the internal Si/SiO2 interface
    sio2_top_y = stack.measured["sio2_top_y_exported"]
    top_edges = _horizontal_edges_at(pts, external["SiO2"], sio2_top_y)
    assert top_edges, "no external horizontal SiO2 top edge in the exported mesh"
    edge = _central_edge(pts, top_edges, x_center)
    assert len(edges[edge]) == 1 and owner(edge) == "SiO2", "SiO2 top edge is not a single-owner SiO2 edge"
    mid = 0.5 * (pts[edge[0]] + pts[edge[1]])
    above_interface = float(mid[1] - interface_y_max)
    assert above_interface > 2.0 * tolerance_um, (
        f"SiO2 top is only {above_interface:.4f} um above the Si/SiO2 interface (<= 2 x tolerance "
        f"{tolerance_um}); this stack cannot separate the two boundaries")
    nearest_si_edge = _clearance(mid, pts, external["Si"])
    assert nearest_si_edge > tolerance_um, "a Si external edge lies within tolerance of the SiO2 pin"
    pins["sio2_top"] = ComputedPin(
        "SiO2_top", as_wafer_x(mid[0]), float(mid[1]), float(mid[0]),
        "midpoint of the exported mesh's SiO2 external (single-triangle) horizontal top edge "
        "nearest the x-centre",
        {"edge_owner_triangles": len(edges[edge]), "edge_owner_material": owner(edge),
         "is_internal_si_sio2_interface": edge in set(map(tuple, interface)),
         "height_above_exported_interface_um": above_interface,
         "distance_to_nearest_Si_external_edge_um": nearest_si_edge})

    # --- Si external bottom boundary
    si_bottom_y = stack.measured["si_bottom_y_exported"]
    bottom_edges = _horizontal_edges_at(pts, external["Si"], si_bottom_y)
    assert bottom_edges, "no external horizontal Si bottom edge in the exported mesh"
    edge = _central_edge(pts, bottom_edges, x_center)
    assert len(edges[edge]) == 1 and owner(edge) == "Si"
    mid = 0.5 * (pts[edge[0]] + pts[edge[1]])
    nearest_other = _clearance(mid, pts, other_than("Si"))
    assert nearest_other > tolerance_um, "a non-Si external edge lies within tolerance of the Si pin"
    pins["si_bottom"] = ComputedPin(
        "Si_bottom", as_wafer_x(mid[0]), float(mid[1]), float(mid[0]),
        "midpoint of the exported mesh's Si external (single-triangle) horizontal bottom edge "
        "nearest the x-centre",
        {"edge_owner_triangles": len(edges[edge]), "edge_owner_material": owner(edge),
         "distance_to_nearest_non_Si_external_edge_um": nearest_other})

    # --- interior Si bulk: mid-depth below the interface, far from EVERY external edge
    si_y_lo, si_y_hi = stack.measured["per_material"]["Si"]["y_range"]
    candidate = np.array([x_center, 0.5 * (si_y_lo + min(si_y_hi, min(interface_y)))])
    clearance = _clearance(candidate, pts, [e for es in external.values() for e in es])
    inside_si = any(
        int(tags[ti]) == inverse["Si"] and _point_in_triangle(candidate, *pts[tris[ti]])
        for ti in range(len(tris)))
    assert inside_si, "bulk candidate is not inside a Si triangle"
    assert clearance > bulk_clearance_factor * tolerance_um, (
        f"bulk candidate clearance {clearance:.4f} um <= {bulk_clearance_factor} x tolerance")
    pins["si_bulk"] = ComputedPin(
        "Si_bulk", as_wafer_x(candidate[0]), float(candidate[1]), float(candidate[0]),
        "x-centre, mid-way between the exported Si floor and the exported Si/SiO2 interface, "
        f"checked to be inside a Si triangle and >{bulk_clearance_factor:g} x tolerance from every "
        "external boundary edge",
        {"inside_Si_triangle": inside_si, "min_distance_to_any_external_edge_um": clearance,
         "tolerance_um": tolerance_um})

    # --- outside the whole mesh, explicit margin beyond the bbox
    x_out = x_max + outside_margin_um
    assert x_out > x_max
    pins["outside"] = ComputedPin(
        "Outside", as_wafer_x(x_out), float(0.5 * (y_min + y_max)), float(x_out),
        f"mesh bbox x_max + explicit margin {outside_margin_um} um",
        {"bbox": bbox, "margin_um": outside_margin_um})
    return pins


def describe(stack: ExplicitSiSiO2Stack) -> str:
    """Input geometry and exported-mesh measurements, kept apart."""
    r, m = stack.requested, stack.measured
    interface = m["si_sio2_interface_y_exported"]
    return (
        f"[{stack.provenance}] REQUESTED (input): Si x={r['si']['x_um']} surface y=0 floor "
        f"{r['si']['export_floor_um']}; SiO2 top y={r['sio2']['top_y_um']}; grid={r['grid_delta_um']}\n"
        f"  NATIVE level-set tops: {stack.native_level_set_top_um}\n"
        f"  EXPORTED mesh: bbox={m['bbox']} materials={m['materials']} "
        f"SiO2 top y={m['sio2_top_y_exported']} Si/SiO2 interface y={interface} "
        f"Si bottom y={m['si_bottom_y_exported']} shared={m['shared_edges']} "
        f"duplicate coordinates={m['duplicate_coordinate_points']}\n"
        f"  (any native-vs-exported difference is an exporter representation offset; it is not "
        f"oxide growth or Si consumption)\n"
        f"  forbidden calls while building: {stack.forbidden_call_counts}")
