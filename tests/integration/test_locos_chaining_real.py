#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOCOS process-flow chaining: what a positive-time LOCOS request now does to a flow — real ViennaPS 4.6.2,
through the actual production entry points (registry -> LocosOxidation.run(); tcad.process.flow.run_flow()).

WHAT THIS TEST PINS NOW (Batch 7). A positive-time LOCOS request is UNSUPPORTED_BY_MODEL:
    state_transition.kind == "unsupported"
    physics_status.resolution == "UNSUPPORTED_BY_MODEL"
    reason (both fields) == "LOCOS_CAPABILITY_PROOF_MISSING"
and it is refused before any solver call. It therefore produces NO LOCOS geometry to chain from:

  A. direct request -- the contract above; `vps.Process`, `vps.Oxidation` (construction and
     `setInitialOxideThickness`) and `LocosOxidation._build_locos_geometry` are trapped and counted (0 calls);
     the returned geometry is the fresh virgin-Si wafer only (no SiO2, no Mask). It is a last-known/fresh
     geometry, not a LOCOS result: no oxide growth, Si consumption, mask retention or chainable LOCOS stack
     is claimed.
  B. run_flow stops -- a real `run_flow` is given [positive-time LOCOS, a SENTINEL step]. The flow returns the
     one unsupported LOCOS result and stops: the sentinel's registry lookup, constructor and run() are all
     0, no directory/geometry exists for it, and the first result's last-known mesh is not treated as a
     post-LOCOS geometry.
  C. no manual chaining -- nothing here hands the `last_domain` of an unsupported LOCOS to an etch, a
     Bosch, an oxidation or a second LOCOS. That would replace an UNCOMPUTED LOCOS state with an "unoxidized
     last-known domain" and continue the process on it: a physically false recovery. (The supported-flow
     mechanics are covered by test_waferstate_sequential_flow_real.py, run separately as a control.)

WHAT IS NOT PINNED ANY MORE (historical). This file used to run a real LOCOS and then check, on its exported
geometry: all 3 materials with >=90% mask retention; chained directional etch, a second chained etch and Bosch
each keeping 3 materials and removing oxide while leaving Si; fin-style oxidation growing oxide on a LOCOS domain;
a second LOCOS refused on a modified domain (stale stash); and a second LOCOS chained directly onto the first
growing oxide and consuming Si (measured then: SiO2 +0.17511 at 10 hr vs the first step's +0.10577, Si -0.06407).
Those were results of a positive-time LOCOS the backend no longer computes. They are HISTORICAL investigation
results (the chainable-domain fix in LocosOxidation._make_locos_domain_chainable() and
tcad.backends.viennaps.io.register_locos_export() belongs to that history), not a current contract; nothing here
recomputes or verifies them.

False-green guards at the end prove each check fails, for its own reason, when its subject is broken.
"""

import copy
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.etching  # noqa: F401 -- registers the models
import tcad.process.oxidation  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.process.base import ProcessStep
from tcad.process.flow import FlowStep, run_flow
from tcad.process.oxidation.locos import LocosOxidation

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
MODULE = viennaps_session.require_viennaps()

# The historical LOCOS chaining recipe, used ONLY as the REQUEST that must be refused (0.02 h is > 0).
OXIDATION_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.02,
    "mask_material": "Mask",
}
EXPECTED_REASON = "LOCOS_CAPABILITY_PROOF_MISSING"
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}
STATUS_KEYS = {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}


# ------------------------------------------------------------------------------------------ solver-call traps
class SolverTrap:
    """Recorders that also raise (a regression fails loudly); the counts catch a call a broad `except` swallowed."""

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


# ------------------------------------------------------------------------------------------ flow sentinel
SENTINEL_CATEGORY, SENTINEL_NAME = "sentinel_tripwire", "must_never_run"


class SentinelStep(ProcessStep):
    """A step that must NEVER be reached: its constructor and run() record themselves and raise."""

    category, name = SENTINEL_CATEGORY, SENTINEL_NAME
    counts = {"constructed": 0, "run": 0}

    def __init__(self, *a, **k):
        SentinelStep.counts["constructed"] += 1
        raise AssertionError("sentinel step constructed")

    def run(self, recipe, output_dir):
        SentinelStep.counts["run"] += 1
        raise AssertionError("sentinel step run()")


class FlowTracker:
    """Registers the sentinel for the duration of the block and records every registry lookup (pass-through)."""

    def __init__(self):
        self.lookups = []

    def __enter__(self):
        SentinelStep.counts.update(constructed=0, run=0)
        registry._REGISTRY.setdefault(SENTINEL_CATEGORY, {})[SENTINEL_NAME] = SentinelStep
        original = registry.get
        tracker = self

        def tracking_get(category, name):
            tracker.lookups.append((category, name))
            return original(category, name)

        self._patch = patch.object(registry, "get", tracking_get)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        registry._REGISTRY.pop(SENTINEL_CATEGORY, None)
        return False

    def sentinel_touches(self):
        return {"lookups": sum(1 for k in self.lookups if k == (SENTINEL_CATEGORY, SENTINEL_NAME)),
                "constructed": SentinelStep.counts["constructed"], "run": SentinelStep.counts["run"]}

    def assert_sentinel_untouched(self, where):
        touches = self.sentinel_touches()
        if any(touches.values()):
            raise AssertionError(f"{where}: sentinel step was reached: {touches}")


def calibrate_sentinel():
    """The sentinel must actually record and raise when touched, and the registry must be clean again afterwards."""
    with FlowTracker() as tracker:
        cls = registry.get(SENTINEL_CATEGORY, SENTINEL_NAME)
        for label, call in (("constructor", lambda: cls()), ("run()", lambda: cls.run(None, {}, "unused"))):
            try:
                call()
            except AssertionError:
                continue
            raise AssertionError(f"the sentinel {label} did not fire")
        assert tracker.sentinel_touches() == {"lookups": 1, "constructed": 1, "run": 1}, tracker.sentinel_touches()
    assert SENTINEL_CATEGORY not in registry._REGISTRY, "the sentinel was left registered"
    SentinelStep.counts.update(constructed=0, run=0)


# ------------------------------------------------------------------------------------------ contract checks
def mesh_materials(path):
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type == "triangle":
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(MODULE.Material(t)).split("'")[1] for t in tags)


def check_unsupported(result, where):
    assert set(result) == RESULT_KEYS, f"{where}: unexpected result keys {sorted(result)}"
    status, transition = result["physics_status"], result["state_transition"]
    if transition.get("kind") != "unsupported":
        raise AssertionError(f"{where}: state_transition.kind is {transition.get('kind')!r}, expected 'unsupported': {transition}")
    if status.get("resolution") != "UNSUPPORTED_BY_MODEL":
        raise AssertionError(f"{where}: physics_status.resolution is {status.get('resolution')!r}, expected 'UNSUPPORTED_BY_MODEL'")
    if status.get("reason_code") != EXPECTED_REASON or transition.get("reason") != EXPECTED_REASON:
        raise AssertionError(f"{where}: reason code is {status.get('reason_code')!r} / {transition.get('reason')!r}, expected {EXPECTED_REASON!r}")
    assert transition == {"kind": "unsupported", "category": "oxidation", "reason": EXPECTED_REASON}, f"{where}: {transition}"
    assert status["measured_min_oxide_um"] is None, f"{where}: an oxide thickness was reported: {status['measured_min_oxide_um']}"
    assert status["requested_initial_oxide_um"] == OXIDATION_RECIPE.get("pad_oxide_thickness_um"), "requested_initial_oxide_um must echo the request"
    assert set(status) == STATUS_KEYS, sorted(status)


def check_fresh_materials(materials, where):
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


def check_flow_stopped(flow, lookups, tracker, flow_dir, where="run_flow"):
    """The flow returned exactly the one unsupported LOCOS result; the sentinel was never looked up, constructed or run; no
    directory (hence no geometry) exists for the second step."""
    assert len(flow) == 1, f"{where}: expected exactly the unsupported LOCOS result, got {len(flow)} results"
    kind = flow[0].metadata["state_transition"]["kind"]
    if kind != "unsupported":
        raise AssertionError(f"{where}: the first result's transition kind is {kind!r}, expected 'unsupported'")
    tracker.assert_sentinel_untouched(where)
    assert lookups == [("oxidation", "locos")], f"{where}: registry lookups were {lookups}"
    made = sorted(p.name for p in Path(flow_dir).iterdir())
    assert len(made) == 1 and made[0].endswith("oxidation_locos"), f"{where}: step directories {made} -- a second step's geometry exists"


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


def run_guards(sample, materials):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "OXIDATION_CAPABILITY_PROOF_MISSING"      # LOCOS <-> thermal swapped
    expect_fail(lambda: check_unsupported(bad, "swapped"), "the LOCOS request carries the thermal reason code",
                "reason code is 'OXIDATION_CAPABILITY_PROOF_MISSING'")
    bad = copy.deepcopy(sample)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "identity"), "the transition kind is identity", "state_transition.kind is 'identity'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED"), "the physics resolution is MODELLED", "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    expect_fail(lambda: check_fresh_materials(sorted(materials + ["Mask"]), "fresh+Mask"), "the fresh result contains a Mask",
                "not the virgin Si wafer only: materials ['Mask', 'Si']")
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")

    # a flow that DOES execute the sentinel (the first step is the sentinel; the exception is swallowed like a broad `except`)
    def flow_that_runs_the_sentinel():
        with FlowTracker() as tracker, tempfile.TemporaryDirectory() as tmp:
            try:
                run_flow([FlowStep(SENTINEL_CATEGORY, SENTINEL_NAME, {})], tmp)
            except AssertionError:
                pass
            tracker.assert_sentinel_untouched("mutant flow")

    expect_fail(flow_that_runs_the_sentinel, "run_flow executes the sentinel step",
                "mutant flow: sentinel step was reached: {'lookups': 1, 'constructed': 1, 'run': 0}")


def main():
    step_cls = registry.get("oxidation", "locos")
    calibrate_trap()
    calibrate_sentinel()
    print("[0] solver traps and the flow sentinel calibrated (each fires when touched directly; the registry is clean afterwards)")

    # ---- A: the direct request ------------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        with SolverTrap() as trap:
            result = step_cls().run(dict(OXIDATION_RECIPE), str(Path(tmp) / "locos"))
        trap.assert_not_entered("direct LOCOS request")
        check_unsupported(result, "direct LOCOS request")
        materials = mesh_materials(result["final_mesh"])
        check_fresh_materials(materials, "direct LOCOS request")
        print(f"[1/3] direct positive-time LOCOS request ({OXIDATION_RECIPE['time_hours']} h): state_transition {result['state_transition']}; "
              f"resolution {result['physics_status']['resolution']}/{result['physics_status']['reason_code']}; solver-path counts "
              f"{dict.fromkeys(SolverTrap.FORBIDDEN, 0)}; returned materials {materials} -- the fresh virgin-Si wafer, NOT a LOCOS "
              f"result: no oxide growth, Si consumption, mask retention or chainable LOCOS stack is claimed")

    # ---- B: run_flow stops at the first unsupported step -----------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        steps = [FlowStep("oxidation", "locos", dict(OXIDATION_RECIPE)), FlowStep(SENTINEL_CATEGORY, SENTINEL_NAME, {})]
        with FlowTracker() as tracker, SolverTrap() as trap:
            flow = run_flow(steps, tmp)
            lookups = list(tracker.lookups)
        trap.assert_not_entered("run_flow")
        check_flow_stopped(flow, lookups, tracker, tmp)
        first = flow[0]
        flow_materials = mesh_materials(first.volume_mesh_path)
        check_fresh_materials(flow_materials, "run_flow first result")
        print(f"[2/3] run_flow([positive-time LOCOS, SENTINEL]): {len(flow)} result (the unsupported LOCOS: transition "
              f"{first.metadata['state_transition']['kind']}, reason {first.metadata['state_transition']['reason']}); registry lookups {lookups}; "
              f"sentinel lookups/constructions/run() = {tracker.sentinel_touches()}; step directories "
              f"{sorted(p.name for p in Path(tmp).iterdir())} (none for the second step); solver-path counts {dict.fromkeys(SolverTrap.FORBIDDEN, 0)}")
        print(f"      the first result's mesh {flow_materials} is the last-known/fresh geometry, not a post-LOCOS geometry; it is not handed to any further step")

    print("[3/3] no manual chaining: the unsupported LOCOS's last_domain is not passed to any etch, Bosch, oxidation or second LOCOS "
          "(that would replace an uncomputed LOCOS state with an 'unoxidized last-known domain' and continue on it)")

    run_guards(result, materials)

    print()
    print("LOCOS CHAINING: positive-time LOCOS = UNSUPPORTED_BY_MODEL / LOCOS_CAPABILITY_PROOF_MISSING; 0 solver and LOCOS-builder calls; "
          "run_flow stops after it (sentinel lookups/constructions/run() all 0); only the fresh virgin Si is returned; no LOCOS chaining is claimed")


if __name__ == "__main__":
    main()
