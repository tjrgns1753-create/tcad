"""Fail-closed area-conservation gate for DEVSIM imports (planar 2D Cartesian).

DEVSIM integrates every node model with its own `NodeVolume`. On a mesh
with obtuse triangles DEVSIM's rule over-integrates (7H-B / 7H-E2), so a
device can carry integration weights whose per-region sum is not the
region's area -- and the unmodified importer returned such a device
(7H-E6E step 1: the E6D G2 mesh, +3.12e-3). This module checks, per
material region and on exactly the float64 coordinates handed to DEVSIM,
that the NodeVolume sum equals the triangle area within a rounding
budget, and refuses otherwise. It never rescales or redefines
NodeVolume. Contract: docs/audits/2026-09-30-batch7h-e6e-area-conservation-gate/PLAN.md.

Pure numpy / math; the two DEVSIM-touching helpers take the module as an
argument so everything else is testable without DEVSIM.
"""
import math
from typing import Dict, List

import numpy as np

U = 2.0 ** -53
GAMMA4 = 4 * U / (1 - 4 * U)
# DEVSIM element-local node-volume budget, per triangle, relative to its
# area, times 1/sin(theta_min): an ASSUMPTION inherited unchanged from
# 7H-E2 PLAN section 4 ("128 u for a <= 64-operation element-local
# computation, times the first-order conditioning 1/sin theta"), not
# derived from DEVSIM source.
NODEVOLUME_ELEMENT_BUDGET = 128 * U


class MeshAreaConservationError(RuntimeError):
    """The mesh cannot be certified to conserve area region by region.
    `physics_status` carries resolution UNSUPPORTED_BY_MODEL, the
    reason_code, the per-region numbers and the cleanup outcome."""

    def __init__(self, message: str, physics_status: dict):
        super().__init__(message)
        self.physics_status = physics_status


def _refuse(code: str, message: str, **extra) -> None:
    status = {"resolution": "UNSUPPORTED_BY_MODEL", "reason_code": code, **extra}
    raise MeshAreaConservationError(f"UNSUPPORTED_BY_MODEL ({code}): {message}", status)


def triangle_terms(points: np.ndarray, triangles: np.ndarray):
    """o_t (twice the signed area), its rounding bound e_t, and theta_min per triangle."""
    P = np.asarray(points, dtype=np.float64)
    T = np.asarray(triangles, dtype=np.int64)
    a, b, c = P[T[:, 0], :2], P[T[:, 1], :2], P[T[:, 2], :2]
    p1 = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
    p2 = (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    o = p1 - p2
    e = GAMMA4 * (np.abs(p1) + np.abs(p2))
    theta = np.full(len(T), np.pi)
    for u_, v_, w_ in ((a, b, c), (b, c, a), (c, a, b)):
        d1, d2 = v_ - u_, w_ - u_
        ang = np.arctan2(np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]), (d1 * d2).sum(axis=1))
        theta = np.minimum(theta, ang)
    return o, e, p1, p2, theta


def check_mesh_input(points, triangles, tags, tag_to_name: Dict[int, str], extra_area_cells: List[str]) -> Dict[str, dict]:
    """Checks that need no DEVSIM. Raises MeshAreaConservationError; returns per-region area terms."""
    P = np.asarray(points, dtype=np.float64)
    T = np.asarray(triangles, dtype=np.int64)
    tags = np.asarray(tags).reshape(-1)
    if not np.isfinite(P).all():
        _refuse("MESH_NONFINITE_COORDINATES", f"{int((~np.isfinite(P)).any(axis=1).sum())} node(s) with a non-finite coordinate")
    if P.ndim == 2 and P.shape[1] > 2 and np.any(P[:, 2:] != 0):
        _refuse("MESH_NOT_PLANAR_2D", "nonzero z coordinate; the importer and this gate are planar 2D Cartesian only")
    if extra_area_cells:
        _refuse("MESH_UNSUPPORTED_CELLS", f"cell blocks {extra_area_cells} besides the imported triangle block would be dropped")
    if len(tags) != len(T):
        _refuse("MESH_TAG_UNMAPPED", f"{len(tags)} tags for {len(T)} triangles")
    unmapped = sorted({int(t) for t in np.unique(tags)} - set(tag_to_name))
    if unmapped:
        _refuse("MESH_TAG_UNMAPPED", f"triangle tag(s) {unmapped} have no material region")
    counts = {name: int((tags == tag).sum()) for tag, name in tag_to_name.items()}
    empty = sorted(n for n, k in counts.items() if k == 0)
    if empty:
        _refuse("MESH_EMPTY_REGION", f"region(s) {empty} have no triangle", regions=counts)
    s = np.sort(T, axis=1)
    if len(np.unique(s, axis=0)) != len(s):
        _refuse("MESH_DUPLICATE_TRIANGLE", f"{len(s) - len(np.unique(s, axis=0))} duplicated vertex triple(s)")
    o, e, p1, p2, theta = triangle_terms(P, T)
    bad = np.abs(o) <= e
    if bad.any():
        i = int(np.argmax(bad))
        _refuse("MESH_DEGENERATE_TRIANGLE", f"{int(bad.sum())} triangle(s) with zero or unresolvable area (first: {i}, 2*area {o[i]!r})")
    npos, nneg = int((o > 0).sum()), int((o < 0).sum())
    if npos and nneg:
        _refuse("MESH_ORIENTATION_MIXED", f"{npos} positively and {nneg} negatively oriented triangles (inverted / negative area)")
    out = {}
    for tag, name in tag_to_name.items():
        m = tags == tag
        at = np.abs(o[m]) / 2
        area = math.fsum(at.tolist())
        out[name] = {"tag": int(tag), "triangles": int(m.sum()), "area": area,
                     "E_A": 0.5 * GAMMA4 * math.fsum((np.abs(p1[m]) + np.abs(p2[m])).tolist()) + U * area,
                     "E_NV": NODEVOLUME_ELEMENT_BUDGET * math.fsum((at / np.sin(theta[m])).tolist())}
    return out


def check_nodevolume(region_terms: Dict[str, dict], nodevolumes: Dict[str, np.ndarray], element_counts: Dict[str, int]) -> Dict[str, dict]:
    """Per-region comparison of the NodeVolume sum with the triangle area. Returns the report; raises on the first failure."""
    report = {}
    for name, rt in region_terms.items():
        nv = np.asarray(nodevolumes.get(name, []), dtype=np.float64)
        r = {"triangles": rt["triangles"], "devsim_elements": element_counts.get(name), "nodes": int(len(nv)), "area": rt["area"]}
        report[name] = r
        if element_counts.get(name) != rt["triangles"]:
            _refuse("MESH_REGION_ELEMENT_MISMATCH", f"region {name!r}: DEVSIM holds {element_counts.get(name)} elements, "
                    f"{rt['triangles']} triangles were passed", regions=report, first_failing_region=name)
        if len(nv) == 0 or not np.isfinite(nv).all() or (nv <= 0).any():
            _refuse("MESH_NODEVOLUME_INVALID", f"region {name!r}: {len(nv)} nodes, {int((~np.isfinite(nv)).sum())} non-finite, "
                    f"{int((nv <= 0).sum())} non-positive NodeVolume", regions=report, first_failing_region=name)
        S = math.fsum(nv.tolist())
        E_S = U * S
        B = rt["E_A"] + E_S + rt["E_NV"]
        r.update({"sum_NodeVolume": S, "relative_difference": S / rt["area"] - 1.0, "tau": B / rt["area"],
                  "E_A": rt["E_A"], "E_S": E_S, "E_NV": rt["E_NV"], "pass": bool(abs(S - rt["area"]) <= B)})
        if not r["pass"]:
            _refuse("MESH_AREA_NOT_CONSERVED", f"region {name!r}: triangle area {rt['area']!r}, NodeVolume sum {S!r}, relative "
                    f"difference {r['relative_difference']!r}, tolerance {r['tau']!r}", regions=report, first_failing_region=name)
    return report


def verify_device(module, device: str, mesh: str, region_terms: Dict[str, dict]) -> Dict[str, dict]:
    """Read each region's NodeVolume and element count from DEVSIM and apply check_nodevolume. On refusal, delete the device and
    the mesh (public API), record the cleanup outcome in the same exception, and re-raise it."""
    try:
        nvs, counts = {}, {}
        try:
            for name in region_terms:
                nvs[name] = np.array(module.get_node_model_values(device=device, region=name, name="NodeVolume"), dtype=np.float64)
                counts[name] = len(module.get_element_node_list(device=device, region=name))
        except Exception as read_error:  # noqa: BLE001 -- cannot verify => refuse, never pass
            _refuse("MESH_NODEVOLUME_INVALID", f"NodeVolume / elements could not be read from DEVSIM: {read_error!r}")
        return check_nodevolume(region_terms, nvs, counts)
    except MeshAreaConservationError as exc:
        cleanup = {}
        for key, call, kw in (("delete_device", module.delete_device, {"device": device}),
                              ("delete_mesh", module.delete_mesh, {"mesh": mesh})):
            try:
                call(**kw)
                cleanup[key] = "ok"
            except Exception as ce:  # noqa: BLE001 -- reported, never hidden
                cleanup[key] = f"FAILED: {ce!r}"
        exc.physics_status.update({"device": device, "mesh": mesh, "cleanup": cleanup})
        if any(v != "ok" for v in cleanup.values()):
            exc.args = (f"{exc.args[0]}\nCleanup after refusal failed: {cleanup}",)
        raise
