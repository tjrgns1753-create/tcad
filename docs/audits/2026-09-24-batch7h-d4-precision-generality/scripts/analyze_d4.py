"""Batch 7H-D4 fail-closed analyzer.

Two modes, one code path:
  --mode d3 : re-judge the committed D3 evidence (11 runs) with the D4 EVIDENCE_INTEGRITY layer on top of the
              unchanged D3 physics rules (analyze_d3.py imported READ-ONLY: pm, self_ok, equality, mirror_pair).
  --mode d4 : judge the D4 runs (P12 vs P4 on three non-obtuse default fixtures) per D4 PLAN.md.

EVIDENCE_INTEGRITY is a gate above every physics verdict. Missing metadata is never defaulted to True / 0:
every required field is read with req(), and an absent field is an integrity error. If integrity fails,
no physics verdict can be PASS (it is reported as BLOCKED_BY_EVIDENCE_INTEGRITY).
The D2/D3 physics tolerances are not changed: tau = 1e-5, zero-bias 1e-6, denominator 1e-6 (from analyze_d3).
"""
import argparse
import glob
import hashlib
import json
import os
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-d3-precision-pair-mirror", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-d1-pn-convergence", "scripts"))
import analyze_d3 as A3  # noqa: E402  (read-only: physics rules of D3, unchanged)
import meshes_d1 as md  # noqa: E402  (read-only: 1D J1 grid)

TAU, DEN = A3.TAU, A3.DEN
BIASED = A3.BIASED
CUTS = A3.CUTS
STEPS = A3.EXPECTED_STEPS                     # 12 recorded solve steps
POINTS = ("B0", "B0rev") + BIASED             # recorded states
REL_STOP = 1e-10                              # registered solver stopping rule (fixed_d2.json)
TOL_PARAM, TOL_PSI_APPLIED = A3.TOL_PARAM, A3.TOL_PSI
NODE_TOL_REL = 2e-10                          # D4 PLAN section 5: 2 x the per-node relative stopping update
FLAG_NAMES = ("extended_model", "extended_equation", "extended_solver")
TARGET = {"P0": (False, False, False), "P12": (True, True, False), "P4": (True, True, True)}
FIXD1 = "docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixtures_d1.json"
FIXD2 = "docs/audits/2026-09-23-batch7h-d2-current-precision/data/fixtures_d2.json"
SHA_D1 = "80d65d513ff9f923ff35cfe54cd937214b33cd47571797a005013e6e82d9f7f5"
SHA_D2 = "e2c018a62292c4f4f9e215a8aa525148c15a618bc50792c141318a6a81f3a6f2"
FIXTURES = {   # expected geometry identity (values copied from the D1/D2 fixture files' own quality blocks)
    "M2_h0.005": (SHA_D1, 4242, 8040, "158f59fed0823626fae406d2152306ca908f46e7c8a7118a4fb307443c58dd49",
                  "f2c579853b7b53a35d4bd9cc6e79aaab92ff07f7cead5527bf1897819eb74c79"),
    "M1_h0.005": (SHA_D1, 4242, 8040, "9e4b5bce717f6f37bbeb54ea93da060284a7434d759d157cf536549140a32d85",
                  "9de5267bb51d699955c58231aaf190aab2515445456d75a8d3d59db7a943b7fc"),
    "M1_h0.00125": (SHA_D2, 64962, 128160, "433cc08c391f13af584f1161073531aca76286c808ed3414bf550dff320c5a9d",
                    "8e360bd3164670dbcfc523642496faad509aade1920ec1a66b932318eabc0857"),
    "M2_h0.00125": (SHA_D2, 64962, 128160, "9540b881034269137b94ba6ff9f2f267efb4093c2cc524f5374fb0c8d08e52fc",
                    "cdb40feea37c6b96cd35e1d6ffefaa3fac468f4073f3e8a70798bd7fad1988a8"),
}
PLAN_SHA = {"d3": "eb6096a9ffc8a338a86dafee5f8f6fee88bf8bc93ac1eaea3fc2f8b62eee1071",
            "d4": "3a53e29b24a7d29aee198a57f8e06f604d243d73babf1b1926ec11fc6fb32912"}


class Missing(Exception):
    pass


def req(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            raise Missing("/".join(str(p) for p in path))
        cur = cur[k]
    return cur


def sha_lf(p):
    return hashlib.sha256(open(p, "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def x1d_sha(h):
    return hashlib.sha256(np.array(md.grid_1d(h, "J1"), dtype=float).tobytes()).hexdigest()


def expected_matrix(mode):
    m = {}
    if mode == "d3":
        for P in ("P0", "P12", "P4"):
            m[f"E1_M2_D0_h0.005_{P}"] = {"kind": "2d", "fam": "M2", "variant": "D0", "h": 0.005, "P": P, "mirror": False}
        for P in ("P4", "P0"):
            for side in ("orig", "mirror"):
                m[f"E2_1D_h0.005_{P}_{side}"] = {"kind": "1d", "h": 0.005, "P": P, "mirror": side == "mirror"}
                m[f"E2_M1_h0.005_{P}_{side}"] = {"kind": "2d", "fam": "M1", "variant": "D0", "h": 0.005, "P": P, "mirror": side == "mirror"}
    else:
        for fam, h in (("M1", 0.005), ("M1", 0.00125), ("M2", 0.00125)):
            for P in ("P12", "P4"):
                m[f"D4_{fam}_D0_h{h}_{P}"] = {"kind": "2d", "fam": fam, "variant": "D0", "h": h, "P": P, "mirror": False}
    for k, v in m.items():
        v["id"] = k
    return m


def check_run(rid, r, cfg, mode, errs):
    """Append integrity errors for one run. Never assumes a missing field."""
    e = lambda msg: errs.append(f"{rid}: {msg}")  # noqa: E731
    try:
        if "error" in r:
            e(f"run reported error: {r['error'][:120]}")
            return
        got = req(r, "cfg")
        for k, v in cfg.items():
            if got.get(k, "<absent>") != v:
                e(f"cfg.{k} = {got.get(k, '<absent>')!r}, expected {v!r}")
        fx = req(r, "fixture")
        if cfg["kind"] == "2d":
            key = f"{cfg['fam']}_h{cfg['h']}"
            fsha, nn, nt, csha, ksha = FIXTURES[key]
            checks = {"file_sha256_raw": fsha, "n_nodes": nn, "n_triangles": nt, "coordinates_sha256": csha,
                      "connectivity_sha256": ksha, "stored_coordinates_sha256": csha, "stored_connectivity_sha256": ksha,
                      "identical_to_stored": True}
            for k, v in checks.items():
                if req(fx, k) != v:
                    e(f"fixture.{k} = {req(fx, k)!r}, expected {v!r}")
        else:
            if req(fx, "n_nodes") != len(md.grid_1d(cfg["h"], "J1")) or req(fx, "x_um_sha256") != x1d_sha(cfg["h"]):
                e("1D grid identity mismatch")
        start = req(r, "flags_at_start")
        for n in FLAG_NAMES:
            if not (isinstance(req(start, n), str) and req(start, n).startswith("UNSET")):
                e(f"flag {n} was not unset at process start: {start.get(n)!r}")
        target = dict(zip(FLAG_NAMES, TARGET[cfg["P"]]))
        if req(r, "flags_set") != target:
            e(f"flags_set {r['flags_set']} != target {target}")
        if req(r, "flags_at_end") != target:
            e(f"flags_at_end {r['flags_at_end']} != target {target}")
        if req(r, "devices_left") != []:
            e("device left registered")
        if req(r, "devsim", "version") != "2.11.0":
            e("DEVSIM version != 2.11.0")
        steps = req(r, "steps")
        extra = set(steps) - set(STEPS)
        if extra:
            e(f"unexpected steps {sorted(extra)}")
        for s in STEPS:
            info = req(steps, s, "info")
            if not (req(info, "ok") is True and req(info, "converged") is True and req(info, "final_device_rel") < REL_STOP):
                e(f"step {s} not accepted (ok={info.get('ok')}, converged={info.get('converged')}, rel={info.get('final_device_rel')})")
        for pnt in POINTS:
            s = req(steps, pnt)
            for c in CUTS:
                req(s, "C2", c, "total")
                req(s, "C2", c, "n")
                req(s, "C2", c, "p")
            for side in ("left", "right"):
                req(s, "C0", side, "total")
                req(s, "C1", side, "total")
            req(s, "C3")
            rb = req(s, "readback")
            v = 0.0 if pnt.startswith("B0") else A3.VSET[pnt]
            if abs(req(rb, "p_bias_readback") - v) > TOL_PARAM or abs(req(rb, "n_bias_readback")) > TOL_PARAM:
                e(f"{pnt}: bias readback p={rb['p_bias_readback']} n={rb['n_bias_readback']} for v={v}")
            if not pnt.startswith("B0"):
                eq = req(steps, "B0rev" if v < 0 else "B0")
                va = A3.applied_v(s, eq)
                if abs(va - v) > TOL_PSI_APPLIED:
                    e(f"{pnt}: applied voltage from contact potentials {va} != {v}")
            if req(s, "positive_finite") is not True:
                e(f"{pnt}: carriers not positive/finite")
        g = req(r, "geometry")
        if not (req(g, "max_abs_dx_vs_expected_um") <= 1e-9 and req(g, "donors_all_on_expected_side") is True
                and req(g, "acceptors_all_on_expected_side") is True):
            e("geometry/doping-side check failed")
        if mode == "d4":
            ns = req(r, "node_state")
            for k in ("npz", "npz_sha256", "x_sha256", "y_sha256", "elements_sha256", "n_nodes"):
                req(ns, k)
    except Missing as m:
        e(f"missing required field {m}")


def integrity(mode, runs_dir, plan_dir, npz_dir):
    errs = []
    plan = {"sha256_lf": sha_lf(os.path.join(plan_dir, "PLAN.md")),
            "recorded": open(os.path.join(plan_dir, "PLAN.sha256"), encoding="utf-8").read().split()[0],
            "pinned": PLAN_SHA[mode]}
    if not (plan["sha256_lf"] == plan["recorded"] == plan["pinned"]):
        errs.append(f"PLAN hash mismatch: file {plan['sha256_lf']} recorded {plan['recorded']} pinned {plan['pinned']}")
    exp = expected_matrix(mode)
    files = {os.path.basename(p)[:-5]: p for p in glob.glob(os.path.join(runs_dir, "*.json"))}
    for k in sorted(set(exp) - set(files)):
        errs.append(f"missing run file {k}.json")
    for k in sorted(set(files) - set(exp)):
        errs.append(f"unexpected run file {k}.json")
    R = {}
    for k, cfg in exp.items():
        if k not in files:
            continue
        try:
            R[k] = json.load(open(files[k], encoding="utf-8"))
        except (OSError, ValueError) as ex:
            errs.append(f"{k}: unreadable ({ex})")
            continue
        check_run(k, R[k], cfg, mode, errs)
        if mode == "d4" and "node_state" in R[k]:
            p = os.path.join(npz_dir, R[k]["node_state"]["npz"])
            if not os.path.exists(p):
                errs.append(f"{k}: node-state archive missing")
            elif hashlib.sha256(open(p, "rb").read()).hexdigest() != R[k]["node_state"]["npz_sha256"]:
                errs.append(f"{k}: node-state archive hash mismatch")
    return errs, R, plan


def current_compare(r12, r4):
    """D3 equality() (contacts + five cut totals) plus per-species cut currents under the same tau / denominator rule."""
    base = A3.equality(r12, r4)
    rows, fails, und = list(base["rows"]), base["n_fail"], base["n_undecidable"]
    for b in BIASED:
        s12, s4 = r12["steps"][b], r4["steps"][b]
        scale = max(abs(s4["C2"][c]["total"]) for c in CUTS)
        for c in CUTS:
            for sp in ("n", "p"):
                a, ref = s12["C2"][c][sp], s4["C2"][c][sp]
                rel = abs(a - ref) / abs(ref) if ref != 0 else float("inf")
                st = "OK"
                if abs(ref) < DEN * scale:
                    st, und = "UNDECIDABLE", und + 1
                elif rel > TAU:
                    st, fails = "FAIL", fails + 1
                rows.append({"point": b, "quantity": f"cut{c}.{sp}", "P12": a, "P4": ref, "rel_diff": rel, "state": st})
    so12, so4 = A3.self_ok(r12)["status"], A3.self_ok(r4)["status"]
    if fails or so12 != "SELF_OK":
        v = "FAIL"
    elif so4 != "SELF_OK" or und:
        v = "INCONCLUSIVE"
    else:
        v = "PASS"
    return {"verdict": v, "P12_self": so12, "P4_self": so4, "n_fail": fails, "n_undecidable": und,
            "max_rel_diff": max((x["rel_diff"] for x in rows if x["state"] != "UNDECIDABLE"), default=None), "rows": rows}


def node_compare(r12, r4, npz_dir):
    z12 = np.load(os.path.join(npz_dir, r12["node_state"]["npz"]))
    z4 = np.load(os.path.join(npz_dir, r4["node_state"]["npz"]))
    order_same = (r12["node_state"]["x_sha256"] == r4["node_state"]["x_sha256"] and r12["node_state"]["y_sha256"] == r4["node_state"]["y_sha256"]
                  and r12["node_state"]["elements_sha256"] == r4["node_state"]["elements_sha256"]
                  and np.array_equal(z12["x"], z4["x"]) and np.array_equal(z12["y"], z4["y"]))
    if not order_same:
        return {"verdict": "INCONCLUSIVE", "reason": "node ordering / mesh identity not proven"}
    pts, bad, und = {}, False, False
    for pnt in POINTS:
        k = pnt.replace("+", "p").replace("-", "m").replace(".", "_")
        psi12, psi4 = z12[f"psi_{k}"], z4[f"psi_{k}"]
        n12, n4, p12, p4 = z12[f"n_{k}"], z4[f"n_{k}"], z12[f"p_{k}"], z4[f"p_{k}"]
        pos = all(np.all(np.isfinite(a)) and np.all(a > 0) for a in (n12, n4, p12, p4)) and np.all(np.isfinite(psi12)) and np.all(np.isfinite(psi4))
        tol_psi = NODE_TOL_REL * float(np.max(np.abs(psi4)))
        d = {"positive_finite": bool(pos), "max_abs_dpsi_V": float(np.max(np.abs(psi12 - psi4))), "tol_psi_V": tol_psi}
        if pos:
            d["max_abs_log_n"] = float(np.max(np.abs(np.log(n12 / n4))))
            d["max_abs_log_p"] = float(np.max(np.abs(np.log(p12 / p4))))
            d["ok"] = d["max_abs_dpsi_V"] <= tol_psi and d["max_abs_log_n"] <= NODE_TOL_REL and d["max_abs_log_p"] <= NODE_TOL_REL
            bad = bad or not d["ok"]
        else:
            und = True
        d["final_rel_update_P12_P4"] = [r12["steps"][pnt]["info"]["final_device_rel"], r4["steps"][pnt]["info"]["final_device_rel"]]
        pts[pnt] = d
    v = "DIFFERS" if bad else ("INCONCLUSIVE" if und else "MATCHES")
    return {"verdict": v, "tol_rel": NODE_TOL_REL, "points": pts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("d3", "d4"), required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan-dir", required=True)
    ap.add_argument("--npz-dir", default=None)
    a = ap.parse_args()
    npz_dir = a.npz_dir or a.runs
    errs, R, plan = integrity(a.mode, a.runs, a.plan_dir, npz_dir)
    ok = not errs
    out = {"schema": 1, "mode": a.mode, "plan": plan, "integrity_errors": errs,
           "EVIDENCE_INTEGRITY": "EVIDENCE_INTEGRITY_PASS" if ok else "EVIDENCE_INTEGRITY_FAIL"}
    block = "BLOCKED_BY_EVIDENCE_INTEGRITY"
    if a.mode == "d3":
        e1 = e2 = block
        if ok:
            eq = A3.equality(R["E1_M2_D0_h0.005_P12"], R["E1_M2_D0_h0.005_P4"])
            p4self = A3.self_ok(R["E1_M2_D0_h0.005_P4"])["status"]
            e1 = eq["verdict"] if p4self == "SELF_OK" else ("FAIL" if eq["verdict"] == "FAIL" else "INCONCLUSIVE")
            pairs = {fx: A3.mirror_pair(R[f"E2_{fx}_h0.005_P4_orig"], R[f"E2_{fx}_h0.005_P4_mirror"])["verdict"] for fx in ("1D", "M1")}
            e2 = ("MIRROR_PASS" if all(v == "MIRROR_PASS" for v in pairs.values()) else
                  "MIRROR_FAIL" if "MIRROR_FAIL" in pairs.values() else "INCONCLUSIVE")
            out["E1_detail"] = {k: eq[k] for k in ("verdict", "P12_self", "n_fail", "n_undecidable", "max_rel_diff")}
            out["E1_P4_self"] = p4self
            out["E2_pairs"] = pairs
        out["final"] = {"EVIDENCE_INTEGRITY": out["EVIDENCE_INTEGRITY"], "integrity_errors": errs, "E1_P12_equals_P4": e1, "E2_mirror_P4": e2}
    else:
        per = {}
        for fam, h in (("M1", 0.005), ("M1", 0.00125), ("M2", 0.00125)):
            fk = f"{fam}_D0_h{h}"
            if not ok:
                per[fk] = {"current": block, "node_state": block}
                continue
            r12, r4 = R[f"D4_{fk}_P12"], R[f"D4_{fk}_P4"]
            cc, nc = current_compare(r12, r4), node_compare(r12, r4, npz_dir)
            per[fk] = {"current": cc["verdict"], "node_state": nc["verdict"], "current_detail": {k: cc[k] for k in cc if k != "rows"},
                       "current_rows": cc["rows"], "node_detail": nc,
                       "wall_s": {"P12": r12.get("wall_s"), "P4": r4.get("wall_s")},
                       "solve_wall_s": {"P12": {s: r12["steps"][s]["info"].get("wall_s") for s in STEPS},
                                        "P4": {s: r4["steps"][s]["info"].get("wall_s") for s in STEPS}},
                       "iterations": {"P12": {s: r12["steps"][s]["info"].get("iterations") for s in STEPS},
                                      "P4": {s: r4["steps"][s]["info"].get("iterations") for s in STEPS}}}
        cur = [v["current"] for v in per.values()]
        nod = [v["node_state"] for v in per.values()]
        if not ok:
            g2, g3 = "P12_GENERALITY_INCONCLUSIVE", "NODE_STATE_INCONCLUSIVE"
        else:
            g2 = ("P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES" if all(c == "PASS" for c in cur) else
                  "P12_DIFFERS_FROM_P4_ON_TESTED_FIXTURE" if "FAIL" in cur else "P12_GENERALITY_INCONCLUSIVE")
            g3 = ("NODE_STATE_MATCHES_ON_TESTED_FIXTURES" if all(c == "MATCHES" for c in nod) else
                  "NODE_STATE_DIFFERS" if "DIFFERS" in nod else "NODE_STATE_INCONCLUSIVE")
        out["per_fixture"] = per
        out["final"] = {"EVIDENCE_INTEGRITY": out["EVIDENCE_INTEGRITY"], "integrity_errors": errs, "P12_generality": g2, "node_state": g3,
                        "per_fixture": {k: {"current": v["current"], "node_state": v["node_state"]} for k, v in per.items()}}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, f"analysis_d4_mode_{a.mode}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=float)
    print(json.dumps(out["final"], indent=1, default=float)[:3000])
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
