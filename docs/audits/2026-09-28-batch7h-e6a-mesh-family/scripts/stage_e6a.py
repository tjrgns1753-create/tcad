"""Batch 7H-E6A remote worker, one mode per subprocess (PLAN sections 1-6). devsim.solve is trapped (0 calls required).
usage: stage_e6a.py regen <out dir>         -> regen.json, wafer_volume.vtu (ViennaPS; no DEVSIM)
       stage_e6a.py level <out dir> <L>     -> level_L<L>.json / .npz / .vtu (production refine + DEVSIM import only)"""
import dataclasses
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
E4D = os.path.join(AUD, "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage", "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import common_e1 as ce  # noqa: E402  (E1, read-only: GUI defaults, strict JSON, sha)
import stage_e2 as se2  # noqa: E402  (E2, read-only: regen(), raw_arrays(), read_device(), release(), write_vtu())
import trace_refine_e2 as tr  # noqa: E402  (E2, read-only: exact_area, node_budget -- 7H-E4 section 4C definitions)
import formulas as fm  # noqa: E402  (7H-B, read-only: node_areas F2/F3, edge_couple_predictions)
import family_e6a as fam  # noqa: E402

E4_OUT = os.path.join(E4D, "data", "remote_run_36143535737", "outputs", "e4_out")
UM = 1e-4
T0 = time.time()


def log(msg):
    print(f"[e6a {time.time() - T0:8.1f}s] {msg}", flush=True)


def memory():
    """Windows GetProcessMemoryInfo of this process (bytes); status string elsewhere."""
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
        return {"peak_working_set_bytes": int(pmc.PeakWorkingSetSize), "peak_private_bytes": int(pmc.PeakPagefileUsage),
                "working_set_bytes": int(pmc.WorkingSetSize)}
    except Exception as e:  # noqa: BLE001
        return {"status": "MEMORY_READ_UNAVAILABLE", "error": repr(e)[:200]}


def doped_from(mesh_path):
    """The tail of 7H-E2 regen() (same production calls, no ViennaPS): ProcessResult + step-junction doping."""
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    pr = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    d = ce.GUI["doping"]
    return apply_step_junction_doping(pr, region=d["region"], junction_axis=d["junction_axis"],
                                      junction_position_um=d["junction_position_um"], donor_conc_cm3=d["donor_conc_cm3"],
                                      acceptor_conc_cm3=d["acceptor_conc_cm3"], chemical_state=d["chemical_state"])


def regen(outd):
    res = {"mode": "regen", "gui": ce.GUI}
    try:
        doped = se2.regen(outd, res)
        P0, T0_, G0 = se2.raw_arrays(doped)
        xs, ys = np.unique(P0[:, 0]), np.unique(P0[:, 1])
        res["s0"] = {"n_nodes": int(len(P0)), "n_triangles": int(len(T0_)), "n_x_lines": int(len(xs)), "n_y_lines": int(len(ys)),
                     "tags": sorted({int(t) for t in G0}), "points_dtype": str(P0.dtype),
                     "e0_um": fam.s0_spacing_error(P0[:, :2])}
        res["s0_shape_ok"] = (len(xs), len(ys), len(T0_), len(res["s0"]["tags"])) == (201, 101, 40000, 1)
        res["input_identity_ok"] = bool(res["input_mesh"]["equal"]) and res["s0_shape_ok"]
        res["wafer_path"] = os.path.basename(doped.volume_mesh_path)
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:500]
        res["traceback"] = traceback.format_exc()[-3000:]
    res["memory"] = memory()
    ce.dump_strict(res, os.path.join(outd, "regen.json"))
    log(f"regen: identity_ok={res.get('input_identity_ok')} error={'error' in res}")
    return 0 if "error" not in res else 1


def nodevolume_checks(d):
    """PLAN 4D3/4D4, the NodeVolume part of 7H-E2 analyze() with identical formulas (no overlap / Delaunay scans)."""
    x, y, nv, el = d["x"], d["y"], d["nv"], d["el"]
    tris = [[int(a), int(b), int(c)] for a, b, c in el]
    Pc = np.column_stack([x, y])
    n = len(x)
    area_exact = tr.exact_area(Pc, tris)
    area = float(area_exact)
    f2 = fm.node_areas(Pc, tris, "F2")
    f3 = fm.node_areas(Pc, tris, "F3")
    b = tr.node_budget(Pc, tris, n)
    tau = (n + len(tris)) * 2.0 ** -52 + float(b.max())
    r = {"n_nodes": n, "n_triangles": len(tris), "exact_area_cm2": f"{area_exact.numerator}/{area_exact.denominator}",
         "area_cm2": area, "sum_NodeVolume_cm2": float(nv.sum()), "ratio": float(nv.sum() / area), "tau": tau,
         "ratio_within_tau": bool(abs(nv.sum() / area - 1.0) <= tau), "budget_max_b_i": float(b.max()),
         "f3_max_rel_error": float(np.max(np.abs(nv - f3) / f3)), "f3_nodes_beyond_budget": int((np.abs(nv - f3) > b * f3).sum()),
         "f3_all_nodes_within_budget": bool((np.abs(nv - f3) <= b * f3).all()),
         "F3_minus_F2_max_rel_reported": float(np.max(np.abs(f3 - f2) / f2)),
         "x_sha256": ce.sha(x.tobytes()), "y_sha256": ce.sha(y.tobytes()), "elements_sha256": ce.sha(el.tobytes()),
         "NodeVolume_sha256": ce.sha(nv.tobytes())}
    ed = d["edge"]
    if "error" in ed:
        r["edgecouple"] = {"status": "EDGECOUPLE_UNKNOWN", "error": ed["error"]}
    else:
        g1, g2, _ = fm.edge_couple_predictions(Pc, tris)
        keys = [(min(a, b_), max(a, b_)) for a, b_ in zip(ed["n0"], ed["n1"])]
        G1 = np.array([g1[k] for k in keys])
        G2 = np.array([g2[k] for k in keys])
        ec = ed["EdgeCouple"]
        scale = float(np.abs(G2).max())
        r["edgecouple"] = {"status": "READ", "n_edges": int(len(ec)), "negative": int((ec < 0).sum()), "zero": int((ec == 0).sum()),
                           "positive": int((ec > 0).sum()), "n_G1_negative": int((G1 < 0).sum()),
                           "max_abs_EC_minus_G2_over_maxG2": float(np.abs(ec - G2).max() / scale),
                           "max_abs_EC_minus_G1_over_maxG2": float(np.abs(ec - G1).max() / scale)}
    return r, f2, f3


def level(outd, L):
    import devsim as dv
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    from tcad.device.devsim.mesh_import import import_process_result
    res = {"mode": "level", "L": L, "solve_calls": 0, "checks": {}, "wall_s": {}}
    chk, wall = res["checks"], res["wall_s"]
    real_solve = dv.solve

    def trap(*a, **k):
        res["solve_calls"] += 1
        raise RuntimeError("E6A forbids devsim.solve")
    dv.solve = trap
    try:
        run_level(outd, L, res, chk, wall, dv, refine_mesh_near, import_process_result)
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:500]
        res["traceback"] = traceback.format_exc()[-3000:]
    finally:
        dv.solve = real_solve
        res["devices_left"] = list(dv.get_device_list())
        chk["devices_left_empty"] = len(res["devices_left"]) == 0
        chk["solve_calls_0"] = res["solve_calls"] == 0
        res["memory"] = memory()
    res["failed_checks"] = [k for k, v in chk.items() if v is not True]
    res["level_pass"] = not res["failed_checks"] and "error" not in res and "stop" not in res
    ce.dump_strict(res, os.path.join(outd, f"level_L{L}.json"))
    log(f"L{L}: pass={res['level_pass']} stop={res.get('stop')} failed={res['failed_checks']} error={'error' in res}")
    return 0 if "error" not in res else 1


def run_level(outd, L, res, chk, wall, dv, refine_mesh_near, import_process_result):
    rg = ce.load_strict(os.path.join(outd, "regen.json"))
    wafer = os.path.join(outd, rg["wafer_path"])
    res["wafer_sha256"] = ce.sha_file(wafer)
    chk["input_identity"] = bool(rg.get("input_identity_ok")) and res["wafer_sha256"] == rg["input_mesh"]["sha256"]
    if not chk["input_identity"]:
        res["stop"] = "INPUT_IDENTITY_FAIL"
        return
    doped = doped_from(wafer)
    P0, T0_, G0 = se2.raw_arrays(doped)
    ny, nxc = len(np.unique(P0[:, 1])) - 1, len(np.unique(P0[:, 0])) - 1
    t = time.time()
    PL, TL, GL = refine_mesh_near(P0, T0_, G0, lambda c: abs(c[0] - 0.0) < 0.1, levels=L)
    wall["production_refine"] = time.time() - t
    t = time.time()
    try:
        pts, tris, tags, rep, info = fam.build_level(P0, PL, TL, GL, L)
    except ValueError as e:
        res["stop"] = str(e).split()[0]
        res["stop_detail"] = str(e)
        return
    wall["build"] = time.time() - t
    res["build"] = rep
    T_pred, N_pred = fam.predicted_counts(L, ny, nxc)
    res["predicted"] = {"T": T_pred, "N": N_pred}
    chk["construction_counts"] = (rep["n_triangles"], rep["n_nodes"]) == (T_pred, N_pred)
    chk["no_unreferenced_nodes"] = rep["unreferenced_nodes"] == 0
    log(f"L{L}: {rep['n_nodes']} nodes, {rep['n_triangles']} triangles (predicted {N_pred}, {T_pred})")

    t = time.time()
    cc = fam.construction_checks(P0, T0_, PL, TL, pts, tris, info, L)
    res["construction"] = cc
    for k in ("x_lines_are_mid32_recursion", "x_lines_strictly_ordered", "sl_points_prefix_bit_identical",
              "fine_rows_identical_to_S_L", "base_rows_identical_to_S_L", "base_region_equal_S0_coordinate_triples",
              "hanging_midpoints_owned"):
        chk[k] = bool(cc[k])
    ex = fam.exact_checks(pts[:, :2], tris, P0[:, :2], T0_, tags, G0[0])
    res["exact"] = ex
    wall["exact_checks"] = time.time() - t
    chk.update({"B1_orientation_positive": ex["n_nonpositive_orientation"] == 0, "B2_no_obtuse": ex["n_obtuse_exact"] == 0,
                "B3_no_duplicates": ex["n_duplicate_triangles"] == 0, "B4_tiling_T2": ex["tiling_T2_ok"],
                "B4_tiling_T3": ex["tiling_T3_ok"], "B5_area_equals_rect": ex["area_equals_rect"],
                "B5_area_equals_S0": ex["area_equals_S0"], "B6_boundary_points_lost_0": ex["boundary_points_lost"] == 0,
                "B6_bbox_equal": ex["bbox_equal"], "B6_contacts_equal_S0": ex["left_contact_set_equal"] and ex["right_contact_set_equal"],
                "B6_tags": ex["tags_single_equal_S0"]})
    log(f"L{L}: exact checks {wall['exact_checks']:.1f}s obtuse {ex['n_obtuse_exact']} T2 {ex['tiling_T2_ok']} T3 {ex['tiling_T3_ok']}")

    t = time.time()
    e0 = fam.s0_spacing_error(P0[:, :2])
    rc, y0, xf = fam.resolution_checks(pts[:, :2], tris, PL[:, :2], P0[:, :2], T0_, rep, L, e0)
    res["resolution"] = rc
    chk["C_resolution"] = bool(rc["ok"])
    wall["resolution"] = time.time() - t

    if L == 4:
        import meshio
        m = meshio.read(os.path.join(E4_OUT, "candidate_e4.vtu"))
        blk = next(c for c in m.cells if c.type == "triangle")
        rtags = m.cell_data[doped.material_field][m.cells.index(blk)]
        res["l4_reproduction"] = fam.l4_reproduction(pts[:, :2], tris, tags, m.points[:, :2], blk.data, rtags)
        chk["L4_reproduction"] = bool(res["l4_reproduction"]["ok"])

    vtu = os.path.join(outd, f"level_L{L}.vtu")
    chk["writer_roundtrip_exact"] = bool(se2.write_vtu(vtu, pts, tris, tags, doped.material_field))
    res["vtu_sha256"] = ce.sha_file(vtu)
    i = ce.GUI["import"]
    t = time.time()
    try:
        imp = import_process_result(dataclasses.replace(doped, volume_mesh_path=vtu), mesh_name=f"e6a_L{L}_mesh",
                                    device_name=f"e6a_L{L}_device", contact_regions=i["contact_regions"],
                                    contact_axis=i["contact_axis"], length_scale_to_cm=i["length_scale_to_cm"])
    except Exception as e:  # noqa: BLE001
        res["stop"] = "DEVSIM_IMPORT_FAIL"
        res["stop_detail"] = repr(e)[:300]
        return
    try:
        d = se2.read_device(dv, imp)
    finally:
        se2.release(dv, imp)
    wall["import_read"] = time.time() - t
    exp = (pts[:, :2] * i["length_scale_to_cm"]).astype(float)
    got = np.column_stack([d["x"], d["y"]])
    srt = lambda Q: Q[np.lexsort((Q[:, 1], Q[:, 0]))]  # noqa: E731
    e4 = ce.load_strict(os.path.join(E4_OUT, "e4_result.json"))
    e4c = {c: v["coords_sha256"] for c, v in e4["analysis"]["contacts"].items()}
    res["devsim"] = {"n_nodes": int(len(d["x"])), "n_elements": int(len(d["el"])), "regions": d["regions"],
                     "contacts": d["contacts"], "e4_contacts_coords_sha256": e4c}
    chk["D2_coordinates_equal_scaled_construction"] = bool(got.shape == exp.shape and np.array_equal(srt(got), srt(exp)))
    chk["D2_elements_count"] = len(d["el"]) == rep["n_triangles"]
    chk["D2_regions"] = d["regions"] == ["Si"]
    chk["D2_contacts"] = ({c: v["n_nodes"] for c, v in d["contacts"].items()} == {"Si_xmin": 101, "Si_xmax": 101}
                          and {c: v["coords_sha256"] for c, v in d["contacts"].items()} == e4c)
    t = time.time()
    nvr, f2, f3 = nodevolume_checks(d)
    wall["nodevolume"] = time.time() - t
    res["nodevolume"] = nvr
    chk["D3_ratio_within_tau"] = nvr["ratio_within_tau"]
    chk["D4_nodevolume_eq_F3_within_budget"] = nvr["f3_all_nodes_within_budget"]
    chk["all_finite"] = bool(np.isfinite(nvr["ratio"]) and np.all(np.isfinite(d["nv"])))
    log(f"L{L}: ratio {nvr['ratio']!r} tau {nvr['tau']:.3e} F3 within budget {nvr['f3_all_nodes_within_budget']} "
        f"({wall['nodevolume']:.1f}s)")
    if L == 4:
        z = np.load(os.path.join(E4_OUT, "candidate_e4.npz"))
        ka = np.lexsort((d["y"], d["x"]))
        kb = np.lexsort((z["y"], z["x"]))
        same_xy = np.array_equal(d["x"][ka], z["x"][kb]) and np.array_equal(d["y"][ka], z["y"][kb])
        res["l4_reproduction"]["nodevolume_equal_E4_by_coordinate_reported_only"] = bool(
            same_xy and np.array_equal(d["nv"][ka], z["NodeVolume"][kb]))
    ed = d["edge"]
    np.savez_compressed(os.path.join(outd, f"level_L{L}.npz"), points_um_f32=pts, triangles=tris, tags=tags, x0_y_um_f32=y0,
                        fine_x_um_f32=xf, x=d["x"], y=d["y"], elements=d["el"], NodeVolume=d["nv"], F2=f2, F3=f3,
                        edge_n0=ed.get("n0", np.array([])), edge_n1=ed.get("n1", np.array([])),
                        EdgeCouple=ed.get("EdgeCouple", np.array([])), EdgeLength=ed.get("EdgeLength", np.array([])))


def main():
    mode, outd = sys.argv[1], os.path.abspath(sys.argv[2])
    os.makedirs(outd, exist_ok=True)
    if mode == "regen":
        return regen(outd)
    return level(outd, int(sys.argv[3]))


if __name__ == "__main__":
    sys.exit(main())
