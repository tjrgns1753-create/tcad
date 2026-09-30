#!/usr/bin/env python3
"""Real DEVSIM check of the fail-closed per-region area-conservation gate
in import_process_result() (Batch 7H-E6E; contract and expectations:
docs/audits/2026-09-30-batch7h-e6e-area-conservation-gate/PLAN.md section 4).

* E6D G0 / G1 (raw, sha-gated): imported, every region passes.
* E6D G2: refused (MESH_AREA_NOT_CONSERVED, region Si) before the importer
  returns; 0 solves, 0 doping writes, device and mesh deleted, the same
  mesh / device names reusable at once.
* two-material and large-coordinate structured controls: imported.
* GUI run_measurement() / resolve_electrode_pins() and CLI run_pipeline()
  on G2: refusal recorded, no doping write, no solve, no number.
Counting wrappers (pass-through) sit on devsim.solve and the node-model
write calls for the whole run."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

AUD = ROOT / "docs" / "audits"
MESHES = {
    "G0": (AUD / "2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/level_L5.vtu",
           "907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70"),
    "G1": (AUD / "2026-09-29-batch7h-e6d-noncore-refinement/data/remote_run_36538742843/outputs/e6d_out/mesh_G1.vtu",
           "48bcf8ea231c5c59a09a2c7089bd6e61af8688c57b73c723d6753305753f4f02"),
    "G2": (AUD / "2026-09-29-batch7h-e6d-noncore-refinement/data/remote_run_36538742843/outputs/e6d_out/mesh_G2.vtu",
           "d9229e8378eb3348523875825dbaf5e9479c968d444c3888dc157a78586c7dae"),
}
WRITE_CALLS = ("solve", "node_model", "set_node_values", "set_node_value")
CALLS = {k: 0 for k in WRITE_CALLS}
RESULTS, FAILURES = {}, []


def check(name, ok, detail):
    RESULTS[name] = {"pass": bool(ok), "detail": detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(detail, default=str)[:1500]}", flush=True)
    if not ok:
        FAILURES.append(name)


def install_counters(dv):
    for k in WRITE_CALLS:
        real = getattr(dv, k)

        def wrapped(*a, _k=k, _real=real, **kw):
            CALLS[_k] += 1
            return _real(*a, **kw)
        setattr(dv, k, wrapped)


def snapshot_calls():
    return dict(CALLS)


def delta(before):
    return {k: CALLS[k] - before[k] for k in WRITE_CALLS}


def structured_vtu(path, tags_fn, x0=-1.0, y0=-1.0, nx=20, ny=10, h=0.1):
    import meshio
    pts = np.array([[x0 + i * h, y0 + j * h, 0.0] for j in range(ny + 1) for i in range(nx + 1)], dtype=np.float64)
    tris, tags = [], []
    for j in range(ny):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
            tags += [tags_fn(i, nx)] * 2
    meshio.write(str(path), meshio.Mesh(pts, [("triangle", np.array(tris))], cell_data={"Material": [np.array(tags, dtype=np.int32)]}))


def main():
    from tcad.device.devsim import backend
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.mesh_conservation import MeshAreaConservationError
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.backends.viennaps import session

    dv = backend.require_devsim()
    install_counters(dv)
    for n, (p, want) in MESHES.items():
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        check(f"input_sha_{n}", got == want, {"sha256": got})
    if FAILURES:
        raise SystemExit(f"FAILED: {FAILURES}")

    def imp(path, mesh="gate_mesh", device="gate_device", **kw):
        pr = build_process_result({"final_mesh": str(path), "snapshots": []})
        return import_process_result(pr, mesh_name=mesh, device_name=device, contact_regions=["Si"], contact_axis="x",
                                     length_scale_to_cm=1e-4, **kw)

    def release(d):
        dv.delete_device(device=d.device)
        dv.delete_mesh(mesh=d.mesh)

    # ---- G0 / G1 controls
    for n in ("G0", "G1"):
        b = snapshot_calls()
        try:
            d = imp(MESHES[n][0])
            rep = d.area_conservation
            check(f"control_{n}_imported", all(r["pass"] for r in rep.values()) and delta(b) == {k: 0 for k in WRITE_CALLS},
                  {"report": rep, "calls": delta(b)})
            release(d)
        except Exception as exc:  # noqa: BLE001
            check(f"control_{n}_imported", False, {"exception": repr(exc)[:800]})

    # ---- G2 refusal, cleanup, same-name retry
    b = snapshot_calls()
    try:
        d = imp(MESHES["G2"][0])
        check("G2_refused", False, {"returned_device": d.device, "report": d.area_conservation})
        release(d)
    except MeshAreaConservationError as exc:
        st = exc.physics_status
        si = st.get("regions", {}).get("Si", {})
        check("G2_refused", st.get("reason_code") == "MESH_AREA_NOT_CONSERVED" and st.get("first_failing_region") == "Si"
              and st.get("resolution") == "UNSUPPORTED_BY_MODEL" and st.get("cleanup") == {"delete_device": "ok", "delete_mesh": "ok"}
              and delta(b) == {k: 0 for k in WRITE_CALLS} and list(dv.get_device_list()) == [],
              {"message": str(exc)[:600], "status": st, "calls": delta(b), "devices_left": list(dv.get_device_list())})
        try:
            d = imp(MESHES["G1"][0])
            check("same_name_retry_after_refusal", all(r["pass"] for r in d.area_conservation.values()), {"device": d.device})
            release(d)
        except Exception as e2:  # noqa: BLE001
            check("same_name_retry_after_refusal", False, {"exception": repr(e2)[:800]})
    except Exception as exc:  # noqa: BLE001
        check("G2_refused", False, {"unexpected_exception": repr(exc)[:800]})

    # ---- two-material and large-coordinate controls
    vps = session.require_viennaps()
    si_tag, ox_tag = int(vps.Material.Si), int(vps.Material.SiO2)
    tmp = Path(tempfile.mkdtemp(prefix="e6e_gate_"))
    two = tmp / "two_material.vtu"
    structured_vtu(two, lambda i, nx: si_tag if i < nx // 2 else ox_tag)
    big = tmp / "large_coordinates.vtu"
    structured_vtu(big, lambda i, nx: si_tag, x0=1.0e4, y0=1.0e4)
    for name, path, kw in (("control_two_material", two, {"interface_region_pairs": [("Si", "SiO2")]}), ("control_large_coordinates", big, {})):
        try:
            d = imp(path, **kw)
            rep = d.area_conservation
            want_regions = {"Si", "SiO2"} if name == "control_two_material" else {"Si"}
            check(name, set(rep) == want_regions and all(r["pass"] for r in rep.values()), {"report": rep, "regions": d.regions})
            release(d)
        except Exception as exc:  # noqa: BLE001
            check(name, False, {"exception": repr(exc)[:800]})

    # ---- GUI paths
    gui_paths(dv, MeshAreaConservationError)
    # ---- CLI path
    cli_path(MeshAreaConservationError)

    check("no_devices_left_at_end", list(dv.get_device_list()) == [], {"devices": list(dv.get_device_list())})
    print("SUMMARY", json.dumps({"results": {k: v["pass"] for k, v in RESULTS.items()}, "calls_total": CALLS}), flush=True)
    if FAILURES:
        raise SystemExit(f"FAILED: {FAILURES}")
    print("ALL MESH AREA CONSERVATION GATE REAL CHECKS PASSED")


def gui_paths(dv, MeshAreaConservationError):
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.physics.doping import apply_uniform_doping
        import tcad.device.devsim.mesh_import as mi
        app = gui.TCADApplication()
    except Exception as exc:  # noqa: BLE001
        check("gui_available", False, {"exception": repr(exc)[:500]})
        return
    app.withdraw()
    infos, errors, logs, imported = [], [], [], []
    app._notify_info = lambda title, msg: infos.append((title, msg))
    app._notify_error = lambda title, msg: errors.append((title, msg))
    real_log = app._log
    app._log = lambda msg: (logs.append(msg), real_log(msg))
    real_import = mi.import_process_result
    stop_after_import = {"measure": False}

    class StopAfterImport(RuntimeError):
        pass

    def counted_import(*a, **kw):
        d = real_import(*a, **kw)
        imported.append(d.device)
        if stop_after_import["measure"]:
            # G1 control: the importer accepted the mesh inside the GUI path; stop here (no doping write, no solve on 0.5M nodes)
            dv.delete_device(device=d.device)
            dv.delete_mesh(mesh=d.mesh)
            raise StopAfterImport("control stop after a successful import")
        return d
    mi.import_process_result = counted_import
    try:
        for n in ("G2", "G1"):
            path = str(MESHES[n][0])
            infos.clear(), errors.clear(), logs.clear(), imported.clear()
            app.last_final_mesh = path
            app.last_doped_result = apply_uniform_doping(build_process_result({"final_mesh": path, "snapshots": []}),
                                                         {"Si": 1.0e16}, chemical_state="ACTIVE")
            app.last_physics_status = None
            stop_after_import["measure"] = n == "G1"
            b = snapshot_calls()
            app.run_measurement()
            stop_after_import["measure"] = False
            st = app.last_physics_status or {}
            number_shown = any("I =" in m for _, m in infos) or any("DEVSIM MEASUREMENT" in m for m in logs)
            if n == "G2":
                check("gui_measure_G2_refused", st.get("reason_code") == "MESH_AREA_NOT_CONSERVED" and not imported
                      and delta(b) == {k: 0 for k in WRITE_CALLS} and not number_shown and list(dv.get_device_list()) == []
                      and any("no current is reported" in m for _, m in errors),
                      {"status_reason": st.get("reason_code"), "calls": delta(b), "number_shown": number_shown, "errors": errors[-1:]})
            else:
                check("gui_measure_G1_reaches_importer", imported == ["gui_measure_device"] and st.get("reason_code") != "MESH_AREA_NOT_CONSERVED"
                      and any("control stop after a successful import" in m for _, m in errors) and list(dv.get_device_list()) == [],
                      {"imported": imported, "status_reason": st.get("reason_code"), "calls": delta(b), "number_shown": number_shown,
                       "errors": [m[:300] for _, m in errors]})
        for n in ("G2", "G1"):
            app._cleanup_electrode_device()
            app.electrode_pins = []
            app.last_final_mesh = str(MESHES[n][0])
            app.add_electrode_pin("P1", "Source", 5.0, 0.0)
            app.last_physics_status = None
            imported.clear(), errors.clear()
            b = snapshot_calls()
            out = app.resolve_electrode_pins()
            st = app.last_physics_status or {}
            if n == "G2":
                check("gui_pins_G2_refused", out is None and app.last_electrode_import is None and st.get("reason_code") == "MESH_AREA_NOT_CONSERVED"
                      and delta(b) == {k: 0 for k in WRITE_CALLS} and list(dv.get_device_list()) == [],
                      {"status_reason": st.get("reason_code"), "calls": delta(b), "errors": [m[:300] for _, m in errors]})
                r = app.run_dc_operating_point(1.0, 1.0)
                check("gui_dc_op_after_G2_refusal_solves_nothing", r is None and delta(b) == {k: 0 for k in WRITE_CALLS}, {"return": r})
            else:
                check("gui_pins_G1_reaches_importer", out is not None and imported == ["gui_electrode_device"],
                      {"imported": imported, "errors": [m[:300] for _, m in errors]})
                app._cleanup_electrode_device()
    finally:
        mi.import_process_result = real_import
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


def cli_path(MeshAreaConservationError):
    import tcad.cli.run_pipeline as rp
    doping_calls = []
    real_proc, real_dop = rp._run_process_step, rp._apply_device_doping
    rp._run_process_step = lambda cfg, workdir: {"final_mesh": str(MESHES["G2"][0]), "snapshots": []}
    rp._apply_device_doping = lambda *a, **kw: doping_calls.append(1)
    work = Path(tempfile.mkdtemp(prefix="e6e_cli_"))
    cfg = {"process": {"category": "unused"}, "doping": {"kind": "uniform", "doping_by_region_cm3": {"Si": 1.0e16}, "chemical_state": "ACTIVE"},
           "device": {"length_scale_to_cm": 1e-4, "contact_regions": ["Si"], "mesh_name": "cli_mesh", "device_name": "cli_device"},
           "characterization": {"kind": "pn_junction_iv", "region": "Si"}, "outputs": {"csv": "iv.csv"}}
    b = snapshot_calls()
    try:
        rp.run_pipeline(cfg, work)
        check("cli_G2_refused", False, {"returned": True})
    except MeshAreaConservationError as exc:
        check("cli_G2_refused", exc.physics_status.get("reason_code") == "MESH_AREA_NOT_CONSERVED" and not doping_calls
              and delta(b) == {k: 0 for k in WRITE_CALLS} and not any(work.iterdir()),
              {"calls": delta(b), "doping_calls": len(doping_calls), "files": [p.name for p in work.iterdir()]})
    except Exception as exc:  # noqa: BLE001
        check("cli_G2_refused", False, {"unexpected_exception": repr(exc)[:800]})
    finally:
        rp._run_process_step, rp._apply_device_doping = real_proc, real_dop


if __name__ == "__main__":
    main()
