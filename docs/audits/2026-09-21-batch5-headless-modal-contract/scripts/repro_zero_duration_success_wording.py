"""Batch 5 -- MINIMAL reproduction of the two GUI-state findings that stop the migration (production is NOT modified).

Finding 1: a 0 h thermal oxidation (fresh materialization AND inherited identity) prints
           "ZERO-DURATION OXIDATION: NO OXIDATION PERFORMED" and then, a few lines later, the log also contains
           "ViennaPS: ViennaPS thermal oxidation simulation complete." (the unconditional success `_notify_info` at the end of
           run_oxidation(), tcad_2d_stagewise.py, the call after `self.redraw()`).
Finding 2: the same two steps light the SESSION STATE marker "Film / oxide" (`_mark_stage_done(1)`), although no oxidation was
           performed and no film was created; the marker's own docstring says it lights "steps that actually ran".
Nothing here is asserted against a threshold; it prints what is there and exits 0 so the evidence can be read."""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")

import tkinter  # noqa: F401
import tcad_2d_stagewise as gui

modal = []
for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, _n=name, **k: modal.append(_n))

app = gui.TCADApplication()
try:
    app.withdraw()
    app.grid_var.set(0.1)
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.0)
    for label in ("FRESH 0 h thermal (materialization)", "INHERITED 0 h thermal (identity)"):
        before = app.log.get("1.0", "end-1c")
        app.run_oxidation()
        delta = app.log.get("1.0", "end-1c")[len(before):]
        lines = [l.strip() for l in delta.splitlines() if l.strip()]
        banner = "ZERO-DURATION OXIDATION: NO OXIDATION PERFORMED" in delta
        success_line = [l for l in lines if "simulation complete" in l]
        lit = [app.stage_labels[i].cget("text") for i in sorted(app._stages_done)]
        print(f"[{label}] modal calls so far: {modal}")
        print(f"   banner 'NO OXIDATION PERFORMED' present: {banner}")
        print(f"   lines containing 'simulation complete': {success_line}")
        print(f"   processed={app.wafer.processed} process_stage={app.process_stage!r} | lit SESSION STATE markers: {lit}")
finally:
    app.destroy()
