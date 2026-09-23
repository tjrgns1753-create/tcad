"""Batch 6 static checks. Read-only; repo root derived from this file's location.

Text / AST / file-time scans: they state what is written in the three migrated tests and which files changed. They do not
prove that the backend behaves correctly (the real runs do) and are not a physical-correctness argument."""
import ast
import datetime
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parents[1]
TESTS = {
    "birds_beak": ROOT / "tests/integration/test_locos_birds_beak_real.py",
    "contact_mode": ROOT / "tests/integration/test_locos_contact_mode_fix_real.py",
    "physics_refs": ROOT / "tests/integration/test_physics_references_real.py",
}
ALLOWED = {str(p.relative_to(ROOT)).replace("\\", "/") for p in TESTS.values()}
failed = []


def read(p):
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def report(ok, text):
    print(("PASS  " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


trees = {k: ast.parse(read(p)) for k, p in TESTS.items()}

# 1 -- no skip / xfail / silent return / broad exception swallowing ---------------------------------------------------------
bad = []
import io
import tokenize
for k, t in trees.items():
    src = read(TESTS[k])
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):       # NAME tokens only: docstrings and comments are not code
        if tok.type == tokenize.NAME and tok.string in ("skip", "xfail", "skipTest", "SkipTest", "pytest", "mark"):
            bad.append((k, tok.start[0], tok.string))
    for n in ast.walk(t):
        if isinstance(n, ast.ExceptHandler):
            names = [getattr(n.type, "id", None)] if not isinstance(n.type, ast.Tuple) else [getattr(e, "id", None) for e in n.type.elts]
            if n.type is None or any(x in (None, "Exception", "BaseException") for x in names):
                bad.append((k, n.lineno, "broad except"))
report(not bad, f"1. no skip/xfail/pytest marks and no bare/broad `except` in the three tests (only `except AssertionError` in guards/calibration): {bad}")

# 2 -- the old positive-time oxidation measurements are gone from the CODE (identifiers, numbers) -----------------------------
forbidden_names = {"plateau", "pad_only", "edge_y", "retention", "consumed", "grown", "ratio", "STOICHIOMETRIC_RATIO", "chained", "single",
                   "_sio2_top_by_x", "_measure", "expected_pre_mask_area", "x_hi", "x_lo", "taper"}
hits = []
for k, t in trees.items():
    for n in ast.walk(t):
        nm = n.id if isinstance(n, ast.Name) else (n.name if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else n.arg if isinstance(n, ast.arg) else None)
        if nm in forbidden_names:
            hits.append((k, n.lineno, nm))
    for n in ast.walk(t):
        if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value in (0.44, 0.9, 0.90, 0.05 * 0 + 0.03):
            hits.append((k, n.lineno, n.value))
report(not hits, f"2. no identifier or numeric literal of the old oxide-growth/plateau/taper/retention/stoichiometry/additivity checks remains in the code: {hits}")

# 3 -- every positive-time request is really positive; zero is never used to pass -------------------------------------------------
vals = []
for k, p in TESTS.items():
    src = read(p)
    vals += [(k, float(v)) for v in re.findall(r'"time_hours":\s*([0-9.eE+-]+)', src)]
    vals += [(k, float(v)) for v in re.findall(r"POSITIVE_HOURS = \(([^)]*)\)", src) for v in v.split(",") if v.strip()]
report(vals and all(v > 0 for _, v in vals), f"3. every time_hours literal in the three tests is > 0 (no positive request was turned into 0 h): {vals}")

# 4 -- each file traps all four forbidden paths and pins the reason codes ---------------------------------------------------------------
need = ("vps.Process", "vps.Oxidation", "setInitialOxideThickness", "LocosOxidation._build_locos_geometry")
res = {}
for k, p in TESTS.items():
    s = read(p)
    res[k] = all(n in s for n in need) and "calibrate_trap()" in s and "assert_not_entered" in s and "SolverTrap()" in s
reasons = {"birds_beak": "LOCOS_CAPABILITY_PROOF_MISSING", "physics_refs": "OXIDATION_CAPABILITY_PROOF_MISSING"}
res2 = {k: v in read(TESTS[k]) for k, v in reasons.items()}
res2["contact_mode"] = all(v in read(TESTS["contact_mode"]) for v in ("OXIDATION_CAPABILITY_PROOF_MISSING", "LOCOS_CAPABILITY_PROOF_MISSING"))
report(all(res.values()) and all(res2.values()),
       f"4. each test defines the four-path solver trap, calibrates it and asserts it was not entered: {res}; exact reason codes pinned: {res2}")

# 5 -- every guard names an expected reason ----------------------------------------------------------------------------------------------
n_guards = {}
ok5 = True
for k, t in trees.items():
    calls = [n for n in ast.walk(t) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "expect_fail"]
    n_guards[k] = len(calls)
    ok5 &= all(len(c.args) >= 3 for c in calls)
report(ok5 and all(v >= 6 for v in n_guards.values()), f"5. expect_fail(check, label, expected) is always called with an expected reason (3 args); guards per file: {n_guards}")

# 6 -- T3b kept, not weakened -----------------------------------------------------------------------------------------------------------
s = read(TESTS["physics_refs"])
t3b = all(x in s for x in ('registry.get("etching", "isotropic")', '"material_rates": {"Si": 0.0}', '"default_rate": 0.0', '"etch_time_s": 0.5',
                            "TOL_SI_UNMOVED = 0.5 * GRID", 'si_entries[0]["value"] == 0.0', "DOES NOT VERIFY PHYSICAL CORRECTNESS"))
report(t3b, "6. T3b keeps the real isotropic etch entry point, rate 0 for Si, the 0.5 x grid unmoved bound, the resolver-reported 0.0 entry, and the 'does not verify physical correctness' label")

# 7 -- scope --------------------------------------------------------------------------------------------------------------------------------
before = {}
for line in (AUDIT / "raw/production_sha256_start.txt").read_text(encoding="utf-8").splitlines():
    if line.strip():
        h, rel = line.split("  ", 1)
        before[rel.strip()] = h.lower()
changed = [rel for rel, h in before.items() if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != h]
new_prod = sorted({str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.joinpath("tcad").rglob("*.py")} - set(before) - {"tcad_2d_stagewise.py"})
report(not changed and not new_prod, f"7a. production ({len(before)} files: tcad/**/*.py + tcad_2d_stagewise.py): changed={changed}, new={new_prod}")
start = datetime.datetime.fromisoformat((AUDIT / "raw/start_timestamp.txt").read_text().strip()).timestamp()
touched = []
for p in ROOT.rglob("*"):
    if not p.is_file() or ".git" in p.parts or ".serena" in p.parts or "__pycache__" in p.parts or AUDIT in p.parents or p.suffix == ".pyc":   # .serena/cache: Serena tool cache, not repository content
        continue
    try:
        if p.stat().st_mtime > start:
            touched.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    except OSError:
        pass
# CLAUDE.md was modified DURING the batch (a "Project-wide Serena MCP policy" section was added) by an actor other than this batch:
# no command, script or test of this batch writes it (checked below). It is listed, not silently passed.
EXTERNAL_ACKNOWLEDGED = {"CLAUDE.md"}
writers = [str(p.relative_to(ROOT)) for p in list(ROOT.joinpath("tests").rglob("*.py")) + list(AUDIT.joinpath("scripts").rglob("*.py"))
           if re.search(r"CLAUDE\.md['\"]\)?\s*\.?\s*(write_text|write_bytes|open\([^)]*['\"][wa])|open\(['\"][^'\"]*CLAUDE\.md['\"],\s*['\"][wa]", read(p))]
outside = sorted(set(touched) - ALLOWED - EXTERNAL_ACKNOWLEDGED)
report(not outside, f"7b. files modified since the start of the batch: {sorted(set(touched))}; outside the three allowed tests and not acknowledged: {outside}")
ext = sorted(set(touched) & EXTERNAL_ACKNOWLEDGED)
mt = {e: datetime.datetime.fromtimestamp((ROOT / e).stat().st_mtime).isoformat(timespec="seconds") for e in ext}
report(not writers, f"7c. NOTE -- externally modified during the batch (not by this batch): {mt}; test/script files in the repo that write CLAUDE.md: {writers}")

print()
print("ALL STATIC CHECKS PASS" if not failed else f"{len(failed)} STATIC CHECK(S) FAILED")
sys.exit(1 if failed else 0)
