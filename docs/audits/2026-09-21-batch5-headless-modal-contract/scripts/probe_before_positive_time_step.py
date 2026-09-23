"""Batch 5 -- read-only reproduction of the FIRST step of the old target test, with the details the old test never printed.

The old test ran `run_oxidation()` with time_hours = 0.1 on a fresh wafer and asserted a real final mesh. Positive-time
oxidation is UNSUPPORTED_BY_MODEL, so that assertion cannot hold. This probe records what the GUI actually returned. It changes
nothing and makes no claim about production behaviour beyond what it prints."""
import json
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

calls = []
for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    if hasattr(gui.messagebox, name):
        setattr(gui.messagebox, name, lambda *a, _n=name, **k: calls.append(_n))

app = gui.TCADApplication()
try:
    app.withdraw()
    app.update_idletasks()
    print("viewable:", app.winfo_viewable())
    app.grid_var.set(0.1)
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.1)
    before = app.log.get("1.0", "end-1c")
    app.run_oxidation()
    delta = app.log.get("1.0", "end-1c")[len(before):]
    print("processed:", app.wafer.processed, "| process_stage:", app.process_stage, "| last_final_mesh:", app.last_final_mesh)
    print("last_domain_state:", app.last_domain_state)
    print("physics_status:", json.dumps(app.last_physics_status, ensure_ascii=False)[:600])
    result_json = None
    if app.last_domain_state:
        for cand in (Path(app.last_domain_state).parent / "result.json", Path(app.last_domain_state).parent.parent / "result.json"):
            if cand.exists():
                result_json = json.loads(cand.read_text(encoding="utf-8"))
                break
    if app.last_final_mesh:
        import meshio
        m = meshio.read(app.last_final_mesh)
        print("materials in the returned mesh:", sorted({str(n) for n in (m.field_data or {})}) or "(no field_data)",
              "| cell types:", [c.type for c in m.cells])
    if result_json:
        print("worker result: success =", result_json.get("success"), "| state_transition =", result_json.get("state_transition"),
              "| final_mesh =", result_json.get("final_mesh"))
    print("modal calls:", calls)
    print("--- log delta ---")
    print(delta)
finally:
    app.destroy()
