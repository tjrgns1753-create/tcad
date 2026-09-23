#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Positive-time thermal and LOCOS requests: fail-closed capability contract, plus ONE clearly labelled
construction-only geometry check. Real ViennaPS 4.6.2, real production entry points
(registry -> ThermalOxidation.run() / LocosOxidation.run()).

The file name is HISTORICAL and is kept on purpose (no rename in Batch 6). It used to be the regression
test for the LOCOS `contactMode=2` fix (tcad/process/oxidation/locos.py: ViennaPS's
OxidationMaskParameters defaults to contactMode=1 "oneway", which diverged for this project's geometry;
contactMode=2 "twoway" is what the official locosOxidation.py example uses) and for the pad-oxide-first
mask-retention fix, by growing oxide and measuring SiO2 area, Si consumption, window width and mask
retention after a positive-time LOCOS run.

WHAT THIS TEST VERIFIES NOW
  1. A positive-time request through EACH of ThermalOxidation and LocosOxidation is refused before any
     solver call, with
        physics_status.resolution == "UNSUPPORTED_BY_MODEL"
        physics_status.reason_code == state_transition.reason == <the model's reason code>
        state_transition.kind      == "unsupported"
     thermal -> OXIDATION_CAPABILITY_PROOF_MISSING, LOCOS -> LOCOS_CAPABILITY_PROOF_MISSING (as production
     returns them). No oxide number of any kind is reported; the geometry returned for a fresh request is
     the virgin Si wafer only (no SiO2, no Mask) and is the last-known geometry, not an oxidation result.
  2. Forced, not inferred: `vps.Process`, `vps.Oxidation` (construction and `setInitialOxideThickness`) and
     `LocosOxidation._build_locos_geometry` (the LOCOS growth-geometry builder) are trapped and counted; none
     of them is entered.
  3. CONSTRUCTION-ONLY: the plain trench-window geometry that `prepare_domain()` builds BEFORE any oxidation
     has the width the recipe asks for (mask_right_um - mask_left_um), for both classes. This is a check of
     mask/window geometry construction. It says nothing about oxidation, contactMode, oxide growth, Si
     consumption or mask retention, and it is not mixed with the request results above.

WHAT THIS TEST DOES NOT VERIFY (and no longer claims)
  * oxide growth, Si consumption, mask retention or post-oxidation window geometry -- the backend does not
    compute them for a positive-time request, so there is nothing real to check;
  * that contactMode=2 makes a LOCOS oxidation succeed -- the code that sets it is unreachable while the
    positive-time gate is closed. The historical contactMode / mask-retention results (docs/investigation_log.md,
    CLAUDE.md) are history, not a current regression contract.
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

import tcad.process.oxidation  # noqa: F401 -- registers the models
from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.process import registry
from tcad.process.oxidation.locos import LocosOxidation

assert session.is_available(), "ViennaPS must be installed for this test"
MODULE = session.require_viennaps()

BASE_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.01,        # the recipe that originally segfaulted -- now only a REQUEST that must be refused
}
MODELS = (
    # label, registry name, recipe extras, reason code production returns
    ("thermal (fin-style)", "thermal", {}, "OXIDATION_CAPABILITY_PROOF_MISSING"),
    ("LOCOS", "locos", {"mask_material": "Mask"}, "LOCOS_CAPABILITY_PROOF_MISSING"),
)
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}
STATUS_KEYS = {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}


# ------------------------------------------------------------------------------------------ solver-call traps
class SolverTrap:
    """Recorders that also raise: a regression fails loudly, and the counts catch a call a broad `except` swallowed."""

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


def check_unsupported(result, where, reason, recipe):
    assert set(result) == RESULT_KEYS, f"{where}: unexpected result keys {sorted(result)}"
    status, transition = result["physics_status"], result["state_transition"]
    if transition.get("kind") != "unsupported":
        raise AssertionError(f"{where}: state_transition.kind is {transition.get('kind')!r}, expected 'unsupported': {transition}")
    if status.get("resolution") != "UNSUPPORTED_BY_MODEL":
        raise AssertionError(f"{where}: physics_status.resolution is {status.get('resolution')!r}, expected 'UNSUPPORTED_BY_MODEL'")
    if status.get("reason_code") != reason or transition.get("reason") != reason:
        raise AssertionError(f"{where}: reason code is {status.get('reason_code')!r} / {transition.get('reason')!r}, expected {reason!r}")
    assert transition == {"kind": "unsupported", "category": "oxidation", "reason": reason}, f"{where}: {transition}"
    entries = status["entries"]
    assert len(entries) == 1 and entries[0]["parameter"] == "positive_time_oxidation" and entries[0]["resolution"] == "UNSUPPORTED_BY_MODEL", entries
    assert status["measured_min_oxide_um"] is None, f"{where}: an oxide thickness was reported: {status['measured_min_oxide_um']}"
    assert status["requested_initial_oxide_um"] == recipe.get("pad_oxide_thickness_um"), "requested_initial_oxide_um must echo the request"
    assert set(status) == STATUS_KEYS, sorted(status)


def check_fresh_materials(materials, where):
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


# ------------------------------------------------------------------------------------------ construction-only check
def si_window_width(mesh_path):
    """CONSTRUCTION-ONLY. Width of the gap in the mask (the trench window), from the mask triangles' own x-centroids: the
    largest gap between consecutive sorted centroids (the mask is two blocks, one each side of the window)."""
    mesh = meshio.read(mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    xs = sorted(sum(mesh.points[i][0] for i in tri) / 3.0
                for tri, tag in zip(block.data, tags) if str(MODULE.Material(int(tag))).split("'")[1] == "Mask")
    assert len(xs) >= 2, "not enough Mask triangles to find a gap"
    return max(b - a for a, b in zip(xs, xs[1:]))


def check_window_width(width, expected, grid, where):
    if abs(width - expected) >= 2 * grid:
        raise AssertionError(f"{where}: window width {width} does not match the recipe's {expected} within {2 * grid} um")


# ------------------------------------------------------------------------------------------ false-green machinery
def expect_fail(check, label, expected):
    """A guard passes only if `check` raises AssertionError whose message contains `expected` (str, tuple of str that must
    all appear, or predicate). A passing check is FALSE GREEN; another reason is WRONG FAILURE REASON."""
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


def run_guards(sample, sample_materials, reason, recipe):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    bad = copy.deepcopy(sample)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "kind=identity", reason, recipe), "the transition kind is identity",
                "state_transition.kind is 'identity'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "SOMETHING_ELSE"
    expect_fail(lambda: check_unsupported(bad, "wrong reason", reason, recipe), "the reason code is a different value",
                "reason code is 'SOMETHING_ELSE'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED", reason, recipe), "the physics resolution is MODELLED",
                "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(sample_materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["measured_min_oxide_um"] = 0.11
    expect_fail(lambda: check_unsupported(bad, "number", reason, recipe), "an oxide thickness is reported", "an oxide thickness was reported")
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")
    expect_fail(lambda: check_window_width(1.5, 1.0, 0.2, "construction"), "the construction-only window is the wrong width",
                "construction: window width 1.5 does not match")


def main():
    calibrate_trap()
    print("[1/4] solver traps calibrated (vps.Process, vps.Oxidation, setInitialOxideThickness, "
          "LocosOxidation._build_locos_geometry each fire when called directly)")

    sample = None
    for label, name, extras, reason in MODELS:
        recipe = {**BASE_RECIPE, **extras}
        with tempfile.TemporaryDirectory() as tmp:
            with SolverTrap() as trap:
                result = registry.get("oxidation", name)().run(dict(recipe), tmp)
            trap.assert_not_entered(label)
            check_unsupported(result, label, reason, recipe)
            materials = mesh_materials(result["final_mesh"])
            check_fresh_materials(materials, label)
            print(f"[2/4] {label}, positive-time request ({recipe['time_hours']} h): forbidden-call counts "
                  f"{dict.fromkeys(SolverTrap.FORBIDDEN, 0)}")
            print(f"      state_transition = {result['state_transition']}")
            print(f"      physics_status: resolution={result['physics_status']['resolution']}, reason_code={result['physics_status']['reason_code']}, "
                  f"measured_min_oxide_um={result['physics_status']['measured_min_oxide_um']}")
            print(f"      returned geometry: materials {materials} (virgin Si only; last-known, not an oxidation result); "
                  f"no oxide area, Si consumption or mask retention is computed")
            if sample is None:
                sample = (result, materials, reason, recipe)

    # CONSTRUCTION-ONLY: the plain window geometry prepare_domain() builds before any oxidation (no oxidation physics, no contactMode).
    expected = round(BASE_RECIPE["mask_right_um"] - BASE_RECIPE["mask_left_um"], 9)
    grid = BASE_RECIPE["grid_delta_um"]
    for label, name, extras, _ in MODELS:
        with tempfile.TemporaryDirectory() as tmp, SolverTrap() as trap:
            geometry = registry.get("oxidation", name)().prepare_domain({**BASE_RECIPE, **extras})
            width = si_window_width(save_volume_mesh(geometry, Path(tmp) / "before"))
        trap.assert_not_entered(f"construction-only {label}")
        check_window_width(width, expected, grid, f"construction-only {label}")
        print(f"[3/4] CONSTRUCTION-ONLY ({label}): window width {width:.4f} um vs the recipe's {expected} um "
              f"(within 2 grid cells) -- geometry construction only; not an oxidation, contactMode or mask-retention check")

    run_guards(*sample)

    print()
    print("POSITIVE-TIME THERMAL AND LOCOS: UNSUPPORTED_BY_MODEL / exact reason codes / kind 'unsupported', 0 solver calls, "
          "virgin Si only, no oxidation number computed; construction-only window geometry checked separately. "
          "(contactMode / mask-retention results are historical, not a current contract.)")


if __name__ == "__main__":
    main()
