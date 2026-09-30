"""Batch 7H-E6I pure judge for the uniform-resistor DD current test. Criteria: ../CRITERIA.md. No DEVSIM / ViennaPS import.
Every comparison is `finite and value <= limit`: NaN / inf / None can never pass."""
import math
from typing import Any, Dict, List

BIASES = {"0V": 0.0, "+1mV": 1.0e-3, "-1mV": -1.0e-3, "+2mV": 2.0e-3}
TOL_CURRENT = 1.0e-2
TOL_HOLE_SHARE = 1.0e-6
TOL_CONSERVATION = 1.0e-6
TOL_SYMMETRY = 1.0e-2
TOL_LINEARITY = 1.0e-2
TOL_MESH = 1.0e-2
TOL_EQUILIBRIUM = 1.0e-4
TOL_N_UNIFORM = 1.0e-4
TOL_PSI_LINEAR = 1.0e-2
# Criterion 1 covers the numeric results only (currents, carrier / potential / recombination summaries); string metadata is not judged.
# A missing key is treated as not finite.
FINITE_KEYS = ("I_max_total", "I_min_total", "Ie_max", "Ie_min", "Ih_max", "Ih_min", "n_uniformity", "psi_lin", "p_min_over_p0", "p_max_over_p0",
               "max_abs_USRH", "recombination_current_A_per_cm")


def theory(n_donor, n_acceptor, n_i, q, mu_n, mu_p, height_cm, length_cm):
    """Non-degenerate, fully ionised, constant-mobility resistor. Numerically stable n0 / p0 (majority from the quadratic root, minority from n_i^2)."""
    net = n_donor - n_acceptor
    root = math.sqrt(net * net + 4.0 * n_i * n_i)
    if net >= 0:
        n0 = 0.5 * (net + root)
        p0 = n_i * n_i / n0
    else:
        p0 = 0.5 * (-net + root)
        n0 = n_i * n_i / p0
    sigma = q * (mu_n * n0 + mu_p * p0)
    g = sigma * height_cm / length_cm
    return {"n0": n0, "p0": p0, "sigma_S_per_cm": sigma, "G_A_per_V_per_cm_depth": g, "I_ref": g * 1.0e-3}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def le(value, limit) -> bool:
    v = _f(value)
    return math.isfinite(v) and math.isfinite(limit) and v <= limit


def all_finite(obj) -> bool:
    if isinstance(obj, dict):
        return all(all_finite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(all_finite(v) for v in obj)
    if isinstance(obj, str) or obj is None:
        return False
    return math.isfinite(_f(obj))


def _rel(a, b):
    try:
        return abs(_f(a) - _f(b)) / abs(_f(b))
    except ZeroDivisionError:
        return float("nan")


def judge(th: Dict[str, float], meshes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    g, i_ref = th["G_A_per_V_per_cm_depth"], th["I_ref"]
    checks: List[Dict[str, Any]] = []

    def add(cid, name, value, limit):
        checks.append({"id": cid, "name": name, "value": value, "limit": limit, "pass": le(value, limit)})

    for key, m in meshes.items():
        b = m["biases"]
        numeric = {label: {k: b[label].get(k) for k in FINITE_KEYS} for label in BIASES}
        states_ok = all(bool(b[label].get("finite_arrays")) for label in BIASES)
        add(1, f"{key}: all values finite", 0.0 if (all_finite(numeric) and states_ok) else 1.0, 0.0)
        for label, v in BIASES.items():
            if v == 0.0:
                continue
            for term, sgn in (("max", +1.0), ("min", -1.0)):
                ith = sgn * g * v
                add(2, f"{key} {label} I_total(Si_x{term}) relative error", _rel(b[label][f"I_{term}_total"], ith), TOL_CURRENT)
                add(2, f"{key} {label} I_electron(Si_x{term}) relative error", _rel(b[label][f"Ie_{term}"], ith), TOL_CURRENT)
                try:
                    share = abs(_f(b[label][f"Ih_{term}"])) / abs(_f(b[label][f"I_{term}_total"]))
                except ZeroDivisionError:
                    share = float("nan")
                add(2, f"{key} {label} hole share at Si_x{term}", share, TOL_HOLE_SHARE)
            add(8, f"{key} {label} electron uniformity max|n/n0-1|", b[label].get("n_uniformity"), TOL_N_UNIFORM)
            add(8, f"{key} {label} potential linearity", b[label].get("psi_lin"), TOL_PSI_LINEAR)
        for label in BIASES:
            add(3, f"{key} {label} |I_max + I_min| / I_ref", abs(_f(b[label]["I_max_total"]) + _f(b[label]["I_min_total"])) / i_ref, TOL_CONSERVATION)
        for term in ("max", "min"):
            ref = _f(b["+1mV"][f"I_{term}_total"])
            try:
                sym = abs(ref + _f(b["-1mV"][f"I_{term}_total"])) / abs(ref)
            except ZeroDivisionError:
                sym = float("nan")
            add(4, f"{key} odd symmetry at Si_x{term}", sym, TOL_SYMMETRY)
            add(5, f"{key} linearity at Si_x{term}", _rel(b["+2mV"][f"I_{term}_total"], 2.0 * ref), TOL_LINEARITY)
            add(7, f"{key} equilibrium |I(0V)| / I_ref at Si_x{term}", abs(_f(b["0V"][f"I_{term}_total"])) / i_ref, TOL_EQUILIBRIUM)
    for fam in sorted({m["family"] for m in meshes.values() if m["family"] != "uniform"}):
        fine = [meshes.get(f"{fam}_{n}") for n in (16, 32)]
        if any(x is None for x in fine):
            add(6, f"{fam}: n = 16 and 32 both present", float("nan"), 0.0)
            continue
        g16, g32 = (_f(x["biases"]["+1mV"]["I_max_total"]) / 1.0e-3 for x in fine)
        add(6, f"{fam}: |G(32) - G(16)| / G(32)", _rel(g16, g32), TOL_MESH)
    return {"checks": checks, "pass": bool(checks) and all(c["pass"] for c in checks), "failed": [c for c in checks if not c["pass"]]}
