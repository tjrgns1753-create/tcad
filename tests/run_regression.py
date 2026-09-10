#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Run the full tcad regression suite in one command:
    python3 tests/run_regression.py

tests/unit/ (mock-based, no real backend needed) always runs.
tests/integration/ (real ViennaPS + real DevSim) runs only if both
backends are actually importable — otherwise each integration test is
reported SKIPPED with the reason, rather than failing the whole suite,
so this script also works in a ViennaPS/DevSim-less environment (see
README.md's dependency boundary section).

Each test file is a standalone script with its own `if __name__ ==
"__main__": main()` (not pytest-based), so this runner just executes
each one as a subprocess and checks its exit code — matching how every
Phase 1-9 test was written and already verified to run.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = ROOT / "tests" / "unit"
INTEGRATION_DIR = ROOT / "tests" / "integration"


def _backends_available() -> tuple[bool, bool]:
    sys.path.insert(0, str(ROOT))
    try:
        from tcad.backends.viennaps import session as viennaps_session
        viennaps_ok = viennaps_session.is_available()
    except Exception:
        viennaps_ok = False
    try:
        from tcad.device.devsim import backend as devsim_backend
        devsim_ok = devsim_backend.is_available()
    except Exception:
        devsim_ok = False
    return viennaps_ok, devsim_ok


# Safety net only, not a fix: bounds a single hung test file to a
# known, finite wall-clock cost instead of blocking the whole suite
# forever. See docs/handoffs/gui-modal-hang-fix.md -- the real fix for
# the specific hang this was added alongside is the messagebox
# notifier gate in tcad_2d_stagewise.py; this timeout exists only so a
# FUTURE hang (this class or any other) shows up as a clearly labeled
# TIMEOUT result instead of silently stalling `run_regression.py`
# itself.
#
# A single flat timeout is wrong here: this project's own real
# DevSim/MOSFET solves are legitimately, not-hung, slow. This table is
# an explicit per-test-name budget, not a category guess -- every
# entry below names its own source:
DEFAULT_TIMEOUT_S = 900  # 15 min -- generous; nearly every test here finishes in well under 1 min
TIMEOUT_OVERRIDES_S = {
    # Measured directly in this project's own regression runs this
    # session (real ViennaPS + real DevSim, this repo, this commit):
    # 619.5s. 3600s leaves comfortable headroom above that.
    "test_device_fabrication_to_dc_sweep_real.py": 3600,
    # Same DevSim-device-lifecycle family as the above; not separately
    # timed this session, given the same 3600s budget on that basis.
    "test_device_lifecycle_repeat_real.py": 3600,
    # CLAUDE.md documents a real run of this exact test taking 1400+s
    # of genuine solving ("DevSim cross-solve sensitivity"). 3600s
    # comfortably covers the documented worst case.
    "test_mosfet_body_bias_real.py": 3600,
    # Same MOSFET/DevSim solve family as body_bias above; not
    # separately timed this session, given the same budget on that
    # basis.
    "test_mosfet_body_contact_real.py": 3600,
    "test_mosfet_gate_stack_cv_real.py": 3600,
    "test_mosfet_id_vds_real.py": 3600,
    "test_mosfet_id_vgs_real.py": 3600,
    "test_mosfet_vth_extraction_real.py": 3600,
    "test_robust_iv_sweep_real.py": 3600,
    # Reported (not independently reproduced this session) at ~3953s
    # of normal execution. This session's own two direct runs of this
    # exact test, this repo, this commit, measured 26.4s and 10.7s --
    # a 150x+ discrepancy neither reconciled nor explained by anything
    # in the test's own source (196 lines, one fixed grid_delta_um,
    # no sweep/loop that could plausibly account for it). Budgeted at
    # 5400s regardless, as a safety margin wide enough to cover BOTH
    # figures rather than adjudicate between them -- this value is a
    # margin, not a claim that 3953s was confirmed here. See
    # docs/handoffs/gui-modal-hang-fix.md for the full discrepancy
    # writeup; a future session that can reproduce a multi-thousand-
    # second run for this test should replace this comment with real
    # evidence of what made it slow.
    "test_auto_refine_from_doping_real.py": 5400,
}


def _timeout_for(path: Path) -> int:
    return TIMEOUT_OVERRIDES_S.get(path.name, DEFAULT_TIMEOUT_S)


def _selftest_timeout_table() -> None:
    """Pure-function check of the budget table itself -- fast (no
    subprocess, no real test execution), run every time this module is
    imported. Proves the *selection logic* is correct without paying
    the cost of actually running a multi-thousand-second test to
    completion just to exercise its own timeout branch."""
    assert _timeout_for(Path("test_auto_refine_from_doping_real.py")) >= 5400, (
        "test_auto_refine_from_doping_real.py must carry a >=5400s budget"
    )
    for name in (
        "test_device_fabrication_to_dc_sweep_real.py",
        "test_device_lifecycle_repeat_real.py",
        "test_mosfet_body_bias_real.py",
        "test_mosfet_body_contact_real.py",
        "test_mosfet_gate_stack_cv_real.py",
        "test_mosfet_id_vds_real.py",
        "test_mosfet_id_vgs_real.py",
        "test_mosfet_vth_extraction_real.py",
        "test_robust_iv_sweep_real.py",
    ):
        assert _timeout_for(Path(name)) > DEFAULT_TIMEOUT_S, (
            f"{name} is a known-heavy DevSim/MOSFET solve and must carry "
            f"a budget above DEFAULT_TIMEOUT_S"
        )
    assert _timeout_for(Path("test_some_ordinary_fast_test_real.py")) == DEFAULT_TIMEOUT_S, (
        "a test with no explicit override must fall back to DEFAULT_TIMEOUT_S"
    )


_selftest_timeout_table()


def _kill_tree_windows(pid: int) -> None:
    """Best-effort: kill `pid` and its full descendant tree via
    `taskkill /T`. This project's own real dispatch path (confirmed
    this investigation, see docs/handoffs/gui-modal-hang-fix.md) spawns
    a "venvlauncher" stub -> real-interpreter grandchild for EVERY
    subprocess call on this machine, and a `--worker` dispatch inside a
    test repeats that one level deeper again -- so killing only the
    immediate child (what a plain `Popen.kill()` does) can leave the
    actual real work still running. This is still only best-effort, not
    a guarantee: a process that has already detached from this tree, or
    one running under different privileges, can still survive it."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass  # best-effort cleanup; the TIMEOUT result itself is what matters


def _run_one(path: Path) -> tuple[str, float, str]:
    timeout = _timeout_for(path)
    start = time.time()
    proc = subprocess.Popen(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        _kill_tree_windows(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=15)
        except Exception:
            stdout, stderr = "", ""
        tail = "\n".join(((stdout or "") + (stderr or "")).strip().splitlines()[-15:])
        return "TIMEOUT", elapsed, (
            f"no result after {timeout}s -- process tree killed "
            f"(taskkill /F /T, best-effort, see docs/handoffs/"
            f"gui-modal-hang-fix.md); this bounds the hang, it does not "
            f"diagnose it\n{tail}"
        )
    elapsed = time.time() - start
    if proc.returncode == 0:
        return "PASS", elapsed, ""
    tail = "\n".join((stdout + stderr).strip().splitlines()[-15:])
    return "FAIL", elapsed, tail


def main() -> int:
    viennaps_ok, devsim_ok = _backends_available()
    print(f"ViennaPS available: {viennaps_ok}")
    print(f"DevSim available:   {devsim_ok}")
    print()

    results: list[tuple[str, str, float, str]] = []

    print("=== tests/unit (mock, always run) ===")
    for path in sorted(UNIT_DIR.glob("test_*.py")):
        status, elapsed, tail = _run_one(path)
        results.append((path.name, status, elapsed, tail))
        print(f"[{status}] {path.name} ({elapsed:.1f}s)")
        if status in ("FAIL", "TIMEOUT"):
            print(tail)

    print()
    print("=== tests/integration (real ViennaPS + real DevSim) ===")
    if not (viennaps_ok and devsim_ok):
        print("SKIPPED: both ViennaPS and DevSim must be installed to run integration tests.")
        print("Install with: pip install tcad[full]")
        for path in sorted(INTEGRATION_DIR.glob("test_*.py")):
            results.append((path.name, "SKIP", 0.0, ""))
            print(f"[SKIP] {path.name}")
    else:
        for path in sorted(INTEGRATION_DIR.glob("test_*.py")):
            status, elapsed, tail = _run_one(path)
            results.append((path.name, status, elapsed, tail))
            print(f"[{status}] {path.name} ({elapsed:.1f}s)")
            if status in ("FAIL", "TIMEOUT"):
                print(tail)

    print()
    print("=== Summary ===")
    passed = sum(1 for _, s, _, _ in results if s == "PASS")
    failed = sum(1 for _, s, _, _ in results if s == "FAIL")
    timed_out = sum(1 for _, s, _, _ in results if s == "TIMEOUT")
    skipped = sum(1 for _, s, _, _ in results if s == "SKIP")
    for name, status, elapsed, _ in results:
        print(f"  {status:7s} {name}")
    print(f"{passed} passed, {failed} failed, {timed_out} timed out, {skipped} skipped")

    return 1 if (failed or timed_out) else 0


if __name__ == "__main__":
    sys.exit(main())
