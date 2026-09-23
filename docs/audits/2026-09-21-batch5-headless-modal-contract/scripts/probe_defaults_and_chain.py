"""Batch 5 -- read-only pre-implementation probe (test-only scratch; no production change).

1. records the GUI's ACTUAL out-of-the-box defaults for the etch and deposition panels;
2. runs the real GUI chain  fresh zero-time thermal -> inherited zero-time thermal -> default etch -> default deposition
   (real worker subprocesses, real ViennaPS) and prints, per step, what came back;
3. investigates worker-failure CANDIDATE 1 only: fresh zero-time thermal + invalid grid (-1.0), three times, to see whether
   the failure is a genuine, deterministic backend exception inside the worker (candidate 2 is NOT touched here).
"""
import hashlib
import json
import os
import sys
import time
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

calls = []
for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, _n=name, **k: calls.append(_n))


def mesh_info(path):
    if not path or not Path(path).exists():
        return None
    m = meshio.read(path)
    out = {}
    for block, data in zip(m.cells, m.cell_data["Material"]):
        if block.type != "triangle":
            continue
        for tag in np.unique(data):
            tri = block.data[np.asarray(data) == tag]
            p = m.points[tri][:, :, :2]
            area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
            name = str(module.Material(int(tag))).split("'")[1]
            out[name] = {"triangles": int(len(tri)), "area": float(area.sum()),
                         "y": [float(m.points[np.unique(tri)][:, 1].min()), float(m.points[np.unique(tri)][:, 1].max())]}
    return out


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16] if path and Path(path).exists() else None


def worker_result(app):
    for start in (app.last_domain_state,):
        if start:
            for d in (Path(start).parent, Path(start).parent.parent):
                if (d / "result.json").exists():
                    return json.loads((d / "result.json").read_text(encoding="utf-8"))
    return None


def step(app, label, fn):
    before = app.log.get("1.0", "end-1c")
    n0 = len(calls)
    t0 = time.time()
    fn()
    delta = app.log.get("1.0", "end-1c")[len(before):]
    res = worker_result(app)
    print(f"\n### {label}  ({time.time() - t0:.1f}s)  modal calls this step: {calls[n0:]}")
    print(f"    processed={app.wafer.processed} etched={app.wafer.etched} stage={app.process_stage} completed_steps={len(app.completed_steps)}")
    print(f"    last_final_mesh={app.last_final_mesh and Path(app.last_final_mesh).name} domain_state sha={sha(app.last_domain_state)} mesh sha={sha(app.last_final_mesh)}")
    print(f"    materials={mesh_info(app.last_final_mesh)}")
    if res:
        print(f"    worker: success={res.get('success')} transition={res.get('state_transition')} error={str(res.get('error'))[:200]!r}")
    print(f"    log tail: {delta.strip().splitlines()[-3:]}")
    return delta


app = gui.TCADApplication()
try:
    app.withdraw()
    app.update_idletasks()
    print("== DEFAULTS (as constructed) ==")
    print("grid_var", app.grid_var.get(), "| wafer width/depth", app.wafer.width_um, app.wafer.silicon_depth_um)
    print("etch_model:", app.etch_model.get(), "| etch_time_var:", app.etch_time_var.get(), "| cycles:", app.cycles_var.get(),
          "| polymer_rate:", app.poly_var.get(), "| ion_rate:", app.ion_rate_var.get())
    print("deposition_model:", app.deposition_model.get(), "| iso rate/time/material:", app.dep_isotropic_rate_var.get(),
          app.dep_isotropic_time_var.get(), app.dep_isotropic_material_var.get())
    print("oxidation_method:", app.oxidation_method.get(), "| oxidant:", app.oxidant_var.get())

    app.grid_var.set(0.1)
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.0)
    step(app, "B fresh zero-time thermal", app.run_oxidation)
    step(app, "C inherited zero-time thermal", app.run_oxidation)
    app.panel_category.set(app._PANEL_LABELS["etch"])
    app._show_panel_category()
    step(app, "D default etch", app.run_etch)
    app.panel_category.set(app._PANEL_LABELS["deposition"])
    app._show_panel_category()
    step(app, "E default deposition", app.run_deposition)

    print("\n== candidate 1: fresh zero-time thermal + invalid grid (x3) ==")
    for i in range(3):
        app.reset()
        app.grid_var.set(-1.0)
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.0)
        delta = step(app, f"G candidate-1 run {i + 1}", app.run_oxidation)
        print("    ERROR lines:", [l for l in delta.splitlines() if "ERROR" in l or "FAILED" in l])
    print("\nmodal calls over the whole probe:", calls)
finally:
    app.destroy()
