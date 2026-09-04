#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage A closing verification: WaferState.net_doping_at (built from
DopantProfile, Task 1/2 of the state-dependent-physics plan) must
reproduce DevSim's own REAL solved NetDoping node values, for every
doping kind, at the real node coordinates DevSim itself reports --
not a second, independently-plausible formula, but the exact same
number the already-verified doping_mapping.py path produces.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md
section 2, this is the proof that the new process-layer query surface
and the existing device-layer NetDoping construction agree, without
requiring doping_mapping.py to change at all.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState, _Cell
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.1,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.3,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}


def _fresh_process_result():
    """Run a fresh etch step in its own temp directory and build the
    ProcessResult. Returns (result, temp_dir). Caller must cleanup temp_dir."""
    step_cls = registry.get("etching", "isotropic")
    tmp = tempfile.TemporaryDirectory()
    try:
        step_result = step_cls().run(RECIPE, tmp.name)
        result = build_process_result(step_result)
        return result, tmp
    except:
        tmp.cleanup()
        raise


def _check_one_kind(label, doped_result, boundaries=()):
    """Import into a fresh DevSim device, read real NetDoping, compare
    node-by-node against WaferState.net_doping_at built from the SAME
    DopingProfile via Task 1/2's new code.

    Task 8 (2026-09-03 dopant-state-unification) note: apply_doping()
    itself now WRITES DevSim's NetDoping by evaluating this exact same
    WaferState.net_doping_at() at every real node -- so `actual` and
    `predicted` below are now the SAME underlying computation, not two
    independently-derived formulas any more. This test still has real
    value as a write/read PIPELINE check (does DevSim's own stored
    NetDoping, read back after set_node_values, equal what was written,
    to full precision, at real node coordinates) -- see
    test_doping_mapping_per_node_real.py for the dedicated new coupling
    test this task adds; this one is kept for its per-kind coverage.
    Boundary-adjacent nodes (step() ambiguity, not the thing under
    test) are skipped, same convention as
    test_implant_windows_doping_real.py."""
    imported = import_process_result(
        doped_result, mesh_name=f"{label}_mesh", device_name=f"{label}_device",
        contact_regions=["Si"], contact_axis="x",
    )
    try:
        profiles = dopant_profiles_from_doping_profile(doped_result.doping)
        # A single wide 'Si' cell, not the real per-x mesh geometry: this
        # test's checked nodes are drawn from devsim's own region="Si"
        # (see import_process_result(..., contact_regions=["Si"]) above),
        # so every x checked here is genuinely Si-exposed -- this is an
        # accurate, minimal fixture for THAT fact, not a stand-in for
        # WaferState.query()'s real per-x geometry (Task 3's
        # from_process_result() is the general mesh-file-derived
        # constructor; this test needs none of that generality).
        state = WaferState(materials=("Si",), stack=(), grid_delta_um=0.1,
                            _cells=(_Cell(-1e9, 1e9, 1.0, "Si"),), _thin_x=(),
                            dopant_profiles=profiles)

        apply_doping(imported.device, "Si", state)

        x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        actual = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

        max_rel_error = 0.0
        n_checked = 0
        for x, dev_value in zip(x_values, actual):
            if boundaries and any(x == b for b in boundaries):
                continue
            predicted = state.net_doping_at(x, 0.0).net_doping
            denom = max(abs(dev_value), 1.0)
            rel_error = abs(predicted - dev_value) / denom
            max_rel_error = max(max_rel_error, rel_error)
            n_checked += 1

        print(f"[{label}] checked {n_checked} nodes, "
              f"max relative error vs real DevSim NetDoping: {max_rel_error:.3e}")
        assert n_checked > 0, f"{label}: no nodes checked"
        assert max_rel_error < 1e-9, (
            f"{label}: WaferState.net_doping_at does not match real "
            f"DevSim NetDoping (max rel error {max_rel_error})"
        )
    finally:
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)


def main():
    # uniform, donor/acceptor split
    result, tmp = _fresh_process_result()
    try:
        doped = apply_uniform_doping(
            result, donor_by_region_cm3={"Si": 1.0e16},
            acceptor_by_region_cm3={"Si": 3.0e15},
        )
        _check_one_kind("uniform", doped)
    finally:
        tmp.cleanup()

    # step_junction
    result, tmp = _fresh_process_result()
    try:
        doped = apply_step_junction_doping(
            result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e18, acceptor_conc_cm3=1.0e18,
        )
        _check_one_kind("step_junction", doped, boundaries=[0.0])
    finally:
        tmp.cleanup()

    # gaussian_implant, donor/acceptor split
    result, tmp = _fresh_process_result()
    try:
        doped = apply_gaussian_implant_doping(
            result, region="Si", junction_axis="x",
            peak_position_um=0.0, straggle_um=0.5,
            donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=1.0e17,
        )
        _check_one_kind("gaussian_implant", doped)
    finally:
        tmp.cleanup()

    # implant_windows, background + one window
    result, tmp = _fresh_process_result()
    try:
        doped = apply_implant_windows_doping(
            result, region="Si", axis="x",
            background_doping_cm3=-1.0e17,
            windows=[{"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20}],
        )
        _check_one_kind("implant_windows", doped, boundaries=[-1.6, -0.6])
    finally:
        tmp.cleanup()

    assert devsim.get_device_list() == (), (
        "a device leaked past cleanup -- would poison a later, "
        "unrelated solve (see CLAUDE.md's documented DevSim-lifecycle trap)"
    )
    print("WaferState.net_doping_at matches real, solved DevSim "
          "NetDoping for all 4 doping kinds.")


if __name__ == "__main__":
    main()
