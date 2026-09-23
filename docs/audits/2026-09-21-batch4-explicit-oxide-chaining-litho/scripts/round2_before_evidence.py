"""Batch 4 round 2 -- code evidence for the two helper defects, taken from the PRE-round-2 helper code.

(1) `assert_fails` accepted ANY AssertionError. The function below is copied VERBATIM from the pre-round-2 helper; it is
    fed a check that fails for an UNRELATED reason and it still reports "sensitivity OK".
(2) `copies_loaded` stored `id(domain)` only. A real domain loaded from the saved `.vpsd` and freed gives its id back to the
    allocator; the loop below counts how often a later, genuinely different domain object receives an id already seen.
Read-only; repo root derived from this file's location.
"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "integration"))
warnings.simplefilter("ignore")


# ---- (1) verbatim copy of the pre-round-2 helper function ---------------------------------------------------------------
def old_assert_fails(check, label: str) -> None:
    """False-green guard: `check` MUST raise AssertionError when its subject is broken."""
    try:
        check()
    except AssertionError as exc:
        print(f"    [sensitivity OK] {label}: fails as it must  ({str(exc).splitlines()[0][:110]})")
        return
    raise AssertionError(f"FALSE GREEN: the check did not fail when {label}")


def unrelated_failure():
    assert False, "some completely unrelated assertion (a typo'd variable, a wrong column count, a stale fixture...)"


print("== (1) pre-round-2 assert_fails, given an UNRELATED AssertionError while claiming 'the Metal etch rate is 0 (thinning)':")
old_assert_fails(unrelated_failure, "the Metal etch rate is 0 (thinning)")
print("   -> accepted as a passing sensitivity check although it says nothing about the Metal etch rate")

# ---- (2) id() reuse of freed real domains ---------------------------------------------------------------------------------
import _explicit_chain_fixture as fx  # noqa: E402
from tcad.backends.viennaps import session  # noqa: E402

print("\n== (2) id(domain) recorded for real domains loaded from ONE saved .vpsd, each freed before the next load:")
with tempfile.TemporaryDirectory() as tmp:
    st = fx.build_explicit_chain_state(tmp, x_extent_um=8.0, y_extent_um=5.0, silicon_depth_um=4.0, oxide_top_um=0.4, grid_delta_um=0.1)
    ids = []
    for _ in range(40):
        d = session.load_domain_state(st.vpsd_path)
        ids.append(id(d))
        del d
    distinct = len(set(ids))
    print(f"   40 loads, {distinct} distinct ids; {40 - distinct} loads received an id that an earlier (already freed) domain had")
    print("   -> an id-only list cannot tell 'same object handed out twice' from 'new object at a recycled address'"
          if distinct < 40 else
          "   -> no recycling observed in this run (the exposure remains: nothing in the id-only design prevents it)")
    # what the pre-round-2 test flow did: run_steps_from_state returned and dropped its domain, so ids were recorded of dead objects
    old_style = []
    for _ in range(5):
        d = st.load_independent_copy()
        del d
    print(f"   pre-round-2 helper after 5 dropped loads: copies_loaded={st.copies_loaded} (ints only; the objects are already gone)")
