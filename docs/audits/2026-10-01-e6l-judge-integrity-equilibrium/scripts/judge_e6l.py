"""E6L strict re-judge of the E6K evidence (pure Python + numpy; no DEVSIM / ViennaPS import).

Fail-closed evidence contract, checked BEFORE any physics comparison:
  * required devices, mesh levels, biases and the minority positions [3, 5, 8] um must all be present, with the exact array lengths;
  * a numeric field accepts only int / float that is finite -- never bool, str (also numeric strings), None, NaN or inf; a count is a non-negative int, never bool;
  * duplicated fields (device record vs metrics vs result table vs states.npz vs a recomputed reference) must agree; a contradiction is never resolved by picking one copy;
  * the 1D unit control is RECOMPUTED from the raw contact currents and the device parameters (sigma V / L); a stored True flag or ratio is never trusted.
Any violation -> every category is EVIDENCE_INTEGRITY_FAIL. A unit control that does not hold -> C..F are BLOCKED_UNIT_NOT_ESTABLISHED.
The physics tolerances are imported unchanged from the E6K judge. No overall PASS and no PN_PHYSICS_VALIDATED is ever produced.
"""
import math
import sys
from pathlib import Path

E6K_SCRIPTS = Path(__file__).resolve().parents[2] / "2026-10-01-e6k-pn-1d-diagnostic" / "scripts"
sys.path.insert(0, str(E6K_SCRIPTS))
import judge_e6k as OLD  # noqa: E402  (tolerances only; read-only)
import pn_reference as R  # noqa: E402

TOL = dict(OLD.TOL)
CATEGORIES = OLD.CATEGORIES
REQUIRED_DEVICES = ("control", "L0_fwd", "L0_rev", "L1_fwd", "L1_rev", "L2_fwd", "L2_rev")
LEVELS = ("L0", "L1", "L2")
VOLTAGES = {"control": [0.001], "fwd": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], "rev": [-0.25, -0.5, -0.75, -1.0]}
J_KEYS = ("0.3", "0.5", "0.6", "-0.5", "-1.0")
JUDGED_J = ("0.5", "0.6", "-0.5", "-1.0")
E_KEYS = ("0.0", "-1.0")
S_UM = [3.0, 5.0, 8.0]
DEVICE_COUNT_FIELDS = ("production_calls", "solves", "expected_solves", "dimension", "nodes")
DUPLICATED = ("production_calls", "solves", "expected_solves", "dimension", "writes_ok", "error", "converged")
PARAM_KEYS = ("ElectronCharge", "n_i", "T", "V_t", "mu_n", "mu_p", "taun", "taup", "Permittivity")
REF_PARAM_KEYS = ("q", "n_i", "T", "Vt", "mu_n", "mu_p", "taun", "taup", "eps", "N_A", "N_D", "W_p", "W_n", "D_n", "D_p", "L_n", "L_p", "V_bi")
EXACT = 1e-12          # copies / recomputations of the same number must agree to round-off


def is_num(v):
    return type(v) in (int, float) and math.isfinite(v)


def is_count(v):
    return type(v) is int and v >= 0


def same(a, b):
    """Duplicated values: identical type class and equal (no 1 == True, no '1' == 1)."""
    if is_num(a) and is_num(b):
        return a == b
    return type(a) is type(b) and a == b


def close(a, b, tol=EXACT):
    return is_num(a) and is_num(b) and abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


class Integrity:
    def __init__(self):
        self.problems = []

    def need(self, cond, msg):
        if not cond:
            self.problems.append(msg)
        return bool(cond)


def _get(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _snapshot(npz, device, bias):
    """Last stored DD snapshot of `device` whose recorded l-bias equals `bias` (keys written by the E6K test: <device>__<solve>__bias<+v.vvv>__<array>)."""
    tag = f"bias{bias:+.3f}"
    idx = sorted({int(k.split("__")[1]) for k in npz.files if k.startswith(device + "__") and f"__{tag}__" in k})
    if not idx:
        return None
    p = f"{device}__{idx[-1]}__{tag}__"
    try:
        return {a: npz[p + a] for a in ("x", "Potential", "Electrons", "Holes", "ElectricField")}
    except KeyError:
        return None


def _field_metrics(s):
    import numpy as np
    x, e, v = s["x"], s["ElectricField"], s["Potential"]
    ok = len(e) == len(x) - 1 and len(v) == len(x) and bool(np.all(np.diff(x) > 0))
    if ok:   # node/edge correspondence is CHECKED, not assumed: E_i == (V_i - V_i+1) / (x_i+1 - x_i)
        cand = (v[:-1] - v[1:]) / (x[1:] - x[:-1])
        ok = bool(np.max(np.abs(e - cand)) <= 1e-9 * np.max(np.abs(e)))
    if not ok:
        return None
    xm = 0.5 * (x[:-1] + x[1:])
    return {"E_max": float(np.max(np.abs(e))), "W_E": float(R.width_from_field(list(xm), list(np.abs(e))))}


def validate(out, npz, e6j=None):
    I = Integrity()
    devs, met = out.get("devices"), out.get("metrics")
    I.need(isinstance(devs, dict) and isinstance(met, dict), "devices / metrics missing")
    if I.problems:
        return I, None
    md = met.get("devices") if isinstance(met.get("devices"), dict) else {}
    clean = {"devices": {}}
    # devices (raw records) and their duplicates in metrics
    for name in REQUIRED_DEVICES:
        d = devs.get(name)
        if not I.need(isinstance(d, dict), f"device {name} missing"):
            continue
        kind = "control" if name == "control" else name.split("_")[1]
        I.need(isinstance(d.get("voltages"), list) and len(d["voltages"]) == len(VOLTAGES[kind]) and all(is_num(a) and a == b for a, b in zip(d["voltages"], VOLTAGES[kind])),
               f"{name}: voltages differ from the plan {VOLTAGES[kind]}")
        for k in DEVICE_COUNT_FIELDS:
            I.need(is_count(d.get(k)), f"{name}: {k} is not a non-negative int ({d.get(k)!r})")
        I.need(is_count(d.get("expected_solves")) and d["expected_solves"] == 2 + len(VOLTAGES[kind]), f"{name}: expected_solves is not 2 + #voltages")
        for k in ("converged", "writes_ok", "has_current_convention_note"):
            I.need(type(d.get(k)) is bool, f"{name}: {k} is not a bool")
        I.need(d.get("error") is None or isinstance(d.get("error"), str), f"{name}: error field malformed")
        cur = d.get("currents")
        ok = isinstance(cur, list) and len(cur) == len(VOLTAGES[kind]) and all(
            isinstance(c, dict) and is_num(c.get("V")) and c["V"] == v and is_num(c.get("I_l")) and is_num(c.get("I_r")) for c, v in zip(cur, VOLTAGES[kind]))
        I.need(ok, f"{name}: currents missing / malformed / not at the planned voltages")
        par = d.get("params")
        I.need(isinstance(par, dict) and all(is_num(par.get(k)) for k in PARAM_KEYS), f"{name}: device parameters missing or not numeric")
        for k in ("donors", "acceptors"):
            I.need(isinstance(d.get(k), list) and all(is_num(a) for a in d[k]), f"{name}: {k} not a numeric list")
        meta = d.get("metadata")
        I.need(isinstance(meta, dict) and "current_unit" in meta and is_count(meta.get("device_dimension")), f"{name}: metadata incomplete")
        m = md.get(name)
        if I.need(isinstance(m, dict), f"metrics.devices.{name} missing"):
            for k in DUPLICATED:
                I.need(k in m and k in d and same(m[k], d[k]), f"{name}: metrics.devices.{k}={m.get(k)!r} contradicts the device record {d.get(k)!r}")
        clean["devices"][name] = d
    I.need(set(md) == set(REQUIRED_DEVICES), f"metrics.devices has extra/missing entries: {sorted(md)}")
    if I.problems:
        return I, None
    # J / Emax / WE completeness, equality with the raw device record and the result table
    for grp, keys in (("J", J_KEYS), ("Emax", E_KEYS), ("WE", E_KEYS)):
        g = met.get(grp)
        I.need(isinstance(g, dict) and set(g) == set(LEVELS), f"metrics.{grp} levels {sorted(g) if isinstance(g, dict) else g} != {LEVELS}")
        for lv in LEVELS:
            row = _get(met, grp, lv)
            I.need(isinstance(row, dict) and set(row) == set(keys) and all(is_num(row[k]) for k in keys), f"metrics.{grp}.{lv} incomplete or non-numeric")
    if I.problems:
        return I, None
    for lv in LEVELS:
        for k in J_KEYS:
            v = float(k)
            dev = clean["devices"][f"{lv}_{'fwd' if v > 0 else 'rev'}"]
            raw = next(c["I_l"] for c in dev["currents"] if c["V"] == v)
            I.need(same(met["J"][lv][k], raw), f"J {lv} {k}: metrics {met['J'][lv][k]!r} != raw device current {raw!r}")
            I.need(same(_get(out, "table", lv, k, "I_l_raw"), raw), f"J {lv} {k}: result table != raw device current")
    # states.npz cross-check (E_max, W_E, minority) -- the stored arrays, with node/edge correspondence verified
    if not I.need(npz is not None, "states.npz missing"):
        return I, None
    for lv in LEVELS:
        for k in E_KEYS:
            s = _snapshot(npz, f"{lv}_rev", float(k))
            fm = _field_metrics(s) if s is not None else None
            if I.need(fm is not None, f"npz snapshot {lv}_rev bias {k} missing or node/edge correspondence not verified"):
                I.need(close(fm["E_max"], met["Emax"][lv][k]), f"E_max {lv} {k}: metrics != recomputed from states.npz")
                I.need(close(fm["W_E"], met["WE"][lv][k]), f"W_E {lv} {k}: metrics != recomputed from states.npz")
    # reference: parameters equal the device parameters; values recomputed
    rp = out.get("reference_parameters")
    if I.need(isinstance(rp, dict) and all(is_num(rp.get(k)) for k in REF_PARAM_KEYS), "reference_parameters missing or not numeric"):
        dp = clean["devices"]["L2_fwd"]["params"]
        for a, b in (("q", "ElectronCharge"), ("n_i", "n_i"), ("T", "T"), ("mu_n", "mu_n"), ("mu_p", "mu_p"), ("taun", "taun"), ("taup", "taup"), ("eps", "Permittivity")):
            I.need(same(rp[a], dp[b]), f"reference_parameters.{a} != L2_fwd device parameter {b}")
        P = R.params(rp["q"], rp["n_i"], rp["T"], rp["mu_n"], rp["mu_p"], rp["taun"], rp["taup"], rp["eps"], rp["N_A"], rp["N_D"], rp["W_p"], rp["W_n"])
        for k in REF_PARAM_KEYS:
            I.need(close(P[k], rp[k]), f"reference_parameters.{k} not reproducible")
        I.need(rp["N_A"] == 1e17 and rp["N_D"] == 1e17 and rp["W_p"] == 20e-4 and rp["W_n"] == 20e-4, "reference geometry/doping differ from the plan")
        ref, refE = met.get("ref"), met.get("ref_E")
        I.need(isinstance(ref, dict) and set(ref) == set(JUDGED_J), "metrics.ref keys incomplete")
        I.need(isinstance(refE, dict) and set(refE) == set(E_KEYS), "metrics.ref_E keys incomplete")
        if not I.problems:
            for k in J_KEYS:
                r = R.reference(P, float(k))
                if k in JUDGED_J:   # every field of the stored reference record, not only the judged one
                    rec = ref.get(k)
                    I.need(isinstance(rec, dict) and set(rec) == set(r) and all(close(rec[f], r[f]) or (rec[f] == r[f] == 0) for f in r),
                           f"ref {k}: stored record differs from the recomputed reference")
                I.need(close(_get(out, "table", "L2", k, "J_model"), r["J_model"]), f"table J_model {k} not reproducible")
            for k in E_KEYS:
                dpl = R.depletion(P, float(k))
                I.need(close(_get(refE, k, "E_max"), dpl["E_max"]) and close(_get(refE, k, "W"), dpl["W"]), f"ref_E {k} not reproducible")
            mi = met.get("minority")
            ok = isinstance(mi, dict) and isinstance(mi.get("s_um"), list) and len(mi["s_um"]) == 3 and all(is_num(a) and a == b for a, b in zip(mi["s_um"], S_UM))
            ok = ok and all(isinstance(mi.get(k), list) and len(mi[k]) == 3 and all(is_num(a) for a in mi[k]) for k in ("dev", "ref"))
            if I.need(ok, "minority: positions must be exactly [3, 5, 8] um with 3 measured and 3 reference values"):
                import numpy as np
                s = _snapshot(npz, "L2_fwd", 0.6)
                if I.need(s is not None, "npz snapshot L2_fwd 0.6 V missing"):
                    x_n = R.depletion(P, 0.6)["x_n"]
                    p_n0 = P["n_i"] ** 2 / P["N_D"]
                    for j, su in enumerate(S_UM):
                        dev = float(np.interp(x_n + su * 1e-4, s["x"], s["Holes"]) - p_n0)
                        I.need(close(mi["dev"][j], dev), f"minority dev at {su} um != recomputed from states.npz")
                        I.need(close(mi["ref"][j], R.minority_excess_profile(P, 0.6, su * 1e-4)), f"minority ref at {su} um not reproducible")
    # unit control: recomputed from raw currents; stored values must agree with the recomputation
    ctl = clean["devices"]["control"]
    u = met.get("unit") if isinstance(met.get("unit"), dict) else {}
    p = ctl["params"]
    n0 = 0.5 * (1.0e16 + math.sqrt(1.0e32 + 4 * p["n_i"] ** 2))
    sigma = p["ElectronCharge"] * (p["mu_n"] * n0 + p["mu_p"] * p["n_i"] ** 2 / n0)
    i_l, i_r = ctl["currents"][0]["I_l"], ctl["currents"][0]["I_r"]
    ratio = i_l / (sigma * 1.0e-3 / 2.0e-4)
    established = (math.isfinite(ratio) and abs(ratio - 1.0) <= TOL["unit_control"] and i_l > 0 > i_r and abs(i_l + i_r) <= 1e-6 * abs(i_l)
                   and ctl["error"] is None and ctl["converged"] is True)
    I.need(close(u.get("control_ratio"), ratio), f"unit.control_ratio {u.get('control_ratio')!r} != recomputed {ratio!r}")
    I.need(same(u.get("control_I_l"), i_l) and same(u.get("control_I_r"), i_r), "unit control currents != raw control record")
    I.need(type(u.get("established_by_control")) is bool and u["established_by_control"] == established, "unit.established_by_control contradicts the recomputation")
    I.need("metadata_unit_1d" in u and same(u.get("metadata_unit_1d"), ctl["metadata"].get("current_unit")), "unit.metadata_unit_1d != control metadata")
    I.need(same(u.get("metadata_dimension_1d"), ctl["metadata"].get("device_dimension")), "unit.metadata_dimension_1d != control metadata")
    I.need(isinstance(u.get("formatted_1d"), str), "unit.formatted_1d missing")
    I.need(close(u.get("sigma_S_per_cm"), sigma) and close(u.get("theory_sigma_V_over_L"), sigma * 1.0e-3 / 2.0e-4), "unit sigma copies != recomputation")
    I.need(same(u.get("metadata_has_2D_note"), ctl["has_current_convention_note"]), "unit.metadata_has_2D_note != control record")
    I.need(is_count(u.get("e6j_checks")) and is_count(u.get("e6j_failed_checks")), "E6J check counts missing")
    if e6j is not None:
        I.need(same(u.get("e6j_checks"), len(e6j["checks"])) and same(u.get("e6j_failed_checks"), sum(1 for c in e6j["checks"] if c["pass"] is not True)),
               "E6J counts != the preserved E6J JSON")
    clean.update({"met": met, "unit_recomputed": {"ratio": ratio, "established": established, "sigma": sigma, "I_l": i_l, "I_r": i_r}})
    return I, clean


def _chk(name, value, limit):
    return {"name": name, "value": value, "limit": limit, "pass": is_num(value) and value <= limit}


def _rel(a, b):
    return abs(a - b) / abs(b) if is_num(a) and is_num(b) and b != 0 else float("nan")


def judge(out, npz, e6j=None):
    I, c = validate(out, npz, e6j)
    res = {"EVIDENCE_INTEGRITY": {"verdict": "PASS" if not I.problems else "EVIDENCE_INTEGRITY_FAIL", "problems": I.problems}}
    if I.problems:
        for k in CATEGORIES:
            res[k] = {"verdict": "EVIDENCE_INTEGRITY_FAIL", "checks": []}
        return res
    met, devs, u = c["met"], c["devices"], c["met"]["unit"]

    def cat(checks):
        return {"verdict": "PASS" if checks and all(x["pass"] for x in checks) else "FAIL", "checks": checks}
    ctl = devs["control"]
    a = [{"name": "1D control metadata: current_unit None, dimension 1, no 2D note", "pass": ctl["metadata"]["current_unit"] is None and ctl["metadata"]["device_dimension"] == 1
          and ctl["has_current_convention_note"] is False},
         {"name": "1D value is displayed as 'unit not established'", "pass": "unit not established" in u["formatted_1d"]},
         {"name": "E6J GUI evidence: 17 checks, 0 failed", "pass": u["e6j_checks"] == 17 and u["e6j_failed_checks"] == 0}]
    res[CATEGORIES[0]] = cat(a)
    b = []
    for name in REQUIRED_DEVICES:
        d = devs[name]
        exp = ([1.0e16], [0.0]) if name == "control" else ([0.0, 1.0e17], [0.0, 1.0e17])
        b.append({"name": f"{name}: production sweep once, solves == 2 + #V, dimension 1, planned doping written, no error",
                  "pass": d["production_calls"] == 1 and d["solves"] == d["expected_solves"] and d["dimension"] == 1 and d["metadata"]["device_dimension"] == 1
                  and d["writes_ok"] is True and d["donors"] == exp[0] and d["acceptors"] == exp[1] and d["error"] is None})
    res[CATEGORIES[1]] = cat(b)
    if not c["unit_recomputed"]["established"]:
        for k in CATEGORIES[2:]:
            res[k] = {"verdict": "BLOCKED_UNIT_NOT_ESTABLISHED", "checks": []}
        return res
    J, E, W = met["J"], met["Emax"], met["WE"]
    cc = [{"name": f"{n}: converged, finite currents", "pass": devs[n]["converged"] is True and devs[n]["error"] is None} for n in REQUIRED_DEVICES]
    cc += [_chk("J(0.6 V) L1 vs L2", _rel(J["L1"]["0.6"], J["L2"]["0.6"]), TOL["mesh_J_0.6"]), _chk("J(-1.0 V) L1 vs L2", _rel(J["L1"]["-1.0"], J["L2"]["-1.0"]), TOL["mesh_J_-1.0"]),
           _chk("E_max(-1.0 V) L1 vs L2", _rel(E["L1"]["-1.0"], E["L2"]["-1.0"]), TOL["mesh_E_max"])]
    res[CATEGORIES[2]] = cat(cc)
    dd = []
    for k in E_KEYS:
        dd += [_chk(f"E_max({k} V) vs depletion approximation", _rel(E["L2"][k], met["ref_E"][k]["E_max"]), TOL["E_max_rel"]),
               _chk(f"W_E({k} V) vs depletion width (NOT independent of E_max: W_E = 2 V_drop / E_max)", _rel(W["L2"][k], met["ref_E"][k]["W"]), TOL["W_rel"])]
    res[CATEGORIES[3]] = cat(dd)
    ee = []
    for k in JUDGED_J:
        dev, ref = J["L2"][k], met["ref"][k]["J_model"]
        ee += [{"name": f"J({k} V) sign equals the reference sign", "pass": dev * ref > 0}, _chk(f"J({k} V) vs J_diff + J_SRH", _rel(dev, ref), TOL["J_model_rel"])]
    res[CATEGORIES[4]] = cat(ee)
    mi = met["minority"]
    res[CATEGORIES[5]] = cat([_chk(f"hole excess at s = {s} um", _rel(d_, r_), TOL["minority_rel"]) for s, d_, r_ in zip(S_UM, mi["dev"], mi["ref"])])
    return res
