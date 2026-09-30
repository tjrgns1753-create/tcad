"""Batch 7H-E6G local evaluation (pure; no DEVSIM). Cases A-G of CRITERIA.md plus a node/triangle order control.
Exact checks reuse the E6F evaluator (eval2_e6f.geometry / boundary_preserved); target resolution is checked exactly against the
request; the old production module (E6F refine_old.py, byte copy) gives the comparison sizes. JSON is rewritten after every case.
usage: eval_e6g.py <out json>"""
import json
import os
import sys
import tempfile
import time
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
E6F = os.path.join(ROOT, "docs", "audits", "2026-10-01-batch7h-e6f-quality-closure", "scripts")
sys.path.insert(0, ROOT)
sys.path.insert(0, E6F)
import eval2_e6f as ev  # noqa: E402  (E6F, read-only: exact geometry and boundary checks)
import refine_old  # noqa: E402  (byte copy of production mesh_refine.py at 0ef6dd2)
from tcad.device.devsim import mesh_refine as mr  # noqa: E402

B_RAW = os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu")
WAFER = os.path.join(ROOT, "docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/wafer_volume.vtu")


def grid(xs, ys, split=None, dtype=np.float64):
    nx = len(xs) - 1
    pts = np.array([[x, y, 0.0] for y in ys for x in xs], dtype=dtype)
    tris, tags = [], []
    for j in range(len(ys) - 1):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
            tags += [10 if split is None or i < split else 11] * 2
    return pts, np.array(tris), np.array(tags, dtype=np.int32)


def resolution(P, T, P0, centers, rings):
    """Every output triangle whose centroid lies in ring k's band has exact x- and y-extent <= its original cell's / 2^(k+1)."""
    P, P0 = np.asarray(P, np.float64), np.asarray(P0, np.float64)
    xs, ys = np.unique(P0[:, 0]), np.unique(P0[:, 1])
    bad = checked = 0
    for t in np.asarray(T).tolist():
        q = P[t, :2]
        cx = float(q[:, 0].mean())
        need = max([k + 1 for k, hw in enumerate(rings) if any(abs(cx - c) < hw for c in centers)] or [0])
        if need == 0:
            continue
        checked += 1
        i = min(max(int(np.searchsorted(xs, cx)) - 1, 0), len(xs) - 2)
        j = min(max(int(np.searchsorted(ys, float(q[:, 1].mean()))) - 1, 0), len(ys) - 2)
        F = Fraction
        ex = F(float(q[:, 0].max())) - F(float(q[:, 0].min()))
        ey = F(float(q[:, 1].max())) - F(float(q[:, 1].min()))
        if ex > (F(float(xs[i + 1])) - F(float(xs[i]))) / 2 ** need or ey > (F(float(ys[j + 1])) - F(float(ys[j]))) / 2 ** need:
            bad += 1
    return {"triangles_in_bands": checked, "violations": bad, "ok": bad == 0 and checked > 0}


def old_sizes(P, T, G, centers, rings):
    preds = [lambda c, hw=hw: any(abs(c[0] - x) < hw for x in centers) for hw in rings]
    for p in preds:
        P, T, G = refine_old.refine_mesh_near(P, T, G, p, levels=1)
    return P, T, G


def canon(P, T, G):
    return ev.canon(P, T, G)


def run_case(label, P0, T0, G0, centers, rings, exact=True, out=None):
    rec = {"input_triangles": int(len(T0)), "input_points": int(len(P0)), "centers": list(centers), "rings": list(rings)}
    t = time.time()
    try:
        P, T, G, rep = mr.structured_lateral_refine(P0, T0, G0, centers, rings)
    except (mr.StructuredRemeshUnsupported, mr.StructuredRemeshAborted) as e:
        rec.update({"refused": type(e).__name__, "reason": e.reason, "detail": str(e)[:300], "generation_s": round(time.time() - t, 3)})
        return rec, None
    rec["generation_s"] = round(time.time() - t, 3)
    rec["report"] = rep
    Po, To, Go = old_sizes(P0, T0, G0, centers, rings)
    rec["old_triangles"] = int(len(To))
    t = time.time()
    rec["resolution"] = resolution(P, T, P0, centers, rings)
    rec["old_resolution_same_check"] = resolution(Po, To, P0, centers, rings)
    rec["resolution_s"] = round(time.time() - t, 3)
    if exact:
        t = time.time()
        rec["geometry"] = ev.geometry(P, T, G, P0, T0, G0)
        rec["geometry_s"] = round(time.time() - t, 3)
    else:
        rec["geometry"] = "NOT_VERIFIED (skipped for size)"
    t = time.time()
    rec["boundary"] = ev.boundary_preserved(P0, T0, G0, P, T, G)
    rec["boundary_s"] = round(time.time() - t, 3)
    return rec, (P, T, G)


def exact_obtuse_area_only(P, T, G, P0, T0, G0):
    P, P0 = np.asarray(P, np.float64), np.asarray(P0, np.float64)
    X, Y = ev.fr(P)
    X0, Y0 = ev.fr(P0)
    obt = deg = 0
    sgn = set()
    area = Fraction(0)
    for a, b, c in np.asarray(T).tolist():
        o = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        deg += o == 0
        sgn.add(o > 0)
        area += abs(o) / 2
        if any((X[u] - X[w]) * (X[v] - X[w]) + (Y[u] - Y[w]) * (Y[v] - Y[w]) < 0 for w, u, v in ((a, b, c), (b, c, a), (c, a, b))):
            obt += 1
    area0 = sum((abs((X0[b] - X0[a]) * (Y0[c] - Y0[a]) - (Y0[b] - Y0[a]) * (X0[c] - X0[a])) / 2 for a, b, c in np.asarray(T0).tolist()), Fraction(0))
    s = np.sort(np.asarray(T), axis=1)
    return {"obtuse": obt, "degenerate": deg, "single_orientation": len(sgn) == 1, "area_equal_input": area == area0,
            "duplicate_triangles": int(len(s) - len(np.unique(s, axis=0))),
            "existing_nodes_preserved": bool(np.array_equal(P[:len(P0), :2], P0[:, :2])), "hanging_nodes": "NOT_VERIFIED (skipped for size)"}


def production(path, kind):
    """The production caller with a pure ProcessResult (no ViennaPS): returns (refined arrays, request)."""
    import meshio
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import implant_windows_lateral_request, refine_process_result_for_implant_windows
    m = meshio.read(path)
    P0, T0, G0 = m.points, m.cells[0].data, m.cell_data["Material"][0]
    pr = ProcessResult(volume_mesh_path=path, material_field="Material", material_regions=[MaterialRegion(name="Si", tag=int(G0[0]))])
    if kind == "1e16":
        bg, win = (1e16, 0.0), 1e16
    else:
        bg, win = (0.0, 1e17), 1e20
    wr = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=bg[0], acceptor_background_cm3=bg[1],
                                      windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": win, "acceptor_conc_cm3": 0.0},
                                               {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": win, "acceptor_conc_cm3": 0.0}],
                                      chemical_state="ACTIVE")
    req = implant_windows_lateral_request(wr.doping, P0, T0)
    outp = os.path.join(tempfile.mkdtemp(prefix="e6g_"), "refined.vtu")
    t = time.time()
    ref = refine_process_result_for_implant_windows(wr, refined_mesh_path=outp)
    wall = time.time() - t
    r = meshio.read(ref.volume_mesh_path)
    return (P0, T0, G0), (r.points, r.cells[0].data, r.cell_data["Material"][0]), req, wall, [c.type for c in r.cells]


def main():
    out_path = sys.argv[1]
    out = {"mesh_refine_lf_sha256": __import__("hashlib").sha256(open(os.path.join(ROOT, "tcad/device/devsim/mesh_refine.py"), "rb").read()
                                                                 .replace(b"\r\n", b"\n")).hexdigest(), "cases": {}}

    def save(label, rec):
        out["cases"][label] = rec
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1)
        print(label, json.dumps(rec)[:900], flush=True)

    # A: the green-split counterexample geometry (2 x 1 unit cells), band on the left cell
    P, T, G = grid([0.0, 1.0, 2.0], [0.0, 1.0])
    rec, _ = run_case("A", P, T, G, [0.5], [0.5])
    save("A_counterexample_2cells", rec)
    # B: uniform 10 x 10 grid, local window, 3 rings
    P, T, G = grid([float(i) for i in range(11)], [float(j) for j in range(11)])
    rec, resB = run_case("B", P, T, G, [5.0], [1.0, 0.5, 0.25])
    save("B_uniform_local_window", rec)
    # order control on B: permute nodes and triangles, rotate each triangle's vertex order
    rng = np.random.default_rng(12345)
    perm = rng.permutation(len(P))
    inv = np.argsort(perm)
    Pp = P[perm]
    Tp = inv[T][rng.permutation(len(T))]
    Tp = np.roll(Tp, 1, axis=1)
    Gp = np.full(len(Tp), 10, dtype=np.int32)
    recp, resBp = run_case("B_perm", Pp, Tp, Gp, [5.0], [1.0, 0.5, 0.25], exact=False)
    recp["same_canonical_output_as_B"] = bool(resB is not None and resBp is not None and canon(*resB) == canon(*resBp))
    save("B_order_control", recp)
    # C: float32 coordinates, slightly anisotropic cells (dy = 0.2 * (1 + 1e-3)), center on a grid line
    xs = [float(np.float32(0.2 * i)) for i in range(16)]
    ys = [float(np.float32(0.2 * (1 + 1e-3) * j)) for j in range(6)]
    P, T, G = grid(xs, ys, dtype=np.float32)
    rec, _ = run_case("C", P, T, G, [float(np.float32(1.4))], [0.2, 0.1, 0.05])
    save("C_float32_anisotropic", rec)
    # D: shifted center (not on a grid line) and two separate windows
    P, T, G = grid([float(i) * 0.5 for i in range(17)], [float(j) * 0.5 for j in range(5)])
    rec, _ = run_case("D1", P, T, G, [3.13], [0.5, 0.25])
    save("D_shifted_center", rec)
    rec, _ = run_case("D2", P, T, G, [1.6, 6.3], [0.5, 0.25, 0.125])
    save("D_two_separate_windows", rec)
    # E, F: production caller on the committed raw meshes
    for label, path, kind, exact in (("E_B_raw_1e16", B_RAW, "1e16", True), ("F_gui_wafer_1e20", WAFER, "1e20", False)):
        (P0, T0, G0), (P, T, G), req, wall, blocks = production(path, kind)
        rec = {"request": req, "production_wall_s": round(wall, 2), "output_blocks": blocks, "input_triangles": int(len(T0)),
               "output_triangles": int(len(T)), "output_points": int(len(P)), "output_dtype": str(P.dtype)}
        Po, To, Go = old_sizes(P0, T0, G0, req["centers"], req["rings"])
        rec["old_triangles"] = int(len(To))
        t = time.time()
        rec["resolution"] = resolution(P, T, P0, req["centers"], req["rings"])
        rec["old_resolution_same_check"] = resolution(Po, To, P0, req["centers"], req["rings"])
        rec["resolution_s"] = round(time.time() - t, 2)
        t = time.time()
        rec["geometry"] = ev.geometry(P, T, G, P0, T0, G0) if exact else exact_obtuse_area_only(P, T, G, P0, T0, G0)
        rec["geometry_s"] = round(time.time() - t, 2)
        t = time.time()
        rec["boundary"] = ev.boundary_preserved(P0, T0, G0, P, T, G)
        rec["boundary_s"] = round(time.time() - t, 2)
        save(label, rec)
    # G: refusals
    P, T, G = grid([float(i) for i in range(6)], [float(j) for j in range(4)], split=3)
    save("G_two_materials", run_case("G1", P, T, G, [2.5], [0.5])[0])
    P, T, G = grid([float(i) for i in range(6)], [float(j) for j in range(4)])
    save("G_missing_triangle", run_case("G2", P, T[1:], G[1:], [2.5], [0.5])[0])
    keep = [k for k, t in enumerate(T.tolist()) if not (P[t, 0].max() <= 1.0 and P[t, 1].max() <= 1.0)]
    used = sorted(set(T[keep].ravel().tolist()))
    remap = {v: n for n, v in enumerate(used)}
    save("G_non_rectangular_notch", run_case("G3", P[used], np.array([[remap[v] for v in t] for t in T[keep].tolist()]), G[keep], [2.5], [0.5])[0])
    Pz = P.copy()
    Pz[0, 2] = 1e-3
    save("G_non_planar", run_case("G4", Pz, T, G, [2.5], [0.5])[0])
    P, T, G = grid([0.1 * i for i in range(11)], [float(j) for j in range(3)])
    save("G_transition_aspect_fails", run_case("G5", P, T, G, [0.5], [0.1])[0])
    # G: production decisions that keep the existing graded path (y axis, interface rings) -- output not built by the new builder
    import meshio
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import refine_process_result_for_implant_windows
    m = meshio.read(B_RAW)
    pr = ProcessResult(volume_mesh_path=B_RAW, material_field="Material", material_regions=[MaterialRegion(name="Si", tag=10)])
    for label, axis, iface in (("G_production_y_axis_keeps_graded", "y", None), ("G_production_interface_keeps_graded", "x", 0.0)):
        wr = apply_implant_windows_doping(pr, region="Si", axis=axis, donor_background_cm3=1e16, acceptor_background_cm3=0.0,
                                          windows=[{"min_um": -0.8, "max_um": -0.4, "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0}],
                                          chemical_state="ACTIVE")
        outp = os.path.join(tempfile.mkdtemp(prefix="e6g_"), "r.vtu")
        ref = refine_process_result_for_implant_windows(wr, refined_mesh_path=outp, interface_position_um=iface)
        r = meshio.read(ref.volume_mesh_path)
        obt = sum(not mr_ok(r.points, t) for t in r.cells[0].data.tolist())
        save(label, {"output_triangles": int(len(r.cells[0].data)), "output_obtuse": obt,
                     "note": "graded (old) path kept for an input outside the structured scope; the importer's area gate then decides"})


def mr_ok(P, t):
    X, Y = [Fraction(float(P[v, 0])) for v in t], [Fraction(float(P[v, 1])) for v in t]
    return all((X[(k + 1) % 3] - X[k]) * (X[(k + 2) % 3] - X[k]) + (Y[(k + 1) % 3] - Y[k]) * (Y[(k + 2) % 3] - Y[k]) >= 0 for k in range(3))


if __name__ == "__main__":
    main()
