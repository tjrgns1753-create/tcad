"""Tier 1 doping-truthfulness -- REAL GUI reproduction (nothing mocked; pass-through observers only).

Drives the real TCADApplication (window withdrawn) through real ViennaPS meshing and, for the measurement follow-up, real DevSim.
For each scenario it prints what run_doping() returned and the canonical WaferStateV2 / GUI deltas it left behind:
  supported | unresolved (materialize, then refused LOCOS) | legacy (refused LOCOS on a fresh wafer) | zero | refused reattach.
Read-only with respect to the repository. Run before and after the production change; the outputs are kept in raw/."""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")

import tkinter  # noqa: F401,E402
import tcad_2d_stagewise as gui  # noqa: E402
from tcad.device.devsim import backend as devsim_backend  # noqa: E402
from tcad.device.devsim import mesh_import  # noqa: E402

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


def new_app():
    app = gui.TCADApplication()
    app.withdraw()
    app.wafer.width_um, app.wafer.silicon_depth_um = 4.0, 1.0
    app.grid_var.set(0.2)
    app.meas_voltage_var.set(0.01)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")
    app.doping_kind.set("Uniform")
    app.dope_uniform_region_var.set("Si")
    return app


def refused_locos(app):
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.oxidation_method.set("LOCOS (Advanced)")
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.1)
    app.run_oxidation()


def snap(app):
    st = app.wafer_state
    return {
        "attachments": [a.attachment_id for a in st.attachments] if st is not None else None,
        "events": len(st.events) if st is not None else None,
        "unresolved": len(st.unresolved_inventory) if st is not None else None,
        "lifecycles": sorted({c.lifecycle for c in st.cells}) if st is not None else None,
        "last_doped_result": id(app.last_doped_result) if app.last_doped_result is not None else None,
        "history": list(app.history),
        "viewer_layer": app.viewer_layer_var.get(),
        "log_len": len(app.log.get("1.0", "end-1c")),
    }


def report(label, app, fn):
    before = snap(app)
    m0, c0 = len(modal), dict(counts)
    ret = fn()
    after = snap(app)
    st = app.wafer_state
    new_events = st.events[before["events"]:] if st is not None and before["events"] is not None else (st.events if st is not None else ())
    delta = app.log.get("1.0", "end-1c")[before["log_len"]:]
    print(f"\n######## {label}")
    print(f"run_doping() returned            : {ret!r}")
    print(f"active attachment ids  before/after: {before['attachments']} -> {after['attachments']}")
    print(f"unresolved inventory   before/after: {before['unresolved']} -> {after['unresolved']}")
    print(f"cell lifecycles        before/after: {before['lifecycles']} -> {after['lifecycles']}")
    print(f"new events                         : {[(e.event_id, e.category, e.process_category, e.model_status) for e in new_events]}")
    print(f"last_doped_result      before/after: {before['last_doped_result']} -> {after['last_doped_result']}  (changed: {before['last_doped_result'] != after['last_doped_result']})")
    print(f"history                before/after: {before['history']} -> {after['history']}")
    print(f"viewer layer           before/after: {before['viewer_layer']} -> {after['viewer_layer']}")
    print(f"modal calls in this step           : {modal[m0:]}")
    print(f"observer counts delta              : { {k: counts[k] - c0[k] for k in counts} }")
    print("log delta (verbatim):")
    for line in delta.strip().splitlines():
        if line.strip():
            print("   |", line)
    return ret


def measure_after(label, app):
    c0, m0 = dict(counts), len(modal)
    log0 = len(app.log.get("1.0", "end-1c"))
    app.run_measurement()
    d = app.log.get("1.0", "end-1c")[log0:]
    print(f"\n---- {label}: MEASURE afterwards -> observer delta { {k: counts[k] - c0[k] for k in counts} }, modal {modal[m0:]}")
    print("     log:", [l for l in d.strip().splitlines() if l.strip()][-4:])
    print("     leaked devices:", list(devsim.get_device_list()))


def set_uniform(app, donor, acceptor):
    app.dope_uniform_donor_var.set(donor)
    app.dope_uniform_acceptor_var.set(acceptor)


# A -- supported: a wafer that is exactly MODELLED virgin Si (materialized only) ------------------------------------------------
app = new_app()
try:
    assert app._materialize_current_wafer()
    set_uniform(app, 1e16, 0.0)
    report("A  supported uniform doping on exact MODELLED virgin Si", app, lambda: app.run_doping(silent=True))
    st = app.wafer_state
    q = st.net_doping_at(0.0, -0.5)
    print("canonical query at (0,-0.5) net_doping:", q.net_doping)
finally:
    app.destroy()

# B -- UNRESOLVED: materialized first, then a refused positive-time LOCOS ---------------------------------------------------------
app = new_app()
try:
    assert app._materialize_current_wafer()
    refused_locos(app)
    set_uniform(app, 1e16, 0.0)
    report("B  uniform doping after refused LOCOS (materialized first -> UNRESOLVED cell)", app, lambda: app.run_doping(silent=True))
    measure_after("B", app)
finally:
    app.destroy()

# C -- LEGACY_UNRESOLVED: refused LOCOS on a fresh wafer ----------------------------------------------------------------------------
app = new_app()
try:
    refused_locos(app)
    set_uniform(app, 1e16, 0.0)
    report("C  uniform doping after refused LOCOS (fresh -> LEGACY_UNRESOLVED cells)", app, lambda: app.run_doping(silent=True))
    measure_after("C", app)
finally:
    app.destroy()

# C2 -- same, non-silent (what the APPLY DOPING button does) ---------------------------------------------------------------------
app = new_app()
try:
    refused_locos(app)
    set_uniform(app, 1e16, 0.0)
    report("C2 same as C, NON-silent (button path)", app, lambda: app.run_doping())
finally:
    app.destroy()

# D -- refused reattach: a stale last_doped_result exists, the canonical state holds no attachment --------------------------------
app = new_app()
try:
    assert app._materialize_current_wafer()
    set_uniform(app, 1e16, 0.0)
    assert app.run_doping(silent=True)
    stale_id = id(app.last_doped_result)
    refused_locos(app)                       # new mesh, attachments moved to the unresolved ledger
    print("\n(D setup) doping stale:", app._doping_is_stale(), "| attachments:", [a.attachment_id for a in app.wafer_state.attachments],
          "| unresolved:", len(app.wafer_state.unresolved_inventory))
    report("D  reattach=True with a stale result and no canonical attachment", app, lambda: app.run_doping(silent=True, reattach=True))
    print("stale result kept:", id(app.last_doped_result) == stale_id)
    measure_after("D", app)
finally:
    app.destroy()

# F -- zero concentration on supported state and on refused state ---------------------------------------------------------------------
for tag, refuse in (("F1 zero concentration on exact MODELLED virgin Si", False), ("F2 zero concentration after refused LOCOS", True)):
    app = new_app()
    try:
        assert app._materialize_current_wafer()
        if refuse:
            refused_locos(app)
        set_uniform(app, 0.0, 0.0)
        report(tag, app, lambda: app.run_doping(silent=True))
    finally:
        app.destroy()
print("\nleaked devices at end:", list(devsim.get_device_list()))
