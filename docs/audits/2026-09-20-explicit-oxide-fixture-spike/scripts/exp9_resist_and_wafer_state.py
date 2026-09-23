# -*- coding: utf-8 -*-
"""EXP 9 (supplementary) -- can the fixtures carry the lithography lifecycle
(#6, #14) and WaferState geometry queries (#17 [A])?

(i)  resist coat over an oxide fixture: blanket (one full-width span) and
     patterned (window) -> remask_domain, export, WaferState.query
(ii) a supported deposition chained onto the resist-covered fixture
(iii) WaferState.query on the explicit LOCOS wrapped stack, before and after
     _make_locos_domain_chainable, against the exported mesh
No oxidation is used anywhere; counters are recorded."""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.deposition  # noqa: F401
from tcad.process import registry
from tcad.physics.wafer_state import WaferState
from tcad.process.oxidation.locos import LocosOxidation
from tcad.backends.viennaps.io import save_locos_volume_mesh

module = C.module_and_counters()
work = C.scratch("exp9_")
G, D = 0.05, 0.30
XS = [0.0, 0.8]
out = {"resist": [], "locos_wafer_state": {}}


def cols(mesh):
    return {x: {k: ([round(t, 4) for t in v] if v else None) for k, v in d.items()}
            for x, d in C.col_at(module, mesh, XS).items()}


C.reset_counts()
fixtures = {"DIRECT_EXPLICIT_GEOMETRY": C.build_explicit(module, G, D)}
fixtures["SUPPORTED_DEPOSITED_OXIDE"], _, _ = C.build_deposited(module, G, 0.10, D / 0.10, work, "dep")
for prov, dom in fixtures.items():
    for label, spans in (("blanket_coat", [(-1.0, 1.0)]), ("patterned", [(-1.0, -0.5), (0.5, 1.0)])):
        rec = {"provenance": prov, "resist": label}
        try:
            cp = C.deep_copy(dom)
            resist = session.remask_domain(cp, grid_delta_um=G, x_extent_um=C.X_EXTENT, spans_um=spans,
                                           mask_height_um=0.3, mask_material="PHS")
            ws = WaferState.query(resist)
            rec["wafer_state"] = {"materials": list(ws.materials),
                                  "exposed_at_x0": ws.exposed_material_at(0.0),
                                  "exposed_at_x0.8": ws.exposed_material_at(0.8),
                                  "under_resolved_x_count": len(ws.under_resolved_x())}
            p = C.export(resist, work, f"resist_{prov}_{label}", C.DEPTH)
            rec["export_materials"] = list(C.measure(module, p)["materials"])
            rec["export_columns"] = cols(p)
            # supported deposition chained on top of the resist-covered fixture
            step = registry.get("deposition", "isotropic")(inherited_domain=resist)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = step.run({"rate": 0.1, "deposition_time_s": 1.0, "material": "Si3N4",
                                "silicon_depth_um": C.DEPTH}, str(Path(work) / f"dep_on_{prov}_{label}"))
            rec["after_deposition_materials"] = list(C.measure(module, res["final_mesh"])["materials"])
            rec["after_deposition_columns"] = cols(res["final_mesh"])
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out["resist"].append(rec)
        print(f"[{prov[:6]} {label}] ws={rec.get('wafer_state')} export={rec.get('export_materials')} "
              f"after_dep={rec.get('after_deposition_materials')} err={rec.get('error')}")
out["counts_resist_section"] = C.snapshot_counts()

# (iii) WaferState on the explicit LOCOS stack
recipe = {"grid_delta_um": G, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT, "mask_left_um": 0.5,
          "mask_right_um": 1.5, "pr_thickness_um": 0.3, "mask_material": "Mask",
          "pad_oxide_thickness_um": 0.10, "silicon_depth_um": C.DEPTH}
step = LocosOxidation()
geometry, mats, flags = step._build_locos_geometry(recipe, module)
for label in ("before_chainable", "after_chainable"):
    if label == "after_chainable":
        step._make_locos_domain_chainable(geometry, mats, flags)
    try:
        ws = WaferState.query(geometry)
        rec = {"materials": list(ws.materials), "exposed_at_x0": ws.exposed_material_at(0.0),
               "exposed_at_x0.8": ws.exposed_material_at(0.8),
               "under_resolved_x_count": len(ws.under_resolved_x())}
    except Exception as exc:
        rec = {"error": f"{type(exc).__name__}: {exc}"}
    out["locos_wafer_state"][label] = rec
    print(label, rec)
p = save_locos_volume_mesh(geometry, mats, flags, str(Path(work) / "locos_truth"), floor_depth_um=C.DEPTH)
out["locos_export_columns"] = cols(p)
out["counts_total"] = C.snapshot_counts()
out["scratch"] = work
C.save_json("exp9_resist_and_wafer_state.json", out)
print("EXP9 DONE", C.snapshot_counts())
