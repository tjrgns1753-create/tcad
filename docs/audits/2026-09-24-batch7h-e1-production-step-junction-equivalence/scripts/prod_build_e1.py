"""Batch 7H-E1 step A: production build + control + pre-checks (one subprocess, remote only).

Reproduces the GUI sequence with the GUI default arguments by calling the SAME production library functions
(no production code is modified; the GUI itself is not executed):
  materialize wafer (make_mask_spans + save_volume_mesh) -> initial_wafer_state_from_recipe ->
  advance_wafer_state(state, mesh ProcessResult, None)  [GUI _sync_wafer_state_geometry] ->
  build_process_result + apply_step_junction_doping + derive_barrier_covered_windows ->
  advance_wafer_state(state, doped, "doping", barrier_windows, "x") -> import_process_result -> apply_doping (CONTROL).
Instrumentation only observes: devsim.solve / doping-model write counts, and every WaferStateV2.net_doping_at return value.
usage: prod_build_e1.py <work dir>   -> <work>/prod.json, <work>/prod_arrays.npz, <work>/wafer mesh files"""
import json
import os
import sys
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-d-sg-pn-mesh-validity", "scripts"))
import common_e1 as ce  # noqa: E402

UM = 1e-4
WRITE_NAMES = {"Donors", "Acceptors", "NetDoping"}


def build(work, out):
    import devsim
    from tcad.backends.viennaps import session as vs
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe, advance_wafer_state
    from tcad.device.devsim.mesh_import import import_process_result, derive_barrier_covered_windows
    g = ce.GUI
    domain = vs.make_mask_spans(grid_delta_um=g["grid_delta_um"], x_extent_um=g["x_extent_um"], y_extent_um=g["y_extent_um"],
                                spans_um=[tuple(s) for s in g["mask_spans_um"]], mask_height_um=max(g["pr_thickness_um"], 0.1),
                                substrate_depth_um=g["silicon_depth_um"] + 1.0)
    mesh_path = save_volume_mesh(domain, os.path.join(work, "wafer"), floor_depth_um=g["silicon_depth_um"])
    out["mesh_file"] = {"name": os.path.basename(mesh_path), "sha256": ce.sha_file(mesh_path)}
    state = initial_wafer_state_from_recipe({"x_extent_um": g["x_extent_um"], "silicon_depth_um": g["silicon_depth_um"],
                                             "grid_delta_um": g["grid_delta_um"]})
    sync_pr = build_process_result({"final_mesh": mesh_path, "snapshots": [], "state_transition": None})
    state = advance_wafer_state(state, sync_pr, None)
    process_result = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    d = g["doping"]
    doped = apply_step_junction_doping(process_result, region=d["region"], junction_axis=d["junction_axis"],
                                       junction_position_um=d["junction_position_um"], donor_conc_cm3=d["donor_conc_cm3"],
                                       acceptor_conc_cm3=d["acceptor_conc_cm3"], chemical_state=d["chemical_state"])
    try:
        b = g["barrier"]
        barrier = derive_barrier_covered_windows(doped, doped_region=d["region"], barrier_material=b["barrier_material"],
                                                 axis=b["axis"], min_barrier_thickness_um=b["min_barrier_thickness_um"])
        out["barrier_windows"] = {"status": "OK", "value": barrier}
    except Exception as e:  # noqa: BLE001 - the GUI catches this and uses None
        barrier = None
        out["barrier_windows"] = {"status": "EXCEPTION_GUI_USES_NONE", "error": repr(e)[:200]}
    state = advance_wafer_state(state, doped, "doping", barrier_windows=barrier, barrier_axis="x")
    out["state"] = {"n_attachments": len(state.attachments),
                    "attachments": [{"model": a.model, "chemical_state": a.chemical_state, "polarity": a.polarity}
                                    for a in state.attachments],
                    "events_status": [getattr(e, "model_status", None) for e in state.events],
                    "active_cells": [{"material": c.material, "lifecycle": c.lifecycle, "bounds_um": c.bounds_um}
                                     for c in state.active_cells()]}
    i = g["import"]
    imported = import_process_result(doped, mesh_name=i["mesh_name"], device_name=i["device_name"],
                                     contact_regions=i["contact_regions"], contact_axis=i["contact_axis"],
                                     length_scale_to_cm=i["length_scale_to_cm"], refine_near_um=i["refine_near_um"],
                                     refine_axis=i["refine_axis"])
    return devsim, imported, state, doped


def device_facts(dv, imported, out, arrays):
    dev = imported.device
    out["dimension"] = int(dv.get_dimension(device=dev))
    out["regions"] = list(dv.get_region_list(device=dev))
    out["contacts"] = list(imported.contacts)
    reg = {}
    for r in out["regions"]:
        x = np.array(dv.get_node_model_values(device=dev, region=r, name="x"))
        y = np.array(dv.get_node_model_values(device=dev, region=r, name="y"))
        el = np.array(dv.get_element_node_list(device=dev, region=r), dtype=np.int64)
        nv = np.array(dv.get_node_model_values(device=dev, region=r, name="NodeVolume"))
        reg[r] = {"material": dv.get_material(device=dev, region=r), "n_nodes": int(len(x)), "n_elements": int(len(el)),
                  "x_range_um": [float(x.min() / UM), float(x.max() / UM)], "y_range_um": [float(y.min() / UM), float(y.max() / UM)],
                  "x_sha256": ce.sha(x.tobytes()), "y_sha256": ce.sha(y.tobytes()), "elements_sha256": ce.sha(el.tobytes()),
                  "sum_NodeVolume_cm2": float(nv.sum())}
        if r == "Si":
            arrays.update({"x": x, "y": y, "elements": el, "NodeVolume": nv})
    out["region_facts"] = reg
    out["contact_facts"] = {c: {"region": list(dv.get_region_list(device=dev, contact=c))} for c in imported.contacts}


def control(dv, imported, state, out):
    from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
    from tcad.physics.wafer_state_v2 import WaferStateV2
    counts = {"solve": 0, "doping_writes": 0, "writes": []}
    rec = []
    orig = {n: getattr(dv, n) for n in ("solve", "node_model", "set_node_values", "edge_model")}
    orig_q = WaferStateV2.net_doping_at

    def w_solve(*a, **k):
        counts["solve"] += 1
        return orig["solve"](*a, **k)

    def mk(name):
        def w(*a, **k):
            if k.get("name") in WRITE_NAMES:
                counts["doping_writes"] += 1
                counts["writes"].append(f"{name}:{k.get('name')}")
            return orig[name](*a, **k)
        return w

    def q(self, x_um, y_um, *a, **k):
        r = orig_q(self, x_um, y_um, *a, **k)
        rec.append((float(x_um), float(y_um), r.donor_concentration, r.acceptor_concentration, r.net_doping,
                    r.physics_status is None))
        return r
    dv.solve = w_solve
    for n in ("node_model", "set_node_values", "edge_model"):
        setattr(dv, n, mk(n))
    WaferStateV2.net_doping_at = q
    import devsim as _dvmod
    patched_module = [n for n in ("solve", "node_model", "set_node_values", "edge_model") if getattr(_dvmod, n) is not orig[n]]
    try:
        apply_doping(imported.device, "Si", state, length_scale_to_cm=ce.GUI["import"]["length_scale_to_cm"])
        out["control"] = {"raised": False}
    except UnsupportedDopingState as e:
        st = e.physics_status
        out["control"] = {"raised": True, "reason_code": st.get("reason_code"), "resolution": st.get("resolution"),
                          "total_nodes": st.get("total_nodes"), "blocked_nodes": st.get("blocked_nodes"),
                          "first_line": str(e).splitlines()[0][:300]}
    except Exception as e:  # noqa: BLE001
        out["control"] = {"raised": True, "other_exception": repr(e)[:300]}
    finally:
        for n, f in orig.items():
            setattr(dv, n, f)
        WaferStateV2.net_doping_at = orig_q
    netdoping_absent = True
    for m in WRITE_NAMES:
        try:
            dv.get_node_model_values(device=imported.device, region="Si", name=m)
            netdoping_absent = False
        except dv.error:
            pass
    out["control"].update({"solve_calls": counts["solve"], "doping_writes": counts["doping_writes"], "writes": counts["writes"],
                           "doping_models_absent_after": netdoping_absent, "instrumented_names": patched_module,
                           "net_doping_at_calls": len(rec)})
    c = out["control"]
    c["verdict"] = "GATE_HELD" if (c.get("reason_code") == ce.REASON and c["solve_calls"] == 0 and c["doping_writes"] == 0
                                   and netdoping_absent) else "GATE_NOT_HELD"
    return rec


def prechecks(dv, imported, state, rec, out, arrays):
    import build_fixtures_7hd as bf7  # 7H-D quality(), read-only
    x, y, el, nv = arrays["x"], arrays["y"], arrays["elements"], arrays["NodeVolume"]
    n = len(x)
    qx = np.array([r[0] for r in rec]) if rec else np.array([])
    out["capture"] = {"n_records": len(rec), "n_nodes": n}
    ok_capture = len(rec) == n and np.allclose(qx, x / UM, rtol=0, atol=1e-9)
    snapped = int(np.sum(np.abs(qx - x / UM) > 0)) if len(rec) == n else None
    out["capture"].update({"one_record_per_node_in_order": bool(ok_capture), "records_with_query_x_ne_node_x": snapped,
                           "all_known": bool(all(r[5] for r in rec))})
    if ok_capture:
        donors = np.array([r[2] for r in rec], dtype=float)
        acceptors = np.array([r[3] for r in rec], dtype=float)
        nets = np.array([r[4] for r in rec], dtype=float)
        arrays.update({"Donors": donors, "Acceptors": acceptors, "NetDoping": nets,
                       "query_x_um": qx, "query_y_um": np.array([r[1] for r in rec])})
        out["capture"]["doping_sha256"] = {k: ce.sha(arrays[k].tobytes()) for k in ("Donors", "Acceptors", "NetDoping")}
        direct = np.array([[q.donor_concentration, q.acceptor_concentration, q.net_doping]
                           for q in (state.net_doping_at(float(xx / UM), float(yy / UM)) for xx, yy in zip(x, y))], dtype=float)
        out["capture"]["direct_query_mismatch_nodes"] = int(np.sum(np.any(direct != np.column_stack([donors, acceptors, nets]), axis=1)))
        on0 = x == 0.0
        area = float(nv.sum())
        Lm, Rm = x < 0, x > 0
        d = ce.GUI["doping"]
        out["doping_prechecks"] = {
            "nodes_x_eq_0": int(on0.sum()), "netdoping_at_x0_values": sorted(set(float(v) for v in nets[on0])),
            "donors_at_x0": sorted(set(float(v) for v in donors[on0])), "acceptors_at_x0": sorted(set(float(v) for v in acceptors[on0])),
            "representation": "J0 (node on the junction, NetDoping = ND - NA there)" if on0.any() else "no node on the junction",
            "sum_NodeVolume_x0_cm2": float(nv[on0].sum()),
            "inventory_donor_cm-1": float((donors * nv).sum()), "inventory_acceptor_cm-1": float((acceptors * nv).sum()),
            "exact_donor_cm-1": d["donor_conc_cm3"] * float(nv[Rm].sum() + 0.5 * nv[on0].sum()),
            "exact_acceptor_cm-1": d["acceptor_conc_cm3"] * float(nv[Lm].sum() + 0.5 * nv[on0].sum()),
            "exact_basis": "N x (NodeVolume of the side + half the x=0 CV); the exact geometric area split of the x=0 CVs is also given",
            "region_area_from_NodeVolume_cm2": area,
            "donor_nodes": int((nets > 0).sum()), "acceptor_nodes": int((nets < 0).sum()), "zero_net_nodes": int((nets == 0).sum())}
    P = np.column_stack([x / UM, y / UM])
    tris = [[int(a), int(b), int(c)] for a, b, c in el]
    out["mesh_quality"] = bf7.quality(P, tris)
    out["mesh_quality"]["devsim_sum_NodeVolume_over_exact_area"] = float(nv.sum() / (sum(bf7.sl.fm.tri_area(P[t] * UM) for t in tris)))
    out["contact_x_um"] = {"x_min_nodes": int(np.sum(x == x.min())), "x_max_nodes": int(np.sum(x == x.max())),
                           "x_min_um": float(x.min() / UM), "x_max_um": float(x.max() / UM)}
    xs = np.unique(np.round(x / UM, 9))
    dx = np.diff(xs)
    out["mesh_spacing"] = {"distinct_x": int(len(xs)), "min_dx_um": float(dx.min()), "max_dx_um": float(dx.max()),
                           "min_dx_within_0.1um_of_junction": float(dx[np.abs(xs[:-1]) < 0.1].min()) if np.any(np.abs(xs[:-1]) < 0.1) else None}


def main():
    work = os.path.abspath(sys.argv[1])
    os.makedirs(work, exist_ok=True)
    out, arrays = {"gui_defaults": ce.GUI}, {}
    try:
        dv, imported, state, doped = build(work, out)
        device_facts(dv, imported, out, arrays)
        rec = control(dv, imported, state, out)
        prechecks(dv, imported, state, rec, out, arrays)
        dv.delete_device(device=imported.device)
        dv.delete_mesh(mesh=imported.mesh)
        out["devices_left"] = list(dv.get_device_list())
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)[:500]
        out["traceback"] = traceback.format_exc()[-2000:]
    np.savez_compressed(os.path.join(work, "prod_arrays.npz"), **arrays)
    out["arrays_npz_sha256"] = ce.sha_file(os.path.join(work, "prod_arrays.npz"))
    out["arrays"] = sorted(arrays)
    ce.dump_strict(out, os.path.join(work, "prod.json"))
    print(f"[prod_build_e1] control={out.get('control', {}).get('verdict')} error={'error' in out}", flush=True)


if __name__ == "__main__":
    main()
