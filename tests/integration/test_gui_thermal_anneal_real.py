#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI: two Gaussian Implant clicks accumulate into two independent
DopantProfiles on the real, cross-step WaferState (Task 9,
dopant-state-unification), and ANNEAL widens both -- by their own,
DIFFERENT species' real D(T) -- with the change directly observable in
the log. Real TCADApplication (window withdrawn), real ViennaPS.

REWRITTEN for the new architecture: multi-implant accumulation is no
longer DopingRegion.gaussian_terms / apply_gaussian_implant_doping's
own `existing=` kwarg (both removed, Task 4) -- it is now
self.wafer_state.dopant_profiles, populated by advance_wafer_state()
inside run_doping() (Task 9). apply_thermal_anneal() (Task 3) now
dispatches per-profile and operates on a profile tuple directly
(returning (updated_profiles, physics_status)), not a ProcessResult.

Also demonstrates, with real printed numbers read from real function
results (not a separate fabricated display):
  - higher anneal temperature alone -> more broadening (isolated,
    same starting profiles, same time, only T varied)
  - longer anneal time alone -> more broadening (isolated, same
    starting profiles, same temperature, only t varied)
  - higher implant dose -> higher recorded peak concentration
  - a SECOND anneal (via a second real GUI click) further widens BOTH
    the B and the P profile already on the wafer -- neither is reset
    or dropped by a repeated anneal.

No depth/junction-depth claim is made anywhere in this test or in the
GUI change it exercises -- this project's diffusion model is x-only
(straggle/peak concentration only); see
tcad.physics.doping.DEPTH_EVOLUTION_RESOLUTION.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS is not installed")
        return

    from tcad.physics.doping import apply_thermal_anneal

    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(0.2)

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"

        # First implant: B (acceptor)
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(-1.0)
        app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(0.0)
        app.dope_gauss_acceptor_var.set(1.0e18)
        app.dope_gauss_donor_species_var.set("")
        app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)

        assert app.wafer_state is not None
        assert len(app.wafer_state.dopant_profiles) == 1
        print(f"[1/6] first implant (B) applied via advance_wafer_state: "
              f"{len(app.wafer_state.dopant_profiles)} profile(s)")

        # Second implant: P (donor) -- must ADD, not replace
        app.dope_gauss_position_var.set(1.0)
        app.dope_gauss_straggle_var.set(0.15)
        app.dope_gauss_donor_var.set(2.0e18)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species_present = {p.species for p in app.wafer_state.dopant_profiles}
        assert species_present == {"B", "P"}, (
            f"second implant must ADD a profile, not replace -- got species "
            f"{species_present}"
        )
        print(f"[2/6] second implant (P) added: both B and P present, "
              f"{len(app.wafer_state.dopant_profiles)} profiles total")

        # -- higher implant dose -> higher recorded peak concentration --
        # B was implanted at 1.0e18 cm^-3, P at 2.0e18 cm^-3 (set above).
        # Both land as independent DopantProfiles in the real,
        # accumulated wafer_state -- this is the real dose each profile
        # carries, not a re-derived or fabricated number.
        by_species = {p.species: p for p in app.wafer_state.dopant_profiles}
        dose_b = by_species["B"].model_params["peak_conc_cm3"]
        dose_p = by_species["P"].model_params["peak_conc_cm3"]
        assert dose_p > dose_b, (
            f"higher implant dose (P, 2.0e18) must record a higher peak "
            f"concentration than the lower dose (B, 1.0e18) -- got "
            f"B={dose_b:.3e}, P={dose_p:.3e}"
        )
        print(f"[3/6] higher implant dose -> higher recorded concentration: "
              f"B(dose 1.0e18)={dose_b:.3e} cm^-3 < P(dose 2.0e18)={dose_p:.3e} cm^-3")

        # Stable snapshot; apply_thermal_anneal never mutates in place --
        # it returns a brand new tuple of profiles each call.
        pre_anneal_profiles = app.wafer_state.dopant_profiles

        # -- anneal temperature increase alone -> more broadening --
        # (same starting profiles, same time, only T varied -- isolates
        # the temperature effect from the time effect, both real calls
        # through the exact function the ANNEAL button itself calls)
        lower_t, _ = apply_thermal_anneal(pre_anneal_profiles, 700.0, 600.0)
        higher_t, _ = apply_thermal_anneal(pre_anneal_profiles, 1100.0, 600.0)
        lower_t_straggle = {p.species: p.model_params["straggle_um"] for p in lower_t}
        higher_t_straggle = {p.species: p.model_params["straggle_um"] for p in higher_t}
        assert higher_t_straggle["B"] > lower_t_straggle["B"]
        assert higher_t_straggle["P"] > lower_t_straggle["P"]
        print(f"[4/6] higher anneal temperature alone -> more broadening (t=600s fixed): "
              f"B straggle @700C={lower_t_straggle['B']:.4f}um < @1100C={higher_t_straggle['B']:.4f}um, "
              f"P straggle @700C={lower_t_straggle['P']:.4f}um < @1100C={higher_t_straggle['P']:.4f}um")

        # -- anneal time increase alone -> more broadening --
        # (same starting profiles, same temperature, only t varied)
        shorter_t, _ = apply_thermal_anneal(pre_anneal_profiles, 900.0, 60.0)
        longer_t, _ = apply_thermal_anneal(pre_anneal_profiles, 900.0, 3600.0)
        shorter_straggle = {p.species: p.model_params["straggle_um"] for p in shorter_t}
        longer_straggle = {p.species: p.model_params["straggle_um"] for p in longer_t}
        assert longer_straggle["B"] > shorter_straggle["B"]
        assert longer_straggle["P"] > shorter_straggle["P"]
        print(f"[5/6] longer anneal time alone -> more broadening (T=900C fixed): "
              f"B straggle @60s={shorter_straggle['B']:.4f}um < @3600s={longer_straggle['B']:.4f}um, "
              f"P straggle @60s={shorter_straggle['P']:.4f}um < @3600s={longer_straggle['P']:.4f}um")

        straggle_before = {
            p.species: p.model_params["straggle_um"] for p in app.wafer_state.dopant_profiles
        }

        # First real GUI anneal click -- must widen BOTH, by DIFFERENT amounts (real, different D(T))
        app.anneal_temp_var.set(900.0)
        app.anneal_time_var.set(600.0)
        app._on_thermal_anneal_clicked()

        straggle_after = {
            p.species: p.model_params["straggle_um"] for p in app.wafer_state.dopant_profiles
        }

        assert straggle_after["B"] > straggle_before["B"], "B must broaden"
        assert straggle_after["P"] > straggle_before["P"], "P must broaden"
        assert abs(straggle_after["B"] - straggle_after["P"]) > 1e-6, (
            "B and P must broaden by DIFFERENT amounts (different real D(T))"
        )
        print(f"[6/6] first ANNEAL (GUI click) widened both: "
              f"B {straggle_before['B']:.4f}->{straggle_after['B']:.4f} um, "
              f"P {straggle_before['P']:.4f}->{straggle_after['P']:.4f} um")

        # A SECOND real GUI anneal click -- both species already on the
        # wafer must be affected again, neither reset nor dropped.
        app.anneal_temp_var.set(950.0)
        app.anneal_time_var.set(300.0)
        app._on_thermal_anneal_clicked()

        species_after_2 = {p.species for p in app.wafer_state.dopant_profiles}
        straggle_after_2 = {
            p.species: p.model_params["straggle_um"] for p in app.wafer_state.dopant_profiles
        }

        assert species_after_2 == {"B", "P"}, (
            f"a second anneal must not drop either species -- got {species_after_2}"
        )
        assert straggle_after_2["B"] > straggle_after["B"], "B must broaden further on a second anneal"
        assert straggle_after_2["P"] > straggle_after["P"], "P must broaden further on a second anneal"
        print(f"second ANNEAL (GUI click) widened both again: "
              f"B {straggle_after['B']:.4f}->{straggle_after_2['B']:.4f} um, "
              f"P {straggle_after['P']:.4f}->{straggle_after_2['P']:.4f} um")

        # The change must be OBSERVABLE in the log -- both species' real numbers.
        log_text = app.log.get("1.0", "end")
        assert "B (acceptor)" in log_text and "P (donor)" in log_text
        assert f"{straggle_after['B']:.4f}" in log_text
        assert f"{straggle_after['P']:.4f}" in log_text
        assert f"{straggle_after_2['B']:.4f}" in log_text
        assert f"{straggle_after_2['P']:.4f}" in log_text
        print("both species' before/after straggle values are in the real log, "
              "for both the first and the second anneal")

        print("\nGUI: Gaussian Implant clicks accumulate real DopantProfiles "
              "on self.wafer_state, and ANNEAL produces a real, "
              "species-dependent, log-observable physical change -- "
              "monotonic in temperature, monotonic in time, repeatable, "
              "and never erases an existing profile.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
