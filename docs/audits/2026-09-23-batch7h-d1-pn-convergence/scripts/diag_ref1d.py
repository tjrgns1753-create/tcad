"""Batch 7H-D1 SUPPLEMENTARY diagnostic (added after the registered runs; not a
registered input, changes no registered result). Question: is the registered 1D J1
reference current really converged? The registered levels show an irregular
pattern (finest pair agrees to ~1e-8 at -0.10/+0.05 V but the previous pair differs
1.5-2.5 %). Same builder, doping, production setup, registered solver rule and
bias schedule as worker_d1; extra levels h = 0.000625 and 0.0003125 um; every
bias step recorded with electron/hole components at both contacts.
usage: diag_ref1d.py  -> data/diag_ref1d.json"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
H = (0.005, 0.0025, 0.00125, 0.000625, 0.0003125)


def one(h):
    import devsim as dv
    import common_d1 as cd
    import meshes_d1 as md
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"h": h, "steps": {}}
    for branch in ([0.025, 0.05, 0.075, 0.1], [-0.025, -0.05, -0.075, -0.1]):
        cd.build_1d(dv, md.grid_1d(h, "J1"))
        cd.set_doping(dv, "J1")
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        ok = cd.solve(dv, "poisson", "A")["ok"]
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        inf = cd.solve(dv, "drift_diffusion", "B0")
        out["steps"]["0.000"] = {"info_ok": inf["ok"], "currents": cd.currents(dv)}
        for v in branch:
            dv.set_parameter(device="d", name="left_bias", value=v)
            inf = cd.solve(dv, "drift_diffusion", f"C{v:+.3f}")
            out["steps"][f"{v:+.3f}"] = {"info_ok": inf["ok"], "rel": inf.get("final_device_rel"),
                                         "iterations": inf.get("iterations"), "currents": cd.currents(dv)}
        out["n_nodes"] = len(dv.get_node_model_values(device="d", region=cd.REGION, name="x"))
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("===RESULT_JSON===")
        print(json.dumps(one(float(sys.argv[1]))))
        sys.exit(0)
    res = {}
    for h in H:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), str(h)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        res[str(h)] = json.loads([ln for ln in p.stdout.splitlines() if ln.startswith('{"h"')][-1])  # DEVSIM C output can interleave after the marker
    with open(os.path.join(HERE, "..", "data", "diag_ref1d.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1)
    vs = ["-0.100", "-0.075", "-0.050", "-0.025", "+0.025", "+0.050", "+0.075", "+0.100"]
    print("h".ljust(10), *[v.rjust(14) for v in vs])
    for h, r in res.items():
        print(h.ljust(10), *["%14.7e" % r["steps"][v]["currents"]["left"]["total"] for v in vs], r["n_nodes"],
              all(s["info_ok"] for s in r["steps"].values()))
    for h, r in res.items():
        s = r["steps"]["+0.100"]["currents"]
        print(h, "+0.1 left e/h", s["left"]["ElectronContinuityEquation"], s["left"]["HoleContinuityEquation"],
              "right e/h", s["right"]["ElectronContinuityEquation"], s["right"]["HoleContinuityEquation"])
