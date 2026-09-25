"""Batch 7H-E3 remote worker (PLAN sections 1-10). Builds ONE candidate mesh via the unmodified production
graded_refine_mesh_near() and evaluates it geometrically against the reused 7H-E2 S4 baseline. No devsim.solve, no
production/test file touched. usage: stage_e3.py <out dir>"""
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
E1 = os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence")
E2 = os.path.join(AUD, "2026-09-25-batch7h-e2-nodevolume-first-bad-stage")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(E1, "scripts"))
sys.path.insert(0, os.path.join(E2, "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-d-sg-pn-mesh-validity", "scripts"))
import common_e1 as ce  # noqa: E402  (E1, read-only: GUI defaults, strict JSON, sha)
import trace_refine_e2 as tr  # noqa: E402  (E2, read-only: exact_area/exact_orient2/node_budget/angle helpers)
import stage_e2 as se2  # noqa: E402  (E2, read-only: read_device()/analyze()/release()/write_vtu(), reused verbatim)

UM = 1e-4
E1_MESH_SHA = "cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a"
E1_PROD = os.path.join(E1, "data", "remote_run_36012608804", "outputs", "e1_out", "prod.json")
E1_NPZ = os.path.join(E1, "data", "remote_run_36012608804", "outputs", "e1_out", "prod_arrays.npz")
E2_S4_NPZ = os.path.join(E2, "data", "remote_run_36129959490", "outputs", "e2_out", "stage_S4.npz")
E2_RESULT = os.path.join(E2, "data", "remote_run_36129959490", "outputs", "e2_out", "e2_result.json")
RING_HALF_WIDTHS = (0.1, 0.05, 0.025, 0.0125)   # PLAN section 2, fixed before results
MAX_TRIANGLES = 500000                          # PLAN section 8
S4_MIN_EDGE_UM = 0.003124296199530363           # PLAN section 3, extracted from E2's committed stage_S4.npz
T0 = time.time()


def log(msg):
    print(f"[e3 {time.time() - T0:8.1f}s] {msg}", flush=True)


def regen_and_state(outd, rec):
    """Regenerate the wafer mesh and the WaferStateV2 the same way prod_build_e1.build() does (reused method, not a
    new one), so state.net_doping_at() is available for the candidate's per-node doping query (section 6)."""
    from tcad.backends.viennaps import session as vs
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe, advance_wafer_state
    from tcad.device.devsim.mesh_import import derive_barrier_covered_windows
    g = ce.GUI
    domain = vs.make_mask_spans(grid_delta_um=g["grid_delta_um"], x_extent_um=g["x_extent_um"], y_extent_um=g["y_extent_um"],
                                spans_um=[tuple(s) for s in g["mask_spans_um"]], mask_height_um=max(g["pr_thickness_um"], 0.1),
                                substrate_depth_um=g["silicon_depth_um"] + 1.0)
    mesh_path = save_volume_mesh(domain, os.path.join(outd, "wafer"), floor_depth_um=g["silicon_depth_um"])
    sha = ce.sha_file(mesh_path)
    rec["input_mesh"] = {"name": os.path.basename(mesh_path), "sha256": sha, "e1_sha256": E1_MESH_SHA, "equal": sha == E1_MESH_SHA}
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
        rec["barrier_windows"] = {"status": "OK", "value": barrier}
    except Exception as e:  # noqa: BLE001 - matches E1/E2's own handling
        barrier = None
        rec["barrier_windows"] = {"status": "EXCEPTION_GUI_USES_NONE", "error": repr(e)[:200]}
    state = advance_wafer_state(state, doped, "doping", barrier_windows=barrier, barrier_axis="x")
    return doped, state


def raw_arrays(result):
    import meshio
    m = meshio.read(result.volume_mesh_path)
    blk = next(c for c in m.cells if c.type == "triangle")
    bi = m.cells.index(blk)
    return m.points, blk.data, m.cell_data[result.material_field][bi]


def s4_baseline_check(raw_points, raw_triangles, raw_tags):
    """PLAN section 1: reproduce S4 with the unmodified production single-window call, and prove -- with plain
    numpy, no second DEVSIM import -- that it is the SAME S4 7H-E1/E2 already built and recorded."""
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    e1 = ce.load_strict(E1_PROD)
    pp, tt, gg = refine_mesh_near(raw_points, raw_triangles, raw_tags, lambda c: abs(c[0] - 0.0) < 0.1, levels=4)
    pc = (pp * ce.GUI["import"]["length_scale_to_cm"]).astype(float)
    x_sha, y_sha = ce.sha(pc[:, 0].tobytes()), ce.sha(pc[:, 1].tobytes())
    reg = e1["region_facts"]["Si"]
    xy_ok = x_sha == reg["x_sha256"] and y_sha == reg["y_sha256"]
    s4npz = np.load(E2_S4_NPZ)
    ok_el = sorted(map(tuple, np.sort(tt, 1).tolist())) == sorted(map(tuple, np.sort(s4npz["elements"], 1).tolist()))
    return {"x_sha256": x_sha, "y_sha256": y_sha, "e1_x_sha256": reg["x_sha256"], "e1_y_sha256": reg["y_sha256"],
            "xy_bit_equal": bool(xy_ok), "elements_multiset_equal_to_E2_S4": bool(ok_el),
            "n_triangles_reproduced": len(tt), "n_triangles_E2_S4": len(s4npz["elements"]),
            "ok": bool(xy_ok and ok_el and len(tt) == len(s4npz["elements"]))}


def geometric_invariants(raw_points, s0_area, candidate_points, candidate_triangles, candidate_tags):
    """PLAN section 4: bit-identical (boundary, tags, exact-zero coords) + geometry-identical (area) + direct checks
    (conforming adjacency, no duplicate/zero/inverted triangle, no exact overlaps)."""
    import build_fixtures_7hd as bf7
    eg = bf7.eg
    P0 = raw_points[:, :2].astype(float)
    Pc = candidate_points[:, :2].astype(float)
    bx0, bx1 = float(P0[:, 0].min()), float(P0[:, 0].max())
    by0, by1 = float(P0[:, 1].min()), float(P0[:, 1].max())
    boundary_mask0 = (P0[:, 0] == bx0) | (P0[:, 0] == bx1) | (P0[:, 1] == by0) | (P0[:, 1] == by1)
    boundary_pts0 = set(map(tuple, P0[boundary_mask0].tolist()))
    boundary_maskc = (Pc[:, 0] == bx0) | (Pc[:, 0] == bx1) | (Pc[:, 1] == by0) | (Pc[:, 1] == by1)
    boundary_ptsc = set(map(tuple, Pc[boundary_maskc].tolist()))
    tris = [[int(v) for v in t] for t in candidate_triangles]
    area_exact = tr.exact_area(Pc, tris)
    x0_c = Pc[Pc[:, 0] == 0.0]
    ipts, K = eg.exact_integer_points(Pc)
    inv = eg.mesh_exact_invariants(ipts, tris, [0] * len(tris))
    scan, _ = eg.global_exact_scan(ipts, tris, K)
    owners = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            owners.setdefault((min(a, b), max(a, b)), []).append(1)
    non_manifold = sum(1 for o in owners.values() if len(o) > 2)
    return {"boundary_points_bit_identical": boundary_ptsc == boundary_pts0, "n_boundary_points": len(boundary_pts0),
            "tags_single_value": bool(np.all(candidate_tags == candidate_tags[0])),
            "n_nodes_exactly_x0": int(len(x0_c)), "x0_coords_exactly_zero": bool(np.all(x0_c[:, 0] == 0.0)) if len(x0_c) else True,
            "exact_area_cm2": f"{area_exact.numerator}/{area_exact.denominator}",
            "exact_area_equal_S0": area_exact == s0_area,
            "n_duplicate_triangles": len(inv["duplicate_triangle_set"]), "n_zero_area": len(inv["zero_area_set"]),
            "n_inverted": len(inv["inverted_set"]), "n_non_manifold_edges": non_manifold,
            "n_exact_positive_overlaps": scan["counts"]["EXACT_POSITIVE_AREA_OVERLAP"],
            "conforming": non_manifold == 0 and len(inv["duplicate_triangle_set"]) == 0 and len(inv["zero_area_set"]) == 0}


def resolution_check(points, triangles):
    """PLAN section 3: minimum edge length among edges with at least one endpoint within 0.1 um of x=0."""
    P = points[:, :2].astype(float)
    edges = set()
    for a, b, c in triangles:
        for u, v in ((a, b), (b, c), (c, a)):
            edges.add((int(min(u, v)), int(max(u, v))))
    E = np.array(sorted(edges))
    L = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    near = np.minimum(np.abs(P[E[:, 0], 0]), np.abs(P[E[:, 1], 0])) < 0.1
    return {"n_edges_near_junction": int(near.sum()), "min_edge_length_near_junction_um": float(L[near].min()),
            "s4_target_um": S4_MIN_EDGE_UM, "not_coarser_than_S4": bool(L[near].min() <= S4_MIN_EDGE_UM)}


def doping_integrals(dv, dev, x, y, nv, F2, state, label):
    """PLAN section 6: three separate references, never conflated. state.net_doping_at() is queried per node
    (the real production canonical-doping method, not a re-derivation)."""
    n = len(x)
    donors = np.empty(n)
    acceptors = np.empty(n)
    for i in range(n):
        q = state.net_doping_at(float(x[i] / UM), float(y[i] / UM))
        donors[i] = q.donor_concentration
        acceptors[i] = q.acceptor_concentration
    finite = bool(np.all(np.isfinite(donors)) and np.all(np.isfinite(acceptors)))
    out = {"label": label, "all_finite": finite}
    for name, N in (("donor", donors), ("acceptor", acceptors)):
        out[f"{name}_devsim_NodeVolume_cm-1"] = float((N * nv).sum())
        out[f"{name}_same_mesh_F2_cm-1"] = float((N * F2).sum())
        out[f"{name}_geometric_continuum_cm-1"] = 1e18 * 25.0 * UM * UM
    return out, donors, acceptors


def main():
    outd = os.path.abspath(sys.argv[1])
    os.makedirs(outd, exist_ok=True)
    import devsim as dv
    res = {"plan_sha256_expected": "0302f032a6f8980d08ed73a4722dd46ea308a906e815278d1e36f1286e82041b",
           "ring_half_widths_um": list(RING_HALF_WIDTHS), "solve_calls": 0}
    real_solve = dv.solve

    def trap(*a, **k):
        res["solve_calls"] += 1
        raise RuntimeError("E3 forbids devsim.solve")
    dv.solve = trap
    try:
        doped, state = regen_and_state(outd, res)
        log(f"input mesh equal to E1: {res['input_mesh']['equal']}")
        if not res["input_mesh"]["equal"]:
            res["stop"] = "MESH_INPUT_IDENTITY_FAIL"
            return finish(outd, res)
        raw_points, raw_triangles, raw_tags = raw_arrays(doped)
        s0_area = tr.exact_area(raw_points[:, :2].astype(float), [[int(v) for v in t] for t in raw_triangles])
        res["s0"] = {"n_nodes": len(raw_points), "n_triangles": len(raw_triangles), "exact_area_cm2": f"{s0_area.numerator}/{s0_area.denominator}"}
        res["s4_baseline_reuse"] = s4_baseline_check(raw_points, raw_triangles, raw_tags)
        log(f"S4 baseline reuse ok: {res['s4_baseline_reuse']['ok']}")
        if not res["s4_baseline_reuse"]["ok"]:
            res["stop"] = "S4_BASELINE_REUSE_FAIL"
            return finish(outd, res)

        from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
        from tcad.device.devsim.mesh_import import import_process_result
        preds = [(lambda c, w=w: abs(c[0] - 0.0) < w) for w in RING_HALF_WIDTHS]
        t = time.time()
        cp, ct, cg = graded_refine_mesh_near(raw_points, raw_triangles, raw_tags, preds)
        res["candidate_build_wall_s"] = time.time() - t
        res["candidate_raw"] = {"n_nodes": len(cp), "n_triangles": len(ct)}
        log(f"candidate raw: {len(cp)} nodes, {len(ct)} triangles ({res['candidate_build_wall_s']:.1f}s)")
        if len(ct) > MAX_TRIANGLES:
            res["stop"] = "COST_CAP_EXCEEDED"
            res["candidate"] = {"verdict": "CANDIDATE_REJECTED", "failed": ["cost_cap"],
                                "reason": f"{len(ct)} triangles exceeds cap {MAX_TRIANGLES}"}
            return finish(outd, res)

        res["geometric_invariants"] = geometric_invariants(raw_points, s0_area, cp, ct, cg)
        res["resolution"] = resolution_check(cp, ct)
        log(f"invariants: {res['geometric_invariants']['conforming']} area_eq_S0: {res['geometric_invariants']['exact_area_equal_S0']}"
            f" resolution: not_coarser={res['resolution']['not_coarser_than_S4']}")

        field = doped.material_field
        vtu_path = os.path.join(outd, "candidate.vtu")
        wr = se2.write_vtu(vtu_path, cp, ct, cg, field)
        res["writer_roundtrip_exact"] = wr
        res["vtu_sha256"] = ce.sha_file(vtu_path)

        i = ce.GUI["import"]
        t = time.time()
        imp = import_process_result(dataclasses.replace(doped, volume_mesh_path=vtu_path), mesh_name="e3_candidate_mesh",
                                    device_name="e3_candidate_device", contact_regions=i["contact_regions"],
                                    contact_axis=i["contact_axis"], length_scale_to_cm=i["length_scale_to_cm"])
        res["import_wall_s"] = time.time() - t
        d = se2.read_device(dv, imp)
        se2.release(dv, imp)
        log(f"import + read: {res['import_wall_s']:.1f}s, {len(d['x'])} DEVSIM nodes")

        analysis, viol = se2.analyze(d, "candidate", {"ring_half_widths_um": list(RING_HALF_WIDTHS)})
        res["candidate_analysis"] = analysis
        res["candidate_analysis"]["lineage_n_delaunay_violations"] = len(viol)

        # doping integrals (candidate: fresh query; S4: reused from E1's already-recorded arrays, not recomputed)
        di, don, acc = doping_integrals(dv, imp.device, d["x"], d["y"], d["nv"], d["F2"], state, "candidate")
        res["doping_candidate"] = di
        e2_result = ce.load_strict(E2_RESULT)
        res["s4_reused_geometry"] = e2_result["stages"][4]   # E2's own recorded S4 row, verbatim, not recomputed
        e1a = np.load(E1_NPZ)
        s4npz = np.load(E2_S4_NPZ)
        res["doping_S4_reused"] = {
            "label": "S4 (reused from E1/E2, not recomputed)",
            "donor_devsim_NodeVolume_cm-1": float((e1a["Donors"] * e1a["NodeVolume"]).sum()),
            "donor_same_mesh_F2_cm-1": float((e1a["Donors"] * s4npz["F2"]).sum()),
            "donor_geometric_continuum_cm-1": 1e18 * 25.0 * UM * UM,
            "acceptor_devsim_NodeVolume_cm-1": float((e1a["Acceptors"] * e1a["NodeVolume"]).sum()),
            "acceptor_same_mesh_F2_cm-1": float((e1a["Acceptors"] * s4npz["F2"]).sum()),
            "acceptor_geometric_continuum_cm-1": 1e18 * 25.0 * UM * UM}
        np.savez_compressed(os.path.join(outd, "candidate.npz"), x=d["x"], y=d["y"], elements=d["el"], NodeVolume=d["nv"],
                            F2=d["F2"], F3=d["F3"], donors=don, acceptors=acc,
                            edge_n0=d["edge"].get("n0", np.array([])), edge_n1=d["edge"].get("n1", np.array([])),
                            EdgeCouple=d["edge"].get("EdgeCouple", np.array([])), EdgeLength=d["edge"].get("EdgeLength", np.array([])))

        checks = {
            "input_identity": res["input_mesh"]["equal"], "s4_baseline_reuse": res["s4_baseline_reuse"]["ok"],
            "boundary_bit_identical": res["geometric_invariants"]["boundary_points_bit_identical"],
            "tags_single_value": res["geometric_invariants"]["tags_single_value"],
            "x0_coords_exact": res["geometric_invariants"]["x0_coords_exactly_zero"],
            "exact_area_equal_S0": res["geometric_invariants"]["exact_area_equal_S0"],
            "conforming_no_duplicate_zero_inverted": res["geometric_invariants"]["conforming"],
            "no_exact_overlaps": res["geometric_invariants"]["n_exact_positive_overlaps"] == 0,
            "resolution_not_coarser_than_S4": res["resolution"]["not_coarser_than_S4"],
            "ratio_within_tau": abs(analysis["ratio"] - 1.0) <= analysis["tau"],
            "all_finite": bool(np.isfinite(analysis["ratio"])) and di["all_finite"],
            "devices_left_empty": True,  # checked below, updated before use
        }
        failed = [k for k, v in checks.items() if not v]
        res["candidate"] = {"verdict": "GEOMETRY_CANDIDATE_ONLY" if not failed else "CANDIDATE_REJECTED",
                            "checks": checks, "failed": failed,
                            "note": "geometry and DEVSIM's own default integration weight ONLY -- not evidence of "
                                    "electrical accuracy, 2D mesh convergence, or applicability beyond the E1 single-Si "
                                    "planar-wafer scope (PLAN section 0)."}
        log(f"candidate verdict {res['candidate']['verdict']} failed={failed}")
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:500]
        res["traceback"] = traceback.format_exc()[-3000:]
    finally:
        dv.solve = real_solve
        res["devices_left"] = list(dv.get_device_list())
        if "candidate" in res and isinstance(res["candidate"].get("checks"), dict):
            res["candidate"]["checks"]["devices_left_empty"] = len(res["devices_left"]) == 0
            if res["devices_left"] and "CANDIDATE_REJECTED" != res["candidate"]["verdict"]:
                res["candidate"]["verdict"] = "CANDIDATE_REJECTED"
                res["candidate"]["failed"].append("devices_left_empty")
    return finish(outd, res)


def finish(outd, res):
    ce.dump_strict(res, os.path.join(outd, "e3_result.json"))
    log(f"done: error={'error' in res} devices_left={res.get('devices_left')} solve_calls={res['solve_calls']}")
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
