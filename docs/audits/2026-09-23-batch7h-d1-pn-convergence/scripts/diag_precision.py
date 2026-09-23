"""Batch 7H-D1 SUPPLEMENTARY diagnostic (after the registered runs; changes no
registered result). Hypothesis: the contact current read by get_contact_current is
limited by float64 resolution of Potential. Near an ohmic contact the current is
majority drift, J = q mu N (psi0 - psi1)/L, and psi0 - psi1 is ~1e-14 V while
ulp(|psi| ~ 0.417 V) = 5.55e-17 V, so J is quantized in steps of
q mu N ulp / L_contact_edge.
For 1D J1 (registered builder/solver/schedule) at +-0.10 V it records, per h:
  contact-edge psi difference in ulps, the predicted quantum, the contact currents,
  and the TOTAL current Jn + Jp on the junction edge (x = -h/2 .. +h/2), where
  |psi| ~ 0 and densities are ~1e10-1e12 cm^-3, plus min/max of Jn + Jp over all
  edges (discrete conservation along the device).
usage: diag_precision.py -> data/diag_precision.json"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
H = (0.02, 0.01, 0.005, 0.0025, 0.00125, 0.000625, 0.0003125)
Q, MU_N, MU_P, N = 1.6e-19, 400.0, 200.0, 1e17


def one(h):
    import devsim as dv
    import common_d1 as cd
    import meshes_d1 as md
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"h": h}
    for branch, target in (([0.025, 0.05, 0.075, 0.1], 0.1), ([-0.025, -0.05, -0.075, -0.1], -0.1)):
        cd.build_1d(dv, md.grid_1d(h, "J1"))
        cd.set_doping(dv, "J1")
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        cd.solve(dv, "poisson", "A")
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        cd.solve(dv, "drift_diffusion", "B0")
        oks = []
        for v in branch:
            dv.set_parameter(device="d", name="left_bias", value=v)
            oks.append(cd.solve(dv, "drift_diffusion", f"C{v:+.3f}")["ok"])
        x = np.array(dv.get_node_model_values(device="d", region=cd.REGION, name="x"))
        psi = np.array(dv.get_node_model_values(device="d", region=cd.REGION, name="Potential"))
        o = np.argsort(x)
        x, psi = x[o], psi[o]
        dv.edge_from_node_model(device="d", region=cd.REGION, node_model="x")
        ex0 = np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name="x@n0"))
        ex1 = np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name="x@n1"))
        jn = np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name="ElectronCurrent"))
        jp = np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name="HoleCurrent"))
        sgn = np.where(ex1 > ex0, 1.0, -1.0)             # orient every edge current toward +x
        jt = (jn + jp) * sgn
        mid = 0.5 * (ex0 + ex1)
        k = int(np.argmin(np.abs(mid)))
        cur = cd.currents(dv)
        rec = {"all_ok": all(oks), "I_left_total": cur["left"]["total"], "I_right_total": cur["right"]["total"],
               "kcl_rel": abs(cur["left"]["total"] + cur["right"]["total"]) / abs(cur["left"]["total"]),
               "J_junction_edge_total_plus_x": float(jt[k]), "junction_edge_mid_um": float(mid[k] / cd.UM),
               "Jt_all_edges_min": float(jt.min()), "Jt_all_edges_max": float(jt.max())}
        for side, i0, i1, mu in (("left", 0, 1, MU_P), ("right", -1, -2, MU_N)):
            d = float(psi[i0] - psi[i1])
            L = float(abs(x[i1] - x[i0]))
            ulp = float(np.spacing(abs(psi[i0])))
            rec[f"{side}_contact_edge"] = {"dpsi_V": d, "dpsi_in_ulps": d / ulp, "ulp_V": ulp, "L_cm": L,
                                           "current_quantum_A_per_cm2": Q * mu * N * ulp / L}
        out[f"{target:+.2f}"] = rec
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(one(float(sys.argv[1]))))
        sys.exit(0)
    res = {}
    for h in H:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), str(h)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        res[str(h)] = json.loads([ln for ln in p.stdout.splitlines() if ln.startswith('{"h"')][-1])
    with open(os.path.join(HERE, "..", "data", "diag_precision.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1)
    for V in ("+0.10", "-0.10"):
        print(f"--- V = {V} V")
        for h, r in res.items():
            q = r[V]
            print(f"h={h:<9} ok={q['all_ok']} I_left={q['I_left_total']:.7e} I_right={q['I_right_total']:.7e} "
                  f"KCL={q['kcl_rel']:.2e} J_junc={q['J_junction_edge_total_plus_x']:.9e} "
                  f"Jt[min,max]=[{q['Jt_all_edges_min']:.4e},{q['Jt_all_edges_max']:.4e}] "
                  f"L:dpsi={q['left_contact_edge']['dpsi_in_ulps']:.1f}ulp q={q['left_contact_edge']['current_quantum_A_per_cm2']:.2e} "
                  f"R:dpsi={q['right_contact_edge']['dpsi_in_ulps']:.1f}ulp q={q['right_contact_edge']['current_quantum_A_per_cm2']:.2e}")
