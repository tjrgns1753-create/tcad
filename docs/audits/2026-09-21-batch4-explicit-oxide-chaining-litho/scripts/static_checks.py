"""Batch 4 static checks (prompt section 10). Read-only; repo root derived from this file's location
(<repo>/docs/audits/<audit>/scripts/static_checks.py). Prints one line per check and exits 1 if any fails.

What each check proves is stated with it; none of them proves physical correctness (the real-ViennaPS runs do).
"""
import ast
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parents[1]
T1 = ROOT / "tests/integration/test_gui_process_state_chaining_real.py"
T2 = ROOT / "tests/integration/test_litho_lifecycle_state_real.py"
HELPER = ROOT / "tests/integration/_explicit_chain_fixture.py"
TARGETS = (T1, T2)
failed = []


def read(p):
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def report(ok, text):
    print(("PASS  " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


# 1 -- positive-time oxidation recipes in the two target tests ---------------------------------------------------------
vals = []
for p in TARGETS:
    for m in re.finditer(r"time_hours['\"]?\s*[:=]\s*([0-9.eE+-]+)", read(p)):
        vals.append((p.name, float(m.group(1))))
report(all(v == 0.0 for _, v in vals) and len(vals) >= 1,
       f"1. every `time_hours` in the two target tests is 0.0 (zero-duration only): {vals}")
report(not any(re.search(r"oxidant.*\n.*time_hours['\"]?\s*[:=]\s*[1-9]", read(p)) for p in TARGETS), "1b. no positive-time oxidation recipe text")

# 2 -- the explicit oxide is never CALLED an oxidation / grown-oxide result ---------------------------------------------
phrases = re.compile(r"grown oxide|oxide growth|oxidation result|oxidation step|step 1 oxidation|Oxidation \(blanket|\bgrown\b|thermal oxide", re.I)
negation = re.compile(r"\b(not|NOT|never|neither|no|without|instead|used to|unsupported|UNSUPPORTED|nor|nothing|isn't|is not)\b|historical|was never", re.I)
unqualified = []
seen = 0
for p in TARGETS + (HELPER,):
    for i, line in enumerate(read(p).splitlines(), 1):
        if phrases.search(line):
            seen += 1
            if not negation.search(line):
                unqualified.append((p.name, i, line.strip()[:110]))
report(not unqualified, f"2. phrases that could name the explicit oxide a grown/oxidation result: {seen} mentions, all negated or historical; unqualified = {unqualified}")

# 3 -- arbitrary oxide-thickness subtraction / seed compensation --------------------------------------------------------
bad = re.compile(r"native.?oxide.{0,40}seed|seed.{0,40}native.?oxide|initial_oxide|setInitialOxideThickness|\bseed(ing|ed)?\b|oxide_thickness\s*[-+]?=|oxide_top[^\n]*-\s*[0-9]|thickness\s*-=", re.I)
hits = [(p.name, i, l.strip()[:100]) for p in TARGETS + (HELPER,) for i, l in enumerate(read(p).splitlines(), 1) if bad.search(l) and not negation.search(l)]
report(not hits, f"3. no oxide-thickness subtraction, seed compensation or native-oxide handling: {hits}")

# 4 -- numeric literals (potential magic tolerances) --------------------------------------------------------------------
def literals(p):
    tree = ast.parse(read(p))
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            doc.add(id(n.body[0].value))
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool) and id(n) not in doc:
            out.setdefault(n.value, []).append(n.lineno)
    return out

# every literal that takes part in a COMPARISON against a measured quantity, with the constant's name if it is one
MIGRATED = ("check_", "assert_", "_check_", "_c_columns", "_present", "_native_film_present", "_explicit_state", "_chain_base",
            "test_b2", "test_b3", "test_c_", "test_sensitivity", "c_steps", "main")


def in_migrated_code(path, node, functions):
    """Only what THIS batch wrote: the whole chaining test and helper, and the migrated B2/B3/C/sensitivity functions of the
    litho test (its A, A2 and B1 are unchanged input-geometry code)."""
    if path != T2:
        return True
    return any(fn.name.startswith(MIGRATED) and fn.lineno <= node.lineno <= fn.end_lineno for fn in functions)


tol_lines = []
for p in TARGETS + (HELPER,):
    tree = ast.parse(read(p))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and in_migrated_code(p, n, functions):
            for c in [n.left] + n.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool) and c.value not in (0, 1, 2, 3, 0.0):
                    tol_lines.append((p.name, n.lineno, c.value))
report(not tol_lines, f"4. in everything this batch wrote (the whole chaining test and helper; the migrated B2/B3/C/sensitivity code of the litho test; "
       f"A, A2, B1 are unchanged) no numeric literal other than 0/1/2/3 is compared against a measurement (tolerances come only from the "
       f"named derived helpers native_eps / native_request_tolerance / exported_tolerance / grid): {tol_lines}")
h = literals(HELPER)
print("      helper numeric literals (all with their derivation in the docstrings): " + ", ".join(f"{v!r}@{sorted(set(l))[:3]}" for v, l in sorted(h.items(), key=lambda kv: str(kv[0]))))

# 5 -- no unsupported -> identity/success conversion --------------------------------------------------------------------
conv = []
for p in TARGETS + (HELPER,):
    for i, line in enumerate(read(p).splitlines(), 1):
        code = line.strip()
        if code.startswith(("print(", "#")) or 'f"' in code:
            continue                                   # text that merely MENTIONS a transition is not an assignment
        if re.search(r"^[\w.\[\]'\"]*state_transition\w*\s*=(?!=)|\"kind\"\s*:\s*\"identity\"|^transition\s*=\s*\{|\.metadata\[.*\]\s*=(?!=)", code):
            conv.append((p.name, i, code[:100]))
report(not conv, f"5. the target tests and helper never construct or overwrite a state transition (they only read and assert it): {conv}")
reads = [(p.name, i) for p in TARGETS for i, l in enumerate(read(p).splitlines(), 1) if "unsupported" in l.lower() and "assert" in l.lower()]
print(f"      places that assert a step is NOT unsupported: {reads}")

# 7 -- assert_fails always names the reason it must fail for (round 2) --------------------------------------------------------
calls = []
for p in TARGETS:
    for n in ast.walk(ast.parse(read(p))):
        if isinstance(n, ast.Call) and (getattr(n.func, "attr", None) == "assert_fails" or getattr(n.func, "id", None) == "assert_fails"):
            calls.append((p.name, n.lineno, len(n.args) + len(n.keywords)))
two_arg = [c for c in calls if c[2] < 3]
report(len(calls) == 14 and not two_arg, f"7. every assert_fails() call supplies an expected reason (3 arguments): {len(calls)} calls found "
       f"(expected 14 = 7 chaining + 7 litho); calls with fewer than 3 arguments (the old 2-argument form): {two_arg}")
aliases = [(p.name, i) for p in TARGETS for i, l in enumerate(read(p).splitlines(), 1) if re.match(r"\s*assert_fails\s*=", l)]
print(f"      alias lines (`assert_fails = fx.assert_fails`, the same function): {aliases}")
htree = ast.parse(read(HELPER))
defn = [n for n in htree.body if isinstance(n, ast.FunctionDef) and n.name == "assert_fails"][0]
report([a.arg for a in defn.args.args] == ["check", "label", "expected"], f"7b. helper signature is assert_fails(check, label, expected): {[a.arg for a in defn.args.args]}")

# 8 -- domain identity: strong references, never ids alone ---------------------------------------------------------------------
ht = read(HELPER)
appends = [(p.name, i, l.strip()) for p in TARGETS + (HELPER,) for i, l in enumerate(read(p).splitlines(), 1) if re.search(r"copies_loaded\s*\.\s*append|copies_loaded\s*[+]?=(?!=)", l)]
cls = [n for n in htree.body if isinstance(n, ast.ClassDef) and n.name == "ExplicitChainState"][0]
prop = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "copies_loaded" and any(getattr(d, "id", "") == "property" for d in n.decorator_list)]
report(not appends and len(prop) == 1 and "self._domains.append(domain)" in ht and "domain is not previous" in ht
       and not re.search(r"copies_loaded\s*:\s*List\[int\]", ht),
       f"8. copies_loaded is a read-only property derived from the held domain objects; nothing stores integer ids in it; new domains are "
       f"compared with `is not` against every held one: stores of ids = {appends}, property definitions = {len(prop)}")

# 9 / 10 -- wording the evidence does not support ---------------------------------------------------------------------------------
report_path = AUDIT / "REPORT.md"
scan = list(TARGETS + (HELPER,)) + ([report_path] if report_path.exists() else [])
eps_claim = re.compile(r"hair off|never sits exactly|deliberate epsilon|intended epsilon|keeps? zero off|zero.{0,40}grid point|"
                       r"MakePlane[^\n]{0,120}epsilon|epsilon[^\n]{0,80}MakePlane|plane epsilon|places? a level-set plane", re.I)
hits9 = [(p.name, i, l.strip()[:90]) for p in scan for i, l in enumerate(read(p).splitlines(), 1) if eps_claim.search(l)]
report(not hits9, f"9. no unverified MakePlane/epsilon cause wording in {[p.name for p in scan]}: {hits9}")
clear_claim = re.compile(r"oxide gone|Si exposed|Si is exposed|silicon (is )?exposed|Si becomes exposed", re.I)
hits10 = [(p.name, i, l.strip()[:90]) for p in scan for i, l in enumerate(read(p).splitlines(), 1) if clear_claim.search(l)]
report(not hits10, f"10. no `oxide gone` / unconditional `Si exposed` wording in {[p.name for p in scan]}: {hits10}")
print("      NOTE: these checks are text/AST scans; they say what is written in the files, not that the physics is right.")

# 6 -- production unchanged ----------------------------------------------------------------------------------------------
before = {}
for line in (AUDIT / "raw/production_sha256_before.txt").read_text(encoding="utf-8").splitlines():
    if line.strip():
        h_, rel = line.split("  ", 1)
        before[rel.strip()] = h_.lower()
changed = [rel for rel, h_ in before.items() if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != h_]
missing = [rel for rel in before if not (ROOT / rel).exists()]
now_prod = {str(p.relative_to(ROOT)).replace("\\", "/") for p in list((ROOT / "tcad").rglob("*.py")) + [ROOT / "tcad_2d_stagewise.py"]}
added = sorted(now_prod - set(before))
report(not changed and not missing and not added, f"6. production (tcad/**/*.py + tcad_2d_stagewise.py): {len(before)} files hashed before; "
       f"changed={changed}, missing={missing}, new={added}")

print()
print("ALL STATIC CHECKS PASS" if not failed else f"{len(failed)} STATIC CHECK(S) FAILED")
sys.exit(1 if failed else 0)
