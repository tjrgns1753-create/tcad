"""Scratch: REAL etches with physically narrower open windows; compare candidate depth statistics.
Uses the test fixture but bypasses its core-region derivation (scratch only; repo untouched)."""
import json, os, statistics, sys, tempfile
from pathlib import Path
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
REPO = Path(__file__).resolve().parents[4]   # <repo>/docs/audits/<batch>/scripts/<this file>
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "tests" / "integration"))
import numpy as np, meshio
from tcad.backends.viennaps import session
import _explicit_etch_fixture as fx

M = session.require_viennaps()
names = {int(getattr(M.Material, a)): a for a in dir(M.Material)
         if not a.startswith("_") and isinstance(getattr(M.Material, a), M.Material)}
GRID, WIDTH, YEXT, SIDEPTH, OX, PR = 0.05, 10.0, 8.0, 5.0, 0.2, 1.0
RATE = 0.05
T = {"insufficient": 0.5 * OX / RATE, "sufficient": (OX + 3 * GRID) / RATE}
NOISE = fx.UNCHANGED_UM


def fake_regions(window, x_extent, grid, reach, **kw):
    return fx.Regions(window_um=tuple(window), core_um=(-GRID, GRID),
                      protected_bands_um=[(-4.5, -3.5), (3.5, 4.5)], reach_um=reach,
                      edge_margin_cells=0, basis="scratch")


fx.derive_regions = fake_regions


def profile(path, mat, lo, hi):
    m = meshio.read(path)
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    nodes = set()
    for t, tag in zip(tri.data, tags):
        if names.get(int(tag)) == mat:
            nodes.update(int(i) for i in t)
    cols = {}
    for n in nodes:
        x, y = float(m.points[n][0]), float(m.points[n][1])
        if lo - 1e-9 <= x <= hi + 1e-9:
            k = round(x, 6); cols[k] = max(cols.get(k, -1e9), y)
    return cols


def plateau(c):
    xs = sorted(c); best = (None, 0.0, 0); i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and abs(c[xs[j + 1]] - c[xs[i]]) <= NOISE:
            j += 1
        w = xs[j] - xs[i]
        if (w, j - i + 1) > (best[1], best[2]):
            best = (float(np.mean([c[x] for x in xs[i:j + 1]])), w, j - i + 1)
        i = j + 1
    return best


rows = []
for half in (1.5, 0.5, 0.3, 0.2, 0.15, 0.1):
    spans = [(-WIDTH / 2, -half), (half, WIDTH / 2)]
    with tempfile.TemporaryDirectory() as tmp:
        b = fx.build_masked_explicit_stack(tmp, x_extent_um=WIDTH, y_extent_um=YEXT, silicon_depth_um=SIDEPTH,
                                           oxide_top_um=OX, grid_delta_um=GRID, mask_spans_um=spans,
                                           mask_height_um=PR, mask_material="PHS", reach_um=0.0)
        for case, mat in (("insufficient", "SiO2"), ("sufficient", "Si")):
            o = fx.run_etch_on_independent_copy(b, "isotropic", {"rate": -RATE, "etch_time_s": T[case],
                                                "mask_material": "PHS", "silicon_depth_um": SIDEPTH}, tmp, case)
            cb = profile(b.baseline_mesh_path, mat, -half, half)
            ca = profile(o.final_mesh, mat, -half, half)
            nat = fx.native_removal(o.core_before, o.core_after)   # native at x~0 (|x|<=grid)
            truth = nat["oxide_removed_um"] if mat == "SiO2" else nat["si_removed_um"]
            pb, pa = plateau(cb), plateau(ca)
            rows.append({"half": half, "case": case, "mat": mat, "native_center_removed": round(truth, 4),
                         "A_max": round(max(cb.values()) - max(ca.values()), 4) if ca else None,
                         "B_median": round(statistics.median(cb.values()) - statistics.median(ca.values()), 4) if ca else None,
                         "C_plateau": round(pb[0] - pa[0], 4) if pa[0] is not None and pb[0] is not None else None,
                         "plateau_width_um": round(pa[1], 3), "window_width_um": 2 * half,
                         "spread_after_um": round(max(ca.values()) - min(ca.values()), 4) if ca else None,
                         "n_cols": len(ca)})
            print(json.dumps(rows[-1]), flush=True)
