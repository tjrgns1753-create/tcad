# -*- coding: utf-8 -*-
"""EXP 4 -- do the EXP 1 / EXP 2 fixtures preserve the scientific intent of
etch-selectivity (#3) and etch-reaches-Si (#11)?

Every etch is a REAL supported registry step run on a deep copy of the
fixture domain (inherited_domain=...). Fixture d = 0.30 um at grid
0.02 / 0.05 / 0.10, two provenances. Raw numbers only; no tolerance is applied.

Scenarios (R = 0.30 um/s nominal rate, budget B = R * time):
  iso_oxide_only_low   material_rates {SiO2:-R, Si:0}          B = 0.5 d   (< d)
  iso_oxide_only_high  material_rates {SiO2:-R, Si:0}          B = d+0.10  (> d)
  iso_plain_low        single rate -R (unselective)            B = 0.5 d
  iso_plain_high       single rate -R                          B = d+0.10
  iso_plain_2d         single rate -R                          B = 2 d
  iso_sel10_2d         material_rates {SiO2:-R, Si:-R/10}      B = 2 d
  dir_plain_2d         directional -R, no material_rates       B = 2 d
  dir_sel10_2d         directional material_rates {SiO2:(-R,0), Si:(-R/10,0)}  B = 2 d
"""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.etching  # noqa: F401
from tcad.process import registry

module = C.module_and_counters()
work = C.scratch("exp4_")
R = 0.30
D = 0.30
GRIDS = [0.02, 0.05, 0.10]
out = {"R_um_per_s": R, "d_um": D, "cases": [], "masked_window": []}
_k = [0]


def etch(domain, model, recipe):
    _k[0] += 1
    cp = C.deep_copy(domain)
    step = registry.get("etching", model)(inherited_domain=cp)
    r = dict(recipe)
    r.setdefault("silicon_depth_um", C.DEPTH)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = step.run(r, str(Path(work) / f"etch_{_k[0]}"))
    return res, cp


def summarize(before, after):
    def mean(m, kind, mat):
        v = m[kind].get(mat)
        return v["mean"] if v and v.get("n") else None
    si_b, si_a = mean(before, "column_top", "Si"), mean(after, "column_top", "Si")
    ox_b = mean(before, "column_thickness", "SiO2")
    ox_a = mean(after, "column_thickness", "SiO2")
    return {"si_top_before": si_b, "si_top_after": si_a,
            "si_depth_removed": (si_b - si_a) if si_b is not None and si_a is not None else None,
            "sio2_before": ox_b, "sio2_after": ox_a,
            "sio2_removed": (ox_b - (ox_a or 0.0)) if ox_b is not None else None,
            "materials_after": list(after["materials"]),
            "sio2_columns_after": after["column_thickness"].get("SiO2", {}).get("n", 0)}


def scenarios():
    yield "iso_oxide_only_low", "isotropic", {"material_rates": {"SiO2": -R, "Si": 0.0}, "etch_time_s": 0.5 * D / R}, 0.5 * D
    yield "iso_oxide_only_high", "isotropic", {"material_rates": {"SiO2": -R, "Si": 0.0}, "etch_time_s": (D + 0.10) / R}, D + 0.10
    yield "iso_plain_low", "isotropic", {"rate": -R, "etch_time_s": 0.5 * D / R}, 0.5 * D
    yield "iso_plain_high", "isotropic", {"rate": -R, "etch_time_s": (D + 0.10) / R}, D + 0.10
    yield "iso_plain_2d", "isotropic", {"rate": -R, "etch_time_s": 2 * D / R}, 2 * D
    yield "iso_sel10_2d", "isotropic", {"material_rates": {"SiO2": -R, "Si": -R / 10.0}, "etch_time_s": 2 * D / R}, 2 * D
    yield "dir_plain_2d", "directional", {"direction": [0, -1, 0], "directional_velocity": -R,
                                          "etch_time_s": 2 * D / R, "calculate_visibility": False}, 2 * D
    yield "dir_sel10_2d", "directional", {"direction": [0, -1, 0],
                                          "material_rates": {"SiO2": (-R, 0.0), "Si": (-R / 10.0, 0.0)},
                                          "etch_time_s": 2 * D / R}, 2 * D


fixtures = {}
for g in GRIDS:
    dom_e = C.build_explicit(module, g, D)
    dom_d, req_d, _ = C.build_deposited(module, g, 0.10, D / 0.10, work, f"dep_{g}")
    fixtures[("DIRECT_EXPLICIT_GEOMETRY", g)] = (dom_e, D)
    fixtures[("SUPPORTED_DEPOSITED_OXIDE", g)] = (dom_d, req_d)

for (prov, g), (dom, requested) in fixtures.items():
    before = C.measure(module, C.export(dom, work, f"before_{prov}_{g}", C.DEPTH))
    for name, model, recipe, budget in scenarios():
        rec = {"provenance": prov, "grid": g, "scenario": name, "model": model,
               "budget_um": budget, "oxide_requested_um": requested,
               "budget_vs_oxide": "below" if budget < requested - 1e-12 else "above"}
        try:
            res, cp_after = etch(dom, model, recipe)
            after = C.measure(module, res["final_mesh"])
            rec.update(summarize(before, after))
            nat = C.native_summary(module, cp_after)
            rec["native_materials_by_index_after"] = nat["materials_by_index"]
            rec["native_si_levelset_ymax_after"] = nat["level_set_surfaces"][0]["y_max"]
            rec["native_si_levelset_ymax_before"] = C.native_summary(module, dom)["level_set_surfaces"][0]["y_max"]
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out["cases"].append(rec)
        print(f"[{prov[:6]} g={g}] {name:20s} B={budget:.3f} Si_removed={rec.get('si_depth_removed')} "
              f"SiO2_removed={rec.get('sio2_removed')} err={rec.get('error')}")

# selectivity ratio + history independence summary
summary = {}
for g in GRIDS:
    row = {}
    for prov in ("DIRECT_EXPLICIT_GEOMETRY", "SUPPORTED_DEPOSITED_OXIDE"):
        get = lambda s: next((c for c in out["cases"] if c["provenance"] == prov and c["grid"] == g and c["scenario"] == s), {})
        for fam in ("iso", "dir"):
            plain, sel = get(f"{fam}_plain_2d"), get(f"{fam}_sel10_2d")
            if plain.get("si_depth_removed") and sel.get("si_depth_removed") is not None:
                row[f"{prov}:{fam}:plain_depth"] = plain["si_depth_removed"]
                row[f"{prov}:{fam}:sel_depth"] = sel["si_depth_removed"]
                row[f"{prov}:{fam}:sel_over_plain"] = sel["si_depth_removed"] / plain["si_depth_removed"]
                row[f"{prov}:{fam}:sio2_removed_sel"] = sel.get("sio2_removed")
    summary[str(g)] = row
out["selectivity_summary"] = summary


# ---- masked window (what #3 actually uses): remask an inherited fixture
def col_at(mesh_path, xs):
    pts, tri, tags = C.load_mesh(mesh_path)
    names = {int(t): C.tag_name(module, t) for t in set(tags.tolist())}
    res = {}
    for x0 in xs:
        res[str(x0)] = {n: C.column_extent(pts, tri, tags == t, x0) for t, n in names.items()}
    return res


for g in (0.02, 0.05):
    for prov in ("DIRECT_EXPLICIT_GEOMETRY", "SUPPORTED_DEPOSITED_OXIDE"):
        dom, requested = fixtures[(prov, g)]
        rec = {"provenance": prov, "grid": g}
        try:
            cols_b = col_at(C.export(dom, work, f"mw_before_{prov}_{g}", C.DEPTH), [0.0, 0.8])
            cp = C.deep_copy(dom)
            step = registry.get("etching", "isotropic")(inherited_domain=cp)
            recipe = {"remask_spans_um": [(-1.0, -0.5), (0.5, 1.0)], "grid_delta_um": g,
                      "x_extent_um": C.X_EXTENT, "pr_thickness_um": 0.3, "mask_material": "Mask",
                      "material_rates": {"SiO2": -R, "Si": -R / 10.0, "Mask": 0.0},
                      "etch_time_s": 2 * D / R, "silicon_depth_um": C.DEPTH}
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = step.run(recipe, str(Path(work) / f"mw_{prov}_{g}"))
            m = C.measure(module, res["final_mesh"])
            rec["materials_after"] = list(m["materials"])
            rec["columns_before"] = cols_b
            rec["columns_after"] = col_at(res["final_mesh"], [0.0, 0.8])
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out["masked_window"].append(rec)
        print(f"[masked-window {prov[:6]} g={g}] mats={rec.get('materials_after')} err={rec.get('error')}")

out["scratch"] = work
C.save_json("exp4_etch.json", out)
print("EXP4 DONE")
