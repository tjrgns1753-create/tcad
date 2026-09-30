"""Batch 7H-E6G remote real-backend checks (GitHub-hosted runner). usage: real_e6g.py <out dir> B|F
B: headless GUI, the E6E-R1 B recipe (width 4, depth 1, grid 0.2, implant windows 1e16 ACTIVE), refinement through the GUI's own
   _refine_for_implant_windows (production caller), then import_process_result with the GUI's measurement arguments (area gate).
F: the E6A GUI-default wafer (sha-gated) with the GUI-default 1e20 windows through refine_process_result_for_implant_windows, then
   import (area gate).
devsim.solve and node / edge / equation writes are counted and must stay 0 (import and gate only). Reports per-region A, S, S/A - 1,
B/A, triangle / node counts, exact obtuse count, and the band resolution check."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import eval_e6g as ev6g  # noqa: E402  (resolution check, exact obtuse / area on large meshes)

WAFER = os.path.join(ROOT, "docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/wafer_volume.vtu")
B_RAW_COMMITTED = os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu")
WRITES = ("solve", "node_model", "edge_model", "set_node_values", "set_node_value", "equation", "contact_equation", "node_solution")


def main():
    outd, which = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(outd, exist_ok=True)
    import meshio
    import devsim as dv
    calls = {k: 0 for k in WRITES}
    for k in WRITES:
        real = getattr(dv, k)

        def wrapped(*a, _k=k, _r=real, **kw):
            calls[_k] += 1
            return _r(*a, **kw)
        setattr(dv, k, wrapped)
    res = {"which": which, "status": None}
    try:
        from tcad.device.devsim.mesh_import import import_process_result, implant_windows_lateral_request
        from tcad.physics.doping import apply_implant_windows_doping
        from tcad.mesh.viennaps_adapter import build_process_result
        tmp = tempfile.mkdtemp(prefix=f"e6g_{which}_")
        if which == "B":
            import tkinter  # noqa: F401
            import tcad_2d_stagewise as gui
            app = gui.TCADApplication()
            app.withdraw()
            try:
                app.wafer.width_um, app.wafer.silicon_depth_um = 4.0, 1.0
                app.grid_var.set(0.2)
                assert app._materialize_current_wafer(), "materializing the real ViennaPS wafer failed"
                raw = os.path.join(tmp, "B_raw.vtu")
                shutil.copy(app.last_final_mesh, raw)
                pr = build_process_result({"final_mesh": raw, "snapshots": []})
                spans = [(float(app.dope_win_src_min_var.get()), float(app.dope_win_src_max_var.get())),
                         (float(app.dope_win_drn_min_var.get()), float(app.dope_win_drn_max_var.get()))]
                doped = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=1e16, acceptor_background_cm3=0.0,
                                                     windows=[{"min_um": a, "max_um": b, "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0}
                                                              for a, b in spans], chemical_state="ACTIVE")
                t = time.time()
                refined = app._refine_for_implant_windows(doped)
                res["refine_wall_s"] = round(time.time() - t, 3)
                assert refined is not None, "the GUI refinement returned None"
            finally:
                app.destroy()
            ca, cb = meshio.read(raw), meshio.read(B_RAW_COMMITTED)
            res["raw_equals_E6E_R1_B_raw"] = bool(np.array_equal(ca.points, cb.points) and np.array_equal(ca.cells[0].data, cb.cells[0].data))
            kw = {"contact_regions": ["Si"], "contact_axis": "x", "length_scale_to_cm": 1.0e-4}
        else:
            res["wafer_sha256"] = hashlib.sha256(open(WAFER, "rb").read()).hexdigest()
            raw = WAFER
            pr = build_process_result({"final_mesh": raw, "snapshots": []})
            doped = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=0.0, acceptor_background_cm3=1e17,
                                                 windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1e20, "acceptor_conc_cm3": 0.0},
                                                          {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": 1e20, "acceptor_conc_cm3": 0.0}],
                                                 chemical_state="ACTIVE")
            from tcad.device.devsim.mesh_import import refine_process_result_for_implant_windows
            t = time.time()
            refined = refine_process_result_for_implant_windows(doped, refined_mesh_path=os.path.join(tmp, "F_refined.vtu"))
            res["refine_wall_s"] = round(time.time() - t, 3)
            kw = {"contact_regions": ["Si"], "contact_axis": "x", "length_scale_to_cm": 1.0e-4}
        m0, m1 = meshio.read(raw), meshio.read(refined.volume_mesh_path)
        P0, T0 = m0.points, m0.cells[0].data
        P1, T1, G1 = m1.points, m1.cells[0].data, m1.cell_data["Material"][0]
        req = implant_windows_lateral_request(doped.doping, P0, T0)
        res["request"] = req
        res["raw"] = {"triangles": int(len(T0)), "points": int(len(P0))}
        res["refined"] = {"triangles": int(len(T1)), "points": int(len(P1)), "dtype": str(P1.dtype), "cell_blocks": [c.type for c in m1.cells]}
        t = time.time()
        res["exact"] = ev6g.exact_obtuse_area_only(P1, T1, G1, P0, T0, m0.cell_data["Material"][0])
        res["resolution"] = ev6g.resolution(P1, T1, P0, req["centers"], req["rings"])
        res["exact_s"] = round(time.time() - t, 2)
        refined_copy = os.path.join(outd, f"{which}_refined.vtu")
        shutil.copy(refined.volume_mesh_path, refined_copy)
        res["refined_vtu_sha256"] = hashlib.sha256(open(refined_copy, "rb").read()).hexdigest()
        before = dict(calls)
        t = time.time()
        d = import_process_result(refined, mesh_name=f"e6g_{which}_mesh", device_name=f"e6g_{which}_device", **kw)
        res["import_wall_s"] = round(time.time() - t, 2)
        res["import"] = {"regions": d.regions, "contacts": d.contacts, "area_conservation": d.area_conservation}
        res["writes_during_import"] = {k: calls[k] - before[k] for k in WRITES}
        dv.delete_device(device=d.device)
        dv.delete_mesh(mesh=d.mesh)
        res["status"] = "OK"
    except Exception as e:  # noqa: BLE001
        res["status"] = "ERROR"
        res["error"] = repr(e)[:800]
        res["traceback"] = traceback.format_exc()[-4000:]
    res["writes_total"] = calls
    res["devices_left"] = list(dv.get_device_list())
    with open(os.path.join(outd, f"real_{which}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, default=str)
    print(json.dumps({k: res.get(k) for k in ("which", "status", "error", "refined", "exact", "resolution", "import", "writes_during_import")},
                     default=str)[:3000], flush=True)
    return 0 if res["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
