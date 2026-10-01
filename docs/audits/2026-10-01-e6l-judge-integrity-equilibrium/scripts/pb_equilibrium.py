"""E6L: equilibrium electric field of the symmetric abrupt junction -- depletion approximation vs Poisson-Boltzmann (PB) vs the stored DEVSIM edge values.
Pure Python + numpy, reads the committed E6K states.npz and pn_1d_diagnostic.json read-only. No DEVSIM / ViennaPS import, no new solve.

The PB reference is built ONLY from the device constants (q, n_i, V_t, eps, N); no stored Potential / carrier array enters it.
Stored arrays are used only for the quantities being judged (edge fields, node positions) and for the stated bookkeeping checks.

Derivation (equilibrium, 1D, Boltzmann carriers n = n_i e^{psi/V_T}, p = n_i e^{-psi/V_T}, psi = intrinsic-level potential, Fermi level at 0):
  Poisson:  d2psi/dx2 = -(q/eps) (p - n + N_D(x) - N_A(x)),   E = -dpsi/dx.
  On the n side (N_D = N, N_A = 0):  d2psi/dx2 = (q/eps)(2 n_i sinh(psi/V_T) - N).
  Multiply by dpsi/dx and integrate from a point at potential psi to the neutral region (psi -> psi_n, dpsi/dx -> 0 for an INFINITE neutral region):
     (1/2) E(psi)^2 = (q/eps) Int_psi^{psi_n} (N - 2 n_i sinh(u/V_T)) du
                    = (q/eps) [ N (psi_n - psi) - 2 n_i V_T (cosh(psi_n/V_T) - cosh(psi/V_T)) ],
  with charge neutrality 2 n_i sinh(psi_n/V_T) = N, i.e. psi_n = V_T a, a = asinh(N / (2 n_i)).
  Symmetry (N_A = N_D = N): psi(0) = 0 at the metallurgical junction, the p side mirrors the n side, so at x = 0:
     E_PB(0)^2 = (2 q V_T / eps) [ N a - 2 n_i (cosh a - 1) ].
  Distance from the junction to the point where |psi| = s (either side): x(s) = Int_0^s du / E(u); the PB average field over an edge [0, d] (or [-d, 0]) is s(d)/d.
  Finite domain: E6K's contacts sit 20 um from the junction with the potential fixed at the neutral value (DEVSIM contact BC); the infinite-region first integral differs from the
  finite-domain solution only through the exponential tail of the neutral region (decay length ~ the extrinsic Debye length, 12.6 nm, against 20 um), which is argued, not computed, to be negligible.
This derivation is done here; it is not quoted from a paper. DEVSIM's own equations (simple_physics.py: IntrinsicElectrons = n_i*exp(Potential/V_t),
IntrinsicHoles = n_i^2/IntrinsicElectrons, PotentialIntrinsicCharge = -ElectronCharge*kahan3(IntrinsicHoles, -IntrinsicElectrons, NetDoping),
ElectricField = (Potential@n0-Potential@n1)*EdgeInverseLength, PotentialEdgeFlux = Permittivity*ElectricField) are the discrete counterpart.
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
E6K = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
OUT = Path(__file__).resolve().parents[1] / "pb_equilibrium.json"


def constants():
    rp = json.load(open(E6K / "pn_1d_diagnostic.json"))["reference_parameters"]
    assert rp["N_A"] == rp["N_D"]
    return {"q": rp["q"], "n_i": rp["n_i"], "Vt": rp["Vt"], "eps": rp["eps"], "N": rp["N_A"], "V_bi": rp["V_bi"]}


def pb_field(c):
    a = math.asinh(c["N"] / (2 * c["n_i"]))
    psi_n = c["Vt"] * a

    def e_of(s):  # |E| at |psi| = s, 0 <= s < psi_n
        val = (2 * c["q"] / c["eps"]) * (c["N"] * (psi_n - s) - 2 * c["n_i"] * c["Vt"] * (math.cosh(a) - math.cosh(s / c["Vt"])))
        return math.sqrt(val)
    e0_closed = math.sqrt((2 * c["q"] * c["Vt"] / c["eps"]) * (c["N"] * a - 2 * c["n_i"] * (math.cosh(a) - 1.0)))
    return a, psi_n, e_of, e0_closed


def pb_edge_average(e_of, d, n_gauss):
    """Solve Int_0^s du/E(u) = d for s (Newton, Gauss-Legendre with n_gauss nodes) and return s/d, the PB mean field over an edge of length d starting at the junction."""
    xg, wg = np.polynomial.legendre.leggauss(n_gauss)

    def dist(s):
        u = 0.5 * s * (xg + 1.0)
        return 0.5 * s * float(sum(w / e_of(ui) for w, ui in zip(wg, u)))
    s = e_of(0.0) * d
    for _ in range(60):
        f = dist(s) - d
        s_new = s - f * e_of(s)
        if abs(s_new - s) <= 1e-16 * abs(s):
            s = s_new
            break
        s = s_new
    return s / d, s


def main():
    c = constants()
    a, psi_n, e_of, e0_closed = pb_field(c)
    e_dep0 = math.sqrt(2 * c["q"] * c["V_bi"] / c["eps"] * (c["N"] * c["N"] / (2 * c["N"])))
    res = {"constants": c, "a": a, "psi_n_V": psi_n, "psi_n_minus_psi_p_V": 2 * psi_n, "V_bi_V": c["V_bi"],
           "E_dep_0": e_dep0, "E_PB_0_closed_form": e0_closed, "E_PB_0_first_integral": e_of(0.0),
           "slope_qN_over_eps": c["q"] * c["N"] / c["eps"], "levels": {}}
    z = np.load(E6K / "states.npz")
    for lv in ("L0", "L1", "L2"):
        p = f"{lv}_rev__2__bias+0.000__"           # E6K stored key: device L*_rev, solve 2 (DD enabled at equilibrium), l-bias 0
        x, v, e = z[p + "x"], z[p + "Potential"], z[p + "ElectricField"]
        rec = {"snapshot": p.rstrip("_"), "n_nodes": int(len(x)), "n_edges": int(len(e)), "x_sorted": bool(np.all(np.diff(x) > 0))}
        cand = (v[:-1] - v[1:]) / (x[1:] - x[:-1])
        rec["edge_correspondence_max_rel_dev"] = float(np.max(np.abs(e - cand)) / np.max(np.abs(e)))
        i0 = int(np.flatnonzero(x == 0.0)[0])
        imax = int(np.argmax(np.abs(e)))
        rec.update({"junction_node_index": i0, "psi_dev_at_junction_V": float(v[i0]), "max_edge_index": imax,
                    "max_edge_x_left_cm": float(x[imax]), "max_edge_x_right_cm": float(x[imax + 1]), "max_edge_length_nm": float((x[imax + 1] - x[imax]) * 1e7)})
        for side, k in (("left", i0 - 1), ("right", i0)):
            d = float(x[k + 1] - x[k])
            e_dev = float(abs(e[k]))
            conv = {n: pb_edge_average(e_of, d, n)[0] for n in (4, 8, 16, 32, 64)}
            e_pb_edge = conv[64]
            first = e0_closed - res["slope_qN_over_eps"] * d / 2
            psi_pb = pb_edge_average(e_of, d, 64)[1]
            rec[side] = {"edge_index": k, "length_nm": d * 1e7, "E_devsim": e_dev, "E_PB_edge_mean": e_pb_edge,
                         "quadrature_n4_to_n64": {str(n): conv[n] for n in conv}, "quadrature_err_estimate": abs(conv[64] - conv[32]),
                         "first_order_estimate": first, "first_order_residual_vs_PB_edge": first - e_pb_edge,
                         "decomposition_V_per_cm": {"1_model_dep_minus_PB_center": e_dep0 - e0_closed,
                                                    "2_measurement_PB_center_minus_PB_edge_mean": e0_closed - e_pb_edge,
                                                    "3_discretisation_PB_edge_mean_minus_devsim": e_pb_edge - e_dev},
                         "edge_potential_drop_devsim_V": float(abs(v[k + 1] - v[k])), "edge_potential_drop_PB_V": psi_pb}
        # diagnostic (hypothesis support only): DEVSIM gives both junction edges the SAME field (the junction node has NetDoping 0 under the step()
        # convention and psi ~ 0, so its control-volume charge is ~0 and the two edge fluxes balance); compare with the PB mean over the combined two-edge interval
        dl, dr = rec["left"]["length_nm"] * 1e-7, rec["right"]["length_nm"] * 1e-7
        comb = (rec["left"]["edge_potential_drop_PB_V"] + rec["right"]["edge_potential_drop_PB_V"]) / (dl + dr)
        rec["combined_two_edge"] = {"E_devsim_left": rec["left"]["E_devsim"], "E_devsim_right": rec["right"]["E_devsim"],
                                    "PB_mean_over_both_edges": comb, "devsim_minus_PB_combined": rec["left"]["E_devsim"] - comb,
                                    "devsim_drop_both_edges_V": rec["left"]["edge_potential_drop_devsim_V"] + rec["right"]["edge_potential_drop_devsim_V"],
                                    "PB_drop_both_edges_V": rec["left"]["edge_potential_drop_PB_V"] + rec["right"]["edge_potential_drop_PB_V"]}
        rec["max_edge_side"] = "left" if imax == i0 - 1 else "right" if imax == i0 else "other"
        # W_E dependence: int|E|dx telescopes to the end-to-end potential drop, set by the contact boundary condition
        integ = float(np.sum(np.abs(e) * np.diff(x)))
        drop = float(abs(v[-1] - v[0]))
        rec["W_E_bookkeeping"] = {"int_absE_dx_V": integ, "end_to_end_potential_drop_V": drop, "contact_potentials_V": [float(v[0]), float(v[-1])],
                                  "W_E_cm": 2 * integ / float(np.max(np.abs(e))), "W_E_over_W_dep": (2 * integ / float(np.max(np.abs(e)))) / (2 * c["V_bi"] / e_dep0),
                                  "E_dep_over_E_max": e_dep0 / float(np.max(np.abs(e)))}
        res["levels"][lv] = rec
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"E_dep(0) {e_dep0:.4f}  E_PB(0) closed {e0_closed:.4f}  first-integral {e_of(0.0):.4f}  model diff {e_dep0 - e0_closed:.4f} V/cm ({(e_dep0 / e0_closed - 1) * 100:.3f} %)")
    print(f"psi_n - psi_p = {2 * psi_n:.10f} V vs V_bi = {c['V_bi']:.10f} V")
    for lv, r in res["levels"].items():
        print(lv, f"nodes {r['n_nodes']} edges {r['n_edges']} sorted {r['x_sorted']} edge-map dev {r['edge_correspondence_max_rel_dev']:.1e} psi(0) {r['psi_dev_at_junction_V']:.3e} V max edge {r['max_edge_side']} "
                  f"[{r['max_edge_x_left_cm']:.9e}, {r['max_edge_x_right_cm']:.3e}] {r['max_edge_length_nm']:.6f} nm")
        for side in ("left", "right"):
            s = r[side]
            dcmp = s["decomposition_V_per_cm"]
            print(f"   {side}: d {s['length_nm']:.6f} nm  E_dev {s['E_devsim']:.4f}  E_PB_edge {s['E_PB_edge_mean']:.4f}  1st-order {s['first_order_estimate']:.4f} (resid {s['first_order_residual_vs_PB_edge']:+.4f})"
                  f"  quad err {s['quadrature_err_estimate']:.1e}  model {dcmp['1_model_dep_minus_PB_center']:.2f}  meas {dcmp['2_measurement_PB_center_minus_PB_edge_mean']:.2f}  discr {dcmp['3_discretisation_PB_edge_mean_minus_devsim']:+.2f}"
                  f"  dpsi dev {s['edge_potential_drop_devsim_V']:.6e} PB {s['edge_potential_drop_PB_V']:.6e}")
        cb = r["combined_two_edge"]
        print(f"   both junction edges: E_dev left {cb['E_devsim_left']:.6f} right {cb['E_devsim_right']:.6f}; PB mean over both {cb['PB_mean_over_both_edges']:.4f}; dev - PB {cb['devsim_minus_PB_combined']:+.4f}")
        w = r["W_E_bookkeeping"]
        print(f"   int|E|dx {w['int_absE_dx_V']:.12f} V, end-to-end drop {w['end_to_end_potential_drop_V']:.12f} V, W_E/W_dep {w['W_E_over_W_dep']:.6f}, E_dep/E_max {w['E_dep_over_E_max']:.6f}, contacts {w['contact_potentials_V']}")


if __name__ == "__main__":
    main()
