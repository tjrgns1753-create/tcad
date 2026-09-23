"""Batch 7D -- false-green mutation check. Copies the package + tests into a scratch tree (never the real one), breaks ONE
thing, runs the test/script that must catch it, requires a non-zero/failing outcome with the expected text.
usage: python mutation_runner_7d.py <scratch_dir>
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = Path(sys.argv[1])
REV2 = "tests/unit/test_dopant_rev2_contract_mock.py"
REAL = "tests/integration/test_dopant_activation_devsim_gate_real.py"
V2 = "tcad/physics/wafer_state_v2.py"
MAP = "tcad/device/devsim/doping_mapping.py"
GUI = "tcad_2d_stagewise.py"
TESTS = (REV2, REAL)

MUTATIONS = [
    ("M1  the junction LINE (touching rectangles) is wrongly flagged as finite-area compensation", V2,
     "    if x1 <= x0 or y1 <= y0:\n        return None\n",
     "    if x1 < x0 or y1 < y0:\n        return None\n",
     REV2, "AssertionError"),
    ("M2  real positive-area compensation is allowed (the gate is removed)", MAP,
     "            problems = compensated_transport_problems(state, region)\n            if not problems:\n                return donors, acceptors, nets\n",
     "            problems = []\n            if not problems:\n                return donors, acceptors, nets\n",
     REV2, "AssertionError"),
]


def build_tree(dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "tcad", dst / "tcad", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "examples", dst / "examples", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / GUI, dst / GUI)
    for t in TESTS:
        (dst / t).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / t, dst / t)


def run(dst: Path, test: str):
    p = subprocess.run([sys.executable, str(dst / test)], cwd=dst, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr)


def last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "Error" in ln:
            return ln[:240]
    return lines[-1][:240] if lines else ""


failed = []
tree = SCRATCH / "tree"
build_tree(tree)
for t in TESTS:
    rc, out = run(tree, t)
    print(f"BASELINE {t}: rc={rc}")
    if rc != 0:
        print(last_line(out))
        failed.append("baseline " + t)

for name, rel, old, new, test, expected in MUTATIONS:
    build_tree(tree)
    path = tree / rel
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if text.count(old) != 1:
        print(f"MUTATION {name}: FAILED TO APPLY ({text.count(old)} matches)")
        failed.append(name)
        continue
    text = text.replace(old, new)
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    rc, out = run(tree, test)
    ok = rc != 0 and expected in out
    print(f"MUTATION {name}\n    caught by {test}: rc={rc}; expected {expected!r} present: {expected in out}\n    -> {last_line(out)}")
    if not ok:
        failed.append(name)

print("\n--- M3: junction node zeroed to break the official-convention assertion -- verified INLINE inside test_dopant_activation_devsim_gate_real.py's own guards (real DevSim); its own rc=0 run already exercises this. See raw/TARGET_test_dopant_activation_devsim_gate_real.out.txt.")

print()
print("ALL MUTATIONS CAUGHT" if not failed else f"NOT CAUGHT / FAILED: {failed}")
sys.exit(1 if failed else 0)
