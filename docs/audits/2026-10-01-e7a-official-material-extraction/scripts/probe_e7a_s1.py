"""E7A supplement S1 probe (AUDIT-ONLY, runner only). usage: probe_e7a_s1.py <out_dir> <case> <route: R4|R5>. See ../S1_CRITERIA.md."""
import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numpy as np  # noqa: E402
import probe_e7a as P  # noqa: E402


def meshio_stats(path, module, case):
    pts, tri, tags = P.load_mesh(path)
    return P.measure_mesh(module, pts, tri, tags, case, floored=False)


def main():
    out_dir, case, rt = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {"case": case, "route": rt, "status": None}
    work = tempfile.mkdtemp(prefix="e7a_s1_")
    try:
        from tcad.backends.viennaps import io as vio, session
        import viennals as vls
        module = session.require_viennaps()
        domain, mats, flags, info = P.build(case, module)
        out["input"] = info
        if rt == "R7":
            # S1c: is the thin-slab emptiness tied to UNION or to thickness? independent (never unioned) planes vs the wrapped stack, same thicknesses
            from tcad.backends.viennaps import session as sess
            out["scan"] = []
            for pad in (0.05, 0.10, 0.15, 0.20):
                rec = {"grid": 0.10, "pad": pad, "pad_over_grid": pad / 0.10}
                d_top = sess.create_domain(0.10, P.X_EXTENT, P.Y_EXTENT)
                module.MakePlane(d_top, pad, module.Material.SiO2).apply()
                d_bot = sess.create_domain(0.10, P.X_EXTENT, P.Y_EXTENT)
                module.MakePlane(d_bot, 0.0, module.Material.Si).apply()
                a = vls.Domain(d_top.getLevelSets()[0])
                vls.BooleanOperation(a, d_bot.getLevelSets()[0], vls.BooleanOperationEnum.RELATIVE_COMPLEMENT).apply()
                m1 = vls.Mesh()
                if a.getNumberOfPoints():
                    vls.ToSurfaceMesh(a, m1).apply()
                rec["independent_planes"] = {"level_set_points": int(a.getNumberOfPoints()), "surface_nodes": int(len(m1.getNodes()))}
                dw = sess.create_domain(0.10, P.X_EXTENT, P.Y_EXTENT)
                module.MakePlane(dw, 0.0, module.Material.Si).apply()
                module.MakePlane(dw, pad, module.Material.SiO2, True).apply()
                ls = dw.getMaterialLevelSet(module.Material.SiO2)
                m2 = vls.Mesh()
                if ls is not None and ls.getNumberOfPoints():
                    vls.ToSurfaceMesh(ls, m2).apply()
                rec["wrapped_official_getMaterialLevelSet"] = {"level_set_points": None if ls is None else int(ls.getNumberOfPoints()), "surface_nodes": int(len(m2.getNodes()))}
                out["scan"].append(rec)
            out["status"] = "OK"
            (out_dir / f"{case}_{rt}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
            print(json.dumps(out["scan"]), flush=True)
            return
        if rt == "R6":
            out["scan"] = []
            for pad in (0.05, 0.10, 0.15, 0.20):
                module_ = module
                from tcad.backends.viennaps import session as sess
                dom = sess.create_domain(0.10, P.X_EXTENT, P.Y_EXTENT)
                module_.MakePlane(dom, 0.0, module_.Material.Si).apply()
                module_.MakePlane(dom, pad, module_.Material.SiO2, True).apply()
                ls = dom.getMaterialLevelSet(module_.Material.SiO2)
                mesh = vls.Mesh()
                if ls is not None and ls.getNumberOfPoints():
                    vls.ToSurfaceMesh(ls, mesh).apply()
                nodes = np.array(mesh.getNodes())
                out["scan"].append({"grid": 0.10, "pad": pad, "pad_over_grid": pad / 0.10, "level_set_points": None if ls is None else int(ls.getNumberOfPoints()),
                                    "surface_nodes": int(len(nodes)), "surface_y": [float(nodes[:, 1].min()), float(nodes[:, 1].max())] if len(nodes) else None})
            out["status"] = "OK"
            (out_dir / f"{case}_{rt}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
            print(json.dumps(out["scan"]), flush=True)
            return
        if rt == "R4":
            floored = vio._floored_copy_for_export(domain, P.DEPTH)
            base = str(Path(work) / f"{case}_R4")
            floored.saveVolumeMesh(base)
            pts, tri, tags = P.load_mesh(base + "_volume.vtu")
            out["measure"] = P.measure_mesh(module, pts, tri, tags, case, floored=True)
            import shutil
            shutil.copy(base + "_volume.vtu", out_dir / f"{case}_R4.vtu")
        else:
            xmin, xmax, _y0, ymax = vio._union_bounding_box(domain)
            per = {}
            for m in sorted(domain.getMaterialsInDomain(), key=int):
                name = P.tag_name(module, int(m))
                ls = domain.getMaterialLevelSet(m)
                rec = {"level_set_points": None if ls is None else int(ls.getNumberOfPoints())}
                if not rec["level_set_points"]:
                    per[name] = rec
                    continue
                mesh = vls.Mesh()
                vls.ToSurfaceMesh(ls, mesh).apply()
                nodes = np.array(mesh.getNodes())
                rec["surface_nodes"] = int(len(nodes))
                rec["surface_bbox"] = [nodes.min(axis=0).tolist(), nodes.max(axis=0).tolist()] if len(nodes) else None
                try:
                    p_, t_ = vio._export_single_level_set(domain, ls, m, P.DEPTH, bounds_hint=(xmin, xmax, ymax))
                    rec["project_single_export"] = {"status": "OK", "triangles": int(len(t_))}
                except Exception as exc:  # noqa: BLE001
                    rec["project_single_export"] = {"status": "EXCEPTION", "error": repr(exc)[:300]}
                try:
                    bcs = domain.getBoundaryConditions()
                    single = domain.__class__([xmin, xmax, -P.DEPTH - 1.0, ymax + 1.0], bcs, domain.getGridDelta())
                    single.insertNextLevelSetAsMaterial(vls.Domain(ls), m, False)
                    base = str(Path(work) / f"{case}_{name}_raw")
                    single.saveVolumeMesh(base)
                    pts, tri, tags = P.load_mesh(base + "_volume.vtu")
                    a = P.tri_area(pts, tri)
                    rec["official_raw_single_export"] = {"status": "OK", "triangles": int(len(tri)), "area": float(a.sum()),
                                                         "y_range": [float(pts[:, 1].min()), float(pts[:, 1].max())]}
                except Exception as exc:  # noqa: BLE001
                    rec["official_raw_single_export"] = {"status": "EXCEPTION", "error": repr(exc)[:300]}
                per[name] = rec
            out["per_material"] = per
        out["status"] = "OK"
    except Exception as exc:  # noqa: BLE001
        out["status"] = "EXCEPTION"
        out["error"] = repr(exc)[:600]
        out["traceback"] = traceback.format_exc()[-3000:]
    with open(out_dir / f"{case}_{rt}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps({k: out.get(k) for k in ("case", "route", "status", "error")}), flush=True)


if __name__ == "__main__":
    main()
