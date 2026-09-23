#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blanket (mask-less) process steps — real ViennaPS 4.6.2.

WHY THIS EXISTS (history). `prepare_domain()` used to build a photoresist mask unconditionally on every
fresh wafer, because the whole process layer assumed "a process step always follows lithography". That is
true for etching and false for any BLANKET step. It produced physically impossible geometry (a mask that
blocked nothing, and -- measured on a plain Dry/1000C/0.5hr oxidation of that era -- oxide separated from the
silicon it supposedly grew from by the full resist thickness). There was also no way to ask for a bare wafer:
a fully-open mask (`mask_spans_from_openings` over the whole wafer) returns an empty span list that the old
truthiness test sent down the MakeTrench path, silently producing a masked wafer.

WHAT THIS TEST VERIFIES NOW (Batch 7). Two independent contracts, kept apart:

  1. POSITIVE-TIME THERMAL OXIDATION IS UNSUPPORTED (test_positive_time_oxidation_contract). The three
     original oxidation requests -- no mask keys, `mask_spans_um: []`, and a masked recipe -- are each
     refused before any solver call:
         state_transition.kind == "unsupported"
         physics_status.resolution == "UNSUPPORTED_BY_MODEL"
         reason (both fields) == "OXIDATION_CAPABILITY_PROOF_MISSING"
     `vps.Process`, `vps.Oxidation` (construction and `setInitialOxideThickness`) and
     `LocosOxidation._build_locos_geometry` are trapped and counted (0 calls). The returned geometry is the
     fresh, materialized virgin-Si wafer ONLY (no SiO2, no Mask -- the recipe's mask keys are not applied);
     it is a last-known/fresh geometry, NOT an oxidation result, and no oxide position, Si consumption or
     oxide-coherence number is computed. That the no-mask and `mask_spans_um: []` requests return the same
     geometry is reported only as "the same fresh materialized virgin-Si geometry", never as "the same oxidation
     result". The original oxide-coherence check (oxide straddling the surface, Si consumed) and the original
     "masked oxidation still builds a Mask" check were oxidation-result claims and are gone.

  2. BLANKET DEPOSITION IS A SUPPORTED PATH (test_blanket_deposition_supported): a real isotropic SiO2
     deposition on a bare wafer builds no Mask; the exported mesh holds Si and a DEPOSITED SiO2 film (not an
     oxidation oxide) lying on the Si at every sampled column, thicker than the exporter's representation
     offset (0.1 x grid). The mask-recipe path (`mask_left_um`/`mask_right_um`) is checked through the same
     supported deposition, since the oxidation variant can no longer show it.

Every measurement is read from the exported mesh. False-green guards at the end prove each check fails, for
its own reason, when its subject is broken.
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

import tcad.process.deposition  # noqa: F401 -- registers deposition models
import tcad.process.oxidation  # noqa: F401 -- registers thermal oxidation
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.process.base import mask_spans_from_openings
from tcad.process.oxidation.locos import LocosOxidation

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
MODULE = viennaps_session.require_viennaps()

GRID = 0.05
X_EXTENT = 4.0
BASE = {"grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0}
OXIDATION = {"oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5}     # a positive-time REQUEST (refused)
EXPORT_TOL = 0.1 * GRID       # smallest geometric change distinguishable from the exporter's representation offset
EXPECTED_REASON = "OXIDATION_CAPABILITY_PROOF_MISSING"
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}
STATUS_KEYS = {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}
XS = np.linspace(-1.5, 1.5, 7)                # sample columns, inside the domain (x = -2..+2)


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


# ------------------------------------------------------------------------------------------ measurement
def _column_extent(points, tris, x):
    ys = []
    for t in tris:
        v = points[t][:, :2]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            (xa, ya), (xb, yb) = v[a], v[b]
            if xa == xb:
                if xa == x:
                    ys += [ya, yb]
            elif (xa - x) * (xb - x) <= 0:
                ys.append(ya + (x - xa) / (xb - xa) * (yb - ya))
    return (min(ys), max(ys)) if ys else (np.nan, np.nan)


def read_geometry(mesh_path):
    """{'materials': sorted names, 'columns': {name: (ymin[], ymax[]) at XS}, 'digest': arrays for equality} of an exported mesh."""
    mesh = meshio.read(mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = np.asarray(mesh.cell_data["Material"][mesh.cells.index(block)])
    columns, names = {}, []
    for tag in sorted(set(int(t) for t in tags)):
        name = str(MODULE.Material(tag)).split("'")[1]
        names.append(name)
        tri = block.data[tags == tag]
        ext = np.array([_column_extent(mesh.points, tri, x) for x in XS])
        columns[name] = (ext[:, 0], ext[:, 1])
    return {"materials": sorted(names), "columns": columns, "points": mesh.points.copy(), "cells": block.data.copy(), "tags": tags.copy()}


def same_geometry(a, b):
    return (a["materials"] == b["materials"] and np.array_equal(a["points"], b["points"])
            and np.array_equal(a["cells"], b["cells"]) and np.array_equal(a["tags"], b["tags"]))


def run_step(category, model, recipe, trap=False):
    """Run a real production step; returns (result dict, geometry read from its exported mesh)."""
    step = registry.get(category, model)()
    with tempfile.TemporaryDirectory() as tmp:
        if trap:
            with SolverTrap() as t:
                result = step.run({**BASE, **recipe}, tmp)
            t.assert_not_entered(f"{category}/{model}")
        else:
            result = step.run({**BASE, **recipe}, tmp)
        return result, read_geometry(result["final_mesh"])


# ------------------------------------------------------------------------------------------ contract checks
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
    assert set(status) == STATUS_KEYS, sorted(status)


def check_fresh_materials(materials, where):
    """A refused request returns the fresh virgin-Si wafer only: no SiO2, no Mask."""
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


def check_deposition_film(geom, where="blanket deposition"):
    """A DEPOSITED SiO2 film (not an oxidation oxide) on the Si, at every sampled column, thicker than 0.1 x grid; no Mask."""
    if geom["materials"] != ["Si", "SiO2"]:
        raise AssertionError(f"{where}: no SiO2 film was added / unexpected materials {geom['materials']}")
    si_lo, si_hi = geom["columns"]["Si"]
    ox_lo, ox_hi = geom["columns"]["SiO2"]
    thickness = ox_hi - ox_lo
    if not np.all(thickness > EXPORT_TOL):
        raise AssertionError(f"{where}: SiO2 film missing or thinner than {EXPORT_TOL:.4g} um (0.1 x grid) at a sampled column: {np.round(thickness, 5)}")
    assert np.all(np.abs(ox_lo - si_hi) <= EXPORT_TOL), f"{where}: the film does not lie on the Si: gap {np.round(ox_lo - si_hi, 5)}"
    assert np.all(np.abs(si_hi) <= EXPORT_TOL), f"{where}: the Si top moved from the bare wafer surface (y = 0): {np.round(si_hi, 5)}"


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


def run_guards(sample, sample_materials, deposition_geom):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "LOCOS_CAPABILITY_PROOF_MISSING"      # thermal <-> LOCOS swapped
    expect_fail(lambda: check_unsupported(bad, "swapped"), "the thermal request carries the LOCOS reason code",
                "reason code is 'LOCOS_CAPABILITY_PROOF_MISSING'")
    bad = copy.deepcopy(sample)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "identity"), "the transition kind is identity", "state_transition.kind is 'identity'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED"), "the physics resolution is MODELLED", "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(sample_materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    expect_fail(lambda: check_fresh_materials(sorted(sample_materials + ["Mask"]), "fresh+Mask"), "the fresh result contains a Mask",
                "not the virgin Si wafer only: materials ['Mask', 'Si']")
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")
    no_film = {**deposition_geom, "materials": ["Si"]}
    expect_fail(lambda: check_deposition_film(no_film), "the supported deposition has no film", "no SiO2 film was added")
    thin = {**deposition_geom, "columns": {**deposition_geom["columns"],
                                            "SiO2": (deposition_geom["columns"]["SiO2"][0], deposition_geom["columns"]["SiO2"][0] + 0.5 * EXPORT_TOL)}}
    expect_fail(lambda: check_deposition_film(thin), "the deposited film is thinner than 0.1 x grid", "SiO2 film missing or thinner than")


# ------------------------------------------------------------------------------------------ tests
def test_positive_time_oxidation_contract():
    calibrate_trap()
    print("[0] solver traps calibrated (vps.Process, vps.Oxidation, setInitialOxideThickness, LocosOxidation._build_locos_geometry)")

    # --- 1: no mask keys at all ------------------------------------------------------------------------------
    r_bare, g_bare = run_step("oxidation", "thermal", OXIDATION, trap=True)
    check_unsupported(r_bare, "no mask keys")
    check_fresh_materials(g_bare["materials"], "no mask keys")
    print(f"[1/4] positive-time thermal, no mask keys: {r_bare['state_transition']}; resolution "
          f"{r_bare['physics_status']['resolution']}/{r_bare['physics_status']['reason_code']}; solver-path counts "
          f"{dict.fromkeys(SolverTrap.FORBIDDEN, 0)}; returned materials {g_bare['materials']} (fresh virgin Si, not an oxidation result)")

    # --- 2: an explicitly EMPTY mask (a fully open wafer) -------------------------------------------------------------
    open_mask = mask_spans_from_openings([(0.0, X_EXTENT)], X_EXTENT)
    assert open_mask == [], f"a fully-open mask should have no opaque spans: {open_mask}"
    r_open, g_open = run_step("oxidation", "thermal", {**OXIDATION, "mask_spans_um": open_mask}, trap=True)
    check_unsupported(r_open, "mask_spans_um=[]")
    check_fresh_materials(g_open["materials"], "mask_spans_um=[]")
    assert same_geometry(g_bare, g_open), "the two refused requests returned different geometries"
    print(f"[2/4] positive-time thermal, mask_spans_um=[]: same contract; it returned the SAME fresh materialized virgin-Si "
          f"geometry as the no-mask request (exported mesh arrays equal) -- a last-known/fresh geometry, not an oxidation result")

    # --- 3: a masked positive-time recipe is refused too ---------------------------------------------------------------
    r_mask, g_mask = run_step("oxidation", "thermal", {**OXIDATION, "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5}, trap=True)
    check_unsupported(r_mask, "masked recipe")
    check_fresh_materials(g_mask["materials"], "masked recipe")
    print(f"[3/4] positive-time thermal WITH mask keys: {r_mask['state_transition']}; returned materials {g_mask['materials']} -- the "
          f"refused request built neither SiO2 nor the Mask its keys describe; no oxide position, Si consumption or oxide "
          f"coherence is computed")
    print("[4/4] no oxidation number of any kind was computed or printed for any of the three requests")
    return r_bare, g_bare["materials"]


def test_blanket_deposition_supported():
    print("\n[deposition] SUPPORTED path: blanket isotropic SiO2 deposition on a bare wafer (a deposited film, not an oxidation oxide)")
    result, geom = run_step("deposition", "isotropic", {"deposition_time_s": 1.0, "rate": 0.1, "material": "SiO2"})
    assert "state_transition" not in result or result["state_transition"] is None, result.get("state_transition")
    assert "Mask" not in geom["materials"], f"blanket deposition still built a mask: {geom['materials']}"
    check_deposition_film(geom)
    si_hi, (ox_lo, ox_hi) = geom["columns"]["Si"][1], geom["columns"]["SiO2"]
    print(f"    materials {geom['materials']}, no Mask; Si top {np.round(si_hi, 4)}; DEPOSITED SiO2 film thickness "
          f"{(ox_hi - ox_lo).min():.4f}..{(ox_hi - ox_lo).max():.4f} um at {len(XS)}/{len(XS)} sampled columns "
          f"(bound: > 0.1 x grid = {EXPORT_TOL:.4f}); the film lies on the Si (film bottom = Si top within {EXPORT_TOL:.4f})")

    # The mask-recipe path, shown through the same supported step: mask_left/right still produce a Mask material.
    _, masked = run_step("deposition", "isotropic", {"deposition_time_s": 1.0, "rate": 0.1, "material": "SiO2",
                                                     "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5})
    assert "Mask" in masked["materials"], f"a masked deposition recipe lost its mask: {masked['materials']}"
    print(f"    mask recipe (supported deposition): Mask present, materials {masked['materials']} -- the masked path is unchanged")
    return geom


def main():
    sample, sample_materials = test_positive_time_oxidation_contract()
    geom = test_blanket_deposition_supported()
    run_guards(sample, sample_materials, geom)
    print()
    print("BLANKET (MASK-LESS) STEPS: positive-time thermal oxidation (no mask / mask_spans_um=[] / masked) = UNSUPPORTED_BY_MODEL / "
          "OXIDATION_CAPABILITY_PROOF_MISSING with 0 solver calls and only the fresh virgin Si returned; blanket deposition is a supported "
          "path (deposited SiO2 film on Si, no Mask). VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
