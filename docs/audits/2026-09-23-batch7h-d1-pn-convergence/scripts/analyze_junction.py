"""Batch 7H-D1 SUPPLEMENTARY analysis of diag_junction_current.json and
diag_precision.json (post-hoc observable, NOT a registered input). Applies the
registered layer-B/C thresholds to the precision-robust junction current:
reference = 1D J1 h = 0.0003125 um (x H for 2D), U = finest-pair change of the 1D
junction current, decreasing = strictly over >= 3 consecutive levels ending at
the finest, finest tolerance = max(5 U, 2 %). Also reads the registered analysis
for E_peak values. -> data/analysis_junction.json"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
d = json.load(open(os.path.join(DATA, "diag_junction_current.json"), encoding="utf-8"))
reg = json.load(open(os.path.join(DATA, "analysis_d1.json"), encoding="utf-8"))
B = ["-0.100", "+0.050", "+0.100"]
H1 = ["0.02", "0.01", "0.005", "0.0025", "0.00125", "0.000625", "0.0003125"]
H2 = ["0.02", "0.01", "0.005", "0.0025"]
HCM = 1e-5
ref = {b: d["1D_J1_h0.0003125"][b]["I_junction"] for b in B}
U = {b: abs(ref[b] - d["1D_J1_h0.000625"][b]["I_junction"]) / abs(ref[b]) for b in B}
out = {"reference_1D_h0.0003125_A_per_cm2": ref, "U_junction": U,
       "reference_converged": all(u <= 0.01 for u in U.values()),
       "ref1d_sequence": {h: {b: d[f"1D_J1_h{h}"][b]["I_junction"] for b in B} for h in H1},
       "ref1d_ratio_of_successive_changes": {}, "variants": {}}
for b in B:
    J = [d[f"1D_J1_h{h}"][b]["I_junction"] for h in H1]
    ch = [abs(J[i + 1] - J[i]) for i in range(len(J) - 1)]
    out["ref1d_ratio_of_successive_changes"][b] = [ch[i] / ch[i + 1] for i in range(len(ch) - 1)]
for v in ("M1_D0", "M2_D0", "M3_D0", "M3_D1"):
    rows = {}
    for b in B:
        e = [(d[f"{v}_h{h}"][b]["I_junction"] / HCM - ref[b]) / abs(ref[b]) for h in H2]
        a = [abs(x) for x in e]
        rows[b] = {"signed_rel_error": e, "decreasing_3": a[-3] > a[-2] > a[-1],
                   "finest_over_previous": a[-1] / a[-2], "finest_pass": a[-1] <= max(5 * U[b], 0.02),
                   "tol": max(5 * U[b], 0.02)}
    ep = [q.get("e_Epeak") for q in reg["variants"][v]["levels"]]
    out["variants"][v] = {"junction_current": rows, "all_decreasing": all(r["decreasing_3"] for r in rows.values()),
                          "all_finest_pass": all(r["finest_pass"] for r in rows.values()), "e_Epeak_registered": ep}
    if v == "M2_D0":
        out["variants"][v]["same_h_vs_1D"] = {h: {b: abs(d[f"M2_D0_h{h}"][b]["I_junction"] / HCM - d[f"1D_J1_h{h}"][b]["I_junction"])
                                                  / abs(d[f"1D_J1_h{h}"][b]["I_junction"]) for b in B} for h in H2}
p = json.load(open(os.path.join(DATA, "diag_precision.json"), encoding="utf-8"))
out["contact_current_precision"] = {h: {V: {"I_left": p[h][V]["I_left_total"], "kcl_rel": p[h][V]["kcl_rel"],
                                            "left_dpsi_ulps": p[h][V]["left_contact_edge"]["dpsi_in_ulps"],
                                            "left_quantum_rel": p[h][V]["left_contact_edge"]["current_quantum_A_per_cm2"] / abs(p[h][V]["I_left_total"])}
                                        for V in ("+0.10", "-0.10")} for h in p}
with open(os.path.join(DATA, "analysis_junction.json"), "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, indent=1)
print("U_junction", U, "converged", out["reference_converged"])
print("1D successive-change ratios", {b: ["%.2f" % r for r in v] for b, v in out["ref1d_ratio_of_successive_changes"].items()})
for v, r in out["variants"].items():
    print(v, "all_decreasing", r["all_decreasing"], "all_finest_pass", r["all_finest_pass"],
          {b: ["%+.3e" % e for e in q["signed_rel_error"]] for b, q in r["junction_current"].items()},
          "Epeak", ["%.2e" % e for e in r["e_Epeak_registered"]])
print("M2 same-h", out["variants"]["M2_D0"]["same_h_vs_1D"])
for h, r in out["contact_current_precision"].items():
    print(h, {V: ("ulps %.0f" % q["left_dpsi_ulps"], "quantum/I %.2e" % q["left_quantum_rel"], "KCL %.2e" % q["kcl_rel"]) for V, q in r.items()})
