"""Batch 7H-C section 6: call the UNMODIFIED production
tcad.device.devsim.solve.run_basic_potential_solve on registered fixtures and
read the assembled matrix through the public get_matrix_and_rhs. One mesh per
process. Also reports the solved potential vs phi = x/L."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import dev_run as dr  # noqa: E402


def main(mesh):
    import devsim as dv
    from tcad.device.devsim.solve import run_basic_potential_solve  # production, unmodified
    P, regions, _ = dr.load_mesh(mesh)
    contacts, region_of, _ = dr.build_device(dv, P, regions, "LR")
    ret = run_basic_potential_solve(device="d", region="R", contact_bias={"left": 0.0, "right": 1.0})
    J, rhs = dr.matrix_dense(dv)
    eqn = np.array(dv.get_equation_numbers(device="d", region="R", equation="PotentialEquation"))
    x = np.array(dv.get_node_model_values(device="d", region="R", name="x"))
    phi = np.array(dv.get_node_model_values(device="d", region="R", name="Potential"))
    dv.edge_from_node_model(device="d", region="R", node_model="node_index")
    n0 = np.array(dv.get_edge_model_values(device="d", region="R", name="node_index@n0")).astype(int)
    n1 = np.array(dv.get_edge_model_values(device="d", region="R", name="node_index@n1")).astype(int)
    C = np.array(dv.get_edge_model_values(device="d", region="R", name="EdgeCouple"))
    Le = np.array(dv.get_edge_model_values(device="d", region="R", name="EdgeLength"))
    cn = {v for e in contacts["left"] + contacts["right"] for v in e}
    rel_c2, rel_col = [], []
    for k, (a, b) in enumerate(zip(n0, n1)):
        for i, j in ((a, b), (b, a)):
            if i not in cn and C[k] != 0:
                w = -J[eqn[i], eqn[j]]
                rel_c2.append(abs(w - C[k] ** 2) / C[k] ** 2)
                rel_col.append(abs(w - C[k] / Le[k]) / (C[k] / Le[k]))
    free = [i for i in range(len(x)) if i not in cn]
    err = phi - (x - x.min()) / (x.max() - x.min())
    return {"mesh": mesh, "production_return": ret, "n_weights": len(rel_c2),
            "max_rel_w_vs_EdgeCouple_squared": max(rel_c2), "max_rel_w_vs_EdgeCouple_over_EdgeLength": max(rel_col),
            "Linf_free_V_vs_x_over_L": float(np.abs(err[free]).max())}


if __name__ == "__main__":
    r = main(sys.argv[1])
    print("===RESULT_JSON===")
    print(json.dumps(r, default=float))
