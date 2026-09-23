"""Shared helpers for the Batch 3A audit. READ-ONLY with respect to tcad/, tests/ and existing audits:
it only imports and calls them. Nothing here changes a recipe, the exporter or the analyzer.

Repo root is derived from this file's location (<repo>/docs/audits/<audit>/scripts/audit_common.py).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
REPO = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "integration"))

import numpy as np
import meshio
import viennals as vls

from tcad.backends.viennaps import session
from tcad.backends.viennaps import io as vio
from tcad.mesh import etch_diagnostics as ed
import test_etch_selectivity_real as T          # the physical inputs of the audited test, unchanged
import _explicit_etch_fixture as fx

MODULE = session.require_viennaps()
MATERIAL_NAMES = {int(getattr(MODULE.Material, a)): a for a in dir(MODULE.Material)
                  if not a.startswith("_") and isinstance(getattr(MODULE.Material, a), MODULE.Material)}
WINDOW = (-T.WINDOW_HALF_UM, T.WINDOW_HALF_UM)

# Numerical (not physical) thresholds used ONLY to summarize continuous profiles. Every raw profile is
# stored, so any other threshold can be applied afterwards; none of these is a criterion.
FLOAT_ZERO_THRESHOLDS_UM = (1e-12, 1e-9, 1e-6, 1e-4)
PRIMARY_THRESHOLD_UM = 1e-9

FALLBACKS = []          # derive_regions fallbacks actually used (recorded in the raw output)

_orig_derive_regions = fx.derive_regions


def _derive_regions_with_fallback(window, x_extent, grid, reach, **kw):
    """The fixture's own protected-band rule (8 cells inside the domain edge) is EMPTY on this 8 um
    domain at grid 0.10. Those regions feed only the fixture's own side measurements, never a verdict
    of this audit, so where the original raises we substitute regions and RECORD it."""
    try:
        return _orig_derive_regions(window, x_extent, grid, reach, **kw)
    except ValueError as exc:
        FALLBACKS.append({"grid_um": grid, "error": str(exc)})
        return fx.Regions(window_um=tuple(window), core_um=(window[0] + reach + 4 * grid, window[1] - reach - 4 * grid),
                          protected_bands_um=[(-3.9, -2.5), (2.5, 3.9)], reach_um=reach, edge_margin_cells=4,
                          basis="AUDIT FALLBACK (fixture rule empty at this grid)")


fx.derive_regions = _derive_regions_with_fallback


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    return sha256_bytes(Path(p).read_bytes())


def sha256_arrays(*arrs) -> str:
    h = hashlib.sha256()
    for a in arrs:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode() + str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


# ------------------------------------------------------------------------------------ native
def ls_surface(ls):
    """(nodes (N,2), lines (K,2)) of the zero level set, via viennals ToSurfaceMesh (real connectivity)."""
    mesh = vls.Mesh()
    vls.ToSurfaceMesh(ls, mesh).apply()
    nodes = np.array(mesh.getNodes(), dtype=np.float64).reshape(-1, 3)[:, :2]
    lines = np.array(mesh.getLines(), dtype=np.int64).reshape(-1, 2)
    return nodes, lines


def domain_surfaces(domain):
    mm = domain.getMaterialMap()
    out = []
    for i, ls in enumerate(domain.getLevelSets()):
        nodes, lines = ls_surface(ls)
        out.append({"idx": i, "name": str(mm.getMaterialAtIdx(i)).split("'")[1], "nodes": nodes, "lines": lines})
    return out


def material_map_record(domain):
    mm = domain.getMaterialMap()
    return {"n_level_sets": int(domain.getNumberOfLevelSets()),
            "order": [(i, str(mm.getMaterialAtIdx(i)).split("'")[1], int(mm.getMaterialIdAtIdx(i)))
                      for i in range(int(domain.getNumberOfLevelSets()))],
            "materials_in_domain": sorted(int(m) for m in domain.getMaterialsInDomain())}


def ymax_at(nodes, lines, xs):
    """Highest crossing y of the polyline set with each vertical line x (NaN if none)."""
    xs = np.asarray(xs, dtype=np.float64)
    if len(lines) == 0:
        return np.full(len(xs), np.nan)
    p, q = nodes[lines[:, 0]], nodes[lines[:, 1]]
    x1, y1, x2, y2 = p[:, 0], p[:, 1], q[:, 0], q[:, 1]
    X = xs[:, None]
    inside = (x1 - X) * (x2 - X) <= 0
    dx = x2 - x1
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dx != 0, (X - x1) / dx, 0.0)
    y = np.where(inside, y1 + t * (y2 - y1), -np.inf)
    out = y.max(axis=1)
    out[~np.isfinite(out)] = np.nan
    return out


def edge_offsets(g):
    """Distances s inward from a window edge, dense near the wall: g*2^-j, k*g/100, k*g/2 out to 0.5 um."""
    s = {g * 2.0 ** -j for j in range(0, 14)}
    s |= {k * g / 100.0 for k in range(1, 101)}
    s |= {k * g / 2.0 for k in range(1, int(0.5 / (g / 2.0)) + 1)}
    return np.array(sorted(s))


def _profiles(surf, xs):
    Y = [ymax_at(s["nodes"], s["lines"], xs) for s in surf]
    return Y


def native_metrics(domain, window, g, core):
    """Occupancy of SiO2 / Mask inside the open window from the NATIVE level sets.

    Level sets are nested (LS_k = everything below surface k), so material k occupies, in a column x,
    the interval between the highest crossings of LS_{k-1} and LS_k:  thickness_k(x) = ymax_k - ymax_{k-1}.
    """
    surf = domain_surfaces(domain)
    names = [s["name"] for s in surf]
    lo, hi = window
    off = edge_offsets(g)
    xl, xr = lo + off, hi - off
    xw = np.arange(lo + g / 20.0, hi, g / 10.0)
    idx = {n: i for i, n in enumerate(names)}
    rec = {"level_set_order": names, "n_nodes": [int(len(s["nodes"])) for s in surf],
           "n_lines": [int(len(s["lines"])) for s in surf],
           "surface_sha256": sha256_arrays(*[a for s in surf for a in (s["nodes"], s["lines"])]),
           "materials": {}}
    for mat in ("SiO2", "Mask"):
        if mat not in idx or idx[mat] == 0:
            rec["materials"][mat] = {"present_in_domain": False}
            continue
        k = idx[mat]

        def thick(xs):
            Y = _profiles(surf, xs)
            return Y[k] - Y[k - 1]

        tl, tr, tw = thick(xl), thick(xr), thick(xw)
        m = {"present_in_domain": True, "level_set_index": k,
             "left_edge_profile_s_um__thickness_um": [[float(s), float(t)] for s, t in zip(off, tl)],
             "right_edge_profile_s_um__thickness_um": [[float(s), float(t)] for s, t in zip(off, tr)]}
        for thr in FLOAT_ZERO_THRESHOLDS_UM:
            def pen(t):
                ok = np.isfinite(t) & (t > thr)
                return float(off[ok].max()) if ok.any() else 0.0
            m[f"max_penetration_um_thr_{thr:g}"] = {"left": pen(tl), "right": pen(tr)}
        allx = np.concatenate([xl, xr, xw])
        allt = np.concatenate([tl, tr, tw])
        ok = np.isfinite(allt) & (allt > PRIMARY_THRESHOLD_UM)
        m["window_positions_with_material"] = {
            "thr_um": PRIMARY_THRESHOLD_UM, "n": int(ok.sum()),
            "x_min": float(allx[ok].min()) if ok.any() else None, "x_max": float(allx[ok].max()) if ok.any() else None,
            "min_abs_x": float(np.abs(allx[ok]).min()) if ok.any() else None,
            "max_thickness_um": float(np.nanmax(allt)) if np.isfinite(allt).any() else None,
            "min_thickness_um_over_all_samples": float(np.nanmin(allt)) if np.isfinite(allt).any() else None}
        cx = xw[(xw >= core[0]) & (xw <= core[1])]
        ct = thick(cx)
        m["core"] = {"x": [float(core[0]), float(core[1])], "n_columns": int(len(cx)),
                     "max_thickness_um": float(np.nanmax(ct)) if len(cx) else None,
                     "n_columns_with_material_thr_1e-9": int((ct > PRIMARY_THRESHOLD_UM).sum())}
        m["present_in_window_native"] = bool(ok.any())
        # WHERE (in height) the penetrating native material sits: top / bottom crossing at the penetrating columns
        Yall = [np.concatenate([ymax_at(s["nodes"], s["lines"], xs) for xs in (xl, xr, xw)]) for s in surf]
        if ok.any():
            top, bot = Yall[k][ok], Yall[k - 1][ok]
            m["at_penetrating_columns"] = {"n": int(ok.sum()), "upper_LS_y_min": float(np.nanmin(top)), "upper_LS_y_max": float(np.nanmax(top)),
                                           "lower_LS_y_min": float(np.nanmin(bot)), "lower_LS_y_max": float(np.nanmax(bot))}
        rec["materials"][mat] = m
    rec["_surf"] = surf          # in-memory only; stripped before JSON
    return rec


def xcross_at_y(nodes, lines, y):
    """x positions where the polyline set crosses the horizontal line y."""
    if len(lines) == 0:
        return np.array([])
    p, q = nodes[lines[:, 0]], nodes[lines[:, 1]]
    y1, y2, x1, x2 = p[:, 1], q[:, 1], p[:, 0], q[:, 0]
    hit = (y1 - y) * (y2 - y) <= 0
    dy = y2 - y1
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dy != 0, (y - y1) / dy, 0.0)
    return (x1 + t * (x2 - x1))[hit]


def wall_positions(surf, g):
    """Horizontal position of the window wall (nearest crossing to x = +-2) of the Mask and SiO2 level sets, per
    height, for the mask body (above the oxide top) and the foot region (around/below it). This is the
    measurement that does not confuse an undercut BENEATH the mask with motion of the mask itself."""
    lo, hi = WINDOW
    oxide_top, mask_top = T.OXIDE_UM, T.OXIDE_UM + T.MASK_HEIGHT_UM
    body_h = [float(round(h, 6)) for h in np.arange(oxide_top + 0.05, mask_top - 0.04, 0.05)]
    foot_h = [float(round(h, 6)) for h in np.arange(-0.2, oxide_top + 0.05 + 1e-9, g / 2.0)]
    names = [s["name"] for s in surf]
    out = {"body_heights_um": body_h, "foot_heights_um": foot_h}
    for ls_name in ("Mask", "SiO2"):
        s = surf[names.index(ls_name)]
        for side, edge in (("right", hi), ("left", lo)):
            def nearest(h):
                x = xcross_at_y(s["nodes"], s["lines"], h)
                x = x[np.abs(x - edge) <= 0.5]
                return float(x[np.argmin(np.abs(x - edge))]) if len(x) else None
            out[f"{ls_name}_{side}_body"] = [nearest(h) for h in body_h]
            out[f"{ls_name}_{side}_foot"] = [nearest(h) for h in foot_h]
    return out


FOOT_X_HALF = 0.06           # descriptive crop of the raw evidence around the right wall (x = +2), not a criterion
FOOT_Y = (-0.25, 0.30)


def foot_native(surf):
    """Raw level-set segments (all three level sets) that touch the crop box around the right window wall."""
    out = {}
    lo, hi = WINDOW[1] - FOOT_X_HALF, WINDOW[1] + FOOT_X_HALF
    for s in surf:
        segs = []
        for a, b in s["lines"]:
            p, q = s["nodes"][a], s["nodes"][b]
            for r in (p, q):
                if lo <= r[0] <= hi and FOOT_Y[0] <= r[1] <= FOOT_Y[1]:
                    segs.append([[float(p[0]), float(p[1])], [float(q[0]), float(q[1])]])
                    break
        segs.sort(key=lambda t: (min(t[0][1], t[1][1]), min(t[0][0], t[1][0])))
        out[s["name"]] = segs
    return out


def foot_triangles(mesh):
    """Raw volume-mesh triangles (material-tagged) that touch the same crop box."""
    lo, hi = WINDOW[1] - FOOT_X_HALF, WINDOW[1] + FOOT_X_HALF
    out = []
    for k, tri in enumerate(mesh.triangles):
        p = mesh.points[tri]
        if any(lo <= v[0] <= hi and FOOT_Y[0] <= v[1] <= FOOT_Y[1] for v in p):
            out.append({"material": mesh.materials[k], "vertices": [[float(v[0]), float(v[1])] for v in p]})
    out.sort(key=lambda t: (t["material"], min(v[1] for v in t["vertices"])))
    return out


def strip_private(d):
    if isinstance(d, dict):
        return {k: strip_private(v) for k, v in d.items() if not k.startswith("_")}
    if isinstance(d, list):
        return [strip_private(v) for v in d]
    return d


def mask_body_movement(pre_surf, post_surf, g):
    """Did the rate-0 Mask's own level-set move? Compare pre/post outside the window, in bands measured from
    the wall (no cutoff: every band is reported), for (a) mask thickness, (b) mask top surface, (c) nearest
    distance of post Mask-LS nodes to the pre Mask-LS polyline."""
    names = [s["name"] for s in pre_surf]
    k = names.index("Mask")
    lo, hi = WINDOW
    bands = [("0..1g", 0.0, g), ("1g..3g", g, 3 * g), ("3g..0.5um", 3 * g, 0.5), ("0.5um..1.5um", 0.5, 1.5)]
    out = {}
    for tag, a, b in bands:
        d = np.unique(np.concatenate([np.linspace(a, b, 60)[1:-1], [a + 1e-9 * g, b - 1e-9 * g]]))
        x = np.concatenate([hi + d, lo - d])
        x = x[np.abs(x) < 3.95]
        Y0, Y1 = _profiles(pre_surf, x), _profiles(post_surf, x)
        th_pre, th_post = Y0[k] - Y0[k - 1], Y1[k] - Y1[k - 1]
        out[tag] = {"n": int(len(x)),
                    "max_abs_delta_thickness_um": float(np.nanmax(np.abs(th_post - th_pre))),
                    "max_abs_delta_top_um": float(np.nanmax(np.abs(Y1[k] - Y0[k])))}
    npost, lpre, npre = post_surf[k]["nodes"], pre_surf[k]["lines"], pre_surf[k]["nodes"]
    sel = npost[np.abs(npost[:, 0]) > hi + g]
    p, q = npre[lpre[:, 0]], npre[lpre[:, 1]]
    d = q - p
    L2 = (d ** 2).sum(axis=1)
    best = np.full(len(sel), np.inf)
    for s0, s1, dd, ll in zip(p, q, d, L2):
        t = np.clip(((sel - s0) @ dd) / ll, 0, 1) if ll > 0 else np.zeros(len(sel))
        proj = s0 + t[:, None] * dd
        best = np.minimum(best, np.linalg.norm(sel - proj, axis=1))
    out["post_Mask_LS_nodes_beyond_wall_plus_1g__max_nearest_distance_to_pre_um"] = float(best.max()) if len(sel) else None
    out["n_such_nodes"] = int(len(sel))
    return out


# ------------------------------------------------------------------------------- volume mesh
def load_tagged(path):
    m = meshio.read(str(path))
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    return ed.TaggedMesh(m.points[:, :2], np.asarray(tri.data),
                         tuple(MATERIAL_NAMES.get(int(t), str(t)) for t in tags))


def _components(members, tri):
    parent = {t: t for t in members}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    owner = {}
    for t in members:
        a, b, c = (int(v) for v in tri[t])
        for e in ((a, b), (b, c), (c, a)):
            key = (min(e), max(e))
            if key in owner:
                ra, rb = find(t), find(owner[key])
                if ra != rb:
                    parent[ra] = rb
            else:
                owner[key] = t
    comps = {}
    for t in members:
        comps.setdefault(find(t), []).append(t)
    return list(comps.values())


def _clip_polygon(tri_pts, lo, hi):
    poly = [(float(p[0]), float(p[1])) for p in tri_pts]
    poly = ed._clip(poly, lo, True)
    if poly:
        poly = ed._clip(poly, hi, False)
    return poly


def _poly_area(poly):
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) * 0.5


def _present_at(mesh, mat_idx, x, eps):
    for k in mat_idx:
        p = mesh.points[mesh.triangles[k]]
        if p[:, 0].min() - eps <= x <= p[:, 0].max() + eps and ed._tri_yrange(p, x, eps) is not None:
            return True
    return False


def volume_metrics(mesh, window, core, pre_mesh=None):
    """Per material: positive-area crossings of the window, connected components (shared-edge triangle
    adjacency), whether a component reaches material outside the window or is an isolated island,
    centre-line / core presence, and the paired-analyzer state."""
    lo, hi = window
    eps = ed._geometry_eps([m for m in (mesh, pre_mesh) if m is not None], window)
    P = mesh.points[mesh.triangles]
    minx, maxx = P[:, :, 0].min(axis=1), P[:, :, 0].max(axis=1)
    tri = mesh.triangles
    unique_xy = len({(float(a), float(b)) for a, b in mesh.points})
    out = {"geometry_eps_um": eps, "n_points": int(len(mesh.points)), "n_unique_xy_points": unique_xy,
           "n_triangles": int(len(tri)), "materials": {}}
    analyzer = {}
    if pre_mesh is not None:
        analyzer = {r.material: r for r in ed.analyze_window(pre_mesh, mesh, window)}
    present_rule = ed._Ctx(mesh, lo, hi, eps).present_materials(lo, hi)
    for mat in sorted(set(mesh.materials)):
        idx = [k for k in range(len(tri)) if mesh.materials[k] == mat]
        comps_out, n_pos, n_rule, area_tot, pen = [], 0, 0, 0.0, 0.0
        for members in _components(idx, tri):
            crossing = []
            for k in members:
                if minx[k] < hi and maxx[k] > lo:
                    poly = _clip_polygon(P[k], lo, hi)
                    if len(poly) >= 3:
                        a = _poly_area(poly)
                        if a > 0:
                            crossing.append((k, a, poly))
            if not crossing:
                continue
            xs = [q[0] for _, _, poly in crossing for q in poly]
            ys = [q[1] for _, _, poly in crossing for q in poly]
            touches_lo = any(abs(q[0] - lo) <= eps for _, _, poly in crossing for q in poly)
            touches_hi = any(abs(q[0] - hi) <= eps for _, _, poly in crossing for q in poly)
            outside = [k for k in members if maxx[k] <= lo + eps or minx[k] >= hi - eps]
            cpen = 0.0
            if touches_lo:
                cpen = max(cpen, max(xs) - lo)
            if touches_hi:
                cpen = max(cpen, hi - min(xs))
            carea = sum(a for _, a, _ in crossing)
            n_pos += len(crossing)
            n_rule += sum(1 for _, a, poly in crossing
                          if a > eps * eps and (max(q[0] for q in poly) - min(q[0] for q in poly)) > eps)
            area_tot += carea
            pen = max(pen, cpen)
            comps_out.append({
                "n_triangles_total": len(members), "n_triangles_crossing_window": len(crossing),
                "clipped_area_um2": carea, "clipped_x_range": [min(xs), max(xs)], "clipped_y_range": [min(ys), max(ys)],
                "touches_window_edge_lo": touches_lo, "touches_window_edge_hi": touches_hi,
                "whole_component_bbox": [float(P[members][:, :, 0].min()), float(P[members][:, :, 0].max()),
                                         float(P[members][:, :, 1].min()), float(P[members][:, :, 1].max())],
                "n_triangles_wholly_outside_window": len(outside),
                "connected_to_material_outside_window": bool(outside),
                "isolated_island": not outside,
                "penetration_from_touched_edge_um": cpen})
        comps_out.sort(key=lambda c: -c["clipped_area_um2"])
        cx = np.linspace(core[0], core[1], 41)
        rec = {"n_triangles_total": len(idx), "n_crossing_triangles_positive_area": n_pos,
               "n_crossing_triangles_analyzer_rule": n_rule, "total_clipped_area_um2": area_tot,
               "max_penetration_um": pen, "n_components_crossing_window": len(comps_out),
               "components_top12": comps_out[:12],
               "present_by_analyzer_rule": mat in present_rule,
               "present_on_centre_line_x0": _present_at(mesh, idx, 0.0, eps),
               "core_columns_with_material": int(sum(_present_at(mesh, idx, float(x), eps) for x in cx)),
               "core_columns_sampled": 41}
        if mat in analyzer:
            r = analyzer[mat]
            rec["paired_analyzer"] = {"status": r.status, "displacement_um": r.displacement_um,
                                      "run_x_um": r.run_x_um, "n_intervals": r.n_intervals, "reach": r.reach,
                                      "reason": r.reason}
        out["materials"][mat] = rec
    if pre_mesh is not None:
        for r in analyzer.values():
            if r.material not in out["materials"]:
                out["materials"][r.material] = {"paired_analyzer": {"status": r.status}}
    return out


def classify(native_present, export_present):
    if native_present is None:
        return "UNKNOWN_NATIVE_CONNECTIVITY"
    if native_present and export_present:
        return "NATIVE_AND_EXPORT"
    if export_present:
        return "EXPORT_ONLY"
    if native_present:
        return "NATIVE_ONLY"
    return "ABSENT_BOTH"


def dump_json(obj, path):
    # bytes, not write_text: on Windows text mode would turn every LF into CRLF
    Path(path).write_bytes(json.dumps(strip_private(obj), indent=1, default=float).encode("utf-8"))
