"""Batch 7H-D1 worker: ONE configuration per process.
cfg: {"kind":"1d","h":h,"junction":"J1"|"J0"} or {"kind":"2d","fam":"M1"|"M2"|"M3","h":h,"variant":"D0"|"D1"}
Sequence (registered, fixed_d1.json): A equilibrium Poisson -> B 0 V DD ->
forward ramp to +0.10 V (record +0.05, +0.10) -> rebuild -> A, B -> reverse ramp
to -0.10 V (record -0.10). Every solve uses info=True; a failure is a result.
Prints ===RESULT_JSON=== then one JSON line."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common_d1 as cd  # noqa: E402
import meshes_d1 as md  # noqa: E402

FWD, REV = [0.025, 0.05, 0.075, 0.1], [-0.025, -0.05, -0.075, -0.1]
RECORD = {0.05, 0.1, -0.1}


def nodes(dv, *names):
    return {n: np.array(dv.get_node_model_values(device="d", region=cd.REGION, name=n)) for n in names}


def edges(dv, *names):
    return {n: np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name=n)) for n in names}


def lst(a):
    return [float(v) for v in a]


def build(dv, cfg):
    if cfg["kind"] == "1d":
        cd.build_1d(dv, md.grid_1d(cfg["h"], cfg["junction"]))
        cd.set_doping(dv, cfg["junction"])
        return {"variant": "1D"}
    f = json.load(open(os.path.join(cd.DATA, "fixtures_d1.json"), encoding="utf-8"))[f"{cfg['fam']}_h{cfg['h']}"]
    cd.build_2d(dv, np.array(f["points_um"]), f["triangles"])
    cd.set_doping(dv, "J1")
    return cd.apply_variant(dv, cfg["variant"])


def summary(dv):
    s = nodes(dv, "x", "Potential", "Electrons", "Holes")
    n, p = s["Electrons"], s["Holes"]
    return {"positive_finite": bool(np.all(np.isfinite(n)) and np.all(np.isfinite(p)) and n.min() > 0 and p.min() > 0),
            "n_min": float(n.min()), "p_min": float(p.min()), "psi_min": float(s["Potential"].min()),
            "psi_max": float(s["Potential"].max())}


def contact_consistency(dv, variant):
    x = nodes(dv, "x")["x"]
    left = set(np.where(x == x.min())[0].tolist())
    dv.edge_from_node_model(device="d", region=cd.REGION, node_model="node_index")
    e = edges(dv, "node_index@n0", "node_index@n1", "ElectronCurrent")
    cname = "OvEdgeCouple" if variant in ("D1", "D2") else "EdgeCouple"
    c = edges(dv, cname)[cname]
    sgn = np.array([1.0 if (int(a) in left and int(b) not in left) else (-1.0 if (int(b) in left and int(a) not in left) else 0.0)
                    for a, b in zip(e["node_index@n0"], e["node_index@n1"])])
    s = float(np.sum(sgn * e["ElectronCurrent"] * c))
    api = float(dv.get_contact_current(device="d", contact="left", equation=cd.ECE))
    return {"couple_model": cname, "I_api_A": api, "sum_J_couple_A": s, "abs_diff": abs(api - s),
            "pass": abs(api - s) <= 1e-10 * abs(api) + 1e-30}


def run(cfg):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"cfg": cfg, "steps": {}}
    out["variant_info"] = build(dv, cfg)
    s = nodes(dv, "x", "y", "NodeVolume", "NetDoping")
    out["mesh"] = {"n_nodes": int(len(s["x"])), "x0_nodes": int(np.sum(s["x"] == 0.0))}
    setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
    inf = cd.solve(dv, "poisson", "A")
    rec = {"info": inf}
    if inf["ok"]:
        a = nodes(dv, "x", "y", "Potential", "IntrinsicElectrons", "IntrinsicHoles", "NodeVolume")
        rec["state"] = {k: lst(v) for k, v in a.items()}
        rec["max_abs_ElectricField_V_per_cm"] = float(np.max(np.abs(edges(dv, "ElectricField")["ElectricField"])))
    out["steps"]["A"] = rec
    if not inf["ok"]:
        return out
    setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
    inf = cd.solve(dv, "drift_diffusion", "B0")
    rec = {"info": inf}
    if inf["ok"]:
        b = nodes(dv, "x", "y", "Potential", "Electrons", "Holes")
        rec.update({"state": {k: lst(v) for k, v in b.items()}, "currents": cd.currents(dv), "summary": summary(dv),
                    "max_abs_edge_J_A_per_cm2": float(max(np.max(np.abs(v)) for v in edges(dv, "ElectronCurrent", "HoleCurrent").values()))})
    out["steps"]["B0"] = rec
    if not inf["ok"]:
        return out
    for v in FWD:
        dv.set_parameter(device="d", name="left_bias", value=v)
        inf = cd.solve(dv, "drift_diffusion", f"C{v:+.3f}")
        rec = {"info": inf}
        if inf["ok"] and v in RECORD:
            rec.update({"currents": cd.currents(dv), "summary": summary(dv)})
            if v == 0.1 and cfg["kind"] == "2d":
                rec["contact_consistency"] = contact_consistency(dv, cfg["variant"])
        out["steps"][f"C{v:+.3f}"] = rec
        if not inf["ok"]:
            break
    dv.delete_device(device="d")
    dv.delete_mesh(mesh="m_d")
    build(dv, cfg)
    setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
    ok = cd.solve(dv, "poisson", "Arev")["ok"]
    if ok:
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        ok = cd.solve(dv, "drift_diffusion", "B0rev")["ok"]
    out["steps"]["reverse_setup_ok"] = ok
    if ok:
        for v in REV:
            dv.set_parameter(device="d", name="left_bias", value=v)
            inf = cd.solve(dv, "drift_diffusion", f"C{v:+.3f}")
            rec = {"info": inf}
            if inf["ok"] and v in RECORD:
                rec.update({"currents": cd.currents(dv), "summary": summary(dv)})
            out["steps"][f"C{v:+.3f}"] = rec
            if not inf["ok"]:
                break
    dv.delete_device(device="d")
    dv.delete_mesh(mesh="m_d")
    out["devices_left"] = list(dv.get_device_list())
    return out


if __name__ == "__main__":
    c = json.loads(sys.argv[1])
    try:
        r = run(c)
    except Exception as e:  # noqa: BLE001
        r = {"cfg": c, "error": repr(e)[:1000]}
    print("===RESULT_JSON===")
    print(json.dumps(r))
