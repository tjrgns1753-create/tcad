"""Read-only E6M before/after evidence check; stdout only, no engine imports.

Run from the repository root with Python -B. Original files are never changed.
"""
import ast
import copy
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

root = Path.cwd()
rel = "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
sys.path.insert(0, str(root / rel / "scripts"))
import judge_e6m as J
import e6m_metrics as M

base = "98ba83574ddb3ede0f743b3ab38f369836e65b54"
p = root / rel / "data/remote_run_36904995835/remote-run-32/outputs/e6m_out"
k = root / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
e = root / "docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json"
r = json.loads((p / "pn_2d_consistency.json").read_text())
z = np.load(p / "arrays.npz")
kr = json.loads((k / "pn_1d_diagnostic.json").read_text())
kz = np.load(k / "states.npz")
er = json.loads(e.read_text())


class Arr(dict):
    @property
    def files(self):
        return list(self)


def compact(result):
    return {key: v["verdict"] for key, v in result.items() if isinstance(v, dict) and "verdict" in v}


def old_module(name, filename):
    mod = types.ModuleType(name)
    mod.__file__ = str(root / rel / "scripts" / filename)
    source = subprocess.check_output(["git", "show", f"{base}:{rel}/scripts/{filename}"]).decode("utf-8")
    exec(compile(source, mod.__file__, "exec"), mod.__dict__)
    return mod


oldm = old_module("e6m_metrics", "e6m_metrics.py")
sys.modules["e6m_metrics"] = oldm
try:
    oldj = old_module("old_judge", "judge_e6m.py")
finally:
    sys.modules["e6m_metrics"] = M
new = J.judge(r, z, kr, kz, er)
out = {"base_sha": base, "original_old": compact(oldj.judge(r, z, kr, kz, er)),
       "original_new": compact(new), "canonical_evidence": new["canonical_evidence"],
       "original_array_problems": {f"{lv}_{d}": M.array_contract(z, lv, d) for lv in M.LEVELS for d in M.DIRECTIONS},
       "counterexamples": {}, "hashes": {}}
for case in ("plan_hash", "reverse_nodevolume_zero", "reverse_doping_zero", "canonical_unresolved"):
    rr = copy.deepcopy(r)
    aa = Arr({key: z[key].copy() for key in z.files})
    if case == "plan_hash":
        rr["plan_sha256"] = "f" * 64
    elif case == "reverse_nodevolume_zero":
        aa["L2__rev__NodeVolume"][:] = 0
    elif case == "reverse_doping_zero":
        for key in ("Donors", "Acceptors", "NetDoping"):
            aa["L2__rev__" + key][:] = 0
    else:
        rr["levels"]["L2"]["audit_doping"]["canonical_unresolved"] = 1
    out["counterexamples"][case] = {"before": compact(oldj.judge(rr, aa, kr, kz, er)), "after": compact(J.judge(rr, aa, kr, kz, er))}
for path in (p / "pn_2d_consistency.json", p / "arrays.npz", k / "pn_1d_diagnostic.json", k / "states.npz", root / rel / "PLAN.md"):
    out["hashes"][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for path in (root / rel / "scripts/e6m_metrics.py", root / rel / "scripts/judge_e6m.py",
             root / "tests/integration/test_pn_2d_1d_consistency_real.py", root / "tests/unit/test_e6m_judge_mock.py"):
    ast.parse(path.read_text(encoding="utf-8"))
    assert b"\r" not in path.read_bytes(), path
assert not {"devsim", "viennaps", "viennals"}.intersection(sys.modules)
out.update(engine_imports=0, solves=0)
print(json.dumps(out, ensure_ascii=False, indent=2))
