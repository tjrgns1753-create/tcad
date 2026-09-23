"""Batch 7H-D supplementary diagnostic (added after the registered runs; changes
no registered setting). For M4 it lists EVERY same-variable off-diagonal entry
whose sign is opposite to the M2 D0 sign and maps it to the DEVSIM edge
(n0, n1) and that edge's signed couple; for D1 it also reads the Poisson row
diagonal at nodes with negative signed node volume. Solver settings are the
same sg_lib.solve (DEVIATIONS.md item 1). One configuration per process.
usage: diag_m4_blocks.py D2|D1"""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sg_lib as sl  # noqa: E402
import sg_worker as sw  # noqa: E402

EXPECTED = {sl.PE: -1, sl.ECE: +1, sl.HCE: -1}   # observed on M2 D0 (analysis_synth.json)


def entries(dv, eqs, contact_nodes):
    m = dv.get_matrix_and_rhs(format="csr")["static"]
    ap, ai, av = np.array(m["ap"]), np.array(m["ai"]), np.array(m["av"])
    out = {}
    for e in eqs:
        rows = np.array(dv.get_equation_numbers(device="d", region=sl.REGION, equation=e))
        col_of = {int(r): k for k, r in enumerate(rows)}
        bad, diag = [], {}
        for k, r in enumerate(rows):
            for q in range(ap[r], ap[r + 1]):
                c = int(ai[q])
                if c == r:
                    diag[k] = float(av[q])
                elif c in col_of and k not in contact_nodes and np.sign(av[q]) == -EXPECTED[e]:
                    bad.append((k, col_of[c], float(av[q])))
        out[e] = {"violations": bad, "diag": diag}
    return out


def main(variant):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    cfg = {"kind": "2d", "mesh": "M4", "variant": variant}
    cn, vinfo = sw.build(dv, cfg)
    couple, vol = sl.signed_geometry(dv)
    n0 = [int(v) for v in dv.get_edge_model_values(device="d", region=sl.REGION, name="node_index@n0")]
    n1 = [int(v) for v in dv.get_edge_model_values(device="d", region=sl.REGION, name="node_index@n1")]
    neg_edges = {(min(a, b), max(a, b)): c for a, b, c in zip(n0, n1, couple) if c < 0}
    neg_vol_nodes = [i for i, v in enumerate(vol) if v < 0]
    setup_semiconductor_potential_equation("d", sl.REGION, ["left", "right"], 300.0)
    okA, _ = sl.solve(dv, "poisson", "A")
    res = {"variant": variant, "poisson_ok": okA, "n_neg_couple_edges": len(neg_edges),
           "n_neg_couple_edges_touching_contact": sum(1 for (a, b) in neg_edges if a in cn or b in cn),
           "n_neg_volume_nodes": len(neg_vol_nodes)}
    if okA:
        setup_drift_diffusion_equation("d", sl.REGION, ["left", "right"])
        okB, _ = sl.solve(dv, "dd", "B0")
        res["dd_ok"] = okB
        eqs = (sl.PE, sl.ECE, sl.HCE) if okB else (sl.PE,)
    else:
        eqs = (sl.PE,)   # Jacobian at the state DEVSIM restored after the failed solve
    ent = entries(dv, eqs, cn)
    for e, d in ent.items():
        pairs = {(min(k, c), max(k, c)) for k, c, _ in d["violations"]}
        noncontact_neg = {p for p in neg_edges if p[0] not in cn and p[1] not in cn}
        res[e] = {"n_violations": len(d["violations"]), "n_violating_edges": len(pairs),
                  "violating_edges_all_negative_couple": pairs <= set(neg_edges),
                  "noncontact_negative_couple_edges_all_violating": noncontact_neg <= pairs,
                  "n_noncontact_negative_couple_edges": len(noncontact_neg),
                  "violations_sample": d["violations"][:10]}
        if e == sl.PE:
            dneg = [d["diag"][i] for i in neg_vol_nodes if i not in cn]
            dpos = [v for i, v in d["diag"].items() if i not in cn and i not in neg_vol_nodes]
            res[e]["diag_at_negative_volume_nodes"] = dneg
            res[e]["diag_other_nodes_min_max"] = [min(dpos), max(dpos)]
            res[e]["n_nonpositive_diag"] = sum(1 for i, v in d["diag"].items() if i not in cn and v <= 0)
    sw.teardown(dv)
    print("===RESULT_JSON===")
    print(json.dumps(res))


if __name__ == "__main__":
    main(sys.argv[1])
