"""Batch 7H-D section 4: physics parameters, analytic reference ranges and
tolerances, fixed BEFORE the first semiconductor solve. Parameter values are
the ones DEVSIM 2.11.0's SetSiliconParameters actually sets (read without a
solve, data/production_sg_path.json). Writes data/fixed_physics.json."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

P = json.load(open(os.path.join(DATA, "production_sg_path.json"), encoding="utf-8"))["parameters"]
Q = P["ElectronCharge"]            # C
EPS = P["Permittivity"]            # F/cm
NI = P["n_i"]                      # cm^-3
VT = P["V_t"]                      # V
MU_N, MU_P = P["mu_n"], P["mu_p"]  # cm^2/(V s)
NA = ND = 1.0e17                   # cm^-3, fully ionized, abrupt, symmetric

UM = 1.0e-4                        # cm per um
X_MIN_UM, X_MAX_UM = -0.5, 0.5     # 2D and 1D synthetic domain (junction at x = 0)
H_UM = 0.1                         # 2D height; 2D current is per unit depth (A/cm)
L3 = {"x_um": [-2.0, 2.0], "y_um": [-2.0, 0.0], "H_um": 2.0}


def analytic():
    vbi = VT * math.log(NA * ND / NI ** 2)
    w = math.sqrt(2.0 * EPS * vbi / Q * (NA + ND) / (NA * ND))
    xp = w * ND / (NA + ND)
    xn = w * NA / (NA + ND)
    emax = Q * ND * xn / EPS
    ld = math.sqrt(EPS * VT / (Q * ND))
    j_scale = Q * MU_N * ND * VT / ((X_MAX_UM - X_MIN_UM) * UM)
    return {"V_T_V": VT, "n_i_cm3": NI, "V_bi_V": vbi, "W_depletion_cm": w, "W_depletion_um": w / UM,
            "x_p_um": xp / UM, "x_n_um": xn / UM, "E_peak_V_per_cm": emax, "L_Debye_um": ld / UM,
            "psi_p_contact_V": -VT * math.log(NA / NI), "psi_n_contact_V": VT * math.log(ND / NI),
            "p_side_majority_p_cm3": NA, "p_side_minority_n_cm3": NI ** 2 / NA,
            "n_side_majority_n_cm3": ND, "n_side_minority_p_cm3": NI ** 2 / ND,
            "J_scale_A_per_cm2": j_scale, "I_scale_2D_A_per_cm": j_scale * H_UM * UM,
            "quasi_neutral_length_each_side_over_W": ((X_MAX_UM - 0.0) * UM - xn) / w,
            "note": "depletion approximation = sanity/reference range only, not the exact DD solution"}


SPEC = {
    "T_K": 300.0, "doping": {"NA_cm3": NA, "ND_cm3": ND, "ionization": "fully ionized, active",
                             "junction": "x = 0 um; p-side x < 0 (NetDoping = -NA), n-side x > 0 (NetDoping = +ND)",
                             "node_exactly_at_x0": "NetDoping = 0 (symmetric step: its dual cell is half p, half n); same rule for every mesh and 1D"},
    "domain_synthetic_um": {"x": [X_MIN_UM, X_MAX_UM], "y_2d": [0.0, H_UM]}, "L3_domain": L3,
    "contacts": "left = boundary at x_min (p-side), right = boundary at x_max (n-side); ohmic via production "
                "setup_semiconductor_potential_equation / setup_drift_diffusion_equation (simple_physics helpers); "
                "top/bottom: no boundary condition (natural zero normal flux)",
    "silicon_parameters_devsim": P,
    "models": {"mobility": "constant mu_n, mu_p (simple_physics)", "recombination": "SRH only, taun = taup = 1e-8 s "
               "(production setup_drift_diffusion_equation), n1 = p1 = n_i", "generation": "SRH (USRH < 0) only; no impact ionization, no optical"},
    "solver": {"poisson": {"type": "dc", "absolute_error": 1e-10, "relative_error": 1e-10, "maximum_iterations": 50},
               "drift_diffusion": {"type": "dc", "absolute_error": 1e30, "relative_error": 1e-10, "maximum_iterations": 50}},
    "bias": {"contact": "left (p-side); right grounded; forward = positive", "targets_V": [-0.10, 0.0, 0.05, 0.10],
             "continuation": "from the 0 V DD state in steps of 0.025 V: forward 0.025, 0.05, 0.075, 0.10; reverse run on a "
                             "freshly rebuilt device: -0.025, -0.05, -0.075, -0.10; no step changed after results"},
    "reference_1d": {"dx_um": [0.02, 0.01, 0.005, 0.0025], "setup": "same physics, contacts, doping rule",
                     "convergence": "successive-level differences in V_bi, psi, log10 n, log10 p and bias currents must "
                                    "decrease monotonically with refinement; otherwise ONE_DIMENSIONAL_REFERENCE_NOT_CONVERGED"},
    "tolerances": {
        "positivity": "every node: n > 0, p > 0, finite",
        "eq_current": "|I_contact| <= 1e-10 * I_scale (2D: A/cm, 1D: A/cm^2)",
        "conservation": "|I_left + I_right| <= 1e-6 * max(|I_left|, |I_right|) + 1e-10 * I_scale",
        "quasi_fermi_eq": "max |phi_n - phi_n(median)| and |phi_p - phi_p(median)| <= 1e-6 V at 0 V, phi_n = psi - V_T ln(n/n_i), phi_p = psi + V_T ln(p/n_i)",
        "mass_action_eq": "max |n p / n_i^2 - 1| <= 1e-6 at 0 V",
        "M2_identity_vs_1D_same_dx": "|dpsi| <= 1e-9 V at every node; bias current rel diff <= 1e-8 (M2 has the same x-lines as 1D dx=0.02)",
        "agreement_vs_1D": "potential: max |psi_2D - psi_1D,finest(interp)| <= 3 U_psi + 1e-6 V, U_psi = max |psi_1D,0.02 - psi_1D,finest(interp)|; "
                           "current: rel diff vs J_1D,finest*H <= 3 U_I + 1e-6, U_I = |J_0.02 - J_finest|/|J_finest|",
        "overshoot": "psi within [psi_left_contact, psi_right_contact] +- 1e-9 V; at 0 V n within [min, max] of contact n values *(1 +- 1e-9), same for p",
        "block_sign": "expected off-diagonal sign of each same-variable Jacobian block = the sign observed on M2 D0; any strictly opposite sign is a violation",
    },
}

if __name__ == "__main__":
    out = {"spec": SPEC, "analytic_reference": analytic()}
    with open(os.path.join(DATA, "fixed_physics.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps(out["analytic_reference"], indent=1))
