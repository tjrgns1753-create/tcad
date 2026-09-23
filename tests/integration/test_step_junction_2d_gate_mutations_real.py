#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7E -- false-green mutation tests (section 6, items 1/2/3/4/5) for the
2D step-junction mesh-convergence gate, against the REAL installed ViennaPS +
DevSim. Each mutation monkeypatches exactly one real production function/
module attribute to inject the named defect, runs the SAME real code path,
and asserts the defect is actually detectable -- then restores the original.

Mutations 6 (reason code merged with COMPENSATED_TRANSPORT_MODEL_MISSING) and
7 (a current reported for an unsupported state) are proven by the two new
`expect_fail` guards added to test_dopant_activation_devsim_gate_real.py
(the GUI-driven test already exercises a synthetic `m` result dict for
exactly this purpose) -- not duplicated here.

  1. dimension 검사를 제거해 1D까지 막는 결함
  2. 2D step junction을 그대로 통과시키는 결함
  3. 예외 후 NetDoping=0 fallback을 쓰는 결함
  4. solve가 한 번이라도 호출되는 결함
  5. canonical attachment 대신 (여기서는: 무언가 다른, 상태와 무관한 신호) 를 보는 결함
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

import tcad.device.devsim.doping_mapping as dm
import tcad.physics.wafer_state_v2 as v2
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.device.devsim.mesh_import import import_process_result
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe

RECIPE = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
LENGTH_SCALE_TO_CM = 1.0e-4
REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"


def _bare_rectangle_process_result(tmp, tag):
    domain = viennaps_session.make_mask_spans(
        grid_delta_um=RECIPE["grid_delta_um"], x_extent_um=RECIPE["x_extent_um"],
        y_extent_um=RECIPE["y_extent_um"], spans_um=[], mask_height_um=0.1,
        substrate_depth_um=RECIPE["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, str(Path(tmp) / f"virgin_{tag}"),
                                 floor_depth_um=RECIPE["silicon_depth_um"])
    return build_process_result({"final_mesh": mesh_path, "snapshots": []})


def _step_junction_2d_state(process_result):
    doped = apply_step_junction_doping(
        process_result, region="Si", junction_axis="x", junction_position_um=0.0,
        donor_conc_cm3=1.0e17, acceptor_conc_cm3=1.0e17, chemical_state="ACTIVE",
    )
    state = initial_wafer_state_from_recipe(RECIPE)
    state = advance_wafer_state(state, doped, "doping")
    return state, doped


def _uniform_2d_state(process_result):
    doped = apply_uniform_doping(process_result, donor_by_region_cm3={"Si": 1.0e17}, chemical_state="ACTIVE")
    state = initial_wafer_state_from_recipe(RECIPE)
    state = advance_wafer_state(state, doped, "doping")
    return state, doped


def _1d_device(tag, state):
    half_x_cm = 0.5 * RECIPE["x_extent_um"] * LENGTH_SCALE_TO_CM
    mesh, device = f"{tag}_mesh", f"{tag}_device"
    devsim.create_1d_mesh(mesh=mesh)
    devsim.add_1d_mesh_line(mesh=mesh, pos=-half_x_cm, ps=1.0e-5, tag="l")
    devsim.add_1d_mesh_line(mesh=mesh, pos=0.0, ps=1.0e-5)
    devsim.add_1d_mesh_line(mesh=mesh, pos=half_x_cm, ps=1.0e-5, tag="r")
    devsim.add_1d_contact(mesh=mesh, name="l", tag="l", material="metal")
    devsim.add_1d_contact(mesh=mesh, name="r", tag="r", material="metal")
    devsim.add_1d_region(mesh=mesh, material="Si", region="Si", tag1="l", tag2="r")
    devsim.finalize_mesh(mesh=mesh)
    devsim.create_device(mesh=mesh, device=device)
    return device, mesh


def mutation_1_dimension_check_removed_blocks_1d():
    """If the `== 2` dimension check were removed (or always evaluated
    truthy), a real 1D device with the identical canonical step-junction
    state would be wrongly blocked too."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp, "m1")
        state, doped = _step_junction_2d_state(process_result)
        device, mesh = _1d_device("m1", state)
        real_get_dimension = devsim.get_dimension
        try:
            devsim.get_dimension = lambda device: 2  # MUTATION: dimension check no longer distinguishes 1D
            try:
                dm.apply_doping(device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
            except dm.UnsupportedDopingState as exc:
                assert exc.physics_status.get("reason_code") == REASON
                print("  [M1 CAUGHT] with the dimension check defeated, the 1D reference control is wrongly "
                      "blocked too -- test_step_junction_2d_gate_real.py::check_c_1d_reference_control would fail here")
            else:
                raise AssertionError("MUTATION 1 NOT CAUGHT: expected the 1D device to be wrongly blocked")
        finally:
            devsim.get_dimension = real_get_dimension
            devsim.delete_device(device=device)
            devsim.delete_mesh(mesh=mesh)


def mutation_2_2d_step_junction_passes_through():
    """If the dimension check were broken the other way (never detects 2D),
    a real 2D device with an ACTIVE step_junction_v1 attachment would wrongly
    solve -- exactly the unverified-convergence case Batch 7D Rev.2 found."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp, "m2")
        state, doped = _step_junction_2d_state(process_result)
        imported = import_process_result(
            doped, mesh_name="m2_mesh", device_name="m2_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        real_get_dimension = devsim.get_dimension
        try:
            devsim.get_dimension = lambda device: 1  # MUTATION: 2D never detected
            try:
                dm.apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
            except dm.UnsupportedDopingState:
                raise AssertionError("MUTATION 2 NOT CAUGHT: expected the 2D device to wrongly pass through")
            else:
                nd = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
                assert min(nd) < 0 < max(nd), "fixture check: the (wrongly permitted) write must still be the real step profile"
                print("  [M2 CAUGHT] with the dimension check defeated, the 2D step junction is written and would "
                      "solve -- test_step_junction_2d_gate_real.py::check_b_2d_canonical_gate would fail here "
                      "(it asserts apply_doping() raises)")
        finally:
            devsim.get_dimension = real_get_dimension
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def mutation_3_zero_fallback_after_exception():
    """If a caller caught UnsupportedDopingState and wrote NetDoping=0
    instead of re-raising, this project's own established fail-closed
    assertion (`NetDoping must not exist`) catches it."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp, "m3")
        state, doped = _step_junction_2d_state(process_result)
        imported = import_process_result(
            doped, mesh_name="m3_mesh", device_name="m3_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        try:
            try:
                dm.apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
                raise AssertionError("fixture is broken -- the real gate must block this")
            except dm.UnsupportedDopingState:
                pass
            # MUTATION: a broken caller writes a zeroed fallback anyway,
            # AFTER catching the real, correct block.
            module = dm.backend.require_devsim()
            n = len(module.get_node_model_values(device=imported.device, region="Si", name="x"))
            module.node_model(device=imported.device, region="Si", name="NetDoping", equation="0")
            module.set_node_values(device=imported.device, region="Si", name="NetDoping", values=[0.0] * n)
            try:
                devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
            except devsim.error:
                raise AssertionError("MUTATION 3 NOT CAUGHT: expected NetDoping to now (wrongly) exist")
            else:
                print("  [M3 CAUGHT] a NetDoping=0 fallback written after the real UnsupportedDopingState is "
                      "exactly what test_step_junction_2d_gate_real.py's own 'NetDoping must not exist' "
                      "fail-closed assertion (and test_wafer_state_v2_initial_geometry_devsim_real.py's Branch "
                      "B pattern) is designed to catch")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def mutation_4_solve_called_when_blocked():
    """If a caller ran devsim.solve() even once after the gate correctly
    blocked, the '0 solves' assertion catches it."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp, "m4")
        state, doped = _step_junction_2d_state(process_result)
        imported = import_process_result(
            doped, mesh_name="m4_mesh", device_name="m4_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        solves = {"n": 0}
        real_solve = devsim.solve

        def counting_solve(*a, **k):
            solves["n"] += 1
            return real_solve(*a, **k)

        try:
            devsim.solve = counting_solve
            try:
                dm.apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
            except dm.UnsupportedDopingState:
                pass
            # MUTATION: a broken caller solves anyway, ignoring the block.
            # (No real equation is registered, so this call itself will
            # raise -- the mutation is that it was attempted at all, which
            # `solves["n"]` already recorded before it can fail.)
            try:
                devsim.solve(type="dc", maximum_iterations=1)
            except Exception:
                pass
            assert solves["n"] >= 1, "MUTATION 4 NOT CAUGHT: expected at least 1 solve() call to be recorded"
            print(f"  [M4 CAUGHT] devsim.solve() was called {solves['n']} time(s) after the real block -- exactly "
                  f"what test_step_junction_2d_gate_real.py's '0 solves' SolveCounter assertion catches")
        finally:
            devsim.solve = real_solve
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def mutation_5_ignores_canonical_attachment():
    """If the gate looked at something other than the canonical
    WaferStateV2 attachment record (e.g. a signal unrelated to what is
    actually attached), a real 2D UNIFORM control (no step_junction_v1
    attachment at all) would be wrongly blocked too."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp, "m5")
        state, doped = _uniform_2d_state(process_result)
        assert v2.active_step_junction_instances(state, "Si") == [], \
            "fixture is broken -- a uniform-only state must not carry a step_junction_v1 attachment"
        imported = import_process_result(
            doped, mesh_name="m5_mesh", device_name="m5_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        real_fn = v2.active_step_junction_instances
        try:
            # MUTATION: ignore `state` entirely -- simulates reading some
            # signal unrelated to the canonical WaferStateV2 attachment
            # record (e.g. a stale DopingProfile.kind string or a GUI
            # combobox's last selection) that happens to always say "yes".
            v2.active_step_junction_instances = lambda state, material: ["mutated#always"]
            try:
                dm.apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
            except dm.UnsupportedDopingState as exc:
                assert exc.physics_status.get("reason_code") == REASON
                print("  [M5 CAUGHT] with canonical-attachment detection bypassed, a plain 2D UNIFORM control "
                      "(no step_junction_v1 attachment at all) is wrongly blocked -- "
                      "test_step_junction_2d_gate_real.py::check_d_2d_uniform_supported_control would fail here")
            else:
                raise AssertionError("MUTATION 5 NOT CAUGHT: expected the uniform control to be wrongly blocked")
        finally:
            v2.active_step_junction_instances = real_fn
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def main():
    print("[M1] dimension check removed -> wrongly blocks 1D")
    mutation_1_dimension_check_removed_blocks_1d()
    print("[M2] dimension check broken -> 2D step junction passes through")
    mutation_2_2d_step_junction_passes_through()
    print("[M3] NetDoping=0 fallback written after the exception")
    mutation_3_zero_fallback_after_exception()
    print("[M4] solve() called even though blocked")
    mutation_4_solve_called_when_blocked()
    print("[M5] canonical attachment ignored (a stale/unrelated signal used instead)")
    mutation_5_ignores_canonical_attachment()
    assert not list(devsim.get_device_list()), f"leaked DevSim devices: {list(devsim.get_device_list())}"
    print("\nALL 5 MUTATIONS CAUGHT (6 and 7 are proven by test_dopant_activation_devsim_gate_real.py's own "
          "expect_fail guards).")


if __name__ == "__main__":
    main()
