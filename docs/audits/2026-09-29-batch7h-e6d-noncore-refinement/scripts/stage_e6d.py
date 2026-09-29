"""Batch 7H-E6D remote worker. PLAN sections 2-4. Runs only on a GitHub-hosted runner (the driver refuses elsewhere).
usage: stage_e6d.py mesh <out dir> <k>          k in 1, 2: production refine_mesh_near(levels=k) on the E6A L5 mesh, pre-solve gates,
                                                DEVSIM import (devsim.solve trapped: 0 calls), mesh_G<k>.json / .npz / _static.npz / .vtu
       stage_e6d.py run <out dir> <k> <P|Q>     one Poisson solve (as E6C) on mesh_G<k>.vtu, in its own process"""
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
E6A_DIR = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family")
E6A_OUT = os.path.join(E6A_DIR, "data", "remote_run_36388479824", "outputs", "e6a_out")
E6B_OUT = os.path.join(AUD, "2026-09-28-batch7h-e6b-poisson-junction-refinement", "data", "remote_run_36527372624", "outputs", "e6b_out")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
for d in (os.path.join(AUD, "2026-09-29-batch7h-e6c-initialization-robustness", "scripts"), os.path.join(E6A_DIR, "scripts"),
          os.path.join(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage", "scripts"),
          os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts")):
    sys.path.insert(0, d)
import common_e1 as ce  # noqa: E402  (E1, read-only: strict JSON, sha256, USER_PATH sanitizer)
import stage_e6c as s6c  # noqa: E402  (E6C worker, read-only: memory, flags, write_j0, doping_record, snapshot, Solver, finish)
import family_e6a as fam  # noqa: E402  (E6A, read-only: exact_checks / tiling conditions)
import trace_refine_e2 as tr  # noqa: E402  (E2, read-only: exact_area, node_budget, max_angle)
import stage_e2 as se2  # noqa: E402  (E2, read-only: write_vtu)
import judge_e6d as jd  # noqa: E402
jb, jc = jd.jb, jd.jc

UM = 1e-4
X02 = 0.20000000298023224                    # PLAN 2 literal; checked equal to E6A level_L5.json below
PRED = {1: (998000, 499725), 2: (1459200, 730909)}
SOLVE_ARGS = s6c.SOLVE_ARGS
T0 = time.time()


def log(msg):
    print(f"[e6d {time.time() - T0:8.1f}s] {msg}", flush=True)


def clean(text):
    return ce.USER_PATH.sub("<USERPROFILE>", str(text))


def load_g0():
    import meshio
    z = jb.load_npz(os.path.join(E6A_OUT, "level_L5.npz"))
    m = meshio.read(os.path.join(E6A_OUT, "level_L5.vtu"))
    blk = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(blk)]
    same = bool(np.array_equal(m.points, z["points_um_f32"]) and m.points.dtype == np.float32
                and np.array_equal(blk.data, z["triangles"]) and np.array_equal(tags, z["tags"]))
    return z, same


def x02_from_json():
    j = ce.load_strict(os.path.join(E6A_OUT, "level_L5.json"))
    xl = j["build"]["x_lines_um"]
    return xl["+"]["X02"], xl["-"]["X02"]


def contacts_of(dv, dev, names):
    out = {}
    for c in names:
        el = dv.get_element_node_list(device=dev, region="Si", contact=c)
        out[c] = {"nodes": sorted({int(v) for e in el for v in e}), "edges": [[int(e[0]), int(e[1])] for e in el]}
    return out


def import_mesh(dv, vtu, name):
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.mesh.viennaps_adapter import build_process_result
    result = build_process_result({"final_mesh": vtu, "snapshots": []})
    return import_process_result(result, mesh_name=f"{name}_mesh", device_name=f"{name}_device", contact_regions=["Si"], contact_axis="x",
                                 length_scale_to_cm=UM)


def read_device(dv, imp):
    dev = imp.device
    g = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    x, y, nv = g("x"), g("y"), g("NodeVolume")
    el = np.array(dv.get_element_node_list(device=dev, region="Si"), dtype=np.int64)
    dv.edge_from_node_model(device=dev, region="Si", node_model="node_index")
    ge = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
    edge = {"n0": ge("node_index@n0").astype(np.int64), "n1": ge("node_index@n1").astype(np.int64), "EdgeCouple": ge("EdgeCouple"),
            "EdgeLength": ge("EdgeLength")}
    return x, y, nv, el, edge, contacts_of(dv, dev, imp.contacts), list(dv.get_region_list(device=dev))


def import_checks(Pk, Tk, x, y, el, contacts, regions):
    exp = (np.asarray(Pk)[:, :2] * UM).astype(float)
    a, b = np.sort(np.asarray(Tk), axis=1), np.sort(el, axis=1)
    ia, ib = np.lexsort((a[:, 2], a[:, 1], a[:, 0])), np.lexsort((b[:, 2], b[:, 1], b[:, 0]))
    ct = jd.contacts_ok(x, y, contacts)
    return {"xy_equal_scaled_construction": bool(len(x) == len(exp) and np.array_equal(x, exp[:, 0]) and np.array_equal(y, exp[:, 1])),
            "vertex_set_multiset_equal": bool(len(a) == len(b) and np.array_equal(a[ia], b[ib])),
            "regions_Si": regions == ["Si"], "contacts_ok": ct["ok"]}, ct


# ---------------------------------------------------------------- mesh stage
def mesh(outd, k):
    import devsim as dv
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    res = {"mode": "mesh", "k": k, "status": None, "solve_calls": 0, "checks": {}, "wall_s": {}}
    chk, wall = res["checks"], res["wall_s"]
    real = dv.solve

    def trap(*a, **kw):
        res["solve_calls"] += 1
        raise RuntimeError("E6D mesh stage forbids devsim.solve")
    dv.solve = trap
    imp = None
    try:
        z, same = load_g0()
        xp, xm = x02_from_json()
        res["input"] = {"L5_vtu_equals_npz": same, "X02_json": [xp, xm], "X02_literal": X02}
        if not (same and xp == X02 and xm == -X02):
            res["status"] = "INPUT_IDENTITY_FAIL"
            raise s6c.Stop
        P0, T0_, G0 = z["points_um_f32"], z["triangles"], z["tags"]
        pred = lambda c: abs(float(c[0])) >= X02  # noqa: E731  (PLAN 2 seed rule; evaluated by refine_mesh_near each pass)
        res["seed_pass1_count"] = int(sum(pred(c) for c in P0[T0_].mean(axis=1)))
        t = time.time()
        Pk, Tk, Gk = refine_mesh_near(P0, T0_, G0, pred, levels=k)
        wall["production_refine"] = time.time() - t
        res["counts"] = {"n_nodes": int(len(Pk)), "n_triangles": int(len(Tk)), "predicted": {"T": PRED[k][0], "N": PRED[k][1]},
                         "dtypes": [str(Pk.dtype), str(Tk.dtype), str(Gk.dtype)]}
        chk["construction_counts"] = (len(Tk), len(Pk)) == PRED[k]
        log(f"G{k}: {len(Pk)} nodes, {len(Tk)} triangles (predicted {PRED[k][1]}, {PRED[k][0]})")
        ci = jd.core_identity(P0, T0_, Pk, Tk)
        res["core_identity"] = ci
        chk["core_node_set_equal"], chk["core_triangle_multiset_equal"] = ci["core_node_set_equal"], ci["core_triangle_multiset_equal"]
        res["change_record"] = jd.change_record(P0, T0_, Pk, Tk)
        np.savez_compressed(os.path.join(outd, f"mesh_G{k}.npz"), points_um_f32=Pk, triangles=Tk, tags=Gk)
        if not ci["ok"]:
            res["status"] = "GATE_FAIL"                                      # CORE_IDENTITY_FAIL: no import, no solve
            raise s6c.Stop
        t = time.time()
        ex = fam.exact_checks(Pk[:, :2], Tk, P0[:, :2], T0_, Gk, G0[0])
        wall["exact_checks"] = time.time() - t
        res["exact"] = ex
        ang = tr.max_angle_deg_per_triangle(Pk[:, :2].astype(np.float64), Tk)
        cx = np.abs(Pk[Tk][:, :, 0].astype(np.float64).mean(axis=1))
        reg = np.where(cx <= jd.X01_UM, "core", np.where(cx >= X02, "outer", "transition"))
        res["obtuse_float_by_region_reported"] = {r: int(((ang > 90.0) & (reg == r)).sum()) for r in ("core", "transition", "outer")}
        kk = jd.keys(Pk)
        used = np.zeros(len(Pk), bool)
        used[np.asarray(Tk).ravel()] = True
        chk.update({"tags_single_equal_G0": ex["tags_single_equal_S0"], "bbox_equal": ex["bbox_equal"], "area_equals_G0": ex["area_equals_S0"],
                    "orientation_positive": ex["n_nonpositive_orientation"] == 0, "no_duplicate_triangles": ex["n_duplicate_triangles"] == 0,
                    "no_duplicate_nodes": bool(len(np.unique(kk)) == len(kk)), "no_isolated_nodes": bool(used.all()),
                    "tiling_T2": ex["tiling_T2_ok"], "tiling_T3": ex["tiling_T3_ok"]})
        log(f"G{k}: exact {wall['exact_checks']:.1f}s obtuse {ex['n_obtuse_exact']} T2 {ex['tiling_T2_ok']} T3 {ex['tiling_T3_ok']} "
            f"area {ex['area_equals_S0']}")
        vtu = os.path.join(outd, f"mesh_G{k}.vtu")
        chk["writer_roundtrip_exact"] = bool(se2.write_vtu(vtu, Pk, Tk, Gk, "Material"))
        res["vtu_sha256"] = ce.sha_file(vtu)
        t = time.time()
        try:
            imp = import_mesh(dv, vtu, f"e6d_G{k}_meshstage")
            chk["import_ok"] = True
        except Exception as e:  # noqa: BLE001
            chk["import_ok"] = False
            res["import_error"] = clean(repr(e))[:300]
            res["status"] = "GATE_FAIL"
            raise s6c.Stop
        x, y, nv, el, edge, contacts, regions = read_device(dv, imp)
        wall["import_read"] = time.time() - t
        ic, ct = import_checks(Pk, Tk, x, y, el, contacts, regions)
        chk.update(ic)
        res["contacts"] = ct
        t = time.time()
        Pc = np.column_stack([x, y])
        tris = el.tolist()
        area = tr.exact_area(Pc, tris)
        tau = (len(x) + len(tris)) * 2.0 ** -52 + float(tr.node_budget(Pc, tris, len(x)).max())
        nvg = jd.nodevolume_gate(nv, float(area), tau)
        nvg["exact_area_cm2"] = f"{area.numerator}/{area.denominator}"
        wall["nodevolume"] = time.time() - t
        res["nodevolume"] = nvg
        chk["nodevolume_positive"], chk["nodevolume_sum_within_tau"] = nvg["positive"], nvg["sum_within_tau"]
        ecr = jd.edgecouple_record(edge["EdgeCouple"], edge["n0"], edge["n1"], x)
        res["edgecouple"] = ecr
        chk["edgecouple_no_negative"] = ecr["no_negative"]
        log(f"G{k}: NodeVolume ratio {nvg['ratio']!r} tau {tau:.3e} within {nvg['sum_within_tau']}; EdgeCouple neg {ecr['n_negative']} "
            f"zero {ecr['n_zero']}; contacts {ct['ok']}")
        np.savez_compressed(os.path.join(outd, f"mesh_G{k}_static.npz"), x=x, y=y, elements=el, NodeVolume=nv, edge_n0=edge["n0"],
                            edge_n1=edge["n1"], EdgeCouple=edge["EdgeCouple"], EdgeLength=edge["EdgeLength"])
        st, why = jd.mesh_state(chk)
        res["state"], res["failed_checks"] = st, why
        res["status"] = "OK" if st == "OK" else "GATE_FAIL"
    except s6c.Stop:
        res["state"], res["failed_checks"] = jd.mesh_state(chk) if res["status"] == "GATE_FAIL" else (res["status"], [])
    except Exception as e:  # noqa: BLE001
        res["status"] = "WORKER_ERROR"
        res["error"] = clean(repr(e))[:500]
        res["traceback"] = clean(traceback.format_exc()[-3000:])
    finally:
        dv.solve = real
        if imp is not None:
            try:
                dv.delete_device(device=imp.device)
                dv.delete_mesh(mesh=imp.mesh)
            except Exception as e:  # noqa: BLE001
                res["cleanup_error"] = clean(repr(e))[:200]
        res["devices_left"] = list(dv.get_device_list())
        res["memory"] = s6c.memory()
        res["wall_total_s"] = round(time.time() - T0, 1)
    ce.dump_strict(res, os.path.join(outd, f"mesh_G{k}.json"))
    log(f"mesh G{k}: status={res['status']} state={res.get('state')} failed={res.get('failed_checks')} solve_calls={res['solve_calls']}")
    return 0 if res["status"] in ("OK", "GATE_FAIL") else 1


# ---------------------------------------------------------------- run stage (E6C procedure on mesh_G<k>)
def run(outd, k, tag):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
    name, cid = f"run_G{k}_{tag}", f"G{k}-{tag}"
    res = {"mode": "run", "k": k, "tag": tag, "status": None, "process_id": os.getpid(), "device_name": f"e6d_G{k}_{tag}_device",
           "solve_count": 0, "solve": None}
    sv = imp = None
    try:
        res["devices_at_start"] = list(dv.get_device_list())
        if res["devices_at_start"]:
            res["status"], res["stop_detail"] = "IMPORT_IDENTITY_FAIL", "device already registered at start"
            raise s6c.Stop
        g = jb.load_npz(os.path.join(outd, f"mesh_G{k}.npz"))
        st = jb.load_npz(os.path.join(outd, f"mesh_G{k}_static.npz"))
        vtu = os.path.join(outd, f"mesh_G{k}.vtu")
        res["input_vtu_sha256"] = ce.sha_file(vtu)
        imp = import_mesh(dv, vtu, f"e6d_G{k}_{tag}")
        dev = imp.device
        x, y, nv, el, edge, contacts, regions = read_device(dv, imp)
        ic, ct = import_checks(g["points_um_f32"], g["triangles"], x, y, el, contacts, regions)
        ic["NodeVolume_bit_equal_mesh_stage"] = bool(np.array_equal(nv, st["NodeVolume"]))
        ic["ok"] = all(ic.values())
        res["identity"], res["contacts"] = ic, ct
        res["edge_arrays_equal_mesh_stage"] = {kk: bool(np.array_equal(edge[kk], st[k2])) for kk, k2 in
                                               (("n0", "edge_n0"), ("n1", "edge_n1"), ("EdgeCouple", "EdgeCouple"), ("EdgeLength", "EdgeLength"))}
        if not ic["ok"]:
            res["status"] = "IMPORT_IDENTITY_FAIL"
            raise s6c.Stop
        donors, acceptors, nets = s6c.write_j0(dv, dev, x)
        gv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n), dtype=np.float64)  # noqa: E731
        rd, ra, rn = gv("Donors"), gv("Acceptors"), gv("NetDoping")
        res["doping"] = s6c.doping_record(x, nv, rd, ra, rn, float((x.max() - x.min()) * (y.max() - y.min())))
        L5 = jb.load_npz(os.path.join(E6A_OUT, "level_L5.npz"))
        ref = dict(jb.load_npz(os.path.join(E6B_OUT, "level_L5_static.npz")))
        ref["core_mask"] = np.abs(L5["points_um_f32"][:, 0].astype(np.float64)) <= jd.X01_UM
        idx = jd.node_index(L5["points_um_f32"], g["points_um_f32"])
        res["core_doping_equal_G0"] = jd.core_doping_equal(idx, rd, ra, rn, ref)
        res["doping_readback_equal_written"] = bool(np.array_equal(rd, donors) and np.array_equal(ra, acceptors) and np.array_equal(rn, nets))
        if not (res["doping"]["x0_ok"] and res["core_doping_equal_G0"] and res["doping_readback_equal_written"]):
            res["status"], res["stop_detail"] = "IMPORT_IDENTITY_FAIL", "J0 doping check failed"
            raise s6c.Stop
        setup_semiconductor_potential_equation(dev, "Si", ["Si_xmin", "Si_xmax"], 300.0)
        res["flags"] = s6c.flags(dv)
        default_init = gv("Potential")
        if tag == "Q":
            vt = float(dv.get_parameter(device=dev, region="Si", name="V_t"))
            ni = float(dv.get_parameter(device=dev, region="Si", name="n_i"))
            n_right, n_left = float(nets[x == x.max()][0]), float(nets[x == x.min()][0])
            vl, vr = jc.contact_potentials(vt, ni, s6c.N_CONC)
            intended = jc.affine_init(x, vl, vr)
            ini = {"V_t": vt, "n_i": ni, "NetDoping_at_x_max": n_right, "NetDoping_at_x_min": n_left, "V_left": vl, "V_right": vr,
                   "intended_sha256": jb.sha_arr(intended), "default_init_sha256": jb.sha_arr(default_init),
                   "max_abs_diff_vs_default_init": float(np.max(np.abs(intended - default_init)))}
            res["initialization"] = ini
            why = jc.init_precheck(vt, ni, vl, vr, intended, n_right, n_left, default_init)
            if not why:
                dv.set_node_values(device=dev, region="Si", name="Potential", values=[float(v) for v in intended])
            back = gv("Potential")
            ini["readback_sha256"] = jb.sha_arr(back)
            ini.update(jc.init_contract(why, intended, back))
            init_arr = back
            if not ini["contract_ok"]:
                res["status"], res["stop_detail"] = "INITIALIZATION_CONTRACT_FAIL", "initial Potential contract not satisfied before the solve"
                np.savez_compressed(os.path.join(outd, f"{name}_init.npz"), Potential=init_arr, snapshot_call_id=np.array(f"{cid}-init"))
                res["init_sha256"] = jb.sha_arr(init_arr)
                raise s6c.Stop
        else:
            init_arr = default_init
        np.savez_compressed(os.path.join(outd, f"{name}_init.npz"), Potential=init_arr, snapshot_call_id=np.array(f"{cid}-init"))
        res["init_sha256"] = jb.sha_arr(init_arr)
        res["init_stats"] = {"n": int(len(init_arr)), "min": float(np.min(init_arr)), "max": float(np.max(init_arr)),
                             "all_finite": bool(np.isfinite(init_arr).all())}
        sv = s6c.Solver(dv)
        s = sv.call(cid, **SOLVE_ARGS)
        arr, rec = s6c.snapshot(dv, dev, cid)
        np.savez_compressed(os.path.join(outd, f"{name}_final.npz"), **arr)
        res["snapshot"], res["solve"], res["solve_count"] = rec, s, sv.count
        log(f"{cid} converged={s.get('converged')} iterations={s.get('n_iterations')} rel={s.get('final_device_relative_error')}")
        res["status"] = "OK"
    except s6c.Stop:
        pass
    except Exception as e:  # noqa: BLE001
        res["status"] = res["status"] or "WORKER_ERROR"
        res["error"] = clean(repr(e))[:500]
        res["traceback"] = clean(traceback.format_exc()[-3000:])
        if sv is not None:
            res["solve"], res["solve_count"] = (sv.calls[0] if sv.calls else None), sv.count
    finally:
        try:
            if imp is not None:
                dv.delete_device(device=imp.device)
                dv.delete_mesh(mesh=imp.mesh)
        except Exception as e:  # noqa: BLE001
            res["cleanup_error"] = clean(repr(e))[:200]
    s6c.finish(outd, f"{name}.json", res, sv, dv)
    return 0 if res["status"] in ("OK", "IMPORT_IDENTITY_FAIL", "INITIALIZATION_CONTRACT_FAIL") else 1


def main():
    mode, outd = sys.argv[1], os.path.abspath(sys.argv[2])
    os.makedirs(outd, exist_ok=True)
    if mode == "mesh":
        return mesh(outd, int(sys.argv[3]))
    return run(outd, int(sys.argv[3]), sys.argv[4])


if __name__ == "__main__":
    sys.exit(main())
