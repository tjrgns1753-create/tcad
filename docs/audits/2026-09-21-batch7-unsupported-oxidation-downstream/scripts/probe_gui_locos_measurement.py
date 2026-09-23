"""Batch 7 -- read-only pre-implementation probe (no production change).

What does the REAL GUI do when a measurement is requested after a positive-time LOCOS request (UNSUPPORTED_BY_MODEL)?
Pass-through observers count devsim.solve, DevSim doping node-model writes and the mesh import; nothing is mocked."""
import json
import os
import re
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")

import tkinter  # noqa: F401
import tcad_2d_stagewise as gui
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim import mesh_import

devsim = devsim_backend.require_devsim()
modal = []
for n in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    setattr(gui.messagebox, n, lambda *a, _n=n, **k: modal.append(_n))

counts = {"solve": 0, "doping_writes": 0, "import_process_result": 0}
DOPING = {"Donors", "Acceptors", "NetDoping"}
orig = {n: getattr(devsim, n) for n in ("solve", "node_model", "set_node_values")}


def solve(*a, **k):
    counts["solve"] += 1
    return orig["solve"](*a, **k)


def node_model(*a, **k):
    if k.get("name") in DOPING:
        counts["doping_writes"] += 1
    return orig["node_model"](*a, **k)


def set_node_values(*a, **k):
    if k.get("name") in DOPING:
        counts["doping_writes"] += 1
    return orig["set_node_values"](*a, **k)


devsim.solve, devsim.node_model, devsim.set_node_values = solve, node_model, set_node_values
orig_import = mesh_import.import_process_result


def counted_import(*a, **k):
    counts["import_process_result"] += 1
    return orig_import(*a, **k)


mesh_import.import_process_result = counted_import

app = gui.TCADApplication()
try:
    app.withdraw()
    app.wafer.width_um, app.wafer.silicon_depth_um = 4.0, 1.0
    app.grid_var.set(0.2)
    app.meas_voltage_var.set(0.01)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.oxidation_method.set("LOCOS (Advanced)")
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.1)
    if os.environ.get("MATERIALIZE") == "1":      # variant: a materialized wafer (a modelled canonical state) exists BEFORE the request
        assert app._materialize_current_wafer(), "materializing the wafer failed"
        print("variant: wafer materialized first; canonical cells:", len(app.wafer_state.cells),
              sorted({c.lifecycle for c in app.wafer_state.cells}))

    def step(label, fn):
        log0 = app.log.get("1.0", "end-1c")
        c0 = dict(counts)
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001 -- probe: record whatever surfaces
            r = f"EXC {type(exc).__name__}: {exc}"
        delta = app.log.get("1.0", "end-1c")[len(log0):]
        print(f"\n### {label}: returned {r!r}; counts delta { {k: counts[k] - c0[k] for k in counts} }; modal {modal}")
        print(f"    processed={app.wafer.processed} stage={app.process_stage} wafer_state={type(app.wafer_state).__name__ if app.wafer_state is not None else None}")
        print("    log tail:", [l for l in delta.strip().splitlines() if l.strip()][-6:])
        return delta

    step("LOCOS positive-time", app.run_oxidation)
    q = app.wafer_state.net_doping_at(0.0, -0.5) if app.wafer_state is not None else None
    print("canonical query at (0,-0.5):", None if q is None else (q.net_doping, (q.physics_status or {}).get("resolution")))
    d1 = step("MEASURE directly (no doping step)", app.run_measurement)
    app.doping_kind.set("Uniform")
    app.dope_uniform_region_var.set("Si")
    app.dope_uniform_donor_var.set(1e16)
    app.dope_uniform_acceptor_var.set(0.0)
    d2 = step("APPLY uniform doping (silent)", lambda: app.run_doping(silent=True))
    d3 = step("MEASURE after the doping attempt", app.run_measurement)
    st = app.wafer_state
    print("\nwafer_state cells:", len(st.cells), "| lifecycles:", sorted({c.lifecycle for c in st.cells}), "| attachments:", len(st.attachments),
          "| query (0,-0.5):", st.net_doping_at(0.0, -0.5).net_doping)
    print("--- FULL log of the second MEASURE (canonical gate) ---")
    print(d3[:2600])
    print("\nleaked devices:", list(devsim.get_device_list()))
    print("physics_status keys:", None if not isinstance(app.last_physics_status, dict) else sorted(app.last_physics_status))
    print("UNSUPPORTED in measurement logs:", "UNSUPPORTED_BY_MODEL" in d1, "UNSUPPORTED_BY_MODEL" in d3)
finally:
    app.destroy()
