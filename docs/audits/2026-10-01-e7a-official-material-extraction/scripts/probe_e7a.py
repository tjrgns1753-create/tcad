"""E7A probe (AUDIT-ONLY, GitHub-hosted runner only). usage: probe_e7a.py <out_dir> <case> <route> [epsilon]
cases: A B1 B2 C CN ; routes: R0 R0d R1 R2 R3 ; or:  probe_e7a.py <out_dir> P0 P0
Criteria: ../CRITERIA.md. Nothing here modifies tcad/, tests/ or the engines. vps.Oxidation / vps.Process are trapped (never called)."""
import json
import math
import os
import sys
import tempfile
import traceback
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

import numpy as np  # noqa: E402

X_EXTENT, Y_EXTENT, DEPTH = 2.0, 2.0, 1.0
CASES = {"A": dict(grid=0.05, pad=0.30, mask=False), "B1": dict(grid=0.05, pad=0.10, mask=False), "B2": dict(grid=0.10, pad=0.10, mask=False),
         "C": dict(grid=0.05, pad=0.10, mask=True), "CN": dict(grid=0.05, pad=0.10, mask=True)}


def analytic(case):
    p = CASES[case]
    boxes = {"Si": [(-1.0, 1.0, -DEPTH, 0.0)], "SiO2": [(-1.0, 1.0, 0.0, p["pad"])]}
    if p["mask"]:
        boxes["Mask"] = [(-1.0, -0.5, p["pad"], p["pad"] + 0.3), (0.5, 1.0, p["pad"], p["pad"] + 0.3)]
    return boxes


def tag_name(module, tag):
    return str(module.Material(int(tag))).split("'")[1]


def tri_area(p, t):
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    return np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])) / 2.0


def column_extent(pts, tri, mask, x0):
    sel = tri[mask]
    if len(sel) == 0:
        return None
    xs = pts[sel][:, :, 0]
    keep = (xs.min(axis=1) <= x0) & (xs.max(axis=1) >= x0)
    ys = []
    for t in sel[keep]:
        v = pts[t]
        for i in range(3):
            (xa, ya), (xb, yb) = v[i], v[(i + 1) % 3]
            if xa == xb:
                if xa == x0:
                    ys += [ya, yb]
            elif (xa - x0) * (xb - x0) <= 0:
                ys.append(ya + (x0 - xa) / (xb - xa) * (yb - ya))
    return [float(min(ys)), float(max(ys))] if ys else None


def measure_mesh(module, pts, tri, tags, case, floored):
    p = CASES[case]
    gd = p["grid"]
    delta = 0.02 * gd + 1e-6
    boxes = analytic(case)
    names = {int(t): tag_name(module, t) for t in np.unique(tags)}
    area_all = tri_area(pts, tri)
    out = {"n_points": int(len(pts)), "n_triangles": int(len(tri)), "delta_um": delta, "materials": {}, "columns": {}, "judgement": {}}
    for t, n in names.items():
        m = tags == t
        used = np.unique(tri[m])
        out["materials"][n] = {"tag": t, "n_triangles": int(m.sum()), "area": float(area_all[m].sum()),
                               "y_range": [float(pts[used, 1].min()), float(pts[used, 1].max())],
                               "x_range": [float(pts[used, 0].min()), float(pts[used, 0].max())]}
    expected_set = set(boxes)
    J = out["judgement"]
    J["1_materials_set_equals_expected"] = set(names.values()) == expected_set and all(v["n_triangles"] > 0 for v in out["materials"].values())
    J["1_missing"] = sorted(expected_set - set(names.values()))
    J["1_unexpected"] = sorted(set(names.values()) - expected_set)
    # 2 area
    area_ok, area_detail = True, {}
    for n, bs in boxes.items():
        exp = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in bs)
        per = sum(2 * ((x1 - x0) + (y1 - y0)) for x0, x1, y0, y1 in bs)
        got = out["materials"].get(n, {}).get("area", 0.0)
        tol = per * delta
        judged = not (n == "Si" and not floored)
        ok = abs(got - exp) <= tol
        area_detail[n] = {"analytic": exp, "measured": got, "abs_err": got - exp, "tol": tol, "judged": judged, "ok": ok}
        if judged:
            area_ok = area_ok and ok
    J["2_area_ok"], J["2_area_detail"] = area_ok, area_detail
    # 3/4 columns
    xs = [0.0, 0.8, -0.8] + ([0.45, 0.55, -0.45, -0.55] if p["mask"] else [])
    pos_ok, col_ok = True, True
    for x0 in xs:
        exp_cols = {}
        for n, bs in boxes.items():
            hit = [(y0, y1) for (bx0, bx1, y0, y1) in bs if bx0 <= x0 <= bx1]
            exp_cols[n] = [min(h[0] for h in hit), max(h[1] for h in hit)] if hit else None
        got_cols = {n: column_extent(pts, tri, tags == t, x0) for t, n in names.items()}
        rec = {"expected": exp_cols, "measured": got_cols, "position_ok": True}
        for n, e in exp_cols.items():
            g = got_cols.get(n)
            if n == "Si" and not floored:
                if g is None or abs(g[1] - e[1]) > delta:
                    rec["position_ok"] = False
                continue
            if e is None:
                if g is not None:
                    rec["position_ok"] = False
            elif g is None or abs(g[0] - e[0]) > delta or abs(g[1] - e[1]) > delta:
                rec["position_ok"] = False
        # consistency: contiguous, non-overlapping in this column
        segs = sorted((v for v in got_cols.values() if v is not None), key=lambda s: s[0])
        cons = all(b[0] - a[1] >= -delta and b[0] - a[1] <= delta for a, b in zip(segs[:-1], segs[1:]))
        rec["consistent"] = bool(cons)
        out["columns"][str(x0)] = rec
        pos_ok = pos_ok and rec["position_ok"]
        col_ok = col_ok and rec["consistent"]
    J["3_positions_ok"], J["4_columns_consistent"] = pos_ok, col_ok
    # 5 connectivity (index-based as written, and coordinate-based)
    own = defaultdict(set)
    own_c = defaultdict(set)
    key = lambda i: (round(float(pts[i][0]), 9), round(float(pts[i][1]), 9))  # noqa: E731
    for t, tag in zip(tri, tags):
        for i in range(3):
            a, b = int(t[i]), int(t[(i + 1) % 3])
            own[tuple(sorted((a, b)))].add(int(tag))
            own_c[tuple(sorted((key(a), key(b))))].add(int(tag))
    def pairs(o):
        r = defaultdict(int)
        for v in o.values():
            if len(v) == 2:
                a, b = sorted(names[x] for x in v)
                r[f"{a}|{b}"] += 1
        return dict(r)
    rounded = {key(i) for i in range(len(pts))}
    J["5_shared_edges_by_index"] = pairs(own)
    J["5_shared_edges_by_coordinate"] = pairs(own_c)
    J["5_duplicate_coordinate_points"] = int(len(pts) - len(rounded))
    return out


def load_mesh(path):
    import meshio
    m = meshio.read(str(path))
    block = next(c for c in m.cells if c.type == "triangle")
    idx = m.cells.index(block)
    return np.asarray(m.points)[:, :2], np.asarray(block.data), np.asarray(m.cell_data["Material"][idx]).astype(int)


def build(case, module):
    from tcad.backends.viennaps import session
    from _explicit_oxide_fixture import forbid_oxidation_and_process
    p = CASES[case]
    info = {"grid": p["grid"], "pad": p["pad"], "x_extent": X_EXTENT, "y_extent": Y_EXTENT}
    with forbid_oxidation_and_process(module) as counts:
        if not p["mask"]:
            domain = session.create_domain(p["grid"], X_EXTENT, Y_EXTENT)
            module.MakePlane(domain, 0.0, module.Material.Si).apply()
            module.MakePlane(domain, p["pad"], module.Material.SiO2, True).apply()
            mats, flags = [module.Material.Si, module.Material.SiO2], [False, True]
        else:
            from tcad.process.oxidation.locos import LocosOxidation
            recipe = {"grid_delta_um": p["grid"], "x_extent_um": X_EXTENT, "y_extent_um": Y_EXTENT, "mask_left_um": 0.5, "mask_right_um": 1.5,
                      "pr_thickness_um": 0.3, "mask_material": "Mask", "pad_oxide_thickness_um": p["pad"], "silicon_depth_um": DEPTH}
            step = LocosOxidation()
            domain, mats, flags = step._build_locos_geometry(recipe, module)
            if case == "CN":
                domain = domain.__class__(domain)
                step._make_locos_domain_chainable(domain, mats, list(flags))
                flags = list(flags[:-1]) + [True]
    info["forbidden_call_counts"] = dict(counts)
    info["materials_by_index"] = [str(m).split("'")[1] for m in mats]
    info["wrap_flags"] = list(flags)
    return domain, mats, flags, info


def native_summary(domain):
    import viennals as vls
    out = []
    for ls in domain.getLevelSets():
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(ls, mesh).apply()
        nodes = np.array(mesh.getNodes())
        out.append({"n_points": int(ls.getNumberOfPoints()), "surface_y": [float(nodes[:, 1].min()), float(nodes[:, 1].max())] if len(nodes) else None})
    return out


def write_merged(parts, path):
    import meshio
    pts, tris, tags = [], [], []
    for material, p, t in parts:
        off = len(pts)
        pts += [[float(a[0]), float(a[1]), 0.0] for a in p]
        tris += [[int(i) + off for i in tri] for tri in t]
        tags += [int(material)] * len(t)
    meshio.write(str(path), meshio.Mesh(np.array(pts) if pts else np.zeros((0, 3)), [("triangle", np.array(tris) if tris else np.zeros((0, 3), dtype=int))],
                                        cell_data={"Material": [np.array(tags, dtype=int)]}))
    return str(path)


def route(out, case, rt, eps, module, domain, mats, flags, work):
    from tcad.backends.viennaps import io as vio
    if rt in ("R0", "R0d"):
        dedupe = list(mats) if rt == "R0d" else None
        path = vio.save_locos_volume_mesh(domain, mats, flags, str(Path(work) / f"{case}_{rt}"), floor_depth_um=DEPTH, dedupe_materials=dedupe)
        pts, tri, tags = load_mesh(path)
        out["measure"] = measure_mesh(module, pts, tri, tags, case, floored=True)
        out["mesh"] = path
    elif rt == "R1":
        base = str(Path(work) / f"{case}_R1_eps{eps}")
        if eps is None:
            domain.saveVolumeMesh(base)
        else:
            domain.saveVolumeMesh(base, eps)
        path = base + "_volume.vtu"
        pts, tri, tags = load_mesh(path)
        out["measure"] = measure_mesh(module, pts, tri, tags, case, floored=False)
        out["mesh"] = path
        out["epsilon"] = eps if eps is not None else "default(0.01)"
    elif rt == "R2":
        xmin, xmax, _ymin, ymax = vio._union_bounding_box(domain)
        parts, per_material = [], {}
        for m in sorted(domain.getMaterialsInDomain(), key=int):
            name = tag_name(module, int(m))
            print(f"### getMaterialLevelSet({name})", flush=True)
            ls = domain.getMaterialLevelSet(m)
            n = None if ls is None else int(ls.getNumberOfPoints())
            rec = {"level_set_points": n}
            if n:
                import viennals as vls
                mesh = vls.Mesh()
                vls.ToSurfaceMesh(ls, mesh).apply()
                nodes = np.array(mesh.getNodes())
                rec["surface_bbox"] = [nodes.min(axis=0).tolist(), nodes.max(axis=0).tolist()] if len(nodes) else None
                p_, t_ = vio._export_single_level_set(domain, ls, m, DEPTH, bounds_hint=(xmin, xmax, ymax))
                rec["exported_triangles"] = int(len(t_))
                parts.append((int(m), p_, t_))
            per_material[name] = rec
        out["per_material"] = per_material
        if parts:
            path = write_merged(parts, Path(work) / f"{case}_R2.vtu")
            pts, tri, tags = load_mesh(path)
            out["measure"] = measure_mesh(module, pts, tri, tags, case, floored=True)
            out["mesh"] = path
        else:
            out["measure"] = None
    elif rt == "R3":
        mesh = domain.getSurfaceMesh(True)
        nodes = np.array(mesh.getNodes())
        lines = [list(l) for l in mesh.getLines()]
        rec = {"n_nodes": int(len(nodes)), "n_lines": len(lines)}
        try:
            cd = mesh.getCellData()
            rec["cell_data_attrs"] = [a for a in dir(cd) if not a.startswith("_")]
            names = cd.getScalarDataNames() if hasattr(cd, "getScalarDataNames") else None
            rec["cell_scalar_names"] = list(names) if names is not None else None
        except Exception as exc:  # noqa: BLE001
            rec["cell_data_error"] = repr(exc)
        p = CASES[case]
        xs = [0.0, 0.8, -0.8] + ([0.45, 0.55, -0.45, -0.55] if p["mask"] else [])
        cols = {}
        for x0 in xs:
            ys = []
            for a, b in lines:
                (xa, ya), (xb, yb) = nodes[a][:2], nodes[b][:2]
                if xa == xb:
                    if xa == x0:
                        ys += [float(ya), float(yb)]
                elif (xa - x0) * (xb - x0) <= 0:
                    ys.append(float(ya + (x0 - xa) / (xb - xa) * (yb - ya)))
            cols[str(x0)] = sorted(set(round(y, 6) for y in ys))
        rec["boundary_y_by_column"] = cols
        out["surface_mesh"] = rec


def p0_control(out, module):
    import viennals as vls
    from tcad.backends.viennaps import session
    res = {}

    def count(ls):
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(ls, mesh).apply()
        nodes = np.array(mesh.getNodes())
        return {"points": int(ls.getNumberOfPoints()), "surface_y_range": [float(nodes[:, 1].min()), float(nodes[:, 1].max())] if len(nodes) else None}
    gd = 0.05
    d1 = session.create_domain(gd, X_EXTENT, Y_EXTENT)
    module.MakePlane(d1, 0.5, module.Material.Si).apply()
    d2 = session.create_domain(gd, X_EXTENT, Y_EXTENT)
    module.MakePlane(d2, 0.0, module.Material.Si).apply()
    a = vls.Domain(d1.getLevelSets()[0])
    vls.BooleanOperation(a, d2.getLevelSets()[0], vls.BooleanOperationEnum.RELATIVE_COMPLEMENT).apply()
    res["independent_planes_y<0.5_minus_y<0.0"] = count(a)
    d3 = session.create_domain(gd, X_EXTENT, Y_EXTENT)
    module.MakePlane(d3, 0.0, module.Material.Si).apply()
    module.MakePlane(d3, 0.5, module.Material.SiO2, True).apply()   # second level set = UNION(plane 0.5, Si)
    top, bottom = d3.getLevelSets()[1], d3.getLevelSets()[0]
    b = vls.Domain(top)
    vls.BooleanOperation(b, bottom, vls.BooleanOperationEnum.RELATIVE_COMPLEMENT).apply()
    res["wrapped_top_minus_bottom_manual"] = count(b)
    print("### getMaterialLevelSet(SiO2) on the wrapped two-layer domain", flush=True)
    ls = d3.getMaterialLevelSet(module.Material.SiO2)
    res["wrapped_getMaterialLevelSet_SiO2"] = count(ls) if ls is not None and ls.getNumberOfPoints() else {"points": 0 if ls is not None else None}
    print("### getMaterialLevelSet(Si) on the wrapped two-layer domain", flush=True)
    ls = d3.getMaterialLevelSet(module.Material.Si)
    res["wrapped_getMaterialLevelSet_Si"] = count(ls) if ls is not None and ls.getNumberOfPoints() else {"points": 0 if ls is not None else None}
    out["control"] = res


def main():
    out_dir, case, rt = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    eps = float(sys.argv[4]) if len(sys.argv) > 4 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{case}_{rt}" + (f"_eps{eps}" if eps is not None else "")
    out = {"case": case, "route": rt, "epsilon": eps, "status": None}
    work = tempfile.mkdtemp(prefix="e7a_")
    try:
        from tcad.backends.viennaps import session
        module = session.require_viennaps()
        out["versions"] = {"viennaps": getattr(module, "__version__", None)}
        if case == "P0":
            p0_control(out, module)
        else:
            domain, mats, flags, info = build(case, module)
            out["input"] = info
            out["native_level_sets"] = native_summary(domain)
            route(out, case, rt, eps, module, domain, mats, flags, work)
        out["status"] = "OK"
    except Exception as exc:  # noqa: BLE001
        out["status"] = "EXCEPTION"
        out["error"] = repr(exc)[:600]
        out["traceback"] = traceback.format_exc()[-3000:]
    if out.get("mesh"):
        import shutil
        dst = out_dir / (tag + ".vtu")
        shutil.copy(out["mesh"], dst)
        out["mesh"] = dst.name
    with open(out_dir / (tag + ".json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps({k: out.get(k) for k in ("case", "route", "status", "error")}), flush=True)


if __name__ == "__main__":
    main()
