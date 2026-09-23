# -*- coding: utf-8 -*-
"""EXP 1 -- SUPPORTED_DEPOSITED_OXIDE: isotropic SiO2 deposition on virgin Si.

Same physical recipe (rate 0.10 um/s) at grids 0.02 / 0.05 / 0.10, two
deposition times (2 s -> 0.20 um, 3 s -> 0.30 um; both >= 2 grid cells even
at 0.10). Raw errors are reported first; no tolerance is applied here.
"""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C

module = C.module_and_counters()
GRIDS = [0.02, 0.05, 0.10]
CASES = [(0.10, 2.0), (0.10, 3.0)]     # (rate um/s, time s)
out = {"provenance": "SUPPORTED_DEPOSITED_OXIDE", "cases": [], "virgin_si": {}}

work = C.scratch("exp1_")

# virgin Si baseline top per grid
for g in GRIDS:
    dom = session.make_mask_spans(g, C.X_EXTENT, C.Y_EXTENT, [], 0.1, substrate_depth_um=C.DEPTH + 1.0)
    p = C.export(dom, work, f"virgin_{g}", C.DEPTH)
    m = C.measure(module, p)
    out["virgin_si"][str(g)] = {"materials": list(m["materials"]),
                                "si_top": m["column_top"]["Si"], "n_points": m["n_points"]}

for g in GRIDS:
    for rate, tsec in CASES:
        C.reset_counts()
        dom, requested, res = C.build_deposited(module, g, rate, tsec, work, f"dep_{g}_{tsec}")
        counts_after_build = C.snapshot_counts()
        native = C.native_summary(module, dom)
        m = C.measure(module, res["final_mesh"])
        sio2 = m["column_thickness"].get("SiO2", {"n": 0})
        rec = {
            "grid": g, "rate": rate, "time_s": tsec, "requested_um": requested,
            "materials": list(m["materials"]),
            "native": native, "counts_after_build": counts_after_build,
            "sio2_thickness_col": sio2,
            "sio2_abs_err_mean_um": (sio2["mean"] - requested) if sio2["n"] else None,
            "sio2_rel_err_mean": ((sio2["mean"] - requested) / requested) if sio2["n"] else None,
            "sio2_abs_err_min_um": (sio2["min"] - requested) if sio2["n"] else None,
            "sio2_abs_err_max_um": (sio2["max"] - requested) if sio2["n"] else None,
            "si_top_col": m["column_top"].get("Si"),
            "sio2_top_col": m["column_top"].get("SiO2"),
            "sio2_bottom_col": m["column_bottom"].get("SiO2"),
            "sio2_columns_present": f'{sio2["n"]}/{m["n_columns"]}',
            "sio2_x_range": m["materials"].get("SiO2", {}).get("x_range"),
            "si_x_range": m["materials"].get("Si", {}).get("x_range"),
            "areas": {k: v["area"] for k, v in m["materials"].items()},
            "n_points": m["n_points"], "n_triangles": m["n_triangles"],
        }
        rec["sio2_area_over_width_um"] = (
            m["materials"]["SiO2"]["area"] / (m["x_range"][1] - m["x_range"][0])
            if "SiO2" in m["materials"] else None)

        # reload identity: .vpsd round trip -> re-export -> compare
        vpsd = str(Path(work) / f"state_{g}_{tsec}.vpsd")
        try:
            session.save_domain_state(dom, vpsd)
            re_dom = session.load_domain_state(vpsd)
            p2 = C.export(re_dom, work, f"reload_{g}_{tsec}", C.DEPTH)
            m2 = C.measure(module, p2)
            rec["reload"] = {
                "materials": list(m2["materials"]),
                "area_diff": {k: m2["materials"].get(k, {}).get("area", float("nan")) - v["area"]
                              for k, v in m["materials"].items()},
                "n_triangles": [m["n_triangles"], m2["n_triangles"]],
                "sio2_thickness_mean_diff": (m2["column_thickness"]["SiO2"]["mean"] - sio2["mean"])
                if "SiO2" in m2["column_thickness"] and sio2["n"] else None,
                "si_top_mean_diff": (m2["column_top"]["Si"]["mean"] - m["column_top"]["Si"]["mean"])
                if "Si" in m2["column_top"] else None,
            }
        except Exception as exc:  # report, do not hide
            rec["reload"] = {"error": f"{type(exc).__name__}: {exc}"}

        # chaining onto a deep copy: supported etch, then supported deposition
        chain = {}
        import tcad.process.etching  # noqa: F401
        import tcad.process.deposition  # noqa: F401
        from tcad.process import registry
        try:
            cp = C.deep_copy(dom)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                e = registry.get("etching", "isotropic")(inherited_domain=cp).run(
                    {"material_rates": {"SiO2": -0.1, "Si": 0.0}, "etch_time_s": 1.0,
                     "silicon_depth_um": C.DEPTH}, str(Path(work) / f"chain_etch_{g}_{tsec}"))
            me = C.measure(module, e["final_mesh"])
            chain["etch"] = {"materials": list(me["materials"]),
                             "sio2_thickness_mean": me["column_thickness"].get("SiO2", {}).get("mean"),
                             "si_top_mean": me["column_top"]["Si"]["mean"],
                             "expected_sio2_after_um": requested - 0.1}
            cp2 = C.deep_copy(dom)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                d = registry.get("deposition", "isotropic")(inherited_domain=cp2).run(
                    {"rate": 0.1, "deposition_time_s": 1.0, "material": "Si3N4",
                     "silicon_depth_um": C.DEPTH}, str(Path(work) / f"chain_dep_{g}_{tsec}"))
            md = C.measure(module, d["final_mesh"])
            chain["deposition_Si3N4"] = {
                "materials": list(md["materials"]),
                "si3n4_thickness_mean": md["column_thickness"].get("Si3N4", {}).get("mean"),
                "sio2_thickness_mean": md["column_thickness"].get("SiO2", {}).get("mean"),
                "si_top_mean": md["column_top"]["Si"]["mean"]}
        except Exception as exc:
            chain["error"] = f"{type(exc).__name__}: {exc}"
        rec["chaining"] = chain
        out["cases"].append(rec)

        print(f"[grid {g} t={tsec}] requested {requested:.4f} um  SiO2 mean "
              f"{sio2.get('mean')}  min {sio2.get('min')} max {sio2.get('max')}  "
              f"cols {rec['sio2_columns_present']}  mats {rec['materials']}  "
              f"Si_top {rec['si_top_col'].get('mean') if rec['si_top_col'] else None}")

out["scratch"] = work
C.save_json("exp1_deposited.json", out)
print("EXP1 DONE")
