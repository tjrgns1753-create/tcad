#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 8 fix round 1 -- dedicated coverage for the RECOVERY mechanism
inside apply_doping() (tcad/device/devsim/doping_mapping.py), which
Task 8's own test (test_doping_mapping_per_node_real.py) deliberately
never exercises (that test uses a no-mask, blanket-etch fixture
specifically so exposed_material_at(x) == "Si" everywhere).

Real ViennaPS mesh with a leftover litho/hard "Mask" OUTSIDE its own
opening -- the same mask_left_um/mask_right_um isotropic-etch recipe
test_gaussian_implant_doping_real.py already uses, where the opening
([1.5, 2.5]) sits almost entirely outside the domain (x_extent_um=4.0,
domain centered on 0), so nearly the whole wafer is a BULK Si node
sitting under a leftover surface Mask -- exactly the shadowing case
RECOVERY exists for.

Proves, with real printed evidence:
  1. exposed_material_at(x) reports "Mask" (not "Si") at a bulk-Si x.
  2. state.net_doping_at() ALONE (no recovery) reports that
     contribution as 0 with a genuine UNSUPPORTED_BY_MODEL gap.
  3. apply_doping()'s real, solved DevSim NetDoping at that exact node
     is the profile's REAL, non-zero concentration -- RECOVERY fired
     and wrote the correct value, not a silent zero.
  4. apply_doping()'s own returned physics_status is None -- the
     recovered contribution is NOT reported as a gap (Important #2).
  5. state.exposed_material_at is called at most once per DISTINCT x
     across the whole node loop, even with 2 accumulated profiles --
     proving the hoist-and-memoize fix (Important #3), not merely
     "still passes".
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

# Same recipe test_gaussian_implant_doping_real.py uses. Note (found by
# direct execution, not assumed): MakeTrench's mask_left_um/
# mask_right_um path uses only their DIFFERENCE as the opening WIDTH
# and always CENTERS that window on x=0 (CLAUDE.md's own documented
# "mask position is now real [for mask_spans_um]... the old mask_left/
# mask_right path ... always centres the window") -- so the real open
# window here is [-0.5, +0.5], not [1.5, 2.5], and everywhere else
# (confirmed with a standalone probe: x=-2.0..-0.5 and +0.5..+2.0 all
# read back exposed_material_at(x) == "Mask") is bulk Si sitting under
# a leftover, never-stripped Mask -- exactly the shadowing case
# RECOVERY exists for.
RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}

DONOR_CM3 = 1.0e17
ACCEPTOR_CM3 = 5.0e16
EXPECTED_NET = DONOR_CM3 - ACCEPTOR_CM3  # uniform, so this is the value EVERYWHERE

BULK_X_UM = 1.0  # well under the leftover Mask (real open window is [-0.5, +0.5])


def main():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        process_result = build_process_result(step_result)

        # Two profiles (donor + acceptor), both host_material="Si", so
        # the RECOVERY loop and the exposed_material_at() memoization
        # both get exercised with more than one accumulated profile.
        doped_result = apply_uniform_doping(
            process_result,
            donor_by_region_cm3={"Si": DONOR_CM3},
            acceptor_by_region_cm3={"Si": ACCEPTOR_CM3},
        )
        state = advance_wafer_state(None, doped_result, "doping")

        # --- (1) exposed_material_at() really reports the shadowing
        # leftover Mask, not Si, at a bulk-Si x. ---
        exposed = state.exposed_material_at(BULK_X_UM)
        print(f"[1/5] state.exposed_material_at({BULK_X_UM}) = {exposed!r} "
              f"(must NOT be 'Si' -- this is the shadowing leftover Mask)")
        assert exposed != "Si", (
            f"fixture is broken: expected a leftover Mask to shadow x={BULK_X_UM}, "
            f"got exposed={exposed!r}"
        )

        # --- (2) net_doping_at() ALONE (no recovery) reports a real
        # gap and a zero contribution at that same point. ---
        raw = state.net_doping_at(BULK_X_UM, 0.0)
        print(f"[2/5] state.net_doping_at({BULK_X_UM}, 0.0) BEFORE recovery: "
              f"net_doping={raw.net_doping:.3e}, physics_status={raw.physics_status}")
        assert raw.net_doping == 0.0, (
            "the raw, un-recovered query must report 0 -- both profiles' "
            "host_material ('Si') is shadowed by the leftover Mask here"
        )
        assert raw.physics_status is not None, (
            "the raw, un-recovered query must flag a real gap here"
        )

        # --- import into a real DevSim device and run the real
        # apply_doping() (WITH recovery). ---
        imported = import_process_result(
            doped_result, mesh_name="recovery_mesh", device_name="recovery_device",
            contact_regions=["Si"], contact_axis="x",
        )
        try:
            # --- (5) instrument exposed_material_at to prove it's
            # called at most once per DISTINCT x across the WHOLE node
            # loop (2 profiles accumulated) -- Important #3. ---
            call_log = []
            original_exposed_at = state.exposed_material_at

            def counting_exposed_at(x):
                call_log.append(x)
                return original_exposed_at(x)

            object.__setattr__(state, "exposed_material_at", counting_exposed_at)

            physics_status = apply_doping(imported.device, "Si", state)

            xs = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
            ys = devsim.get_node_model_values(device=imported.device, region="Si", name="y")
            net = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

            distinct_x = len({round(x, 9) for x in xs})
            # WaferState.net_doping_at() ITSELF (wafer_state.py, out of
            # this task's scope, untouched) calls self.exposed_material_at
            # once per matching-polarity profile inside _polarity_sum --
            # i.e. len(state.dopant_profiles) calls per node, UNAVOIDABLY,
            # every time apply_doping() calls state.net_doping_at(x_um,
            # y_um) (once per node, unchanged by this fix). That baseline
            # is subtracted out below so what remains isolates ONLY
            # apply_doping()'s OWN call site (the RECOVERY loop's hoisted
            # lookup) -- which the fix must bring down to at most once per
            # DISTINCT x, from the old once-per-(node,profile).
            baseline_from_net_doping_at = len(xs) * len(state.dopant_profiles)
            own_calls = len(call_log) - baseline_from_net_doping_at
            print(f"[5/5] exposed_material_at called {len(call_log)} times total "
                  f"({baseline_from_net_doping_at} unavoidably from WaferState's "
                  f"OWN net_doping_at(), out of this task's scope) -> "
                  f"{own_calls} calls attributable to apply_doping()'s own RECOVERY "
                  f"loop, across {len(xs)} nodes x {len(state.dopant_profiles)} "
                  f"profiles ({len(xs) * len(state.dopant_profiles)} node-profile "
                  f"pairs the OLD, unhoisted code would have called it for there); "
                  f"distinct x values = {distinct_x}")
            assert own_calls <= distinct_x, (
                f"apply_doping()'s own exposed_material_at lookup must be memoized "
                f"to at most once per distinct x ({distinct_x}), but accounted for "
                f"{own_calls} calls"
            )
            assert own_calls < len(xs) * len(state.dopant_profiles), (
                "must be strictly fewer calls than the old once-per-(node,profile) count"
            )

            # --- (3) the real, solved DevSim NetDoping at the bulk
            # node closest to BULK_X_UM is the REAL recovered value,
            # not a silent zero. ---
            idx = min(range(len(xs)), key=lambda i: abs(xs[i] - BULK_X_UM))
            print(f"[3/5] closest real node: x={xs[idx]:.4f}, y={ys[idx]:.4f}, "
                  f"DevSim NetDoping={net[idx]:.6e} (expected {EXPECTED_NET:.3e})")
            assert abs(xs[idx] - BULK_X_UM) < 0.3, (
                "sanity: the closest real node must actually be near BULK_X_UM"
            )
            rel_error = abs(net[idx] - EXPECTED_NET) / max(abs(EXPECTED_NET), 1.0)
            assert rel_error < 1e-6, (
                f"RECOVERY did not fire correctly: expected NetDoping={EXPECTED_NET:.3e} "
                f"at a bulk Si node under the leftover Mask, got {net[idx]:.6e} "
                f"(rel_error={rel_error:.3e})"
            )

            # Every node (masked or open) must show the same uniform
            # value -- recovered or directly-included, the answer must
            # agree everywhere for a spatially uniform profile.
            max_rel_error = max(
                abs(n - EXPECTED_NET) / max(abs(EXPECTED_NET), 1.0) for n in net
            )
            print(f"    max relative error across ALL {len(net)} real nodes: "
                  f"{max_rel_error:.3e}")
            assert max_rel_error < 1e-6, (
                f"NetDoping must equal {EXPECTED_NET:.3e} at every node, recovered "
                f"or not; max relative error {max_rel_error:.3e}"
            )

            # --- (4) apply_doping()'s own returned physics_status must
            # NOT flag the (fully recovered) contribution as a gap. ---
            print(f"[4/5] apply_doping()'s returned physics_status = {physics_status} "
                  f"(must be None -- every gap here was actually resolved by RECOVERY)")
            assert physics_status is None, (
                f"apply_doping() must not report a gap for a fully-recovered "
                f"contribution, got {physics_status}"
            )
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)

        print()
        print("RECOVERY mechanism VERIFIED against real ViennaPS 4.6.2 + DevSim: "
              "a bulk Si node shadowed by a leftover litho Mask is correctly "
              "recovered to its real doping value, physics_status correctly "
              "omits the resolved gap, and exposed_material_at() is memoized "
              "per distinct x rather than recomputed per (node, profile).")


if __name__ == "__main__":
    main()
