"""Batch 7H-D section 5: freeze M1-M4 (points, triangles) and pre-solve
geometry to data/fixtures_7hd.json. Imports each mesh into DEVSIM only to
read the default NodeVolume (no equation, no solve)."""
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meshes_7hd as mh  # noqa: E402
import sg_lib as sl  # noqa: E402

eg = mh.eg
AUD = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-exact-flip-certification", "scripts"))
import exact_flip as ef  # noqa: E402


def quality(P, tris):
    ipts, K = eg.exact_integer_points(P)
    cls = {"acute": 0, "right": 0, "obtuse": 0}
    angs = []
    for t in tris:
        Q = [ipts[v] for v in t]
        d = [(Q[(k + 1) % 3][0] - Q[k][0]) * (Q[(k + 2) % 3][0] - Q[k][0]) + (Q[(k + 1) % 3][1] - Q[k][1]) * (Q[(k + 2) % 3][1] - Q[k][1]) for k in range(3)]
        cls["obtuse" if min(d) < 0 else ("right" if min(d) == 0 else "acute")] += 1
        for k in range(3):
            u, v = P[t[(k + 1) % 3]] - P[t[k]], P[t[(k + 2) % 3]] - P[t[k]]
            angs.append(np.degrees(np.arccos(np.clip(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v), -1, 1))))
    owners, bset, _, _ = eg.edge_sets([list(t) for t in tris], [0] * len(tris))
    prot = frozenset(e for e, _ in bset)
    viol = ef.exact_violations(ipts, [list(t) for t in tris], [0] * len(tris), prot)
    gabriel = 0
    for e, o in owners.items():
        if len(o) == 1:
            t = tris[o[0]]
            c = [v for v in t if v not in e][0]
            A, B, C = ipts[e[0]], ipts[e[1]], ipts[c]
            if (A[0] - C[0]) * (B[0] - C[0]) + (A[1] - C[1]) * (B[1] - C[1]) < 0:
                gabriel += 1
    scan, _ = eg.global_exact_scan(ipts, [list(t) for t in tris], K)
    Pc = P * sl.UM
    g1, _, _ = sl.fm.edge_couple_predictions(Pc, [list(t) for t in tris])
    vol = sl.fm.node_areas(Pc, [list(t) for t in tris], "F2")
    cp = np.array(list(g1.values()))
    return {"n_nodes": len(P), "n_triangles": len(tris), "classes": cls, "min_angle_deg": float(min(angs)),
            "max_angle_deg": float(max(angs)), "all_ccw": all(eg.orient(*[ipts[v] for v in t]) > 0 for t in tris),
            "exact_delaunay_violations_interior": len(viol), "boundary_gabriel_violations": gabriel,
            "exact_positive_overlaps": scan["counts"]["EXACT_POSITIVE_AREA_OVERLAP"],
            "signed_edge_couple": {"negative": int((cp < 0).sum()), "zero": int((cp == 0).sum()), "positive": int((cp > 0).sum()),
                                   "min_cm": float(cp.min())},
            "signed_node_volume": {"negative": int((vol < 0).sum()), "zero": int((vol == 0).sum()), "positive": int((vol > 0).sum()),
                                   "min_cm2": float(vol.min())},
            "x0_column_nodes": int(sum(1 for x, _ in P if x == 0.0)),
            "left_contact_nodes": int(sum(1 for x, _ in P if x == P[:, 0].min())),
            "right_contact_nodes": int(sum(1 for x, _ in P if x == P[:, 0].max())),
            "area_exact_um2": str(eg.Fraction(sum(abs(eg.orient(*[ipts[v] for v in t])) for t in tris), 2 * (1 << (2 * K))))}


def main():
    import devsim as dv
    out = {}
    for name, f in mh.FAMILIES.items():
        P, tris = f()
        P = np.asarray(P, dtype=float)
        tris = [[int(v) for v in t] for t in tris]
        q = quality(P, tris)
        sl.build_2d(dv, P, tris, dev="q" + name)
        nv = np.array(dv.get_node_model_values(device="q" + name, region=sl.REGION, name="NodeVolume"))
        area = sum(sl.fm.tri_area(P[t] * sl.UM) for t in tris)
        dv.delete_device(device="q" + name)
        dv.delete_mesh(mesh="m_q" + name)
        q["devsim_default_sum_NodeVolume_over_area"] = float(nv.sum() / area)
        q["connectivity_sha256"] = hashlib.sha256(json.dumps(sorted(sorted(t) for t in tris)).encode()).hexdigest()
        q["coordinates_sha256"] = hashlib.sha256(np.ascontiguousarray(P).tobytes()).hexdigest()
        out[name] = {"points_um": P.tolist(), "triangles": tris, "quality": q}
        print(name, {k: v for k, v in q.items() if not k.endswith("sha256")})
    p = os.path.join(sl.DATA, "fixtures_7hd.json")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("fixtures_7hd.json sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
