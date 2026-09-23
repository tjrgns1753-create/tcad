"""Batch 7H-D1 SUPPLEMENTARY diagnostic (after the registered runs; changes no
registered result). diag_precision.py showed get_contact_current is quantized by
float64 ulp(Potential) at the contact edge. This re-runs the SAME registered
builders / production setup / solver rule / bias schedule and reads a
precision-robust observable: the total current crossing the junction line x = 0,
  I_junc = sum over edges with endpoints on opposite sides of x = 0 of
           (ElectronCurrent + HoleCurrent) * couple_used, oriented toward +x
(1D: couple = 1, A/cm^2; 2D: EdgeCouple for D0, OvEdgeCouple for D1, A/cm).
At x = 0 |psi| ~ 0 and n, p ~ 1e10-1e12 cm^-3, so no contact-edge quantization.
usage: diag_junction_current.py -> data/diag_junction_current.json"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
H1D = (0.02, 0.01, 0.005, 0.0025, 0.00125, 0.000625, 0.0003125)
H2D = (0.02, 0.01, 0.005, 0.0025)
REC = {0.05: "+0.050", 0.1: "+0.100", -0.1: "-0.100"}


def one(cfg):
    import devsim as dv
    import common_d1 as cd
    import worker_d1 as wk
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"cfg": cfg}
    for branch in ([0.025, 0.05, 0.075, 0.1], [-0.025, -0.05, -0.075, -0.1]):
        wk.build(dv, cfg)
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        ok = cd.solve(dv, "poisson", "A")["ok"]
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        ok = ok and cd.solve(dv, "drift_diffusion", "B0")["ok"]
        dv.edge_from_node_model(device="d", region=cd.REGION, node_model="x")
        cname = "OvEdgeCouple" if cfg.get("variant") in ("D1", "D2") else "EdgeCouple"
        for v in branch:
            dv.set_parameter(device="d", name="left_bias", value=v)
            ok = ok and cd.solve(dv, "drift_diffusion", f"C{v:+.3f}")["ok"]
            if v in REC:
                g = lambda n: np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name=n))  # noqa: E731
                x0, x1 = g("x@n0"), g("x@n1")
                cross = (x0 * x1) < 0
                sgn = np.where(x1 > x0, 1.0, -1.0)
                ij = float(np.sum(((g("ElectronCurrent") + g("HoleCurrent")) * g(cname) * sgn)[cross]))
                cur = cd.currents(dv)
                out[REC[v]] = {"ok": bool(ok), "I_junction": ij, "n_crossing_edges": int(cross.sum()),
                               "I_left": cur["left"]["total"], "I_right": cur["right"]["total"]}
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    return out


def configs():
    c = [{"id": f"1D_J1_h{h}", "kind": "1d", "h": h, "junction": "J1"} for h in H1D]
    c += [{"id": f"{f}_{v}_h{h}", "kind": "2d", "fam": f, "h": h, "variant": v}
          for f, vs in (("M1", ("D0",)), ("M2", ("D0",)), ("M3", ("D0", "D1"))) for v in vs for h in H2D]
    return c


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("RESULT " + json.dumps(one(json.loads(sys.argv[1]))))
        sys.exit(0)
    res = {}
    for cfg in configs():
        p = subprocess.run([sys.executable, os.path.abspath(__file__), json.dumps(cfg)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        lines = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
        res[cfg["id"]] = json.loads(lines[-1][7:]) if lines else {"error": (p.stdout + p.stderr)[-600:]}
        print(cfg["id"], {k: (v["ok"], "%.9e" % v["I_junction"]) for k, v in res[cfg["id"]].items() if k in REC.values()},
              flush=True)
    with open(os.path.join(HERE, "..", "data", "diag_junction_current.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1)
