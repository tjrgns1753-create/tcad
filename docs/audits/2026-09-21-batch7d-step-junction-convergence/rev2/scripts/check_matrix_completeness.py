"""Batch 7D Rev.2 completeness checker over data/rev2_L0L3.json / rev2_L4L5.json. Enforces every requirement
section 9 of the bounded prompt lists. No fabricated pass/fail tolerance beyond what's explicitly specified.
usage: python check_matrix_completeness.py <matrix.json> <levels-comma-separated e.g. 0,1,2,3>
"""
import json
import math
import sys

path, levels_arg = sys.argv[1], sys.argv[2]
REQUIRED_LEVELS = {int(x) for x in levels_arg.split(",")}
REQUIRED_GEOM = {"1d", "2d"}
REQUIRED_REPS = {"R1", "R2"}
REQUIRED_SHIFT = {False, True}

m = json.load(open(path, encoding="utf-8"))
(key,) = m.keys()
cases = m[key]
problems = []


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


# ---- 1. every requested (geometry, level, representation, shifted) combination is present -----------------------------
combos = {(c.get("geometry"), c.get("level"), c.get("representation"), c.get("shifted")) for c in cases}
required = {(g, lv, r, s) for g in REQUIRED_GEOM for lv in REQUIRED_LEVELS for r in REQUIRED_REPS for s in REQUIRED_SHIFT}
missing = required - combos
if missing:
    problems.append(f"missing (geometry, level, representation, shifted) combinations: {sorted(missing)}")

by_key = {}
for c in cases:
    by_key.setdefault((c.get("geometry"), c.get("level"), c.get("representation")), {})[c.get("shifted")] = c

for c in cases:
    label = c.get("label")
    if "error" in c:
        problems.append(f"{label}: probe raised/timed out: {c['error'][:150]}")
        continue

    # ---- 2. aligned junction_on_a_node True; shifted junction_on_a_node False -----------------------------------------
    if c["shifted"] is False and c.get("junction_on_a_node") is not True:
        problems.append(f"{label}: aligned case must have junction_on_a_node=True, got {c.get('junction_on_a_node')}")
    if c["shifted"] is True and c.get("junction_on_a_node") is not False:
        problems.append(f"{label}: shifted case must have junction_on_a_node=False, got {c.get('junction_on_a_node')}")

    # ---- 3. shifted xj actually different, and equals local_spacing/2 --------------------------------------------------
    if c["shifted"] is True:
        disp = c.get("xj_used_cm", 0) - c.get("x0_aligned_cm", 0)
        expect = c.get("local_spacing_cm", 0) / 2.0
        if c.get("xj_used_cm") == c.get("x0_aligned_cm"):
            problems.append(f"{label}: shifted xj equals the aligned x0 (no real shift)")
        if not finite(disp) or abs(disp - expect) > 1e-9 * max(abs(expect), 1e-15):
            problems.append(f"{label}: shifted displacement {disp} != local_spacing/2 ({expect})")

    # ---- 4. aligned vs shifted doping arrays differ at the common reference point x0 -------------------------------------
    if c["shifted"] is True:
        aligned = by_key.get((c["geometry"], c["level"], c["representation"]), {}).get(False)
        if aligned is None or "error" in aligned:
            problems.append(f"{label}: no valid aligned sibling case to compare doping arrays against")
        else:
            if (c.get("donors_at_x0") == aligned.get("donors_at_x0") and c.get("acceptors_at_x0") == aligned.get("acceptors_at_x0")):
                problems.append(f"{label}: aligned/shifted doping at the reference node x0 are IDENTICAL "
                               f"(donors={c.get('donors_at_x0')}, acceptors={c.get('acceptors_at_x0')}) -- the shift had no effect")

    if not c.get("equilibrium_converged"):
        problems.append(f"{label}: equilibrium did not converge -- UNVERIFIED, no bias/field/depletion data expected")
        continue

    # ---- 5. contact-boundary-consistency and independent metrics are separately named / present -----------------------
    if "contact_potential_span" not in c or "contact_boundary_consistency_error" not in c:
        problems.append(f"{label}: missing contact_potential_span / contact_boundary_consistency_error fields")
    forbidden_names = {"V_bi_solved", "V_bi_error", "independent_V_bi", "Vbi_independent"}
    present_forbidden = forbidden_names & set(c.keys())
    if present_forbidden:
        problems.append(f"{label}: forbidden legacy field name(s) present (Rev.1's circular-Vbi naming): {sorted(present_forbidden)}")
    if c.get("peak_field_solved_Vpercm") is None:
        problems.append(f"{label}: missing peak_field_solved_Vpercm (independent, solved-interior metric)")
    if c.get("depletion_recovery_donor_side") is None or c.get("depletion_recovery_acceptor_side") is None:
        problems.append(f"{label}: missing depletion_recovery_* independent metric")

    # ---- 6. actual iteration counts are never fabricated ------------------------------------------------------------------
    for stage_name, stage in c.get("solve_detail", {}).items():
        if stage.get("actual_iterations") is not None:
            problems.append(f"{label}/{stage_name}: actual_iterations is not None ({stage.get('actual_iterations')!r}) -- must be null")
        if stage.get("actual_iterations_status") != "UNAVAILABLE_FROM_PUBLIC_API":
            problems.append(f"{label}/{stage_name}: actual_iterations_status is {stage.get('actual_iterations_status')!r}, expected UNAVAILABLE_FROM_PUBLIC_API")
        if "iteration_limit" not in stage:
            problems.append(f"{label}/{stage_name}: missing iteration_limit")
    for bp in c.get("bias_points", []):
        if bp.get("converged") and bp.get("actual_iterations") is not None:
            problems.append(f"{label}: bias point actual_iterations is not None: {bp}")
        if bp.get("converged") and "conservation_error" not in bp:
            problems.append(f"{label}: bias point missing conservation_error: {bp}")
        elif bp.get("converged") and not finite(bp.get("conservation_error")):
            problems.append(f"{label}: bias point conservation_error not finite: {bp}")

if problems:
    print("COMPLETENESS CHECK FAILED:")
    for p in problems:
        print(" -", p)
    sys.exit(1)

print(f"COMPLETENESS CHECK PASSED ({key}): all combinations present, aligned/shifted preflight holds, doping arrays "
      f"differ, contact-boundary and independent metrics both present and separately named, no fabricated iteration counts.")
