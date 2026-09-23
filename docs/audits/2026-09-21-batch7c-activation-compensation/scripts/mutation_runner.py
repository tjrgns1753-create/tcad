"""Batch 7C -- false-green mutation check on PRODUCTION code.

For each mutation: copy the package + GUI + the needed tests into a scratch tree, break ONE production behaviour there (never in the real
tree), run the test that must catch it, and require a non-zero exit whose last traceback line is the expected assertion. A baseline run of the
unmutated copy must pass first. The real working tree is never modified by this script.
usage: python mutation_runner.py <scratch_dir>
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = Path(sys.argv[1])
UNIT_ACT = "tests/unit/test_dopant_activation_compensation_mock.py"
UNIT_GUI = "tests/unit/test_gui_doping_application_truthfulness_mock.py"
REAL = "tests/integration/test_dopant_activation_devsim_gate_real.py"
V2 = "tcad/physics/wafer_state_v2.py"
DP = "tcad/physics/dopant_profile.py"
ACC = "tcad/physics/wafer_state_accumulation.py"
GUI = "tcad_2d_stagewise.py"

MUTATIONS = [
    ("M1  the activation gate is removed from net_doping_at (CHEMICAL summed like ACTIVE)", V2,
     'if a.chemical_state != "ACTIVE" and (', 'if False and (', UNIT_ACT, "expected all three None"),
    ("M2  a CHEMICAL/UNKNOWN attachment reads as 0.0 instead of None", V2,
     '''                        donor_concentration=None, acceptor_concentration=None,
                        net_doping=None,
                        physics_status={
                            "resolution": "UNSUPPORTED_BY_MODEL",
                            "entries": [{
                                "parameter": "dopant_activation_state",''',
     '''                        donor_concentration=0.0, acceptor_concentration=0.0,
                        net_doping=0.0,
                        physics_status={
                            "resolution": "UNSUPPORTED_BY_MODEL",
                            "entries": [{
                                "parameter": "dopant_activation_state",''', UNIT_ACT, "expected all three None"),
    ("M3  Gaussian explicit donor/acceptor peaks are collapsed into the derived net", DP,
     'if region.donor_peak_conc_cm3 is not None or region.acceptor_peak_conc_cm3 is not None:', 'if False:', UNIT_ACT, "AssertionError"),
    ("M4  the GUI passes only the net (donor - acceptor) for Uniform", GUI,
     '''                    donor_by_region_cm3={region: donor},
                    acceptor_by_region_cm3={region: acceptor},''',
     '''                    donor_by_region_cm3={region: max(conc, 0.0)},
                    acceptor_by_region_cm3={region: max(-conc, 0.0)},''', UNIT_GUI, "supported doping must return True"),
    ("M5  reattach succeeds when ANY attachment exists", ACC,
     '''    if not isinstance(state, v2.WaferStateV2) or doping is None:
        return False, (), "no canonical WaferStateV2 or no doping request"''',
     '''    if not isinstance(state, v2.WaferStateV2) or doping is None:
        return False, (), "no canonical WaferStateV2 or no doping request"
    if state.attachments:
        return True, tuple(state.attachments), "any attachment"''', UNIT_ACT, "AssertionError"),
    ("M6  the doping request is no longer atomic (partial attachments stay)", ACC,
     'partial = any(would_attach) and not all(would_attach)', 'partial = False', UNIT_ACT, "a partly refused request must leave NO new active attachment"),
    ("M7  a CHEMICAL request is reported as an applied active doping", GUI,
     'if any(a.chemical_state != "ACTIVE" for a in recorded):', 'if False:', UNIT_GUI, "AssertionError"),
    ("M8  chemical_state validation is disabled", V2,
     'if value not in CHEMICAL_STATES:', 'if False:', UNIT_ACT, "was accepted"),
    ("M9  an undeclared DopingRegion is read as ACTIVE instead of UNKNOWN", DP,
     'state = "UNKNOWN" if region.chemical_state is None else region.chemical_state', 'state = "ACTIVE"', UNIT_ACT, "AssertionError"),
    ("M10 the activation gate is removed -- on a REAL DevSim device", V2,
     'if a.chemical_state != "ACTIVE" and (', 'if False and (', REAL, "DevSim doping write(s)"),
    ("M11 a refused request still replaces last_doped_result (GUI)", GUI,
     '''        if refused:
            self._log(''', '''        if refused:
            self.last_doped_result = doped_result
            self._log(''', UNIT_GUI, "last_doped_result untouched"),
]


def build_tree(dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "tcad", dst / "tcad", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / GUI, dst / GUI)
    for t in (UNIT_ACT, UNIT_GUI, REAL):
        (dst / t).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / t, dst / t)


def run(dst: Path, test: str):
    p = subprocess.run([sys.executable, str(dst / test)], cwd=dst, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr)


def last_assertion(out: str) -> str:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "Error" in ln or "AssertionError" in ln:
            return ln[:230]
    return lines[-1][:230] if lines else ""


failed = []
tree = SCRATCH / "tree"
build_tree(tree)
for t in (UNIT_ACT, UNIT_GUI, REAL):
    rc, out = run(tree, t)
    print(f"BASELINE {t}: rc={rc}")
    if rc != 0:
        print(last_assertion(out))
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
    path.write_bytes((text.replace(old, new).replace("\n", "\r\n") if crlf else text.replace(old, new)).encode("utf-8"))
    rc, out = run(tree, test)
    ok = rc != 0 and expected in out
    print(f"MUTATION {name}\n    caught by {test}: rc={rc}; expected {expected!r} present: {expected in out}\n    -> {last_assertion(out)}")
    if not ok:
        failed.append(name)
print()
print("ALL MUTATIONS CAUGHT" if not failed else f"NOT CAUGHT / FAILED: {failed}")
sys.exit(1 if failed else 0)
