"""Batch 7 static checks. Read-only; repo root derived from this file's location.

Text / AST / file-time scans: they state what is written in the three migrated tests and which files changed. They do not
prove that the backend behaves correctly (the real runs do) and are not a physical-correctness argument."""
import ast
import datetime
import hashlib
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parents[1]
TESTS = {
    "blanket": ROOT / "tests/integration/test_blanket_no_mask_real.py",
    "chaining": ROOT / "tests/integration/test_locos_chaining_real.py",
    "devsim": ROOT / "tests/integration/test_locos_devsim_import_real.py",
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

# 1 -- no skip / xfail / marks / broad exception swallowing ---------------------------------------------------------------
bad = []
for k, t in trees.items():
    for tok in tokenize.generate_tokens(io.StringIO(read(TESTS[k])).readline):
        if tok.type == tokenize.NAME and tok.string in ("skip", "xfail", "skipTest", "SkipTest", "pytest", "mark"):
            bad.append((k, tok.start[0], tok.string))
    for n in ast.walk(t):
        if isinstance(n, ast.ExceptHandler):
            names = [getattr(n.type, "id", None)] if not isinstance(n.type, ast.Tuple) else [getattr(e, "id", None) for e in n.type.elts]
            if n.type is None or any(x in (None, "Exception", "BaseException") for x in names):
                bad.append((k, n.lineno, "broad except"))
report(not bad, f"1. no skip/xfail/pytest marks and no bare/broad `except` (only `except AssertionError`): {bad}")

# 2 -- the old oxidation-result claims are gone from the CODE (identifiers, numbers) -------------------------------------------
forbidden = {"retention", "mask_area", "expected_pre_mask_area", "areas_by_material", "areas1", "areas2", "areas3", "areas4", "areas5",
             "mask_area_initial", "si_top", "oxide_tag", "mask_tag", "areas_first", "areas_second", "tri_area", "trench_width"}
hits = []
for k, t in trees.items():
    for n in ast.walk(t):
        nm = n.id if isinstance(n, ast.Name) else n.name if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else n.arg if isinstance(n, ast.arg) else None
        if nm in forbidden:
            hits.append((k, n.lineno, nm))
        if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value in (0.9, 0.90):
            hits.append((k, n.lineno, n.value))
report(not hits, f"2. no identifier or literal of the old growth/consumption/retention/coherence/chaining checks remains in the code: {hits}")

# 3 -- no manual chaining and no import of a refused result ---------------------------------------------------------------------
chain_src = read(TESTS["chaining"])
kw = [n.lineno for t in (trees["chaining"], trees["devsim"], trees["blanket"]) for n in ast.walk(t) if isinstance(n, ast.keyword) and n.arg == "inherited_domain"]
last = [n.lineno for k in ("chaining", "devsim") for n in ast.walk(trees[k]) if isinstance(n, ast.Attribute) and n.attr == "last_domain"]
imp_calls = [n.lineno for n in ast.walk(trees["devsim"]) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "import_process_result"]
report(not kw and not last and not imp_calls,
       f"3. no `inherited_domain=` keyword, no `.last_domain` use in the chaining/devsim tests and no call of import_process_result() on the refused result: "
       f"inherited_domain={kw}, last_domain={last}, import_process_result calls={imp_calls}")

# 4 -- every positive-time request is really positive ---------------------------------------------------------------------------------------
vals = []
for k, p in TESTS.items():
    vals += [(k, float(v)) for v in re.findall(r'"time_hours":\s*([0-9.eE+-]+)', read(p))]
    vals += [(k, float(v)) for v in re.findall(r"ox_time_var\.set\(([0-9.eE+-]+)\)", read(p))]
report(vals and all(v > 0 for _, v in vals), f"4. every time_hours / ox_time literal is > 0 (no positive request was turned into 0 h): {vals}")

# 5 -- solver traps + reason codes ---------------------------------------------------------------------------------------------------------------
need = ("vps.Process", "vps.Oxidation", "setInitialOxideThickness", "LocosOxidation._build_locos_geometry")
res = {k: all(n in read(p) for n in need) and "calibrate_trap()" in read(p) and "assert_not_entered" in read(p) and "SolverTrap()" in read(p) for k, p in TESTS.items()}
codes = {"blanket": 'EXPECTED_REASON = "OXIDATION_CAPABILITY_PROOF_MISSING"' in read(TESTS["blanket"]),
         "chaining": 'EXPECTED_REASON = "LOCOS_CAPABILITY_PROOF_MISSING"' in read(TESTS["chaining"]),
         "devsim": 'EXPECTED_REASON = "LOCOS_CAPABILITY_PROOF_MISSING"' in read(TESTS["devsim"])}
report(all(res.values()) and all(codes.values()), f"5. four-path solver trap defined, calibrated and asserted in each file: {res}; exact reason code pinned per model: {codes}")

# 6 -- every guard names an expected reason -------------------------------------------------------------------------------------------------------
counts, ok6 = {}, True
for k, t in trees.items():
    calls = [n for n in ast.walk(t) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "expect_fail"]
    counts[k] = len(calls)
    ok6 &= all(len(c.args) >= 3 for c in calls)
report(ok6 and all(v >= 7 for v in counts.values()),
       f"6. expect_fail(check, label, expected) always has an expected reason; guards per file (>= 7: the 7 shared categories -- reason swap, identity, "
       f"MODELLED, SiO2, Mask, trap called, plus the file's own flow/DevSim/deposition guards): {counts}")

# 7 -- flow sentinel and DevSim observers exist and are calibrated ------------------------------------------------------------------------
c = read(TESTS["chaining"])
d = read(TESTS["devsim"])
s7 = all(x in c for x in ("class SentinelStep(ProcessStep)", "calibrate_sentinel()", "assert_sentinel_untouched", "lookups", "constructed", "run_flow(", "registry._REGISTRY.pop"))
o7 = all(x in d for x in ("class DevsimObserver", "calibrate_observer()", "solve_calls", "doping_writes", "DOPING_MODELS", "import_calls", "UnsupportedDopingState"))
report(s7 and o7, f"7. the flow sentinel (lookups/constructor/run counted, calibrated, unregistered afterwards) and the DevSim observers (solve, doping writes, import) are present: sentinel={s7}, devsim={o7}")

# 8 -- the supported deposition is a separate, independently callable function that asserts a real film ---------------------------------------
b = trees["blanket"]
fn = {n.name for n in b.body if isinstance(n, ast.FunctionDef)}
b_src = read(TESTS["blanket"])
report({"test_positive_time_oxidation_contract", "test_blanket_deposition_supported"} <= fn and "check_deposition_film(geom)" in b_src and "EXPORT_TOL" in b_src,
       f"8. test_blanket_deposition_supported() is a separate function that checks a real deposited film via check_deposition_film (Si+SiO2, no Mask, film on Si, thickness > 0.1 x grid): {sorted(fn)}")

# 9 -- scope -------------------------------------------------------------------------------------------------------------------------------------------------
before = {}
for line in (AUDIT / "raw/production_sha256_start.txt").read_text(encoding="utf-8").splitlines():
    if line.strip():
        h, rel = line.split("  ", 1)
        before[rel.strip()] = h.lower()
changed = [rel for rel, h in before.items() if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != h]
new_prod = sorted({str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.joinpath("tcad").rglob("*.py")} - set(before) - {"tcad_2d_stagewise.py"})
report(not changed and not new_prod, f"9a. production ({len(before)} files: tcad/**/*.py + tcad_2d_stagewise.py) unchanged: changed={changed}, new={new_prod}")
claude_before = (AUDIT / "raw/claude_md_sha256_start.txt").read_text().split()[0].lower()
report(hashlib.sha256((ROOT / "CLAUDE.md").read_bytes()).hexdigest() == claude_before, "9b. CLAUDE.md is byte-identical to its state at the start of the batch")
start = datetime.datetime.fromisoformat((AUDIT / "raw/start_timestamp.txt").read_text().strip()).timestamp()
touched = []
for p in ROOT.rglob("*"):
    if not p.is_file() or ".git" in p.parts or ".serena" in p.parts or "__pycache__" in p.parts or AUDIT in p.parents or p.suffix == ".pyc":
        continue
    try:
        if p.stat().st_mtime > start:
            touched.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    except OSError:
        pass
outside = sorted(set(touched) - ALLOWED)
report(not outside, f"9c. files modified since the start of the batch: {sorted(set(touched))}; outside the three allowed tests: {outside}")

print()
print("ALL STATIC CHECKS PASS" if not failed else f"{len(failed)} STATIC CHECK(S) FAILED")
sys.exit(1 if failed else 0)
