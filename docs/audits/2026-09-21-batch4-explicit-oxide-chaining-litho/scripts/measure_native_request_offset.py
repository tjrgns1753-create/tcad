"""Batch 4 round 2 -- PRE-REGISTERED measurement of the native-vs-REQUESTED offset of explicit Si/SiO2 stacks.

Everything below the "REGISTERED" line was fixed BEFORE the first run and is not to be changed after seeing results.

Purpose: state, as facts only, (a) how large the offset between a native level-set position and the requested input value
is, and (b) over which grid / height range that was verified. It does NOT establish a cause; the cause stays
UNKNOWN_NUMERICAL_REPRESENTATION_OFFSET (the installed ViennaLS 5.8.5 / ViennaPS 4.6.2 wheels contain no C++ headers or
sources, and their .pyi stubs / docstrings contain no statement about it).

REGISTERED
  cases      : grid_delta in {0.2, 0.1, 0.05, 0.025} um x requested oxide top in {0.2, 0.25, 0.4, 0.6} um,
               keeping only cases with oxide_top >= 2 * grid_delta (the helper's own rule). Domain x extent 8, y extent 5, 9 columns
               from fx.sample_columns. No process solver is called; the explicit stack is built exactly as the helper builds it.
  measured   : offset_SiO2 = max_columns |native SiO2 top - requested top|, offset_Si = max_columns |native Si top - 0|.
  decision   : a case is WITHIN the observational bound iff max(offset_SiO2, offset_Si) <= 1e-11 * grid_delta
               (fx.native_request_tolerance). A case above it is reported as OUTSIDE the verified range; the bound is NOT changed.
  reading path (a second, separate observation on grid 0.1 / top 0.4): the same native tops read with
               vls.ToSurfaceMesh(..., eps) for eps in {1e-15, 1e-12 (the default), 1e-9}. Reported as observed offsets only.
               Rule: "changes with eps" if the three offsets are not identical; nothing else is concluded from it.
"""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "integration"))
warnings.simplefilter("ignore")

import numpy as np

import _explicit_chain_fixture as fx
from tcad.backends.viennaps import session

module = session.require_viennaps()
import viennals as vls

X_EXTENT, Y_EXTENT = 8.0, 5.0
GRIDS = (0.2, 0.1, 0.05, 0.025)
TOPS = (0.2, 0.25, 0.4, 0.6)


def build(grid, top):
    domain = session.create_domain(grid, X_EXTENT, Y_EXTENT)
    module.MakePlane(domain, 0.0, module.Material.Si).apply()
    module.MakePlane(domain, float(top), module.Material.SiO2, True).apply()
    return domain


def tops_with_eps(domain, xs, eps):
    material_map = domain.getMaterialMap()
    out = {}
    for i, level_set in enumerate(domain.getLevelSets()):
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(level_set, mesh, 0.05, eps).apply()
        nodes = np.array(mesh.getNodes(), dtype=float).reshape(-1, 3)[:, :2]
        lines = np.array(mesh.getLines(), dtype=np.int64).reshape(-1, 2)
        out[str(material_map.getMaterialAtIdx(i)).split("'")[1]] = fx._ymax_at(nodes, lines, xs)
    return out


xs = fx.sample_columns(X_EXTENT, 9)
print(f"{'grid':>6} {'top':>5} {'cells':>6} {'offset SiO2':>12} {'offset Si':>12} {'/grid':>9} {'bound 1e-11*grid':>17}  verdict")
outside = []
for g in GRIDS:
    for t in TOPS:
        if t < 2.0 * g:
            continue
        native = fx.native_column_tops(build(g, t), xs)
        o_ox = float(np.max(np.abs(native["SiO2"] - t)))
        o_si = float(np.max(np.abs(native["Si"])))
        bound = fx.native_request_tolerance(g)
        ok = max(o_ox, o_si) <= bound
        if not ok:
            outside.append((g, t))
        print(f"{g:>6} {t:>5} {t / g:>6.2f} {o_ox:>12.3g} {o_si:>12.3g} {max(o_ox, o_si) / g:>9.3g} {bound:>17.3g}  "
              f"{'WITHIN' if ok else 'OUTSIDE (bound not changed)'}")
print("\ncases outside the observational bound:", outside if outside else "none")

print("\nreading path, grid 0.1 / top 0.4: native offsets with vls.ToSurfaceMesh eps")
domain = build(0.1, 0.4)
seen = []
for eps in (1e-15, 1e-12, 1e-9):
    n = tops_with_eps(domain, xs, eps)
    seen.append((float(np.max(np.abs(n["SiO2"] - 0.4))), float(np.max(np.abs(n["Si"])))))
    print(f"   eps={eps:g}: offset SiO2 {seen[-1][0]:.3g}  offset Si {seen[-1][1]:.3g}")
print("   offsets change with eps:", len(set(seen)) > 1)
