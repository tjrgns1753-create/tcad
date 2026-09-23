"""Batch 7D Rev.2 -- mutation tests for check_matrix_completeness.py / scan_public_api_only.py.

Builds each mutated fixture from a REAL, already-converged case pulled out of
data/rev2_L0L3.json (never invented from scratch), injects exactly one defect per
Codex's section-10 list, and asserts the corresponding checker exits 1 and names the
defect. Mutation 8 (private DEVSIM API access) mutates a COPY of probe_case.py's source
text and runs scan_public_api_only.py on it, never the real script.

usage: python mutation_runner_rev2.py
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
CHECKER = os.path.join(HERE, "check_matrix_completeness.py")
SCANNER = os.path.join(HERE, "scan_public_api_only.py")
PROBE = os.path.join(HERE, "probe_case.py")

with open(os.path.join(DATA, "rev2_L0L3.json"), encoding="utf-8") as f:
    BASE = json.load(f)["rev2_L0L3"]
BY_LABEL = {c["label"]: c for c in BASE}

results = []


def run_checker(matrix_name, cases, levels):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "m.json")
        json.dump({matrix_name: cases}, open(path, "w", encoding="utf-8"))
        p = subprocess.run([sys.executable, CHECKER, path, levels], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def check(name, expect_substring, returncode, output):
    caught = returncode == 1 and expect_substring in output
    results.append((name, caught, output.strip().splitlines()[-1] if output.strip() else "(no output)"))
    print(f"[{name}] {'CAUGHT' if caught else 'MISSED'} (rc={returncode})")


def full_l0l3(overrides_by_label):
    """Full, valid L0-L3 case list with a per-label dict of field overrides applied."""
    out = []
    for label, c in BY_LABEL.items():
        c2 = copy.deepcopy(c)
        c2.update(overrides_by_label.get(label, {}))
        out.append(c2)
    return out


# ---- 1. shifted-xj-collapses-to-0 (the exact Rev.1 bug: shifted xj == aligned x0) --------------------------------
label = "rev2_L0L3_1d_L0_R1_shift"
mutated = full_l0l3({label: {"xj_used_cm": BY_LABEL[label]["x0_aligned_cm"]}})
rc, out = run_checker("m1", mutated, "0,1,2,3")
check("1_shifted_xj_collapses_to_0", "no real shift", rc, out)

# ---- 2. shifted junction_on_a_node=True allowed --------------------------------------------------------------------
label = "rev2_L0L3_1d_L0_R1_shift"
mutated = full_l0l3({label: {"junction_on_a_node": True}})
rc, out = run_checker("m2", mutated, "0,1,2,3")
check("2_shifted_on_node_true", "shifted case must have junction_on_a_node=False", rc, out)

# ---- 3. identical aligned/shifted doping arrays pass -----------------------------------------------------------------
label = "rev2_L0L3_1d_L0_R1_shift"
aligned_label = "rev2_L0L3_1d_L0_R1_node"
mutated = full_l0l3({label: {"donors_at_x0": BY_LABEL[aligned_label]["donors_at_x0"],
                              "acceptors_at_x0": BY_LABEL[aligned_label]["acceptors_at_x0"]}})
rc, out = run_checker("m3", mutated, "0,1,2,3")
check("3_identical_aligned_shifted_doping", "IDENTICAL", rc, out)

# ---- 4. contact-potential-span mislabeled as independent Vbi (Rev.1's forbidden legacy field name) ------------------
label = "rev2_L0L3_1d_L0_R1_node"
mutated = full_l0l3({label: {"V_bi_solved": BY_LABEL[label]["contact_potential_span"]}})
rc, out = run_checker("m4", mutated, "0,1,2,3")
check("4_forbidden_legacy_vbi_field", "forbidden legacy field name", rc, out)

# ---- 5. maximum_iterations stored as actual_iterations --------------------------------------------------------------
label = "rev2_L0L3_1d_L0_R1_node"
mutated_case = copy.deepcopy(BY_LABEL[label])
mutated_case["solve_detail"] = copy.deepcopy(mutated_case["solve_detail"])
mutated_case["solve_detail"]["stage2_drift_diffusion"]["actual_iterations"] = \
    mutated_case["solve_detail"]["stage2_drift_diffusion"]["iteration_limit"]
mutated = full_l0l3({label: mutated_case})
rc, out = run_checker("m5", mutated, "0,1,2,3")
check("5_fabricated_actual_iterations", "actual_iterations is not None", rc, out)

# ---- 6. L4 or L5 missing (run the checker against the REAL L4/L5 matrix with one case dropped) -----------------------
with open(os.path.join(DATA, "rev2_L4L5.json"), encoding="utf-8") as f:
    l4l5 = json.load(f)["rev2_L4L5"]
dropped = [c for c in l4l5 if c["label"] != "rev2_L4L5_2d_L5_R1_node"]
rc, out = run_checker("m6", dropped, "4,5")
check("6_l5_case_missing", "missing (geometry, level, representation, shifted) combinations", rc, out)

# ---- 7. contact conservation missing ---------------------------------------------------------------------------------
label = "rev2_L0L3_1d_L0_R1_node"
mutated_case = copy.deepcopy(BY_LABEL[label])
mutated_case["bias_points"] = [dict(bp) for bp in mutated_case["bias_points"]]
del mutated_case["bias_points"][1]["conservation_error"]
mutated = full_l0l3({label: mutated_case})
rc, out = run_checker("m7", mutated, "0,1,2,3")
check("7_conservation_error_missing", "missing conservation_error", rc, out)

# ---- 8. private DEVSIM API access (mutate a COPY of probe_case.py's source, never the real file) ---------------------
src = open(PROBE, encoding="utf-8").read()
mutated_src = src.replace("devsim.solve(type=\"dc\", **kw)",
                           "devsim.solve(type=\"dc\", **kw); devsim._internal_hack()", 1)
assert mutated_src != src, "mutation site not found in probe_case.py -- update this mutation test"
with tempfile.TemporaryDirectory() as td:
    mpath = os.path.join(td, "probe_case_mutated.py")
    open(mpath, "w", encoding="utf-8").write(mutated_src)
    p = subprocess.run([sys.executable, SCANNER, mpath], capture_output=True, text=True)
    check("8_private_devsim_api_access", "PRIVATE/INTERNAL ACCESS", p.returncode, p.stdout + p.stderr)

print()
print("=== SUMMARY ===")
all_caught = True
for name, caught, last_line in results:
    print(f"{'CAUGHT' if caught else 'MISSED'}  {name}  ({last_line})")
    all_caught = all_caught and caught
print()
if all_caught:
    print(f"ALL {len(results)}/8 MUTATIONS CAUGHT.")
    sys.exit(0)
else:
    print("SOME MUTATIONS WERE MISSED -- see above.")
    sys.exit(1)
