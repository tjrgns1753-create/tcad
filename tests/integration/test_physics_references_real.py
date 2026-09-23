#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Positive-time oxidation capability contract (T3a) and a clearly-labelled etch fidelity check (T3b).

T3a -- CAPABILITY CONTRACT, NOT PHYSICS. This section used to test two independent physical relations
against a positive-time thermal oxidation: Si consumed / oxide grown = 0.44 (molar volumes of Si and SiO2)
and time additivity (t then t equals 2t once). Those relations are physics, but they can only be checked
against an oxidation result, and the current backend produces none: a positive-time thermal request is
UNSUPPORTED_BY_MODEL, refused before any solver call with

    physics_status.resolution == "UNSUPPORTED_BY_MODEL"
    physics_status.reason_code == state_transition.reason == "OXIDATION_CAPABILITY_PROOF_MISSING"
    state_transition.kind      == "unsupported"

So T3a now checks that, for several positive times and for chained requests: every request is refused
with that exact contract; `vps.Process`, `vps.Oxidation` (construction and `setInitialOxideThickness`)
and `LocosOxidation._build_locos_geometry` are never entered (trapped and counted); no oxide thickness,
consumed Si, ratio or relative error is computed; a chained request does not continue a computation after the
first unsupported one; and the geometry handed back is the LAST-KNOWN geometry, unchanged, never an
oxidation result. The historical numbers (0.434 / 0.437 / 0.439 at 0.5 / 1.0 / 2.0 hr; 0.39% additivity) came from a
model state that no longer exists in production; they are history, are not reproduced here, and nothing in this
test says the current backend computes them.

T3b -- TRANSMISSION FIDELITY ONLY, UNCHANGED. THIS DOES NOT VERIFY THE RESOLVER'S NUMERICAL CORRECTNESS. It
verifies only that the number the resolver produced is the number the backend applied: a material given etch
rate 0 stays where it was (within the representation tolerance 0.5 x grid), and the resolver's OWN reported entry
for that material reads 0.0. It is a separate, supported physical path (the real isotropic etch entry point) and
is not an accuracy check of any etch-rate model.
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

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.process.flow import FlowStep, run_flow
from tcad.process.oxidation.locos import LocosOxidation

MODULE = viennaps_session.require_viennaps()

GRID = 0.02
BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=GRID,
            x_extent_um=6.0, y_extent_um=6.0)
EXPECTED_REASON = "OXIDATION_CAPABILITY_PROOF_MISSING"      # what thermal.py returns for a positive-time request
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}
STATUS_KEYS = {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}
POSITIVE_HOURS = (0.5, 1.0, 2.0)


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


# ------------------------------------------------------------------------------------------ measurement helpers
def _tops(mesh_path):
    """Top y of every material of an exported mesh (used by T3b, the supported etch path)."""
    import viennaps as vps

    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        value = getattr(vps.Material, attr)
        if isinstance(value, vps.Material):
            names.setdefault(int(value), attr)

    mesh = meshio.read(mesh_path)
    points = mesh.points
    found = {}
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            values = np.asarray(values).ravel()
            for tag in set(values.tolist()):
                selected = cells.data[values == tag]
                if len(selected) == 0:
                    continue
                name = names.get(int(tag), str(int(tag)))
                top = float(points[np.unique(selected)][:, 1].max())
                found[name] = max(found.get(name, top), top)
    return found


def mesh_materials(path):
    """Exact sorted material names present as triangles in an exported mesh."""
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type == "triangle":
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(MODULE.Material(t)).split("'")[1] for t in tags)


def same_mesh(a, b):
    a, b = meshio.read(a), meshio.read(b)
    np.testing.assert_array_equal(a.points, b.points)
    assert len(a.cells) == len(b.cells)
    for x, y in zip(a.cells, b.cells):
        assert x.type == y.type
        np.testing.assert_array_equal(x.data, y.data)
    for x, y in zip(a.cell_data["Material"], b.cell_data["Material"]):
        np.testing.assert_array_equal(x, y)


# ------------------------------------------------------------------------------------------ T3a contract checks
def check_unsupported(result, where, recipe):
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
    # no oxidation result was computed: the only fields besides the verdict are echoes of the request
    assert status["measured_min_oxide_um"] is None, f"{where}: an oxide thickness was reported: {status['measured_min_oxide_um']}"
    assert status["requested_initial_oxide_um"] == recipe.get("pad_oxide_thickness_um"), "requested_initial_oxide_um must echo the request"
    assert set(status) == STATUS_KEYS, sorted(status)


def check_fresh_materials(materials, where):
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


def _request(hours, domain=None):
    recipe = {**BASE, "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": hours}
    if domain is None:
        recipe["mask_spans_um"] = []
    step = registry.get("oxidation", "thermal")(inherited_domain=domain)
    with SolverTrap() as trap:
        result = step.run(recipe, tempfile.mkdtemp(prefix="ref_"))
    trap.assert_not_entered(f"thermal {hours} h" + (" (chained)" if domain is not None else ""))
    return step, result, recipe


def test_t3a_positive_time_capability_contract():
    print("\n[T3a] positive-time thermal oxidation = UNSUPPORTED_BY_MODEL: capability contract (no oxidation number is computed)")
    first = None
    for hours in POSITIVE_HOURS:
        step, result, recipe = _request(hours)
        check_unsupported(result, f"t={hours} h", recipe)
        materials = mesh_materials(result["final_mesh"])
        check_fresh_materials(materials, f"t={hours} h")
        print(f"    t={hours} h: state_transition={result['state_transition']}, reason_code={result['physics_status']['reason_code']}, "
              f"materials={materials}, forbidden-call counts {dict.fromkeys(SolverTrap.FORBIDDEN, 0)}")
        if first is None:
            first = (step, result, recipe)

    # Chained request 1: a second positive-time request handed the domain the first one returned. It must be refused
    # again, must not compute anything on top of the first, and must return that domain's geometry UNCHANGED.
    step0, result0, _ = first
    domain = step0.last_domain
    step1, result1, recipe1 = _request(POSITIVE_HOURS[0], domain=domain)
    check_unsupported(result1, "chained request", recipe1)
    assert step1.last_domain is domain, "the chained request replaced the geometry it was given"
    same_mesh(result0["final_mesh"], result1["final_mesh"])
    check_fresh_materials(mesh_materials(result1["final_mesh"]), "chained request")
    print(f"    chained request on the first result's domain: unsupported again, geometry byte-identical to the first "
          f"(last-known geometry, not an oxidation result), materials {mesh_materials(result1['final_mesh'])}")

    # Chained request 2: through the real flow runner, which must stop at the first unsupported step.
    steps = [FlowStep("oxidation", "thermal", {**BASE, "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": h, "mask_spans_um": []})
             for h in (0.5, 0.5)]
    with SolverTrap() as trap, tempfile.TemporaryDirectory() as tmp:
        flow = run_flow(steps, tmp)
        flow_kinds = [r.metadata["state_transition"]["kind"] for r in flow]
        flow_materials = [mesh_materials(r.volume_mesh_path) for r in flow]
    trap.assert_not_entered("chained flow")
    assert len(flow) == 1 and flow_kinds == ["unsupported"], (
        f"the flow did not stop at the first unsupported step: {len(flow)} results, transitions {flow_kinds}")
    assert flow_materials == [["Si"]], flow_materials
    print(f"    two chained positive-time steps through run_flow: {len(flow)} result (the second step never ran), "
          f"transitions {flow_kinds}, materials {flow_materials[0]}, forbidden-call counts {dict.fromkeys(SolverTrap.FORBIDDEN, 0)}")
    return first


# ------------------------------------------------------------------------------------------ T3b (supported etch path)
TOL_SI_UNMOVED = 0.5 * GRID


def check_t3b_unmoved(si_top, where="T3b"):
    if not abs(si_top) < TOL_SI_UNMOVED:
        raise AssertionError(f"{where}: a material given rate 0 moved to {si_top:.4f} -- the resolved value is not the value the backend applied")


def check_t3b_reported(entries, where="T3b"):
    si_entries = [e for e in entries if e["material"] == "Si"]
    if not (si_entries and si_entries[0]["value"] == 0.0):
        raise AssertionError(f"{where}: the resolver's OWN reported entry for Si must also read 0.0, not just the unmoved geometry: {entries}")


def test_t3b_transmission_only():
    """DOES NOT VERIFY PHYSICAL CORRECTNESS -- transmission fidelity only."""
    print("\n[T3b] the rate the resolver produced is the rate applied")
    print("      (this check does NOT verify the rate is physically right)")
    step = registry.get("etching", "isotropic")()
    result = step.run({**BASE, "mask_spans_um": [],
                       "material_rates": {"Si": 0.0}, "default_rate": 0.0,
                       "etch_time_s": 0.5},
                      tempfile.mkdtemp(prefix="ref_"))
    tops = _tops(result["final_mesh"])
    check_t3b_unmoved(tops["Si"])
    print(f"    rate 0 -> Si surface at {tops['Si']:+.4f} (unmoved; tolerance {TOL_SI_UNMOVED:.3f} = 0.5 x grid)")

    entries = result["physics_status"]["entries"]
    check_t3b_reported(entries)
    si_entries = [e for e in entries if e["material"] == "Si"]
    print(f"    resolver's own reported entry for Si: value={si_entries[0]['value']} (matches what was applied)")
    return result, tops


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


def run_guards(t3a_first, t3b):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    _, sample, recipe = t3a_first
    materials = mesh_materials(sample["final_mesh"])
    bad = copy.deepcopy(sample)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "kind=identity", recipe), "the transition kind is identity", "state_transition.kind is 'identity'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "SOMETHING_ELSE"
    expect_fail(lambda: check_unsupported(bad, "wrong reason", recipe), "the reason code is a different value", "reason code is 'SOMETHING_ELSE'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED", recipe), "the physics resolution is MODELLED", "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["measured_min_oxide_um"] = 0.11
    expect_fail(lambda: check_unsupported(bad, "number", recipe), "an oxide thickness is reported", "an oxide thickness was reported")
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")
    # T3b: the Si surface moved by more than the representation tolerance / the resolver reported a different rate
    result, tops = t3b
    expect_fail(lambda: check_t3b_unmoved(tops["Si"] + 1.5 * TOL_SI_UNMOVED, "T3b moved"), "the Si surface moved more than 0.5 x grid",
                "T3b moved: a material given rate 0 moved to")
    entries = copy.deepcopy(result["physics_status"]["entries"])
    for entry in entries:
        if entry["material"] == "Si":
            entry["value"] = 0.3
    expect_fail(lambda: check_t3b_reported(entries, "T3b reported"), "the resolver reports a non-zero Si rate",
                "T3b reported: the resolver's OWN reported entry for Si must also read 0.0")


def main():
    calibrate_trap()
    print("[0] solver traps calibrated (vps.Process, vps.Oxidation, setInitialOxideThickness, "
          "LocosOxidation._build_locos_geometry each fire when called directly)")
    first = test_t3a_positive_time_capability_contract()
    t3b = test_t3b_transmission_only()
    run_guards(first, t3b)
    print()
    print("PHYSICS REFERENCES: T3a positive-time oxidation = UNSUPPORTED_BY_MODEL / OXIDATION_CAPABILITY_PROOF_MISSING / kind 'unsupported', "
          "0 solver calls, no oxidation number computed (capability contract, not physics); "
          "T3b etch transmission fidelity unchanged and passing (fidelity only, labelled)")


if __name__ == "__main__":
    main()
