"""E6K independent analytic reference for the abrupt 1D p-n diode (pure Python, no DEVSIM / ViennaPS import). Criteria: ../PN_PLAN_v2.md.

Model (all cgs; q [C], lengths [cm], concentrations [cm^-3], tau [s], J [A/cm^2], V [V], forward bias = positive on the p side):
  * abrupt junction at x = 0, ACTIVE N_A (x < 0) and N_D (x > 0), full ionisation, Boltzmann statistics, constant mobilities, SRH with n1 = p1 = n_i.
  * depletion approximation: W(V) = sqrt(2 eps (V_bi - V) (1/N_A + 1/N_D) / q), x_p = W N_D/(N_A+N_D), x_n = W N_A/(N_A+N_D); the intrinsic-level potential is
    piecewise quadratic and is built here WITHOUT any solved DEVSIM array.
  * flat quasi-Fermi levels across the depletion region separated by V: n = n_i exp((Psi + V/2)/V_t), p = n_i exp((-Psi + V/2)/V_t) with Psi the intrinsic-level potential measured from the
    mid-point of the quasi-Fermi levels; Psi_p = V/2 - V_t ln(N_A/n_i) at x = -x_p, Psi_n = -V/2 + V_t ln(N_D/n_i) at x = +x_n (so n p = n_i^2 exp(V/V_t)).
  * J_diff: minority diffusion in the two neutral regions of finite length (ohmic contacts: excess = 0 at the contact), SRH recombination in the neutral regions through the diffusion length:
      J_diff = q n_i^2 [D_n coth(W_p'/L_n) / (N_A L_n) + D_p coth(W_n'/L_p) / (N_D L_p)] (exp(V/V_t) - 1),  W_n' = W_n - x_n(V), W_p' = W_p - x_p(V), L = sqrt(D tau).
  * J_SRH = q * integral_{-x_p}^{x_n} U dx with U = (n p - n_i^2) / (tau_p (n + n_i) + tau_n (p + n_i)) in the depletion region ONLY (the neutral-region recombination is already inside J_diff: no double counting).
    The integral is a composite Simpson rule on [-x_p, 0] and [0, x_n] separately; the Simpson refinement error is reported separately and is NOT a statement about the model error.
  * total J = J_diff + J_SRH, positive = conventional current from the p contact into the device (the DEVSIM convention measured in E6I: positive contact current is into the device).
  * not modelled: depletion-charge modulation (steady state), voltage drop across the neutral regions, high injection, field-dependent mobility, Auger, band-gap narrowing, tunnelling, QFL splitting inside the depletion region.
"""
import math

K_BOLTZMANN = 1.3806503e-23          # J/K, as simple_physics.py


def vt(temperature_k, q):
    return K_BOLTZMANN * temperature_k / q


def params(q, n_i, temperature_k, mu_n, mu_p, taun, taup, eps, n_a, n_d, w_p_cm, w_n_cm):
    v_t = vt(temperature_k, q)
    return {"q": q, "n_i": n_i, "T": temperature_k, "Vt": v_t, "mu_n": mu_n, "mu_p": mu_p, "taun": taun, "taup": taup, "eps": eps, "N_A": n_a, "N_D": n_d,
            "W_p": w_p_cm, "W_n": w_n_cm, "D_n": mu_n * v_t, "D_p": mu_p * v_t, "L_n": math.sqrt(mu_n * v_t * taun), "L_p": math.sqrt(mu_p * v_t * taup),
            "V_bi": v_t * math.log(n_a * n_d / n_i ** 2)}


def depletion(p, v):
    """Depletion-approximation geometry at applied voltage v (V_bi - v must be > 0)."""
    drive = p["V_bi"] - v
    if not drive > 0:
        raise ValueError("V_bi - V must be positive")
    w = math.sqrt(2.0 * p["eps"] * drive * (1.0 / p["N_A"] + 1.0 / p["N_D"]) / p["q"])
    x_p, x_n = w * p["N_D"] / (p["N_A"] + p["N_D"]), w * p["N_A"] / (p["N_A"] + p["N_D"])
    e_max = p["q"] * p["N_A"] * x_p / p["eps"]
    return {"W": w, "x_p": x_p, "x_n": x_n, "E_max": e_max, "V_drive": drive}


def psi(p, v, x):
    """Intrinsic-level potential Psi(x) [V] of the depletion approximation (piecewise quadratic), referenced to the mid quasi-Fermi level."""
    d = depletion(p, v)
    psi_p = v / 2.0 - p["Vt"] * math.log(p["N_A"] / p["n_i"])
    psi_n = -v / 2.0 + p["Vt"] * math.log(p["N_D"] / p["n_i"])
    if x <= -d["x_p"]:
        return psi_p
    if x >= d["x_n"]:
        return psi_n
    if x <= 0.0:
        return psi_p + p["q"] * p["N_A"] * (x + d["x_p"]) ** 2 / (2.0 * p["eps"])
    return psi_n - p["q"] * p["N_D"] * (d["x_n"] - x) ** 2 / (2.0 * p["eps"])


def carriers(p, v, x):
    """Explicit n(x), p(x) in the depletion region (flat quasi-Fermi levels)."""
    ps = psi(p, v, x)
    return p["n_i"] * math.exp((ps + v / 2.0) / p["Vt"]), p["n_i"] * math.exp((-ps + v / 2.0) / p["Vt"])


def srh_rate(p, n, pp):
    return (n * pp - p["n_i"] ** 2) / (p["taup"] * (n + p["n_i"]) + p["taun"] * (pp + p["n_i"]))


def _simpson(f, a, b, panels):
    if panels % 2:
        panels += 1
    h = (b - a) / panels
    s = f(a) + f(b)
    for i in range(1, panels):
        s += (4 if i % 2 else 2) * f(a + i * h)
    return s * h / 3.0


def j_srh(p, v, panels=2048):
    d = depletion(p, v)

    excess = p["n_i"] ** 2 * math.expm1(v / p["Vt"])      # n p - n_i^2 under flat quasi-Fermi levels; exactly 0 at V = 0 (no cancellation error)

    def integrand(x):
        n, pp = carriers(p, v, x)
        return excess / (p["taup"] * (n + p["n_i"]) + p["taun"] * (pp + p["n_i"]))
    return p["q"] * (_simpson(integrand, -d["x_p"], 0.0, panels) + _simpson(integrand, 0.0, d["x_n"], panels))


def coth(x):
    return 1.0 / math.tanh(x)


def j_diff(p, v):
    d = depletion(p, v)
    wp, wn = p["W_p"] - d["x_p"], p["W_n"] - d["x_n"]
    js = p["q"] * p["n_i"] ** 2 * (p["D_n"] * coth(wp / p["L_n"]) / (p["N_A"] * p["L_n"]) + p["D_p"] * coth(wn / p["L_p"]) / (p["N_D"] * p["L_p"]))
    return js * math.expm1(v / p["Vt"])


def reference(p, v, panels=2048):
    d = depletion(p, v)
    jd, js = j_diff(p, v), j_srh(p, v, panels)
    return {"V": v, "J_diff": jd, "J_srh": js, "J_model": jd + js, "W": d["W"], "x_p": d["x_p"], "x_n": d["x_n"], "E_max": d["E_max"],
            "J_srh_refined": j_srh(p, v, panels * 2), "srh_fraction": js / (jd + js) if (jd + js) != 0 else float("nan")}


def minority_excess_profile(p, v, s):
    """Hole excess p_n(s) - p_n0 in the n neutral region, s measured from the depletion edge x_n (s = 0 -> law of the junction), contact at s = W_n' (excess 0)."""
    d = depletion(p, v)
    wn = p["W_n"] - d["x_n"]
    p_n0 = p["n_i"] ** 2 / p["N_D"]
    return p_n0 * math.expm1(v / p["Vt"]) * math.sinh((wn - s) / p["L_p"]) / math.sinh(wn / p["L_p"])


def width_from_field(x_cm, e_abs):
    """Operational depletion width from a field profile: W_E = 2 * integral|E| dx / E_max (exact for the triangular field of the depletion approximation)."""
    area = 0.0
    for i in range(len(x_cm) - 1):
        area += 0.5 * (abs(e_abs[i]) + abs(e_abs[i + 1])) * (x_cm[i + 1] - x_cm[i])
    return 2.0 * area / max(abs(e) for e in e_abs)
