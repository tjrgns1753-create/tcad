"""Batch 7H-B completeness check. Fails if the pre-declared tolerance or
formula/fixture files changed after the pre-DEVSIM hash, if any fixture is
missing or failed import verification, or if a required output is missing.
usage: check_completeness_7hb.py [audit_dir]"""
import hashlib
import json
import os
import re
import sys

EXPECT = {"EPS": 2.220446049250313e-16, "ABS_FACTOR": 256.0, "REL_TOL": 1e-11}


def main(root):
    problems = []
    draft_rec = open(os.path.join(root, "data", "draft_sha256_before_devsim.txt"), encoding="utf-8").read()
    for line in draft_rec.splitlines():
        m = re.match(r"^([0-9a-f]{64}) \*(.+)$", line.strip())
        if not m:
            continue
        sha, rel = m.groups()
        p = os.path.join(root, rel)
        if not os.path.exists(p) or hashlib.sha256(open(p, "rb").read()).hexdigest() != sha:
            problems.append(f"pre-DEVSIM file changed or missing: {rel}")
    src = open(os.path.join(root, "scripts", "devsim_probe.py"), encoding="utf-8").read()
    for k, v in EXPECT.items():
        m = re.search(rf"^{k}\s*=\s*([0-9.eE+-]+)\s*$", src, re.M)
        if not m or float(m.group(1)) != v:
            problems.append(f"tolerance constant {k} differs from REPORT_DRAFT value {v}: {m.group(1) if m else None}")
    if "def match(d, p, abs_tol):\n    return abs(d - p) <= abs_tol + REL_TOL * abs(p)" not in src:
        problems.append("match() rule differs from the pre-declared rule")
    draft = open(os.path.join(root, "REPORT_DRAFT.md"), encoding="utf-8").read()
    for token in ("ABS_FACTOR   = 256", "REL_TOL      = 1e-11"):
        if token not in draft:
            problems.append(f"REPORT_DRAFT tolerance line missing: {token}")
    res_p = os.path.join(root, "data", "fixture_results.json")
    if not os.path.exists(res_p):
        problems.append("fixture_results.json missing")
    else:
        res = json.load(open(res_p, encoding="utf-8"))
        need = ["T1_equilateral", "T2_scalene_acute", "T3_right_isosceles", "T4_mild_obtuse", "T5_strong_obtuse",
                "T6_T4_mirror", "T7_T4_rot90", "T8_T4_x0.1", "T9_T4_x10", "P1_square_diagA", "P2_square_diagB",
                "P3_kite_nonDelaunay", "P4_kite_Delaunay", "P5_interior_obtuse_Delaunay", "P6_fan_obtuse_centre",
                "P7_fan_right_control"]
        for n in need:
            if n not in res:
                problems.append(f"fixture missing: {n}")
            elif not all(res[n]["verify"].values()):
                problems.append(f"fixture import verification failed: {n}")
    if not os.path.exists(os.path.join(root, "data", "l3_f3_prediction.json")):
        problems.append("l3_f3_prediction.json missing")
    if problems:
        print("COMPLETENESS CHECK FAILED:")
        for p in problems:
            print(" -", p)
        return 1
    print("COMPLETENESS CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
