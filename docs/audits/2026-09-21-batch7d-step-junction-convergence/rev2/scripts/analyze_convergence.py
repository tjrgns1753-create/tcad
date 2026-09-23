"""Rev.2 convergence analysis over data/rev2_L0L3.json + data/rev2_L4L5.json (L0..L5).
Read-only report generator -- no production code touched. Prints per-bias-point log-current
tables, R1/R2 delta, aligned/shifted delta, contact conservation, E-field/depletion trends.
"""
import json
import math
import os

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

cases = []
for fn in ("rev2_L0L3.json", "rev2_L4L5.json"):
    d = json.load(open(os.path.join(DATA, fn), encoding="utf-8"))
    (k,) = d.keys()
    cases.extend(d[k])

by_key = {(c["geometry"], c["level"], c["representation"], c["shifted"]): c for c in cases}
LEVELS = [0, 1, 2, 3, 4, 5]


def log10i(i):
    if i is None or i == 0:
        return None
    return math.log10(abs(i))


print("=" * 100)
print("SECTION 9-10: per-bias-point log-current convergence, L0..L5, both geometries")
print("=" * 100)
for geometry in ("1d", "2d"):
    for rep in ("R1", "R2"):
        for shifted in (False, True):
            tag = "{} {} {}".format(geometry, rep, "shift" if shifted else "node")
            print("\n-- {} --".format(tag))
            prev_logs = None
            for lv in LEVELS:
                c = by_key.get((geometry, lv, rep, shifted))
                if c is None:
                    print("  L{}: MISSING".format(lv))
                    prev_logs = None
                    continue
                if not c.get("equilibrium_converged"):
                    print("  L{}: EQ_FAIL".format(lv))
                    prev_logs = None
                    continue
                bp = c.get("bias_points", [])
                n_ok = sum(1 for b in bp if b.get("converged"))
                cur_list = []
                for b in bp:
                    if not b.get("converged"):
                        cur_list.append(None)
                        continue
                    cur = b["currents"]
                    val = list(cur.values())[0]
                    cur_list.append(val)
                logs = [log10i(v) for v in cur_list]
                dlog = None
                if prev_logs is not None and len(prev_logs) == len(logs):
                    diffs = []
                    for a, b2 in zip(prev_logs, logs):
                        diffs.append(round(b2 - a, 4) if (a is not None and b2 is not None) else None)
                    dlog = diffs
                print("  L{}: {}/{} bias ok logI={} dlog_vs_prev_level={}".format(
                    lv, n_ok, len(bp), [round(x, 4) if x is not None else None for x in logs], dlog))
                prev_logs = logs

print()
print("=" * 100)
print("SECTION 11: R1 vs R2 delta (same geometry/level/shift), log10|I| difference per bias point")
print("=" * 100)
for geometry in ("1d", "2d"):
    for shifted in (False, True):
        print("\n-- {} {} --".format(geometry, "shift" if shifted else "node"))
        for lv in LEVELS:
            c1 = by_key.get((geometry, lv, "R1", shifted))
            c2 = by_key.get((geometry, lv, "R2", shifted))
            if c1 is None or c2 is None or not c1.get("equilibrium_converged") or not c2.get("equilibrium_converged"):
                print("  L{}: one or both UNAVAILABLE (R1 eq={}, R2 eq={})".format(
                    lv, c1 and c1.get("equilibrium_converged"), c2 and c2.get("equilibrium_converged")))
                continue
            bp1, bp2 = c1.get("bias_points", []), c2.get("bias_points", [])
            deltas = []
            for b1, b2 in zip(bp1, bp2):
                if not (b1.get("converged") and b2.get("converged")):
                    deltas.append(None)
                    continue
                i1 = list(b1["currents"].values())[0]
                i2 = list(b2["currents"].values())[0]
                l1, l2 = log10i(i1), log10i(i2)
                deltas.append(round(l2 - l1, 6) if (l1 is not None and l2 is not None) else None)
            print("  L{}: delta_log10|I|(R2-R1) per bias = {}".format(lv, deltas))

print()
print("=" * 100)
print("SECTION 12: aligned vs shifted delta (same geometry/level/representation), log10|I| difference")
print("=" * 100)
for geometry in ("1d", "2d"):
    for rep in ("R1", "R2"):
        print("\n-- {} {} --".format(geometry, rep))
        for lv in LEVELS:
            cn = by_key.get((geometry, lv, rep, False))
            cs = by_key.get((geometry, lv, rep, True))
            if cn is None or cs is None or not cn.get("equilibrium_converged") or not cs.get("equilibrium_converged"):
                print("  L{}: one or both UNAVAILABLE (node eq={}, shift eq={})".format(
                    lv, cn and cn.get("equilibrium_converged"), cs and cs.get("equilibrium_converged")))
                continue
            bpn, bps = cn.get("bias_points", []), cs.get("bias_points", [])
            deltas = []
            for bn, bs in zip(bpn, bps):
                if not (bn.get("converged") and bs.get("converged")):
                    deltas.append(None)
                    continue
                iN = list(bn["currents"].values())[0]
                iS = list(bs["currents"].values())[0]
                lN, lS = log10i(iN), log10i(iS)
                deltas.append(round(lS - lN, 6) if (lN is not None and lS is not None) else None)
            print("  L{}: delta_log10|I|(shift-node) per bias = {}".format(lv, deltas))

print()
print("=" * 100)
print("SECTION 13: contact conservation error, and E-field / depletion trend")
print("=" * 100)
for geometry in ("1d", "2d"):
    for rep in ("R1", "R2"):
        for shifted in (False, True):
            tag = "{} {} {}".format(geometry, rep, "shift" if shifted else "node")
            print("\n-- {} --".format(tag))
            for lv in LEVELS:
                c = by_key.get((geometry, lv, rep, shifted))
                if c is None or not c.get("equilibrium_converged"):
                    print("  L{}: N/A".format(lv))
                    continue
                bp = c.get("bias_points", [])
                cons = [round(b.get("conservation_error"), 4) if b.get("converged") and b.get("conservation_error") is not None else None for b in bp]
                ef = c.get("peak_field_solved_Vpercm")
                efa = c.get("E_max_analytic_Vpercm")
                dep_d = c.get("depletion_recovery_donor_side")
                dep_a = c.get("depletion_recovery_acceptor_side")
                ratio = round(ef / efa, 4) if (ef and efa) else None
                print("  L{}: conservation_error={} peak_E_solved={} peak_E_analytic={} E_ratio={} "
                      "depletion_donor_side={} depletion_acceptor_side={}".format(
                          lv, cons, ef, efa, ratio, dep_d, dep_a))
