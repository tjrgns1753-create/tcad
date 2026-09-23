# -*- coding: utf-8 -*-
"""EXP 5 -- explicit thin SiO2 layers WITHOUT oxidation: thickness <, ==, >
grid. For each case record (a) whether the layer exists in the exported
mesh and how thick it really is, (b) what WaferState.query() /
under_resolved_x() / exposed_material_at() report, so that a layer that
vanished from the export, or a warning attached to a layer that is in fact
resolved, is visible (false PASS / false warning).

Routes: DIRECT_EXPLICIT_GEOMETRY (MakePlane), SUPPORTED_DEPOSITED_OXIDE
(thin isotropic deposition), and a SUPPORTED residual-after-etch layer
(deposit 0.30 um, oxide-only etch leaving a thin remainder).
"""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.physics.wafer_state import WaferState

module = C.module_and_counters()
work = C.scratch("exp5_")
out = {"cases": []}


def export_truth_top_material(m, x_frac=0.5):
    col = m["columns"][int(round(x_frac * (len(m["columns"]) - 1)))]
    best, top = None, None
    for k, v in col.items():
        if k == "x" or not v:
            continue
        if top is None or v[1] > top:
            best, top = k, v[1]
    return best


def record(kind, grid, requested, dom, label):
    p = C.export(dom, work, f"{label}", C.DEPTH)
    m = C.measure(module, p)
    sio2 = m["column_thickness"].get("SiO2", {"n": 0})
    ws = WaferState.query(dom)
    thin = ws.under_resolved_x()
    rec = {
        "kind": kind, "grid": grid, "requested_um": requested,
        "requested_over_grid": requested / grid,
        "native": C.native_summary(module, dom),
        "export_materials": list(m["materials"]),
        "layer_in_export": sio2["n"] > 0,
        "sio2_columns_present": f'{sio2["n"]}/{m["n_columns"]}',
        "sio2_thickness_mean": sio2.get("mean"), "sio2_thickness_min": sio2.get("min"),
        "sio2_thickness_max": sio2.get("max"),
        "sio2_abs_err_mean": (sio2["mean"] - requested) if sio2["n"] else None,
        "sio2_rel_err_mean": ((sio2["mean"] - requested) / requested) if sio2["n"] else None,
        "wafer_state_materials": list(ws.materials),
        "wafer_state_exposed_materials": sorted(ws.exposed_materials()),
        "wafer_state_exposed_at_x0": ws.exposed_material_at(0.0),
        "export_truth_top_material_at_mid_column": export_truth_top_material(m),
        "under_resolved_x_count": len(thin),
        "under_resolved_x_span": [min(thin), max(thin)] if thin else None,
    }
    rec["exposed_agrees_with_export"] = (rec["wafer_state_exposed_at_x0"]
                                         == rec["export_truth_top_material_at_mid_column"])
    if rec["layer_in_export"] and not thin:
        rec["verdict"] = "layer present, NOT flagged under-resolved"
    elif rec["layer_in_export"] and thin:
        rec["verdict"] = "layer present, flagged under-resolved"
    elif thin:
        rec["verdict"] = "layer ABSENT from export, flagged under-resolved"
    else:
        rec["verdict"] = "layer ABSENT from export, NOT flagged (silent loss)"
    out["cases"].append(rec)
    print(f"[{kind} g={grid} req={requested:.4f} ({requested/grid:.2f}g)] in_export={rec['layer_in_export']} "
          f"mean={rec['sio2_thickness_mean']} thin_x={rec['under_resolved_x_count']} "
          f"exposed_ws={rec['wafer_state_exposed_at_x0']} truth={rec['export_truth_top_material_at_mid_column']} "
          f"=> {rec['verdict']}")
    return rec


MULTS = [0.02, 0.05, 0.10, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
for g in (0.02, 0.05, 0.10):
    for mult in MULTS:
        t = round(mult * g, 6)
        record("DIRECT_EXPLICIT_GEOMETRY", g, t, C.build_explicit(module, g, t), f"exp_{g}_{mult}")

g = 0.05
for mult in (0.5, 1.0, 1.5):
    t = round(mult * g, 6)
    dom, req, _ = C.build_deposited(module, g, 0.10, t / 0.10, work, f"depthin_{mult}")
    record("SUPPORTED_DEPOSITED_OXIDE(thin)", g, req, dom, f"depthin_{mult}")

# residual layer left by a supported oxide-only etch of a thick deposit
for mult in (0.5, 1.0):
    t = round(mult * g, 6)
    dom, req, _ = C.build_deposited(module, g, 0.10, 3.0, work, f"resid_base_{mult}")
    cp = C.deep_copy(dom)
    step = registry.get("etching", "isotropic")(inherited_domain=cp)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        step.run({"material_rates": {"SiO2": -0.30, "Si": 0.0},
                  "etch_time_s": (0.30 - t) / 0.30, "silicon_depth_um": C.DEPTH},
                 str(Path(work) / f"resid_{mult}"))
    record("SUPPORTED_RESIDUAL_AFTER_ETCH", g, t, step.last_domain, f"resid_{mult}")

out["scratch"] = work
C.save_json("exp5_thin_layer.json", out)
print("EXP5 DONE")
