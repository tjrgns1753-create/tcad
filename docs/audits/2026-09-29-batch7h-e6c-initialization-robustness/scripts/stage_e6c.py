"""Batch 7H-E6C remote worker, ONE run (one level, one initial condition) per process; exactly one devsim.solve call. PLAN sections 2, 3, 6.
DEVSIM import and solve happen only here, only on a GitHub-hosted runner. Poisson-only, 300 K, both contact biases 0 V, no precision flag
set, J0 doping written explicitly (never through apply_doping).
usage: stage_e6c.py run <out dir> <L> <P|Q>      L in 3, 4, 5"""
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
import judge_e6c as jc  # noqa: E402
jb = jc.jb

UM = 1e-4
N_CONC = 1.0e18
SOLVE_ARGS = dict(absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)     # PLAN 2 (identical for P and Q)
T0 = time.time()


class Stop(Exception):
    """Fail-closed early exit; the status is already in `res`, cleanup and the result file still run."""


def log(msg):
    print(f"[e6c {time.time() - T0:8.1f}s] {msg}", flush=True)


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


def write_j0(dv, dev, x_cm):
    """J0 = both species at full strength ON x = 0 (donor x >= 0, acceptor x <= 0), net 0 there (as E6B). An audit device; not evidence
    about production apply_doping on a 2D step junction."""
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
            "x0_sum_NodeVolume_cm2": float(nv[m0].sum()), "x0_sum_Donors_x_NodeVolume": float((donors * nv)[m0].sum()),
            "x0_sum_Acceptors_x_NodeVolume": float((acceptors * nv)[m0].sum()), "x0_sum_NetDoping_x_NodeVolume": float((nets * nv)[m0].sum()),
            "total_Donors_x_NodeVolume": float((donors * nv).sum()), "total_Acceptors_x_NodeVolume": float((acceptors * nv).sum()),
            "continuum_N_x_area": N_CONC * area_cm2 / 2,
            "note": "raw numbers of the discrete doping representation; not called a sheet charge"}


def snapshot(dv, dev, call_id):
    """ONE query batch of every Potential-derived model, immediately after the (only) solve call and before anything else (PLAN 6)."""
    nv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    ev = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    arr = {"Potential": nv("Potential"), "IntrinsicElectrons": nv("IntrinsicElectrons"), "IntrinsicHoles": nv("IntrinsicHoles"),
           "IntrinsicCharge": nv("IntrinsicCharge"), "PotentialIntrinsicCharge": nv("PotentialIntrinsicCharge"),
           "ElectricField": ev("ElectricField"), "PotentialEdgeFlux": ev("PotentialEdgeFlux")}
    rec = {"call_id": call_id, "array_sha256": {k: jb.sha_arr(v) for k, v in arr.items()},
           "all_finite": bool(all(np.isfinite(v).all() for v in arr.values()))}
    arr["snapshot_call_id"] = np.array(call_id)
    return arr, rec


class Solver:
    """Counts EVERY devsim.solve call and keeps the RAW info result of each (PLAN 6)."""

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
                        "iteration_device_relative_errors": [i["devices"][0]["relative_error"] for i in its],
                        "raw_info": r})
        else:
            rec["converged"] = False
        self.calls.append(rec)
        return rec


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


def run(outd, L, tag):
    import devsim as dv
    name = f"run_L{L}_{tag}"
    res = {"mode": "run", "L": L, "tag": tag, "status": None, "process_id": os.getpid(), "device_name": f"e6c_L{L}_{tag}_device",
           "solve_count": 0, "solve": None}
    sv = None
    dev = mesh = None
    try:
        res["devices_at_start"] = list(dv.get_device_list())
        if res["devices_at_start"]:
            res["status"], res["stop_detail"] = "IMPORT_IDENTITY_FAIL", "device already registered at start"
            raise Stop
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
        ref = jb.load_npz(os.path.join(E6A_OUT, f"level_L{L}.npz"))
        vtu = os.path.join(E6A_OUT, f"level_L{L}.vtu")
        res["input_vtu_sha256"] = ce.sha_file(vtu)
        result = build_process_result({"final_mesh": vtu, "snapshots": []})
        imp = import_process_result(result, mesh_name=f"e6c_L{L}_{tag}_mesh", device_name=res["device_name"],
                                    contact_regions=["Si"], contact_axis="x", length_scale_to_cm=UM)
        dev, mesh = imp.device, imp.mesh
        nv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
        x, y, vol = nv("x"), nv("y"), nv("NodeVolume")
        el = np.array(dv.get_element_node_list(device=dev, region="Si"), dtype=np.int64)
        # ---- import identity (PLAN 3), before this run's solve
        contacts = {}
        for c in imp.contacts:
            contacts[c] = sorted({int(v) for e in dv.get_element_node_list(device=dev, region="Si", contact=c) for v in e})
        idn = jc.import_identity(x, y, vol, el, contacts, list(dv.get_region_list(device=dev)), ref)
        res["identity"] = idn
        if not idn["ok"]:
            res["status"] = "IMPORT_IDENTITY_FAIL"
            raise Stop
        donors, acceptors, nets = write_j0(dv, dev, x)
        res["doping"] = doping_record(x, vol, donors, acceptors, nets, float((x.max() - x.min()) * (y.max() - y.min())))
        if not (res["doping"]["x0_ok"] and jc.doping_check(x, donors, acceptors, nets)):
            res["status"], res["stop_detail"] = "IMPORT_IDENTITY_FAIL", "J0 doping check at x = 0 failed"
            raise Stop
        setup_semiconductor_potential_equation(dev, "Si", ["Si_xmin", "Si_xmax"], 300.0)
        res["flags"] = flags(dv)
        dv.edge_from_node_model(device=dev, region="Si", node_model="node_index")
        ge = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
        n0, n1 = ge("node_index@n0").astype(np.int64), ge("node_index@n1").astype(np.int64)
        res["edge_arrays_equal_E6A"] = {k: bool(np.array_equal(v, ref[k2])) for k, v, k2 in
                                        (("n0", n0, "edge_n0"), ("n1", n1, "edge_n1"), ("EdgeCouple", ge("EdgeCouple"), "EdgeCouple"),
                                         ("EdgeLength", ge("EdgeLength"), "EdgeLength"))}
        # ---- initial potential: P keeps DEVSIM's default; Q is set (PLAN 2), and read back before the solve
        default_init = nv("Potential")
        if tag == "Q":
            vt = float(dv.get_parameter(device=dev, region="Si", name="V_t"))
            ni = float(dv.get_parameter(device=dev, region="Si", name="n_i"))
            n_right, n_left = float(nets[x == x.max()][0]), float(nets[x == x.min()][0])
            vl, vr = jc.contact_potentials(vt, ni, N_CONC)
            intended = jc.affine_init(x, vl, vr)
            ini = {"V_t": vt, "n_i": ni, "NetDoping_at_x_max": n_right, "NetDoping_at_x_min": n_left, "V_left": vl, "V_right": vr,
                   "intended_sha256": jb.sha_arr(intended), "default_init_sha256": jb.sha_arr(default_init),
                   "max_abs_diff_vs_default_init": float(np.max(np.abs(intended - default_init)))}
            res["initialization"] = ini
            why = jc.init_precheck(vt, ni, vl, vr, intended, n_right, n_left, default_init)
            if not why:
                dv.set_node_values(device=dev, region="Si", name="Potential", values=[float(v) for v in intended])
            back = nv("Potential")
            ini["readback_sha256"] = jb.sha_arr(back)
            ini.update(jc.init_contract(why, intended, back))
            init_arr = back
            if not ini["contract_ok"]:
                res["status"] = "INITIALIZATION_CONTRACT_FAIL"
                res["stop_detail"] = "initial Potential contract not satisfied before the solve"
                np.savez_compressed(os.path.join(outd, f"{name}_init.npz"), Potential=init_arr, snapshot_call_id=np.array(f"L{L}-Q-init"))
                res["init_sha256"] = jb.sha_arr(init_arr)
                raise Stop
        else:
            init_arr = default_init
        np.savez_compressed(os.path.join(outd, f"{name}_init.npz"), Potential=init_arr, snapshot_call_id=np.array(f"L{L}-{tag}-init"))
        res["init_sha256"] = jb.sha_arr(init_arr)
        res["init_stats"] = {"n": int(len(init_arr)), "min": float(np.min(init_arr)), "max": float(np.max(init_arr)),
                             "all_finite": bool(np.isfinite(init_arr).all())}
        # ---- the only solve, then one snapshot batch
        sv = Solver(dv)
        s = sv.call(f"L{L}-{tag}", **SOLVE_ARGS)
        arr, rec = snapshot(dv, dev, f"L{L}-{tag}")
        np.savez_compressed(os.path.join(outd, f"{name}_final.npz"), **arr)
        res["snapshot"] = rec
        res["solve"], res["solve_count"] = s, sv.count
        log(f"L{L}-{tag} converged={s.get('converged')} iterations={s.get('n_iterations')} rel={s.get('final_device_relative_error')}")
        res["status"] = "OK"
    except Stop:
        pass
    except Exception as e:  # noqa: BLE001
        res["status"] = res["status"] or "WORKER_ERROR"
        res["error"] = clean(repr(e))[:500]
        res["traceback"] = clean(traceback.format_exc()[-3000:])
        if sv is not None:
            res["solve"], res["solve_count"] = (sv.calls[0] if sv.calls else None), sv.count
    finally:
        try:
            if dev is not None:
                dv.delete_device(device=dev)
            if mesh is not None:
                dv.delete_mesh(mesh=mesh)
        except Exception as e:  # noqa: BLE001
            res["cleanup_error"] = clean(repr(e))[:200]
    finish(outd, f"{name}.json", res, sv, dv)
    return 0 if res["status"] in ("OK", "IMPORT_IDENTITY_FAIL", "INITIALIZATION_CONTRACT_FAIL") else 1


def main():
    outd = os.path.abspath(sys.argv[2])
    os.makedirs(outd, exist_ok=True)
    return run(outd, int(sys.argv[3]), sys.argv[4])


if __name__ == "__main__":
    sys.exit(main())
