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

Final-review Fix 2 adds a SECOND, separate scenario
(scenario_conversion_entry_survives, below): a real LOCOS oxidation
(Si->SiO2 CONVERSION, not removal) genuinely consumes Si at a fixed x,
while a real DevSim "Si" region node still exists there (bulk Si below
the new oxide). RECOVERY still WRITES the real value there (unchanged
behavior) -- but unlike the removal-shadowing scenario above (category
"doping", UNCLASSIFIED, entries stay suppressed, physics_status stays
None), this scenario's category is real "oxidation" (classified
"conversion" in MATERIAL_CHANGE_KIND_BY_CATEGORY), so the entry must now
SURVIVE into apply_doping()'s returned physics_status -- whether dopant
segregated during real oxide growth is genuinely unknown, and RECOVERY
writing a value does not resolve that uncertainty.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
import tcad.process.oxidation  # noqa: F401 -- registers "oxidation"/"thermal"
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping, apply_gaussian_implant_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.backends.viennaps.io import save_volume_mesh, register_locos_export

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
            acceptor_by_region_cm3={"Si": ACCEPTOR_CM3}, chemical_state="ACTIVE",
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
            # WaferState.net_doping_at() ITSELF calls self.exposed_material_at
            # ONCE per node (final-review Fix 6 hoisted this OUT of the
            # per-profile _polarity_sum loop, where it used to be called
            # once per matching-polarity profile -- i.e. len(state.
            # dopant_profiles) calls per node -- so this baseline is now
            # len(xs), not len(xs) * len(state.dopant_profiles)). That
            # baseline is subtracted out below so what remains isolates
            # ONLY apply_doping()'s OWN call site (the RECOVERY loop's
            # hoisted lookup, Important #3, unaffected by Fix 6) -- which
            # must stay at most once per DISTINCT x.
            baseline_from_net_doping_at = len(xs)
            own_calls = len(call_log) - baseline_from_net_doping_at
            print(f"[5/5] exposed_material_at called {len(call_log)} times total "
                  f"({baseline_from_net_doping_at} from WaferState's OWN "
                  f"net_doping_at(), now once per node after Fix 6's hoist) -> "
                  f"{own_calls} calls attributable to apply_doping()'s own RECOVERY "
                  f"loop, across {len(xs)} nodes x {len(state.dopant_profiles)} "
                  f"profiles ({len(xs) * len(state.dopant_profiles)} node-profile "
                  f"pairs the OLD, unhoisted code would have called it for there); "
                  f"distinct x values = {distinct_x}")
            assert 0 <= own_calls <= distinct_x, (
                f"apply_doping()'s own exposed_material_at lookup must be memoized "
                f"to at most once per distinct x ({distinct_x}), but accounted for "
                f"{own_calls} calls"
            )
            assert len(call_log) < len(xs) * len(state.dopant_profiles), (
                "must be strictly fewer TOTAL calls than the old once-per-(node,profile) "
                "count from BOTH net_doping_at() and apply_doping()'s own RECOVERY loop"
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


# --- Final-review Fix 2: a SEPARATE, real CONVERSION scenario --------
# Same real LOCOS oxidation+strip technique as Task 7's own
# test_ce2_oxidation_conversion_unsupported_real.py (reused, not
# re-derived -- each real integration test in this project keeps its
# own copy of this helper, matching
# test_gui_doping_color_overlay_real.py's own established pattern).
CONV_GRID_UM = 0.2
CONV_X_EXTENT_UM, CONV_Y_EXTENT_UM, CONV_SI_DEPTH_UM = 10.0, 8.0, 5.0
CONV_WINDOW_HALF_UM = 1.0     # LOCOS open (growth) window is x in [-1.0, +1.0]
CONV_X_UM = 0.0               # inside the open window -- genuinely converts to SiO2
CONV_PAD_STRIP_DEPTH_UM = 0.19  # fixed ahead of time -- see the CE-2 test's own comment


def _real_locos_oxidation_then_strip(tmp):
    """Real LOCOS oxidation (masked, open window |x|<=1.0) followed by a
    real mask + pad-oxide strip -- converts the open window's Si to
    SiO2 permanently while restoring real Si everywhere else. Identical
    recipe/technique to the CE-2 test (task-7)."""
    # 2026-09-08: LOCOS split out of ThermalOxidation into its own
    # registry entry ("oxidation", "locos") -- tcad/process/oxidation/
    # locos.py. Both steps below genuinely run LOCOS (mask_material set).
    step0 = registry.get("oxidation", "locos")()
    recipe0 = {
        "_process_category": "oxidation", "_process_model_key": "locos",
        "mask_left_um": -CONV_WINDOW_HALF_UM, "mask_right_um": CONV_WINDOW_HALF_UM,
        "mask_material": "Mask", "pr_thickness_um": 1.0,
        "silicon_depth_um": CONV_SI_DEPTH_UM, "grid_delta_um": CONV_GRID_UM,
        "x_extent_um": CONV_X_EXTENT_UM, "y_extent_um": CONV_Y_EXTENT_UM,
        "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
    }
    step0.run(recipe0, tmp)

    recipe1 = dict(recipe0)
    recipe1["temperature_c"], recipe1["time_hours"] = 1100.0, 8.0
    step1 = registry.get("oxidation", "locos")(inherited_domain=step0.last_domain)
    step1.run(recipe1, tmp)

    module = viennaps_session.require_viennaps()
    domain = step1.last_domain
    domain.removeMaterial(module.Material.Mask)
    register_locos_export(domain, [module.Material.Si, module.Material.SiO2], [False, True])

    strip_step = registry.get("etching", "isotropic")(inherited_domain=domain)
    strip_recipe = {
        "material_rates": {"SiO2": -CONV_PAD_STRIP_DEPTH_UM, "Si": 0.0},
        "default_rate": 0.0, "etch_time_s": 1.0,
        "silicon_depth_um": CONV_SI_DEPTH_UM,
    }
    strip_result = strip_step.run(strip_recipe, tmp)
    return {"final_mesh": strip_result["final_mesh"], "snapshots": []}


def scenario_conversion_entry_survives():
    with tempfile.TemporaryDirectory() as tmp:
        # A real bare-Si wafer (no mask, no oxide) carrying a real
        # Gaussian donor implant centered exactly at CONV_X_UM.
        domain = viennaps_session.make_mask_spans(
            grid_delta_um=CONV_GRID_UM, x_extent_um=CONV_X_EXTENT_UM,
            y_extent_um=CONV_Y_EXTENT_UM, spans_um=[], mask_height_um=0.1,
            substrate_depth_um=CONV_SI_DEPTH_UM + 1.0,
        )
        base_mesh = save_volume_mesh(domain, str(Path(tmp) / "base"), floor_depth_um=CONV_SI_DEPTH_UM)
        base = build_process_result({"final_mesh": base_mesh, "snapshots": []})

        doped = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=CONV_X_UM,
            straggle_um=0.3, donor_peak_conc_cm3=1e18, donor_species="P", chemical_state="ACTIVE",
        )
        state1 = advance_wafer_state(None, doped, "doping")

        oxidized = build_process_result(_real_locos_oxidation_then_strip(tmp))
        state2 = advance_wafer_state(state1, oxidized, "oxidation")

        converted = state2.exposed_material_at(CONV_X_UM)
        print(f"[conversion scenario] exposed_material_at({CONV_X_UM}) after real "
              f"LOCOS oxidation = {converted!r} (must NOT be 'Si' -- real field-oxide "
              f"growth in the open window)")
        assert converted != "Si", (
            "fixture is broken: expected the real LOCOS open window to genuinely "
            f"convert Si -> SiO2 at x={CONV_X_UM}, got exposed={converted!r}"
        )

        imported = import_process_result(
            oxidized, mesh_name="conversion_mesh", device_name="conversion_device",
            contact_regions=["Si"], contact_axis="x",
        )
        try:
            physics_status = apply_doping(imported.device, "Si", state2)

            xs = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
            ys = devsim.get_node_model_values(device=imported.device, region="Si", name="y")
            net = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

            # RECOVERY still WRITES the real value at the real DevSim
            # "Si" node closest to CONV_X_UM, unchanged behavior -- only
            # the DISCLOSURE differs (Fix 2 is additive to the returned
            # physics_status, never a change to what gets written).
            idx = min(range(len(xs)), key=lambda i: abs(xs[i] - CONV_X_UM))
            print(f"[conversion scenario] closest real Si node: x={xs[idx]:.4f}, "
                  f"y={ys[idx]:.4f}, DevSim NetDoping={net[idx]:.6e}")
            assert net[idx] != 0.0, (
                "RECOVERY must still write a real, non-zero value here -- Fix 2 "
                "changes disclosure only, never the write"
            )

            print(f"[conversion scenario] apply_doping()'s returned physics_status "
                  f"= {physics_status}")
            assert physics_status is not None, (
                "Fix 2: a CONVERSION-caused gap (real oxidation, Si no longer "
                "exposed at this x) must SURVIVE into the returned physics_status, "
                "not be silently suppressed the way a removal-caused gap is"
            )
            assert physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
            assert any(
                e["note"].startswith("Si no longer exposed")
                and "conversion" in e["note"]
                for e in physics_status["entries"]
            ), f"expected a real conversion-classified gap entry, got {physics_status['entries']}"
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)

        print()
        print("CONVERSION scenario VERIFIED (final-review Fix 2): RECOVERY still writes "
              "the real value at a genuinely-existing DevSim node below newly-grown "
              "oxide, but the UNSUPPORTED_BY_MODEL disclosure now correctly survives "
              "to apply_doping()'s own returned physics_status instead of being "
              "silently dropped just because a value was written.")


if __name__ == "__main__":
    main()
    scenario_conversion_entry_survives()
