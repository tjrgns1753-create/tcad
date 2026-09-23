"""Batch 7H-D analysis of results_ref1d.json / results_synth2d.json (and, when
present, results_l3ref.json / results_l3.json). Applies ONLY the tolerances
registered in fixed_physics.json. Writes data/analysis_<set>.json.
usage: analyze.py synth | l3"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
FIX = json.load(open(os.path.join(DATA, "fixed_physics.json"), encoding="utf-8"))
REF = FIX["analytic_reference"]
VT, NI = REF["V_T_V"], REF["n_i_cm3"]
NA = ND = 1e17
BIAS = ["C_-0.100", "C_+0.050", "C_+0.100"]
EQS = ("PotentialEquation", "ElectronContinuityEquation", "HoleContinuityEquation")


def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def A(d, k):
    return np.array(d[k], dtype=float)


def jtot(step, contact="left"):
    return step["currents"][contact]["total"]


def one_d_metrics(st):
    x, psi = A(st, "x"), A(st, "psi")
    o = np.argsort(x)
    x, psi = x[o], psi[o]
    E = -np.diff(psi) / np.diff(x)
    return {"V_bi_numeric_V": float(psi[-1] - psi[0]), "E_peak_V_per_cm": float(np.max(np.abs(E)))}


def width_um(st):
    """distance between the points where the majority carrier = 0.5 * |doping| (sanity metric)."""
    x, n, p = A(st, "x"), A(st, "n"), A(st, "p")
    o = np.argsort(x)
    x, n, p = x[o], n[o], p[o]
    xl = x[x < 0][np.argmin(np.abs(p[x < 0] - 0.5 * NA))]
    xr = x[x > 0][np.argmin(np.abs(n[x > 0] - 0.5 * ND))]
    return float((xr - xl) * 1e4)


def ref(res1d):
    ids = sorted(res1d, key=lambda k: -res1d[k]["cfg"]["dx_um"])
    fin = res1d[ids[-1]]["steps"]
    xf = A(fin["A_poisson"]["state"], "x")
    o = np.argsort(xf)
    out = {"levels": {}, "finest": ids[-1]}
    for k in ids:
        s = res1d[k]["steps"]
        lv = {"dx_um": res1d[k]["cfg"]["dx_um"], "all_ok": all(v.get("ok", True) for v in s.values() if isinstance(v, dict))}
        x, psi = A(s["A_poisson"]["state"], "x"), A(s["A_poisson"]["state"], "psi")
        pf = np.interp(x, xf[o], A(fin["A_poisson"]["state"], "psi")[o])
        lv["psiA_Linf_vs_finest_V"] = float(np.max(np.abs(psi - pf)))
        lv.update(one_d_metrics(s["A_poisson"]["state"]))
        lv["W_um_B0"] = width_um(s["B_0V"]["state"])
        sb = s["B_0V"]["state"]
        xb, nb, pb = A(sb, "x"), A(sb, "n"), A(sb, "p")
        il, ir = int(np.argmin(xb)), int(np.argmax(xb))
        lv["B0_contact_p_side_p_n_cm3"] = [float(pb[il]), float(nb[il])]
        lv["B0_contact_n_side_n_p_cm3"] = [float(nb[ir]), float(pb[ir])]
        lv["B0_currents_A_per_cm2"] = [jtot(s["B_0V"], "left"), jtot(s["B_0V"], "right")]
        phin = A(sb, "psi") - VT * np.log(nb / NI)
        lv["B0_qf_n_dev_V"] = float(np.max(np.abs(phin - np.median(phin))))
        lv["B0_mass_action_dev"] = float(np.max(np.abs(nb * pb / NI ** 2 - 1)))
        lv["newton"] = {k: v["iterations"] for k, v in res1d[k]["newton"].items()}
        for b in BIAS:
            lv[f"J_{b}_A_per_cm2"] = jtot(s[b])
            lv[f"Jrel_{b}_vs_finest"] = abs(jtot(s[b]) - jtot(fin[b])) / abs(jtot(fin[b]))
        out["levels"][k] = lv
    coarse = out["levels"][ids[0]]
    out["U_psi_V"] = coarse["psiA_Linf_vs_finest_V"]
    out["U_I"] = {b: coarse[f"Jrel_{b}_vs_finest"] for b in BIAS}
    out["monotone_psi_diff"] = bool(np.all(np.diff([out["levels"][k]["psiA_Linf_vs_finest_V"] for k in ids[:-1]]) < 0))
    out["monotone_J_diff"] = {b: bool(np.all(np.diff([out["levels"][k][f"Jrel_{b}_vs_finest"] for k in ids[:-1]]) < 0)) for b in BIAS}
    out["_fin"] = fin
    out["_coarsest"] = res1d[ids[0]]["steps"]
    return out


def expected_signs(m2d0):
    exp = {}
    for step in ("B_0V", "C_+0.100", "C_-0.100"):
        for e, b in m2d0["steps"][step]["blocks"].items():
            s = exp.setdefault(e, set())
            if b["n_offdiag_positive"]:
                s.add(+1)
            if b["n_offdiag_negative"]:
                s.add(-1)
    for e, b in m2d0["steps"]["A_poisson"]["blocks"].items():
        s = exp.setdefault(e + "@A", set())
        if b["n_offdiag_positive"]:
            s.add(+1)
        if b["n_offdiag_negative"]:
            s.add(-1)
    return {k: sorted(v) for k, v in exp.items()}


def block_viol(blocks, exp):
    out = {}
    for e, b in blocks.items():
        sg = exp.get(e)
        if sg == [1]:
            out[e] = {"violations": b["n_offdiag_negative"], "expected": "+"}
        elif sg == [-1]:
            out[e] = {"violations": b["n_offdiag_positive"], "expected": "-"}
        else:
            out[e] = {"violations": None, "expected": "BLOCK_SIGN_AUDIT_UNAVAILABLE (mixed on M2 D0)"}
        out[e]["n_rows_not_weakly_diag_dominant"] = b["n_rows_not_weakly_diag_dominant"]
    return out


def two_d(r, R, H_cm, i_scale, exp, m2_identity=None):
    s = r["steps"]
    fin = R["_fin"]
    xf = A(fin["A_poisson"]["state"], "x")
    o = np.argsort(xf)
    out = {"newton": {k: v["iterations"] for k, v in r["newton"].items()},
           "final_err": {k: [v["final_rel"], v["final_abs"]] for k, v in r["newton"].items()},
           "variant_info": r.get("variant_info"), "error": r.get("error")}
    oks = {k: v.get("ok") for k, v in s.items() if isinstance(v, dict)}
    out["ok"] = oks
    if not s.get("A_poisson", {}).get("ok"):
        return out
    # ---- A
    st = s["A_poisson"]["state"]
    x, y, psi = A(st, "x"), A(st, "y"), A(st, "psi")
    pf = np.interp(x, xf[o], A(fin["A_poisson"]["state"], "psi")[o])
    d = psi - pf
    xl, xr = x.min(), x.max()
    psil, psir = psi[x == xl].mean(), psi[x == xr].mean()
    cols = {}
    for xi, pi in zip(np.round(x * 1e8).astype(np.int64), psi):
        cols.setdefault(xi, []).append(pi)
    yvar = max(max(v) - min(v) for v in cols.values())
    xs = np.sort(np.unique(x))
    Ecol = []
    for xa, xb in zip(xs[:-1], xs[1:]):
        Ecol.append(abs(np.mean(psi[x == xb]) - np.mean(psi[x == xa])) / (xb - xa))
    A_ = {"psi_Linf_vs_1D_finest_V": float(np.max(np.abs(d))), "psi_L2rms_vs_1D_finest_V": float(np.sqrt(np.mean(d ** 2))),
          "agree_tol_V": 3 * R["U_psi_V"] + 1e-6,
          "V_bi_numeric_V": float(psir - psil), "y_variation_same_x_V": float(yvar),
          "E_peak_column_mean_V_per_cm": float(max(Ecol)),
          "overshoot_V": float(max(0.0, psi.max() - max(psil, psir), min(psil, psir) - psi.min())),
          "blocks": block_viol(s["A_poisson"]["blocks"], {"PotentialEquation": exp["PotentialEquation@A"]})}
    A_["agree"] = A_["psi_Linf_vs_1D_finest_V"] <= A_["agree_tol_V"]
    A_["no_overshoot"] = A_["overshoot_V"] <= 1e-9
    if m2_identity is not None:
        c = m2_identity["A_poisson"]["state"]
        xc, pc = A(c, "x"), A(c, "psi")
        oc = np.argsort(xc)
        A_["M2_identity_max_dpsi_V"] = float(np.max(np.abs(psi - np.interp(x, xc[oc], pc[oc]))))
    out["A"] = A_
    # ---- B
    b = s.get("B_0V", {})
    if b.get("ok"):
        st = b["state"]
        x, psi, n, p = A(st, "x"), A(st, "psi"), A(st, "n"), A(st, "p")
        phin = psi - VT * np.log(n / NI)
        phip = psi + VT * np.log(p / NI)
        cl, cr = x == x.min(), x == x.max()
        il, ir = jtot(b, "left"), jtot(b, "right")
        B_ = {"positive_finite": bool(np.all(np.isfinite(n)) and np.all(np.isfinite(p)) and n.min() > 0 and p.min() > 0),
              "n_min_cm3": float(n.min()), "p_min_cm3": float(p.min()),
              "I_left_A_per_cm": il, "I_right_A_per_cm": ir, "eq_current_tol": 1e-10 * i_scale,
              "qf_n_dev_V": float(np.max(np.abs(phin - np.median(phin)))),
              "qf_p_dev_V": float(np.max(np.abs(phip - np.median(phip)))),
              "mass_action_dev": float(np.max(np.abs(n * p / NI ** 2 - 1))),
              "blocks": block_viol(b["blocks"], exp)}
        nc = np.r_[n[cl], n[cr]]
        pc = np.r_[p[cl], p[cr]]
        B_["n_overshoot"] = bool(n.max() > nc.max() * (1 + 1e-9) or n.min() < nc.min() * (1 - 1e-9))
        B_["p_overshoot"] = bool(p.max() > pc.max() * (1 + 1e-9) or p.min() < pc.min() * (1 - 1e-9))
        B_["W_um"] = width_um(st)
        B_["contact_p_side_p_n_cm3"] = [float(p[cl].mean()), float(n[cl].mean())]
        B_["contact_n_side_n_p_cm3"] = [float(n[cr].mean()), float(p[cr].mean())]
        B_["contact_rel_neutrality"] = float(max(np.max(np.abs(p[cl] - n[cl] - NA)) / NA, np.max(np.abs(n[cr] - p[cr] - ND)) / ND))
        xf0 = A(fin["B_0V"]["state"], "x")
        of0 = np.argsort(xf0)
        B_["psi_Linf_vs_1D_finest_V"] = float(np.max(np.abs(psi - np.interp(x, xf0[of0], A(fin["B_0V"]["state"], "psi")[of0]))))
        B_["eq_current_ok"] = max(abs(il), abs(ir)) <= B_["eq_current_tol"]
        B_["conservation_ok"] = abs(il + ir) <= 1e-6 * max(abs(il), abs(ir)) + 1e-10 * i_scale
        B_["qf_ok"] = max(B_["qf_n_dev_V"], B_["qf_p_dev_V"]) <= 1e-6
        B_["mass_action_ok"] = B_["mass_action_dev"] <= 1e-6
        out["B"] = B_
    # ---- C
    C_ = {}
    for k in BIAS:
        c = s.get(k, {})
        if not c.get("ok"):
            C_[k] = {"ok": False}
            continue
        il, ir = jtot(c, "left"), jtot(c, "right")
        jref = jtot(fin[k]) * H_cm
        rel = abs(il - jref) / abs(jref)
        tol = 3 * R["U_I"][k] + 1e-6
        e = {"ok": True, "I_left_A_per_cm": il, "I_right_A_per_cm": ir, "I_ref_1Dfinest_times_H_A_per_cm": jref,
             "rel_diff_vs_1D": rel, "agree_tol": tol, "agree": rel <= tol,
             "conservation_ok": abs(il + ir) <= 1e-6 * max(abs(il), abs(ir)) + 1e-10 * i_scale,
             "n_min_cm3": float(A(c["state"], "n").min()), "p_min_cm3": float(A(c["state"], "p").min())}
        psi, x = A(c["state"], "psi"), A(c["state"], "x")
        psil, psir = psi[x == x.min()].mean(), psi[x == x.max()].mean()
        e["psi_overshoot_V"] = float(max(0.0, psi.max() - max(psil, psir), min(psil, psir) - psi.min()))
        if "blocks" in c:
            e["blocks"] = block_viol(c["blocks"], exp)
        if m2_identity is not None:
            e["M2_identity_rel_vs_1D_0.02"] = abs(il / H_cm - jtot(m2_identity[k])) / abs(jtot(m2_identity[k]))
        C_[k] = e
    out["C"] = C_
    return out


def main(which):
    if which == "synth":
        R = ref(load("results_ref1d.json"))
        res = load("results_synth2d.json")
        H_cm = 0.1e-4
    else:
        R = ref(load("results_l3ref.json"))
        res = load("results_l3.json")
        H_cm = 2.0e-4
    exp = expected_signs(load("results_synth2d.json")["M2_D0"])
    i_scale = REF["J_scale_A_per_cm2"] * H_cm
    out = {"ref1d": {k: v for k, v in R.items() if not k.startswith("_")}, "expected_block_signs_from_M2_D0": exp,
           "I_scale_A_per_cm": i_scale, "configs": {}}
    for k, r in res.items():
        m2i = R["_coarsest"] if k == "M2_D0" else None
        out["configs"][k] = two_d(r, R, H_cm, i_scale, exp, m2i)
    with open(os.path.join(DATA, f"analysis_{which}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=float)
    print(json.dumps(out["ref1d"], indent=1, default=float))
    print("expected signs", exp)
    for k, c in out["configs"].items():
        a, b, cc = c.get("A", {}), c.get("B", {}), c.get("C", {})
        print(f"\n== {k} newton={c['newton']} ok_all={all(v for v in c['ok'].values())}")
        if a:
            print(f"  A: Linf={a['psi_Linf_vs_1D_finest_V']:.3e} V tol={a['agree_tol_V']:.3e} agree={a['agree']} "
                  f"Vbi={a['V_bi_numeric_V']:.6f} yvar={a['y_variation_same_x_V']:.2e} Epk={a['E_peak_column_mean_V_per_cm']:.4e} "
                  f"over={a['overshoot_V']:.2e} PEviol={a['blocks']['PotentialEquation']['violations']}"
                  + (f" M2id={a['M2_identity_max_dpsi_V']:.2e}" if "M2_identity_max_dpsi_V" in a else ""))
        if b:
            print(f"  B: pos={b['positive_finite']} Il={b['I_left_A_per_cm']:.2e} Ir={b['I_right_A_per_cm']:.2e} eqok={b['eq_current_ok']} "
                  f"cons={b['conservation_ok']} qf={max(b['qf_n_dev_V'], b['qf_p_dev_V']):.2e} ma={b['mass_action_dev']:.2e} "
                  f"nover={b['n_overshoot']} pover={b['p_overshoot']} viol={ {e: v['violations'] for e, v in b['blocks'].items()} }\n"
                  f"     W={b['W_um']:.4f} um neut={b['contact_rel_neutrality']:.2e} pside(p,n)={b['contact_p_side_p_n_cm3']} "
                  f"nside(n,p)={b['contact_n_side_n_p_cm3']} psiB_Linf={b['psi_Linf_vs_1D_finest_V']:.3e} V")
        for bk, e in cc.items():
            if e.get("ok"):
                print(f"  {bk}: I={e['I_left_A_per_cm']:.6e} ref={e['I_ref_1Dfinest_times_H_A_per_cm']:.6e} rel={e['rel_diff_vs_1D']:.3e} "
                      f"tol={e['agree_tol']:.3e} agree={e['agree']} cons={e['conservation_ok']} over={e['psi_overshoot_V']:.1e}"
                      + (f" viol={ {q: v['violations'] for q, v in e['blocks'].items()} }" if "blocks" in e else "")
                      + (f" M2id={e['M2_identity_rel_vs_1D_0.02']:.2e}" if "M2_identity_rel_vs_1D_0.02" in e else ""))
            else:
                print(f"  {bk}: not reached / failed")


if __name__ == "__main__":
    main(sys.argv[1])
