"""Batch 7H-D supplementary diagnostic: does DEVSIM's reported contact current
use the SAME edge couple as the bulk override? M4 has 10 negative signed couple
edges touching a contact node, so override and default couples differ there.
Same build / production setup / sg_lib.solve / forward schedule as sg_worker.
Compares get_contact_current(ElectronContinuityEquation, left) at +0.10 V with
sum over edges incident to exactly one left-contact node of ElectronCurrent x
couple, for couple = OvEdgeCouple and couple = EdgeCouple (orientation: sign
+1 when the contact node is n0, -1 when it is n1; both signs reported).
usage: diag_contact_current.py D2|D0"""
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


def main(variant):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    cfg = {"kind": "2d", "mesh": "M4", "variant": variant}
    sw.build(dv, cfg)
    x = np.array(dv.get_node_model_values(device="d", region=sl.REGION, name="x"))
    left = set(np.where(x == x.min())[0].tolist())
    setup_semiconductor_potential_equation("d", sl.REGION, ["left", "right"], 300.0)
    ok, _ = sl.solve(dv, "poisson", "A")
    setup_drift_diffusion_equation("d", sl.REGION, ["left", "right"])
    ok = ok and sl.solve(dv, "dd", "B0")[0]
    for v in sw.FWD:
        dv.set_parameter(device="d", name="left_bias", value=v)
        ok = ok and sl.solve(dv, "dd", f"C{v:+.3f}")[0]
    g = lambda n: np.array(dv.get_edge_model_values(device="d", region=sl.REGION, name=n))  # noqa: E731
    dv.edge_from_node_model(device="d", region=sl.REGION, node_model="node_index")
    n0, n1 = g("node_index@n0").astype(int), g("node_index@n1").astype(int)
    jn = g("ElectronCurrent")
    sgn = np.array([1.0 if (a in left and b not in left) else (-1.0 if (b in left and a not in left) else 0.0)
                    for a, b in zip(n0, n1)])
    out = {"variant": variant, "all_solves_ok": bool(ok),
           "I_api_left_ECE_A_per_cm": float(dv.get_contact_current(device="d", contact="left",
                                                                     equation=sl.ECE)),
           "n_edges_one_left_contact_node": int(np.count_nonzero(sgn))}
    names = ["EdgeCouple"] + (["OvEdgeCouple"] if variant in ("D1", "D2") else [])
    for cn in names:
        c = g(cn)
        s = float(np.sum(sgn * jn * c))
        out[f"sum_J_x_{cn}"] = s
        out[f"n_negative_{cn}_on_those_edges"] = int(np.count_nonzero((sgn != 0) & (c < 0)))
    sw.teardown(dv)
    print("===RESULT_JSON===")
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1])
