"""Batch 7H-E4 remote worker (PLAN sections 2-5). Mesh construction, DEVSIM import and default geometric-model reads
only; devsim.solve trapped. Reuses 7H-E3 (regen/state/baseline/doping) and 7H-E2 (device read/analysis) helpers
read-only. usage: stage_e4.py <out dir>"""
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
E2D = os.path.join(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage")
E3D = os.path.join(AUD, "2026-09-25-batch7h-e3-junction-refinement-candidate")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(E3D, "scripts"))
import stage_e3 as s3  # noqa: E402  (E3, read-only: regen_and_state, raw_arrays, s4_baseline_check, doping_integrals)
import quadtree_e4 as q  # noqa: E402

ce, se2 = s3.ce, s3.se2
E2_OUT = os.path.join(E2D, "data", "remote_run_36129959490", "outputs", "e2_out")
PLAN_SHA = "5630cd702a0ae59e781f3bff0d9e3d6fab05c3b2d279609110e598d4aad866ad"
MAX_TRIANGLES = 500000
N = 1e18
UM = 1e-4
T0 = time.time()


def log(msg):
    print(f"[e4 {time.time() - T0:8.1f}s] {msg}", flush=True)


def main():
    outd = os.path.abspath(sys.argv[1])
    os.makedirs(outd, exist_ok=True)
    import devsim as dv
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    from tcad.device.devsim.mesh_import import import_process_result
    res = {"plan_sha256_expected": PLAN_SHA, "solve_calls": 0, "checks": {}}
    real_solve = dv.solve

    def trap(*a, **k):
        res["solve_calls"] += 1
        raise RuntimeError("E4 forbids devsim.solve")
    dv.solve = trap
    chk = res["checks"]
    try:
        run(outd, res, chk, dv, refine_mesh_near, import_process_result)
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:500]
        res["traceback"] = traceback.format_exc()[-3000:]
    finally:
        dv.solve = real_solve
        res["devices_left"] = list(dv.get_device_list())
        chk["devices_left_empty"] = len(res["devices_left"]) == 0
        chk["solve_calls_0"] = res["solve_calls"] == 0
    failed = [k for k, v in chk.items() if v is not True]
    ok = not failed and "error" not in res and "stop" not in res
    res["verdict"] = {"verdict": "GEOMETRY_CANDIDATE_ONLY" if ok else "CANDIDATE_REJECTED", "failed": failed,
                      "stop": res.get("stop"), "error": res.get("error"),
                      "note": "geometry and DEVSIM's default integration weight only; not electrical accuracy, not 2D mesh "
                              "convergence, not process-order generality; scope = 7H-E1 planar single-Si wafer (PLAN s. 0)"}
    log(f"verdict {res['verdict']['verdict']} failed={failed}")
    return finish(outd, res)


def run(outd, res, chk, dv, refine_mesh_near, import_process_result):
    doped, state = s3.regen_and_state(outd, res)
    chk["input_identity"] = bool(res["input_mesh"]["equal"])
    if not chk["input_identity"]:
        res["stop"] = "MESH_INPUT_IDENTITY_FAIL"
        return
    P0, T0_, G0 = s3.raw_arrays(doped)
    res["s4_baseline_reuse"] = s3.s4_baseline_check(P0, T0_, G0)
    chk["s4_baseline_reuse"] = bool(res["s4_baseline_reuse"]["ok"])
    if not chk["s4_baseline_reuse"]:
        res["stop"] = "S4_BASELINE_REUSE_FAIL"
        return
    P4, T4, G4 = refine_mesh_near(P0, T0_, G0, lambda c: abs(c[0] - 0.0) < 0.1, levels=4)
    t = time.time()
    try:
        pts, tris, tags, rep = q.build_candidate(P0, P4, T4, G4)
    except ValueError as e:
        res["stop"] = str(e)
        return
    masks = rep.pop("_masks")
    res["build"] = rep
    res["build_wall_s"] = time.time() - t
    chk["row_nesting"] = True
    chk["no_unreferenced_nodes"] = rep["unreferenced_nodes"] == 0
    chk["cost_cap"] = rep["n_triangles"] <= MAX_TRIANGLES
    log(f"candidate: {rep['n_nodes']} nodes, {rep['n_triangles']} triangles (build {res['build_wall_s']:.1f}s)")
    if not chk["cost_cap"]:
        res["stop"] = "COST_CAP_EXCEEDED"
        return

    t = time.time()
    ex = q.exact_checks(pts[:, :2], tris, P0[:, :2], T0_)
    res["exact"] = ex
    rem = q.exact_area_of(P4[:, :2], T4[masks["removed"]])
    gen = q.exact_area_of(pts[:, :2], tris[len(tris) - masks["n_new_tris"]:])
    res["strip_area_um2"] = {"removed": f"{rem.numerator}/{rem.denominator}", "generated": f"{gen.numerator}/{gen.denominator}"}
    fine_s4 = {tuple(sorted(map(tuple, P4[t_, :2].astype(float).tolist()))) for t_ in T4[masks["fine"]]}
    nf, nb = int(masks["fine"].sum()), int(masks["base"].sum())
    fine_c = {tuple(sorted(map(tuple, pts[t_, :2].astype(float).tolist()))) for t_ in tris[:nf]}
    base_s4 = {tuple(sorted(map(tuple, P4[t_, :2].astype(float).tolist()))) for t_ in T4[masks["base"]]}
    base_c = {tuple(sorted(map(tuple, pts[t_, :2].astype(float).tolist()))) for t_ in tris[nf:nf + nb]}
    res["exact_wall_s"] = time.time() - t
    chk.update({"fine_region_identical_to_S4": fine_s4 == fine_c, "base_region_identical_to_S4": base_s4 == base_c,
                "removed_area_equals_generated": rem == gen, "exact_area_equal_S0": ex["exact_area_equal_S0"],
                "boundary_points_lost_0": ex["boundary_points_lost"] == 0,
                "boundary_edges_on_outer_lines": ex["n_boundary_edges_off_outer_lines"] == 0, "bbox_equal": ex["bbox_equal"],
                "contact_sets_equal_S0": ex["left_contact_set_equal"] and ex["right_contact_set_equal"],
                "single_tag": bool(np.all(tags == tags[0])) and rep["s4_tags_single_value"],
                "orientation_positive": ex["n_nonpositive_orientation"] == 0, "no_duplicates": ex["n_duplicate_triangles"] == 0,
                "conforming": ex["n_non_manifold_edges"] == 0, "no_obtuse_exact": ex["n_obtuse_exact"] == 0})
    log(f"exact checks ({res['exact_wall_s']:.1f}s): obtuse {ex['n_obtuse_exact']} area_eq {ex['exact_area_equal_S0']}"
        f" boundary lost {ex['boundary_points_lost']} added {ex['boundary_points_added']}")

    vtu = os.path.join(outd, "candidate_e4.vtu")
    res["writer_roundtrip_exact"] = se2.write_vtu(vtu, pts, tris, tags, doped.material_field)
    chk["writer_roundtrip_exact"] = bool(res["writer_roundtrip_exact"])
    res["vtu_sha256"] = ce.sha_file(vtu)
    i = ce.GUI["import"]
    t = time.time()
    imp = import_process_result(dataclasses.replace(doped, volume_mesh_path=vtu), mesh_name="e4_mesh", device_name="e4_device",
                                contact_regions=i["contact_regions"], contact_axis=i["contact_axis"],
                                length_scale_to_cm=i["length_scale_to_cm"])
    res["import_wall_s"] = time.time() - t
    d = se2.read_device(dv, imp)
    se2.release(dv, imp)
    log(f"import + read {res['import_wall_s']:.1f}s: {len(d['x'])} DEVSIM nodes, contacts {sorted(d['contacts'])}")
    t = time.time()
    a, viol = se2.analyze(d, "candidate_e4")
    res["analysis_wall_s"] = time.time() - t
    res["analysis"] = a
    e2r = ce.load_strict(os.path.join(E2_OUT, "e2_result.json"))
    s0c = {c: v["coords_sha256"] for c, v in e2r["stages"][0]["contacts"].items()}
    chk.update({"devsim_contacts_equal_S0": {c: v["coords_sha256"] for c, v in d["contacts"].items()} == s0c,
                "ratio_within_tau": abs(a["ratio"] - 1.0) <= a["tau"],
                "nodevolume_eq_F3_within_budget": bool(a["f3_all_nodes_within_budget"]),
                "quality_exact_overlaps_0": a["quality_7hd"]["exact_positive_overlaps"] == 0,
                "quality_obtuse_0": a["quality_7hd"]["classes"]["obtuse"] == 0})
    res["F3_minus_F2_max_rel"] = float(np.max(np.abs(d["F3"] - d["F2"]) / d["F2"]))
    log(f"ratio {a['ratio']!r} tau {a['tau']:.3e} obtuse {a['quality_7hd']['classes']} delaunay "
        f"{a['quality_7hd']['exact_delaunay_violations_interior']} ({res['analysis_wall_s']:.1f}s)")

    # junction resolution vs S4 / S0 (DEVSIM cm coordinates, exact comparisons)
    z4, z0 = np.load(os.path.join(E2_OUT, "stage_S4.npz")), np.load(os.path.join(E2_OUT, "stage_S0.npz"))
    bc, yc = q.band_stats(d["x"], d["y"], d["el"])
    b4, y4 = q.band_stats(z4["x"], z4["y"], z4["elements"])
    b0, _ = q.band_stats(z0["x"], z0["y"], z0["elements"])
    res["resolution"] = {"candidate": bc, "S4": b4, "S0": b0}
    near = ("0.0-0.025", "0.025-0.05", "0.05-0.1")
    le = lambda u, v: u is not None and v is not None and u <= v  # noqa: E731
    chk["x0_line_equal_S4"] = bool(np.array_equal(yc, y4))
    chk["first_columns_equal_S4"] = bc["x0_line"]["first_columns_cm"] == b4["x0_line"]["first_columns_cm"]
    chk["near_bands_not_coarser_than_S4"] = all(
        le(bc[k]["max_edge_um"], b4[k]["max_edge_um"]) and le(bc[k]["max_horizontal_um"], b4[k]["max_horizontal_um"])
        and le(bc[k]["max_vertical_um"], b4[k]["max_vertical_um"]) for k in near)
    chk["outer_bands_not_coarser_than_S0"] = all(le(bc[k]["max_edge_um"], b0[k]["max_edge_um"]) for k in ("0.1-0.15", "0.15-0.2"))

    # doping integrals: three references per species, x = 0 part and the formula gap reported separately
    di, don, acc = s3.doping_integrals(dv, None, d["x"], d["y"], d["nv"], d["F2"], state, "candidate_e4")
    m0 = d["x"] == 0.0
    xs = np.unique(d["x"])
    i0 = np.searchsorted(xs, 0.0)
    H = float(d["y"].max() - d["y"].min())
    di.update({"x0_nodes": int(m0.sum()), "x0_F2_area_cm2": float(d["F2"][m0].sum()), "x0_NodeVolume_area_cm2": float(d["nv"][m0].sum()),
               "donor_x0_part_F2_cm-1": float((don * d["F2"])[m0].sum()),
               "FORMULA_donor_gap_N_H_hleft_over_2_cm-1": N * H * float(xs[i0] - xs[i0 - 1]) / 2,
               "FORMULA_acceptor_gap_N_H_hright_over_2_cm-1": N * H * float(xs[i0 + 1] - xs[i0]) / 2})
    res["doping"] = di
    chk["all_finite"] = bool(np.isfinite(a["ratio"]) and di["all_finite"])
    np.savez_compressed(os.path.join(outd, "candidate_e4.npz"), x=d["x"], y=d["y"], elements=d["el"], NodeVolume=d["nv"],
                        F2=d["F2"], F3=d["F3"], donors=don, acceptors=acc, edge_n0=d["edge"].get("n0", np.array([])),
                        edge_n1=d["edge"].get("n1", np.array([])), EdgeCouple=d["edge"].get("EdgeCouple", np.array([])),
                        EdgeLength=d["edge"].get("EdgeLength", np.array([])))


def finish(outd, res):
    ce.dump_strict(res, os.path.join(outd, "e4_result.json"))
    log(f"done: error={'error' in res} devices_left={res.get('devices_left')} solve_calls={res['solve_calls']}")
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
