# -*- coding: utf-8 -*-
"""Shared helpers for the explicit-oxide-fixture capability spike.

AUDIT-ONLY. Nothing here is imported by tcad/ or tests/. It only *reads*
production entry points (registry steps, session helpers, io exporters,
mesh_import, contact_probe, WaferState) and measures what they produce.

Provenance labels used throughout (fixed vocabulary, see REPORT.md):
  DIRECT_EXPLICIT_GEOMETRY      SiO2 stated as input geometry (MakePlane)
  SUPPORTED_DEPOSITED_OXIDE     SiO2 made by a supported deposition step
  LOCOS_WRAPPED_EXPLICIT_STACK  pad oxide + mask stack built without a solver
  PROCESS_GROWN_OXIDE           real oxidation kinetics -- UNSUPPORTED today
"""
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from tcad.backends.viennaps import session  # noqa: E402
from tcad.backends.viennaps.io import save_volume_mesh  # noqa: E402

RAW = SPIKE_DIR / "raw"
RAW.mkdir(exist_ok=True)

# ---------------------------------------------------------------- counters
COUNTS = {
    "Oxidation_constructed": 0,
    "Process_constructed": 0,
    "Process_apply": 0,
    "Oxidation_setInitialOxideThickness": 0,
}
SPY_CALLS = []          # (method, repr(args)) recorded on Oxidation spies
SPY_OBJECTS = []        # the spy instances themselves


class _ProcProxy:
    def __init__(self, real):
        self._real = real

    def apply(self):
        COUNTS["Process_apply"] += 1
        return self._real.apply()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _OxidationSpy:
    """Records every method call on a real vps.Oxidation and delegates."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "mask_params_seen", [])

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            SPY_CALLS.append((name, repr(args)))
            if name == "setInitialOxideThickness":
                COUNTS["Oxidation_setInitialOxideThickness"] += 1
            if name == "setMaskParameters":
                # snapshot value NOW (the object could be mutated later)
                self.mask_params_seen.append(int(args[0].contactMode))
            return attr(*args, **kwargs)
        return wrapper


def install_counters(module):
    """Patch the viennaps module object the production code fetches via
    session.require_viennaps(). Idempotent. Returns the originals."""
    if getattr(module, "_spike_patched", False):
        return
    orig_ox, orig_proc = module.Oxidation, module.Process

    def ox_factory(*a, **k):
        COUNTS["Oxidation_constructed"] += 1
        spy = _OxidationSpy(orig_ox(*a, **k))
        SPY_OBJECTS.append(spy)
        return spy

    def proc_factory(*a, **k):
        COUNTS["Process_constructed"] += 1
        return _ProcProxy(orig_proc(*a, **k))

    module.Oxidation = ox_factory
    module.Process = proc_factory
    module._spike_patched = True
    module._spike_orig = (orig_ox, orig_proc)


def reset_counts():
    for k in COUNTS:
        COUNTS[k] = 0
    SPY_CALLS.clear()
    SPY_OBJECTS.clear()


def snapshot_counts():
    return dict(COUNTS)


# ------------------------------------------------------------- scratch dirs
def scratch(prefix):
    """ASCII-only scratch dir (ViennaPS Writer/Reader cannot open non-ASCII
    paths -- see session._ascii_scratch_dir)."""
    return tempfile.mkdtemp(prefix=prefix, dir=session._ascii_scratch_dir())


def module_and_counters():
    module = session.require_viennaps()
    install_counters(module)
    return module


# ---------------------------------------------------------------- mesh read
def load_mesh(path):
    import meshio
    m = meshio.read(str(path))
    block = next(c for c in m.cells if c.type == "triangle")
    idx = m.cells.index(block)
    tags = np.asarray(m.cell_data["Material"][idx]).astype(int)
    return np.asarray(m.points)[:, :2], np.asarray(block.data), tags


def tag_name(module, tag):
    return str(module.Material(int(tag))).split("'")[1]


def _tri_area(p, t):
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    return np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])) / 2.0


def column_extent(pts, tri, mask, x0):
    """[ymin, ymax] of the union of `tri[mask]` cut by the vertical line
    x=x0 (exact scanline), or None."""
    ys = []
    sel = tri[mask]
    if len(sel) == 0:
        return None
    xs = pts[sel][:, :, 0]
    keep = (xs.min(axis=1) <= x0) & (xs.max(axis=1) >= x0)
    for t in sel[keep]:
        v = pts[t]
        for i in range(3):
            (xa, ya), (xb, yb) = v[i], v[(i + 1) % 3]
            if xa == xb:
                if xa == x0:
                    ys += [ya, yb]
            elif (xa - x0) * (xb - x0) <= 0:
                ys.append(ya + (x0 - xa) / (xb - xa) * (yb - ya))
    if not ys:
        return None
    return [float(min(ys)), float(max(ys))]


def measure(module, mesh_path, n_cols=21):
    """Raw geometry of an exported volume mesh: per-material area / bbox /
    triangle count, plus exact vertical scanline extents at n_cols columns
    spread over the whole mesh width."""
    pts, tri, tags = load_mesh(mesh_path)
    names = {int(t): tag_name(module, t) for t in np.unique(tags)}
    x_lo, x_hi = float(pts[:, 0].min()), float(pts[:, 0].max())
    out = {
        "mesh": str(mesh_path),
        "n_points": int(len(pts)), "n_triangles": int(len(tri)),
        "x_range": [x_lo, x_hi], "y_range": [float(pts[:, 1].min()), float(pts[:, 1].max())],
        "materials": {}, "columns": [],
    }
    area_all = _tri_area(pts, tri)
    for t, name in names.items():
        m = tags == t
        used = np.unique(tri[m])
        out["materials"][name] = {
            "tag": t, "n_triangles": int(m.sum()), "area": float(area_all[m].sum()),
            "x_range": [float(pts[used, 0].min()), float(pts[used, 0].max())],
            "y_range": [float(pts[used, 1].min()), float(pts[used, 1].max())],
        }
    eps = 1e-7 * (x_hi - x_lo)
    for x0 in np.linspace(x_lo + eps, x_hi - eps, n_cols):
        col = {"x": float(x0)}
        for t, name in names.items():
            col[name] = column_extent(pts, tri, tags == t, float(x0))
        out["columns"].append(col)
    # column summaries
    def _stat(name, fn):
        vals = [fn(c[name]) for c in out["columns"] if c.get(name)]
        return ({"n": len(vals), "min": float(min(vals)), "max": float(max(vals)),
                 "mean": float(np.mean(vals))} if vals else {"n": 0})
    for name in names.values():
        out.setdefault("column_thickness", {})[name] = _stat(name, lambda e: e[1] - e[0])
        out.setdefault("column_top", {})[name] = _stat(name, lambda e: e[1])
        out.setdefault("column_bottom", {})[name] = _stat(name, lambda e: e[0])
    out["n_columns"] = n_cols
    return out


def native_summary(module, domain):
    """Native (pre-export) view of a ViennaPS domain."""
    import viennals as vls
    mm = domain.getMaterialMap()
    names = [str(mm.getMaterialAtIdx(i)).split("'")[1] for i in range(mm.size())]
    tops = []
    for ls in domain.getLevelSets():
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(ls, mesh).apply()
        nodes = np.array(mesh.getNodes())
        tops.append({"n_surface_nodes": int(len(nodes)),
                     "y_max": float(nodes[:, 1].max()) if len(nodes) else None,
                     "y_min": float(nodes[:, 1].min()) if len(nodes) else None})
    return {"n_level_sets": len(domain.getLevelSets()), "materials_by_index": names,
            "grid_delta": float(domain.getGridDelta()), "level_set_surfaces": tops}


def export(domain, outdir, name, depth):
    return save_volume_mesh(domain, str(Path(outdir) / name), floor_depth_um=depth)


def deep_copy(domain):
    return domain.__class__(domain)


# ----------------------------------------------------------------- fixtures
X_EXTENT = 2.0
Y_EXTENT = 2.0
DEPTH = 1.0


def build_deposited(module, grid, rate, time_s, outdir, tag="dep"):
    """SUPPORTED_DEPOSITED_OXIDE: isotropic SiO2 deposition on virgin Si,
    through the production registry step. Returns (domain, requested_um)."""
    import tcad.process.deposition  # noqa: F401
    from tcad.process import registry
    step = registry.get("deposition", "isotropic")()
    recipe = {"grid_delta_um": grid, "x_extent_um": X_EXTENT, "y_extent_um": Y_EXTENT,
              "silicon_depth_um": DEPTH, "rate": rate, "deposition_time_s": time_s,
              "material": "SiO2"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = step.run(recipe, str(Path(outdir) / tag))
    return step.last_domain, rate * time_s, res


def build_explicit(module, grid, thickness):
    """DIRECT_EXPLICIT_GEOMETRY: Si half-space plane at y=0 + SiO2 plane at
    y=thickness (addToExisting). No Oxidation, no Process.apply, no
    setInitialOxideThickness, thickness is a separate input."""
    dom = session.create_domain(grid, X_EXTENT, Y_EXTENT)
    module.MakePlane(dom, 0.0, module.Material.Si).apply()
    module.MakePlane(dom, float(thickness), module.Material.SiO2, True).apply()
    return dom


def save_json(name, obj):
    path = RAW / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
    return path


def col_at(module, mesh_path, xs):
    """Exact vertical extents per material at the given x columns."""
    pts, tri, tags = load_mesh(mesh_path)
    names = {int(t): tag_name(module, t) for t in set(tags.tolist())}
    return {str(x0): {n: column_extent(pts, tri, tags == t, float(x0)) for t, n in names.items()}
            for x0 in xs}


def edge_pairs(module, mesh_path):
    """Number of mesh edges shared between each pair of materials (a
    conformal interface has > 0; 0 means the materials do not touch by
    edge)."""
    from collections import defaultdict
    pts, tri, tags = load_mesh(mesh_path)
    names = {int(t): tag_name(module, t) for t in set(tags.tolist())}
    owners = defaultdict(set)
    for t, tag in zip(tri, tags):
        for i in range(3):
            owners[tuple(sorted((int(t[i]), int(t[(i + 1) % 3]))))].add(int(tag))
    out = defaultdict(int)
    for o in owners.values():
        if len(o) == 2:
            a, b = sorted(names[x] for x in o)
            out[f"{a}|{b}"] += 1
    rounded = {(round(float(x), 9), round(float(y), 9)) for x, y in pts}
    return {"shared_edges": dict(out), "n_points": int(len(pts)),
            "duplicate_coordinate_points": int(len(pts) - len(rounded))}
