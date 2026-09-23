"""Batch 7D -- false-green checks on the audit's OWN completeness/conservation checker (check_matrix_completeness.py),
not on production. Two mutations against a COPY of data/matrix.json:
  M4 drop one refinement level entirely -> the completeness check must report it missing.
  M5 remove 'conservation_error' from a converged bias point -> the completeness check must report it missing.
Also runs the public-API-only scanner (M6) against a copy of the probe script with one disallowed private-looking
call injected, and confirms the scanner flags it.
usage: python mutation_completeness.py <scratch_dir>
"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)
SCRATCH = sys.argv[1]
os.makedirs(SCRATCH, exist_ok=True)
matrix = json.load(open(os.path.join(HERE, "..", "data", "matrix.json"), encoding="utf-8"))

failed = []


def run_completeness(path):
    p = subprocess.run([sys.executable, os.path.join(HERE, "check_matrix_completeness.py"), path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


# Informational only: the real Trial-A matrix legitimately contains genuine non-convergence (R1 on the 2D
# unstructured mesh under the too-tight 1D-example tolerance) and one real probe-execution error case, both
# real findings this batch reports -- rc!=0 here is the CORRECT, truthful completeness verdict, not a bug, so
# it is never counted as a caught/failed mutation.
rc, out = run_completeness(os.path.join(HERE, "..", "data", "matrix.json"))
print(f"INFO (not a mutation, not required to pass) completeness check on the real Trial-A matrix: rc={rc} "
      f"(non-zero is CORRECT here -- see the batch report for which cases are genuinely UNVERIFIED)")

# M4: drop one level entirely
m4 = copy.deepcopy(matrix)
m4["2d"] = [c for c in m4["2d"] if c.get("level") != 2]
p4 = os.path.join(SCRATCH, "m4_missing_level.json")
json.dump(m4, open(p4, "w", encoding="utf-8"))
rc, out = run_completeness(p4)
ok4 = rc != 0 and "missing mesh/refinement" in out.lower() or "missing" in out.lower()
print(f"MUTATION M4 (drop level 2 from 2D): rc={rc}; caught={ok4}\n    -> {[l for l in out.splitlines() if 'missing' in l.lower()][:1]}")
if not ok4:
    failed.append("M4")

# M5: remove conservation_error from a converged bias point
m5 = copy.deepcopy(matrix)
for c in m5["1d"]:
    if c.get("equilibrium_converged") and c.get("bias_points"):
        for bp in c["bias_points"]:
            if bp.get("converged"):
                del bp["conservation_error"]
                break
        break
p5 = os.path.join(SCRATCH, "m5_missing_conservation.json")
json.dump(m5, open(p5, "w", encoding="utf-8"))
rc, out = run_completeness(p5)
ok5 = rc != 0 and "conservation_error" in out
print(f"MUTATION M5 (remove conservation_error from one converged bias point): rc={rc}; caught={ok5}\n    -> {[l for l in out.splitlines() if 'conservation_error' in l][:1]}")
if not ok5:
    failed.append("M5")

# M6: inject a disallowed devsim.* access into a copy of the probe script and confirm the scanner flags it
src = open(os.path.join(HERE, "probe_step_junction_convergence.py"), encoding="utf-8").read()
injected = src.replace("import devsim  # noqa: E402",
                       "import devsim  # noqa: E402\n_ = devsim._internal_solver_state  # MUTATION: not a public API")
p6 = os.path.join(SCRATCH, "m6_injected_probe.py")
open(p6, "w", encoding="utf-8").write(injected)
p = subprocess.run([sys.executable, os.path.join(HERE, "scan_public_api_only.py"), p6], capture_output=True, text=True, encoding="utf-8", errors="replace")
ok6 = p.returncode != 0 and "PRIVATE/INTERNAL ACCESS" in p.stdout
print(f"MUTATION M6 (inject devsim._internal_solver_state into a probe copy): rc={p.returncode}; caught={ok6}\n    -> {[l for l in p.stdout.splitlines() if 'PRIVATE' in l]}")
if not ok6:
    failed.append("M6")

print()
print("ALL MUTATIONS CAUGHT" if not failed else f"NOT CAUGHT / FAILED: {failed}")
sys.exit(1 if failed else 0)
