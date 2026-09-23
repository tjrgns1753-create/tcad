# -*- coding: utf-8 -*-
"""EXP 2 -- DIRECT_EXPLICIT_GEOMETRY: planar Si/SiO2 built with
vps.MakePlane only (Si half-space at y=0, SiO2 plane at y=thickness with
addToExisting=True). Requested thickness is an independent input; grid is
never used as thickness. Oxidation constructed 0x, Process.apply 0x,
setInitialOxideThickness 0x are COUNTED (see counts_*), not assumed."""
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C

module = C.module_and_counters()
GRIDS = [0.02, 0.05, 0.10]
THICKNESSES = [0.20, 0.30]        # >= 2 x grid even at grid 0.10
out = {"provenance": "DIRECT_EXPLICIT_GEOMETRY", "cases": []}
work = C.scratch("exp2_")

for g in GRIDS:
    for d in THICKNESSES:
        C.reset_counts()
        dom = C.build_explicit(module, g, d)
        counts = C.snapshot_counts()
        native = C.native_summary(module, dom)
        p = C.export(dom, work, f"explicit_{g}_{d}", C.DEPTH)       # PLAIN save_volume_mesh
        m = C.measure(module, p)
        sio2 = m["column_thickness"].get("SiO2", {"n": 0})
        rec = {
            "grid": g, "requested_um": d, "counts_after_build_and_export": counts,
            "native": native, "materials_in_plain_export": list(m["materials"]),
            "both_materials_preserved": {"Si", "SiO2"} <= set(m["materials"]),
            "sio2_thickness_col": sio2,
            "sio2_abs_err_mean_um": (sio2["mean"] - d) if sio2["n"] else None,
            "sio2_rel_err_mean": ((sio2["mean"] - d) / d) if sio2["n"] else None,
            "sio2_abs_err_min_um": (sio2["min"] - d) if sio2["n"] else None,
            "sio2_abs_err_max_um": (sio2["max"] - d) if sio2["n"] else None,
            "si_top_col": m["column_top"].get("Si"),
            "sio2_bottom_col": m["column_bottom"].get("SiO2"),
            "sio2_top_col": m["column_top"].get("SiO2"),
            "sio2_columns_present": f'{sio2["n"]}/{m["n_columns"]}',
            "sio2_x_range": m["materials"].get("SiO2", {}).get("x_range"),
            "si_x_range": m["materials"].get("Si", {}).get("x_range"),
            "areas": {k: v["area"] for k, v in m["materials"].items()},
            "n_points": m["n_points"], "n_triangles": m["n_triangles"],
        }
        vpsd = str(Path(work) / f"state_{g}_{d}.vpsd")
        try:
            session.save_domain_state(dom, vpsd)
            re_dom = session.load_domain_state(vpsd)
            m2 = C.measure(module, C.export(re_dom, work, f"reload_{g}_{d}", C.DEPTH))
            rec["reload"] = {
                "materials": list(m2["materials"]),
                "area_diff": {k: m2["materials"].get(k, {}).get("area", float("nan")) - v["area"]
                              for k, v in m["materials"].items()},
                "n_triangles": [m["n_triangles"], m2["n_triangles"]],
                "sio2_thickness_mean_diff": (m2["column_thickness"]["SiO2"]["mean"] - sio2["mean"])
                if "SiO2" in m2["column_thickness"] and sio2["n"] else None,
            }
        except Exception as exc:
            rec["reload"] = {"error": f"{type(exc).__name__}: {exc}"}
        out["cases"].append(rec)
        print(f"[grid {g} d={d}] SiO2 mean {sio2.get('mean')} (err {rec['sio2_abs_err_mean_um']}) "
              f"cols {rec['sio2_columns_present']} mats {rec['materials_in_plain_export']} "
              f"counts {counts}")

# cross-grid comparison of identical absolute thickness
cross = {}
for d in THICKNESSES:
    vals = {c["grid"]: c["sio2_thickness_col"].get("mean") for c in out["cases"] if c["requested_um"] == d}
    vs = [v for v in vals.values() if v is not None]
    cross[str(d)] = {"per_grid_mean_thickness": vals,
                     "max_minus_min_um": (max(vs) - min(vs)) if vs else None}
out["cross_grid_same_thickness"] = cross

# static evidence: the builder source contains none of the forbidden calls
import ast
import inspect
import textwrap
src = inspect.getsource(C.build_explicit)
tree = ast.parse(textwrap.dedent(src))
calls = sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)})
out["builder_called_callables_ast"] = calls          # CALLS only; docstrings/comments excluded
out["builder_forbidden_calls_present_ast"] = {
    tok: any(tok in c for c in calls) for tok in ("Oxidation", "Process", "setInitialOxideThickness")
}
out["builder_source"] = src
out["scratch"] = work
C.save_json("exp2_explicit.json", out)
print("EXP2 DONE")
