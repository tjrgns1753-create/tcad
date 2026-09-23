"""Batch 7C Rev.2 -- false-green mutation check on PRODUCTION code.

Each mutation is applied to a scratch COPY of the tree (never the real one): one production behaviour is broken, the test that must catch it is
run, and the run must exit non-zero with the expected assertion text. An unmutated baseline of every test must pass first.
usage: python mutation_runner.py <scratch_dir>
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = Path(sys.argv[1])
REV2 = "tests/unit/test_dopant_rev2_contract_mock.py"
REAL = "tests/integration/test_dopant_activation_devsim_gate_real.py"
ACT = "tests/unit/test_dopant_activation_compensation_mock.py"
GUI_T = "tests/unit/test_gui_doping_application_truthfulness_mock.py"
TESTS = (REV2, REAL, ACT, GUI_T)
DOPING = "tcad/physics/doping.py"
CLI = "tcad/cli/run_pipeline.py"
MAP = "tcad/device/devsim/doping_mapping.py"
ACC = "tcad/physics/wafer_state_accumulation.py"
DP = "tcad/physics/dopant_profile.py"
GUI = "tcad_2d_stagewise.py"

GATE_OLD = "            problems = compensated_transport_problems(state, region)\n            if not problems:\n                return donors, acceptors, nets\n"

MUTATIONS = [
    ("R1  the helper default ACTIVE is restored (apply_uniform_doping)", [(DOPING, '    species_by_region: Optional[Dict[str, tuple]] = None,\n    chemical_state: str,\n',
                                    '    species_by_region: Optional[Dict[str, tuple]] = None,\n    chemical_state: str = "ACTIVE",\n')],
     REV2, "expected TypeError, nothing was raised"),
    ("R2  the CLI default ACTIVE is restored (missing chemical_state accepted as ACTIVE)", [
        (CLI, '    if "chemical_state" not in cfg:\n', '    if False:\n'),
        (CLI, 'state = validate_chemical_state(cfg["chemical_state"])', 'state = validate_chemical_state(cfg.get("chemical_state", "ACTIVE"))')],
     REV2, "nothing was raised"),
    ("R2b a bare `chemical_state: ACTIVE` is accepted for gaussian_implant / implant_windows", [
        (CLI, 'if kind in _PROCESS_LIKE_KINDS and state == "ACTIVE" and semantics != DIRECT_ANALYTIC_ACTIVE:', 'if False:')],
     REV2, "nothing was raised"),
    ("R3  the compensated-transport gate is removed", [(MAP, GATE_OLD, "            problems = []\n            if not problems:\n                return donors, acceptors, nets\n")],
     REV2, "AssertionError"),
    ("R3b the same removal, on a REAL DevSim device (a compensated region writes doping)", [(MAP, GATE_OLD, "            problems = []\n            if not problems:\n                return donors, acceptors, nets\n")],
     REAL, "DevSim doping write(s)"),
    ("R4  a compensated region is allowed ONE devsim.solve before it is refused", [(MAP, "            n = len(points)\n            scope = f\"{n} of {n} mesh node(s) blocked (region-level: compensated region)\"\n",
                                                                                    "            n = len(points)\n            backend.require_devsim().solve(type=\"dc\")\n            scope = f\"{n} of {n} mesh node(s) blocked (region-level: compensated region)\"\n")],
     REAL, "devsim.solve was called 1 time(s)"),
    ("R4b the same one-solve mutation, on the recording DevSim of the unit test", [(MAP, "            n = len(points)\n            scope = f\"{n} of {n} mesh node(s) blocked (region-level: compensated region)\"\n",
                                                                                      "            n = len(points)\n            backend.require_devsim().solve(type=\"dc\")\n            scope = f\"{n} of {n} mesh node(s) blocked (region-level: compensated region)\"\n")],
     REV2, "AssertionError"),
    ("R5  a strict SUBSET of the requested support is accepted as an exact reattach", [(ACC, "            and a.support_region_um == desired\n",
                                                                                        "            and a.support_region_um is not None and v2._covered_by(a.support_region_um, [desired])\n")],
     REV2, "expected a refused reattach"),
    ("R5b a strict SUPERSET of the requested support is accepted as an exact reattach", [(ACC, "            and a.support_region_um == desired\n",
                                                                                          "            and a.support_region_um is not None and v2._covered_by(desired, [a.support_region_um])\n")],
     REV2, "expected a refused reattach"),
    ("R5c the reattach ignores the barrier windows an application would use", [(GUI, '                state, doped_result.doping,\n                barrier_windows=barrier_windows, barrier_axis="x")',
                                                                                  '                state, doped_result.doping)')],
     REV2, "AssertionError"),
    ("R6  the step junction activates BOTH polarities at the junction coordinate", [(DP, "v * _below(x, p)", "v * _step(p - x)")],
     REV2, "exactly ONE polarity"),
    ("R6b the same, on a REAL DevSim device (the junction node carries both polarities)", [(DP, "v * _below(x, p)", "v * _step(p - x)")],
     REAL, "carry BOTH polarities"),
    ("R7  the compensation gate treats an unknown-model donor+acceptor as compatible", [(
        "tcad/physics/wafer_state_v2.py", "                if rd is None or ra is None:\n                    out.append(",
        "                if rd is None or ra is None:\n                    continue\n                    out.append(")],
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
for name, edits, test, expected in MUTATIONS:
    build_tree(tree)
    ok_apply = True
    for rel, old, new in edits:
        path = tree / rel
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        if text.count(old) != 1:
            print(f"MUTATION {name}: FAILED TO APPLY to {rel} ({text.count(old)} matches)")
            ok_apply = False
            break
        text = text.replace(old, new)
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    if not ok_apply:
        failed.append(name)
        continue
    rc, out = run(tree, test)
    ok = rc != 0 and expected in out
    print(f"MUTATION {name}\n    caught by {test}: rc={rc}; expected {expected!r} present: {expected in out}\n    -> {last_line(out)}")
    if not ok:
        failed.append(name)
print()
print("ALL MUTATIONS CAUGHT" if not failed else f"NOT CAUGHT / FAILED: {failed}")
sys.exit(1 if failed else 0)
