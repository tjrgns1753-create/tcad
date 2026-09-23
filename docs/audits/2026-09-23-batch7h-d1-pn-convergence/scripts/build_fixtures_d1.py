"""Batch 7H-D1: freeze M1(h)/M2(h)/M3(h) and their pre-solve geometry to
data/fixtures_d1.json (no equation, no solve). Per mesh:
  * 7H-D quality() (exact angle classes, exact Delaunay / boundary Gabriel,
    signed couple / signed node volume from the 7H-B formulas)
  * zero-doped junction nodes (x == 0) -> must be 0
  * J2 exact check: every triangle's signed circumcentric dual pieces
    (v_i, m_ij, c) and (v_i, c, m_ik) are clipped by x = 0 in exact rational
    arithmetic; J2 == J1 iff every node's CV lies entirely on its own side.
    Triangles farther than 4h from x = 0 (float prefilter, every vertex and the
    float circumcenter at |x| > 1e-6 um) are assigned by sign without clipping.
  * integrated acceptor / donor inventory (cm^-1 per unit depth) with DEVSIM's
    default NodeVolume (read after import) and with the signed F2 volume.
usage: build_fixtures_d1.py"""
import hashlib
import json
import os
import sys
from fractions import Fraction as Fr

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meshes_d1 as md  # noqa: E402
import common_d1 as cd  # noqa: E402

NA = ND = 1e17


def _circ(A, B, C):
    d = 2 * (A[0] * (B[1] - C[1]) + B[0] * (C[1] - A[1]) + C[0] * (A[1] - B[1]))
    a2, b2, c2 = A[0] ** 2 + A[1] ** 2, B[0] ** 2 + B[1] ** 2, C[0] ** 2 + C[1] ** 2
    return ((a2 * (B[1] - C[1]) + b2 * (C[1] - A[1]) + c2 * (A[1] - B[1])) / d,
            (a2 * (C[0] - B[0]) + b2 * (A[0] - C[0]) + c2 * (B[0] - A[0])) / d)


def _area(poly):
    return sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(poly, poly[1:] + poly[:1])) / 2 if len(poly) >= 3 else 0


def _clip_left(tri):
    out = []
    for i in range(3):
        a, b = tri[i], tri[(i + 1) % 3]
        if a[0] < 0:
            out.append(a)
        if (a[0] < 0) != (b[0] < 0):
            t = a[0] / (a[0] - b[0])
            out.append((Fr(0), a[1] + t * (b[1] - a[1])))
    return _area(out)


def j2_check(P, tris, h):
    n = len(P)
    left = [Fr(0)] * n
    total = [Fr(0)] * n
    n_exact = 0
    for t in tris:
        pf = P[t]
        if np.min(np.abs(pf[:, 0])) > 4 * h:
            cxf = _circ(*[(float(a), float(b)) for a, b in pf])[0]
            assert (np.all(pf[:, 0] > 0) and cxf > 1e-6) or (np.all(pf[:, 0] < 0) and cxf < -1e-6)
            continue
        n_exact += 1
        Q = [(Fr(float(P[v, 0])), Fr(float(P[v, 1]))) for v in t]
        c = _circ(*Q)
        for k in range(3):
            i, j, l = k, (k + 1) % 3, (k + 2) % 3
            mij = ((Q[i][0] + Q[j][0]) / 2, (Q[i][1] + Q[j][1]) / 2)
            mil = ((Q[i][0] + Q[l][0]) / 2, (Q[i][1] + Q[l][1]) / 2)
            for sub in ((Q[i], mij, c), (Q[i], c, mil)):
                total[t[i]] += _area(list(sub))
                left[t[i]] += _clip_left(list(sub))
    touched = [i for i in range(n) if total[i] != 0]
    bad = [i for i in touched if not ((P[i, 0] < 0 and left[i] == total[i]) or (P[i, 0] > 0 and left[i] == 0))]
    return {"n_triangles_clipped_exactly": n_exact, "n_nodes_with_exact_pieces": len(touched),
            "n_nodes_cv_crossing_x0": len(bad), "J2_equals_J1": not bad}


def main():
    import devsim as dv
    out = {}
    for fam in md.FAMILIES:
        for h in md.H_2D:
            P, tris = md.build(fam, h)
            q = cd.quality(P, tris)
            cd.build_2d(dv, P, tris, dev="q")
            nv = np.array(dv.get_node_model_values(device="q", region=cd.REGION, name="NodeVolume"))
            dv.delete_device(device="q")
            dv.delete_mesh(mesh="m_q")
            Pc = P * cd.UM
            sv = cd.fm.node_areas(Pc, [list(t) for t in tris], "F2")
            area = sum(cd.fm.tri_area(Pc[t]) for t in tris)
            L, R = P[:, 0] < 0, P[:, 0] > 0
            inv = {}
            for name, V in (("default", nv), ("signed", sv)):
                a, d = NA * V[L].sum(), ND * V[R].sum()
                inv[name] = {"acceptor_cm-1": float(a), "donor_cm-1": float(d), "rel_asymmetry": float(abs(a - d) / a),
                             "sum_over_area": float(V.sum() / area)}
            q.update({"h_um": h, "zero_doped_junction_nodes": int(np.sum(P[:, 0] == 0.0)), "inventory": inv,
                      "area_cm2": float(area), "mirror_points_symmetric": bool(
                          sorted(map(tuple, np.round(P, 15))) == sorted(map(tuple, np.round(P * [-1, 1], 15)))),
                      "j2": j2_check(P, tris, h),
                      "connectivity_sha256": hashlib.sha256(json.dumps(sorted(sorted(t) for t in tris)).encode()).hexdigest(),
                      "coordinates_sha256": hashlib.sha256(np.ascontiguousarray(P).tobytes()).hexdigest()})
            key = f"{fam}_h{h}"
            out[key] = {"points_um": P.tolist(), "triangles": tris, "quality": q}
            print(key, json.dumps({k: v for k, v in q.items() if not k.endswith("sha256")}), flush=True)
    p = os.path.join(cd.DATA, "fixtures_d1.json")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, sort_keys=True)
    print("fixtures_d1.json sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
