"""Batch 7H-D worker: ONE configuration per process.
cfg: {"kind": "1d", "dx_um": ..., "x_range_um": [..]} or
     {"kind": "2d", "mesh": "M1".."M4" | "L3_after", "variant": "D0".."D3"}
Prints ===RESULT_JSON=== then one JSON line. Solve failures are recorded,
never retried with different settings."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sg_lib as sl  # noqa: E402

FWD = [0.025, 0.05, 0.075, 0.10]
REV = [-0.025, -0.05, -0.075, -0.10]
RECORD = {0.05, 0.10, -0.10}


def load_mesh(name):
    if name.startswith("L3_"):
        f = json.load(open(os.path.join(sl.DATA, "..", "..", "2026-09-23-batch7h-c-flux-discretization", "data",
                                        "l3_meshes.json"), encoding="utf-8"))  # 7H-C export, read-only, sha 8206a9a5...
        return np.array(f["points_um"]), f[name]
    f = json.load(open(os.path.join(sl.DATA, "fixtures_7hd.json"), encoding="utf-8"))[name]
    return np.array(f["points_um"]), f["triangles"]


def arr(s, keys):
    return {k: [float(v) for v in s[k]] for k in keys if k in s}


def build(dv, cfg):
    if cfg["kind"] == "1d":
        sl.build_1d(dv, cfg["dx_um"], tuple(cfg.get("x_range_um", (-0.5, 0.5))))
        x = np.array(dv.get_node_model_values(device="d", region=sl.REGION, name="x"))
        contact_nodes = {int(np.argmin(x)), int(np.argmax(x))}
    else:
        P, tris = load_mesh(cfg["mesh"])
        info = sl.build_2d(dv, P, tris)
        contact_nodes = set(info["left_nodes"]) | set(info["right_nodes"])
    sl.set_doping(dv)
    vinfo = sl.apply_variant(dv, cfg.get("variant", "D0")) if cfg["kind"] == "2d" else {"variant": "1D"}
    return contact_nodes, vinfo


def teardown(dv):
    dv.delete_device(device="d")
    dv.delete_mesh(mesh="m_d")


def run(cfg):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"cfg": cfg, "steps": {}}
    cn, vinfo = build(dv, cfg)
    out["variant_info"] = vinfo
    out["n_nodes"] = len(dv.get_node_model_values(device="d", region=sl.REGION, name="x"))
    # ---- Experiment A: equilibrium Poisson (production setup, unmodified)
    setup_semiconductor_potential_equation("d", sl.REGION, ["left", "right"], 300.0)
    ok, err = sl.solve(dv, "poisson", "A")
    s = sl.state(dv, with_carriers=False)
    s["n"] = np.array(dv.get_node_model_values(device="d", region=sl.REGION, name="IntrinsicElectrons"))
    s["p"] = np.array(dv.get_node_model_values(device="d", region=sl.REGION, name="IntrinsicHoles"))
    out["steps"]["A_poisson"] = {"ok": ok, "err": err, "state": arr(s, ("x", "y", "psi", "n", "p", "C", "V")),
                                 "blocks": sl.matrix_blocks(dv, eqs=(sl.PE,), contact_nodes=cn) if ok else None}
    if not ok:
        teardown(dv)
        return out
    # ---- Experiment B: zero-bias DD (production setup, unmodified)
    setup_drift_diffusion_equation("d", sl.REGION, ["left", "right"])
    ok, err = sl.solve(dv, "dd", "B0")
    st = {"ok": ok, "err": err}
    if ok:
        s = sl.state(dv)
        st.update({"state": arr(s, ("x", "y", "psi", "n", "p")), "currents": sl.currents(dv),
                   "blocks": sl.matrix_blocks(dv, eqs=(sl.PE, sl.ECE, sl.HCE), contact_nodes=cn)})
    out["steps"]["B_0V"] = st
    if ok:
        for v in FWD:
            dv.set_parameter(device="d", name="left_bias", value=v)
            ok, err = sl.solve(dv, "dd", f"C{v:+.3f}")
            rec = {"ok": ok, "err": err}
            if ok and v in RECORD:
                s = sl.state(dv)
                rec.update({"state": arr(s, ("x", "y", "psi", "n", "p")), "currents": sl.currents(dv)})
                if v == 0.10:
                    rec["blocks"] = sl.matrix_blocks(dv, eqs=(sl.PE, sl.ECE, sl.HCE), contact_nodes=cn)
            out["steps"][f"C_{v:+.3f}"] = rec
            if not ok:
                break
    teardown(dv)
    # ---- reverse branch on a rebuilt device
    if out["steps"]["B_0V"]["ok"]:
        cn, _ = build(dv, cfg)
        setup_semiconductor_potential_equation("d", sl.REGION, ["left", "right"], 300.0)
        ok, _ = sl.solve(dv, "poisson", "Arev")
        if ok:
            setup_drift_diffusion_equation("d", sl.REGION, ["left", "right"])
            ok, _ = sl.solve(dv, "dd", "B0rev")
        out["steps"]["reverse_setup_ok"] = ok
        if ok:
            for v in REV:
                dv.set_parameter(device="d", name="left_bias", value=v)
                ok, err = sl.solve(dv, "dd", f"C{v:+.3f}")
                rec = {"ok": ok, "err": err}
                if ok and v in RECORD:
                    s = sl.state(dv)
                    rec.update({"state": arr(s, ("x", "y", "psi", "n", "p")), "currents": sl.currents(dv),
                                "blocks": sl.matrix_blocks(dv, eqs=(sl.PE, sl.ECE, sl.HCE), contact_nodes=cn)})
                out["steps"][f"C_{v:+.3f}"] = rec
                if not ok:
                    break
        teardown(dv)
    out["devices_left"] = list(dv.get_device_list())
    return out


if __name__ == "__main__":
    cfg = json.loads(sys.argv[1])
    try:
        r = run(cfg)
    except Exception as e:
        r = {"cfg": cfg, "error": repr(e)[:1000]}
    print("===RESULT_JSON===")
    print(json.dumps(r))
