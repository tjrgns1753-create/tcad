# -*- coding: utf-8 -*-
"""EXP 6 -- LOCOS_WRAPPED_EXPLICIT_STACK: pad oxide + mask stack built by
LocosOxidation._build_locos_geometry() (PRIVATE method -- coupling is
recorded as a finding) with pad_oxide_thickness_um passed EXPLICITLY, so the
grid floor `max(0.02, grid)` is never consulted. No solver is run.

Recorded: constructor/apply counters, native stack, save_locos_volume_mesh
export, reload topology, DevSim import, _make_locos_domain_chainable
before/after, chaining a supported step, and a .vpsd round trip.
"""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C

from tcad.device.devsim import backend as devsim_backend
assert devsim_backend.is_available()
import devsim  # noqa: E402
import tcad.process.oxidation  # noqa: F401,E402
import tcad.process.etching  # noqa: F401,E402
import tcad.process.deposition  # noqa: F401,E402
from tcad.process import registry  # noqa: E402
from tcad.process.oxidation.locos import LocosOxidation  # noqa: E402
from tcad.backends.viennaps.io import save_locos_volume_mesh, is_locos_registered  # noqa: E402
from tcad.mesh.viennaps_adapter import build_process_result  # noqa: E402
from tcad.device.devsim.mesh_import import import_process_result  # noqa: E402

module = C.module_and_counters()
work = C.scratch("exp6_")
CASES = [(0.02, 0.10), (0.02, 0.20), (0.05, 0.10), (0.05, 0.20), (0.10, 0.20)]
XS = [0.0, 0.8, -0.8]        # window centre, under right mask, under left mask
out = {"provenance": "LOCOS_WRAPPED_EXPLICIT_STACK", "cases": []}
_n = [0]


def recipe_for(g, pad):
    return {"grid_delta_um": g, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT,
            "mask_left_um": 0.5, "mask_right_um": 1.5, "pr_thickness_um": 0.3,
            "mask_material": "Mask", "pad_oxide_thickness_um": pad,
            "silicon_depth_um": C.DEPTH}


def build(g, pad):
    step = LocosOxidation()
    geometry, mats, flags = step._build_locos_geometry(recipe_for(g, pad), module)
    return step, geometry, mats, flags


def area_dict(m):
    return {k: v["area"] for k, v in m["materials"].items()}


for g, pad in CASES:
    C.reset_counts()
    step, geometry, mats, flags = build(g, pad)
    counts = C.snapshot_counts()
    rec = {"grid": g, "requested_pad_um": pad, "pad_over_grid": pad / g,
           "counts_after_build": counts,
           "stack_materials": [str(x).split("'")[1] for x in mats], "wrap_flags": list(flags),
           "native": C.native_summary(module, geometry)}
    # (1) dedicated wrapped exporter
    p_a = save_locos_volume_mesh(geometry, mats, flags, str(Path(work) / f"locos_{g}_{pad}"),
                                 floor_depth_um=C.DEPTH)
    m_a = C.measure(module, p_a)
    rec["locos_export"] = {
        "materials": list(m_a["materials"]), "areas": area_dict(m_a),
        "n_points": m_a["n_points"], "n_triangles": m_a["n_triangles"],
        "columns": C.col_at(module, p_a, XS),
        "edge_pairs": C.edge_pairs(module, p_a),
    }
    win = rec["locos_export"]["columns"]["0.0"]
    rec["pad_thickness_window_col"] = (win["SiO2"][1] - win["SiO2"][0]) if win.get("SiO2") else None
    rec["pad_abs_err_um"] = (rec["pad_thickness_window_col"] - pad) if rec["pad_thickness_window_col"] is not None else None
    # (2) PLAIN exporter on the un-registered stack (why the hint exists)
    try:
        p_plain = save_volume_mesh(geometry, str(Path(work) / f"plain_{g}_{pad}"), floor_depth_um=C.DEPTH)
        m_p = C.measure(module, p_plain)
        rec["plain_export_unregistered"] = {"materials": list(m_p["materials"]), "areas": area_dict(m_p)}
    except Exception as exc:
        rec["plain_export_unregistered"] = {"error": f"{type(exc).__name__}: {exc}"}
    # (3) DevSim import of the wrapped export
    _n[0] += 1
    imported = None
    try:
        pr = build_process_result({"final_mesh": p_a, "snapshots": []})
        imported = import_process_result(
            pr, mesh_name=f"spike6_mesh_{_n[0]}", device_name=f"spike6_dev_{_n[0]}",
            contact_regions=["Si"], contact_axis="x",
            interface_region_pairs=[("Si", "SiO2"), ("SiO2", "Mask")])
        dev = imported.device
        rec["devsim"] = {
            "regions": list(devsim.get_region_list(device=dev)),
            "interfaces": list(devsim.get_interface_list(device=dev)),
            "contacts": list(devsim.get_contact_list(device=dev)),
            "node_counts": {r: len(devsim.get_node_model_values(device=dev, region=r, name="x"))
                            for r in devsim.get_region_list(device=dev)},
        }
    except Exception as exc:
        rec["devsim"] = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        if imported is not None:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)
    # (4) _make_locos_domain_chainable before/after
    before_registered = is_locos_registered(geometry)
    step._make_locos_domain_chainable(geometry, mats, flags)
    p_c = save_volume_mesh(geometry, str(Path(work) / f"chainable_{g}_{pad}"), floor_depth_um=C.DEPTH)
    m_c = C.measure(module, p_c)
    rec["chainable"] = {
        "registered_before": before_registered, "registered_after": is_locos_registered(geometry),
        "materials_after": list(m_c["materials"]), "areas_after": area_dict(m_c),
        "area_diff_vs_locos_export": {k: m_c["materials"].get(k, {}).get("area", float("nan")) - v
                                      for k, v in area_dict(m_a).items()},
        "columns_after": C.col_at(module, p_c, XS),
        "native_after": C.native_summary(module, geometry),
        "counts_after_fixup": C.snapshot_counts(),
    }
    # (5) .vpsd round trip of the chainable domain, plain export
    try:
        vpsd = str(Path(work) / f"state_{g}_{pad}.vpsd")
        session.save_domain_state(geometry, vpsd)
        re_dom = session.load_domain_state(vpsd)
        m_r = C.measure(module, save_volume_mesh(re_dom, str(Path(work) / f"reload_{g}_{pad}"),
                                                 floor_depth_um=C.DEPTH))
        rec["vpsd_roundtrip"] = {"materials": list(m_r["materials"]), "areas": area_dict(m_r),
                                 "area_diff_vs_chainable": {k: m_r["materials"].get(k, {}).get("area", float("nan")) - v
                                                            for k, v in area_dict(m_c).items()}}
    except Exception as exc:
        rec["vpsd_roundtrip"] = {"error": f"{type(exc).__name__}: {exc}"}
    out["cases"].append(rec)
    print(f"[g={g} pad={pad}] stack={rec['stack_materials']} pad_meas={rec['pad_thickness_window_col']} "
          f"locos_mats={rec['locos_export']['materials']} plain_mats={rec['plain_export_unregistered'].get('materials')} "
          f"devsim={rec['devsim'].get('regions')}/{rec['devsim'].get('interfaces')} counts={counts}")

# (6) chaining supported steps onto a fresh, chainable stack (fixup applied)
chain = {}
for label, model_cat, model, recipe in [
    ("deposition_Si3N4_0.1um", "deposition", "isotropic",
     {"rate": 0.1, "deposition_time_s": 1.0, "material": "Si3N4", "silicon_depth_um": C.DEPTH}),
    ("etch_oxide_only_0.05um", "etching", "isotropic",
     {"material_rates": {"SiO2": -0.1, "Si": 0.0, "Mask": 0.0}, "etch_time_s": 0.5, "silicon_depth_um": C.DEPTH}),
]:
    g, pad = 0.05, 0.10
    step, geometry, mats, flags = build(g, pad)
    m0 = C.measure(module, save_locos_volume_mesh(geometry, mats, flags, str(Path(work) / f"c0_{label}"),
                                                  floor_depth_um=C.DEPTH))
    step._make_locos_domain_chainable(geometry, mats, flags)
    try:
        nxt = registry.get(model_cat, model)(inherited_domain=geometry)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = nxt.run(dict(recipe), str(Path(work) / f"chain_{label}"))
        m1 = C.measure(module, res["final_mesh"])
        chain[label] = {"materials_before": list(m0["materials"]), "materials_after": list(m1["materials"]),
                        "areas_before": area_dict(m0), "areas_after": area_dict(m1),
                        "columns_after": C.col_at(module, res["final_mesh"], XS)}
    except Exception as exc:
        chain[label] = {"error": f"{type(exc).__name__}: {exc}"}
    print(f"[chain {label}] {chain[label].get('materials_after') or chain[label].get('error')}")
out["chain_onto_chainable"] = chain
out["leftover_devsim_devices"] = list(devsim.get_device_list())
out["scratch"] = work
C.save_json("exp6_wrapped_locos.json", out)
print("EXP6 DONE")
