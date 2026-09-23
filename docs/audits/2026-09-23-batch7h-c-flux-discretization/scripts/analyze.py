"""Batch 7H-C: tables and verdicts computed from data/results_7hc.json only."""
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
R = json.load(open(os.path.join(DATA, "results_7hc.json"), encoding="utf-8"))
FIX = json.load(open(os.path.join(DATA, "fixtures_7hc.json"), encoding="utf-8"))
TOL = FIX["spec"]["tolerances"]
I_AN = 0.5  # A/cm
OUT = {}


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def weights_check(key):
    w = R[key]["regions"]["R"]["weights"]
    nz = [x for x in w if x["C_devsim"] != 0 or x["w_matrix"] != 0]
    return {
        "n_rows": len(w),
        "max_rel_w_vs_C_over_L": max((rel(x["w_matrix"], x["C_over_L"]) for x in nz if x["C_over_L"] != 0), default=0.0),
        "max_rel_w_vs_C_squared": max((rel(x["w_matrix"], x["C_squared"]) for x in nz if x["C_squared"] != 0), default=0.0),
        "max_abs_w_where_C_zero": max((abs(x["w_matrix"]) for x in w if x["C_devsim"] == 0), default=0.0),
        "max_rel_w_vs_signed_C_over_L": max((rel(x["w_matrix"], x["signed_C_over_L"]) for x in nz if x["signed_C_over_L"] != 0), default=0.0),
        "n_rows_abs_ne_signed": sum(1 for x in w if rel(x["C_over_L"], x["signed_C_over_L"]) > TOL["WEIGHT_REL"]),
    }


def main():
    # 6. double EdgeCouple
    dbl = {}
    for m in ("M1", "M2", "M3", "M4", "M4_mirror", "M4_rot180", "M4_scale2"):
        dbl[m] = {"E1": weights_check(f"A_{m}_E1"), "E2": weights_check(f"A_{m}_E2")}
    e2_is_c2 = all(v["E2"]["max_rel_w_vs_C_squared"] <= TOL["WEIGHT_REL"] for v in dbl.values())
    e1_is_col = all(v["E1"]["max_rel_w_vs_C_over_L"] <= TOL["WEIGHT_REL"] for v in dbl.values())
    OUT["double_edgecouple"] = {"per_mesh": dbl, "E2_weight_equals_EdgeCouple_squared_everywhere": e2_is_c2,
                                "E1_weight_equals_EdgeCouple_over_EdgeLength_everywhere": e1_is_col,
                                "verdict": "DOUBLE_EDGECOUPLE_CONFIRMED" if (e2_is_c2 and e1_is_col) else "INCONCLUSIVE"}

    # 8/9. Experiment A and B
    A = {}
    for m in ("M1", "M2", "M3", "M4", "M4_mirror", "M4_rot180", "M4_scale2"):
        for fl in ("E1", "E2"):
            r = R[f"A_{m}_{fl}"]
            g = r["regions"]["R"]
            Il, Ir = r["contact_current"]["left"], r["contact_current"]["right"]
            # P3: E1 residual vs sum_j (w_matrix - signed w)(phi_a_i - phi_a_j)
            p3 = None
            if fl == "E1":
                P = np.array(FIX["fixtures"][m]["points_um"]) * 1e-4
                Lx = P[:, 0].max() - P[:, 0].min()
                phia = (P[:, 0] - P[:, 0].min()) / Lx
                pred = {}
                for x in g["weights"]:
                    a, b = x["edge"]
                    # row node is the free node whose residual is predicted; both orientations appear
                    for i, j in ((a, b), (b, a)):
                        if str(i) in g["residual_at_analytic_free"]:
                            pass
                rows = {}
                for x in g["weights"]:
                    a, b = x["edge"]
                    rows.setdefault(a, []).append((b, x))
                    rows.setdefault(b, []).append((a, x))
                errs = []
                for i_s, rres in g["residual_at_analytic_free"].items():
                    i = int(i_s)
                    s = 0.0
                    seen = set()
                    for j, x in rows.get(i, []):
                        if (i, j) in seen:
                            continue
                        seen.add((i, j))
                        s += (x["C_over_L"] - x["signed_C_over_L"]) * (phia[i] - phia[j])
                    errs.append(abs(rres - s))
                p3 = {"max_abs_residual_minus_prediction": float(max(errs)), "max_abs_residual": g["residual_at_analytic_free_max_abs"]}
            A[f"{m}_{fl}"] = {"Linf_free_V": g["Linf_free_V"], "L2_free_V": g["L2_free_V"],
                              "max_rel_to_dV": g["Linf_free_V"] / 1.0, "residual_max_abs": g["residual_at_analytic_free_max_abs"],
                              "I_left_A_per_cm": Il, "I_right_A_per_cm": Ir, "KCL_sum": Il + Ir,
                              "I_abs_err_A_per_cm": abs(abs(Ir) - I_AN), "I_rel_err": rel(abs(Ir), I_AN),
                              "phi_exact": g["Linf_free_V"] <= TOL["EXACT_V"], "I_exact": rel(abs(Ir), I_AN) <= TOL["EXACT_I_REL"],
                              "P3_check": p3}
    OUT["experiment_A_B"] = A
    ctrl_I = [A[f"{m}_E1"]["I_right_A_per_cm"] for m in ("M4", "M4_mirror", "M4_rot180", "M4_scale2")]
    OUT["controls_M4_E1_current_spread_rel"] = float((max(ctrl_I) - min(ctrl_I)) / abs(np.mean(ctrl_I)))

    # 10. Experiment C
    C = {}
    for m in ("M1", "M2", "M3", "M4"):
        a = R[f"A_{m}_E1"]["regions"]["R"]
        g = R[f"C3_{m}_E1"]["regions"]["R"]
        src_vs_zv = max(rel(g["poisson_source_part_free"][k], g["Z_times_NodeVolume_free"][k]) for k in g["poisson_source_part_free"])
        p5 = max(abs(g["residual_at_analytic_free"][k] - g["P5_predicted_residual_free"][k]) for k in g["residual_at_analytic_free"])
        C[m] = {"C1_sum_NodeVolume_over_area": a["sum_NodeVolume_cm2"] / a["area_cm2"],
                "C3_Linf_free_V": g["Linf_free_V"], "C3_phi_scale_V": g["phi_scale_V"],
                "C3_rel_to_phi_scale": g["Linf_free_V"] / g["phi_scale_V"], "C3_L2_free_V": g["L2_free_V"],
                "C3_residual_max_abs": g["residual_at_analytic_free_max_abs"],
                "C3_source_part_equals_Z_times_NodeVolume_max_rel": src_vs_zv,
                "C3_P5_prediction_max_abs_diff": p5}
    OUT["experiment_C"] = C

    # 11. override capability
    ov = {}
    for k, r in R.items():
        if k.startswith(("OV_", "EL_", "X2_", "EV_", "ELV_", "IF_", "SP_")):
            if "skip" in r:
                ov[k] = {"skipped": r["skip"]}
                continue
            if "error" in r:
                ov[k] = {"error": r["error"]}
                continue
            row = {"params": r["override_info"].get("parameters_set"), "I": r["contact_current"]}
            for rn, g in r["regions"].items():
                if "Linf_free_V" in g:
                    row[f"Linf_free_V_{rn}"] = g["Linf_free_V"]
                if "weights_over_permittivity" in g:
                    w = g["weights_over_permittivity"]
                    row["max_rel_w_over_eps_vs_C_over_L"] = max((rel(x["w_matrix_over_eps"], x["C_over_L"]) for x in w if x["C_over_L"] != 0), default=0)
                    row["max_rel_w_over_eps_vs_signed"] = max((rel(x["w_matrix_over_eps"], x["signed_C_over_L"]) for x in w if x["signed_C_over_L"] != 0), default=0)
                    row["n_weights"] = len(w)
                    row["n_negative_signed"] = sum(1 for x in w if x["signed_C_over_L"] < 0)
            row.update({k2: v for k2, v in r["override_info"].items() if k2.startswith("n_negative")})
            ov[k] = row
    OUT["override_capability"] = ov
    with open(os.path.join(DATA, "analysis_7hc.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(OUT, f, indent=1, sort_keys=True)
    print(json.dumps({"double": {m: {fl: {k: f"{v:.3e}" if isinstance(v, float) else v for k, v in d.items()} for fl, d in x.items()} for m, x in dbl.items()},
                      "verdict": OUT["double_edgecouple"]["verdict"]}, indent=0))
    for k, v in A.items():
        print(k, {kk: (f"{vv:.6e}" if isinstance(vv, float) else vv) for kk, vv in v.items()})
    print("controls spread", OUT["controls_M4_E1_current_spread_rel"])
    for k, v in C.items():
        print(k, {kk: f"{vv:.6e}" for kk, vv in v.items()})
    for k, v in ov.items():
        print(k, v)


if __name__ == "__main__":
    main()
