"""Batch 7H-E6F evaluator v2 (local, pure). Separate fixed modules, no monkeypatching:
  old   = refine_old.py      (byte copy of production mesh_refine.py at 0ef6dd2)
  red   = refine_red.py      (old + red_promotion_attempt.patch)
  proto = alt_rgb_e6f.py     (blue prototype, reference semantics)
  blue  = refine_blue.py     (blue with caches / queue / float screening)
Small fixtures get the full exact check: obtuse, degenerate, orientation, duplicate triangles and coordinates, conformity (edge
owners <= 2 with opposite directions AND no node strictly inside any edge = no hanging node), tag of every child equal to the tag of the
input triangle containing its centroid, exact area per tag, outer / interface segment preservation (spatial index; each original
segment exactly covered by contiguous collinear new segments of the same kind, none elsewhere), existing nodes unchanged, and target
resolution (max edge among triangles whose centroid satisfies the last predicate, compared exactly with the old module's). Timings are
split into generation / exact geometry / boundary / other. JSON is rewritten and closed after every case.
usage: eval2_e6f.py <out json>"""
import collections
import json
import os
import sys
import time
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import refine_old  # noqa: E402
import refine_red  # noqa: E402
import alt_rgb_e6f as proto  # noqa: E402
import refine_blue  # noqa: E402

ALGOS = {"old": lambda P, T, G, p: refine_old.refine_mesh_near(P, T, G, p, levels=1),
         "red": lambda P, T, G, p: refine_red.refine_mesh_near(P, T, G, p, levels=1),
         "proto": lambda P, T, G, p: proto.refine_mesh_near_rgb(P, T, G, p, levels=1),
         "blue": lambda P, T, G, p: refine_blue.refine_mesh_near_blue(P, T, G, p, levels=1)}


def fr(P):
    return [Fraction(float(x)) for x in P[:, 0]], [Fraction(float(y)) for y in P[:, 1]]


def geometry(P, T, G, P0, T0, G0):
    P, P0 = np.asarray(P, np.float64), np.asarray(P0, np.float64)
    T, T0 = np.asarray(T, np.int64), np.asarray(T0, np.int64)
    X, Y = fr(P)
    obt = deg = pos = neg = 0
    area = collections.defaultdict(Fraction)
    for (a, b, c), g in zip(T.tolist(), np.asarray(G).tolist()):
        o = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        deg += o == 0
        pos += o > 0
        neg += o < 0
        area[int(g)] += abs(o) / 2
        if any((X[u] - X[w]) * (X[v] - X[w]) + (Y[u] - Y[w]) * (Y[v] - Y[w]) < 0 for w, u, v in ((a, b, c), (b, c, a), (c, a, b))):
            obt += 1
    X0, Y0 = fr(P0)
    area0 = collections.defaultdict(Fraction)
    for (a, b, c), g in zip(T0.tolist(), np.asarray(G0).tolist()):
        area0[int(g)] += abs((X0[b] - X0[a]) * (Y0[c] - Y0[a]) - (Y0[b] - Y0[a]) * (X0[c] - X0[a])) / 2
    own = collections.defaultdict(list)
    for (a, b, c) in T.tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            own[(min(u, v), max(u, v))].append(u < v)
    s = np.sort(T, axis=1)
    kc = collections.Counter(zip(X, Y))
    # hanging nodes: a node strictly inside an edge (float prefilter by bounding box, exact collinearity / betweenness)
    hanging = 0
    for (u, v) in own:
        lo, hi = np.minimum(P[u, :2], P[v, :2]), np.maximum(P[u, :2], P[v, :2])
        cand = np.nonzero(np.all((P[:, :2] >= lo) & (P[:, :2] <= hi), axis=1))[0]
        for w in cand.tolist():
            if w in (u, v):
                continue
            cr = (X[w] - X[u]) * (Y[v] - Y[u]) - (Y[w] - Y[u]) * (X[v] - X[u])
            if cr == 0:
                hanging += 1
    # tag of every child = tag of the input triangle containing its centroid (grid index over input triangles)
    tag_bad = tag_unfound = 0
    cell = max(float(np.ptp(P0[:, 0])), float(np.ptp(P0[:, 1]))) / 64 or 1.0
    idx = collections.defaultdict(list)
    for i, t in enumerate(T0.tolist()):
        mn, mx = P0[t, :2].min(0), P0[t, :2].max(0)
        for gx in range(int(np.floor(mn[0] / cell)), int(np.floor(mx[0] / cell)) + 1):
            for gy in range(int(np.floor(mn[1] / cell)), int(np.floor(mx[1] / cell)) + 1):
                idx[(gx, gy)].append(i)
    for (a, b, c), g in zip(T.tolist(), np.asarray(G).tolist()):
        cx, cy = (X[a] + X[b] + X[c]) / 3, (Y[a] + Y[b] + Y[c]) / 3
        found = None
        for i in idx[(int(np.floor(float(cx) / cell)), int(np.floor(float(cy) / cell)))]:
            p, q, r = T0[i]
            s1 = (X0[q] - X0[p]) * (cy - Y0[p]) - (Y0[q] - Y0[p]) * (cx - X0[p])
            s2 = (X0[r] - X0[q]) * (cy - Y0[q]) - (Y0[r] - Y0[q]) * (cx - X0[q])
            s3 = (X0[p] - X0[r]) * (cy - Y0[r]) - (Y0[p] - Y0[r]) * (cx - X0[r])
            if (s1 > 0 and s2 > 0 and s3 > 0) or (s1 < 0 and s2 < 0 and s3 < 0):
                found = i
                break
        if found is None:
            tag_unfound += 1
        elif int(G0[found]) != int(g):
            tag_bad += 1
    return {"triangles": int(len(T)), "points": int(len(P)), "obtuse": int(obt), "degenerate": int(deg),
            "orientation_pos_neg": [int(pos), int(neg)], "edges_over_2_owners": int(sum(len(v) > 2 for v in own.values())),
            "two_owner_same_direction": int(sum(len(v) == 2 and v[0] == v[1] for v in own.values())),
            "hanging_nodes": int(hanging), "duplicate_triangles": int(len(s) - len(np.unique(s, axis=0))),
            "duplicate_node_coordinates": int(sum(v > 1 for v in kc.values())),
            "existing_nodes_preserved": bool(np.array_equal(P[:len(P0), :2], P0[:, :2])),
            "area_by_tag_equal_input": {str(k): v for k, v in area.items()} == {str(k): v for k, v in area0.items()},
            "child_tag_mismatch": int(tag_bad), "child_parent_not_found": int(tag_unfound)}


def seg_kinds(T, G):
    own = collections.defaultdict(list)
    for (a, b, c), g in zip(np.asarray(T).tolist(), np.asarray(G).tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            own[(min(u, v), max(u, v))].append(int(g))
    return {e: (("outer", gs[0]) if len(gs) == 1 else ("interface", tuple(sorted(gs)))) for e, gs in own.items()
            if len(gs) == 1 or (len(gs) == 2 and gs[0] != gs[1])}


def boundary_preserved(P0, T0, G0, P, T, G):
    P0, P = np.asarray(P0, np.float64), np.asarray(P, np.float64)
    s0, s1 = seg_kinds(T0, G0), seg_kinds(T, G)
    X0, Y0 = fr(P0)
    X, Y = fr(P)
    cell = max(float(np.ptp(P0[:, 0])), float(np.ptp(P0[:, 1]))) / 64 or 1.0
    grid = collections.defaultdict(list)
    for e in s0:
        mn, mx = P0[list(e), :2].min(0), P0[list(e), :2].max(0)
        for gx in range(int(np.floor(mn[0] / cell)), int(np.floor(mx[0] / cell)) + 1):
            for gy in range(int(np.floor(mn[1] / cell)), int(np.floor(mx[1] / cell)) + 1):
                grid[(gx, gy)].append(e)
    pieces = collections.defaultdict(list)
    orphan = 0
    for (a, b), kind in s1.items():
        m = (P[a, :2] + P[b, :2]) / 2
        placed = False
        for (u, v) in grid[(int(np.floor(m[0] / cell)), int(np.floor(m[1] / cell)))]:
            if s0[(u, v)] != kind:
                continue
            dx, dy = X0[v] - X0[u], Y0[v] - Y0[u]
            dd = dx * dx + dy * dy
            ts = []
            for w in (a, b):
                if (X[w] - X0[u]) * dy - (Y[w] - Y0[u]) * dx != 0:
                    break
                ts.append(((X[w] - X0[u]) * dx + (Y[w] - Y0[u]) * dy) / dd)
            if len(ts) == 2 and 0 <= min(ts) and max(ts) <= 1:
                pieces[(u, v)].append((min(ts), max(ts)))
                placed = True
                break
        orphan += not placed
    uncovered = 0
    for e in s0:
        ps = sorted(pieces.get(e, []))
        if not ps or ps[0][0] != 0 or ps[-1][1] != 1 or any(ps[i][1] != ps[i + 1][0] for i in range(len(ps) - 1)):
            uncovered += 1
    return {"original_segments": len(s0), "new_segments": len(s1), "new_segments_not_on_an_original": orphan,
            "original_segments_not_exactly_covered": uncovered, "preserved": orphan == 0 and uncovered == 0}


def max_edge2_in(P, T, pred):
    P = np.asarray(P, np.float64)
    best = Fraction(0)
    X, Y = fr(P)
    for t in np.asarray(T).tolist():
        if pred(P[t].mean(0)):
            for u, v in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                best = max(best, (X[u] - X[v]) ** 2 + (Y[u] - Y[v]) ** 2)
    return best


def canon(P, T, G):
    P = np.asarray(P, np.float64)
    return sorted((tuple(sorted(tuple(P[v, :2].tolist()) for v in t)), int(g)) for t, g in zip(np.asarray(T).tolist(), np.asarray(G).tolist()))


def grid(nx, ny, h=1.0, split=None):
    pts = np.array([[i * h, j * h, 0.0] for j in range(ny + 1) for i in range(nx + 1)])
    tris, tags = [], []
    for j in range(ny):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
            tags += [10 if split is None or i < split else 11] * 2
    return pts, np.array(tris), np.array(tags)


def lattice(n):
    """Equilateral triangular lattice (acute input; coordinates rounded to float64 -- the input's own exactness is reported)."""
    h = np.sqrt(3) / 2
    pts = np.array([[i + 0.5 * (j % 2), j * h, 0.0] for j in range(n + 1) for i in range(n + 1)])
    tris = []
    for j in range(n):
        for i in range(n):
            a, b, c, d = j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i, (j + 1) * (n + 1) + i + 1
            tris += [(a, b, d), (a, d, c)] if j % 2 == 0 else [(a, b, c), (b, d, c)]
    return pts, np.array(tris), np.full(len(tris), 10)


def cases():
    import meshio
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import derive_implant_windows_refinement
    P, T, G = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], float), np.array([[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4]]), np.full(4, 10)
    yield "counterexample_2cells", P, T, G, [lambda c: c[0] < 1 and c[1] < 0.5]
    P, T, G = grid(10, 10)
    for lv in (1, 2, 3):
        yield f"grid10_window_x5_passes{lv}", P, T, G, [lambda c: abs(c[0] - 5.0) < 1.0] * lv
    P, T, G = grid(6, 4, split=3)
    yield "two_material_window_on_interface_passes2", P, T, G, [lambda c: abs(c[0] - 3.0) < 1.0, lambda c: abs(c[0] - 3.0) < 0.5]
    yield "identity_all_false", P, T, G, [lambda c: False]
    P, T, G = grid(10, 10)
    yield "grid10_graded_3_windows", P, T, G, [lambda c, hw=hw: abs(c[0] - 5.0) < hw for hw in (1.0, 0.5, 0.25)]
    P, T, G = lattice(8)
    yield "equilateral_lattice_passes2", P, T, G, [lambda c: abs(c[0] - 4.0) < 1.0] * 2
    path = os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu")
    m = meshio.read(path)
    P0, T0, G0 = m.points, m.cells[0].data, m.cell_data["Material"][0]
    pr = ProcessResult(volume_mesh_path=path, material_field="Material", material_regions=[MaterialRegion(name="Si", tag=10)])
    wr = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=1e16, acceptor_background_cm3=0.0,
                                      windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0},
                                               {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0}],
                                      chemical_state="ACTIVE")
    yield "B_raw_recipe_1e16", P0, T0, G0, derive_implant_windows_refinement(wr.doping, P0, T0)


def main():
    out_path = sys.argv[1]
    out = {"modules": {n: __import__("hashlib").sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
                       for n, f in (("old", "refine_old.py"), ("red", "refine_red.py"), ("proto", "alt_rgb_e6f.py"), ("blue", "refine_blue.py"))},
           "cases": {}}
    for label, P0, T0, G0, preds in cases():
        case = {"input_triangles": int(len(T0)), "input_points": int(len(P0)), "passes": len(preds), "algorithms": {}}
        results = {}
        for name, fn in ALGOS.items():
            t0 = time.time()
            P, T, G = P0, T0, G0
            sizes = []
            refine_blue.STATS.clear()
            for p in preds:
                P, T, G = fn(P, T, G, p)
                sizes.append(int(len(T)))
            t_gen = time.time() - t0
            t1 = time.time()
            geo = geometry(P, T, G, P0, T0, G0)
            t_geo = time.time() - t1
            t2 = time.time()
            bnd = boundary_preserved(P0, T0, G0, P, T, G)
            t_bnd = time.time() - t2
            t3 = time.time()
            results[name] = (P, T, G)
            r = {"sizes_per_pass": sizes, "output_dtype": str(np.asarray(P).dtype), **geo, "boundary": bnd,
                 "time_s": {"generation": round(t_gen, 4), "exact_geometry": round(t_geo, 4), "boundary": round(t_bnd, 4)}}
            if name == "blue":
                r["sign_tests"] = dict(refine_blue.STATS)
            r["time_s"]["other"] = round(time.time() - t3, 4)
            case["algorithms"][name] = r
        last = preds[-1]
        ref = max_edge2_in(*results["old"][:2], last)
        for name in ALGOS:
            m2 = max_edge2_in(*results[name][:2], last)
            case["algorithms"][name]["target_max_edge"] = float(m2) ** 0.5
            case["algorithms"][name]["target_resolution_at_least_old"] = bool(m2 <= ref)
        case["blue_equals_proto"] = {"same_arrays": bool(all(np.array_equal(a, b) for a, b in zip(results["blue"], results["proto"]))),
                                     "same_geometric_partition": canon(*results["blue"]) == canon(*results["proto"])}
        out["cases"][label] = case
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1)
        print(label, json.dumps({n: {k: case["algorithms"][n][k] for k in ("sizes_per_pass", "obtuse", "hanging_nodes", "child_tag_mismatch",
                                                                            "target_resolution_at_least_old", "time_s")}
                                 for n in ALGOS}), case["blue_equals_proto"], flush=True)


if __name__ == "__main__":
    main()
