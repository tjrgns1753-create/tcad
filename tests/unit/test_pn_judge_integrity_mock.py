#!/usr/bin/env python3
"""E6L: the strict judge must reproduce the original A..F verdicts on the untouched E6K evidence and must never keep PASS when evidence is removed,
duplicated inconsistently, or replaced by non-numeric / non-finite values. Reads the committed E6K evidence read-only. Pure Python + numpy."""
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6l-judge-integrity-equilibrium/scripts"))
import judge_e6l as J  # noqa: E402

E6K = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
E6J = ROOT / "docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json"
BASE = json.load(open(E6K / "pn_1d_diagnostic.json"))
NPZ = np.load(E6K / "states.npz")
E6JD = json.load(open(E6J))
EXPECTED = {"EVIDENCE_INTEGRITY": "PASS", "A_CURRENT_UNIT_CONTRACT": "PASS", "B_PRODUCTION_PATH_EXECUTED": "PASS", "C_NUMERICAL_CONVERGENCE_AND_MESH_SENSITIVITY": "PASS",
            "D_ANALYTICAL_ELECTROSTATICS_COMPARISON": "FAIL", "E_APPROXIMATE_SRH_DIFFUSION_REFERENCE_COMPARISON": "PASS", "F_MINORITY_CARRIER_PROFILE_COMPARISON": "PASS"}


def verdicts(out, npz=NPZ):
    return {k: v["verdict"] for k, v in J.judge(out, npz, E6JD).items()}


def integrity_fail(mutate, label, npz=NPZ):
    out = copy.deepcopy(BASE)
    mutate(out)
    v = verdicts(out, npz)
    assert v["EVIDENCE_INTEGRITY"] == "EVIDENCE_INTEGRITY_FAIL" and all(v[k] == "EVIDENCE_INTEGRITY_FAIL" for k in J.CATEGORIES), (label, v)


def leaves(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, path + (i,))
    else:
        yield path


def set_path(o, path, value=None, delete=False):
    for k in path[:-1]:
        o = o[k]
    if delete:
        if isinstance(o, list):
            o.pop(path[-1])
        else:
            del o[path[-1]]
    else:
        o[path[-1]] = value


def main():
    assert verdicts(copy.deepcopy(BASE)) == EXPECTED, verdicts(copy.deepcopy(BASE))
    # each required device deleted, from the raw records and from the metrics copy
    for name in J.REQUIRED_DEVICES:
        integrity_fail(lambda o, n=name: o["devices"].pop(n), f"delete devices.{name}")
        integrity_fail(lambda o, n=name: o["metrics"]["devices"].pop(n), f"delete metrics.devices.{name}")
    # each required bias / level deleted
    for grp, keys in (("J", J.J_KEYS), ("Emax", J.E_KEYS), ("WE", J.E_KEYS)):
        for lv in J.LEVELS:
            integrity_fail(lambda o, g=grp, l=lv: o["metrics"][g].pop(l), f"delete {grp}.{lv}")
            for k in keys:
                integrity_fail(lambda o, g=grp, l=lv, k_=k: o["metrics"][g][l].pop(k_), f"delete {grp}.{lv}.{k}")
    integrity_fail(lambda o: o["devices"]["L1_fwd"]["currents"].pop(2), "delete a raw current point")
    integrity_fail(lambda o: o["devices"]["L2_rev"]["voltages"].pop(), "delete a planned voltage")
    # minority arrays shortened / extended and positions moved
    for k in ("s_um", "dev", "ref"):
        integrity_fail(lambda o, k_=k: o["metrics"]["minority"][k_].pop(), f"shorten minority.{k}")
        integrity_fail(lambda o, k_=k: o["metrics"]["minority"][k_].append(o["metrics"]["minority"][k_][-1]), f"extend minority.{k}")
    integrity_fail(lambda o: o["metrics"]["minority"].__setitem__("s_um", [3.0, 5.0, 7.0]), "move a minority position")
    integrity_fail(lambda o: o["metrics"]["minority"].__setitem__("s_um", [3, 5, 8, 10]), "add a minority position")
    # numeric strings, bool, None, NaN, inf in numeric evidence
    targets = [("metrics", "J", "L2", "0.6"), ("metrics", "Emax", "L2", "-1.0"), ("metrics", "WE", "L0", "0.0"), ("metrics", "minority", "dev", 1),
               ("metrics", "minority", "ref", 2), ("metrics", "unit", "control_ratio"), ("devices", "L0_rev", "currents", 1, "I_l"), ("devices", "control", "currents", 0, "I_r"),
               ("devices", "control", "params", "mu_n"), ("reference_parameters", "eps"), ("metrics", "ref", "0.5", "J_model"), ("metrics", "ref_E", "0.0", "E_max")]
    for path in targets:
        for bad in ("1.0", "0.116", True, False, None, float("nan"), float("inf"), -float("inf")):
            integrity_fail(lambda o, p=path, b=bad: set_path(o, p, b), f"{path} = {bad!r}")
    # counts: bool, negative, float
    for k in ("solves", "expected_solves", "production_calls", "dimension"):
        for bad in (True, -1, 8.0, "8"):
            integrity_fail(lambda o, k_=k, b=bad: (o["devices"]["L0_fwd"].__setitem__(k_, b), o["metrics"]["devices"]["L0_fwd"].__setitem__(k_, b)), f"count {k} = {bad!r}")
    # unit control: tampered ratio / raw currents while the stored True flag is kept
    integrity_fail(lambda o: o["metrics"]["unit"].__setitem__("control_ratio", float("nan")), "ratio NaN, flag True")
    integrity_fail(lambda o: o["metrics"]["unit"].__setitem__("control_ratio", 1.0000001), "ratio altered, flag True")
    integrity_fail(lambda o: o["devices"]["control"]["currents"][0].__setitem__("I_l", 3.3), "raw control current altered, flag True")

    def consistent_bad_control(o):      # raw current, metrics copy and ratio all changed consistently, flag left True
        o["devices"]["control"]["currents"][0]["I_l"] = 3.3
        o["metrics"]["unit"]["control_I_l"] = 3.3
        o["metrics"]["unit"]["control_ratio"] = 3.3 / o["metrics"]["unit"]["theory_sigma_V_over_L"]
    integrity_fail(consistent_bad_control, "consistent tamper, flag True contradicts the recomputation")

    def consistent_bad_control_flag_false(o):   # fully consistent but not established -> C..F blocked, never PASS
        consistent_bad_control(o)
        o["metrics"]["unit"]["established_by_control"] = False
    out = copy.deepcopy(BASE)
    consistent_bad_control_flag_false(out)
    v = verdicts(out)
    assert v["EVIDENCE_INTEGRITY"] == "PASS" and all(v[k] == "BLOCKED_UNIT_NOT_ESTABLISHED" for k in J.CATEGORIES[2:]), v
    integrity_fail(lambda o: o["devices"]["control"]["currents"][0].__setitem__("I_r", 3.2), "control contact sign wrong")
    # raw vs metrics vs table mismatch
    integrity_fail(lambda o: o["devices"]["L2_fwd"]["currents"][5].__setitem__("I_l", 0.12), "raw current differs from metrics")
    integrity_fail(lambda o: o["metrics"]["J"]["L1"].__setitem__("0.5", o["metrics"]["J"]["L1"]["0.5"] * 1.001), "metrics differ from raw")
    integrity_fail(lambda o: o["table"]["L0"]["-1.0"].__setitem__("I_l_raw", 1.0), "table differs from raw")
    integrity_fail(lambda o: o["metrics"]["devices"]["L2_rev"].__setitem__("solves", 7), "metrics.devices solves contradicts the record")
    integrity_fail(lambda o: o["metrics"]["devices"]["L2_rev"].__setitem__("converged", 1), "bool replaced by 1")
    integrity_fail(lambda o: o["metrics"]["Emax"]["L2"].__setitem__("0.0", 116584.6), "E_max replaced by the reference value")
    integrity_fail(lambda o: o["metrics"]["minority"]["dev"].__setitem__(0, o["metrics"]["minority"]["ref"][0]), "minority dev replaced by the reference")
    integrity_fail(lambda o: None, "states.npz absent", npz=None)
    # generic: deleting ANY leaf of metrics, of a device record's judged fields, of the result table or of the reference parameters must not keep the original verdicts
    paths = [p for p in leaves(BASE["metrics"])]
    paths = [("metrics",) + p for p in paths]
    paths += [("devices", n, k) for n in J.REQUIRED_DEVICES for k in ("voltages", "currents", "params", "donors", "acceptors", "metadata", "solves", "expected_solves",
                                                                      "production_calls", "dimension", "converged", "writes_ok", "error", "has_current_convention_note", "nodes")]
    paths += [("table", lv, k, "I_l_raw") for lv in J.LEVELS for k in J.J_KEYS] + [("reference_parameters", k) for k in J.REF_PARAM_KEYS]
    kept = []
    for p in paths:
        out = copy.deepcopy(BASE)
        set_path(out, p, delete=True)
        if verdicts(out) == EXPECTED:
            kept.append(p)
    allowed = set()
    assert set(kept) <= allowed, f"deleting these leaves keeps the original verdicts: {sorted(set(kept) - allowed)}"
    print(f"STRICT JUDGE INTEGRITY TESTS PASSED ({len(paths)} deletions; tolerated informational leaves: {sorted(set(kept))})")


if __name__ == "__main__":
    main()
