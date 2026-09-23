"""Batch 7H-D1 section 2: quantify the J0 (x == 0 -> NetDoping 0) intrinsic stripe
WITHOUT any solve. (a) 1D J0 grids at every h (DEVSIM import only);
(b) the 7H-D fixtures M1-M4 (h = 0.02 um, read-only), DEVSIM default NodeVolume
and signed F2 volume; the exact left/right split of each x = 0 node's signed
CV (exact rational clipping, build_fixtures_d1.j2 pieces).
Missing inventory = what J1 would assign to that CV: NA * (left part) + ND * (right part).
Units: 1D per cm^2 of junction area; 2D per cm of depth."""
import json
import os
import sys
from fractions import Fraction as Fr

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common_d1 as cd  # noqa: E402
import meshes_d1 as md  # noqa: E402
import build_fixtures_d1 as bf  # noqa: E402

UM = cd.UM


def x0_split(P, tris):
    """exact signed left / total CV area (um^2) of every x == 0 node."""
    zero = set(np.where(P[:, 0] == 0.0)[0].tolist())
    left, total = {i: Fr(0) for i in zero}, {i: Fr(0) for i in zero}
    for t in tris:
        if not zero.intersection(t):
            continue
        Q = [(Fr(float(P[v, 0])), Fr(float(P[v, 1]))) for v in t]
        c = bf._circ(*Q)
        for k in range(3):
            if t[k] not in zero:
                continue
            i, j, l = k, (k + 1) % 3, (k + 2) % 3
            mij = ((Q[i][0] + Q[j][0]) / 2, (Q[i][1] + Q[j][1]) / 2)
            mil = ((Q[i][0] + Q[l][0]) / 2, (Q[i][1] + Q[l][1]) / 2)
            for sub in ((Q[i], mij, c), (Q[i], c, mil)):
                total[t[i]] += bf._area(list(sub))
                left[t[i]] += bf._clip_left(list(sub))
    return float(sum(left.values())), float(sum(total.values()))


def main():
    import devsim as dv
    out = {"1D": {}, "2D_7HD_fixtures": {}}
    for h in md.H_1D:
        xs = md.grid_1d(h, "J0")
        cd.build_1d(dv, xs)
        x = np.array(dv.get_node_model_values(device="d", region=cd.REGION, name="x"))
        nv = np.array(dv.get_node_model_values(device="d", region=cd.REGION, name="NodeVolume"))
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
        z = np.where(x == 0.0)[0]
        w = float(nv[z].sum())                        # cm (1D NodeVolume)
        out["1D"][str(h)] = {"n_nodes": int(len(x)), "x0_nodes": int(len(z)), "sum_NodeVolume_x0_cm": w,
                             "stripe_width_um": w / UM, "fraction_of_domain": w / (1.0 * UM),
                             "missing_acceptor_cm-2": cd.NA * w / 2, "missing_donor_cm-2": cd.ND * w / 2,
                             "missing_total_over_side_inventory": (cd.NA * w / 2) / (cd.NA * 0.5 * UM)}
    f7 = json.load(open(os.path.join(cd.DATA, "..", "..", "2026-09-23-batch7h-d-sg-pn-mesh-validity", "data",
                                     "fixtures_7hd.json"), encoding="utf-8"))
    for name in ("M1", "M2", "M3", "M4"):
        P, tris = np.array(f7[name]["points_um"]), f7[name]["triangles"]
        cd.build_2d(dv, P, tris, dev="q")
        nv = np.array(dv.get_node_model_values(device="q", region=cd.REGION, name="NodeVolume"))
        dv.delete_device(device="q")
        dv.delete_mesh(mesh="m_q")
        sv = cd.fm.node_areas(P * UM, [list(t) for t in tris], "F2")
        z = np.where(P[:, 0] == 0.0)[0]
        lft, tot = x0_split(P, [list(t) for t in tris])
        H = 0.1 * UM
        r = {"x0_nodes": int(len(z))}
        for lab, V in (("default", nv), ("signed", sv)):
            s = float(V[z].sum())
            r[lab] = {"sum_NodeVolume_x0_cm2": s, "fraction_of_domain": s / (1.0 * UM * H),
                      "stripe_width_um": s / H / UM, "missing_total_cm-1_assuming_half_half": cd.NA * s}
        r["signed_exact_split"] = {"left_um2": lft, "total_um2": tot,
                                   "missing_acceptor_cm-1": cd.NA * lft * UM * UM,
                                   "missing_donor_cm-1": cd.ND * (tot - lft) * UM * UM}
        out["2D_7HD_fixtures"][name] = r
    with open(os.path.join(cd.DATA, "j0_stripe.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
