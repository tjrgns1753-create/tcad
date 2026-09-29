"""Batch 7H-E6D synthetic false-PASS tests (local; pure judge + production refine_mesh_near on a small synthetic mesh; no DEVSIM).
Every expectation is fixed in EXPECT before any case runs. Writes synthetic_e6d_results.json next to this file's batch folder."""
import os
import sys

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
AUD = os.path.join(ROOT, "docs", "audits")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family", "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import judge_e6d as jd  # noqa: E402
import family_e6a as fam  # noqa: E402
import common_e1 as ce  # noqa: E402
from tcad.device.devsim.mesh_refine import refine_mesh_near  # noqa: E402  (production, called only)

jb = jd.jb
F = np.float32
X01, X015, X02 = float(F(0.1)), float(F(0.15)), float(F(0.2))
H = 0.05

EXPECT = {
    "A_core_triangle_changed_same_nodes": {"core_node_set_equal": True, "core_triangle_multiset_equal": False,
                                           "mesh_state": "CORE_IDENTITY_FAIL"},
    "B_hidden_transition_change": {"flip_transition_changed": True, "flip_removed_transition": 2, "flip_added_transition": 2,
                                   "G1_transition_changed": True, "G1_core_identity_ok": True},
    "C_negative_edgecouple": {"no_negative": False, "mesh_state": "GEOMETRY_UNSUPPORTED"},
    "D_missing_contact_edge": {"contacts_ok": False, "mesh_state": "IMPORT_IDENTITY_FAIL", "control_contacts_ok": True},
    "E_nodevolume_total_error": {"sum_within_tau": False, "mesh_state": "GEOMETRY_UNSUPPORTED", "control_within_tau": True},
    "F_Q_not_converged_PQ_equal_G1": {"G1_state": "POISSON_NOT_CONVERGED", "overall": "POISSON_NOT_CONVERGED", "any_metric_classified": False},
    "F_Q_not_converged_PQ_equal_G2": {"G2_state": "POISSON_NOT_CONVERGED", "decrease_test_evaluated": False,
                                      "overall": "NONCORE_REFINEMENT_SENSITIVITY_ONLY", "metric_state": "NONCORE_CHANGE_RESOLVED_01"},
    "G_empty_common_core": {"overall": "CONSISTENCY_FAIL"},
    "H_only_third_inequality_fails": {"metric_state": "NO_NONCORE_DECREASE", "overall": "NONCORE_REFINEMENT_SENSITIVITY_ONLY"},
    "I_positive_control_all_hold": {"metric_state": "NONCORE_REFINEMENT_DECREASE_OBSERVED", "overall": "NONCORE_REFINEMENT_DECREASE_OBSERVED"},
    "J_no_resolvable_change": {"overall": "NO_RESOLVABLE_NONCORE_CHANGE"},
    "K_missing_checks_fail_closed": {"mesh_state": "IMPORT_IDENTITY_FAIL", "all_missing_state": "CORE_IDENTITY_FAIL"},
    "L_green_of_green_obtuse": {"G0_obtuse": 0, "G1_obtuse": 0, "G2_obtuse": 16, "G2_obtuse_transition": 16, "G1_T2": True, "G1_T3": True,
                                "G2_T2": True, "G2_T3": True, "G1_area_equal": True, "G2_area_equal": True, "G2_core_identity_ok": True},
}


# ---------------------------------------------------------------- synthetic mesh (E6A-like: core, transition, template column, base)
def build():
    pts, idx = [], {}

    def p(x, y):
        k = (float(F(x)), float(F(y)))
        if k not in idx:
            idx[k] = len(pts)
            pts.append(k)
        return idx[k]
    tris = []
    ny = 4
    ys = [float(F(H * j)) for j in range(ny + 1)]
    mid = lambda a, b: float((np.array([a], F) + np.array([b], F))[0] / F(2.0))  # noqa: E731  (production float32 midpoint, as E4 mid32)
    yh = [v for j in range(ny) for v in (ys[j], mid(ys[j], ys[j + 1]))] + [ys[-1]]
    xin = [-X015, -X01, -0.05, 0.0, 0.05, X01, X015]
    for i in range(len(xin) - 1):                                       # inner grid, y spacing H/2
        for j in range(2 * ny):
            a, b, c, d = p(xin[i], yh[j]), p(xin[i + 1], yh[j]), p(xin[i + 1], yh[j + 1]), p(xin[i], yh[j + 1])
            tris += [(a, b, c), (a, c, d)]
    for j in range(ny):                                                 # template column, both sides
        y0, y1, ym = ys[j], ys[j + 1], yh[2 * j + 1]
        LL, LR, UR, UL, M = p(X015, y0), p(X02, y0), p(X02, y1), p(X015, y1), p(X015, ym)
        tris += [(LL, LR, M), (M, LR, UR), (M, UR, UL)]
        LL, LR, UR, UL, M = p(-X015, y0), p(-X02, y0), p(-X02, y1), p(-X015, y1), p(-X015, ym)
        tris += [(M, LR, LL), (UR, LR, M), (UL, UR, M)]
    xb = [X02, 0.25, 0.3]
    for s in (+1, -1):                                                  # base region
        for i in range(len(xb) - 1):
            for j in range(ny):
                xa, xc = s * xb[i], s * xb[i + 1]
                a, b, c, d = p(xa, ys[j]), p(xc, ys[j]), p(xc, ys[j + 1]), p(xa, ys[j + 1])
                tris += [(a, b, c), (a, c, d)] if s > 0 else [(a, d, c), (a, c, b)]
    P = np.array([[x, y, 0.0] for x, y in pts], dtype=np.float32)
    return P, np.array(tris, dtype=np.int64), np.full(len(tris), 10, dtype=np.int32)


def small_cs():
    P, T, _ = build()
    xcm = P[:, 0].astype(np.float64) * 1e-4
    return P, jb.CommonSet({3: P[:, :2], 4: P[:, :2], 5: P[:, :2]}, np.ones(len(P)), xcm, P[:, 1].astype(np.float64) * 1e-4)


def ok_checks():
    return {k: True for k in jd.CHECK_CLASS}


def psi_family(cs, s01, s12, a):
    """psi_k,P and psi_k,Q with every difference proportional to the same shape g (so all four metrics scale alike)."""
    x = cs.xcm / 1e-4
    base = 0.47 * np.tanh(x / 0.05)
    g = np.exp(-(x / 0.08) ** 2) * (1 + x)
    P0 = base
    P1 = base + s01 * g
    P2 = P1 + s12 * g
    return {0: {"P": P0, "Q": P0 + a[0] * g}, 1: {"P": P1, "Q": P1 + a[1] * g}, 2: {"P": P2, "Q": P2 + a[2] * g}}


def main():
    got = {}
    P0, T0, G0 = build()
    # ---- A
    T_bad = T0.copy()
    ci = None
    for n in range(0, len(T0), 2):                                      # first all-core cell (two triangles a,b,c / a,c,d): flip it
        a, b, c = T0[n]
        d = T0[n + 1][2]
        if all(abs(P0[v, 0]) <= X01 for v in (a, b, c, d)):
            T_bad[n], T_bad[n + 1] = (a, b, d), (b, c, d)
            break
    ci = jd.core_identity(P0, T0, P0, T_bad)
    chk = ok_checks()
    chk.update({"core_node_set_equal": ci["core_node_set_equal"], "core_triangle_multiset_equal": ci["core_triangle_multiset_equal"]})
    got["A_core_triangle_changed_same_nodes"] = {"core_node_set_equal": ci["core_node_set_equal"],
                                                 "core_triangle_multiset_equal": ci["core_triangle_multiset_equal"],
                                                 "mesh_state": jd.mesh_state(chk)[0]}
    # ---- B: flip one transition cell (inner column X01..X015) with unchanged counts; and the real G1 closure change
    T_fl = T0.copy()
    for n in range(0, len(T0), 2):
        a, b, c = T0[n]
        d = T0[n + 1][2]
        cx = np.mean(P0[[a, b, c, d], 0])
        if X01 < cx < X015:
            T_fl[n], T_fl[n + 1] = (a, b, d), (b, c, d)
            break
    cr = jd.change_record(P0, T0, P0, T_fl)
    G1 = refine_mesh_near(P0, T0, G0, lambda c: abs(float(c[0])) >= X02, levels=1)
    G2 = refine_mesh_near(P0, T0, G0, lambda c: abs(float(c[0])) >= X02, levels=2)
    cr1 = jd.change_record(P0, T0, G1[0], G1[1])
    got["B_hidden_transition_change"] = {"flip_transition_changed": cr["transition_changed"], "flip_removed_transition": cr["removed"]["transition"],
                                         "flip_added_transition": cr["added"]["transition"], "G1_transition_changed": cr1["transition_changed"],
                                         "G1_core_identity_ok": jd.core_identity(P0, T0, G1[0], G1[1])["ok"]}
    got["B_hidden_transition_change"]["_G1_change_record"] = cr1
    # ---- C
    ec = np.array([1.0, 0.5, -1e-30, 0.0])
    er = jd.edgecouple_record(ec, np.array([0, 1, 2, 3]), np.array([1, 2, 3, 0]), np.array([0.0, 1e-5, 2e-5, 3e-5]))
    chk = ok_checks()
    chk["edgecouple_no_negative"] = er["no_negative"]
    got["C_negative_edgecouple"] = {"no_negative": er["no_negative"], "mesh_state": jd.mesh_state(chk)[0], "_record": er}
    # ---- D: contact line with 5 nodes; drop one contact edge
    x = np.array([0.0] * 5 + [1.0] * 5)
    y = np.array([0.0, 0.25, 0.5, 0.75, 1.0] * 2)
    full = {"Si_xmin": {"nodes": [0, 1, 2, 3, 4], "edges": [[0, 1], [1, 2], [2, 3], [3, 4]]},
            "Si_xmax": {"nodes": [5, 6, 7, 8, 9], "edges": [[5, 6], [6, 7], [7, 8], [8, 9]]}}
    miss = {"Si_xmin": {"nodes": [0, 1, 2, 3, 4], "edges": [[0, 1], [2, 3], [3, 4]]}, "Si_xmax": full["Si_xmax"]}
    chk = ok_checks()
    chk["contacts_ok"] = jd.contacts_ok(x, y, miss)["ok"]
    got["D_missing_contact_edge"] = {"contacts_ok": chk["contacts_ok"], "mesh_state": jd.mesh_state(chk)[0],
                                     "control_contacts_ok": jd.contacts_ok(x, y, full)["ok"]}
    # ---- E: NodeVolume sum off by more than tau, control within tau
    nv = np.full(100, 0.01)
    area = float(nv.sum())
    tau = 200 * 2.0 ** -52 + 1e-13
    bad = nv.copy()
    bad[0] = bad[0] * (1 + 1e-9)
    ctl = nv.copy()
    ctl[0] = np.nextafter(ctl[0], 1.0)
    assert ctl[0] != nv[0]
    g_bad, g_ctl = jd.nodevolume_gate(bad, area, tau), jd.nodevolume_gate(ctl, area, tau)
    chk = ok_checks()
    chk["nodevolume_sum_within_tau"] = g_bad["sum_within_tau"]
    got["E_nodevolume_total_error"] = {"sum_within_tau": g_bad["sum_within_tau"], "mesh_state": jd.mesh_state(chk)[0],
                                       "control_within_tau": g_ctl["sum_within_tau"]}
    # ---- F, G, H, I, J: judge on a small common set
    Ps, cs = small_cs()
    conv = {"ok": True, "converged": True, "final_rel": 1e-12}
    noconv = {"ok": True, "converged": False, "final_rel": 1e-3}
    good = {"P": {"status": None, "solve": conv, "consistency_ok": True}, "Q": {"status": None, "solve": conv, "consistency_ok": True}}
    badQ = {"P": {"status": None, "solve": conv, "consistency_ok": True}, "Q": {"status": None, "solve": noconv, "consistency_ok": True}}
    psiF = psi_family(cs, 1e-3, 2.5e-4, (0.0, 0.0, 0.0))               # P and Q arrays EQUAL at every level
    st1 = {0: "OK", 1: jd.g_state("OK", badQ), 2: jd.g_state("OK", good)}
    j = jd.judge(st1, psiF, cs, {})
    got["F_Q_not_converged_PQ_equal_G1"] = {"G1_state": st1[1], "overall": j["overall"],
                                            "any_metric_classified": any(j["metrics"][M]["state"] != "NOT_CLASSIFIED" for M in jd.METRICS)}
    st2 = {0: "OK", 1: jd.g_state("OK", good), 2: jd.g_state("OK", badQ)}
    psi2 = {k: dict(v) for k, v in psiF.items()}
    j = jd.judge(st2, psi2, cs, {})
    got["F_Q_not_converged_PQ_equal_G2"] = {"G2_state": st2[2], "decrease_test_evaluated": j["decrease_test_evaluated"],
                                            "overall": j["overall"], "metric_state": j["metrics"]["psiLinf"]["state"]}
    csE = small_cs()[1]
    for m in csE.masks:
        csE.masks[m] = np.zeros_like(csE.masks[m])
    j = jd.judge({0: "OK", 1: "OK", 2: "OK"}, psi_family(csE, 1e-3, 2.5e-4, (1e-15,) * 3), csE, {})
    got["G_empty_common_core"] = {"overall": j["overall"]}
    allok = {0: "OK", 1: "OK", 2: "OK"}
    j = jd.judge(allok, psi_family(cs, 1e-3, 1e-3 - 1e-5, (1e-5, 1e-5, 1e-5)), cs, {})
    iq = j["metrics"]["psiLinf"]["inequalities"]
    got["H_only_third_inequality_fails"] = {"metric_state": j["metrics"]["psiLinf"]["state"], "overall": j["overall"],
                                            "_ineq_holds": [iq[f"ineq{i}"]["holds"] for i in (1, 2, 3)]}
    assert got["H_only_third_inequality_fails"]["_ineq_holds"] == [True, True, False]
    j = jd.judge(allok, psi_family(cs, 1e-3, 2.5e-4, (1e-15, 1e-15, 1e-15)), cs, {})
    got["I_positive_control_all_hold"] = {"metric_state": j["metrics"]["ExRMS"]["state"], "overall": j["overall"]}
    j = jd.judge(allok, psi_family(cs, 1e-15, 1e-15, (1e-12, 1e-12, 1e-12)), cs, {})
    got["J_no_resolvable_change"] = {"overall": j["overall"]}
    # ---- K
    chk = ok_checks()
    chk["contacts_ok"] = False
    for k in ("nodevolume_positive", "nodevolume_sum_within_tau", "edgecouple_no_negative"):
        del chk[k]
    got["K_missing_checks_fail_closed"] = {"mesh_state": jd.mesh_state(chk)[0], "all_missing_state": jd.mesh_state({})[0]}
    # ---- L: green-of-green obtuse prediction (exact, family_e6a.exact_checks) on the synthetic mesh
    ex = {}
    for name, (P, T, G) in (("G0", (P0, T0, G0)), ("G1", G1), ("G2", G2)):
        ex[name] = fam.exact_checks(P[:, :2], T, P0[:, :2], T0, G, 10)
    cx2 = np.abs(G2[0][G2[1]][:, :, 0].astype(np.float64).mean(axis=1))
    P2 = G2[0][:, :2].astype(np.float64)
    T2 = G2[1]
    ob = np.zeros(len(T2), bool)
    for kk in range(3):
        a, b, c = T2[:, kk], T2[:, (kk + 1) % 3], T2[:, (kk + 2) % 3]
        ob |= ((P2[b] - P2[a]) * (P2[c] - P2[a])).sum(1) < 0
    got["L_green_of_green_obtuse"] = {"G0_obtuse": ex["G0"]["n_obtuse_exact"], "G1_obtuse": ex["G1"]["n_obtuse_exact"],
                                      "G2_obtuse": ex["G2"]["n_obtuse_exact"],
                                      "G2_obtuse_transition": int((ob & (cx2 > X01) & (cx2 < X02)).sum()),
                                      "G1_T2": ex["G1"]["tiling_T2_ok"], "G1_T3": ex["G1"]["tiling_T3_ok"],
                                      "G2_T2": ex["G2"]["tiling_T2_ok"], "G2_T3": ex["G2"]["tiling_T3_ok"],
                                      "G1_area_equal": ex["G1"]["area_equals_S0"], "G2_area_equal": ex["G2"]["area_equals_S0"],
                                      "G2_core_identity_ok": jd.core_identity(P0, T0, G2[0], G2[1])["ok"],
                                      "_counts": {n: [int(len(P)), int(len(T))] for n, (P, T, _) in (("G0", (P0, T0, G0)), ("G1", G1), ("G2", G2))}}
    # ---- compare
    fails = []
    for case, exp in EXPECT.items():
        for k, v in exp.items():
            if got[case].get(k) != v:
                fails.append(f"{case}.{k}: expected {v!r} got {got[case].get(k)!r}")
    out = {"expectations": EXPECT, "observed": got, "failures": fails, "pass": not fails}
    ce.dump_strict(out, os.path.join(HERE, "..", "synthetic_e6d_results.json"))
    for f in fails:
        print("FAIL", f)
    print("synthetic_e6d:", "PASS" if not fails else f"{len(fails)} FAIL", {c: "ok" for c in EXPECT} if not fails else "")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
