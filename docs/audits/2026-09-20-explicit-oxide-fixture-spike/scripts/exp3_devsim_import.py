# -*- coding: utf-8 -*-
"""EXP 3 -- DevSim import + contact/pin classification for every EXP 1
(SUPPORTED_DEPOSITED_OXIDE) and EXP 2 (DIRECT_EXPLICIT_GEOMETRY) mesh.

Import completing without an exception is NOT accepted as a pass: region
set, interface existence, shared-edge count, node/element counts, duplicate
coordinates, and the pin classifier's answers are all recorded raw.
"""
import warnings
from collections import defaultdict

from common import *  # noqa: F401,F403
import common as C

from tcad.device.devsim import backend as devsim_backend  # sets DevSim env first
assert devsim_backend.is_available()
import devsim  # noqa: E402
from tcad.mesh.viennaps_adapter import build_process_result  # noqa: E402
from tcad.device.devsim.mesh_import import import_process_result  # noqa: E402
from tcad.mesh.pin import Pin  # noqa: E402
from tcad.device.devsim.contact_probe import (  # noqa: E402
    validate_pin_placement, PinPlacementError,
)

module = C.module_and_counters()
work = C.scratch("exp3_")
GRIDS = [0.02, 0.05, 0.10]
THICKNESSES = [0.20, 0.30]
out = {"cases": []}
_n = [0]


def edge_stats(mesh_path):
    pts, tri, tags = C.load_mesh(mesh_path)
    names = {int(t): C.tag_name(module, t) for t in set(tags.tolist())}
    owners = defaultdict(set)
    for t, tag in zip(tri, tags):
        for i in range(3):
            e = tuple(sorted((int(t[i]), int(t[(i + 1) % 3]))))
            owners[e].add(int(tag))
    inv = {v: k for k, v in names.items()}
    si, ox = inv.get("Si"), inv.get("SiO2")
    shared = sum(1 for o in owners.values() if o == {si, ox}) if si is not None and ox is not None else None
    rounded = {(round(float(x), 9), round(float(y), 9)) for x, y in pts}
    return {"shared_Si_SiO2_edges": shared, "n_points": int(len(pts)),
            "n_unique_coordinates": len(rounded),
            "duplicate_coordinate_points": int(len(pts) - len(rounded))}


def classify_pins(process_result, m):
    xlo, xhi = m["x_range"]
    wafer_x = 0.5 * (xhi - xlo)
    ox_top = m["column_top"]["SiO2"]["mean"]
    si_top = m["column_top"]["Si"]["mean"]
    y_bot = m["y_range"][0]
    y_top = m["y_range"][1]
    cases = [
        ("Si_bottom_boundary", y_bot, "Si"),
        ("SiO2_top_minus_0.005", ox_top - 0.005, "on_insulator"),
        ("outside_above_mesh", y_top + 1.0, "outside_mesh"),
        ("deep_Si_bulk", 0.5 * (y_bot + si_top), "interior_bulk"),
        ("at_Si_SiO2_interface", si_top, None),      # no expectation asserted; recorded raw
    ]
    res = []
    for label, y, expected in cases:
        pin = Pin(name=label, role="Body", x_um=wafer_x, y_um=float(y))
        try:
            got = "region=" + validate_pin_placement(process_result, pin, {"Si"})
        except PinPlacementError as exc:
            got = "reason=" + str(exc.reason)
        exp = None if expected is None else (("region=" + expected) if expected == "Si" else ("reason=" + expected))
        res.append({"pin": label, "y_um": float(y), "got": got, "expected": exp,
                    "match": (got == exp) if exp else None})
    return res


def one(kind, grid, thickness, mesh_path):
    _n[0] += 1
    rec = {"kind": kind, "grid": grid, "requested_um": thickness, "mesh": str(mesh_path)}
    m = C.measure(module, mesh_path)
    rec["edge_stats"] = edge_stats(mesh_path)
    pr = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    rec["process_result_regions"] = sorted(r.name for r in pr.material_regions)
    imported = None
    try:
        imported = import_process_result(
            pr, mesh_name=f"spike_mesh_{_n[0]}", device_name=f"spike_dev_{_n[0]}",
            contact_regions=["Si"], contact_axis="x",
            interface_region_pairs=[("Si", "SiO2")])
        dev = imported.device
        rec["imported"] = {"regions": imported.regions, "contacts": imported.contacts,
                           "interfaces": imported.interfaces}
        rec["devsim_region_list"] = list(devsim.get_region_list(device=dev))
        rec["devsim_interface_list"] = list(devsim.get_interface_list(device=dev))
        rec["devsim_contact_list"] = list(devsim.get_contact_list(device=dev))
        rec["node_counts"] = {r: len(devsim.get_node_model_values(device=dev, region=r, name="x"))
                              for r in rec["devsim_region_list"]}
        try:
            rec["element_counts"] = {r: len(devsim.get_element_node_list(device=dev, region=r))
                                     for r in rec["devsim_region_list"]}
        except Exception as exc:
            rec["element_counts"] = f"unavailable: {type(exc).__name__}: {exc}"
        rec["si_region_present"] = "Si" in rec["devsim_region_list"]
        rec["sio2_region_present"] = "SiO2" in rec["devsim_region_list"]
        rec["interface_present"] = len(rec["devsim_interface_list"]) > 0
        rec["regions_equal_mesh_regions"] = sorted(rec["devsim_region_list"]) == rec["process_result_regions"]
    except Exception as exc:
        rec["import_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if imported is not None:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)
    rec["pins"] = classify_pins(pr, m)
    rec["pins_all_expected_match"] = all(p["match"] is not False for p in rec["pins"])
    print(f"[{kind} g={grid} d={thickness}] regions={rec.get('devsim_region_list')} "
          f"interfaces={rec.get('devsim_interface_list')} nodes={rec.get('node_counts')} "
          f"shared_edges={rec['edge_stats']['shared_Si_SiO2_edges']} "
          f"pins_ok={rec['pins_all_expected_match']} err={rec.get('import_error')}")
    return rec


for g in GRIDS:
    for d in THICKNESSES:
        rate, tsec = 0.10, d / 0.10
        dom, req, res = C.build_deposited(module, g, rate, tsec, work, f"dep_{g}_{d}")
        out["cases"].append(one("SUPPORTED_DEPOSITED_OXIDE", g, req, res["final_mesh"]))
        dom2 = C.build_explicit(module, g, d)
        out["cases"].append(one("DIRECT_EXPLICIT_GEOMETRY", g, d,
                                C.export(dom2, work, f"explicit_{g}_{d}", C.DEPTH)))

out["devsim_devices_left_over"] = list(devsim.get_device_list())
out["scratch"] = work
C.save_json("exp3_devsim_import.json", out)
print("EXP3 DONE  leftover devices:", out["devsim_devices_left_over"])
