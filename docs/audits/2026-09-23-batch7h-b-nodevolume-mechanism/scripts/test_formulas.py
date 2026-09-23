"""Batch 7H-B required test 1-2: analytical formula unit tests and exact
area-conservation tests. No DEVSIM. Also writes data/analytic_predictions.json
(per-node predictions on the INPUT coordinates, recorded before DEVSIM runs)."""
import hashlib
import json
import os
import sys
from fractions import Fraction

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formulas as fm  # noqa: E402
import fixtures as fx  # noqa: E402

RESULTS = []
REL = 1e-12   # pure float64 formula self-consistency, not the DEVSIM comparison tolerance


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{name}] {'PASS' if cond else 'FAIL'}  {detail}")


def exact_area(p):
    fr = [(Fraction(float(x)), Fraction(float(y))) for x, y in p]
    (ax, ay), (bx, by), (cx, cy) = fr
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / 2


def main():
    kinds = {"acute": "T2_scalene_acute", "right": "T3_right_isosceles", "obtuse": "T5_strong_obtuse",
             "equilateral": "T1_equilateral", "mild_obtuse": "T4_mild_obtuse"}
    for kind, name in kinds.items():
        p, t = fx.as_arrays(name)
        A = float(exact_area(p))
        sums = {r: float(fm.node_areas(p, t, r).sum()) for r in fm.RULES}
        for r in ("F1", "F2", "F5"):
            check(f"{kind}_{r}_sum_equals_area", abs(sums[r] - A) <= REL * A, f"sum={sums[r]!r} area={A!r}")
        if kind in ("obtuse", "mild_obtuse"):
            check(f"{kind}_F3_overcounts", sums["F3"] > A * (1 + 1e-9), f"F3/area={sums['F3'] / A:.12f}")
        else:
            check(f"{kind}_F3_equals_area", abs(sums["F3"] - A) <= REL * A, f"F3/area={sums['F3'] / A:.15f}")
            check(f"{kind}_F2_F3_F4_F5_identical",
                  all(np.allclose(fm.node_areas(p, t, r), fm.node_areas(p, t, "F2"), rtol=REL, atol=0)
                      for r in ("F3", "F4", "F5")), "")

    # exact area conservation of the analytic F2 identity on a dyadic obtuse triangle
    p = np.array([[0.0, 0.0], [1.0, 0.0], [0.375, 0.125]])
    cot, l2, _ = fm.tri_parts(p)
    fr = [(Fraction(float(x)), Fraction(float(y))) for x, y in p]

    def fcot(a, b, c):
        u = (b[0] - a[0], b[1] - a[1]); v = (c[0] - a[0], c[1] - a[1])
        return (u[0] * v[0] + u[1] * v[1]) / abs(u[0] * v[1] - u[1] * v[0])
    fc = [fcot(fr[0], fr[1], fr[2]), fcot(fr[1], fr[2], fr[0]), fcot(fr[2], fr[0], fr[1])]
    fl2 = [(fr[(v + 1) % 3][0] - fr[(v + 2) % 3][0]) ** 2 + (fr[(v + 1) % 3][1] - fr[(v + 2) % 3][1]) ** 2 for v in range(3)]
    s = sum((fl2[(i + 2) % 3] * fc[(i + 2) % 3] + fl2[(i + 1) % 3] * fc[(i + 1) % 3]) / 8 for i in range(3))
    check("exact_rational_F2_sum_equals_area", s == exact_area(p), f"sum={s} area={exact_area(p)}")

    # mirror / rotation / scale invariance of every rule (per node, same node order)
    base, t = fx.as_arrays("T4_mild_obtuse")
    for name, scale in (("T6_T4_mirror", 1.0), ("T7_T4_rot90", 1.0), ("T8_T4_x0.1", 0.01), ("T9_T4_x10", 100.0)):
        q, _ = fx.as_arrays(name)
        ok = all(np.allclose(fm.node_areas(q, t, r), scale * fm.node_areas(base, t, r), rtol=1e-12, atol=0) for r in fm.RULES)
        check(f"invariance_{name}", ok, f"expected area scale {scale}")

    # G1 signed element couples: each element edge gives 0.25*couple*L to EACH
    # of its two endpoints, i.e. 0.5*couple*L per element edge in total.
    # (First draft summed 0.25*c*L once per edge and failed at area/2 before
    # any DEVSIM run; corrected here, recorded in REPORT_DRAFT.md.)
    for name in ("T2_scalene_acute", "T5_strong_obtuse"):
        p, t = fx.as_arrays(name)
        ec = fm.element_couples(p, t)
        s = sum(2 * 0.25 * c * L for v in ec.values() for _, c, L in v)
        check(f"{name}_signed_couple_quarter_CL_per_endpoint_sums_to_area", abs(s - fm.tri_area(p)) <= REL * fm.tri_area(p),
              f"sum={s!r} area={fm.tri_area(p)!r}")

    preds = {}
    for name in fx.FIXTURES:
        p, t = fx.as_arrays(name)
        pc = p * 1e-4
        preds[name] = {"area_cm2": sum(fm.tri_area(pc[list(tt)]) for tt in t),
                       "rules": {r: fm.node_areas(pc, t, r).tolist() for r in fm.RULES}}
    out = os.path.join(HERE, "..", "data", "analytic_predictions.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(preds, f, indent=1, sort_keys=True)
    print("analytic_predictions.json sha256", hashlib.sha256(open(out, "rb").read()).hexdigest())

    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"=== {len(RESULTS) - n_fail}/{len(RESULTS)} PASSED ===")
    return n_fail == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
