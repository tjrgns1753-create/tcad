#!/usr/bin/env python3
"""E6M judge / metrics on SYNTHETIC 2D evidence lifted from the preserved E6K 1D data (y-invariant copy): the ideal case passes every category, and the
2D-structure and unit-conversion counterexamples are caught. Pure Python + numpy; no engine import; the E6L 279-deletion suite is not duplicated here."""
import copy
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts"))
import e6m_metrics as M  # noqa: E402
import judge_e6m as J  # noqa: E402

E6K = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
E6K_JSON = json.load(open(E6K / "pn_1d_diagnostic.json"))
E6K_NPZ = np.load(E6K / "states.npz")
E6J = json.load(open(ROOT / "docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json"))


class Arr(dict):
    @property
    def files(self):
        return list(self.keys())


def synth():
    raw, arr = {"plan_sha256": "0" * 64, "H_um": 0.1, "levels": {}}, Arr()
    for lv in M.LEVELS:
        x1 = M.e6k_snapshot(E6K_NPZ, lv, "rev", 0.0)["x"]
        pts, tris = M.build_mesh(x1)
        arr[f"{lv}__points_um"], arr[f"{lv}__triangles"] = pts, tris
        x, y = pts[:, 0] * 1.0e-4, pts[:, 1] * 1.0e-4
        nx = len(x1)
        p2 = np.stack([x, y], axis=1)
        a, b, c = p2[tris[:, 0]], p2[tris[:, 1]], p2[tris[:, 2]]
        area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
        nv = np.zeros(len(x))
        for k in range(3):
            np.add.at(nv, tris[:, k], area / 3.0)
        edges = [(j * nx + i, j * nx + i + 1) for j in range(3) for i in range(nx - 1)] + [(j * nx + i, (j + 1) * nx + i) for j in range(2) for i in range(nx)] \
            + [(j * nx + i, (j + 1) * nx + i + 1) for j in range(2) for i in range(nx - 1)]
        e = np.array(edges)
        length = np.hypot(x[e[:, 1]] - x[e[:, 0]], y[e[:, 1]] - y[e[:, 0]])
        devices = {}
        for d in M.DIRECTIONS:
            geo = {"x": x, "y": y, "NodeVolume": nv, "Donors": M.N_DOP * (x >= 0), "Acceptors": M.N_DOP * (x <= 0), "NetDoping": M.N_DOP * (x >= 0) - M.N_DOP * (x <= 0),
                   "edge_x0": x[e[:, 0]], "edge_x1": x[e[:, 1]], "edge_y0": y[e[:, 0]], "edge_y1": y[e[:, 1]], "EdgeLength": length, "element_nodes": tris}
            for k, v in geo.items():
                arr[M.akey(lv, d, k)] = v
            for vb in M.SNAP_BIASES[d]:
                s1 = M.e6k_snapshot(E6K_NPZ, lv, d, vb)
                for name in ("Potential", "Electrons", "Holes"):
                    arr[M.akey(lv, d, name, vb)] = np.tile(s1[name], 3)
                pot = arr[M.akey(lv, d, "Potential", vb)]
                arr[M.akey(lv, d, "ElectricField", vb)] = (pot[e[:, 0]] - pot[e[:, 1]]) / length
            one = E6K_JSON["devices"][f"{lv}_{d}"]
            devices[d] = {"voltages": list(M.VOLTAGES[d]), "currents": [{"V": c1["V"], "I_min": c1["I_l"] * M.H_CM, "I_max": c1["I_r"] * M.H_CM} for c1 in one["currents"]],
                          "solves": 2 + len(M.VOLTAGES[d]), "expected_solves": 2 + len(M.VOLTAGES[d]), "error": None, "converged": True,
                          "metadata": {"current_unit": "A/cm", "current_normalization": "per_out_of_plane_depth", "device_dimension": 2}, "params": dict(one["params"]),
                          "canonical_audit": {"canonical_checked": len(x), "canonical_unresolved": 0, "canonical_mismatch": 0}}
        raw["levels"][lv] = {
            "geometry_import": {"regions": ["Si"], "conformity_pass": True, "pre_solve_geometry_ok": True, "area_gate": {"pass": True, "A": 4e-8, "S": 4e-8},
                                "contacts": {"Si_xmin": {"n_nodes": 3, "x_cm": [-0.002, -0.002], "y_cm": [-M.H_CM, 0.0]}, "Si_xmax": {"n_nodes": 3, "x_cm": [0.002, 0.002], "y_cm": [-M.H_CM, 0.0]}}},
            "gate": {"raised": True, "resolution": "UNSUPPORTED_BY_MODEL", "reason_code": J.GATE_REASON, "doping_writes": 0, "solves": 0},
            "audit_doping": {"canonical_checked": len(x), "canonical_unresolved": 0, "canonical_mismatch": 0}, "devices": devices}
    raw["summary"] = M.compute(raw, arr, E6K_JSON, E6K_NPZ)
    return raw, arr


RAW, ARR = synth()


def verdicts(raw, arr, e6k_json=E6K_JSON):
    return {k: v["verdict"] for k, v in J.judge(raw, arr, e6k_json, E6K_NPZ, E6J, expected_plan_sha256="0" * 64).items() if isinstance(v, dict) and "verdict" in v}


def case(mutate, recompute, expect, label):
    raw, arr = copy.deepcopy(RAW), Arr({k: v.copy() for k, v in ARR.items()})
    mutate(raw, arr)
    if recompute:
        raw["summary"] = M.compute(raw, arr, E6K_JSON, E6K_NPZ)
    v = verdicts(raw, arr)
    for k, want in expect.items():
        assert v[k] == want, (label, k, v[k], want, v)
    return v


def update_field(arr, level, direction, bias):
    x, y = arr[M.akey(level, direction, "x")], arr[M.akey(level, direction, "y")]
    index = {p: i for i, p in enumerate(zip(x, y))}
    i0 = [index[p] for p in zip(arr[M.akey(level, direction, "edge_x0")], arr[M.akey(level, direction, "edge_y0")])]
    i1 = [index[p] for p in zip(arr[M.akey(level, direction, "edge_x1")], arr[M.akey(level, direction, "edge_y1")])]
    v = arr[M.akey(level, direction, "Potential", bias)]
    arr[M.akey(level, direction, "ElectricField", bias)] = (v[i0] - v[i1]) / arr[M.akey(level, direction, "EdgeLength")]


def hardened_cases():
    FAIL = "EVIDENCE_INTEGRITY_FAIL"
    gate = J.CATEGORIES[1]
    for value in ("f" * 64, "xyz", None):
        case(lambda r, a, value=value: r.__setitem__("plan_sha256", value), False, {"EVIDENCE_INTEGRITY": FAIL}, "PLAN mismatch")
    case(lambda r, a: r.pop("plan_sha256"), False, {"EVIDENCE_INTEGRITY": FAIL}, "PLAN missing")
    for d in M.DIRECTIONS:
        for field, value in (("canonical_unresolved", 1), ("canonical_checked", 0), ("canonical_checked", 1), ("canonical_mismatch", 1)):
            case(lambda r, a, d=d, field=field, value=value: r["levels"]["L2"]["devices"][d]["canonical_audit"].__setitem__(field, value),
                 True, {gate: "FAIL", J.CATEGORIES[5]: "BLOCKED_GATE_OR_AUDIT_DOPING"}, f"{d}: canonical {field}")
        for recompute in (False, True):
            for name, mutation in (
                ("NodeVolume zero", lambda a: a.__setitem__(M.akey("L2", d, "NodeVolume"), np.zeros_like(a[M.akey("L2", d, "NodeVolume")]))),
                ("NodeVolume short", lambda a: a.__setitem__(M.akey("L2", d, "NodeVolume"), a[M.akey("L2", d, "NodeVolume")][:-1])),
                ("NodeVolume NaN", lambda a: a[M.akey("L2", d, "NodeVolume")].__setitem__(0, np.nan)),
                ("NodeVolume negative", lambda a: a[M.akey("L2", d, "NodeVolume")].__setitem__(0, -1.0)),
                ("all doping zero", lambda a: [a.__setitem__(M.akey("L2", d, k), np.zeros_like(a[M.akey("L2", d, k)])) for k in ("Donors", "Acceptors", "NetDoping")]),
                ("one donor edited", lambda a: a[M.akey("L2", d, "Donors")].__setitem__(0, 1.0)),
                ("net identity broken", lambda a: a[M.akey("L2", d, "NetDoping")].__setitem__(0, 0.0)),
                ("coordinate edited", lambda a: a[M.akey("L2", d, "y")].__setitem__(0, 1.0)),
                ("edge length edited", lambda a: a[M.akey("L2", d, "EdgeLength")].__setitem__(0, 1.0)),
                ("field edited", lambda a: a[M.akey("L2", d, "ElectricField", 0.0)].__setitem__(0, 1.0)),
                ("element index out of range", lambda a: a[M.akey("L2", d, "element_nodes")].__setitem__((0, 0), 999999)),
                ("element index float", lambda a: a.__setitem__(M.akey("L2", d, "element_nodes"), a[M.akey("L2", d, "element_nodes")].astype(float))),
            ):
                # Some malformed shapes make compute fail before a summary can be refreshed.
                # Keep its old summary in that case; the raw-array contract must still reject it.
                def mutate(r, a, mutation=mutation):
                    mutation(a)
                    if recompute:
                        try:
                            r["summary"] = M.compute(r, a, E6K_JSON, E6K_NPZ)
                        except (ValueError, IndexError):
                            pass
                case(mutate, False, {"EVIDENCE_INTEGRITY": FAIL}, f"{d}: {name}, refreshed={recompute}")
    # Missing historical reverse records are not silently promoted to PASS.
    case(lambda r, a: [r["levels"][lv]["devices"]["rev"].pop("canonical_audit") for lv in M.LEVELS], False,
         {"EVIDENCE_INTEGRITY": "PASS", gate: "NOT_EVALUATED"}, "reverse canonical audit not recorded")
    # Both functions below are the actual guarded runner callbacks, not a separate test-only gate.
    good = dict(canonical_checked=3, canonical_unresolved=0, canonical_mismatch=0)
    for patch in ({"canonical_unresolved": 1}, {"canonical_checked": 0}, {"canonical_checked": 2}, {"canonical_mismatch": 1}):
        calls = {"writes": 0, "sweeps": 0, "solves": 0}
        def writer():
            calls["writes"] += 1
        def sweep():
            calls["sweeps"] += 1
            calls["solves"] += 1
        try:
            M.guarded_audit({**good, **patch}, 3, writer, sweep)
        except ValueError as exc:
            assert "CANONICAL_AUDIT_BLOCKED" in str(exc)
        else:
            raise AssertionError("invalid canonical evidence ran callbacks")
        assert calls == {"writes": 0, "sweeps": 0, "solves": 0}, calls
    calls = []
    assert M.guarded_audit(good, 3, lambda: calls.append("write"), lambda: calls.append("sweep")) is None
    assert calls == ["write", "sweep"]
    # Canonical net None/NaN/False must block even if donor and acceptor look valid.
    from types import SimpleNamespace
    for bad in (None, float("nan"), False):
        state = SimpleNamespace(net_doping_at=lambda x, y, bad=bad: SimpleNamespace(
            donor_concentration=M.N_DOP, acceptor_concentration=0.0, net_doping=bad, physics_status=None))
        rec = M.canonical_checks(state, np.array([1.0]), np.array([0.0]), 1.0)
        assert rec["canonical_unresolved"] == 1
    print("E6M hardened cases: both directions, PLAN, arrays, unknown-state callback traps PASS")


def main():
    v = verdicts(RAW, ARR)
    assert v["EVIDENCE_INTEGRITY"] == "PASS" and all(v[k] == "PASS" for k in J.CATEGORIES), v
    FAIL = "EVIDENCE_INTEGRITY_FAIL"
    G = {k.split("_")[0]: k for k in J.CATEGORIES}
    # completeness: mesh / device / bias / array removed
    case(lambda r, a: r["levels"].pop("L1"), False, {"EVIDENCE_INTEGRITY": FAIL, G["G6"]: FAIL}, "level removed")
    case(lambda r, a: r["levels"]["L2"]["devices"].pop("rev"), False, {"EVIDENCE_INTEGRITY": FAIL}, "device removed")
    case(lambda r, a: r["levels"]["L0"]["devices"]["fwd"]["currents"].pop(), False, {"EVIDENCE_INTEGRITY": FAIL}, "bias removed")
    case(lambda r, a: a.pop(M.akey("L2", "fwd", "Holes", 0.6)), False, {"EVIDENCE_INTEGRITY": FAIL}, "snapshot array removed")
    case(lambda r, a: a.pop(M.akey("L0", "rev", "edge_y1")), False, {"EVIDENCE_INTEGRITY": FAIL}, "edge end-point array removed")
    # number types
    for bad in ("0.1", True, None, float("nan"), float("inf"), 0.2):
        case(lambda r, a, b=bad: r.__setitem__("H_um", b), False, {"EVIDENCE_INTEGRITY": FAIL}, f"H_um = {bad!r}")
    for bad in ("1e-9", True, None, float("nan")):
        case(lambda r, a, b=bad: r["levels"]["L1"]["devices"]["fwd"]["currents"][4].__setitem__("I_min", b), False, {"EVIDENCE_INTEGRITY": FAIL}, f"I_min = {bad!r}")
        case(lambda r, a, b=bad: r["levels"]["L1"]["devices"]["rev"]["params"].__setitem__("mu_n", b), False, {"EVIDENCE_INTEGRITY": FAIL}, f"param = {bad!r}")
    case(lambda r, a: r["levels"]["L0"]["devices"]["fwd"].__setitem__("solves", True), False, {"EVIDENCE_INTEGRITY": FAIL}, "bool solve count")
    # raw vs summary
    case(lambda r, a: r["summary"]["levels"]["L2"]["currents"][M.vkey(0.6)].__setitem__("rel_diff", 0.5), False, {"EVIDENCE_INTEGRITY": FAIL}, "summary edited")
    case(lambda r, a: r["levels"]["L2"]["devices"]["fwd"]["currents"][5].__setitem__("I_min", 1.3e-6), False, {"EVIDENCE_INTEGRITY": FAIL}, "raw current edited, summary stale")
    case(lambda r, a: a.__setitem__(M.akey("L2", "rev", "Potential", -1.0), a[M.akey("L2", "rev", "Potential", -1.0)] + 1e-3), False, {"EVIDENCE_INTEGRITY": FAIL}, "array edited, summary stale")
    case(lambda r, a: r.pop("summary"), False, {"EVIDENCE_INTEGRITY": FAIL}, "summary missing")
    # unit conversion and unit basis
    def wrong_h(r, a):
        for lv in M.LEVELS:
            for d in M.DIRECTIONS:
                for c in r["levels"][lv]["devices"][d]["currents"]:
                    c["I_min"], c["I_max"] = c["I_min"] * 2, c["I_max"] * 2      # as if H were 0.2 um
    case(wrong_h, True, {G["G6"]: "FAIL", "EVIDENCE_INTEGRITY": "PASS"}, "current scaled as with a different H")
    for md in ({"current_unit": None}, {"current_unit": "A"}, {"current_normalization": None}, {"device_dimension": 1}, {"device_dimension": True}):
        case(lambda r, a, m=md: r["levels"]["L0"]["devices"]["fwd"]["metadata"].update(m), True, {G["G3"]: "FAIL", G["G6"]: "BLOCKED_UNIT_NOT_ESTABLISHED", G["G9"]: "BLOCKED_UNIT_NOT_ESTABLISHED"}, f"unit {md}")
    bad_1d = copy.deepcopy(E6K_JSON)
    bad_1d["devices"]["control"]["currents"][0]["I_l"] = 3.3
    raw, arr = copy.deepcopy(RAW), ARR
    assert verdicts(raw, arr, bad_1d)["EVIDENCE_INTEGRITY"] == FAIL, "tampered 1D reference must not be usable"
    # geometry / contacts / gate
    case(lambda r, a: r["levels"]["L1"]["geometry_import"]["contacts"]["Si_xmax"].__setitem__("n_nodes", 2), True, {G["G1"]: "FAIL", G["G4"]: "BLOCKED_GEOMETRY", G["G6"]: "BLOCKED_GEOMETRY"}, "contact not full height")
    case(lambda r, a: r["levels"]["L1"]["geometry_import"]["contacts"]["Si_xmin"].__setitem__("y_cm", [-M.H_CM / 2, 0.0]), True, {G["G1"]: "FAIL"}, "contact covers half the height")
    case(lambda r, a: r["levels"]["L0"]["geometry_import"]["area_gate"].__setitem__("pass", False), True, {G["G1"]: "FAIL", G["G8"]: "BLOCKED_GEOMETRY"}, "area gate failed")
    case(lambda r, a: r["levels"]["L0"]["geometry_import"].__setitem__("regions", ["Si", "SiO2"]), True, {G["G1"]: "FAIL"}, "extra region")

    def obtuse(r, a):
        p = a["L0__points_um"]
        p[1, 1] += 0.2                      # lift one bottom node above the top: obtuse / area change
    case(obtuse, True, {"EVIDENCE_INTEGRITY": FAIL}, "distorted triangle inconsistent with imported coordinates")
    case(lambda r, a: r["levels"]["L2"]["gate"].__setitem__("raised", False), True, {G["G2"]: "FAIL", G["G6"]: "BLOCKED_GATE_OR_AUDIT_DOPING"}, "gate did not refuse")
    case(lambda r, a: r["levels"]["L2"]["gate"].__setitem__("reason_code", "COMPENSATED_TRANSPORT_MODEL_MISSING"), True, {G["G2"]: "FAIL"}, "other gate reason")
    case(lambda r, a: r["levels"]["L2"]["gate"].__setitem__("doping_writes", 3), True, {G["G2"]: "FAIL"}, "gate wrote doping")
    case(lambda r, a: r["levels"]["L2"]["devices"]["fwd"]["canonical_audit"].__setitem__("canonical_mismatch", 1), True, {G["G2"]: "FAIL"}, "audit doping contradicts canonical")
    case(lambda r, a: a.__setitem__(M.akey("L1", "fwd", "Donors"), a[M.akey("L1", "fwd", "Donors")] * 0 + M.N_DOP), True, {"EVIDENCE_INTEGRITY": FAIL}, "step convention broken")
    # physics-shaped deviations
    def y_var(r, a):
        k = M.akey("L1", "fwd", "Potential", 0.6)
        v = a[k].copy()
        v[: len(v) // 3] += 5e-5           # the bottom y line differs by 50 uV
        a[k] = v
        update_field(a, "L1", "fwd", 0.6)  # a physically shaped deviation must keep the field definition consistent
    case(y_var, True, {G["G5"]: "FAIL", "EVIDENCE_INTEGRITY": "PASS"}, "y variation")

    def shift_all(r, a):
        k = M.akey("L2", "rev", "Potential", -1.0)
        a[k] = a[k] + 1e-3                 # y-invariant but 1 mV away from 1D
    case(shift_all, True, {G["G7"]: "FAIL", G["G5"]: "PASS"}, "profile differs from 1D")

    def field_flip(r, a):
        k = M.akey("L0", "rev", "ElectricField", 0.0)
        a[k] = a[k] * 1.05
    case(field_flip, True, {"EVIDENCE_INTEGRITY": FAIL}, "junction field contradicts Potential")

    def kcl(r, a):
        r["levels"]["L0"]["devices"]["rev"]["currents"][3]["I_max"] *= 0.99
    case(kcl, True, {G["G4"]: "FAIL"}, "terminal currents do not balance")
    case(lambda r, a: r["levels"]["L1"]["devices"]["fwd"].__setitem__("solves", 7), True, {G["G4"]: "FAIL"}, "missing solve")
    case(lambda r, a: r["levels"]["L1"]["devices"]["fwd"]["params"].__setitem__("taun", 1e-5), True, {G["G4"]: "FAIL"}, "physical parameter differs from E6K")
    hardened_cases()
    assert "PN_PHYSICS_VALIDATED" not in json.dumps(J.judge(RAW, ARR, E6K_JSON, E6K_NPZ, E6J, expected_plan_sha256="0" * 64), default=str)
    print("E6M JUDGE / METRICS SYNTHETIC CHECKS PASSED")


if __name__ == "__main__":
    main()
