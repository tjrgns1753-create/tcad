"""Batch 5 (resumed round) static checks. Read-only; repo root derived from this file's location.

These are text / AST / file-time scans. They state what is written in the files and which files changed; they do NOT prove
that the GUI behaves correctly (the real-GUI runs do) and they are not a physical-correctness argument."""
import ast
import datetime
import hashlib
import re
import sys
import tkinter.messagebox as tkmb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tcad_2d_stagewise.py"
TARGET = ROOT / "tests/integration/test_gui_headless_no_modal_hang_real.py"
ALLOWED = {"tcad_2d_stagewise.py", "tests/integration/test_gui_headless_no_modal_hang_real.py",
           "tests/integration/test_oxidation_positive_time_unsupported_real.py"}
failed = []


def read(p):
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def report(ok, text):
    print(("PASS  " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


gui_tree = ast.parse(read(GUI))
run_ox = [n for n in ast.walk(gui_tree) if isinstance(n, ast.FunctionDef) and n.name == "run_oxidation"]
assert len(run_ox) == 1
fn = run_ox[0]


def strings_in(nodes):
    out = []
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.append(n.value)
    return " ".join(out)


# 1 -- "simulation complete" only in the physical-success branch -------------------------------------------------------
chain = next((s for s in fn.body if isinstance(s, ast.If) and isinstance(s.test, ast.Name) and s.test.id == "fresh_wafer" and s.orelse
              and s.lineno > 3200), None)
ok1, detail1 = False, "notify chain not found"
if chain is not None:
    elif_ = chain.orelse[0] if isinstance(chain.orelse[0], ast.If) else None
    if elif_ is not None and isinstance(elif_.test, ast.Name) and elif_.test.id == "inherited_identity":
        fresh_txt, ident_txt, real_txt = strings_in(chain.body), strings_in(elif_.body), strings_in(elif_.orelse)
        phrases = ("simulation complete", "oxidation complete", "growth complete")
        ok1 = (not any(p in fresh_txt.lower() for p in phrases) and not any(p in ident_txt.lower() for p in phrases)
               and "simulation complete" in real_txt.lower() and "no oxidation performed" in fresh_txt.lower()
               and "no oxidation performed" in ident_txt.lower() and fresh_txt != ident_txt)
        detail1 = "fresh and identity branches have no success phrase and differ; the else (physical) branch has 'simulation complete'"
total = strings_in([fn]).lower().count("simulation complete")
report(ok1 and total == 1, f"1. run_oxidation(): zero-duration branches contain no 'simulation/oxidation/growth complete'; the one 'simulation complete' "
       f"string ({total} in the function) sits in the else branch of `if fresh_wafer / elif inherited_identity`: {detail1}")

# 2 -- the marker call in run_oxidation ---------------------------------------------------------------------------------
marks = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_mark_stage_done"]
parents = {}
for p in ast.walk(fn):
    for c in ast.iter_child_nodes(p):
        parents[c] = p
guarded = []
for m in marks:
    anc, node = [], m
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.If):
            anc.append(node)
    guarded.append(any(isinstance(a.test, ast.UnaryOp) and isinstance(a.test.op, ast.Not) and getattr(a.test.operand, "id", "") == "identity" for a in anc))
ident_assign = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "identity"]
ident_ok = bool(ident_assign) and ast.unparse(ident_assign[0].value) == "inherited_identity or fresh_wafer"
report(len(marks) == 1 and all(guarded) and ident_ok,
       f"2. run_oxidation() calls _mark_stage_done {len(marks)} time(s), guarded by `if not identity:` ({guarded}), with "
       f"identity == `inherited_identity or fresh_wafer` -> a fresh materialization or an inherited identity cannot reach it "
       f"(the only remaining call is the physical, supported-oxidation path)")

# 3 -- unsupported ----------------------------------------------------------------------------------------------------------
unsupported_if = [n for n in fn.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "unsupported" and n.lineno > 3150]
uns_marks = sum(1 for u in unsupported_if for n in ast.walk(u) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_mark_stage_done")
uns_returns = all(isinstance(u.body[-1], ast.Return) for u in unsupported_if)
after_unsupported = all(m.lineno > u.end_lineno for m in marks for u in unsupported_if)
report(bool(unsupported_if) and uns_marks == 0 and uns_returns and after_unsupported,
       f"3. the unsupported branch makes {uns_marks} marker calls and returns before the only marker call ({len(unsupported_if)} branch(es), "
       f"returns: {uns_returns}, marker call after it: {after_unsupported})")

# 4 -- worker-failure wording ---------------------------------------------------------------------------------------------
t_src = read(TARGET)
claim = re.compile(r"ViennaPS (solver )?(exception|RuntimeError|failure)|physical simulation failure|solver (exception|failure)", re.I)
neg = re.compile(r"\b(not|never|neither|nor|no|without)\b", re.I)
hits4 = [(i, l.strip()[:100]) for i, l in enumerate(t_src.splitlines(), 1) if claim.search(l) and not neg.search(l)]
report(not hits4 and "wafer-state/recipe VALIDATION failure" in t_src,
       f"4. the worker-failure scenario is never described as a ViennaPS solver exception / physical simulation failure without a negation, "
       f"and is named a worker-side wafer-state/recipe validation failure: un-negated claims = {hits4}")

# 5 -- Bosch: no exact hash / depth assertion, no seed, no retry ---------------------------------------------------------------
t_tree = ast.parse(t_src)
funcs = {n.name: n for n in t_tree.body if isinstance(n, ast.FunctionDef)}
def numeric_literals(func):
    """Numeric literals of `func` that are not the digits argument of a display `round(...)` call."""
    skip = set()
    for c in ast.walk(func):
        if isinstance(c, ast.Call) and getattr(c.func, "attr", getattr(c.func, "id", "")) == "round":
            skip.update(id(a) for a in c.args[1:])
    return sorted({n.value for n in ast.walk(func) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                   and not isinstance(n.value, bool) and id(n) not in skip})


numeric = {name: numeric_literals(funcs[name]) for name in ("check_bosch_lowered", "check_deposition_film")}
hex_literals = re.findall(r"['\"][0-9a-f]{12,64}['\"]", t_src)
sha_compares = [n.lineno for n in ast.walk(t_tree) if isinstance(n, ast.Compare) and any(getattr(x, "attr", "") == "sha256" for x in ast.walk(n))
                and any(isinstance(c, ast.Constant) for c in n.comparators)]
seeds = re.findall(r"random[._]seed|setRandomSeed|\bseed\s*=|\bretry\b|\bfor attempt\b|while True", t_src)
report(not hex_literals and not sha_compares and not seeds and all(all(v in (0, 1, 2, 3) for v in vs) for vs in numeric.values()),
       f"5. no exact mesh-hash literal or comparison, no seed/retry, and the Bosch/deposition checks compare only against the named bound EXPORT_TOL "
       f"(the only numeric literals inside them are 0-3, i.e. bbox/array indices and zero; found: {numeric}; hex literals {hex_literals}; hash comparisons {sha_compares}; seeds/retries {seeds})")

# 6 -- the trap covers every blocking messagebox function -----------------------------------------------------------------------
m = re.search(r"BLOCKING = \(([^)]*)\)", t_src, re.S)
listed = sorted(re.findall(r'"(\w+)"', m.group(1))) if m else []
exposed = sorted(n for n in dir(tkmb) if n.startswith(("show", "ask")))
report(listed == exposed and len(listed) == 8 and "assert exposed == sorted(BLOCKING)" in t_src,
       f"6. the trapped list equals the {len(exposed)} show*/ask* functions this Python's tkinter.messagebox exposes {exposed}; "
       f"the test also asserts that equality at run time")

# 7 -- scope -------------------------------------------------------------------------------------------------------------------
patch = (AUDIT / "raw/production_diff_tcad_2d_stagewise.patch").read_text(encoding="utf-8")
hunks = re.findall(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", patch, re.M)
changed_lines, ln = [], 0
for row in patch.splitlines():
    if row.startswith("@@"):
        ln = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", row).group(1))
    elif row.startswith(("---", "+++")):
        continue
    elif row.startswith("+"):
        changed_lines.append(ln)
        ln += 1
    elif row.startswith("-"):
        changed_lines.append(ln)          # a deletion sits at the current new-file position
    else:
        ln += 1
inside = bool(changed_lines) and all(fn.lineno <= x <= fn.end_lineno for x in changed_lines)
report(inside, f"7a. this round's edits to tcad_2d_stagewise.py: {len(hunks)} hunk(s), changed lines {min(changed_lines)}-{max(changed_lines)} "
       f"({len(changed_lines)} lines), all inside run_oxidation() (lines {fn.lineno}-{fn.end_lineno}); hunk context lines are not counted")
before = {}
for line in (AUDIT / "raw/production_sha256_start.txt").read_text(encoding="utf-8").splitlines():
    if line.strip():
        h, rel = line.split("  ", 1)
        before[rel.strip()] = h.lower()
changed = [rel for rel, h in before.items() if rel != "tcad_2d_stagewise.py" and hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != h]
new_prod = sorted({str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.joinpath("tcad").rglob("*.py")} - set(before))
report(not changed and not new_prod, f"7b. the other {len(before) - 1} production files (tcad/**/*.py) are unchanged since the start of Batch 5: changed={changed}, new={new_prod}")
start = datetime.datetime.fromisoformat((AUDIT / "raw/round2_start_timestamp.txt").read_text().strip()).timestamp()
touched = []
for p in ROOT.rglob("*"):
    if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts or AUDIT in p.parents or p.suffix == ".pyc":
        continue
    try:
        if p.stat().st_mtime > start:
            touched.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    except OSError:
        pass
outside = sorted(set(touched) - ALLOWED)
report(not outside, f"7c. files modified after the start of this round: {sorted(set(touched))}; outside the allowed list: {outside}")

print()
print("ALL STATIC CHECKS PASS" if not failed else f"{len(failed)} STATIC CHECK(S) FAILED")
sys.exit(1 if failed else 0)
