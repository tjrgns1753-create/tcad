"""Batch 7H-E2 remote worker (PLAN sections 1-8). Mesh geometry and DEVSIM default geometric models only:
no devsim.solve, no doping written to DEVSIM. usage: stage_e2.py <out dir>"""
import collections
import dataclasses
import json
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
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(E1, "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-d-sg-pn-mesh-validity", "scripts"))
import common_e1 as ce  # noqa: E402  (E1, read-only: GUI defaults, strict JSON, sha)
import trace_refine_e2 as tr  # noqa: E402
import verdicts_e2 as vd  # noqa: E402

UM = 1e-4
E1_MESH_SHA = "cfae97d4aca233b5e20ffed23741e37e0498ddb419c0babc045f57ce920b1c7a"
E1_PROD = os.path.join(E1, "data", "remote_run_36012608804", "outputs", "e1_out", "prod.json")
E1_NPZ = os.path.join(E1, "data", "remote_run_36012608804", "outputs", "e1_out", "prod_arrays.npz")
T0 = time.time()


def log(msg):
    print(f"[e2 {time.time() - T0:8.1f}s] {msg}", flush=True)


def regen(outd, rec):
    from tcad.backends.viennaps import session as vs
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    g = ce.GUI
    domain = vs.make_mask_spans(grid_delta_um=g["grid_delta_um"], x_extent_um=g["x_extent_um"], y_extent_um=g["y_extent_um"],
                                spans_um=[tuple(s) for s in g["mask_spans_um"]], mask_height_um=max(g["pr_thickness_um"], 0.1),
                                substrate_depth_um=g["silicon_depth_um"] + 1.0)
    mesh_path = save_volume_mesh(domain, os.path.join(outd, "wafer"), floor_depth_um=g["silicon_depth_um"])
    sha = ce.sha_file(mesh_path)
    rec["input_mesh"] = {"name": os.path.basename(mesh_path), "sha256": sha, "e1_sha256": E1_MESH_SHA, "equal": sha == E1_MESH_SHA}
    pr = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    d = g["doping"]
    doped = apply_step_junction_doping(pr, region=d["region"], junction_axis=d["junction_axis"],
                                       junction_position_um=d["junction_position_um"], donor_conc_cm3=d["donor_conc_cm3"],
                                       acceptor_conc_cm3=d["acceptor_conc_cm3"], chemical_state=d["chemical_state"])
    return doped


def raw_arrays(result):
    import meshio
    m = meshio.read(result.volume_mesh_path)
    blk = next(c for c in m.cells if c.type == "triangle")
    bi = m.cells.index(blk)
    return m.points, blk.data, m.cell_data[result.material_field][bi]


def do_import(result, k, name, refine=True):
    from tcad.device.devsim.mesh_import import import_process_result
    i = ce.GUI["import"]
    kw = dict(contact_regions=i["contact_regions"], contact_axis=i["contact_axis"], length_scale_to_cm=i["length_scale_to_cm"])
    if refine:
        kw.update(refine_near_um=i["refine_near_um"], refine_axis=i["refine_axis"])
        if k is not None:
            kw["refine_levels"] = k
    return import_process_result(result, mesh_name=name + "_mesh", device_name=name + "_device", **kw)


def read_device(dv, imp):
    dev = imp.device
    g = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n))  # noqa: E731
    x, y, nv = g("x"), g("y"), g("NodeVolume")
    el = np.array(dv.get_element_node_list(device=dev, region="Si"), dtype=np.int64)
    contacts = {}
    for c in imp.contacts:
        try:
            nodes = sorted({int(v) for e in dv.get_element_node_list(device=dev, region="Si", contact=c) for v in e})
            mode = "get_element_node_list(contact)"
        except Exception:  # noqa: BLE001
            sel = x == (x.min() if c.endswith("min") else x.max())
            nodes, mode = sorted(np.where(sel)[0].tolist()), "x extreme (fallback)"
        contacts[c] = {"n_nodes": len(nodes), "mode": mode,
                       "coords_sha256": ce.sha(np.round(np.column_stack([x[nodes], y[nodes]]), 30).tobytes())}
    edge = {}
    try:
        dv.edge_from_node_model(device=dev, region="Si", node_model="node_index")
        ge = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n))  # noqa: E731
        edge = {"n0": ge("node_index@n0").astype(np.int64), "n1": ge("node_index@n1").astype(np.int64),
                "EdgeCouple": ge("EdgeCouple"), "EdgeLength": ge("EdgeLength")}
    except Exception as e:  # noqa: BLE001
        edge = {"error": repr(e)[:300]}
    return {"x": x, "y": y, "nv": nv, "el": el, "contacts": contacts, "regions": list(dv.get_region_list(device=dev)),
            "edge": edge}


def release(dv, imp):
    dv.delete_device(device=imp.device)
    dv.delete_mesh(mesh=imp.mesh)


def exact_obtuse(P, tris, cand):
    """Exact classification (Fraction dot products) for triangles in `cand`; returns the obtuse subset."""
    from fractions import Fraction as F
    out = []
    for t in cand:
        a, b, c = (P[v] for v in tris[t])
        pts = [(F(float(p[0])), F(float(p[1]))) for p in (a, b, c)]
        for k in range(3):
            o, p, q = pts[k], pts[(k + 1) % 3], pts[(k + 2) % 3]
            if (p[0] - o[0]) * (q[0] - o[0]) + (p[1] - o[1]) * (q[1] - o[1]) < 0:
                out.append(int(t))
                break
    return out


def analyze(d, label, extra=None):
    """Everything of PLAN section 3 for one imported device (coordinates as DEVSIM holds them)."""
    import build_fixtures_7hd as bf7
    fm = bf7.sl.fm
    ef = bf7.ef
    eg = bf7.eg
    x, y, nv, el = d["x"], d["y"], d["nv"], d["el"]
    tris = [[int(a), int(b), int(c)] for a, b, c in el]
    Pc = np.column_stack([x, y])
    P = Pc / UM
    n = len(x)
    area_exact = tr.exact_area(Pc, tris)
    area = float(area_exact)
    f2 = fm.node_areas(Pc, tris, "F2")
    f3 = fm.node_areas(Pc, tris, "F3")
    b = tr.node_budget(Pc, tris, n)
    tau = (n + len(tris)) * 2.0 ** -52 + float(b.max())
    rel = np.abs(nv - f3) / f3
    exc_nodes = np.where((f3 - f2) > b * f3)[0]
    maxang = tr.max_angle_deg_per_triangle(Pc, tris)
    obt = exact_obtuse(Pc, tris, np.where(maxang > 89.99)[0])
    obt_vertices = {v for t in obt for v in tris[t]}
    q = bf7.quality(P, tris)
    ipts, _ = eg.exact_integer_points(P)
    owners, bset, _, _ = eg.edge_sets(tris, [0] * len(tris))
    viol = ef.exact_violations(ipts, tris, [0] * len(tris), frozenset(e for e, _ in bset))
    r = {"label": label, "n_nodes": n, "n_triangles": len(tris), "regions": d["regions"],
         "x_sha256": ce.sha(x.tobytes()), "y_sha256": ce.sha(y.tobytes()), "elements_sha256": ce.sha(el.tobytes()),
         "NodeVolume_sha256": ce.sha(nv.tobytes()), "contacts": d["contacts"],
         "contact_nodes_sha256": ce.sha(json.dumps({c: v["coords_sha256"] for c, v in sorted(d["contacts"].items())}).encode()),
         "exact_area_cm2": f"{area_exact.numerator}/{area_exact.denominator}", "area_cm2": area,
         "float_triangle_area_sum_cm2": float(sum(fm.tri_area(Pc[t]) for t in tris)),
         "sum_NodeVolume_cm2": float(nv.sum()), "ratio": float(nv.sum() / area), "tau": tau,
         "excess_over_area": float((nv.sum() - area) / area), "sum_F3_minus_F2_over_area": float((f3 - f2).sum() / area),
         "sum_F2_over_area": float(f2.sum() / area),
         "excess_explained_by_F3_within_tau": bool(abs((nv.sum() - area) - (f3 - f2).sum()) / area <= tau),
         "f3_max_rel_error": float(rel.max()), "f3_nodes_beyond_budget": int((np.abs(nv - f3) > b * f3).sum()),
         "f3_all_nodes_within_budget": bool((np.abs(nv - f3) <= b * f3).all()),
         "budget_max_b_i": float(b.max()),
         "n_nodes_F3_gt_F2": int(len(exc_nodes)),
         "f3_excess_nodes_all_obtuse_vertices": bool(set(exc_nodes.tolist()) <= obt_vertices),
         "excess_node_abs_x_um": sorted({round(abs(float(v)), 6) for v in P[exc_nodes, 0]}),
         "n_obtuse_exact": len(obt), "obtuse_vertex_abs_x_um": sorted({round(abs(float(P[v, 0])), 6) for v in obt_vertices}),
         "max_angle_deg": float(maxang.max()), "quality_7hd": q, "n_delaunay_violations_exact": len(viol),
         "delaunay_violation_edge_abs_x_um": sorted({(round(abs(float(P[e[0], 0])), 6), round(abs(float(P[e[1], 0])), 6))
                                                     for e, *_ in viol}),
         "tags_all_si": d["regions"] == ["Si"]}
    ed = d["edge"]
    if "error" in ed:
        r["edgecouple"] = {"status": "EDGECOUPLE_UNKNOWN", "error": ed["error"]}
    else:
        g1, g2, _ = fm.edge_couple_predictions(Pc, tris)
        keys = [(min(a, b_), max(a, b_)) for a, b_ in zip(ed["n0"], ed["n1"])]
        G1 = np.array([g1[k] for k in keys])
        G2 = np.array([g2[k] for k in keys])
        ec, L = ed["EdgeCouple"], ed["EdgeLength"]
        neg = G1 < 0
        scale = float(np.abs(G2).max())
        nv_from_edges = np.zeros(n)
        np.add.at(nv_from_edges, ed["n0"], 0.25 * ec * L)
        np.add.at(nv_from_edges, ed["n1"], 0.25 * ec * L)
        r["edgecouple"] = {"status": "READ", "n_edges": int(len(ec)), "n_G1_negative": int(neg.sum()),
                           "devsim_at_G1_negative": {"negative": int((ec[neg] < 0).sum()), "zero": int((ec[neg] == 0).sum()),
                                                     "positive": int((ec[neg] > 0).sum())},
                           "devsim_negative_total": int((ec < 0).sum()),
                           "max_abs_EC_minus_G2_over_maxG2": float(np.abs(ec - G2).max() / scale),
                           "max_abs_EC_minus_G1_over_maxG2": float(np.abs(ec - G1).max() / scale),
                           "at_G1_negative_max_abs_EC_minus_G2_over_maxG2": float(np.abs(ec[neg] - G2[neg]).max() / scale) if neg.any() else None,
                           "at_G1_negative_max_abs_EC_minus_G1_over_maxG2": float(np.abs(ec[neg] - G1[neg]).max() / scale) if neg.any() else None,
                           "NodeVolume_vs_sum_quarter_EC_L_max_rel": float(np.abs(nv - nv_from_edges).max() / nv.max())}
        d["G1"], d["G2"] = G1, G2
    d.update({"F2": f2, "F3": f3, "b": b, "obtuse": np.array(obt, dtype=np.int64)})
    if extra:
        r.update(extra)
    return r, viol


def lineage(k, dmap, origin, kinds, s0_P, s0_T, tri_list, viol):
    """Lineage of obtuse triangles and of Delaunay-violating edge triangles at stage k (dmap: DEVSIM tri -> traced tri)."""
    from fractions import Fraction as F

    def s0_class(t):
        pts = [(F(float(p[0])), F(float(p[1]))) for p in (s0_P[v] for v in s0_T[t])]
        dots = [(pts[(j + 1) % 3][0] - pts[j][0]) * (pts[(j + 2) % 3][0] - pts[j][0]) +
                (pts[(j + 1) % 3][1] - pts[j][1]) * (pts[(j + 2) % 3][1] - pts[j][1]) for j in range(3)]
        return "obtuse" if min(dots) < 0 else ("right" if min(dots) == 0 else "acute")

    def rec(t_dev):
        t = dmap[t_dev]
        o = int(origin[k][t])
        return {"origin_S0_triangle": o, "origin_class": s0_class(o),
                "origin_vertices_um": [[float(v) for v in s0_P[i][:2]] for i in s0_T[o]],
                "kinds": [tr.KIND_NAMES[j] for j in kinds[k][t]]}
    obt = [rec(int(t)) for t in tri_list]
    pat = collections.Counter((r["origin_class"], tuple(r["kinds"])) for r in obt)
    vrec = [{"edge": [int(e[0]), int(e[1])], "t1": rec(int(t1)), "t2": rec(int(t2))} for e, t1, t2, *_ in viol]
    vpat = collections.Counter((a["t1"]["origin_class"], tuple(a["t1"]["kinds"]), a["t2"]["origin_class"], tuple(a["t2"]["kinds"]))
                               for a in vrec)
    return {"obtuse_patterns": [{"origin_class": c, "kinds": list(kk), "count": n} for (c, kk), n in pat.most_common()],
            "obtuse_distinct_origins": len({r["origin_S0_triangle"] for r in obt}),
            "obtuse_examples": obt[:6],
            "violation_patterns": [{"t1": [a, list(b)], "t2": [c, list(dd)], "count": n} for (a, b, c, dd), n in vpat.most_common()],
            "violation_examples": vrec[:4]}


def write_vtu(path, points, tris, tags, field):
    import meshio
    meshio.write(path, meshio.Mesh(points, [("triangle", np.asarray(tris))], cell_data={field: [np.asarray(tags)]}))
    m = meshio.read(path)
    blk = next(c for c in m.cells if c.type == "triangle")
    ok = (np.array_equal(m.points, points) and m.points.dtype == points.dtype and np.array_equal(blk.data, tris)
          and np.array_equal(m.cell_data[field][m.cells.index(blk)], tags))
    return ok


def main():
    outd = os.path.abspath(sys.argv[1])
    os.makedirs(outd, exist_ok=True)
    import devsim as dv
    res = {"plan_sha256_expected": "92e87eadb6c2317b3edab7c4e51b88653cc5cf5050fc87fcd97f304782b41c6b", "stages": [],
           "solve_calls": 0}
    real_solve = dv.solve

    def trap(*a, **k):
        res["solve_calls"] += 1
        raise RuntimeError("E2 forbids devsim.solve")
    dv.solve = trap
    try:
        doped = regen(outd, res)
        log(f"input mesh equal to E1: {res['input_mesh']['equal']}")
        if not res["input_mesh"]["equal"]:
            res["stop"] = "MESH_INPUT_IDENTITY_FAIL"
            return finish(outd, res)
        from tcad.device.devsim.mesh_refine import refine_mesh_near
        p0, t0, g0 = raw_arrays(doped)
        i = ce.GUI["import"]
        ax = {"x": 0, "y": 1}[i["refine_axis"]]
        pred = lambda c: abs(c[ax] - i["refine_near_um"]) < 0.1  # noqa: E731  (production default half width)
        states, origin, kinds = tr.refine_traced(p0, t0, g0, pred, 4)
        res["n_passes_traced"] = len(states) - 1
        e1 = ce.load_strict(E1_PROD)
        e1a = np.load(E1_NPZ)
        stage_arrays = {}
        for k in range(5):
            log(f"stage S{k}")
            pp, tt, gg = refine_mesh_near(p0, t0, g0, pred, levels=k)
            sp, st, sg = states[min(k, len(states) - 1)]
            i1 = bool(np.array_equal(pp, sp) and np.array_equal(tt, st) and np.array_equal(gg, sg))
            name = "gui_measure" if k == 4 else f"e2_s{k}"
            imp = do_import(doped, None if k == 4 else k, name)
            d = read_device(dv, imp)
            release(dv, imp)
            pc = pp * i["length_scale_to_cm"]
            i2_xy = bool(len(d["x"]) == len(pc) and np.array_equal(d["x"], pc[:, 0].astype(float))
                         and np.array_equal(d["y"], pc[:, 1].astype(float)))
            if i2_xy:
                nmap = np.arange(len(pc))
            else:   # DEVSIM node -> traced node by exact coordinates (recorded, never assumed)
                key = {(float(a), float(b)): j for j, (a, b) in enumerate(zip(pc[:, 0], pc[:, 1]))}
                nm = [key.get((float(a), float(b))) for a, b in zip(d["x"], d["y"])]
                nmap = np.array([m if m is not None else -1 for m in nm])
            el_m = nmap[d["el"]]
            if i2_xy and np.array_equal(d["el"], tt):
                i2_mode, dmap = "exact_order", np.arange(len(tt))
            else:
                lut = {tuple(sorted(t)): j for j, t in enumerate(tt.tolist())}
                dm = [lut.get(tuple(sorted(t))) for t in el_m.tolist()] if (nmap >= 0).all() else [None]
                ok = None not in dm and len(set(dm)) == len(tt) == len(el_m) and len(set(nmap.tolist())) == len(pc)
                i2_mode = ("coordinate_mapped_" if not i2_xy else "") + "multiset_of_sorted_triples" if ok else "MISMATCH"
                dmap = np.array([m if m is not None else -1 for m in dm])
            ident = {"I1": i1, "I2": bool(i2_xy and i2_mode != "MISMATCH"), "I2_xy_bit_equal": i2_xy, "I2_element_mode": i2_mode}
            r, viol = analyze(d, f"S{k}", {"k": k})
            if k == 4:
                reg = e1["region_facts"]["Si"]
                ident["I3"] = bool(r["x_sha256"] == reg["x_sha256"] and r["y_sha256"] == reg["y_sha256"]
                                   and r["elements_sha256"] == reg["elements_sha256"]
                                   and np.array_equal(d["nv"], e1a["NodeVolume"])
                                   and sorted(d["contacts"]) == sorted(e1["contacts"]) and d["regions"] == e1["regions"])
            r["identity"] = ident
            if i2_mode != "MISMATCH":
                r["lineage"] = lineage(min(k, len(states) - 1), dmap, origin, kinds, p0, t0, d["obtuse"].tolist(), viol)
            res["stages"].append(r)
            stage_arrays[k] = d
            np.savez_compressed(os.path.join(outd, f"stage_S{k}.npz"), x=d["x"], y=d["y"], elements=d["el"], NodeVolume=d["nv"],
                                F2=d["F2"], F3=d["F3"], budget=d["b"], obtuse=d["obtuse"],
                                **({"edge_n0": d["edge"]["n0"], "edge_n1": d["edge"]["n1"], "EdgeCouple": d["edge"]["EdgeCouple"],
                                    "EdgeLength": d["edge"]["EdgeLength"], "G1": d["G1"], "G2": d["G2"]} if "G1" in d else {}),
                                origin_S0=origin[min(k, len(states) - 1)],
                                kinds=np.array([sum(v * 4 ** j for j, v in enumerate(kk)) for kk in kinds[min(k, len(states) - 1)]]))
            log(f"S{k}: nodes {r['n_nodes']} ratio {r['ratio']!r} tau {r['tau']:.3e} I1 {i1} I2 {ident['I2']} {ident.get('I3', '')}")
        i3 = bool(res["stages"][4]["identity"].get("I3"))
        # controls
        p4, t4, g4 = states[-1]
        field = doped.material_field
        s4 = stage_arrays[4]
        controls = {}
        for label, tris in (("C_rt", t4), ("C_ccw", None)):
            if tris is None:
                tris, nflip = tr.ccw_only(p4, t4)
            else:
                nflip = 0
            path = os.path.join(outd, f"{label}.vtu")
            wr = write_vtu(path, p4, tris, g4, field)
            imp = do_import(dataclasses.replace(doped, volume_mesh_path=path), None, "e2_" + label.lower(), refine=False)
            d = read_device(dv, imp)
            release(dv, imp)
            r, _ = analyze(d, label, {"writer_roundtrip_exact": wr, "n_triangles_reoriented": nflip,
                                       "vtu_sha256": ce.sha_file(path)})
            b = s4["b"]
            r["n_nodes_beyond_budget_vs_S4"] = int((np.abs(d["nv"] - s4["nv"]) > b * s4["nv"]).sum()) if len(d["nv"]) == len(s4["nv"]) else None
            if label == "C_rt":
                r["reproduces_S4"] = bool(wr and np.array_equal(d["x"], s4["x"]) and np.array_equal(d["y"], s4["y"])
                                          and np.array_equal(d["el"], s4["el"]) and np.array_equal(d["nv"], s4["nv"]))
                rt = d
            else:
                r["max_abs_NodeVolume_diff_vs_rt_rel"] = float(np.abs(d["nv"] - rt["nv"]).max() / rt["nv"].max())
                r["n_nodes_beyond_budget_vs_rt"] = int((np.abs(d["nv"] - rt["nv"]) > rt["b"] * rt["nv"]).sum())
                r["points_identical"] = bool(np.array_equal(d["x"], rt["x"]) and np.array_equal(d["y"], rt["y"]))
                r["same_vertex_sets"] = bool(np.array_equal(np.sort(d["el"], 1), np.sort(rt["el"], 1)))
            controls[label] = r
            log(f"{label}: ratio {r['ratio']!r} reoriented {nflip}")
        res["controls"] = controls
        dec = vd.decide(res["stages"], i3, controls.get("C_rt"), controls.get("C_ccw"))
        res["decision"] = dec
        log(f"decision {dec['verdicts']} withheld {dec['withheld']}")
        res["candidate"] = candidate(dv, doped, dec, p4, t4, g4, field, s4, e1a, outd) if dec["candidate_allowed"] else \
            {"verdict": "CANDIDATE_NOT_RUN", "reason": "PLAN section 7 preconditions not met"}
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:500]
        res["traceback"] = traceback.format_exc()[-3000:]
    finally:
        dv.solve = real_solve
        res["devices_left"] = list(dv.get_device_list())
    return finish(outd, res)


def candidate(dv, doped, dec, p4, t4, g4, field, s4, e1a, outd):
    import build_fixtures_7hd as bf7
    ef, eg, fm = bf7.ef, bf7.eg, bf7.sl.fm
    c = {}
    tris0 = [[int(v) for v in t] for t in t4]
    P2 = np.asarray(p4)[:, :2]
    owners, bset, iset, _ = eg.edge_sets(tris0, g4)
    x0_edges = frozenset(e for e in owners if P2[e[0], 0] == 0.0 and P2[e[1], 0] == 0.0)
    protected = frozenset(e for e, _ in bset) | x0_edges
    tris1, tags1, info = ef.exact_flip(P2, tris0, g4, protected=protected, max_passes=200)
    c["flip"] = {"terminated": info["terminated"], "n_flips": len(info["history"]), "passes": len(info["passes"])}
    ipts, K = eg.exact_integer_points(P2)
    inv0, inv1 = eg.mesh_exact_invariants(ipts, tris0, g4), eg.mesh_exact_invariants(ipts, tris1, tags1)
    own1, _, _, _ = eg.edge_sets(tris1, tags1)
    x0_after = frozenset(e for e in own1 if P2[e[0], 0] == 0.0 and P2[e[1], 0] == 0.0)
    scan, _ = eg.global_exact_scan(ipts, tris1, K)
    c.update({"points_identical": True, "boundary_edges_equal": inv0["boundary_edge_set"] == inv1["boundary_edge_set"],
              "interface_edges_equal": inv0["interface_edge_set"] == inv1["interface_edge_set"],
              "x0_edges_equal": x0_edges == x0_after, "tag_counter_equal": inv0["tag_counter"] == inv1["tag_counter"],
              "exact_area_equal": inv0["total_area2_int"] == inv1["total_area2_int"],
              "no_duplicate_zero_nonmanifold": not (inv1["duplicate_triangle_set"] or inv1["zero_area_set"] or inv1["non_manifold_edge_set"]),
              "no_positive_overlap": scan["counts"]["EXACT_POSITIVE_AREA_OVERLAP"] == 0,
              "flip_terminated_clean": info["terminated"] == "no_exact_violations_remaining"})
    path = os.path.join(outd, "candidate_flip.vtu")
    tri_arr = np.array(tris1, dtype=t4.dtype)
    tag_arr = np.array(tags1, dtype=g4.dtype)
    c["writer_roundtrip_exact"] = write_vtu(path, p4, tri_arr, tag_arr, field)
    c["vtu_sha256"] = ce.sha_file(path)
    imp = do_import(dataclasses.replace(doped, volume_mesh_path=path), None, "e2_cand", refine=False)
    d = read_device(dv, imp)
    release(dv, imp)
    r, _ = analyze(d, "candidate")
    c["analysis"] = r
    c["points_identical"] = bool(np.array_equal(d["x"], s4["x"]) and np.array_equal(d["y"], s4["y"]))
    c["contacts_equal"] = {k: v["coords_sha256"] for k, v in d["contacts"].items()} == \
        {k: v["coords_sha256"] for k, v in s4["contacts"].items()}
    c["regions_equal"] = d["regions"] == s4["regions"]
    c["ratio_within_tau"] = abs(r["ratio"] - 1.0) <= r["tau"]
    don, acc = e1a["Donors"], e1a["Acceptors"]
    for nm, N in (("donor", don), ("acceptor", acc)):
        inv_dev, inv_f2 = float((N * d["nv"]).sum()), float((N * d["F2"]).sum())
        c[f"inventory_{nm}_cm-1"] = {"devsim": inv_dev, "exact_dual_F2": inv_f2, "continuum_N_x_25um2": 1e18 * 25.0 * UM * UM}
        c[f"inventory_{nm}_within_tau"] = abs(inv_dev - inv_f2) / inv_f2 <= r["tau"]
    np.savez_compressed(os.path.join(outd, "candidate.npz"), elements=d["el"], NodeVolume=d["nv"], F2=d["F2"], F3=d["F3"])
    c.update(vd.candidate_verdict(c))
    log(f"candidate {c['verdict']} failed {c['failed']}")
    return c


def finish(outd, res):
    ce.dump_strict(res, os.path.join(outd, "e2_result.json"))
    log(f"done: error={'error' in res} devices_left={res.get('devices_left')} solve_calls={res['solve_calls']}")
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
