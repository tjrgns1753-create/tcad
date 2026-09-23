"""Batch 7H-D2: freeze the h = 0.00125 um M1/M2/M3 meshes with the 7H-D1 builder,
quality, exact J2 check and inventory (7H-D1 scripts imported read-only; their
own main() is NOT called, nothing is written into the 7H-D1 folder).
h = 0.02 / 0.005 / 0.0025 um fixtures are read from 7H-D1 data/fixtures_d1.json.
-> data/fixtures_d2.json"""
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common_d2 as c2  # noqa: E402

md, bf, cd = c2.md, c2.bf, c2.cd
H = 0.00125


def main():
    import devsim as dv
    out = {}
    for fam in md.FAMILIES:
        P, tris = md.build(fam, H)
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
            a, d = cd.NA * V[L].sum(), cd.ND * V[R].sum()
            inv[name] = {"acceptor_cm-1": float(a), "donor_cm-1": float(d), "rel_asymmetry": float(abs(a - d) / a),
                         "sum_over_area": float(V.sum() / area)}
        q.update({"h_um": H, "zero_doped_junction_nodes": int(np.sum(P[:, 0] == 0.0)), "inventory": inv,
                  "j2": bf.j2_check(P, tris, H),
                  "connectivity_sha256": hashlib.sha256(json.dumps(sorted(sorted(t) for t in tris)).encode()).hexdigest(),
                  "coordinates_sha256": hashlib.sha256(np.ascontiguousarray(P).tobytes()).hexdigest()})
        out[f"{fam}_h{H}"] = {"points_um": P.tolist(), "triangles": tris, "quality": q}
        print(f"{fam}_h{H}", json.dumps({k: v for k, v in q.items() if not k.endswith("sha256")}), flush=True)
    p = os.path.join(c2.DATA, "fixtures_d2.json")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, sort_keys=True)
    print("fixtures_d2.json sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
