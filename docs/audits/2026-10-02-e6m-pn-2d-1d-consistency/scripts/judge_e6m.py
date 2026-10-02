"""E6M judge (pure Python + numpy; no DEVSIM / ViennaPS import). Criteria: ../PLAN.md section 7. Reuses the E6L evidence principles:
required meshes / devices / biases / arrays must exist, numbers must be finite int/float (no bool, numeric string, None, NaN, inf), the stored summary must equal the summary
recomputed from the raw JSON and the stored arrays, and the units must be established before any current comparison. Separate verdicts only; never a combined PASS."""
import math
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "2026-10-01-e6l-judge-integrity-equilibrium" / "scripts"))
import e6m_metrics as M  # noqa: E402
import judge_e6l as E6L  # noqa: E402  (strict validation of the preserved 1D evidence; read-only)

VERSION = "e6m-judge-2"
PINNED_PLAN_SHA256 = "5aeb9dc28bf79f82404d728f9507c6a8208c531cc9bff32829cbf46e58e5410f"
GATE_REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"
LIM = {"area_rel": 1e-12, "x_lines_rel": 1e-12, "kcl_rel": 1e-3, "psi_y_spread_V": 1e-5, "carrier_y_spread_rel": 1e-3, "J_fwd_rel": 0.01, "J_rev_rel": 0.02,
       "psi_vs_1d_in_Vt": 0.01, "carrier_vs_1d_rel": 0.01, "E_junction_rel": 0.02, "mesh_J_0.6": 0.01, "mesh_J_-1.0": 0.02, "mesh_E": 0.02}
CATEGORIES = ("G1_GEOMETRY_AND_IMPORT", "G2_PRODUCTION_GATE_HELD_AND_AUDIT_DOPING", "G3_UNIT", "G4_CONVERGENCE_AND_CONSERVATION", "G5_Y_INVARIANCE", "G6_CURRENT_2D_VS_1D",
              "G7_PROFILE_2D_VS_1D", "G8_JUNCTION_FIELD_2D_VS_1D", "G9_MESH_SENSITIVITY_2D")
PARAMS = ("ElectronCharge", "n_i", "T", "mu_n", "mu_p", "taun", "taup", "Permittivity")
REF_OF = {"ElectronCharge": "q", "n_i": "n_i", "T": "T", "mu_n": "mu_n", "mu_p": "mu_p", "taun": "taun", "taup": "taup", "Permittivity": "eps"}

is_num, is_count, same = E6L.is_num, E6L.is_count, E6L.same


def close(a, b, tol=1e-9):
    return is_num(a) and is_num(b) and abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def all_leaves_valid(o, path, problems):
    if isinstance(o, dict):
        for k, v in o.items():
            all_leaves_valid(v, path + (k,), problems)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            all_leaves_valid(v, path + (i,), problems)
    elif not (type(o) is bool or is_num(o)):
        problems.append(f"summary leaf {'/'.join(map(str, path))} is not a finite number / bool: {o!r}")


def deep_equal(a, b, path, problems):
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            problems.append(f"summary keys differ at {'/'.join(map(str, path))}")
            return
        for k in a:
            deep_equal(a[k], b[k], path + (k,), problems)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            problems.append(f"summary list length differs at {'/'.join(map(str, path))}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            deep_equal(x, y, path + (i,), problems)
    elif type(a) is bool or type(b) is bool:
        if not (type(a) is bool and type(b) is bool and a == b):
            problems.append(f"summary bool differs at {'/'.join(map(str, path))}")
    elif not close(a, b):
        problems.append(f"stored summary {a!r} != recomputed {b!r} at {'/'.join(map(str, path))}")


def validate(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
    problems = []

    def need(cond, msg):
        if not cond:
            problems.append(msg)
        return bool(cond)
    need(is_num(raw.get("H_um")) and raw["H_um"] == M.H_UM, "H_um missing or not the planned 0.1")
    if expected_plan_sha256 is None:
        expected_plan_sha256 = PINNED_PLAN_SHA256
        local_sha = hashlib.sha256((HERE.parent / "PLAN.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        need(local_sha == PINNED_PLAN_SHA256, "local PLAN differs from the pre-solve pinned PLAN")
    need(isinstance(expected_plan_sha256, str) and len(expected_plan_sha256) == 64
         and all(c in "0123456789abcdef" for c in expected_plan_sha256), "invalid expected PLAN hash")
    need(raw.get("plan_sha256") == expected_plan_sha256, "plan_sha256 differs from independently expected PLAN")
    lev = raw.get("levels")
    if not need(isinstance(lev, dict) and set(lev) == set(M.LEVELS), "levels must be exactly L0, L1, L2") or not need(npz is not None, "arrays (npz) missing"):
        return problems, None, None
    for lv in M.LEVELS:
        L = lev[lv]
        gi = L.get("geometry_import") if isinstance(L, dict) else None
        if need(isinstance(gi, dict), f"{lv}: geometry_import missing"):
            need(isinstance(gi.get("regions"), list) and all(isinstance(r, str) for r in gi["regions"]), f"{lv}: regions malformed")
            need(type(gi.get("conformity_pass")) is bool and type(gi.get("pre_solve_geometry_ok")) is bool, f"{lv}: geometry flags must be bool")
            ag = gi.get("area_gate")
            need(isinstance(ag, dict) and type(ag.get("pass")) is bool and is_num(ag.get("A")) and is_num(ag.get("S")), f"{lv}: area_gate record malformed")
            ct = gi.get("contacts")
            ok = isinstance(ct, dict) and set(ct) == {"Si_xmin", "Si_xmax"}
            if need(ok, f"{lv}: contacts must be exactly Si_xmin and Si_xmax"):
                for n, c in ct.items():
                    need(isinstance(c, dict) and is_count(c.get("n_nodes")) and all(isinstance(c.get(k), list) and len(c[k]) == 2 and all(is_num(t) for t in c[k]) for k in ("x_cm", "y_cm")),
                         f"{lv}: contact {n} record malformed")
        gt = L.get("gate") if isinstance(L, dict) else None
        need(isinstance(gt, dict) and type(gt.get("raised")) is bool and isinstance(gt.get("resolution"), str) and isinstance(gt.get("reason_code"), str)
             and is_count(gt.get("doping_writes")) and is_count(gt.get("solves")), f"{lv}: gate record malformed")
        ad = L.get("audit_doping") if isinstance(L, dict) else None
        need(isinstance(ad, dict) and all(is_count(ad.get(k)) for k in ("canonical_checked", "canonical_unresolved", "canonical_mismatch")), f"{lv}: audit_doping record malformed")
        devs = L.get("devices") if isinstance(L, dict) else None
        if not need(isinstance(devs, dict) and set(devs) == set(M.DIRECTIONS), f"{lv}: devices must be exactly fwd and rev"):
            continue
        for d in M.DIRECTIONS:
            dev, plan_v = devs[d], M.VOLTAGES[d]
            if not need(isinstance(dev, dict), f"{lv}_{d}: device record malformed"):
                continue
            need(isinstance(dev.get("voltages"), list) and len(dev["voltages"]) == len(plan_v) and all(is_num(a) and a == b for a, b in zip(dev["voltages"], plan_v)), f"{lv}_{d}: voltages differ from the plan")
            cur = dev.get("currents")
            need(isinstance(cur, list) and len(cur) == len(plan_v) and all(isinstance(c, dict) and is_num(c.get("V")) and c["V"] == v and is_num(c.get("I_min")) and is_num(c.get("I_max"))
                                                                           for c, v in zip(cur, plan_v)), f"{lv}_{d}: currents missing / malformed / not at the planned voltages")
            need(is_count(dev.get("solves")) and is_count(dev.get("expected_solves")), f"{lv}_{d}: solve counts malformed")
            need(type(dev.get("converged")) is bool and (dev.get("error") is None or isinstance(dev.get("error"), str)), f"{lv}_{d}: converged / error malformed")
            need(isinstance(dev.get("metadata"), dict) and isinstance(dev.get("params"), dict) and all(is_num(dev["params"].get(k)) for k in PARAMS), f"{lv}_{d}: metadata / params malformed")
            for a in M.GEOM_ARRAYS:
                need(M.akey(lv, d, a) in npz.files, f"array {M.akey(lv, d, a)} missing")
            for v in M.SNAP_BIASES[d]:
                for a in M.SNAP_ARRAYS:
                    need(M.akey(lv, d, a, v) in npz.files, f"array {M.akey(lv, d, a, v)} missing")
        for a in ("points_um", "triangles"):
            need(f"{lv}__{a}" in npz.files, f"array {lv}__{a} missing")
    if problems:
        return problems, None, None
    for lv in M.LEVELS:
        for d in M.DIRECTIONS:
            try:
                problems.extend(M.array_contract(npz, lv, d, LIM["area_rel"]))
            except (ValueError, TypeError, IndexError, KeyError) as exc:
                problems.append(f"{lv}_{d}: malformed array evidence: {exc!r}")
    if problems:
        return problems, None, None
    # the preserved 1D evidence must itself be intact, and its unit control must hold (recomputed, not trusted)
    i1, c1 = E6L.validate(e6k_json, e6k_npz, e6j)
    need(not i1.problems, f"preserved E6K evidence fails its own integrity check: {i1.problems[:2]}")
    if problems:
        return problems, None, None
    try:
        summary = M.compute(raw, npz, e6k_json, e6k_npz)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"summary cannot be recomputed from the raw evidence: {exc!r}")
        return problems, None, None
    all_leaves_valid(summary, (), problems)
    if need(isinstance(raw.get("summary"), dict), "stored summary missing"):
        deep_equal(raw["summary"], summary, (), problems)
    return problems, summary, c1


def _c(name, value, limit):
    return {"name": name, "value": value, "limit": limit, "pass": is_num(value) and value <= limit}


def _b(name, cond, value=None):
    return {"name": name, "value": value, "pass": bool(cond)}


def judge(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
    problems, S, c1 = validate(raw, npz, e6k_json, e6k_npz, e6j, expected_plan_sha256=expected_plan_sha256)
    res = {"judge_version": VERSION, "EVIDENCE_INTEGRITY": {"verdict": "PASS" if not problems else "EVIDENCE_INTEGRITY_FAIL", "problems": problems}}
    if problems:
        for k in CATEGORIES:
            res[k] = {"verdict": "EVIDENCE_INTEGRITY_FAIL", "checks": []}
        return res

    def cat(checks):
        return {"verdict": "PASS" if checks and all(x["pass"] for x in checks) else "FAIL", "checks": checks}
    rp = e6k_json["reference_parameters"]
    g1, g2, g3, g4, g5, g6, g7, g8 = [], [], [], [], [], [], [], []
    canonical_evidence, canonical_missing = {}, False
    for lv in M.LEVELS:
        L, s = raw["levels"][lv], S["levels"][lv]
        gi, g = L["geometry_import"], s["geometry"]
        g1 += [_c(f"{lv}: triangle area sum vs 40 um x H", g["area_rel_err"], LIM["area_rel"]), _b(f"{lv}: importer area / NodeVolume gate passed", gi["area_gate"]["pass"] is True),
               _b(f"{lv}: no obtuse / degenerate triangle", g["obtuse_triangles"] == 0 and g["degenerate_triangles"] == 0), _b(f"{lv}: exact conformity check passed", gi["conformity_pass"] is True),
               _b(f"{lv}: regions == [Si]", gi["regions"] == ["Si"], gi["regions"]), _b(f"{lv}: node grid complete with 3 y lines", g["grid_complete"] and g["n_y_lines"] == 3),
               _b(f"{lv}: geometry was checked before solving", gi["pre_solve_geometry_ok"] is True),
               _b(f"{lv}: x lines equal the 1D node count", g["x_lines_equal_1d_count"]), _c(f"{lv}: max |x_2D - x_1D| / L", g["x_lines_max_abs_diff_cm"] / M.L_CM, LIM["x_lines_rel"])]
        for name, xc in (("Si_xmin", -M.L_CM / 2), ("Si_xmax", M.L_CM / 2)):
            c = gi["contacts"][name]
            g1.append(_b(f"{lv}: {name} covers the full height (3 nodes, x = {xc:+.0e} cm, y in [-H, 0])",
                         c["n_nodes"] == 3 and all(abs(t - xc) <= 1e-12 * M.L_CM for t in c["x_cm"]) and abs(c["y_cm"][0] + M.H_CM) <= 1e-12 * M.H_CM and abs(c["y_cm"][1]) <= 1e-12 * M.H_CM, c))
        gt, ad = L["gate"], L["audit_doping"]
        g2 += [_b(f"{lv}: production apply_doping refused (UNSUPPORTED_BY_MODEL / {GATE_REASON}), 0 writes, 0 solves",
                  gt["raised"] is True and gt["resolution"] == "UNSUPPORTED_BY_MODEL" and gt["reason_code"] == GATE_REASON and gt["doping_writes"] == 0 and gt["solves"] == 0, gt),
               _b(f"{lv}: stored audit doping follows the step convention", s["doping_step_convention_ok"])]
        for d in M.DIRECTIONS:
            dev = L["devices"][d]
            # Legacy E6M recorded only the forward canonical query. Never fabricate a reverse record.
            record = dev.get("canonical_audit", ad if d == "fwd" else None)
            key = f"{lv}_{d}"
            if record is None:
                canonical_missing = True
                canonical_evidence[key] = "NOT_RECORDED"
            else:
                try:
                    M.require_canonical(record, int(len(npz[M.akey(lv, d, "x")])))
                except ValueError:
                    canonical_evidence[key] = "FAIL"
                    g2.append(_b(f"{key}: complete, resolved canonical audit", False, record))
                else:
                    canonical_evidence[key] = "RECORDED_VALID"
                    g2.append(_b(f"{key}: complete, resolved canonical audit", True, record))
            md = dev["metadata"]
            g3.append(_b(f"{lv}_{d}: 2D result unit A/cm, per_out_of_plane_depth, dimension 2", md.get("current_unit") == "A/cm" and md.get("current_normalization") == "per_out_of_plane_depth"
                         and type(md.get("device_dimension")) is int and md["device_dimension"] == 2, {k: md.get(k) for k in ("current_unit", "current_normalization", "device_dimension")}))
            g4 += [_b(f"{lv}_{d}: converged, no error, solves == 2 + #V", dev["converged"] is True and dev["error"] is None and dev["solves"] == dev["expected_solves"] == 2 + len(M.VOLTAGES[d]),
                      [dev["solves"], dev["expected_solves"], dev["error"]]),
                   _b(f"{lv}_{d}: physical parameters equal the E6K reference", all(same(dev["params"][k], rp[REF_OF[k]]) for k in PARAMS))]
            for v in M.VOLTAGES[d]:
                g4.append(_c(f"{lv} {M.vkey(v)} V: |I_min + I_max| / |I_min|", s["currents"][M.vkey(v)]["kcl_rel"], LIM["kcl_rel"]))
        for d, v in M.PROFILE_CASES:
            p = s["profiles"][M.vkey(v)]
            g5 += [_c(f"{lv} {M.vkey(v)} V: potential spread over y [V]", p["psi_y_spread_V"], LIM["psi_y_spread_V"]),
                   _c(f"{lv} {M.vkey(v)} V: electron spread over y", p["Electrons_y_spread_rel"], LIM["carrier_y_spread_rel"]),
                   _c(f"{lv} {M.vkey(v)} V: hole spread over y", p["Holes_y_spread_rel"], LIM["carrier_y_spread_rel"])]
            g7 += [_c(f"{lv} {M.vkey(v)} V: max |psi_2D - psi_1D| / V_t", p["psi_max_abs_diff_vs_1d_V"] / rp["Vt"], LIM["psi_vs_1d_in_Vt"]),
                   _c(f"{lv} {M.vkey(v)} V: electrons vs 1D", p["Electrons_max_rel_diff_vs_1d"], LIM["carrier_vs_1d_rel"]),
                   _c(f"{lv} {M.vkey(v)} V: holes vs 1D", p["Holes_max_rel_diff_vs_1d"], LIM["carrier_vs_1d_rel"])]
        for d, v in M.JUDGED_CURRENT:
            c = s["currents"][M.vkey(v)]
            g6 += [_b(f"{lv} {M.vkey(v)} V: sign equals 1D", c["same_sign"]), _c(f"{lv} {M.vkey(v)} V: |I_2D/H - I_1D| / |I_1D|", c["rel_diff"], LIM["J_fwd_rel"] if v > 0 else LIM["J_rev_rel"])]
        for d, v in M.FIELD_CASES:
            for side in ("left", "right"):
                f = s["junction_field"][M.vkey(v)][side]
                g8 += [_b(f"{lv} {M.vkey(v)} V {side}: 3 horizontal junction edges found", f["n_edges"] == 3, f["n_edges"]),
                       _c(f"{lv} {M.vkey(v)} V {side}: E_x 2D vs 1D same edge", f["max_rel_diff"], LIM["E_junction_rel"])]
    u = c1["unit_recomputed"]
    g3 += [_b("H: 0.1 um = 1e-5 cm", S["H_cm"] == M.H_UM * 1.0e-4 and raw["H_um"] == 0.1, S["H_cm"]),
           _b("1D basis: E6K resistor control recomputed from raw currents (ratio within 1e-6); production 1D metadata declares NO unit", u["established"] is True, u["ratio"])]
    ms = S["mesh_sensitivity"]
    g9 = [_c("J(0.6 V) L1 vs L2", ms["J_0.6_L1_vs_L2"], LIM["mesh_J_0.6"]), _c("J(-1.0 V) L1 vs L2", ms["J_-1.0_L1_vs_L2"], LIM["mesh_J_-1.0"]),
          _c("junction-edge E_x(-1.0 V) L1 vs L2", ms["E_junction_left_-1.0_L1_vs_L2"], LIM["mesh_E"])]
    for k, checks in zip(CATEGORIES, (g1, g2, g3, g4, g5, g6, g7, g8, g9)):
        res[k] = cat(checks)
    if canonical_missing and res[CATEGORIES[1]]["verdict"] == "PASS":
        res[CATEGORIES[1]]["verdict"] = "NOT_EVALUATED"
        res[CATEGORIES[1]]["reason"] = "reverse pre-solve canonical audit NOT_RECORDED; stored arrays were checked independently"
    res["canonical_evidence"] = canonical_evidence
    geom_ok, gate_ok, unit_ok = (res[CATEGORIES[i]]["verdict"] == "PASS" for i in range(3))
    for k in CATEGORIES[3:]:
        if not geom_ok:
            res[k] = {"verdict": "BLOCKED_GEOMETRY", "checks": []}
        elif not gate_ok:
            res[k] = {"verdict": "BLOCKED_GATE_OR_AUDIT_DOPING", "checks": []}
    if geom_ok and gate_ok and not unit_ok:
        for k in (CATEGORIES[5], CATEGORIES[8]):
            res[k] = {"verdict": "BLOCKED_UNIT_NOT_ESTABLISHED", "checks": []}
    res["diagnostics_not_judged"] = S["equilibrium_diagnostics_not_judged"]
    return res
