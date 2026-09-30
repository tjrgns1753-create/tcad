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
BUDGET_BASIS = ("ASSUMED_BOUND: E_NV = 128 u sum_t A_t / sin(theta_min,t), inherited from 7H-E2 PLAN section 4, not derived from "
                "DEVSIM source; E_A = gamma4 two-product rounding bound + u A; E_S = u S (correctly rounded fsum)")
# Pre-registered engineering limit on the relative rounding budget B/A that
# may still be called certified (Batch 7H-E6E-R1 PLAN section 1). Not a
# proven DEVSIM error bound, not a physical material-loss threshold, and
# not the area tolerance: a region under this limit is still compared with
# its own B. A region above it is refused as uncertifiable.
MAX_AREA_RELATIVE_UNCERTAINTY = 1e-8


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
    with np.errstate(over="ignore", invalid="ignore"):
        o, e, p1, p2, theta = triangle_terms(P, T)
    if not (np.isfinite(o).all() and np.isfinite(e).all()):
        _refuse("MESH_AREA_BUDGET_NONFINITE", f"{int((~(np.isfinite(o) & np.isfinite(e))).sum())} triangle(s) whose area or "
                "rounding bound is not finite (overflow)")
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
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            cond = at / np.sin(theta[m])
        e_a = 0.5 * GAMMA4 * math.fsum((np.abs(p1[m]) + np.abs(p2[m])).tolist()) + U * area
        e_nv = NODEVOLUME_ELEMENT_BUDGET * math.fsum(cond.tolist()) if np.isfinite(cond).all() else math.inf
        out[name] = {"tag": int(tag), "triangles": int(m.sum()), "area": area, "E_A": e_a, "E_NV": e_nv}
    return out


def check_nodevolume(region_terms: Dict[str, dict], nodevolumes: Dict[str, np.ndarray], element_counts: Dict[str, int]) -> Dict[str, dict]:
    """Per-region certification (7H-E6E-R1 PLAN section 1), in order: element count; A finite > 0; NodeVolume valid; S and every
    budget term finite; B/A <= MAX_AREA_RELATIVE_UNCERTAINTY (decided before, and independently of, S vs A); |S - A| <= B.
    Returns the report; raises on the first failure. The importer calls this same function."""
    report = {}
    for name, rt in region_terms.items():
        nv = np.asarray(nodevolumes.get(name, []), dtype=np.float64)
        A = rt["area"]
        r = {"triangles": rt["triangles"], "devsim_elements": element_counts.get(name), "nodes": int(len(nv)), "A": A,
             "certification_limit": MAX_AREA_RELATIVE_UNCERTAINTY, "budget_basis": BUDGET_BASIS}
        report[name] = r

        def refuse(code, message):
            _refuse(code, f"region {name!r}: {message}", regions=report, first_failing_region=name)
        if element_counts.get(name) != rt["triangles"]:
            refuse("MESH_REGION_ELEMENT_MISMATCH", f"DEVSIM holds {element_counts.get(name)} elements, {rt['triangles']} triangles were passed")
        if not (math.isfinite(A) and A > 0):
            refuse("MESH_AREA_INVALID", f"triangle area {A!r} is not finite and positive")
        if len(nv) == 0 or not np.isfinite(nv).all() or (nv <= 0).any():
            refuse("MESH_NODEVOLUME_INVALID", f"{len(nv)} nodes, {int((~np.isfinite(nv)).sum())} non-finite, "
                   f"{int((nv <= 0).sum())} non-positive NodeVolume")
        with np.errstate(over="ignore"):
            S = math.fsum(nv.tolist()) if np.isfinite(nv.sum()) else math.inf
        E_A, E_NV = rt["E_A"], rt["E_NV"]
        E_S = U * S
        B = E_A + E_S + E_NV
        rel_u = B / A
        r.update({"S": S, "relative_difference": S / A - 1.0, "E_A": E_A, "E_S": E_S, "E_NV": E_NV, "B": B, "relative_uncertainty": rel_u})
        if not all(math.isfinite(v) for v in (S, E_A, E_S, E_NV, B, rel_u)):
            refuse("MESH_AREA_BUDGET_NONFINITE", f"S {S!r}, E_A {E_A!r}, E_S {E_S!r}, E_NV {E_NV!r}, B {B!r} -- not all finite")
        if rel_u > MAX_AREA_RELATIVE_UNCERTAINTY:
            refuse("MESH_AREA_UNCERTAINTY_TOO_LARGE", f"relative rounding budget B/A {rel_u!r} exceeds the certification limit "
                   f"{MAX_AREA_RELATIVE_UNCERTAINTY!r}; area conservation cannot be certified (A {A!r}, S {S!r})")
        r["pass"] = bool(abs(S - A) <= B)
        if not r["pass"]:
            refuse("MESH_AREA_NOT_CONSERVED", f"triangle area {A!r}, NodeVolume sum {S!r}, relative difference "
                   f"{r['relative_difference']!r}, tolerance B/A {rel_u!r}")
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
