"""Batch 5 -- read-only probe 2 (test-only scratch; no production change).

(a) determinism of the GUI-default etch (Bosch DRIE) and deposition (Isotropic) on the state left by fresh zero-time
    thermal: the chain fresh-zero -> inherited-zero -> etch -> deposition is run 5 times in FRESH processes' worth of state
    (app.reset() between runs) and the exported meshes are compared byte-for-byte (sha256 of the files' arrays);
(b) what the OLD test's failure recipe (positive-time thermal + invalid grid -1.0) returns now, to record whether the
    positive-time capability gate masks a worker failure.
"""
import hashlib
import json
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

calls = []
for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, _n=name, **k: calls.append(_n))


def mesh_digest(path):
    m = meshio.read(path)
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(m.points).tobytes())
    for block, data in zip(m.cells, m.cell_data["Material"]):
        h.update(block.type.encode())
        h.update(np.ascontiguousarray(block.data).tobytes())
        h.update(np.ascontiguousarray(data).tobytes())
    return h.hexdigest()[:16]


app = gui.TCADApplication()
try:
    app.withdraw()
    app.update_idletasks()
    digests = []
    for i in range(5):
        app.reset()
        app.grid_var.set(0.1)
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.0)
        app.run_oxidation()
        app.run_oxidation()
        b = mesh_digest(app.last_final_mesh)
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        app.run_etch()
        d = mesh_digest(app.last_final_mesh)
        app.panel_category.set(app._PANEL_LABELS["deposition"])
        app._show_panel_category()
        app.run_deposition()
        e = mesh_digest(app.last_final_mesh)
        digests.append((b, d, e))
        print(f"run {i + 1}: zero-time mesh {b} | etch mesh {d} | deposition mesh {e}")
    print("distinct etch meshes:", len({d for _, d, _ in digests}), "| distinct deposition meshes:", len({e for _, _, e in digests}),
          "| distinct zero-time meshes:", len({b for b, _, _ in digests}))

    print("\n== OLD failure recipe: positive-time thermal + invalid grid -1.0, fresh wafer ==")
    for i in range(2):
        app.reset()
        app.grid_var.set(-1.0)
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.1)
        before = app.log.get("1.0", "end-1c")
        app.run_oxidation()
        delta = app.log.get("1.0", "end-1c")[len(before):]
        res = None
        if app.last_domain_state:
            for d in (Path(app.last_domain_state).parent, Path(app.last_domain_state).parent.parent):
                if (d / "result.json").exists():
                    res = json.loads((d / "result.json").read_text(encoding="utf-8"))
        print(f"run {i + 1}: processed={app.wafer.processed} last_final_mesh={bool(app.last_final_mesh)} "
              f"worker success={res and res.get('success')} transition={res and res.get('state_transition')}")
        print("   ERROR lines:", [l for l in delta.splitlines() if "ERROR" in l or "FAILED" in l or "NOT COMPUTED" in l])
    print("\nmodal calls over the whole probe:", calls)
finally:
    app.destroy()
