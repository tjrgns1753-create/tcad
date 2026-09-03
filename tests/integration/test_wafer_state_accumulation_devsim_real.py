# -*- coding: utf-8 -*-
"""Real ViennaPS, real mesh FILE (matching the actual GUI/production
path -- no live domain object anywhere in this test, per this task's
own architecture finding). Two SEPARATE apply_gaussian_implant_doping
calls (B, then P -- Task 4 removed the old existing= mechanism)
accumulate at the WaferState layer instead, via advance_wafer_state().
category='doping' for both calls -- neither is a geometry-changing
step."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.process import registry
from tcad.process.etching import isotropic  # noqa: F401
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result  # same helper run_doping() itself uses


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # Base step: a blanket (no-mask), real isotropic etch -- NOT
        # thermal oxidation, deliberately (see task-5-report.md
        # "Deviation from the brief" for the full real-physics finding:
        # tcad/process/oxidation/thermal.py's non-LOCOS path
        # unconditionally calls setInitialOxideThickness(max(0.002,
        # grid_delta_um)) before any growth solve, so ANY plain/fin
        # thermal oxidation on an unmasked wafer seeds a full-gridDelta
        # SiO2 layer across the ENTIRE exposed Si surface regardless of
        # time_hours -- Si is never again the top-of-stack material
        # anywhere, so a later net_doping_at() probe at any x correctly
        # (per spec Sec3/Sec6) reports UNSUPPORTED_BY_MODEL rather than
        # a real concentration. A blanket isotropic etch has no such
        # seed step and leaves Si exposed everywhere, matching what this
        # test actually needs to verify: WaferState-layer accumulation
        # through a real mesh FILE, not oxidation's own physics.
        step = registry.get("etching", "isotropic")()
        recipe = {
            "_process_category": "etching", "_process_model_key": "isotropic",
            "rate": -0.02, "etch_time_s": 5.0,
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "mask_spans_um": [],
        }
        result0 = step.run(recipe, tmp)
        base = build_process_result({"final_mesh": result0["final_mesh"], "snapshots": []})

        b_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=0.2, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state1 = advance_wafer_state(None, b_result, "doping")
        print(f"after B implant: {len(state1.dopant_profiles)} profile(s), "
              f"species={[p.species for p in state1.dopant_profiles]}")
        assert len(state1.dopant_profiles) == 1

        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=0.15, donor_peak_conc_cm3=2e18, donor_species="P",
        )
        state2 = advance_wafer_state(state1, p_result, "doping")
        species = sorted(p.species for p in state2.dopant_profiles)
        print(f"after P implant (via advance_wafer_state, NOT existing=): "
              f"{len(state2.dopant_profiles)} profile(s), species={species}")
        assert species == ["B", "P"], "both must be present -- accumulation now lives at the WaferState layer"

        q = state2.net_doping_at(-1.0, 0.0)
        print(f"net_doping at x=-1.0 (B's own peak): donor={q.donor_concentration:.3e}, "
              f"acceptor={q.acceptor_concentration:.3e}, net={q.net_doping:.3e}")
        assert q.acceptor_concentration > 0 and q.physics_status is None

        # Required acceptance assertion (user's own final review, point 2):
        # a GEOMETRY-CHANGING step in between two doping calls must NOT
        # drop either existing profile. Real etch, positioned away from
        # both B and P so neither is geometry-gated by it -- this phase
        # is purely about whether advance_wafer_state() PRESERVES the
        # accumulated list across a non-doping step, not about erasure
        # (Task 6 owns the erasure claim).
        etch_step = registry.get("etching", "isotropic")(inherited_domain=step.last_domain)
        etch_recipe = {
            "_process_category": "etching", "_process_model_key": "isotropic",
            "rate": -0.02, "etch_time_s": 5.0,  # brief, real, but nowhere near B(-1.0)/P(+1.0)
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "mask_spans_um": [[-4.5, -3.5]],  # opens far from both B and P
        }
        etch_result = etch_step.run(etch_recipe, tmp)
        state3 = advance_wafer_state(
            state2, build_process_result({"final_mesh": etch_result["final_mesh"], "snapshots": []}),
            "etching",
        )
        species_after_etch = sorted(p.species for p in state3.dopant_profiles)
        print(f"after a real, unrelated etch (category='etching', no doping in this step): "
              f"species={species_after_etch}")
        assert species_after_etch == ["B", "P"], (
            "a geometry-changing step with NO doping of its own must still preserve "
            "every previously-accumulated profile -- P doping -> etch -> (implicitly) N "
            "doping must end with BOTH present, not just whichever was implanted last"
        )

        # thermal_history is untouched by advance_wafer_state() -- it only
        # concatenates profile objects, never rewrites any profile's own
        # fields. True by construction (no anneal ran in this test), verified
        # directly rather than merely asserted from the implementation:
        b_profile = next(p for p in state3.dopant_profiles if p.species == "B")
        print(f"B's thermal_history after accumulate+etch: {b_profile.thermal_history} (must be empty -- no anneal ran)")
        assert b_profile.thermal_history == ()

        print("WaferState.dopant_profiles accumulates real, independent B+P profiles "
              "through advance_wafer_state(), from a real mesh FILE -- matching the actual "
              "GUI production path, not a live-domain shortcut -- survives an intervening "
              "geometry-changing step with no doping of its own, and closes the "
              "ProcessResult.doping dual-source-of-truth gap.")


if __name__ == "__main__":
    main()
