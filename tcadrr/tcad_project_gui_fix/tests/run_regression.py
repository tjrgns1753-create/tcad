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


def _run_one(path: Path) -> tuple[str, float, str]:
    start = time.time()
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - start
    if proc.returncode == 0:
        return "PASS", elapsed, ""
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
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
        if status == "FAIL":
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
            if status == "FAIL":
                print(tail)

    print()
    print("=== Summary ===")
    passed = sum(1 for _, s, _, _ in results if s == "PASS")
    failed = sum(1 for _, s, _, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _, _ in results if s == "SKIP")
    for name, status, elapsed, _ in results:
        print(f"  {status:5s} {name}")
    print(f"{passed} passed, {failed} failed, {skipped} skipped")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
