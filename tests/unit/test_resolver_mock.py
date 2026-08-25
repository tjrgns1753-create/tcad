#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The resolver: pure, history-free, honest about what it does not know."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.intent import ProcessIntent
from tcad.physics.resolve import resolve
from tcad.physics.values import Provenance, Resolution


class _FakeState:
    """Only what the resolver reads — no ViennaPS needed."""

    def __init__(self, exposed, declared=None, thin=()):
        self._exposed = frozenset(exposed)
        self.materials = tuple(declared or exposed)
        self._thin = tuple(thin)

    def exposed_materials(self):
        return self._exposed

    def under_resolved_x(self):
        return self._thin


def test_no_history_channel():
    """T1: order cannot influence a function that cannot see it."""
    parameters = list(inspect.signature(resolve).parameters)
    assert parameters[:2] == ["intent", "state"], parameters
    forbidden = {"history", "previous", "previous_step", "completed_steps",
                 "process_stage", "last_step"}
    assert not forbidden.intersection(parameters), (
        f"resolve() gained a history channel: {parameters}")
    print("[T1] resolve(intent, state) has no history parameter")


def test_unknown_still_resolves():
    """An empty table must not stop the step from running."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si", "SiO2"}))
    assert resolved.resolution is Resolution.UNKNOWN
    assert resolved.entries, "the resolver must say WHICH lookups were unknown"
    assert {e.material for e in resolved.entries} == {"Si", "SiO2"}
    print(f"[unknown] {resolved.resolution.value}, "
          f"{len(resolved.entries)} entries recorded")


def test_user_supplied_is_its_own_provenance():
    """A caller-specified rate is honoured, and labelled as unverified."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si", "SiO2"}),
                       user_supplied={"material_rates": {"Si": -0.3}})
    assert resolved.backend_kwargs["materialRates"]["Si"] == -0.3
    supplied = [e for e in resolved.entries if e.material == "Si"][0]
    assert supplied.provenance is Provenance.USER_SUPPLIED
    assert supplied.resolution is Resolution.UNVERIFIED, (
        "USER_SUPPLIED means this project has not verified the value, not "
        "that the value is wrong")
    print("[compat] caller rates honoured as USER_SUPPLIED / UNVERIFIED")


def test_same_state_same_result():
    """T2: identical (state, intent) must resolve identically."""
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    first = resolve(intent, _FakeState({"Si", "SiO2"}))
    second = resolve(intent, _FakeState({"SiO2", "Si"}))
    assert first.backend_kwargs == second.backend_kwargs
    assert first.resolution is second.resolution
    print("[T2] same exposed materials + same intent -> same resolution")


def test_numerical_axis_stays_separate():
    intent = ProcessIntent(category="etching", method="isotropic",
                           chemistry="SF6O2", parameters={"etch_time_s": 1.0})
    resolved = resolve(intent, _FakeState({"Si"}, thin=(0.0, 0.1)))
    assert resolved.under_resolved_x == (0.0, 0.1)
    assert "UNDER_RESOLVED" not in resolved.resolution.value, (
        "the numerical warning must not be folded into physics status")
    print("[axes] under_resolved_x carried separately from resolution")


def main():
    test_no_history_channel()
    test_unknown_still_resolves()
    test_user_supplied_is_its_own_provenance()
    test_same_state_same_result()
    test_numerical_axis_stays_separate()
    print()
    print("RESOLVER OK — pure, history-free, UNKNOWN-safe")


if __name__ == "__main__":
    main()
