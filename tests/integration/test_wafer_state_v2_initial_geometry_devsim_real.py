#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 -- the EXPLICIT initial-geometry production path, end to
end through real DevSim (the user's P0 "명시적 초기 geometry 초기화 경로").

Branch A (this file's main scenarios): the initial 2D silicon rectangle
comes from AUTHORITATIVE recipe input -- `x_extent_um` / `silicon_depth_um`
-- via `initial_wafer_state_from_recipe()` -> `initialize_wafer_state()`.
That MODELLED `WaferStateV2` is threaded as `prior_state` into
`advance_wafer_state(..., "doping")`, the dopant attaches to the real Si
instance, and `apply_doping()` writes a real numeric per-node NetDoping
that DevSim then solves. The exported mesh is used ONLY as validation
evidence that the recipe bounds match the real geometry -- never as the
bounds source.

  1. explicit-rectangle virgin Si -> uniform doping -> apply_doping ->
     real DevSim NetDoping numeric write + Poisson-only solve, checked
     against the analytic built-in potential.
  2. explicit-rectangle virgin Si -> step junction -> BLOCKED (Batch 7E):
     `canonical_node_doping()` refuses 2D DevSim transport for an ACTIVE
     step_junction_v1 attachment (reason_code
     STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED) -- Batch 7D Rev.2's own
     real L0-L5 mesh-refinement study
     (docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2) found
     the 2D step-junction terminal current, peak ElectricField and R1/R2
     representation agreement do not converge. The canonical donor/
     acceptor/net concentration itself stays real and queryable from
     WaferStateV2.net_doping_at() -- this scenario asserts that fail-closed
     contract directly (0 DevSim doping writes, 0 solves), not a solved PN
     sweep. A real, converged 2D step-junction PN solve is no longer
     claimed anywhere in this file; see
     tests/integration/test_step_junction_2d_gate_real.py for the fuller
     2D/1D/CLI/bypass proof of this same gate.

Branch B (fail-closed guard, same file): once a real non-representable
process step is advanced with `transform=None`, the state goes
UNRESOLVED and `apply_doping()` raises `UnsupportedDopingState` and
writes nothing -- the solve is blocked, not fed a zeroed NetDoping.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "silicon_depth_um": 2.0,
}


def _bare_rectangle_process_result(tmp):
    """A genuine virgin Si rectangle: make_mask_spans with an empty span
    set (no resist), floored at silicon_depth_um. This is the geometry
    initial_wafer_state_from_recipe() describes exactly."""
    from tcad.backends.viennaps import session as _session
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result

    domain = _session.make_mask_spans(
        grid_delta_um=RECIPE["grid_delta_um"],
        x_extent_um=RECIPE["x_extent_um"],
        y_extent_um=RECIPE["y_extent_um"],
        spans_um=[],
        mask_height_um=0.1,
        substrate_depth_um=RECIPE["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(
        domain, str(Path(tmp) / "virgin_wafer"),
        floor_depth_um=RECIPE["silicon_depth_um"],
    )
    return build_process_result({"final_mesh": mesh_path, "snapshots": []})


def _assert_mesh_matches_recipe_bounds(process_result):
    """VALIDATION EVIDENCE ONLY -- the mesh confirms the recipe bounds
    are physical; it is never the source of them."""
    import meshio

    mesh = meshio.read(process_result.volume_mesh_path)
    xs = mesh.points[:, 0]
    ys = mesh.points[:, 1]
    half_x = RECIPE["x_extent_um"] / 2.0
    # ViennaPS pads the domain box slightly; tolerate ~1 grid cell.
    tol = RECIPE["grid_delta_um"] * 1.5
    assert abs(xs.min() - (-half_x)) < tol, (xs.min(), -half_x)
    assert abs(xs.max() - half_x) < tol, (xs.max(), half_x)
    assert abs(ys.max() - 0.0) < tol, ys.max()
    assert abs(ys.min() - (-RECIPE["silicon_depth_um"])) < tol, (
        ys.min(), -RECIPE["silicon_depth_um"])


def _builtin_potential_spread(device, region):
    import devsim

    pot = devsim.get_node_model_values(device=device, region=region, name="Potential")
    return max(pot) - min(pot), pot


def scenario_uniform():
    import devsim
    from tcad.physics.doping import apply_uniform_doping
    from tcad.physics.wafer_state_accumulation import (
        advance_wafer_state, initial_wafer_state_from_recipe,
    )
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.device.devsim.semiconductor_equation import (
        setup_semiconductor_potential_equation,
    )
    from tcad.device.devsim.resistor_equation import set_bias
    from devsim.python_packages import simple_physics as sp

    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)
        _assert_mesh_matches_recipe_bounds(process_result)

        n_doping = 1.0e17
        doped = apply_uniform_doping(process_result, {"Si": n_doping}, chemical_state="ACTIVE")

        # Branch A: MODELLED initial state from the RECIPE, threaded as
        # prior_state -- NOT advance_wafer_state(None, ...).
        state = initial_wafer_state_from_recipe(RECIPE)
        init_cell = state.active_cells()[0]
        assert init_cell.is_modelled and init_cell.material == "Si"
        assert init_cell.bounds_um == (-2.0, 2.0, -2.0, 0.0), init_cell.bounds_um

        state = advance_wafer_state(state, doped, "doping")
        assert state.attachments, "dopant must attach to the MODELLED Si instance"

        imported = import_process_result(
            doped, mesh_name="v2init_uniform_mesh",
            device_name="v2init_uniform_dev",
            contact_regions=["Si"], contact_axis="x",
        )
        # Real numeric per-node write -- must NOT raise UnsupportedDopingState.
        apply_doping(imported.device, "Si", state)

        nd = devsim.get_node_model_values(
            device=imported.device, region="Si", name="NetDoping")
        assert min(nd) == max(nd) == n_doping, (min(nd), max(nd))

        setup_semiconductor_potential_equation(
            imported.device, "Si", imported.contacts, temperature_k=300.0)
        for c in imported.contacts:
            set_bias(imported.device, c, 0.0)
        devsim.solve(type="dc", solver_type="direct",
                     absolute_error=1e10, relative_error=1e-10,
                     maximum_iterations=30)

        spread, pot = _builtin_potential_spread(imported.device, "Si")
        # Uniform doping -> flat potential (single built-in contact value,
        # no junction). Analytic contact potential = V_t*ln(Nd/n_i).
        v_t = sp.V_t if hasattr(sp, "V_t") else 0.02585
        n_i = getattr(sp, "n_i", 1.0e10)
        expected = v_t * math.log(n_doping / n_i)
        assert spread < 1e-3, f"uniform doping must give a flat potential, spread={spread:.3e}"
        assert abs(pot[0] - expected) < 0.05, (pot[0], expected)

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)
        print(f"  [uniform] NetDoping written = {n_doping:.1e} cm^-3 at every "
              f"node; solved Potential = {pot[0]:.4f} V (analytic {expected:.4f} V)")

        # ---- Branch B guard: a fail-closed step blocks the solve ----
        from tcad.device.devsim.doping_mapping import UnsupportedDopingState

        blocked = advance_wafer_state(state, doped, "etching", transform=None)
        imported2 = import_process_result(
            doped, mesh_name="v2init_blocked_mesh",
            device_name="v2init_blocked_dev",
            contact_regions=["Si"], contact_axis="x",
        )
        try:
            apply_doping(imported2.device, "Si", blocked)
        except UnsupportedDopingState as exc:
            assert "must not proceed" in str(exc)
            # apply_doping raised BEFORE registering any node model, so
            # NetDoping does not exist at all -- the strongest possible
            # "wrote nothing".
            try:
                devsim.get_node_model_values(
                    device=imported2.device, region="Si", name="NetDoping")
                raise AssertionError("NetDoping must not have been written")
            except devsim.error:
                pass
            print("  [branch B] fail-closed etch -> UnsupportedDopingState, "
                  "no NetDoping node model created, solve blocked")
        else:
            raise AssertionError(
                "a fail-closed state must block apply_doping, not write zeros")
        finally:
            devsim.delete_device(device=imported2.device)
            devsim.delete_mesh(mesh=imported2.mesh)


def scenario_step_junction():
    """Batch 7E: an ACTIVE step_junction_v1 attachment on a 2D DevSim
    device is now refused by the central gate
    (STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED) -- see this module's
    own docstring for why. This asserts the fail-closed contract exactly:
    the canonical donor/acceptor/net concentration stays real (queried
    directly from WaferStateV2, unaffected by the gate), while 2D DevSim
    transport (doping write + solve) does not happen at all."""
    import devsim
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.physics.wafer_state_accumulation import (
        advance_wafer_state, initial_wafer_state_from_recipe,
    )
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.doping_mapping import UnsupportedDopingState, apply_doping

    with tempfile.TemporaryDirectory() as tmp:
        process_result = _bare_rectangle_process_result(tmp)

        donor = 1.0e18
        acceptor = 1.0e18
        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x",
            junction_position_um=0.0,
            donor_conc_cm3=donor, acceptor_conc_cm3=acceptor, chemical_state="ACTIVE",
        )

        state = initial_wafer_state_from_recipe(RECIPE)
        state = advance_wafer_state(state, doped, "doping")
        assert state.attachments

        # The canonical concentration is preserved and directly queryable
        # -- the gate below affects only 2D DevSim TRANSPORT, never this.
        q_right = state.net_doping_at(1.0, -1.0)
        q_left = state.net_doping_at(-1.0, -1.0)
        assert q_right.donor_concentration == donor and q_right.acceptor_concentration == 0.0, q_right
        assert q_left.donor_concentration == 0.0 and q_left.acceptor_concentration == acceptor, q_left

        scale = 1.0e-4  # um -> cm, same as Phase 8
        imported = import_process_result(
            doped, mesh_name="v2init_step_mesh",
            device_name="v2init_step_dev",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=scale,
            refine_near_um=0.0, refine_axis="x",
        )
        try:
            assert devsim.get_dimension(device=imported.device) == 2, "fixture is broken -- expected a 2D device"
            try:
                apply_doping(imported.device, "Si", state, length_scale_to_cm=scale)
            except UnsupportedDopingState as exc:
                status = exc.physics_status
                assert status["reason_code"] == "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED", status
                assert status["resolution"] == "UNSUPPORTED_BY_MODEL", status
                assert status["blocked_nodes"] == status["total_nodes"] > 0, status
            else:
                raise AssertionError(
                    "a 2D ACTIVE step_junction_v1 attachment must be refused, not solved -- "
                    "see docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2")
            # apply_doping raised BEFORE registering any node model -- the
            # strongest possible "wrote nothing", same as Branch B below.
            try:
                devsim.get_node_model_values(
                    device=imported.device, region="Si", name="NetDoping")
                raise AssertionError("NetDoping must not have been written")
            except devsim.error:
                pass
            print(f"  [step junction] BLOCKED as STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED: "
                  f"canonical donor/acceptor preserved (right of junction {(q_right.donor_concentration, q_right.acceptor_concentration)}, "
                  f"left {(q_left.donor_concentration, q_left.acceptor_concentration)}), "
                  f"no NetDoping node model created, no solve run")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def main():
    if not viennaps_session.is_available():
        print("SKIPPED: ViennaPS is not installed")
        return
    if not devsim_backend.is_available():
        print("SKIPPED: DevSim is not installed")
        return

    print("[1/2] explicit-rectangle virgin Si -> uniform doping -> real DevSim")
    scenario_uniform()
    print("[2/2] explicit-rectangle virgin Si -> step junction -> real DevSim")
    scenario_step_junction()
    print("PASS: WaferState v2 explicit initial-geometry path writes real "
          "numeric NetDoping and solves for uniform doping; a fail-closed "
          "state, and a 2D ACTIVE step_junction_v1 attachment "
          "(STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED, Batch 7E), both "
          "block the solve while the canonical state stays queryable.")


if __name__ == "__main__":
    main()
