"""Batch 7H-C: freeze fixtures, expected solutions and per-mesh pre-solve
quality to data/fixtures_7hc.json BEFORE any DEVSIM solve. Signed couples
use the analytic formula (7H-B formulas.py, read-only); the "DEVSIM absolute
weight" and sum(NodeVolume)/area columns are PREDICTIONS from the 7H-B
experimental rule, not measurements."""
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import meshes as ms  # noqa: E402
import formulas as fm  # noqa: E402  (7H-B, read-only)

UM = 1e-4  # cm per um


def couples(P, tris):
    g1, g2, glen = fm.edge_couple_predictions(P, tris)
    return g1, g2, glen


def main():
    fixtures = {}
    base = {n: f() for n, f in ms.FAMILIES.items()}
    allm = dict(base)
    for k, v in ms.variants(*base["M4"]).items():
        allm["M4_" + k] = v
    for name, (P, tris) in allm.items():
        q = ms.quality(P, tris)
        Pc = P * UM
        g1, g2, glen = couples(Pc, tris)
        neg = {e: c for e, c in g1.items() if c < 0}
        nv_f3 = fm.node_areas(Pc, tris, "F3").sum()
        area = sum(fm.tri_area(Pc[list(t)]) for t in tris)
        conn = hashlib.sha256(json.dumps(sorted(sorted(int(v) for v in t) for t in tris)).encode()).hexdigest()
        fixtures[name] = {
            "points_um": P.tolist(), "triangles": [[int(v) for v in t] for t in tris], "quality": q,
            "connectivity_sha256": conn, "domain_um": [float(P[:, 0].max() - P[:, 0].min()), float(P[:, 1].max() - P[:, 1].min())],
            "n_edges": len(g1), "n_edges_negative_signed_couple": len(neg),
            "min_signed_couple_over_length": float(min(g1[e] / glen[e] for e in g1)),
            "signed_vs_abs_weight_rows": [{"edge": list(e), "signed_couple_cm": g1[e], "abs_couple_cm_predicted": g2[e],
                                           "length_cm": glen[e]} for e in sorted(g1)],
            "predicted_sum_NodeVolume_over_area_F3": float(nv_f3 / area),
        }
    spec = {
        "units": "coordinates um in fixtures; DEVSIM receives float64 cm = um*1e-4",
        "experiment_A": {"bc": "Potential=0 V on left contact (x=0), 1 V on right contact (x=L); top/bottom natural (zero normal flux)",
                         "analytic": "phi(x,y) = x/L  [V]", "no_node_source": True,
                         "E1": "Flux = (Potential@n0-Potential@n1)*EdgeInverseLength   [V/cm]",
                         "E2": "Flux = (Potential@n0-Potential@n1)*EdgeCouple          [V*cm] (solve.py form)"},
        "experiment_B": {"sigma_S_per_cm": 1.0, "dV_V": 1.0, "L_H": "domain of each mesh (M*: 2e-4 x 1e-4 cm; scale2: 4e-4 x 2e-4 cm)",
                         "analytic_current_A_per_cm_depth": "I = sigma*H/L*dV = 0.5 A/cm for every mesh (H/L = 0.5)",
                         "sign_convention": "get_contact_current values are recorded as returned; the check is |I| vs analytic and "
                                            "I_left + I_right = 0; the sign must be opposite between the two contacts and the "
                                            "same for every mesh",
                         "E1": "Current = sigma*(Potential@n0-Potential@n1)*EdgeInverseLength",
                         "E2": "Current = sigma*(Potential@n0-Potential@n1)*EdgeCouple"},
        "experiment_C": {"C1": "sum(NodeVolume*1) vs exact area",
                         "C3": {"analytic": "phi = (x^2 + y^2)/l^2 [V], l = 1e-4 cm", "laplacian": "4/l^2 = 4e8 V/cm^2",
                                "equation": "edge Flux = (Potential@n0-Potential@n1)*EdgeInverseLength; node source Z = +4/l^2",
                                "sign": "DEVSIM form div(Y)+Z=0 with Y=-grad(phi): -lap(phi)+Z=0 -> Z=+lap(phi)",
                                "bc": "Dirichlet phi on every boundary node (one contact on all boundary edges)"}},
        "tolerances": {"EXACT_V": 1e-10, "EXACT_I_REL": 1e-10, "SIGNIFICANT_REL": 1e-6, "WEIGHT_REL": 1e-12,
                       "solver": "direct, absolute_error=1e-30, relative_error=1e-13, maximum_iterations=20",
                       "justification": "linear problems, one direct-LU Newton step; ~50-node systems have rounding ~1e-13; "
                                        "EXACT_* leaves 1000x margin; SIGNIFICANT is 1e4 x EXACT"},
        "a_priori_predictions": [
            "P1 signed circumcentric weights (C_signed/L) have linear precision: phi=x is reproduced exactly on every valid mesh",
            "P2 on non-obtuse meshes DEVSIM absolute weights equal signed weights -> E1 exact on M1, M2",
            "P3 on obtuse meshes E1 (absolute) breaks linear precision: interior residual r_i = sum_j (w_abs - w_signed)(phi_i - phi_j)",
            "P4 if equation assembly multiplies an edge model by EdgeCouple, E2's effective weight is EdgeCouple^2 (not C/L)",
            "P5 Poisson (x^2+y^2): with DEVSIM's own volume (= 0.25*sum |C| L) and absolute weights the quadratic part is "
            "self-consistent; the residual at the analytic nodal values is the linear-precision defect only: "
            "r_i = -(2/l^2) * x_i . sum_j w_abs,ij (x_j - x_i)",
        ],
    }
    out = {"spec": spec, "fixtures": fixtures}
    p = os.path.join(HERE, "..", "data", "fixtures_7hc.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    for n, fx in fixtures.items():
        q = fx["quality"]
        print(f"{n:10s} pts={q['n_points']} tri={q['n_triangles']} cls={q['classes']} angle[{q['min_angle_deg']:.2f},{q['max_angle_deg']:.2f}] "
              f"delaunay_viol={q['exact_delaunay_violations']} overlap={q['exact_overlap_counts']['EXACT_POSITIVE_AREA_OVERLAP']} "
              f"ccw={q['all_ccw']} area={q['area_exact_um2']} neg_signed_couples={fx['n_edges_negative_signed_couple']}/{fx['n_edges']} "
              f"minCs/L={fx['min_signed_couple_over_length']:.4f} predNV/area={fx['predicted_sum_NodeVolume_over_area_F3']:.12f} "
              f"left={len(q['left_contact_nodes'])} right={len(q['right_contact_nodes'])} conn={fx['connectivity_sha256'][:12]}")
    print("fixtures_7hc.json sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())


if __name__ == "__main__":
    main()
