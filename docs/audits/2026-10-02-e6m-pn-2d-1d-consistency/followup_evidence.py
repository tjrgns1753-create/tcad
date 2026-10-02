"""Read-only before/after canonical repro and original evidence comparison."""
import copy
import hashlib
import json
import runpy
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
REL = "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
BASE = "cdcb830ff07ef5e8f4938c111eaa18be546de6e7"
sys.path.insert(0, str(ROOT / REL / "scripts"))
import judge_e6m as J


def compact(result):
    return {k: v["verdict"] for k, v in result.items() if isinstance(v, dict) and "verdict" in v}


def main():
    old = types.ModuleType("judge_before_followup")
    old.__file__ = str(ROOT / REL / "scripts/judge_e6m.py")
    src = subprocess.check_output(["git", "show", BASE + ":" + REL + "/scripts/judge_e6m.py"]).decode("utf-8")
    exec(compile(src, old.__file__, "exec"), old.__dict__)
    test = runpy.run_path(str(ROOT / "tests/unit/test_e6m_judge_mock.py"))
    r = copy.deepcopy(test["RAW"])
    r["levels"]["L2"]["audit_doping"]["canonical_unresolved"] = 1
    args = (r, test["ARR"], test["E6K_JSON"], test["E6K_NPZ"], test["E6J"])
    before = compact(old.judge(*args, expected_plan_sha256="0" * 64))
    after = compact(J.judge(*args, expected_plan_sha256="0" * 64))
    assert all(v == "PASS" for v in before.values())
    assert after[J.CATEGORIES[1]] == "FAIL" and after[J.CATEGORIES[5]] == "BLOCKED_GATE_OR_AUDIT_DOPING"
    control = compact(J.judge(test["RAW"], *args[1:], expected_plan_sha256="0" * 64))
    assert all(v == "PASS" for v in control.values())
    data = ROOT / REL / "data/remote_run_36904995835/remote-run-32/outputs/e6m_out"
    original_raw = json.loads((data / "pn_2d_consistency.json").read_text())
    original_arrays = np.load(data / "arrays.npz")
    args = (original_raw, original_arrays, test["E6K_JSON"], test["E6K_NPZ"], test["E6J"])
    previous, current = compact(old.judge(*args)), J.judge(*args)
    assert previous == compact(current), "original evidence verdicts changed"
    stored = json.loads((ROOT / REL / "rejudge_support_result.json").read_text())
    hashes = {}
    for rel, digest in stored["hashes"].items():
        data = (ROOT / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert data == subprocess.check_output(["git", "show", BASE + ":" + rel])
        hashes[rel] = digest
    assert not any(n in sys.modules for n in ("devsim", "viennaps"))
    print(json.dumps({"base_sha": BASE, "conflict_before": before, "conflict_after": after,
                      "consistent_control": control, "original_before": previous, "original_after": compact(current),
                      "canonical_evidence": current["canonical_evidence"], "original_hashes_unchanged": hashes,
                      "engine_imports": 0, "real_solves": 0}, indent=2))


if __name__ == "__main__":
    main()
