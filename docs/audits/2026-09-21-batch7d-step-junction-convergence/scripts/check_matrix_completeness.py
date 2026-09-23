"""Completeness / conservation check over data/matrix.json (the probe's own output). No fabricated pass/fail
tolerance is invented here: this only checks that every required combination is PRESENT, that every converged
case reports a finite V_bi_error, and that every bias point reports a finite contact-current conservation
error -- then prints the actual numbers for the report to judge by refinement trend, per the batch's own
"do not invent a tolerance" instruction.
usage: python check_matrix_completeness.py <matrix.json>
"""
import json
import math
import sys

path = sys.argv[1]
m = json.load(open(path, encoding="utf-8"))

REQUIRED_LEVELS = {0, 1, 2, 3}
REQUIRED_REPS = {"R1", "R2"}
REQUIRED_SHIFT = {False, True}

problems = []


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


for geometry in ("1d", "2d"):
    cases = m.get(geometry, [])
    combos = {(c.get("level"), c.get("representation"), c.get("shifted")) for c in cases}
    missing = {(lv, rep, sh) for lv in REQUIRED_LEVELS for rep in REQUIRED_REPS for sh in REQUIRED_SHIFT} - combos
    if missing:
        problems.append(f"{geometry}: missing mesh/representation combinations: {sorted(missing)}")
    for c in cases:
        label = c.get("label")
        if "error" in c:
            problems.append(f"{geometry}/{label}: probe raised {c['error']}")
            continue
        if not c.get("equilibrium_converged"):
            problems.append(f"{geometry}/{label}: equilibrium did not converge -- UNVERIFIED, no V_bi/bias data expected")
            continue
        if not finite(c.get("V_bi_error")):
            problems.append(f"{geometry}/{label}: V_bi_error is not finite: {c.get('V_bi_error')!r}")
        if not c.get("bias_points"):
            problems.append(f"{geometry}/{label}: no bias points recorded")
            continue
        for bp in c["bias_points"]:
            if bp.get("converged") and "conservation_error" not in bp:
                problems.append(f"{geometry}/{label}: bias point {bp} is missing conservation_error")
            elif bp.get("converged") and not finite(bp.get("conservation_error")):
                problems.append(f"{geometry}/{label}: bias point conservation_error is not finite: {bp}")

if problems:
    print("COMPLETENESS CHECK FAILED:")
    for p in problems:
        print(" -", p)
    sys.exit(1)

print("COMPLETENESS CHECK PASSED: all required (level x representation x shift) combinations present for 1D and 2D; "
      "every converged case has a finite V_bi_error; every converged bias point has a finite conservation_error.")

# ---- refinement-trend report (descriptive only, no invented tolerance) --------------------------------------
for geometry in ("1d", "2d"):
    print(f"\n--- {geometry} V_bi_error and conservation-error trend by level (R1 vs R2, node-aligned) ---")
    for rep in ("R1", "R2"):
        row = []
        for lv in sorted(REQUIRED_LEVELS):
            c = next((c for c in m[geometry] if c.get("level") == lv and c.get("representation") == rep and c.get("shifted") is False), None)
            if c and c.get("equilibrium_converged"):
                cons = [bp.get("conservation_error") for bp in c.get("bias_points", []) if bp.get("converged")]
                row.append(f"L{lv}: Vbi_err={c['V_bi_error']:.3e} max|cons|={max(cons) if cons else float('nan'):.3e}")
            else:
                row.append(f"L{lv}: NOT CONVERGED")
        print(f"  {rep}: " + " | ".join(row))
