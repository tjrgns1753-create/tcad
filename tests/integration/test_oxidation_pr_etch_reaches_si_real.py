#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEGACY FILENAME. This test NO LONGER RUNS ANY OXIDATION. The name is kept only so the
regression collection stays stable.

What it verifies: etch REACHABILITY and the GUI's diagnostic summary.
  * on an EXPLICIT INITIAL Si/SiO2 stack with an explicit resist mask (provenance
    DIRECT_EXPLICIT_GEOMETRY, tests/integration/_explicit_etch_fixture.py), an etch whose budget
    is smaller than the stated oxide thickness must leave the oxide in the open window and must
    not move Si, while an etch whose budget clears the oxide and bites into Si must punch through
    and move Si -- with the resist-protected Si untouched in both;
  * `_log_etch_material_summary()` (tcad/mesh/etch_diagnostics.py: a PAIRED pre/post comparison over
    the flat interior connected to the window centre) must report exactly that: for the insufficient
    budget the SiO2 vertical displacement and Si "unchanged ... overlying material remains" (it no
    longer claims "not yet reached" from a small displacement alone), for the sufficient one Si
    genuinely etched and SiO2 fully cleared -- and every number must agree with the real geometry
    measured at the CENTRAL CORE of the open window, exported AND native;
  * a blanket (coated, not developed) resist reports no open window and never one invented from a
    stale `mask_openings_um`.

The SiO2 is a structure this test STATES as an input. It is NOT an oxidation growth result, NOT a
deposited oxide, NOT a Deal-Grove result; no Si consumption is implied. Both budgets are computed
from the stated oxide thickness (formulas printed). Verdicts use NATIVE level-set positions at the
open window's central core (beyond every mask-edge effect); the exported mesh is reported separately.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

import _explicit_etch_fixture as fx

# ---- explicit INPUT geometry (requested values; chosen before any measurement) -------------
GRID_UM = 0.05
WIDTH_UM = 10.0
HALF_UM = WIDTH_UM / 2.0
Y_EXTENT_UM = 8.0
SILICON_DEPTH_UM = 5.0
OXIDE_UM = 0.2                        # Hox: 4 grid cells, a stated input
MASK_MATERIAL = "PHS"                 # the GUI's resist tag
PR_THICKNESS_UM = 1.0
WINDOW_HALF_UM = 1.5
DEVELOPED_SPANS = [[-HALF_UM, -WINDOW_HALF_UM], [WINDOW_HALF_UM, HALF_UM]]
OPEN_WINDOW = [-WINDOW_HALF_UM, WINDOW_HALF_UM]

# ---- etch budgets, computed from the stated oxide thickness (um, s) -------------------------
RATE_UM_PER_S = 0.05                  # the original test's isotropic rate, kept as a stated input
INSUFFICIENT_BUDGET_UM = 0.5 * OXIDE_UM                      # clearly smaller than Hox
SI_TARGET_UM = 3 * GRID_UM                                    # several cells of Si must be removed
SUFFICIENT_BUDGET_UM = OXIDE_UM + SI_TARGET_UM                # clears Hox, then bites SI_TARGET into Si
T_INSUFFICIENT_S = INSUFFICIENT_BUDGET_UM / RATE_UM_PER_S
T_SUFFICIENT_S = SUFFICIENT_BUDGET_UM / RATE_UM_PER_S
EXPECTED_SI_SUFFICIENT_UM = RATE_UM_PER_S * (T_SUFFICIENT_S - OXIDE_UM / RATE_UM_PER_S)
REACH_UM = RATE_UM_PER_S * T_SUFFICIENT_S                     # largest isotropic lateral reach
DEPTH_TOLERANCE_UM = GRID_UM                                  # level-set resolution


def _recipe(t):
    return {"rate": -RATE_UM_PER_S, "etch_time_s": t, "mask_material": MASK_MATERIAL,
            "silicon_depth_um": SILICON_DEPTH_UM}


def main():
    print(f"budgets from Hox={OXIDE_UM} um at rate {RATE_UM_PER_S} um/s:")
    print(f"  insufficient: budget = 0.5*Hox = {INSUFFICIENT_BUDGET_UM:.3f} um -> T = budget/rate = {T_INSUFFICIENT_S:.3f} s")
    print(f"  sufficient  : budget = Hox + {SI_TARGET_UM:.2f} (3 cells) = {SUFFICIENT_BUDGET_UM:.3f} um -> T = {T_SUFFICIENT_S:.3f} s; "
          f"expected Si depth = rate*(T - Hox/rate) = {EXPECTED_SI_SUFFICIENT_UM:.4f} um; isotropic reach = {REACH_UM:.3f} um")
    # precondition of the design (no measurement involved): at least two grid cells below Hox.
    # 0.5*Hox is exactly Hox - 2 cells at these inputs, so the bound is inclusive (float-safe).
    assert INSUFFICIENT_BUDGET_UM <= OXIDE_UM - 2 * GRID_UM + 1e-12, "insufficient budget must be clearly below Hox"
    assert EXPECTED_SI_SUFFICIENT_UM >= 3 * GRID_UM - 1e-12, "sufficient budget must bite several cells into Si"

    with tempfile.TemporaryDirectory() as tmp:
        baseline = fx.build_masked_explicit_stack(
            tmp, x_extent_um=WIDTH_UM, y_extent_um=Y_EXTENT_UM, silicon_depth_um=SILICON_DEPTH_UM,
            oxide_top_um=OXIDE_UM, grid_delta_um=GRID_UM,
            mask_spans_um=[tuple(s) for s in DEVELOPED_SPANS], mask_height_um=PR_THICKNESS_UM,
            mask_material=MASK_MATERIAL, reach_um=REACH_UM)
        print(fx.describe_baseline(baseline))
        assert baseline.forbidden_call_counts == {"Oxidation": 0, "Process": 0}, baseline.forbidden_call_counts
        assert all(v <= 1e-12 for v in baseline.mask_creation_native_shift_um.values()), \
            baseline.mask_creation_native_shift_um
        assert list(baseline.requested["mask"]["open_window_um"]) == OPEN_WINDOW

        insufficient = fx.run_etch_on_independent_copy(baseline, "isotropic", _recipe(T_INSUFFICIENT_S), tmp, "insufficient")
        sufficient = fx.run_etch_on_independent_copy(baseline, "isotropic", _recipe(T_SUFFICIENT_S), tmp, "sufficient")
        for o in (insufficient, sufficient):
            assert o.copy_matches_baseline["exported_mesh_identical"], o.copy_matches_baseline
            assert all(v <= 1e-12 for v in o.copy_matches_baseline["native_max_abs_dy_um"].values())
            assert o.oxidation_calls == 0
        assert insufficient.core_before == sufficient.core_before      # same pre-etch geometry

        # --- Case 1: insufficient budget: oxide remains in the core, Si does not move -------------
        rm1 = fx.native_removal(insufficient.core_before, insufficient.core_after)
        ev1 = fx.exported_view(insufficient.core_before, insufficient.core_after)
        print(f"Insufficient (NATIVE core): Si moved {rm1['si_removed_um']:+.5f} um; oxide "
              f"{rm1['oxide_thickness_before_um']:.5f} -> {rm1['oxide_thickness_after_um']:.5f} "
              f"(removed {rm1['oxide_removed_um']:.5f}; budget {INSUFFICIENT_BUDGET_UM:.5f})")
        print(f"Insufficient (EXPORTED core, corroboration): SiO2 columns "
              f"{ev1['sio2_columns_present_before']} -> {ev1['sio2_columns_present_after']}; "
              f"Si top {ev1['si_top_before']:.5f} -> {ev1['si_top_after']:.5f}")
        assert abs(rm1["si_removed_um"]) <= fx.UNCHANGED_UM, (
            f"with a budget below the oxide thickness, Si must NOT move -- moved {rm1['si_removed_um']:.5f} um")
        assert ev1["sio2_columns_present_after"] == ev1["sio2_columns_present_before"] > 0, "oxide must remain in the core"
        assert rm1["oxide_thickness_after_um"] > 0.5 * OXIDE_UM - DEPTH_TOLERANCE_UM
        assert abs(rm1["oxide_removed_um"] - INSUFFICIENT_BUDGET_UM) <= DEPTH_TOLERANCE_UM

        # --- Case 2: sufficient budget: oxide punched through, Si genuinely moved ------------------
        rm2 = fx.native_removal(sufficient.core_before, sufficient.core_after)
        ev2 = fx.exported_view(sufficient.core_before, sufficient.core_after)
        print(f"Sufficient (NATIVE core): Si moved {rm2['si_removed_um']:+.5f} um (recipe-derived "
              f"{EXPECTED_SI_SUFFICIENT_UM:.5f}); oxide {rm2['oxide_thickness_before_um']:.5f} -> "
              f"{rm2['oxide_thickness_after_um']:.5f}")
        print(f"Sufficient (EXPORTED core, corroboration): SiO2 columns "
              f"{ev2['sio2_columns_present_before']} -> {ev2['sio2_columns_present_after']}; "
              f"Si top {ev2['si_top_before']:.5f} -> {ev2['si_top_after']:.5f}")
        assert ev2["sio2_columns_present_after"] == 0, "oxide must be punched through in the core"
        assert abs(rm2["si_removed_um"] - EXPECTED_SI_SUFFICIENT_UM) <= DEPTH_TOLERANCE_UM, (
            f"Si removed {rm2['si_removed_um']:.5f} differs from the recipe-derived {EXPECTED_SI_SUFFICIENT_UM:.5f} "
            f"by more than one grid cell")
        assert rm2["si_removed_um"] >= 2 * GRID_UM, "Si must move by several cells"

        # --- resist-protected Si must be untouched in BOTH cases ---------------------------------
        for tag, o in (("insufficient", insufficient), ("sufficient", sufficient)):
            for i, (b, a) in enumerate(zip(o.bands_before, o.bands_after)):
                rm = fx.native_removal(b, a)
                print(f"  [{tag}] protected band {i}: Si moved {rm['si_removed_um']:+.6f}, oxide changed {rm['oxide_removed_um']:+.6f}")
                assert abs(rm["si_removed_um"]) <= fx.UNCHANGED_UM, f"[{tag}] PR-protected Si must be untouched"
                assert abs(rm["oxide_removed_um"]) <= fx.UNCHANGED_UM
                assert a["exported"]["materials"][MASK_MATERIAL]["columns_present"] == a["exported"]["n_columns"]

        pristine = fx.verify_baseline_pristine(baseline, tmp)
        print(f"independence: after both etches the saved baseline is {pristine}")
        assert pristine == {"vpsd_sha256_unchanged": True, "fresh_copy_export_identical": True}

        # --- The GUI's own log summary, called on BOTH real results ------------------------------
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui
        app = gui.TCADApplication()
        try:
            app.withdraw()
            app.update_idletasks()
            logged = []
            app._log = lambda msg: logged.append(msg)
            # pre-etch reference: the real post-mask volume mesh (per-material tags), the same
            # baseline both experiments started from.
            app._log_etch_material_summary(baseline.baseline_mesh_path, insufficient.final_mesh, [OPEN_WINDOW])
            log_insufficient = "".join(logged)
            logged.clear()
            app._log_etch_material_summary(baseline.baseline_mesh_path, sufficient.final_mesh, [OPEN_WINDOW])
            log_sufficient = "".join(logged)
            logged.clear()
            print("LOGGER (insufficient budget):" + log_insufficient.rstrip())
            print("LOGGER (sufficient budget):" + log_sufficient.rstrip())

            def line_of(log, material):
                return next((l for l in log.splitlines() if l.strip().startswith(f"{material}:")), "")

            def block_of(log, material):
                """The material's own line plus its indented detail lines (up to the next material / window line)."""
                out, on = [], False
                for l in log.splitlines():
                    indent = len(l) - len(l.lstrip())
                    if l.strip().startswith(f"{material}:") and indent == 4:
                        on, out = True, [l.strip()]
                    elif on and indent > 4:
                        out.append(l.strip())
                    elif on:
                        break
                return "\n".join(out)

            def logged_etched_um(line):
                m = re.search(r"etched (-?\d+\.\d+)um", line)
                return float(m.group(1)) if m else 0.0

            # VERDICTS (hard assertions). A small Si displacement is NOT evidence that the etch has not
            # reached Si (a selective recipe can expose Si and leave it unmoved), so the old
            # "not yet reached" wording is forbidden; what may be said is what the geometry proves.
            si_line_1 = line_of(log_insufficient, "Si")
            assert "overlying material remains" in si_line_1 and "unchanged within diagnostic tolerance" in si_line_1, (
                f"insufficient-budget log must say Si is unchanged with SiO2 still directly on top of it: "
                f"{log_insufficient!r}")
            assert "not yet reached" not in log_insufficient and "not yet reached" not in log_sufficient
            assert "newly exposed" not in log_insufficient and "newly exposed" not in log_sufficient
            si_line_2 = line_of(log_sufficient, "Si")
            assert "etched" in si_line_2 and "unchanged" not in si_line_2, (
                f"sufficient-budget log must say Si was genuinely etched (native core removal "
                f"{rm2['si_removed_um']:.5f} um): {log_sufficient!r}")
            si_block_2 = block_of(log_sufficient, "Si")
            assert "vertical paired flat-interior displacement" in si_block_2 and "not undercut/path length" in si_block_2, si_block_2
            assert "evidence source: exported volume mesh" in si_block_2, si_block_2
            # Batch 3B contract: the sufficient SiO2 is FULLY_CLEARED_IN_WINDOW -- the exported post mesh has no
            # positive-area SiO2 intersection anywhere in the window -- and says where that evidence comes from
            ox_block_2 = block_of(log_sufficient, "SiO2")
            assert line_of(log_sufficient, "SiO2").strip() == "SiO2: fully cleared in the exported-mesh window", log_sufficient
            assert ("(no positive-area post-step intersection; evidence source: exported volume mesh)" in ox_block_2), ox_block_2
            assert "residual" not in ox_block_2, ox_block_2                  # nothing remains, so nothing is listed
            assert line_of(log_insufficient, "SiO2").strip() == "SiO2: etched 0.1000um", log_insufficient

            # MAGNITUDES: the diagnostic reports the PAIRED vertical displacement over the flat interior connected
            # to the window centre (the mask-edge shoulder is excluded by the pairing itself, not by a fitted
            # margin). Compare with the same exported mesh read at the CENTRAL CORE (the bound is the project's own
            # 0.001 um diagnostic comparison tolerance, not a fitted number). Collected here, asserted after the
            # remaining sections have run, so every discrepancy is reported together.
            def core_top(o, when, material):
                block = (o.core_before if when == "before" else o.core_after)["exported"]["materials"]
                return block[material]["top_mean"]

            core_ox_removed = core_top(insufficient, "before", "SiO2") - core_top(insufficient, "after", "SiO2")
            core_si_removed = core_top(sufficient, "before", "Si") - core_top(sufficient, "after", "Si")
            logger_ox = logged_etched_um(line_of(log_insufficient, "SiO2"))
            logger_si = logged_etched_um(si_line_2)
            print(f"logger SiO2 etched {logger_ox:.4f} um (insufficient) vs core exported {core_ox_removed:.4f} "
                  f"(native {rm1['oxide_removed_um']:.5f}); logger Si etched {logger_si:.4f} um (sufficient) vs core "
                  f"exported {core_si_removed:.4f} (native {rm2['si_removed_um']:.5f})")
            logger_mismatches = []
            # both the exported core (same file the logger reads) and the NATIVE level-set core; the
            # tolerance is the project's own diagnostic comparison tolerance, not a fitted number
            for label, got, want in (("insufficient / SiO2 vs exported core", logger_ox, core_ox_removed),
                                     ("sufficient / Si vs exported core", logger_si, core_si_removed),
                                     ("insufficient / SiO2 vs native core", logger_ox, rm1["oxide_removed_um"]),
                                     ("sufficient / Si vs native core", logger_si, rm2["si_removed_um"])):
                if abs(got - want) > fx.UNCHANGED_UM:
                    logger_mismatches.append(
                        f"{label}: the logger reports {got:.4f} um but the central-core geometry moved {want:.4f} um "
                        f"(difference {got - want:+.4f} um)")

            # --- Finding 1: a blanket (coated, not developed) resist reports NOTHING open --------
            ok = app._materialize_current_wafer()
            assert ok, "materializing a real ViennaPS wafer failed"
            app.process_pr_coat()
            assert app.wafer.pr_present and not app.wafer.developed, (
                "PR COAT alone must not also develop the resist")

            captured_windows = {}
            real_log_etch_summary = app._log_etch_material_summary

            def spy_log_etch_summary(pre_mesh, post_mesh, open_windows_um):
                captured_windows["windows"] = open_windows_um
                return real_log_etch_summary(pre_mesh, post_mesh, open_windows_um)

            app._log_etch_material_summary = spy_log_etch_summary
            app.etch_model.set("Isotropic etch")
            app.isotropic_rate_var.set(0.3)
            app.etch_time_var.set(1.0)
            app.run_etch()

            assert captured_windows.get("windows") == [], (
                f"a blanket (coated, not developed) resist must report NOTHING open, got "
                f"{captured_windows.get('windows')!r} -- this must not be the stale mask_openings_um-derived "
                f"default [[-1.5, 1.5]]")
            print("Coated-not-developed etch correctly reports nothing open (not the stale "
                  "mask_openings_um default).")
        finally:
            app.destroy()
        assert not logger_mismatches, (
            "_log_etch_material_summary() disagrees with the real central-core geometry -- production "
            "diagnostic finding, NOT relaxed here: " + "; ".join(logger_mismatches))

    print("Etch reachability verified on an explicit initial Si/SiO2 stack (DIRECT_EXPLICIT_GEOMETRY; "
          "not an oxidation result); the log summary reports a paired vertical flat-interior displacement "
          "that agrees with the central-core geometry (exported and native), says what geometry proves about "
          "Si (overlying oxide remains / cleared) instead of inferring 'not reached'; PR protection holds in both cases.")


if __name__ == "__main__":
    main()
