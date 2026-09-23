"""Batch 4 round 2 -- exercises the new `assert_fails(check, label, expected)` contract on the real helper (no ViennaPS needed).

Each row states the input, the required outcome, and the observed outcome. Exit code 1 if any row differs."""
import os
import sys
import io
import contextlib
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

import _explicit_chain_fixture as fx


def boom(msg):
    def f():
        assert False, msg
    return f


def value_error():
    raise ValueError("not an assertion")


def passes():
    return None


rows = [
    ("check succeeds -> FALSE GREEN", lambda: fx.assert_fails(passes, "x", "anything"), AssertionError, "FALSE GREEN"),
    ("AssertionError, reason does not match -> WRONG FAILURE REASON", lambda: fx.assert_fails(boom("unrelated"), "x", "the Metal rate"),
     AssertionError, "WRONG FAILURE REASON"),
    ("tuple: only one of two substrings present -> WRONG FAILURE REASON", lambda: fx.assert_fails(boom("alpha only"), "x", ("alpha", "beta")),
     AssertionError, "WRONG FAILURE REASON"),
    ("predicate returns False -> WRONG FAILURE REASON", lambda: fx.assert_fails(boom("alpha"), "x", lambda m: "beta" in m),
     AssertionError, "WRONG FAILURE REASON"),
    ("other exception type propagates unchanged", lambda: fx.assert_fails(value_error, "x", "not an assertion"), ValueError, "not an assertion"),
    ("no expected reason (old 2-argument form) -> TypeError", lambda: fx.assert_fails(boom("a"), "x"), TypeError, None),
    ("empty expected string -> TypeError", lambda: fx.assert_fails(boom("a"), "x", ""), TypeError, "non-empty"),
    ("empty expected tuple -> TypeError", lambda: fx.assert_fails(boom("a"), "x", ()), TypeError, "non-empty"),
    ("matching substring -> passes", lambda: fx.assert_fails(boom("the Metal rate must be negative"), "x", "Metal rate must"), None, None),
    ("tuple, all present -> passes", lambda: fx.assert_fails(boom("alpha and beta"), "x", ("alpha", "beta")), None, None),
    ("predicate True -> passes", lambda: fx.assert_fails(boom("alpha"), "x", lambda m: "alpha" in m), None, None),
]
bad = 0
for name, call, exc_type, needle in rows:
    buf = io.StringIO()
    got = None
    try:
        with contextlib.redirect_stdout(buf):
            call()
    except BaseException as e:  # noqa: BLE001 -- the point is to classify what came out
        got = e
    ok = (got is None) if exc_type is None else (type(got) is exc_type and (needle is None or needle in str(got)))
    bad += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {'no exception' if got is None else type(got).__name__}")
print("\nALL CONTRACT ROWS OK" if not bad else f"\n{bad} ROW(S) FAILED")
sys.exit(1 if bad else 0)
