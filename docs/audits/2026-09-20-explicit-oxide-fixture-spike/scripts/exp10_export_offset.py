# -*- coding: utf-8 -*-
"""EXP 10 (supplementary) -- where does the interface offset of
+0.4975% x grid (seen in EXP 1/2 exports; native level set is at 0.0)
come from: the project's floored-copy export (`save_volume_mesh`), or
ViennaPS's own `Domain.saveVolumeMesh` on the untouched domain?

Also the per-material `save_locos_volume_mesh` route on an explicit planar
stack (wrap flags [False, True]) for comparison. Measurement only."""
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
from tcad.backends.viennaps.io import save_locos_volume_mesh

module = C.module_and_counters()
work = C.scratch("exp10_")
out = {"cases": []}
for g in (0.02, 0.05, 0.10):
    d = 0.30
    dom = C.build_explicit(module, g, d)
    rec = {"grid": g, "requested_um": d, "native": C.native_summary(module, dom)}
    # (a) project export (floored copy)
    m_a = C.measure(module, C.export(dom, work, f"proj_{g}", C.DEPTH))
    # (b) ViennaPS native saveVolumeMesh on a deep copy (no floor, no Expand/intersect)
    cp = C.deep_copy(dom)
    base = str(Path(work) / f"raw_{g}")
    cp.saveVolumeMesh(base)
    m_b = C.measure(module, base + "_volume.vtu")
    # (c) per-material exporter (wrapped stack: Si plain, SiO2 wrapping)
    m_c = C.measure(module, save_locos_volume_mesh(
        dom, [module.Material.Si, module.Material.SiO2], [False, True], str(Path(work) / f"perm_{g}"),
        floor_depth_um=C.DEPTH))
    for tag, m in (("project_save_volume_mesh", m_a), ("vps_native_saveVolumeMesh", m_b),
                   ("save_locos_volume_mesh_per_material", m_c)):
        rec[tag] = {"materials": list(m["materials"]),
                    "si_top": m["column_top"].get("Si", {}).get("mean"),
                    "sio2_bottom": m["column_bottom"].get("SiO2", {}).get("mean"),
                    "sio2_top": m["column_top"].get("SiO2", {}).get("mean"),
                    "sio2_thickness": m["column_thickness"].get("SiO2", {}).get("mean")}
        s = rec[tag]["si_top"]
        rec[tag]["si_top_over_grid"] = (s / g) if s is not None else None
    out["cases"].append(rec)
    print(g, {k: v for k, v in rec.items() if k not in ("native",)})
out["one_over_201"] = 1 / 201.0
out["scratch"] = work
C.save_json("exp10_export_offset.json", out)
print("EXP10 DONE")
