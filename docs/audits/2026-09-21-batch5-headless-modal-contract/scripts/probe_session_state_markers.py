"""Batch 5 -- minimal read-only reproduction: which SESSION STATE marker does each oxidation-panel outcome light?

`_mark_stage_done`'s own docstring says it lights "markers for steps that actually ran". The marker list is
["Si wafer", "Film / oxide", "PR coat", "Mask alignment", "Exposure", "Develop", "Etch", "PR strip"]."""
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

for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, **k: None)

app = gui.TCADApplication()
try:
    app.withdraw()
    app.grid_var.set(0.1)
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.ox_temp_var.set(1000.0)

    def report(label):
        lit = [app.stage_labels[i].cget("text") for i in sorted(app._stages_done)]
        print(f"{label}: _stages_done={sorted(app._stages_done)} lit markers={lit} | processed={app.wafer.processed} "
              f"process_stage={app.process_stage} | history={app.history}")

    report("fresh wafer, nothing run")
    app.ox_time_var.set(0.0)
    app.run_oxidation()
    report("after FRESH 0 h thermal (materialization, 'no oxidation was performed')")
    app.run_oxidation()
    report("after INHERITED 0 h thermal (identity, 'no oxidation was performed')")
    app.reset()
    app.grid_var.set(0.1)
    app.ox_time_var.set(0.4)
    app.run_oxidation()
    report("after reset + POSITIVE-time thermal (UNSUPPORTED_BY_MODEL)")
finally:
    app.destroy()
