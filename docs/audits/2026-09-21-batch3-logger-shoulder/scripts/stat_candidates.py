"""Scratch: compare candidate 'etched depth' statistics on the saved Batch-2 meshes.
Read-only w.r.t. the repo. Per-material top(x) = max y of that material's nodes at each x column."""
import json, sys, statistics
from pathlib import Path
REPO = Path(__file__).resolve().parents[4]   # <repo>/docs/audits/<batch>/scripts/<this file>
sys.path.insert(0, str(REPO))
import numpy as np
import meshio
from tcad.backends.viennaps import session as _s
vps = _s.require_viennaps()

AUD = str(REPO / "docs" / "audits" / "2026-09-21-batch2-explicit-oxide-etch" / "raw" / "meshes")
NOISE = 0.001  # project's own noise floor used by the logger
GRID = 0.05

names = {}
for a in dir(vps.Material):
    if a.startswith("_"):
        continue
    v = getattr(vps.Material, a)
    if isinstance(v, vps.Material):
        names[int(v)] = a


def read(path):
    m = meshio.read(path)
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    by = {}
    for t, tag in zip(tri.data, tags):
        by.setdefault(names.get(int(tag), str(tag)), set()).update(int(i) for i in t)
    return m.points, by


def top_profile(pts, by, mat, lo, hi):
    cols = {}
    for n in by.get(mat, ()):
        x, y = pts[n][0], pts[n][1]
        if lo <= x <= hi:
            k = round(float(x), 6)
            cols[k] = max(cols.get(k, -1e9), float(y))
    return cols  # x -> top


def stat_max(c):
    return max(c.values())


def stat_median(c):
    return statistics.median(c.values())


def stat_plateau(c):
    """largest contiguous-x run whose tops agree with each other within NOISE; returns (value, width, n)."""
    xs = sorted(c)
    best = (None, 0.0, 0)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and abs(c[xs[j + 1]] - c[xs[i]]) <= NOISE:
            j += 1
        w = xs[j] - xs[i]
        if (w, j - i + 1) > (best[1], best[2]):
            best = (float(np.mean([c[x] for x in xs[i:j + 1]])), w, j - i + 1)
        i = j + 1
    return best


base = read(f"{AUD}/baseline_post_mask_pre_etch.vtu")
cases = {"insufficient": ("SiO2", read(f"{AUD}/insufficient.vtu")),
         "sufficient": ("Si", read(f"{AUD}/sufficient.vtu"))}
truth = {"insufficient": 0.1, "sufficient": 0.15}  # native central-core removal (from logger_shoulder.json)

out = []
for half in (1.5, 1.45, 1.4, 1.0, 0.5, 0.3, 0.2, 0.1, 0.05):
    for case, (mat, (pts, by)) in cases.items():
        cb = top_profile(*base, mat, -half, half)
        ca = top_profile(pts, by, mat, -half, half)
        if not cb or not ca:
            out.append((half, case, "no nodes")); continue
        row = {"half": half, "case": case, "mat": mat, "truth": truth[case], "ncols": len(ca)}
        row["A_max"] = round(stat_max(cb) - stat_max(ca), 4)
        row["B_median"] = round(stat_median(cb) - stat_median(ca), 4)
        pb, pa = stat_plateau(cb), stat_plateau(ca)
        row["C_plateau"] = None if pb[0] is None or pa[0] is None else round(pb[0] - pa[0], 4)
        row["C_plateau_width_after"] = round(pa[1], 3)
        row["spread_after"] = round(max(ca.values()) - min(ca.values()), 4)
        out.append(row)
for r in out:
    print(json.dumps(r))
