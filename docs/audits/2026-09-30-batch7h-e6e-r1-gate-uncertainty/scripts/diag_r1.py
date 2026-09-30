"""Batch 7H-E6E-R1 import-only diagnosis of two representative ViennaPS meshes (PLAN section 3). Remote only.
usage: diag_r1.py <out dir> A|B
A: tests/integration/test_phase5_devsim_real.py production path (isotropic etch with Mask, no refinement, length_scale_to_cm 1.0)
B: tests/integration/test_measurement_canonical_state_gate_real.py case B1 (GUI wafer, implant_windows refinement, 1e-4); B raw too.
For every mesh: the production refusal first; then, in THIS process only, verify_device is replaced by a recorder so every region can be
read (diagnostic bypass). solve / doping / equation writes are trapped (a call raises and is counted). NodeVolume is only read."""
import collections
import json
import os
import shutil
import sys
import tempfile
import traceback
from fractions import Fraction

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import formulas as fm  # noqa: E402  (7H-B, read-only: F2 / F3 node areas)
import common_e1 as ce  # noqa: E402

WRITE_APIS = ("solve", "node_model", "edge_model", "set_node_values", "set_node_value", "equation", "contact_equation", "node_solution")
CALLS = collections.Counter()


def exact_area(P, T):
    X = [Fraction(float(v)) for v in P[:, 0]]
    Y = [Fraction(float(v)) for v in P[:, 1]]
    return sum(abs((X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])) for a, b, c in np.asarray(T).tolist()) / 2


def fr(x):
    return {"exact": f"{x.numerator}/{x.denominator}", "float": float(x)}


def angles_deg(P, T):
    P = np.asarray(P, dtype=np.float64)[:, :2]
    T = np.asarray(T, dtype=np.int64)
    out = []
    for k in range(3):
        a, b, c = P[T[:, k]], P[T[:, (k + 1) % 3]], P[T[:, (k + 2) % 3]]
        u, v = b - a, c - a
        out.append(np.degrees(np.arctan2(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), (u * v).sum(1))))
    return np.stack(out, axis=1)


def shape(P, T):
    ang = angles_deg(P, T)
    mx, mn = ang.max(1), ang.min(1)
    k = np.round(np.asarray(P, dtype=np.float64)[:, :2], 15)
    _, cnt = np.unique(k, axis=0, return_counts=True)
    s = np.sort(np.asarray(T), axis=1)
    return {"triangles": int(len(T)), "min_angle_deg": {"min": float(mn.min()), "median": float(np.median(mn))},
            "max_angle_deg": {"max": float(mx.max()), "median": float(np.median(mx))},
            "n_max_angle_gt": {str(t): int((mx > t).sum()) for t in (90, 120, 150, 170, 179)},
            "duplicate_coordinates": int((cnt > 1).sum()), "duplicate_triangles": int(len(s) - len(np.unique(s, axis=0)))}


def edges_owned(T):
    e = collections.defaultdict(list)
    for i, (a, b, c) in enumerate(np.asarray(T).tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            e[(min(u, v), max(u, v))].append(i)
    return e


def topology(P, T, tags, names):
    e = edges_owned(T)
    owners = collections.Counter(len(v) for v in e.values())
    inter = collections.Counter()
    one_len = collections.Counter()
    for (u, v), ow in e.items():
        rs = sorted({names[int(tags[i])] for i in ow})
        L = float(np.hypot(*(np.asarray(P[u], dtype=np.float64)[:2] - np.asarray(P[v], dtype=np.float64)[:2])))
        if len(ow) == 2 and len(rs) == 2:
            inter["|".join(rs)] += L
        if len(ow) == 1:
            one_len[rs[0]] += L
    return {"edge_owner_count_histogram": {str(k): v for k, v in sorted(owners.items())},
            "interface_edge_length_by_region_pair": dict(inter), "boundary_edge_length_by_region": dict(one_len)}


def mesh_file_report(path, names):
    import meshio
    m = meshio.read(path)
    blk = next(c for c in m.cells if c.type == "triangle")
    tags = np.asarray(m.cell_data["Material"][m.cells.index(blk)]).reshape(-1)
    out = {"points_dtype": str(m.points.dtype), "points_shape": list(m.points.shape), "cell_blocks": [[c.type, int(len(c.data))] for c in m.cells],
           "tag_to_region": {str(k): v for k, v in names.items()}, "regions": {}}
    for tag, name in names.items():
        tt = blk.data[tags == tag]
        out["regions"][name] = {"triangles": int(len(tt)), "file_area": fr(exact_area(m.points, tt)), "shape": shape(m.points, tt)}
    out["topology"] = topology(m.points, blk.data, tags, names)
    return out, m.points, blk.data, tags


def parse_elements(elements):
    tris, lines, i = [], [], 0
    el = [int(v) for v in elements]
    while i < len(el):
        if el[i] == 2:
            tris.append(el[i + 1:i + 5])
            i += 5
        elif el[i] == 1:
            lines.append(el[i + 1:i + 4])
            i += 4
        else:
            raise ValueError(f"unknown element type {el[i]}")
    return np.array(tris, dtype=np.int64), np.array(lines, dtype=np.int64)


def diagnose(outd, label, path, import_kw, dv):
    import tcad.device.devsim.mesh_import as mi
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.device.devsim.mesh_conservation import MeshAreaConservationError
    pr = build_process_result({"final_mesh": path, "snapshots": []})
    names = {r.tag: r.name for r in pr.material_regions}
    rep = {"label": label, "file_sha256": ce.sha_file(path), "import_kwargs": import_kw}
    rep["file"], Pf, Tf, Gf = mesh_file_report(path, names)
    before = dict(CALLS)
    # (a) the production importer, unmodified
    try:
        d = mi.import_process_result(pr, mesh_name=f"r1_{label}_prod_mesh", device_name=f"r1_{label}_prod_device", **import_kw)
        rep["production"] = {"refused": False, "area_conservation": d.area_conservation}
        dv.delete_device(device=d.device)
        dv.delete_mesh(mesh=d.mesh)
    except MeshAreaConservationError as exc:
        rep["production"] = {"refused": True, "message": str(exc)[:600], "physics_status": exc.physics_status}
    rep["devices_after_production"] = list(dv.get_device_list())
    # (b) diagnostic bypass: capture create_gmsh_mesh input; read every region instead of refusing
    captured, recorded = {}, {}
    real_cgm, real_verify = dv.create_gmsh_mesh, mi.verify_device

    def cap(**kw):
        captured.update(kw)
        return real_cgm(**kw)

    def recorder(module, device, mesh, region_terms):
        for name in region_terms:
            g = lambda n: np.array(module.get_node_model_values(device=device, region=name, name=n), dtype=np.float64)  # noqa: E731
            recorded[name] = {"x": g("x"), "y": g("y"), "NodeVolume": g("NodeVolume"),
                              "el": np.array(module.get_element_node_list(device=device, region=name), dtype=np.int64),
                              "terms": region_terms[name]}
        return {"DIAGNOSTIC_BYPASS": "not certified"}
    dv.create_gmsh_mesh, mi.verify_device = cap, recorder
    try:
        d = mi.import_process_result(pr, mesh_name=f"r1_{label}_diag_mesh", device_name=f"r1_{label}_diag_device", **import_kw)
    finally:
        dv.create_gmsh_mesh, mi.verify_device = real_cgm, real_verify
    Pt = np.array(captured["coordinates"], dtype=np.float64).reshape(-1, 3)
    Tt, Lt = parse_elements(captured["elements"])
    pn = list(captured["physical_names"])
    scale = import_kw.get("length_scale_to_cm", 1.0)
    exp = (Pf * scale).astype(np.float64)
    rep["transfer"] = {"n_points": int(len(Pt)), "coordinates_equal_file_times_scale_as_importer_computes": bool(np.array_equal(Pt, exp)),
                       "file_dtype_times_scale_dtype": str((Pf * scale).dtype), "physical_names": pn,
                       "n_triangle_elements": int(len(Tt)), "n_line_elements": int(len(Lt)),
                       "triangles_equal_file": bool(np.array_equal(Tt[:, 1:], Tf)),
                       "triangle_physical_name_equals_file_region": bool(all(pn[int(i)] == names[int(g)] for i, g in zip(Tt[:, 0], Gf))),
                       "regions": {}}
    for tag, name in names.items():
        tt = Tf[Gf == tag]
        rep["transfer"]["regions"][name] = {"triangles": int(len(tt)), "transfer_area": fr(exact_area(Pt, tt))}
    # (c) readback per region, correspondence, F2 / F3
    rep["readback"] = {}
    key = {(float(x), float(y)): i for i, (x, y) in enumerate(Pt[:, :2])}
    for name, r in recorded.items():
        Pr = np.column_stack([r["x"], r["y"]])
        el = r["el"]
        glob = np.array([key.get((float(x), float(y)), -1) for x, y in Pr])
        tag = next(t for t, n in names.items() if n == name)
        src = np.sort(Tf[Gf == tag], axis=1)
        mapped = np.sort(glob[el], axis=1) if (glob >= 0).all() else None
        A_rb = exact_area(Pr, el)
        nv = r["NodeVolume"]
        f2 = fm.node_areas(Pr, el.tolist(), "F2")
        f3 = fm.node_areas(Pr, el.tolist(), "F3")
        per_tri_excess = []
        for ti, t in enumerate(el.tolist()):
            a2 = fm.per_triangle_node(Pr[t], "F2")
            a3 = fm.per_triangle_node(Pr[t], "F3")
            per_tri_excess.append(sum(a3) - sum(a2))
        per_tri_excess = np.array(per_tri_excess)
        ang = angles_deg(Pr, el)
        top = np.argsort(-per_tri_excess)[:5]
        S = float(nv.sum())
        rep["readback"][name] = {
            "nodes": int(len(Pr)), "elements": int(len(el)), "all_nodes_found_in_transfer": bool((glob >= 0).all()),
            "node_map_injective": bool(len(set(glob.tolist())) == len(glob)),
            "element_multiset_equals_source": bool(mapped is not None and len(mapped) == len(src) and np.array_equal(
                mapped[np.lexsort(mapped.T[::-1])], src[np.lexsort(src.T[::-1])])),
            "readback_area": fr(A_rb), "NodeVolume": {"min": float(nv.min()), "max": float(nv.max()), "sum": S},
            "S_over_readback_area_minus_1": S / float(A_rb) - 1.0,
            "gate_terms": {k: r["terms"][k] for k in ("area", "E_A", "E_NV")},
            "F2_sum": float(f2.sum()), "F3_sum": float(f3.sum()),
            "max_rel_NodeVolume_minus_F3": float(np.max(np.abs(nv - f3) / np.maximum(np.abs(f3), 1e-300))),
            "max_rel_NodeVolume_minus_F2": float(np.max(np.abs(nv - f2) / np.maximum(np.abs(f2), 1e-300))),
            "n_nodes_F2_negative": int((f2 < 0).sum()),
            "excess_F3_minus_F2_total": float(per_tri_excess.sum()), "n_triangles_with_excess": int((per_tri_excess > 0).sum()),
            "top_excess_triangles": [{"coords": Pr[el[i]].tolist(), "angles_deg": ang[i].tolist(), "area": float(fm.tri_area(Pr[el[i]])),
                                      "excess": float(per_tri_excess[i])} for i in top],
            "shape": shape(Pr, el)}
    rep["devsim_write_calls_during_diagnosis"] = {k: CALLS[k] - before.get(k, 0) for k in WRITE_APIS}
    dv.delete_device(device=d.device)
    dv.delete_mesh(mesh=d.mesh)
    rep["devices_after_diagnosis"] = list(dv.get_device_list())
    return rep


def build_A(tmp):
    import tcad.process.etching  # noqa: F401
    from tcad.process import registry
    recipe = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "mask_left_um": 1.5, "mask_right_um": 2.5,
              "pr_thickness_um": 0.5, "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask"}
    res = registry.get("etching", "isotropic")().run(recipe, tmp)
    return [("A", res["final_mesh"], {"contact_regions": ["Si"], "contact_axis": "x"})], {"recipe": recipe}


def build_B(tmp):
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import refine_process_result_for_implant_windows
    app = gui.TCADApplication()
    app.withdraw()
    try:
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer(), "materializing the real ViennaPS wafer failed"
        raw = os.path.join(tmp, "B_raw.vtu")
        shutil.copy(app.last_final_mesh, raw)
        spans = {"src": [float(app.dope_win_src_min_var.get()), float(app.dope_win_src_max_var.get())],
                 "drn": [float(app.dope_win_drn_min_var.get()), float(app.dope_win_drn_max_var.get())]}
        pr = build_process_result({"final_mesh": raw, "snapshots": []})
        wr = apply_implant_windows_doping(
            pr, region="Si", axis="x", donor_background_cm3=1e16, acceptor_background_cm3=0.0,
            windows=[{"min_um": spans["src"][0], "max_um": spans["src"][1], "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0},
                     {"min_um": spans["drn"][0], "max_um": spans["drn"][1], "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0}],
            chemical_state="ACTIVE")
        ref = refine_process_result_for_implant_windows(wr)
        kw = {"contact_regions": ["Si"], "contact_axis": "x", "length_scale_to_cm": 1.0e-4}
        return [("B_raw", raw, kw), ("B_refined", ref.volume_mesh_path, kw)], {"gui": {"width_um": 4.0, "silicon_depth_um": 1.0,
                                                                                    "grid_delta_um": 0.2}, "window_spans_um": spans}
    finally:
        app.destroy()


def refinement_compare(file_reports, raw_path, ref_path):
    import meshio
    out = {}
    ms = {k: meshio.read(p) for k, p in (("raw", raw_path), ("refined", ref_path))}
    rows = {}
    for k, m in ms.items():
        blk = next(c for c in m.cells if c.type == "triangle")
        P = np.asarray(m.points, dtype=np.float64)[:, :2]
        rows[k] = collections.Counter(tuple(sorted(map(tuple, np.round(P[t], 15).tolist()))) for t in blk.data.tolist())
        out[f"{k}_points"] = int(len(m.points))
    out["triangles_removed"] = int(sum((rows["raw"] - rows["refined"]).values()))
    out["triangles_added"] = int(sum((rows["refined"] - rows["raw"]).values()))
    out["regions"] = {n: {"raw": file_reports["raw"]["regions"][n]["file_area"], "refined": file_reports["refined"]["regions"][n]["file_area"],
                          "triangles": [file_reports["raw"]["regions"][n]["triangles"], file_reports["refined"]["regions"][n]["triangles"]]}
                      for n in file_reports["raw"]["regions"]}
    out["boundary_and_interface_lengths"] = {"raw": file_reports["raw"]["topology"], "refined": file_reports["refined"]["topology"]}
    return out


def main():
    outd, which = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(outd, exist_ok=True)
    import devsim as dv
    for k in WRITE_APIS:
        real = getattr(dv, k)

        def trap(*a, _k=k, **kw):
            CALLS[_k] += 1
            raise RuntimeError(f"E6E-R1 diagnosis forbids devsim.{_k}")
        setattr(dv, k, trap)
    res = {"which": which, "process_id": os.getpid(), "reports": {}}
    try:
        tmp = tempfile.mkdtemp(prefix=f"r1_{which}_")
        meshes, res["recipe"] = (build_A if which == "A" else build_B)(tmp)
        for label, path, kw in meshes:
            dst = os.path.join(outd, f"{label}.vtu")
            shutil.copy(path, dst)
            res["reports"][label] = diagnose(outd, label, dst, kw, dv)
        if which == "B":
            res["refinement"] = refinement_compare({"raw": res["reports"]["B_raw"]["file"], "refined": res["reports"]["B_refined"]["file"]},
                                                   os.path.join(outd, "B_raw.vtu"), os.path.join(outd, "B_refined.vtu"))
        res["status"] = "OK"
    except Exception as e:  # noqa: BLE001
        res["status"] = "ERROR"
        res["error"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:600]
        res["traceback"] = ce.USER_PATH.sub("<USERPROFILE>", traceback.format_exc()[-4000:])
    res["write_calls_total"] = dict(CALLS)
    res["devices_left"] = list(dv.get_device_list())
    ce.dump_strict(res, os.path.join(outd, f"diag_{which}.json"))
    print(json.dumps({"which": which, "status": res["status"], "error": res.get("error"), "calls": dict(CALLS)}), flush=True)
    return 0 if res["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
