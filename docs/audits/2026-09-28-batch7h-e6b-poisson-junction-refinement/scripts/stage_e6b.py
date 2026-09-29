"""Batch 7H-E6B remote worker, ONE device per process (PLAN Rev.3 sections 5-8). DEVSIM import and solve happen only here,
only on a GitHub-hosted runner. Poisson-only, 300 K, both contact biases 0 V, no precision flag set, J0 doping written
explicitly (never through apply_doping).
usage: stage_e6b.py level <out dir> <L>      L in 3, 4, 5 : 2D level, calls L<L>-P then (if P converged) L<L>-C
       stage_e6b.py ref <out dir> <m>        m in 6, 7    : 1D reference, calls R<m>-P then (if P converged) R<m>-C"""
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
AUD = os.path.join(ROOT, "docs", "audits")
E6A_OUT = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402  (E1, read-only: strict JSON, sha256, USER_PATH sanitizer)
import judge_e6b as jd  # noqa: E402

UM = 1e-4
N_CONC = 1.0e18
PRIMARY = dict(absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)      # PLAN 6.4 (E5 / production values)
CONTROL = dict(absolute_error=1e-12, relative_error=1e-12, maximum_iterations=10)    # PLAN 6.4 solver-sensitivity control
T0 = time.time()


def log(msg):
    print(f"[e6b {time.time() - T0:8.1f}s] {msg}", flush=True)


def clean(text):
    return ce.USER_PATH.sub("<USERPROFILE>", str(text))


def memory():
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return {"status": "GetProcessMemoryInfo_FAILED"}
        return {"peak_working_set_bytes": int(pmc.PeakWorkingSetSize), "peak_private_bytes": int(pmc.PeakPagefileUsage)}
    except Exception as e:  # noqa: BLE001
        return {"status": "MEMORY_READ_UNAVAILABLE", "error": clean(repr(e))[:200]}


def flags(dv):
    out = {}
    for n in ("extended_model", "extended_equation", "extended_solver"):
        try:
            out[n] = dv.get_parameter(name=n)
        except Exception as e:  # noqa: BLE001
            out[n] = "UNSET: " + clean(e).strip()[:50]
    return out


class Stop(Exception):
    """Fail-closed early exit; the status is already in `res`, cleanup and the result file still run."""


class Solver:
    """Counts EVERY devsim.solve call (a hidden call would break the registered list) and records each raw result."""

    def __init__(self, dv):
        self.dv, self.calls, self.count = dv, [], 0
        self._orig = dv.solve

        def counted(*a, **k):
            self.count += 1
            return self._orig(*a, **k)
        dv.solve = counted

    def restore(self):
        self.dv.solve = self._orig

    def call(self, call_id, **kw):
        t = time.time()
        rec = {"call_id": call_id, "k": kw}
        try:
            r = self.dv.solve(type="dc", info=True, **kw)
            rec.update({"ok": True, "error": None})
        except Exception as e:  # noqa: BLE001
            r = None
            rec.update({"ok": False, "error": clean(repr(e))[:300]})
        rec["wall_s"] = round(time.time() - t, 3)
        if r:
            its = r["iterations"]
            last = its[-1]["devices"][0] if its else None
            rec.update({"converged": bool(r["converged"]), "n_iterations": len(its),
                        "final_device_relative_error": last["relative_error"] if last else None,
                        "final_device_absolute_error": last["absolute_error"] if last else None,
                        "final_equations": {e["name"]: {"abs": e["absolute_error"], "rel": e["relative_error"]}
                                            for reg in last["regions"] for e in reg["equations"]} if last else {},
                        "iteration_device_relative_errors": [i["devices"][0]["relative_error"] for i in its]})
        else:
            rec["converged"] = False
        self.calls.append(rec)
        return rec


def snapshot(dv, dev, call_id):
    """ONE query batch of every Potential-derived model, immediately after solve call `call_id` and before any other solve
    (PLAN 6.6). Returns (arrays, JSON record with per-array sha256)."""
    nv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    ev = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    arr = {"Potential": nv("Potential"), "IntrinsicElectrons": nv("IntrinsicElectrons"), "IntrinsicHoles": nv("IntrinsicHoles"),
           "IntrinsicCharge": nv("IntrinsicCharge"), "PotentialIntrinsicCharge": nv("PotentialIntrinsicCharge"),
           "ElectricField": ev("ElectricField"), "PotentialEdgeFlux": ev("PotentialEdgeFlux")}
    rec = {"call_id": call_id, "array_sha256": {k: jd.sha_arr(v) for k, v in arr.items()},
           "all_finite": bool(all(np.isfinite(v).all() for v in arr.values()))}
    arr["snapshot_call_id"] = np.array(call_id)
    return arr, rec


def write_j0(dv, dev, x_cm):
    """PLAN 1 row 12: J0 = both species at full strength ON x = 0 (donor x >= 0, acceptor x <= 0), net 0 there. An audit
    device; not evidence about production apply_doping on a 2D step junction."""
    donors = np.where(x_cm >= 0.0, N_CONC, 0.0)
    acceptors = np.where(x_cm <= 0.0, N_CONC, 0.0)
    nets = donors - acceptors
    for name, vals in (("Donors", donors), ("Acceptors", acceptors), ("NetDoping", nets)):
        dv.node_model(device=dev, region="Si", name=name, equation="0")
        dv.set_node_values(device=dev, region="Si", name=name, values=[float(v) for v in vals])
    return donors, acceptors, nets


def doping_record(x_cm, nv, donors, acceptors, nets, area_cm2):
    m0 = x_cm == 0.0
    return {"n_nodes": int(len(x_cm)), "n_x0_nodes": int(m0.sum()),
            "x0_Donors_unique": sorted({float(v) for v in donors[m0]}), "x0_Acceptors_unique": sorted({float(v) for v in acceptors[m0]}),
            "x0_NetDoping_unique": sorted({float(v) for v in nets[m0]}),
            "x0_ok": bool(m0.any() and set(donors[m0]) == {N_CONC} and set(acceptors[m0]) == {N_CONC} and set(nets[m0]) == {0.0}),
            "x0_sum_NodeVolume_cm2": float(nv[m0].sum()) if nv is not None else None,
            "x0_sum_Donors_x_NodeVolume": float((donors * nv)[m0].sum()) if nv is not None else None,
            "x0_sum_Acceptors_x_NodeVolume": float((acceptors * nv)[m0].sum()) if nv is not None else None,
            "x0_sum_NetDoping_x_NodeVolume": float((nets * nv)[m0].sum()) if nv is not None else None,
            "total_Donors_x_NodeVolume": float((donors * nv).sum()) if nv is not None else None,
            "total_Acceptors_x_NodeVolume": float((acceptors * nv).sum()) if nv is not None else None,
            "continuum_N_x_area": N_CONC * area_cm2 / 2 if area_cm2 else None,
            "note": "raw numbers of the discrete doping representation; not called a sheet charge"}


def finish(outd, name, res, sv, dv):
    if sv is not None:
        sv.restore()
    try:
        res["devices_left"] = list(dv.get_device_list())
    except Exception as e:  # noqa: BLE001
        res["devices_left"] = f"UNREADABLE: {clean(e)[:100]}"
    res["memory"] = memory()
    res["wall_s"] = round(time.time() - T0, 1)
    ce.dump_strict(res, os.path.join(outd, name))
    log(f"{name}: status={res.get('status')} solve_count={res.get('solve_count')} devices_left={res.get('devices_left')}")


def level(outd, L):
    import devsim as dv
    res = {"mode": "level", "L": L, "status": None, "solve_calls": [], "solve_count": 0}
    sv = None
    dev = mesh = None
    try:
        if list(dv.get_device_list()):
            res["status"] = "IMPORT_IDENTITY_FAIL"
            res["stop_detail"] = "device already registered at start"
            raise Stop
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
        ref = jd.load_npz(os.path.join(E6A_OUT, f"level_L{L}.npz"))
        vtu = os.path.join(E6A_OUT, f"level_L{L}.vtu")
        res["input_vtu_sha256"] = ce.sha_file(vtu)
        result = build_process_result({"final_mesh": vtu, "snapshots": []})
        imp = import_process_result(result, mesh_name=f"e6b_L{L}_mesh", device_name=f"e6b_L{L}_device",
                                    contact_regions=["Si"], contact_axis="x", length_scale_to_cm=UM)
        dev, mesh = imp.device, imp.mesh
        nv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
        x, y, vol = nv("x"), nv("y"), nv("NodeVolume")
        el = np.array(dv.get_element_node_list(device=dev, region="Si"), dtype=np.int64)
        # ---- import identity (PLAN 6.2), before this level's solve
        P32 = ref["points_um_f32"][:, :2]
        exp_xy = (P32 * UM).astype(float)          # the production scaling expression (mesh_import.py:989)
        a, b = np.sort(ref["triangles"], axis=1), np.sort(el, axis=1)
        ia, ib = np.lexsort((a[:, 2], a[:, 1], a[:, 0])), np.lexsort((b[:, 2], b[:, 1], b[:, 0]))
        contacts = {}
        for c in imp.contacts:
            nodes = sorted({int(v) for e in dv.get_element_node_list(device=dev, region="Si", contact=c) for v in e})
            contacts[c] = nodes
        want = {"Si_xmin": set(np.where(x == x.min())[0].tolist()), "Si_xmax": set(np.where(x == x.max())[0].tolist())}
        idn = {"n_nodes": [int(len(x)), int(len(P32))], "nodes_equal": bool(len(x) == len(P32)),
               "xy_equal_scaled_construction": bool(len(x) == len(P32) and np.array_equal(x, exp_xy[:, 0]) and np.array_equal(y, exp_xy[:, 1])),
               "n_elements": [int(len(el)), int(len(ref["triangles"]))],
               "vertex_set_multiset_equal": bool(len(a) == len(b) and np.array_equal(a[ia], b[ib])),
               "NodeVolume_bit_equal_E6A": bool(np.array_equal(vol, ref["NodeVolume"])),
               "regions": list(dv.get_region_list(device=dev)),
               "contacts": {c: len(n) for c, n in contacts.items()},
               "contacts_by_coordinate_ok": bool(sorted(contacts) == ["Si_xmax", "Si_xmin"]
                                                  and all(set(contacts[c]) == want[c] and len(contacts[c]) == 101 for c in want))}
        idn["ok"] = bool(idn["nodes_equal"] and idn["xy_equal_scaled_construction"] and idn["n_elements"][0] == idn["n_elements"][1]
                         and idn["vertex_set_multiset_equal"] and idn["NodeVolume_bit_equal_E6A"] and idn["regions"] == ["Si"]
                         and idn["contacts_by_coordinate_ok"])
        res["identity"] = idn
        if not idn["ok"]:
            res["status"] = "IMPORT_IDENTITY_FAIL"
            raise Stop
        # ---- device: J0 doping, Poisson equation
        donors, acceptors, nets = write_j0(dv, dev, x)
        res["doping"] = doping_record(x, vol, donors, acceptors, nets, float((x.max() - x.min()) * (y.max() - y.min())))
        if not res["doping"]["x0_ok"]:
            res["status"] = "IMPORT_IDENTITY_FAIL"
            res["stop_detail"] = "J0 doping check at x = 0 failed"
            raise Stop
        setup_semiconductor_potential_equation(dev, "Si", ["Si_xmin", "Si_xmax"], 300.0)
        res["flags"] = flags(dv)
        dv.edge_from_node_model(device=dev, region="Si", node_model="node_index")
        ge = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
        n0, n1 = ge("node_index@n0").astype(np.int64), ge("node_index@n1").astype(np.int64)
        EC, EL = ge("EdgeCouple"), ge("EdgeLength")
        res["edge_arrays_equal_E6A"] = {k: bool(np.array_equal(v, ref[k2])) for k, v, k2 in
                                        (("n0", n0, "edge_n0"), ("n1", n1, "edge_n1"), ("EdgeCouple", EC, "EdgeCouple"),
                                         ("EdgeLength", EL, "EdgeLength"))}
        static = {"x": x, "y": y, "elements": el.astype(np.int32), "NodeVolume": vol, "Donors": donors, "Acceptors": acceptors,
                  "NetDoping": nets, "edge_n0": n0.astype(np.int32), "edge_n1": n1.astype(np.int32), "EdgeCouple": EC, "EdgeLength": EL}
        np.savez_compressed(os.path.join(outd, f"level_L{L}_static.npz"), **static)
        res["static_sha256"] = {k: jd.sha_arr(v) for k, v in static.items()}
        # ---- solves: P, snapshot, then C (only if P converged), snapshot
        sv = Solver(dv)
        res["snapshots"] = {}
        p = sv.call(f"L{L}-P", **PRIMARY)
        arr, rec = snapshot(dv, dev, f"L{L}-P")
        np.savez_compressed(os.path.join(outd, f"level_L{L}_state_P.npz"), **arr)
        res["snapshots"]["P"] = rec
        log(f"L{L}-P converged={p.get('converged')} iterations={p.get('n_iterations')} rel={p.get('final_device_relative_error')}")
        if p.get("converged") is True:
            c = sv.call(f"L{L}-C", **CONTROL)
            arr, rec = snapshot(dv, dev, f"L{L}-C")
            np.savez_compressed(os.path.join(outd, f"level_L{L}_state_C.npz"), **arr)
            res["snapshots"]["C"] = rec
            log(f"L{L}-C converged={c.get('converged')} iterations={c.get('n_iterations')} rel={c.get('final_device_relative_error')}")
        res["solve_calls"], res["solve_count"] = sv.calls, sv.count
        res["status"] = "OK"
    except Stop:
        pass
    except Exception as e:  # noqa: BLE001
        res["status"] = res["status"] or "WORKER_ERROR"
        res["error"] = clean(repr(e))[:500]
        res["traceback"] = clean(traceback.format_exc()[-3000:])
        if sv is not None:
            res["solve_calls"], res["solve_count"] = sv.calls, sv.count
    finally:
        try:
            if dev is not None:
                dv.delete_device(device=dev)
            if mesh is not None:
                dv.delete_mesh(mesh=mesh)
        except Exception as e:  # noqa: BLE001
            res["cleanup_error"] = clean(repr(e))[:200]
    finish(outd, f"level_L{L}.json", res, sv, dv)
    return 0 if res["status"] in ("OK", "IMPORT_IDENTITY_FAIL") else 1


def ref(outd, m):
    """1D reference R<m>: the 233 distinct DEVSIM x values of the L3 node set (cm, float64), each interval split into 2^m
    equal parts, ns / ps set to the adjacent interval lengths (DEVSIM add_1d_mesh_line: ns / ps are the spacings in the
    negative / positive direction), so no node is inserted. Fail closed if the built nodes differ from the plan."""
    import devsim as dv
    res = {"mode": "ref", "m": m, "status": None, "solve_calls": [], "solve_count": 0}
    sv = None
    dev = mesh = None
    try:
        if list(dv.get_device_list()):
            res["status"] = "REFERENCE_1D_UNUSABLE"
            res["stop_detail"] = "device already registered at start"
            raise Stop
        from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
        e6a3 = jd.load_npz(os.path.join(E6A_OUT, "level_L3.npz"))
        ux = np.unique(e6a3["x"])                                  # 233 DEVSIM x values (cm)
        parts = 2 ** m
        pos = []
        for a, b in zip(ux[:-1], ux[1:]):
            pos.extend(float(a + (b - a) * k / parts) for k in range(parts))
        pos.append(float(ux[-1]))
        pos = np.array(pos, dtype=np.float64)
        res["plan"] = {"n_x_2d": int(len(ux)), "n_nodes_planned": int((len(ux) - 1) * parts + 1), "parts": parts}
        mesh, dev = f"e6b_R{m}_mesh", f"e6b_R{m}_device"
        dv.create_1d_mesh(mesh=mesh)
        gaps = np.diff(pos)
        for i, xv in enumerate(pos):
            ns = float(gaps[i - 1]) if i > 0 else float(gaps[0])
            ps = float(gaps[i]) if i < len(gaps) else float(gaps[-1])
            kw = {"mesh": mesh, "pos": xv, "ns": ns, "ps": ps}
            if i == 0:
                kw["tag"] = "left"
            elif i == len(pos) - 1:
                kw["tag"] = "right"
            dv.add_1d_mesh_line(**kw)
        dv.add_1d_contact(mesh=mesh, name="left", tag="left", material="metal")
        dv.add_1d_contact(mesh=mesh, name="right", tag="right", material="metal")
        dv.add_1d_region(mesh=mesh, material="Si", region="Si", tag1="left", tag2="right")
        dv.finalize_mesh(mesh=mesh)
        dv.create_device(mesh=mesh, device=dev)
        x = np.array(dv.get_node_model_values(device=dev, region="Si", name="x"), dtype=np.float64)
        vol = np.array(dv.get_node_model_values(device=dev, region="Si", name="NodeVolume"), dtype=np.float64)
        order = np.argsort(x)
        pos_ok = bool(len(x) == res["plan"]["n_nodes_planned"] and np.array_equal(x[order], pos))
        idn = {"n_nodes": int(len(x)), "positions_equal_planned_bitwise": pos_ok,
               "all_2d_x_present_bitwise": bool(np.isin(ux, x).all())}
        res["identity"] = idn
        if not (pos_ok and idn["all_2d_x_present_bitwise"]):
            res["status"] = "REFERENCE_1D_UNUSABLE"
            res["stop_detail"] = "1D nodes differ from the planned positions"
            raise Stop
        donors, acceptors, nets = write_j0(dv, dev, x)
        res["doping"] = doping_record(x, vol, donors, acceptors, nets, None)
        setup_semiconductor_potential_equation(dev, "Si", ["left", "right"], 300.0)
        res["flags"] = flags(dv)
        sv = Solver(dv)
        arrays = {"x": x, "Donors": donors, "Acceptors": acceptors, "NetDoping": nets, "NodeVolume": vol}
        res["snapshots"] = {}
        p = sv.call(f"R{m}-P", **PRIMARY)
        pot = np.array(dv.get_node_model_values(device=dev, region="Si", name="Potential"), dtype=np.float64)
        arrays["Potential_after_P"], arrays["snapshot_call_id_P"] = pot, np.array(f"R{m}-P")
        log(f"R{m}-P converged={p.get('converged')} iterations={p.get('n_iterations')} rel={p.get('final_device_relative_error')}")
        if p.get("converged") is True:
            c = sv.call(f"R{m}-C", **CONTROL)
            arrays["Potential_after_C"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Potential"), dtype=np.float64)
            arrays["snapshot_call_id_C"] = np.array(f"R{m}-C")
            log(f"R{m}-C converged={c.get('converged')} iterations={c.get('n_iterations')} rel={c.get('final_device_relative_error')}")
        else:
            arrays["Potential_after_C"], arrays["snapshot_call_id_C"] = np.full_like(pot, np.nan), np.array("NOT_RUN")
        # NaN placeholders are stored only in the npz (never in JSON); they exist so a missing control cannot be silently read
        np.savez_compressed(os.path.join(outd, f"ref_R{m}.npz"), **arrays)
        res["array_sha256"] = {k: jd.sha_arr(v) for k, v in arrays.items() if not k.startswith("snapshot_call_id")}
        res["solve_calls"], res["solve_count"] = sv.calls, sv.count
        res["status"] = "OK"
    except Stop:
        pass
    except Exception as e:  # noqa: BLE001
        res["status"] = res["status"] or "WORKER_ERROR"
        res["error"] = clean(repr(e))[:500]
        res["traceback"] = clean(traceback.format_exc()[-3000:])
        if sv is not None:
            res["solve_calls"], res["solve_count"] = sv.calls, sv.count
    finally:
        try:
            if dev is not None:
                dv.delete_device(device=dev)
            if mesh is not None:
                dv.delete_mesh(mesh=mesh)
        except Exception as e:  # noqa: BLE001
            res["cleanup_error"] = clean(repr(e))[:200]
    finish(outd, f"ref_R{m}.json", res, sv, dv)
    return 0 if res["status"] in ("OK", "REFERENCE_1D_UNUSABLE") else 1


def main():
    mode, outd = sys.argv[1], os.path.abspath(sys.argv[2])
    os.makedirs(outd, exist_ok=True)
    return level(outd, int(sys.argv[3])) if mode == "level" else ref(outd, int(sys.argv[3]))


if __name__ == "__main__":
    sys.exit(main())
