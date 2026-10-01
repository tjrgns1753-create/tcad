"""E6K judge (pure Python): six separate category verdicts, NaN / inf / None / non-numeric can never pass (`finite and value <= limit`). Criteria: ../PN_PLAN_v2.md section 8.
No overall PASS is produced and PN_PHYSICS_VALIDATED is never emitted: the categories are reported separately."""
import math

TOL = {"E_max_rel": 0.03, "W_rel": 0.05, "J_model_rel": 0.10, "minority_rel": 0.10, "mesh_J_0.6": 0.01, "mesh_J_-1.0": 0.02, "mesh_E_max": 0.02, "unit_control": 1.0e-6}
J_BIASES = ("0.5", "0.6", "-0.5", "-1.0")            # judged in E; 0.3 is reported
CATEGORIES = ("A_CURRENT_UNIT_CONTRACT", "B_PRODUCTION_PATH_EXECUTED", "C_NUMERICAL_CONVERGENCE_AND_MESH_SENSITIVITY", "D_ANALYTICAL_ELECTROSTATICS_COMPARISON",
              "E_APPROXIMATE_SRH_DIFFUSION_REFERENCE_COMPARISON", "F_MINORITY_CARRIER_PROFILE_COMPARISON")


def f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


def le(value, limit):
    v = f(value)
    return math.isfinite(v) and v <= limit


def rel(a, b):
    try:
        return abs(f(a) - f(b)) / abs(f(b))
    except ZeroDivisionError:
        return float("nan")


def cat(checks, evaluated=True):
    if not evaluated:
        return {"verdict": "NOT_EVALUATED", "checks": checks}
    return {"verdict": "PASS" if checks and all(c["pass"] for c in checks) else "FAIL", "checks": checks}


def chk(name, value, limit):
    return {"name": name, "value": value, "limit": limit, "pass": le(value, limit)}


def judge(m):
    out = {}
    # A: unit contract (1D result must carry NO established unit; display must say so); 1D unit evidence is recorded separately
    a = [{"name": "1D result metadata current_unit is None (production does not assume a unit)", "value": m["unit"].get("metadata_unit_1d"), "limit": None,
          "pass": m["unit"].get("metadata_unit_1d") is None and m["unit"].get("metadata_dimension_1d") == 1},
         {"name": "format_current of a 1D value says 'unit not established'", "value": m["unit"].get("formatted_1d"), "limit": None,
          "pass": isinstance(m["unit"].get("formatted_1d"), str) and "unit not established" in m["unit"]["formatted_1d"]},
         chk("E6J GUI evidence: failed checks of the preserved JSON", m["unit"].get("e6j_failed_checks"), 0)]
    out[CATEGORIES[0]] = cat(a)
    # B: production path executed
    b = []
    for name, d in m["devices"].items():
        b.append({"name": f"{name}: production sweep called once, expected solves, doping written, dimension 1, no exception",
                  "value": {k: d.get(k) for k in ("production_calls", "solves", "expected_solves", "dimension", "error")}, "limit": None,
                  "pass": d.get("production_calls") == 1 and d.get("solves") == d.get("expected_solves") and d.get("dimension") == 1 and d.get("writes_ok") is True and not d.get("error")})
    out[CATEGORIES[1]] = cat(b)
    unit_ok = m["unit"].get("established_by_control") is True
    # C: convergence and mesh sensitivity (needs the 1D unit control to have passed, else PN numbers are not judged at all)
    if not unit_ok:
        for c in CATEGORIES[2:]:
            out[c] = cat([], evaluated=False)
        out["unit_control"] = {"verdict": "UNIT_NOT_ESTABLISHED", "value": m["unit"].get("control_ratio"), "checks": []}
        return out
    c = [{"name": f"{n}: converged, all solves returned, finite currents", "value": d.get("converged"), "limit": None, "pass": d.get("converged") is True} for n, d in m["devices"].items()]
    J = m["J"]
    c.append(chk("J(0.6 V) L1 vs L2 relative difference", rel(J["L1"]["0.6"], J["L2"]["0.6"]), TOL["mesh_J_0.6"]))
    c.append(chk("J(-1.0 V) L1 vs L2 relative difference", rel(J["L1"]["-1.0"], J["L2"]["-1.0"]), TOL["mesh_J_-1.0"]))
    c.append(chk("E_max(-1.0 V) L1 vs L2 relative difference", rel(m["Emax"]["L1"]["-1.0"], m["Emax"]["L2"]["-1.0"]), TOL["mesh_E_max"]))
    out[CATEGORIES[2]] = cat(c)
    # D: electrostatics (L2)
    d_ = []
    for v in ("0.0", "-1.0"):
        d_.append(chk(f"E_max({v} V) vs depletion approximation, relative", rel(m["Emax"]["L2"][v], m["ref_E"][v]["E_max"]), TOL["E_max_rel"]))
        d_.append(chk(f"W_E({v} V) = 2 int|E|dx / E_max vs depletion width, relative", rel(m["WE"]["L2"][v], m["ref_E"][v]["W"]), TOL["W_rel"]))
    out[CATEGORIES[3]] = cat(d_)
    # E: approximate SRH + diffusion reference (first-diagnostic comparison level only)
    e = []
    for v in J_BIASES:
        dev, ref = J["L2"][v], m["ref"][v]["J_model"]
        e.append({"name": f"J({v} V) sign equals the reference sign", "value": [dev, ref], "limit": None, "pass": math.isfinite(f(dev)) and math.isfinite(f(ref)) and f(dev) * f(ref) > 0})
        e.append(chk(f"J({v} V) vs J_diff + J_SRH, relative", rel(dev, ref), TOL["J_model_rel"]))
    out[CATEGORIES[4]] = cat(e)
    # F: minority carrier profile at 0.6 V (L2)
    fc = [chk(f"hole excess at s = {s} um vs sinh solution, relative", rel(dv, rv), TOL["minority_rel"]) for s, dv, rv in zip(m["minority"]["s_um"], m["minority"]["dev"], m["minority"]["ref"])]
    out[CATEGORIES[5]] = cat(fc)
    return out
