"""Batch 5 -- read-only probe 3 (test-only scratch): HOW MUCH does the GUI-default Bosch etch vary between runs, and do the
invariants the new test would rest on hold every time?

Probe 2 showed the exported meshes are not bit-identical between runs (Bosch DRIE is a ray-traced model). This probe runs
fresh zero-time thermal -> default etch 10 times and reports, per run, the exported Si top at 9 sampled interior columns,
the Si area, the materials, and then the range over the runs. Nothing is compared to a threshold here; the ranges are
reported so the assertion margins in the test can be judged against them. The default deposition is then run on each etched
result and the same is reported for the film."""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")

import meshio
import numpy as np
import tkinter  # noqa: F401
import tcad_2d_stagewise as gui
from tcad.backends.viennaps import session

module = session.require_viennaps()
for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, **k: None)

XS = np.linspace(-4.5, 4.5, 9)


def per_material(path):
    m = meshio.read(path)
    pts = m.points
    out = {}
    for block, data in zip(m.cells, m.cell_data["Material"]):
        if block.type != "triangle":
            continue
        for tag in np.unique(data):
            tri = block.data[np.asarray(data) == tag]
            p = pts[tri][:, :, :2]
            area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
            name = str(module.Material(int(tag))).split("'")[1]
            ymin, ymax = np.full(len(XS), np.nan), np.full(len(XS), np.nan)
            for j, x in enumerate(XS):
                ys = []
                for t in tri[(p[:, :, 0].min(axis=1) <= x) & (p[:, :, 0].max(axis=1) >= x)] if False else tri:
                    v = pts[t][:, :2]
                    for a, b in ((0, 1), (1, 2), (2, 0)):
                        (xa, ya), (xb, yb) = v[a], v[b]
                        if xa == xb:
                            if xa == x:
                                ys += [ya, yb]
                        elif (xa - x) * (xb - x) <= 0:
                            ys.append(ya + (x - xa) / (xb - xa) * (yb - ya))
                if ys:
                    ymin[j], ymax[j] = min(ys), max(ys)
            out[name] = {"area": float(area.sum()), "ymin": ymin, "ymax": ymax}
    return out


app = gui.TCADApplication()
rows = []
try:
    app.withdraw()
    for i in range(10):
        app.reset()
        app.grid_var.set(0.1)
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.0)
        app.run_oxidation()
        b = per_material(app.last_final_mesh)
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        app.run_etch()
        d = per_material(app.last_final_mesh)
        app.panel_category.set(app._PANEL_LABELS["deposition"])
        app._show_panel_category()
        app.run_deposition()
        e = per_material(app.last_final_mesh)
        rows.append((b, d, e))
        lowered = b["Si"]["ymax"] - d["Si"]["ymax"]
        film = e["SiO2"]["ymax"] - e["SiO2"]["ymin"]
        print(f"run {i + 1}: materials after etch {sorted(d)}; Si top lowered by min/max over 9 columns = {np.nanmin(lowered):.5f} / {np.nanmax(lowered):.5f} um; "
              f"Si area {b['Si']['area']:.4f} -> {d['Si']['area']:.4f}; after deposition {sorted(e)}; SiO2 film thickness min/max = "
              f"{np.nanmin(film):.5f} / {np.nanmax(film):.5f}; film area {e['SiO2']['area']:.5f}; SiO2 present at {int(np.isfinite(e['SiO2']['ymax']).sum())}/9 columns; "
              f"Si top change by deposition max = {np.nanmax(np.abs(e['Si']['ymax'] - d['Si']['ymax'])):.5f}")
    low_all = np.array([r[0]["Si"]["ymax"] - r[1]["Si"]["ymax"] for r in rows])
    print(f"\nOVER 10 RUNS: Si-top lowering: min {np.nanmin(low_all):.5f}  max {np.nanmax(low_all):.5f}  mean {np.nanmean(low_all):.5f} um "
          f"(grid 0.1 um; 0.1*grid = 0.01)")
    areas = np.array([r[1]["Si"]["area"] for r in rows])
    print(f"Si area after etch: min {areas.min():.5f} max {areas.max():.5f} (initial {rows[0][0]['Si']['area']:.5f})")
    film_area = np.array([r[2]["SiO2"]["area"] for r in rows])
    print(f"SiO2 film area: min {film_area.min():.5f} max {film_area.max():.5f}; nominal rate*time*width = 0.05*0.5*10 = {0.05 * 0.5 * 10:.5f}")
finally:
    app.destroy()
