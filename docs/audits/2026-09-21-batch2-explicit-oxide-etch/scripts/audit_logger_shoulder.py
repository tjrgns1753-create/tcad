# -*- coding: utf-8 -*-
"""Evidence for the Batch 2 production-diagnostic finding:
`TCADApplication._log_etch_material_summary()` reads each material's max(y) over the WHOLE open
window (x in [lo, hi], boundary nodes included), so the protected shoulder at the mask edge
under-reports what the etch did in the window's centre.

Uses the SAME explicit stack, budgets and recipes as tests/integration/test_oxidation_pr_etch_reaches_si_real.py
(imported constants, nothing re-tuned), saves the pre/post meshes, records the logger's real output,
the central-core measurements (native + exported), the location of the max-y node the logger used,
and how the logger's formula changes with the window it is given (post-processing of the SAME
meshes; no new physics run, no production change).

Writes raw/logger_shoulder.json and raw/meshes/*.vtu.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
INTEGRATION = REPO / "tests" / "integration"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(INTEGRATION))

import numpy as np
import meshio

import _explicit_etch_fixture as fx
import test_oxidation_pr_etch_reaches_si_real as t2
from tcad.backends.viennaps import session

module = session.require_viennaps()
RAW = HERE.parent / "raw"
(RAW / "meshes").mkdir(exist_ok=True)


def material_nodes(mesh_path, material):
    m = meshio.read(mesh_path)
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    tag = int(getattr(module.Material, material))
    idx = sorted({int(n) for t, g in zip(tri.data, tags) if int(g) == tag for n in t})
    return m.points[idx][:, :2]


def logger_formula(mesh_path, material, lo, hi):
    """exactly the arithmetic of top_in_window(): max y over the material's nodes with lo <= x <= hi."""
    nodes = material_nodes(mesh_path, material)
    sel = nodes[(nodes[:, 0] >= lo) & (nodes[:, 0] <= hi)]
    if len(sel) == 0:
        return None, None
    k = int(np.argmax(sel[:, 1]))
    return float(sel[k, 1]), float(sel[k, 0])


out = {"parameters": {"oxide_um": t2.OXIDE_UM, "rate_um_per_s": t2.RATE_UM_PER_S,
                      "T_insufficient_s": t2.T_INSUFFICIENT_S, "T_sufficient_s": t2.T_SUFFICIENT_S,
                      "window": t2.OPEN_WINDOW, "grid": t2.GRID_UM, "mask": t2.MASK_MATERIAL}}
tmp = tempfile.mkdtemp(prefix="logger_shoulder_", dir=session._ascii_scratch_dir())
baseline = fx.build_masked_explicit_stack(
    tmp, x_extent_um=t2.WIDTH_UM, y_extent_um=t2.Y_EXTENT_UM, silicon_depth_um=t2.SILICON_DEPTH_UM,
    oxide_top_um=t2.OXIDE_UM, grid_delta_um=t2.GRID_UM, mask_spans_um=[tuple(s) for s in t2.DEVELOPED_SPANS],
    mask_height_um=t2.PR_THICKNESS_UM, mask_material=t2.MASK_MATERIAL, reach_um=t2.REACH_UM)
ins = fx.run_etch_on_independent_copy(baseline, "isotropic", t2._recipe(t2.T_INSUFFICIENT_S), tmp, "insufficient")
suf = fx.run_etch_on_independent_copy(baseline, "isotropic", t2._recipe(t2.T_SUFFICIENT_S), tmp, "sufficient")
meshes = {"baseline_post_mask_pre_etch": baseline.baseline_mesh_path, "insufficient": ins.final_mesh,
          "sufficient": suf.final_mesh}
for k, p in meshes.items():
    shutil.copy(p, RAW / "meshes" / f"{k}.vtu")
out["core_um"] = baseline.regions.core_um
out["core_measurements"] = {
    "insufficient": {"native": fx.native_removal(ins.core_before, ins.core_after),
                     "exported_view": fx.exported_view(ins.core_before, ins.core_after)},
    "sufficient": {"native": fx.native_removal(suf.core_before, suf.core_after),
                   "exported_view": fx.exported_view(suf.core_before, suf.core_after)},
}

# the logger, called for real
import tcad_2d_stagewise as gui
app = gui.TCADApplication()
try:
    app.withdraw()
    logged = []
    app._log = lambda msg: logged.append(msg)
    app._log_etch_material_summary(meshes["baseline_post_mask_pre_etch"], meshes["insufficient"], t2.OPEN_WINDOW and [t2.OPEN_WINDOW])
    out["logger_output_insufficient"] = "".join(logged)
    logged.clear()
    app._log_etch_material_summary(meshes["baseline_post_mask_pre_etch"], meshes["sufficient"], [t2.OPEN_WINDOW])
    out["logger_output_sufficient"] = "".join(logged)
finally:
    app.destroy()

lo, hi = t2.OPEN_WINDOW
argmax = {}
for state, mesh, material in (("baseline", meshes["baseline_post_mask_pre_etch"], "SiO2"),
                              ("insufficient", meshes["insufficient"], "SiO2"),
                              ("baseline", meshes["baseline_post_mask_pre_etch"], "Si"),
                              ("sufficient", meshes["sufficient"], "Si")):
    y, x = logger_formula(mesh, material, lo, hi)
    argmax[f"{material}@{state}"] = {"max_y_in_window": y, "at_x": x}
out["max_y_node_used_by_logger"] = argmax

# profile of the material's top across the half-window (max y per distinct x): centre vs mask edge
def top_profile(mesh, material):
    nodes = material_nodes(mesh, material)
    prof = {}
    for x, y in nodes:
        k = round(float(x), 6)
        if 0.0 <= k <= hi + 1e-9:
            prof[k] = max(prof.get(k, -1e9), float(y))
    return dict(sorted(prof.items()))

out["top_profile_half_window"] = {
    "SiO2@insufficient": top_profile(meshes["insufficient"], "SiO2"),
    "Si@sufficient": top_profile(meshes["sufficient"], "Si"),
}

# how the logger's formula depends on the window it is handed (same meshes, post-processing only)
sweep = []
for half in [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.95, 0.9, 0.5, 0.0]:
    wlo, whi = -half, half
    row = {"window_half_um": half}
    for material, before, after, key in (("SiO2", "baseline_post_mask_pre_etch", "insufficient", "SiO2_insufficient"),
                                         ("Si", "baseline_post_mask_pre_etch", "sufficient", "Si_sufficient")):
        b, _ = logger_formula(meshes[before], material, wlo, whi)
        a, _ = logger_formula(meshes[after], material, wlo, whi)
        row[key + "_logger_would_report_um"] = None if a is None or b is None else b - a
    sweep.append(row)
out["logger_formula_vs_window_half_width"] = sweep
out["scratch"] = tmp

(RAW / "logger_shoulder.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print("LOGGER (insufficient):", out["logger_output_insufficient"])
print("LOGGER (sufficient):", out["logger_output_sufficient"])
print("core measurements:", json.dumps(out["core_measurements"], indent=1, default=str))
print("max-y node the logger used:", json.dumps(argmax, indent=1))
print("top profile SiO2@insufficient (x: max y):", out["top_profile_half_window"]["SiO2@insufficient"])
print("top profile Si@sufficient (x: max y):", out["top_profile_half_window"]["Si@sufficient"])
print("logger formula vs window half-width:")
for r in sweep:
    print("  ", r)
print("DONE")
