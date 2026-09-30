"""Batch 7H-E6F local, pure evaluation (no DEVSIM, no ViennaPS): old production closure vs the red-promotion quality closure vs the
red-green-blue audit prototype, on the minimal counterexample, a structured 10x10 grid, and the committed E6E-R1 B_raw / E6A
wafer_volume meshes with the production implant-windows predicates. Every geometric property is checked exactly (Fraction).
usage: eval_e6f.py <out json>"""
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
import alt_rgb_e6f as rgb  # noqa: E402
from tcad.device.devsim import mesh_refine as mr  # noqa: E402

CAP = 400000


def exact_report(P, T, G, P0=None, T0=None, G0=None):
    P = np.asarray(P, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64)
    X = [Fraction(float(v)) for v in P[:, 0]]
    Y = [Fraction(float(v)) for v in P[:, 1]]
    obt = deg = pos = neg = 0
    area = collections.defaultdict(Fraction)
    for (a, b, c), g in zip(T.tolist(), np.asarray(G).tolist()):
        o = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        if o == 0:
            deg += 1
        pos += o > 0
        neg += o < 0
        area[int(g)] += abs(o) / 2
        for (o_, u, v) in ((a, b, c), (b, c, a), (c, a, b)):
            if (X[u] - X[o_]) * (X[v] - X[o_]) + (Y[u] - Y[o_]) * (Y[v] - Y[o_]) < 0:
                obt += 1
                break
    own = collections.defaultdict(list)
    for i, (a, b, c) in enumerate(T.tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            own[(min(u, v), max(u, v))].append((i, u < v))
    over2 = sum(len(v) > 2 for v in own.values())
    same_dir = sum(len(v) == 2 and v[0][1] == v[1][1] for v in own.values())
    s = np.sort(T, axis=1)
    kc = collections.Counter(zip(X, Y))
    rep = {"triangles": int(len(T)), "points": int(len(P)), "obtuse": obt, "degenerate": deg, "orientation_pos_neg": [int(pos), int(neg)],
           "edges_over_2_owners": int(over2), "two_owner_same_direction": int(same_dir),
           "duplicate_triangles": int(len(s) - len(np.unique(s, axis=0))), "duplicate_node_coordinates": int(sum(v > 1 for v in kc.values())),
           "area_by_tag": {str(k): f"{v.numerator}/{v.denominator}" for k, v in sorted(area.items())}}
    if P0 is not None:
        P0 = np.asarray(P0, dtype=np.float64)
        rep["existing_nodes_preserved"] = bool(len(P) >= len(P0) and np.array_equal(P[:len(P0), :2], P0[:, :2]))
        r0 = exact_report(P0, T0, G0)
        rep["area_by_tag_equal_input"] = rep["area_by_tag"] == r0["area_by_tag"]
        rep["boundary_segments_preserved"] = boundary_preserved(P0, T0, G0, P, T, G)
    return rep


def segments(P, T, G):
    """{(u, v): kind} for outer-boundary edges (1 owner, kind = ('outer', tag)) and material-interface edges (2 owners, different tags)."""
    own = collections.defaultdict(list)
    for (a, b, c), g in zip(np.asarray(T).tolist(), np.asarray(G).tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            own[(min(u, v), max(u, v))].append(int(g))
    out = {}
    for e, gs in own.items():
        if len(gs) == 1:
            out[e] = ("outer", gs[0])
        elif len(gs) == 2 and gs[0] != gs[1]:
            out[e] = ("interface", tuple(sorted(gs)))
    return out


def boundary_preserved(P0, T0, G0, P1, T1, G1):
    """Every original boundary / interface segment equals the union of new segments of the same kind lying on it (collinear, inside,
    contiguous from end to end), and no new segment lies elsewhere."""
    F = lambda P, i: (Fraction(float(P[i][0])), Fraction(float(P[i][1])))  # noqa: E731
    s0, s1 = segments(P0, T0, G0), segments(P1, T1, G1)
    used = set()
    for (u, v), kind in s0.items():
        A, B = F(P0, u), F(P0, v)
        d = (B[0] - A[0], B[1] - A[1])
        dd = d[0] * d[0] + d[1] * d[1]
        pieces = []
        for (a, b), k1 in s1.items():
            if k1 != kind:
                continue
            ts = []
            for w in (a, b):
                Q = F(P1, w)
                cr = (Q[0] - A[0]) * d[1] - (Q[1] - A[1]) * d[0]
                if cr != 0:
                    break
                ts.append(((Q[0] - A[0]) * d[0] + (Q[1] - A[1]) * d[1]) / dd)
            if len(ts) == 2 and 0 <= min(ts) and max(ts) <= 1:
                pieces.append((min(ts), max(ts), (a, b)))
        pieces.sort()
        if not pieces or pieces[0][0] != 0 or pieces[-1][1] != 1 or any(pieces[i][1] != pieces[i + 1][0] for i in range(len(pieces) - 1)):
            return False
        used |= {p[2] for p in pieces}
    return used == set(s1)


def run(algo, P, T, G, preds):
    t = time.time()
    sizes = []
    saved = mr._non_obtuse_exact
    try:
        for p in preds:
            if algo == "old":
                mr._non_obtuse_exact = lambda *a: True          # the green quality test always passes = the old closure
                P, T, G = mr.refine_mesh_near(P, T, G, p, levels=1)
            elif algo == "red_promotion":
                P, T, G = mr.refine_mesh_near(P, T, G, p, levels=1)
            else:
                P, T, G = rgb.refine_mesh_near_rgb(P, T, G, p, levels=1)
            mr._non_obtuse_exact = saved
            sizes.append(int(len(T)))
            if len(T) > CAP:
                return None, sizes, round(time.time() - t, 2)
    finally:
        mr._non_obtuse_exact = saved
    return (P, T, G), sizes, round(time.time() - t, 2)


def grid(nx, ny, h=1.0):
    pts = np.array([[i * h, j * h, 0.0] for j in range(ny + 1) for i in range(nx + 1)])
    tris = []
    for j in range(ny):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
    return pts, np.array(tris), np.full(len(tris), 10)


def main():
    import meshio
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import derive_implant_windows_refinement
    out = {}
    cases = []
    P, T, G = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], float), np.array([[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4]]), np.full(4, 10)
    cases.append(("counterexample_2cells", P, T, G, [lambda c: c[0] < 1 and c[1] < 0.5]))
    P, T, G = grid(10, 10)
    for lv in (1, 2, 3):
        cases.append((f"grid10_window_x5_levels{lv}", P, T, G, [lambda c: abs(c[0] - 5.0) < 1.0] * lv))
    E6ER1 = os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu")
    WAFER = os.path.join(ROOT, "docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/wafer_volume.vtu")
    for label, path, bg, win in (("B_recipe_1e16", E6ER1, (1e16, 0.0), 1e16), ("B_mesh_gui_default_1e20", E6ER1, (0.0, 1e17), 1e20),
                                 ("wafer_volume_gui_default_1e20", WAFER, (0.0, 1e17), 1e20)):
        m = meshio.read(path)
        P0, T0, G0 = m.points, m.cells[0].data, m.cell_data["Material"][0]
        pr = ProcessResult(volume_mesh_path=path, material_field="Material", material_regions=[MaterialRegion(name="Si", tag=int(G0[0]))])
        wr = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=bg[0], acceptor_background_cm3=bg[1],
                                          windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": win, "acceptor_conc_cm3": 0.0},
                                                   {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": win, "acceptor_conc_cm3": 0.0}],
                                          chemical_state="ACTIVE")
        cases.append((label, P0, T0, G0, derive_implant_windows_refinement(wr.doping, P0, T0)))
    for label, P0, T0, G0, preds in cases:
        out[label] = {"input": {"triangles": int(len(T0)), "predicates": len(preds)}}
        for algo in ("old", "red_promotion", "rgb_prototype"):
            res, sizes, wall = run(algo, P0, T0, G0, preds)
            r = {"sizes_per_pass": sizes, "wall_s": wall}
            if res is None:
                r["stopped"] = f"triangles > {CAP}"
            else:
                r.update(exact_report(*res, P0, T0, G0) if len(res[1]) <= 60000 else {"triangles": int(len(res[1])), "exact_checks": "skipped (> 60000 triangles)"})
                if label.startswith("grid10"):
                    kept = {tuple(map(int, t)) for t in res[1]}
                    ch = [t for t in T0 if tuple(map(int, t)) not in kept]
                    cx = [float(np.asarray(P0, float)[list(t)].mean(0)[0]) for t in ch]
                    r["original_triangles_changed"] = len(ch)
                    r["changed_centroid_x_range"] = [min(cx), max(cx)] if cx else None
            out[label][algo] = r
            print(label, algo, json.dumps(r)[:400], flush=True)
    json.dump(out, open(sys.argv[1], "w", encoding="utf-8", newline="\n"), indent=1)


if __name__ == "__main__":
    main()
