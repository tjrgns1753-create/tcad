#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOCOS positive-time request: the fail-closed CAPABILITY CONTRACT, through the real
production entry point (registry -> LocosOxidation.run(), tcad/process/oxidation/locos.py),
real ViennaPS 4.6.2.

WHAT THIS TEST PINS NOW (Batch 6). A positive-time LOCOS request is UNSUPPORTED_BY_MODEL:
production blocks it before any solver call and returns

    physics_status.resolution == "UNSUPPORTED_BY_MODEL"
    physics_status.reason_code == state_transition.reason == "LOCOS_CAPABILITY_PROOF_MISSING"
    state_transition.kind      == "unsupported"

with NO oxidation number of any kind: no oxide growth, no field-oxide plateau, no pad-only
height, no taper, no bird's-beak length, no mask retention. The geometry that comes back for a
fresh request is the recipe's virgin Si wafer and nothing else (no SiO2, no Mask) and it is the
LAST-KNOWN geometry, never an oxidation result. This test computes and prints none of those
numbers, and it forces (not infers) that the oxidation paths were never entered: `vps.Process`,
`vps.Oxidation` (construction and `setInitialOxideThickness`) and
`LocosOxidation._build_locos_geometry` are trapped and counted.

WHAT IS NOT PINNED ANY MORE. This file used to measure a field-oxide plateau, an under-mask pad-only
height, a mask-edge intermediate height and a taper length from a positive-time LOCOS run, and to
call that a "confirmed" bird's beak. Those results were a HISTORICAL investigation
(docs/investigation_log.md, "LOCOS bird's-beak shape"; and the pre-2026-09-18 model state). They are
NOT a supported regression contract of the current backend: the backend no longer computes them.
Nothing here says the current backend reproduces them, and none of those numbers may be quoted as a
current result.

The reason code is pinned per model as production returns it: LOCOS -> LOCOS_CAPABILITY_PROOF_MISSING
(locos.py); thermal oxidation returns OXIDATION_CAPABILITY_PROOF_MISSING (see the other Batch 6
tests). Fail-closed false-green guards at the end prove each check fails, for its own reason, when
its subject is broken. No skip, no xfail, no swallowed exception.
"""

import copy
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401 -- registers "locos"
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.process.oxidation.locos import LocosOxidation

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
MODULE = viennaps_session.require_viennaps()

# The historical bird's-beak recipe class (pad 0.1 um, 0.5 h, 1000 C dry, grid 0.05): it is used here ONLY as the
# REQUEST that must be refused; nothing about its historical outcome is asserted.
RECIPE = {
    "grid_delta_um": 0.05,
    "x_extent_um": 3.0,
    "y_extent_um": 2.0,
    "mask_left_um": 1.0,
    "mask_right_um": 2.0,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.5,
    "mask_material": "Mask",
    "pad_oxide_thickness_um": 0.1,
}
EXPECTED_REASON = "LOCOS_CAPABILITY_PROOF_MISSING"      # what locos.py returns for a positive-time request
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}


# ------------------------------------------------------------------------------------------ solver-call traps
class SolverTrap:
    """Replaces the forbidden oxidation paths with recorders that ALSO raise, so a regression fails loudly; the counts are
    kept separately so a call swallowed by a broad `except` is still caught by `assert_not_entered`."""

    FORBIDDEN = ("vps.Process", "vps.Oxidation", "setInitialOxideThickness", "LocosOxidation._build_locos_geometry")

    def __init__(self):
        self.calls = []
        self._stack = None

    def __enter__(self):
        trap = self

        def process(*a, **k):
            trap.calls.append("vps.Process")
            raise AssertionError("vps.Process() called on a positive-time request")

        class OxidationModel:
            def __init__(self, *a, **k):
                trap.calls.append("vps.Oxidation")
                raise AssertionError("vps.Oxidation() constructed on a positive-time request")

            def setInitialOxideThickness(self, *a, **k):
                trap.calls.append("setInitialOxideThickness")
                raise AssertionError("setInitialOxideThickness() called on a positive-time request")

        def build(*a, **k):
            trap.calls.append("LocosOxidation._build_locos_geometry")
            raise AssertionError("LocosOxidation._build_locos_geometry() called on a positive-time request")

        self._stack = ExitStack()
        self._stack.enter_context(patch.object(MODULE, "Process", process))
        self._stack.enter_context(patch.object(MODULE, "Oxidation", OxidationModel))
        self._stack.enter_context(patch.object(LocosOxidation, "_build_locos_geometry", build))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    def assert_not_entered(self, where):
        if self.calls:
            raise AssertionError(f"{where}: solver/oxidation path was entered: {self.calls}")


def calibrate_trap():
    """Each trapped path, called directly, must be recorded and raise: a trap that never fires proves nothing."""
    with SolverTrap() as trap:
        for label, call in (
            ("vps.Process", lambda: MODULE.Process()),
            ("vps.Oxidation", lambda: MODULE.Oxidation()),
            ("setInitialOxideThickness", lambda: MODULE.Oxidation.setInitialOxideThickness(None, 0.1)),
            ("LocosOxidation._build_locos_geometry", lambda: LocosOxidation()._build_locos_geometry({}, MODULE)),
        ):
            try:
                call()
            except AssertionError:
                continue
            raise AssertionError(f"the trap for {label} did not fire")
        assert trap.calls == list(SolverTrap.FORBIDDEN), trap.calls


# ------------------------------------------------------------------------------------------ contract checks
def mesh_materials(path):
    """Exact sorted material names present as triangles in an exported mesh."""
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type == "triangle":
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(MODULE.Material(t)).split("'")[1] for t in tags)


def check_unsupported(result, where):
    """UNSUPPORTED_BY_MODEL / exact reason / kind 'unsupported' -- and nothing that looks like an oxidation number."""
    assert set(result) == RESULT_KEYS, f"{where}: unexpected result keys {sorted(result)}"
    status, transition = result["physics_status"], result["state_transition"]
    if transition.get("kind") != "unsupported":
        raise AssertionError(f"{where}: state_transition.kind is {transition.get('kind')!r}, expected 'unsupported': {transition}")
    if status.get("resolution") != "UNSUPPORTED_BY_MODEL":
        raise AssertionError(f"{where}: physics_status.resolution is {status.get('resolution')!r}, expected 'UNSUPPORTED_BY_MODEL'")
    if status.get("reason_code") != EXPECTED_REASON or transition.get("reason") != EXPECTED_REASON:
        raise AssertionError(f"{where}: reason code is {status.get('reason_code')!r} / {transition.get('reason')!r}, expected {EXPECTED_REASON!r}")
    assert transition == {"kind": "unsupported", "category": "oxidation", "reason": EXPECTED_REASON}, f"{where}: {transition}"
    entries = status["entries"]
    assert len(entries) == 1 and entries[0]["parameter"] == "positive_time_oxidation" and entries[0]["resolution"] == "UNSUPPORTED_BY_MODEL", entries
    # no oxidation result of any kind was computed: the only numeric field is an ECHO of the request
    assert status["measured_min_oxide_um"] is None, f"{where}: an oxide thickness was reported: {status['measured_min_oxide_um']}"
    assert status["requested_initial_oxide_um"] == RECIPE["pad_oxide_thickness_um"], "requested_initial_oxide_um must echo the request"
    assert set(status) == {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}, sorted(status)


def check_fresh_materials(materials, where):
    """A fresh unsupported request returns the virgin Si wafer only -- no SiO2, no Mask, no pad oxide."""
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


# ------------------------------------------------------------------------------------------ false-green machinery
def expect_fail(check, label, expected):
    """A guard passes only if `check` raises AssertionError whose message contains `expected` (str, or a tuple of str that must
    all appear, or a predicate). A passing check is FALSE GREEN; another reason is WRONG FAILURE REASON."""
    try:
        check()
    except AssertionError as exc:
        message = str(exc)
        parts = (expected,) if isinstance(expected, str) else expected
        ok = expected(message) if callable(expected) else all(p in message for p in parts)
        if not ok:
            raise AssertionError(f"WRONG FAILURE REASON for {label!r}:\n  expected: {expected!r}\n  actual:   {message[:300]}") from exc
        print(f"    [guard OK] {label}: fails for the expected reason ({message.splitlines()[0][:90]})")
        return
    raise AssertionError(f"FALSE GREEN: the check did not fail when {label}")


def run_guards(result, materials, trap_probe):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    bad = copy.deepcopy(result)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "kind=identity"), "the transition kind is identity", "state_transition.kind is 'identity'")
    bad = copy.deepcopy(result)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "SOMETHING_ELSE"
    expect_fail(lambda: check_unsupported(bad, "wrong reason"), "the reason code is a different value", "reason code is 'SOMETHING_ELSE'")
    bad = copy.deepcopy(result)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED"), "the physics resolution is MODELLED", "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    bad = copy.deepcopy(result)
    bad["physics_status"]["measured_min_oxide_um"] = 0.11
    expect_fail(lambda: check_unsupported(bad, "number"), "an oxide thickness is reported", "an oxide thickness was reported")
    # a solver-path call that a broad `except` swallowed is still caught by the counter
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")


def main():
    step_cls = registry.get("oxidation", "locos")
    calibrate_trap()
    print("[1/4] solver traps calibrated: vps.Process, vps.Oxidation, setInitialOxideThickness and "
          "LocosOxidation._build_locos_geometry each fire when called directly")

    with tempfile.TemporaryDirectory() as tmp:
        with SolverTrap() as trap:
            result = step_cls().run(dict(RECIPE), tmp)
        trap.assert_not_entered("positive-time LOCOS request")
        print(f"[2/4] positive-time LOCOS request ({RECIPE['time_hours']} h, mask_material set) ran through the real entry point; "
              f"forbidden-call counts: {dict.fromkeys(SolverTrap.FORBIDDEN, 0)}")

        check_unsupported(result, "LOCOS positive-time")
        print(f"[3/4] state_transition = {result['state_transition']}")
        print(f"      physics_status: resolution={result['physics_status']['resolution']}, reason_code={result['physics_status']['reason_code']}, "
              f"measured_min_oxide_um={result['physics_status']['measured_min_oxide_um']}, "
              f"requested_initial_oxide_um={result['physics_status']['requested_initial_oxide_um']} (an echo of the request)")

        materials = mesh_materials(result["final_mesh"])
        check_fresh_materials(materials, "LOCOS positive-time")
        print(f"[4/4] returned geometry = last-known/virgin wafer only: materials {materials} (no SiO2, no Mask); "
              f"it is NOT an oxidation result and no oxide number was computed or is printed")

        run_guards(result, materials, None)

    print()
    print("LOCOS POSITIVE-TIME: UNSUPPORTED_BY_MODEL / LOCOS_CAPABILITY_PROOF_MISSING / kind 'unsupported', "
          "0 solver calls, virgin Si only, no oxidation number computed. "
          "(The old bird's-beak plateau/taper measurements are historical, not a current contract.)")


if __name__ == "__main__":
    main()
