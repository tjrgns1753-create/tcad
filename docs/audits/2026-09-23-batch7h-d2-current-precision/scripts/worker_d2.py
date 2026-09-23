"""Batch 7H-D2 worker: ONE configuration x ONE precision variant per process.
cfg: {"kind":"1d","h":h,"P":"P0".."P4","mirror":bool}
   | {"kind":"2d","fam":"M1"|"M2"|"M3","variant":"D0"|"D1","h":h,"P":..,"mirror":bool}
Sequence (as 7H-D1): A Poisson -> B 0 V DD -> +0.025..+0.10 (record +0.05, +0.10)
-> rebuild -> A, B -> -0.025..-0.10 (record -0.10). Bias on the p contact
(left; right when mirror). Every measured quantity is read from DEVSIM's own
public node/edge model values or get_contact_current.

Orientation: DEVSIM ElectronCurrent / HoleCurrent edge models are conventional
current density flowing n0 -> n1 (checked: sign agrees with get_contact_current).
C1 contact reconstruction: sum over edges with EXACTLY one node in the contact set
of (Jn+Jp)*couple_used*s, s = +1 if the contact node is n0 else -1 (current
leaving the contact into the device). C2 cut at x_c: node partition
L = {x < x_c}, R = {x >= x_c} (a node exactly on the cut belongs to R); every edge
with one node in L and one in R counted once, s = +1 if n0 in L else -1
(current toward +x). couple_used = OvEdgeCouple for D1, EdgeCouple otherwise.
C3 between consecutive cuts a < b: dI_n = I_n(b)-I_n(a) vs +q*sum U*V, dI_p vs
-q*sum U*V over nodes with x_a <= x < x_b, V = the node volume the equation uses.
Units: 1D A/cm^2, 2D A/cm (per unit depth)."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common_d2 as c2  # noqa: E402

cd, md = c2.cd, c2.md
FWD, REV = [0.025, 0.05, 0.075, 0.1], [-0.025, -0.05, -0.075, -0.1]
RECORD = {0.05: "+0.050", 0.1: "+0.100", -0.1: "-0.100"}
SG = {  # the three kahan3 terms of the production SG currents (simple_dd.py:48, :69)
    "e1": "ElectronCharge*mu_n*EdgeInverseLength*V_t*Electrons@n1*Bern01",
    "e2": "ElectronCharge*mu_n*EdgeInverseLength*V_t*Electrons@n1*vdiff",
    "e3": "-ElectronCharge*mu_n*EdgeInverseLength*V_t*Electrons@n0*Bern01",
    "h1": "-ElectronCharge*mu_p*EdgeInverseLength*V_t*Holes@n1*Bern01",
    "h2": "ElectronCharge*mu_p*EdgeInverseLength*V_t*Holes@n0*Bern01",
    "h3": "ElectronCharge*mu_p*EdgeInverseLength*V_t*Holes@n0*vdiff",
}


def nv(dv, n):
    return np.array(dv.get_node_model_values(device="d", region=cd.REGION, name=n))


def ev(dv, n):
    return np.array(dv.get_edge_model_values(device="d", region=cd.REGION, name=n))


def build(dv, cfg):
    if cfg["kind"] == "1d":
        cd.build_1d(dv, md.grid_1d(cfg["h"], "J1"))
        c2.set_doping(dv, cfg["mirror"])
        return {"variant": "1D"}
    P, tris, _ = c2.fixture(cfg["fam"], cfg["h"])
    if cfg["mirror"]:
        P = P * np.array([-1.0, 1.0])
        tris = [[a, c, b] for a, b, c in tris]
    cd.build_2d(dv, P, tris)
    c2.set_doping(dv, cfg["mirror"])
    return cd.apply_variant(dv, cfg["variant"])


def diag_models(dv):
    dv.edge_model(device="d", region=cd.REGION, name="D2_dpsi", equation="Potential@n0 - Potential@n1")
    for k, e in SG.items():
        dv.edge_model(device="d", region=cd.REGION, name="D2_" + k, equation=e)


def measure(dv, cfg):
    x, psi = nv(dv, "x"), nv(dv, "Potential")
    n, p = nv(dv, "Electrons"), nv(dv, "Holes")
    usrh = nv(dv, "USRH")
    vol = nv(dv, "OvNodeVolume") if cfg.get("variant") == "D1" else nv(dv, "NodeVolume")
    for m in ("x", "node_index"):
        dv.edge_from_node_model(device="d", region=cd.REGION, node_model=m)
    n0, n1 = ev(dv, "node_index@n0").astype(int), ev(dv, "node_index@n1").astype(int)
    cname = "OvEdgeCouple" if cfg.get("variant") == "D1" else "EdgeCouple"
    cpl = ev(dv, cname) if cfg["kind"] == "2d" else np.ones(len(n0))
    if cfg["kind"] == "1d":
        cname = "1D (couple = 1)"
    jn, jp = ev(dv, "ElectronCurrent"), ev(dv, "HoleCurrent")
    Fn, Fp = jn * cpl, jp * cpl
    out = {"couple_model": cname}
    cur = cd.currents(dv)
    out["C0"] = cur
    xmin, xmax = x.min(), x.max()
    for side, cset in (("left", x == xmin), ("right", x == xmax)):
        a, b = cset[n0], cset[n1]
        s = np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))
        out.setdefault("C1", {})[side] = {"n": float(np.sum(s * Fn)), "p": float(np.sum(s * Fp)),
                                          "total": float(np.sum(s * (Fn + Fp))), "n_edges": int(np.count_nonzero(s))}
        out.setdefault("contact_edges", {})[side] = np.where(s != 0)[0]
    cuts = {}
    xum = x / cd.UM
    for xc in c2.CUTS_UM:
        L = xum < xc
        a, b = L[n0], L[n1]
        s = np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))
        cuts[f"{xc:+.2f}"] = {"n": float(np.sum(s * Fn)), "p": float(np.sum(s * Fp)), "total": float(np.sum(s * (Fn + Fp))),
                              "n_edges": int(np.count_nonzero(s)), "nodes_on_cut": int(np.sum(xum == xc)),
                              "_edges": np.where(s != 0)[0]}
    c3 = {}
    ks = [f"{xc:+.2f}" for xc in c2.CUTS_UM]
    for ka, kb, xa, xb in zip(ks[:-1], ks[1:], c2.CUTS_UM[:-1], c2.CUTS_UM[1:]):
        m = (xum >= xa) & (xum < xb)
        gen = float(c2.Q * np.sum(usrh[m] * vol[m]))
        c3[f"{ka}..{kb}"] = {"dI_n": cuts[kb]["n"] - cuts[ka]["n"], "q_int_U": gen,
                             "dI_p": cuts[kb]["p"] - cuts[ka]["p"], "dI_total": cuts[kb]["total"] - cuts[ka]["total"]}
    out["C3"] = c3
    # ULP / cancellation on contact edges and cut edges (DEVSIM-evaluated models)
    dpsi_dev = ev(dv, "D2_dpsi")
    terms = {k: ev(dv, "D2_" + k) for k in SG}
    vdiff = ev(dv, "vdiff")
    dpsi_py = psi[n0] - psi[n1]
    ulp = np.spacing(np.abs(psi[n0]))

    def stats(idx):
        if len(idx) == 0:
            return None
        tn = np.max(np.abs(np.vstack([terms["e1"][idx], terms["e2"][idx], terms["e3"][idx]])), axis=0)
        tp = np.max(np.abs(np.vstack([terms["h1"][idx], terms["h2"][idx], terms["h3"][idx]])), axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            cn, cp = tn / np.abs(jn[idx]), tp / np.abs(jp[idx])
        return {"n_edges": int(len(idx)), "min_abs_dpsi_over_ulp": float(np.min(np.abs(dpsi_py[idx]) / ulp[idx])),
                "median_abs_dpsi_over_ulp": float(np.median(np.abs(dpsi_py[idx]) / ulp[idx])),
                "max_abs_dpsi_V": float(np.max(np.abs(dpsi_dev[idx]))),
                "max_rel_dev_minus_py_dpsi": float(np.max(np.abs(dpsi_dev[idx] - dpsi_py[idx]) / np.maximum(np.abs(dpsi_dev[idx]), 1e-300))),
                "vdiff_range": [float(np.min(vdiff[idx])), float(np.max(vdiff[idx]))],
                "max_term_n": float(np.max(tn)), "max_term_p": float(np.max(tp)),
                "max_abs_Jn": float(np.max(np.abs(jn[idx]))), "max_abs_Jp": float(np.max(np.abs(jp[idx]))),
                "max_cancellation_n": float(np.nanmax(cn)), "max_cancellation_p": float(np.nanmax(cp)),
                "kahan_sum_check_n": float(np.max(np.abs(terms["e1"][idx] + terms["e2"][idx] + terms["e3"][idx] - jn[idx])
                                              / np.maximum(np.abs(jn[idx]), 1e-300)))}
    out["ulp"] = {"left_contact": stats(out["contact_edges"].pop("left")),
                  "right_contact": stats(out["contact_edges"].pop("right"))}
    del out["contact_edges"]
    for k, v in cuts.items():
        out["ulp"]["cut" + k] = stats(v.pop("_edges"))
    out["C2"] = cuts
    out["positive_finite"] = bool(np.all(np.isfinite(n)) and np.all(np.isfinite(p)) and n.min() > 0 and p.min() > 0)
    out["psi_range"] = [float(psi.min()), float(psi.max())]
    return out


def run(cfg):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    out = {"cfg": cfg, "flags_at_start": c2.read_flags(dv), "flags_set": c2.set_precision(dv, cfg["P"]),
           "info": dv.get_parameter(name="info"), "steps": {}}
    bias = "right_bias" if cfg["mirror"] else "left_bias"
    sgn = -1.0 if cfg["mirror"] else 1.0     # forward = p contact positive
    for branch in (FWD, REV):
        vinfo = build(dv, cfg)
        out["variant_info"] = vinfo
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        a = c2.solve(dv, "poisson", "A")
        out["steps"].setdefault("A" if branch is FWD else "Arev", {"info": a})
        if not a["ok"]:
            break
        if branch is FWD:
            out["steps"]["A"]["state"] = {"x": nv(dv, "x").tolist(), "y": nv(dv, "y").tolist(),
                                          "psi": nv(dv, "Potential").tolist()}
            out["steps"]["A"]["max_abs_ElectricField"] = float(np.max(np.abs(ev(dv, "ElectricField"))))
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        diag_models(dv)
        b = c2.solve(dv, "drift_diffusion", "B0")
        if branch is FWD:
            rec = {"info": b}
            if b["ok"]:
                rec.update(measure(dv, cfg))
                xx, psi, n, p = nv(dv, "x"), nv(dv, "Potential"), nv(dv, "Electrons"), nv(dv, "Holes")
                phin, phip = psi - cd._sl.VT * np.log(n / cd._sl.NI), psi + cd._sl.VT * np.log(p / cd._sl.NI)
                rec["qf_dev_V"] = float(max(np.max(np.abs(phin - np.median(phin))), np.max(np.abs(phip - np.median(phip)))))
                rec["mass_action_dev"] = float(np.max(np.abs(n * p / cd._sl.NI ** 2 - 1)))
                rec["state"] = {"x": xx.tolist(), "y": nv(dv, "y").tolist(), "ln_n": np.log(n).tolist(),
                                "ln_p": np.log(p).tolist(), "psi": psi.tolist()}
            out["steps"]["B0"] = rec
        if not b["ok"]:
            break
        for v in branch:
            dv.set_parameter(device="d", name=bias, value=sgn * v)
            r = c2.solve(dv, "drift_diffusion", f"C{v:+.3f}")
            rec = {"info": r}
            if r["ok"] and v in RECORD:
                rec.update(measure(dv, cfg))
            out["steps"][f"C{v:+.3f}"] = rec
            if not r["ok"]:
                break
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    out["flags_at_end"] = c2.read_flags(dv)
    out["devices_left"] = list(dv.get_device_list())
    return out


if __name__ == "__main__":
    c = json.loads(sys.argv[1])
    try:
        r = run(c)
    except Exception as e:  # noqa: BLE001
        import traceback
        r = {"cfg": c, "error": repr(e)[:500], "tb": traceback.format_exc()[-1500:]}
    print("RESULT " + json.dumps(r))
