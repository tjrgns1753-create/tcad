#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7E -- real-DevSim proof of the 2D step-junction mesh-convergence gate
(items B, C, D, F, G of the bounded prompt).

Batch 7D Rev.2's own real L0-L5 mesh-refinement study
(docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2) found the 2D
step-junction terminal current, peak ElectricField and R1/R2 representation
agreement do NOT converge. This file proves, against the REAL installed
ViennaPS 4.6.2 + DevSim, that `canonical_node_doping()` now refuses 2D DevSim
TRANSPORT for an ACTIVE step_junction_v1 attachment (reason_code
STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED) while:
  B. still writing 0 doping node models and running 0 solves for the blocked
     2D case, and still returning the real canonical concentration directly
     from WaferStateV2.net_doping_at() (never masked/zeroed);
  C. NOT blocking the identical canonical state on a real 1D public DevSim
     device (devsim.get_dimension() == 1) -- proving the gate is genuinely
     2D-specific, not activation/compensation-driven;
  D. NOT blocking a 2D uniform ACTIVE control all the way through a real
     potential-only equilibrium SOLVE, not merely a NetDoping write (the
     gate must not be over-broad; Batch 7E Rev.1 P1) -- a separate,
     independent control from the step-junction scenarios, never reusing
     a step-junction number;
  F. the real CLI entry point (`tcad.cli.run_pipeline._apply_device_doping`,
     the exact function `run_pipeline()`/`main()` call for doping) enforces
     the identical gate, and `main()`'s own exception propagation is loud
     (no try/except swallows UnsupportedDopingState between it and
     run_pipeline());
  G. `tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium` (the
     OTHER production caller of the central gate, used by the robust/
     implant-windows solve path) cannot bypass this gate either -- it calls
     `canonical_node_doping()` first, exactly like `apply_doping()` does.

KNOWN, PRE-EXISTING, UNRELATED DEFECT FOUND DURING THIS INVESTIGATION (NOT
fixed here -- out of scope for this bounded prompt; see the Batch 7E chat
report): `advance_wafer_state(None, <ViennaPS-mesh-derived ProcessResult>,
"doping")`'s LEGACY fallback (`legacy_state_from_v1_cells()`) currently
produces LEGACY_UNRESOLVED cells with no exact bounds for several existing
real tests (test_voltage_probe_real.py, test_phase8_pn_junction_real.py,
test_gui_measurement_doping_kinds_real.py,
test_auto_refine_from_doping_real.py), and
`test_dopant_profile_matches_devsim_real.py` separately fails on an
unrelated uniform donor/acceptor-split case before ever reaching its own
step_junction scenario. All five were independently confirmed to fail
IDENTICALLY with this Batch 7E gate's own code temporarily removed, so this
is not a regression from this change. `run_pipeline()`'s own top-level
config schema requires `process.category` (for `_run_process_step`) while
`_apply_device_doping()` unconditionally fail-closes (`transform=None`) any
state whose recipe carries explicit `x_extent_um`/`silicon_depth_um`
together with a truthy `category` -- so there is currently NO config that
reaches a real, cleanly-modelled 2D doped device through the full
`run_pipeline()` top-level function; this file therefore calls
`_apply_device_doping()` directly (still 100% real, unmodified CLI
production code) for item F, with `process_cfg` carrying no `category` key
so `_initial_state_for_process()`'s own real, unmocked
`initial_wafer_state_from_recipe()` path is exercised without also hitting
that separate, pre-existing limitation.
"""
import inspect
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

from tcad.backends.viennaps.io import save_volume_mesh
from tcad.characterization.robust_iv_sweep import ramp_doping_to_equilibrium
from tcad.cli.run_pipeline import _apply_device_doping, run_pipeline
from tcad.device.devsim.doping_mapping import UnsupportedDopingState, apply_doping
from tcad.device.devsim.mesh_import import import_process_result
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping
from tcad.physics.wafer_state_accumulation import (
    advance_wafer_state, initial_wafer_state_from_recipe,
)

RECIPE = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
LENGTH_SCALE_TO_CM = 1.0e-4
REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"


def _bare_rectangle_process_result(tmp):
    domain = viennaps_session.make_mask_spans(
        grid_delta_um=RECIPE["grid_delta_um"], x_extent_um=RECIPE["x_extent_um"],
        y_extent_um=RECIPE["y_extent_um"], spans_um=[], mask_height_um=0.1,
        substrate_depth_um=RECIPE["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, str(Path(tmp) / "virgin_wafer"),
                                 floor_depth_um=RECIPE["silicon_depth_um"])
    return build_process_result({"final_mesh": mesh_path, "snapshots": []})


class _SolveCounter:
    """Counts real devsim.solve() calls without altering their behavior."""

    def __init__(self):
        self.n = 0
        self._orig = devsim.solve

    def __enter__(self):
        def counting(*a, **k):
            self.n += 1
            return self._orig(*a, **k)
        devsim.solve = counting
        return self

    def __exit__(self, *exc):
        devsim.solve = self._orig


def check_b_2d_canonical_gate():
    """B: real 2D device, ACTIVE step_junction_v1 -> gate fires; canonical
    concentrations stay real and queryable; 0 writes; 0 solves."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e17, acceptor_conc_cm3=1.0e17, chemical_state="ACTIVE",
        )
        state = initial_wafer_state_from_recipe(RECIPE)
        state = advance_wafer_state(state, doped, "doping")
        assert state.attachments, "fixture is broken -- no attachment was created"

        # item 8 of the report: the canonical DIRECT query is unaffected by the gate.
        q = state.net_doping_at(1.0, -1.0)
        assert q.donor_concentration == 1.0e17 and q.acceptor_concentration == 0.0 and q.net_doping == 1.0e17, (
            f"canonical direct query must still report real numbers: {q}")
        q_left = state.net_doping_at(-1.0, -1.0)
        assert q_left.donor_concentration == 0.0 and q_left.acceptor_concentration == 1.0e17, q_left
        print(f"  [B] canonical direct query preserved: x=+1um -> {(q.donor_concentration, q.acceptor_concentration, q.net_doping)}, "
              f"x=-1um -> {(q_left.donor_concentration, q_left.acceptor_concentration, q_left.net_doping)}")

        imported = import_process_result(
            doped, mesh_name="b_gate_mesh", device_name="b_gate_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        try:
            dimension = devsim.get_dimension(device=imported.device)
            assert dimension == 2, f"fixture is broken -- expected a 2D device, got dimension={dimension}"
            print(f"  [B] real devsim.get_dimension(device=...) == {dimension} (public API)")

            with _SolveCounter() as sc:
                try:
                    apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
                    raise AssertionError("apply_doping must raise for an ACTIVE step_junction_v1 on a 2D device")
                except UnsupportedDopingState as exc:
                    status = exc.physics_status
                    assert status["resolution"] == "UNSUPPORTED_BY_MODEL", status
                    assert status["reason_code"] == REASON, status
                    assert status["device"] == imported.device and status["region"] == "Si", status
                    assert status["total_nodes"] == status["blocked_nodes"] > 0, status
                    assert status["first_blocked_node"] is None, status
                    assert "entries" in status and status["entries"], status
                    print(f"  [B] UnsupportedDopingState raised: reason_code={status['reason_code']!r}, "
                          f"blocked_nodes={status['blocked_nodes']}/{status['total_nodes']}")
                assert sc.n == 0, f"0 solves expected, got {sc.n}"
            for model in ("Donors", "Acceptors", "NetDoping"):
                try:
                    devsim.get_node_model_values(device=imported.device, region="Si", name=model)
                    raise AssertionError(f"{model} node model exists although the gate blocked")
                except devsim.error:
                    pass
            print("  [B] 0 devsim.solve calls, 0 Donors/Acceptors/NetDoping node models written")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def check_c_1d_reference_control():
    """C: the SAME canonical step-junction state, on a real 1D public DevSim
    device, is NOT blocked by the 2D-specific reason -- and its Donors/
    Acceptors follow the official R1 step() convention."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e17, acceptor_conc_cm3=1.0e17, chemical_state="ACTIVE",
        )
        state = initial_wafer_state_from_recipe(RECIPE)
        state = advance_wafer_state(state, doped, "doping")

        half_x_cm = 0.5 * RECIPE["x_extent_um"] * LENGTH_SCALE_TO_CM
        mesh, device = "c_1d_mesh", "c_1d_device"
        devsim.create_1d_mesh(mesh=mesh)
        devsim.add_1d_mesh_line(mesh=mesh, pos=-half_x_cm, ps=1.0e-5, tag="l")
        # An explicit mesh line exactly AT the junction (x=0.0), so a real
        # mesh node lands there to floating-point exactness -- without this,
        # DevSim's own line placement between -half_x_cm/+half_x_cm gives no
        # guarantee any node sits exactly on the junction coordinate.
        devsim.add_1d_mesh_line(mesh=mesh, pos=0.0, ps=1.0e-5)
        devsim.add_1d_mesh_line(mesh=mesh, pos=half_x_cm, ps=1.0e-5, tag="r")
        devsim.add_1d_contact(mesh=mesh, name="l", tag="l", material="metal")
        devsim.add_1d_contact(mesh=mesh, name="r", tag="r", material="metal")
        devsim.add_1d_region(mesh=mesh, material="Si", region="Si", tag1="l", tag2="r")
        devsim.finalize_mesh(mesh=mesh)
        devsim.create_device(mesh=mesh, device=device)
        try:
            dimension = devsim.get_dimension(device=device)
            assert dimension == 1, f"fixture is broken -- expected a 1D device, got dimension={dimension}"
            print(f"  [C] real devsim.get_dimension(device=...) == {dimension} (public API)")

            result = apply_doping(device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
            assert result is None, "apply_doping() returns None on full success"
            xs = [x / LENGTH_SCALE_TO_CM for x in devsim.get_node_model_values(device=device, region="Si", name="x")]
            donors = devsim.get_node_model_values(device=device, region="Si", name="Donors")
            acceptors = devsim.get_node_model_values(device=device, region="Si", name="Acceptors")
            on_j = [i for i, x in enumerate(xs) if abs(x) < 1e-9]
            assert on_j, "the 1D mesh must have a node exactly on the junction for this control to mean anything"
            assert all(donors[i] == 1.0e17 and acceptors[i] == 1.0e17 for i in on_j), \
                f"official step() convention: both polarities must fire on the junction node, got {[(donors[i], acceptors[i]) for i in on_j]}"
            assert all(d == 1.0e17 for x, d in zip(xs, donors) if x > 1e-9) and all(a == 0.0 for x, a in zip(xs, acceptors) if x > 1e-9)
            assert all(d == 0.0 for x, d in zip(xs, donors) if x < -1e-9) and all(a == 1.0e17 for x, a in zip(xs, acceptors) if x < -1e-9)
            print(f"  [C] 1D device NOT blocked by {REASON}: Donors/Acceptors written, official step() convention confirmed on {len(on_j)} junction node(s)")
            print("  [C] NOTE: this 1D success is a reference control only -- it is never generalized as proof of 2D production capability.")
        finally:
            devsim.delete_device(device=device)
            devsim.delete_mesh(mesh=mesh)


def check_d_2d_uniform_supported_control():
    """D (Batch 7E Rev.1 P1): the gate must not be over-broad. This is a
    SEPARATE, independent control from the step-junction scenarios above --
    it does not reuse or route through any step-junction number. Its own
    purpose is narrow: prove the new gate does not block a 2D ACTIVE uniform
    donor-only state all the way through to a real potential-only
    equilibrium SOLVE (not just a NetDoping write). The resulting potential
    value is NOT a new physics baseline to pin -- only "at least one real
    devsim.solve() call succeeded, with 0 STEP_JUNCTION_2D_MESH_CONVERGENCE_
    UNVERIFIED anywhere" is asserted."""
    from tcad.device.devsim.resistor_equation import set_bias
    from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation

    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        doped = apply_uniform_doping(process_result, donor_by_region_cm3={"Si": 1.0e17}, chemical_state="ACTIVE")
        state = initial_wafer_state_from_recipe(RECIPE)
        state = advance_wafer_state(state, doped, "doping")

        imported = import_process_result(
            doped, mesh_name="d_uniform_mesh", device_name="d_uniform_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        try:
            assert devsim.get_dimension(device=imported.device) == 2
            with _SolveCounter() as sc:
                result = apply_doping(imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
                assert result is None, "apply_doping() returns None on full success"
                donors = devsim.get_node_model_values(device=imported.device, region="Si", name="Donors")
                acceptors = devsim.get_node_model_values(device=imported.device, region="Si", name="Acceptors")
                nd = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
                assert set(donors) == {1.0e17} and set(acceptors) == {0.0} and set(nd) == {1.0e17}, \
                    (set(donors), set(acceptors), set(nd))
                assert min(nd) == max(nd) == 1.0e17

                # A real, supported potential-only equilibrium solve --
                # not merely a NetDoping write -- confirming the gate does
                # not block the actual SOLVE path either.
                setup_semiconductor_potential_equation(
                    imported.device, "Si", imported.contacts, temperature_k=300.0)
                for c in imported.contacts:
                    set_bias(imported.device, c, 0.0)
                devsim.solve(type="dc", solver_type="direct",
                             absolute_error=1e10, relative_error=1e-10, maximum_iterations=30)
            assert sc.n >= 1, f"expected >=1 real devsim.solve() call, got {sc.n}"
            pot = devsim.get_node_model_values(device=imported.device, region="Si", name="Potential")
            # Sanity check only (not a new physics baseline): uniform doping
            # gives an (almost) flat potential -- solver noise, not this
            # project's physics, accounts for the tiny spread.
            assert max(pot) - min(pot) < 1e-3, f"uniform doping -> flat potential expected, spread={max(pot) - min(pot):.3e}"
            print(f"  [D] 2D uniform ACTIVE control NOT blocked: NetDoping written = {set(nd)} cm^-3 at every node; "
                  f"real potential-only equilibrium solve succeeded (devsim.solve called {sc.n}x, "
                  f"solved Potential={pot[0]:.4f} V -- not saved as a new physics baseline, only 'a real solve "
                  f"ran' is asserted); {REASON} appears 0 times")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def check_f_cli_entry_point():
    """F: the real CLI doping-application function enforces the identical
    gate; and main()/run_pipeline() propagate ANY UnsupportedDopingState
    uncaught (loud failure), verified by inspecting the real source (no
    config currently reaches this gate through the FULL run_pipeline() --
    see this module's own docstring for the separate, pre-existing reason)."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        imported = import_process_result(
            process_result, mesh_name="f_cli_mesh", device_name="f_cli_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e17, acceptor_conc_cm3=1.0e17, chemical_state="ACTIVE",
        )
        try:
            with _SolveCounter() as sc:
                try:
                    _apply_device_doping(
                        imported, doped,
                        {"mesh_name": "f_cli_mesh", "device_name": "f_cli_device", "length_scale_to_cm": LENGTH_SCALE_TO_CM},
                        {"recipe": RECIPE},  # no "category" key -- see module docstring
                        netdoping_region="Si",
                    )
                    raise AssertionError("_apply_device_doping must raise for a 2D ACTIVE step junction")
                except UnsupportedDopingState as exc:
                    assert exc.physics_status["reason_code"] == REASON, exc.physics_status
                    print(f"  [F] real tcad.cli.run_pipeline._apply_device_doping() raised {REASON!r}")
                assert sc.n == 0, f"0 solves expected via the CLI entry point, got {sc.n}"
            try:
                devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
                raise AssertionError("NetDoping must not exist -- the CLI path wrote nothing")
            except devsim.error:
                pass
            print("  [F] 0 solves, 0 NetDoping node model via the CLI's own doping-application function")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)

    # Static evidence: main() has no try/except around run_pipeline() -- any
    # UnsupportedDopingState (including this new one) propagates as an
    # uncaught exception, so the process exits non-zero and prints no
    # success JSON.
    main_src = inspect.getsource(sys.modules["tcad.cli.run_pipeline"].main)
    assert "try" not in main_src, (
        "main() must have no exception handling that could swallow "
        "UnsupportedDopingState and disguise it as success:\n" + main_src)
    assert "run_pipeline(config, workdir)" in main_src and "print(json.dumps(summary" in main_src
    print("  [F] static evidence: main() has no try/except around run_pipeline() -- "
          "an UnsupportedDopingState is a loud, uncaught failure (non-zero exit), "
          "never a disguised success")


def check_g_robust_iv_sweep_cannot_bypass():
    """G: robust_iv_sweep's own direct entry point into the gate
    (`ramp_doping_to_equilibrium`, used by the implant-windows-heavy-doping
    solve path) cannot bypass the central gate either -- it calls
    `canonical_node_doping()` first, exactly like `apply_doping()` does."""
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e17, acceptor_conc_cm3=1.0e17, chemical_state="ACTIVE",
        )
        state = initial_wafer_state_from_recipe(RECIPE)
        state = advance_wafer_state(state, doped, "doping")

        imported = import_process_result(
            doped, mesh_name="g_bypass_mesh", device_name="g_bypass_device",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        try:
            with _SolveCounter() as sc:
                try:
                    ramp_doping_to_equilibrium(
                        imported.device, "Si", state, length_scale_to_cm=LENGTH_SCALE_TO_CM,
                        contacts=imported.contacts,
                    )
                    raise AssertionError("ramp_doping_to_equilibrium must raise for a 2D ACTIVE step junction")
                except UnsupportedDopingState as exc:
                    assert exc.physics_status["reason_code"] == REASON, exc.physics_status
                    print(f"  [G] real ramp_doping_to_equilibrium() (robust_iv_sweep's own gate entry) raised {REASON!r}")
                assert sc.n == 0, f"0 solves expected, got {sc.n}"
            print("  [G] 0 solves -- the central gate cannot be bypassed via the robust/continuation solve path")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def main():
    print("[B] 2D canonical gate (real ViennaPS + DevSim)")
    check_b_2d_canonical_gate()
    print("[C] 1D reference control (real public 1D DevSim device)")
    check_c_1d_reference_control()
    print("[D] 2D uniform ACTIVE supported control (gate is not over-broad)")
    check_d_2d_uniform_supported_control()
    print("[F] CLI entry point (tcad.cli.run_pipeline)")
    check_f_cli_entry_point()
    print("[G] robust_iv_sweep bypass check")
    check_g_robust_iv_sweep_cannot_bypass()
    assert not list(devsim.get_device_list()), f"leaked DevSim devices: {list(devsim.get_device_list())}"
    print("\nPASS: the 2D step-junction mesh-convergence gate (STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED) "
          "blocks 2D transport while preserving canonical concentrations, does not block the 1D reference or "
          "2D uniform controls, and cannot be bypassed via the CLI or the robust/continuation solve path.")


if __name__ == "__main__":
    main()
