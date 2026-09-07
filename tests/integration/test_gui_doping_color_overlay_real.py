#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 10, dopant-state-unification: confirmed live this session, the
OLD `_doping_color_segments()` read `region.peak_conc_cm3` (a legacy,
single-value field on `self.last_doped_result.doping.regions` that only
ever reflects the MOST RECENT `apply_doping()` call), painting an
ENTIRE multi-term doping region ONE flat, wrong color whenever more
than one implant had been applied. This test proves the FIX with a
per-bucket cross-check -- not just "at least two colors appear" --
confirming EVERY real bucket's rendered color matches the SIGN (or
UNSUPPORTED_BY_MODEL status) of `self.wafer_state.net_doping_at()` at
that exact bucket's own center, and that a bucket whose real dopant
host material is no longer exposed (spec Sec6) renders as a visibly
distinct marker, never blended into the normal blue/red rendering.

Setup: real GUI (Task 9's own B-then-P Gaussian Implant pattern,
`tests/integration/test_gui_thermal_anneal_real.py`), PLUS a third
implant placed inside a real LOCOS oxidation's open (growth) window.
The oxidation-then-mask/pad-oxide-strip construction is the exact,
already-proven recipe from
`test_ce2_oxidation_conversion_unsupported_real.py` (Task 7) -- reused
directly rather than re-derived, since it is what genuinely converts
real Si to SiO2 at a known coordinate (the open window) while
genuinely restoring real Si everywhere else (the masked span, after a
fixed-depth pad-oxide strip) -- see that test's own module docstring
for the full physical reasoning (three real, non-obvious findings
about LOCOS masking/export/pad-oxide behavior).

Deliberate deviation from this task's own brief draft: the real
oxidation + strip is driven through DIRECT registry/session calls
(`registry.get("oxidation", "thermal")`, etc.) rather than through the
GUI's own subprocess-based `run_oxidation()` panel. This is still real
ViennaPS execution -- the exact same registry dispatch `run_oxidation`
itself uses internally -- and avoids re-deriving untested GUI-panel-
level LOCOS/mask-material/pad-strip wiring that this task does not
otherwise need; `app.wafer_state` is then advanced with the real
result via `advance_wafer_state()`, mirroring exactly what
`_sync_wafer_state_geometry()` does for a real oxidation recipe. Doping
accumulation itself (the part this task actually rewrites the renderer
for) goes through the real GUI (`app.run_doping()`), unchanged from
Task 9's own pattern.

No depth/junction-depth claim is made anywhere -- this project's
doping/diffusion model is x-only; net_doping_at() is always queried at
depth_um=0.0.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401 -- registers "oxidation"/"thermal"
import tcad.process.etching  # noqa: F401 -- registers "etching"/"isotropic"
from tcad.process import registry
from tcad.backends.viennaps.io import register_locos_export

N_COLOR, P_COLOR, UNSUPPORTED_MARKER = "#2f6fed", "#e0393e", "#unsupported"
# Final-review Fix 5: a fully-computable, genuinely-zero bucket (real
# geometry-gated erasure, or simply never doped -- as most of this
# test's own domain is, far from all 3 narrow implants) must render as
# its own distinct marker, never blended into N_COLOR just because
# 0.0 >= 0. Matches tcad_2d_stagewise._DOPING_ZERO_MARKER exactly.
ZERO_MARKER = "#zero"

# Same real, already-proven geometry/recipe constants as
# test_ce2_oxidation_conversion_unsupported_real.py (Task 7) -- reused,
# not re-derived. GRID/extents also match the GUI's own real defaults
# (Wafer.width_um=10.0, Wafer.silicon_depth_um=5.0, y_extent_um=8.0
# hardcoded in run_oxidation()/_materialize_current_wafer()), so the
# directly-built oxidation is physically consistent with what the real
# GUI just materialized.
GRID_UM = 0.2
X_EXTENT_UM, Y_EXTENT_UM, SI_DEPTH_UM = 10.0, 8.0, 5.0
WINDOW_HALF_UM = 1.0        # LOCOS open (growth) window is x in [-1.0, +1.0]
PAD_STRIP_DEPTH_UM = 0.19   # fixed ahead of time -- see the Task 7 test's own comment


def _real_locos_oxidation_then_strip(tmp):
    """Real LOCOS oxidation (masked, open window |x|<=1.0) followed by a
    real mask + pad-oxide strip -- converts the open window's Si to
    SiO2 permanently (field oxide thicker than the fixed strip depth)
    while restoring real Si everywhere else (pad oxide only, fully
    cleared). Identical recipe to the Task 7 CE-2 test."""
    from tcad.backends.viennaps import session as vps_session

    # 2026-09-08: LOCOS split out of ThermalOxidation into its own
    # registry entry ("oxidation", "locos") -- tcad/process/oxidation/
    # locos.py. Both steps below genuinely run LOCOS (mask_material set).
    step0 = registry.get("oxidation", "locos")()
    recipe0 = {
        "_process_category": "oxidation", "_process_model_key": "locos",
        "mask_left_um": -WINDOW_HALF_UM, "mask_right_um": WINDOW_HALF_UM,
        "mask_material": "Mask", "pr_thickness_um": 1.0,
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": X_EXTENT_UM, "y_extent_um": Y_EXTENT_UM,
        "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
    }
    step0.run(recipe0, tmp)

    recipe1 = dict(recipe0)
    recipe1["temperature_c"], recipe1["time_hours"] = 1100.0, 8.0
    step1 = registry.get("oxidation", "locos")(inherited_domain=step0.last_domain)
    step1.run(recipe1, tmp)

    module = vps_session.require_viennaps()
    domain = step1.last_domain
    domain.removeMaterial(module.Material.Mask)
    register_locos_export(domain, [module.Material.Si, module.Material.SiO2], [False, True])

    strip_step = registry.get("etching", "isotropic")(inherited_domain=domain)
    strip_recipe = {
        "material_rates": {"SiO2": -PAD_STRIP_DEPTH_UM, "Si": 0.0},
        "default_rate": 0.0, "etch_time_s": 1.0,
        "silicon_depth_um": SI_DEPTH_UM,
    }
    strip_result = strip_step.run(strip_recipe, tmp)
    return {"final_mesh": strip_result["final_mesh"], "snapshots": []}


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

    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.wafer_state_accumulation import advance_wafer_state

    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(GRID_UM)

        assert app._materialize_current_wafer(), "materializing a real ViennaPS wafer failed"

        def _implant(position_um, straggle_um, donor, acceptor, donor_species, acceptor_species):
            app.doping_kind.set("Gaussian Implant")
            app.dope_gauss_region_var.set("Si")
            app.dope_gauss_axis_var.set("x")
            app.dope_gauss_position_var.set(position_um)
            app.dope_gauss_straggle_var.set(straggle_um)
            app.dope_gauss_donor_var.set(donor)
            app.dope_gauss_acceptor_var.set(acceptor)
            app.dope_gauss_donor_species_var.set(donor_species)
            app.dope_gauss_acceptor_species_var.set(acceptor_species)
            assert app.run_doping(silent=True)

        # Real B(acceptor)/P(donor) implants -- Task 9's own real
        # accumulation mechanism (self.wafer_state.dopant_profiles),
        # unchanged. Positions measured directly against THIS real,
        # solved geometry (not assumed symmetric around the nominal
        # +-1.0um mask window): a real, measured finding this session
        # is that the chained-LOCOS recipe below reuses step0's
        # already-deformed mask AS-IS for step1 (locos.py's own
        # documented behavior, also flagged -- but not measured -- by
        # test_ce2_oxidation_conversion_unsupported_real.py), so the
        # real converted (SiO2) span ends up ASYMMETRIC: measured via a
        # direct exposed_material_at() scan of this exact recipe,
        # real Si survives only in x<-2.4 and x>4.2 (out of a 10um,
        # roughly [-5.0, 5.05] domain) -- nothing like the nominal
        # +-1.0um window. B and P are placed well inside those real,
        # measured Si-surviving margins so each one's OWN real,
        # non-negligible concentration (not just a near-zero background
        # tie-break) is what the "distinct colors" check below proves.
        _implant(-4.0, 0.2, 0.0, 1.0e18, "", "B")
        _implant(4.6, 0.15, 1.0e18, 0.0, "P", "")
        # A third, donor implant placed INSIDE the real converted span
        # measured above -- its host_material (Si) will no longer be
        # exposed there once the real oxidation below runs, so every
        # bucket covering it must report UNSUPPORTED_BY_MODEL, never a
        # silent value.
        _implant(0.0, 0.2, 1.0e18, 0.0, "Sb", "")

        species_present = {p.species for p in app.wafer_state.dopant_profiles}
        assert species_present == {"B", "P", "Sb"}
        print(f"[setup] 3 real DopantProfiles accumulated on app.wafer_state: "
              f"{sorted(species_present)}")

        with tempfile.TemporaryDirectory() as tmp:
            oxidized = _real_locos_oxidation_then_strip(tmp)
            oxidized_result = build_process_result(oxidized)
            app.wafer_state = advance_wafer_state(app.wafer_state, oxidized_result, "oxidation")

            converted = app.wafer_state.exposed_material_at(0.0)
            protected_b = app.wafer_state.exposed_material_at(-4.0)
            protected_p = app.wafer_state.exposed_material_at(4.6)
            print(f"[real LOCOS oxidation + mask/pad-oxide strip] "
                  f"x=0.0 (open window, Sb) exposed={converted!r}, "
                  f"x=-4.0 (B) exposed={protected_b!r}, "
                  f"x=4.6 (P) exposed={protected_p!r}")
            assert converted != "Si", "the open window must genuinely convert Si -> SiO2"
            assert protected_b == "Si", "B's real position must genuinely stay/return to real Si"
            assert protected_p == "Si", "P's real position must genuinely stay/return to real Si"

            # Confirm each is a REAL, non-negligible signal at its own
            # position -- not merely a near-zero background tie-break
            # (>=2 colors could otherwise pass for the wrong reason).
            b_query = app.wafer_state.net_doping_at(-4.0, 0.0)
            p_query = app.wafer_state.net_doping_at(4.6, 0.0)
            print(f"[real signal check] B@-4.0: net_doping={b_query.net_doping:.3e}, "
                  f"P@4.6: net_doping={p_query.net_doping:.3e}")
            assert b_query.net_doping < -1e17, "B's own real acceptor concentration must dominate at its own position"
            assert p_query.net_doping > 1e17, "P's own real donor concentration must dominate at its own position"

            segments = app._doping_color_segments("Si", x_min_um=-5.0, x_max_um=5.0)

        print(f"{len(segments)} real segments returned")

        mismatches = []
        unsupported_seen = supported_seen = zero_seen = 0
        for x_lo, x_hi, color in segments:
            bucket_center = (x_lo + x_hi) / 2.0
            result = app.wafer_state.net_doping_at(bucket_center, 0.0)
            if result.physics_status is not None:
                unsupported_seen += 1
                if color != UNSUPPORTED_MARKER:
                    mismatches.append(
                        f"bucket@{bucket_center:.3f}um: physics_status shows a gap but "
                        f"rendered color={color!r} (expected {UNSUPPORTED_MARKER!r})"
                    )
                continue
            # Final-review Fix 5: a genuinely-zero, fully-computable
            # bucket (real here for most of this domain -- far from all
            # 3 narrow implants, each profile's own Gaussian tail
            # underflows to an exact 0.0) must render as ZERO_MARKER,
            # never blended into N_COLOR.
            if result.net_doping == 0.0:
                zero_seen += 1
                if color != ZERO_MARKER:
                    mismatches.append(
                        f"bucket@{bucket_center:.3f}um: net_doping is exactly 0.0 but "
                        f"rendered color={color!r} (expected {ZERO_MARKER!r})"
                    )
                continue
            supported_seen += 1
            expected = N_COLOR if result.net_doping >= 0 else P_COLOR
            if color != expected:
                mismatches.append(
                    f"bucket@{bucket_center:.3f}um: net_doping={result.net_doping:.3e} "
                    f"(sign expects {expected!r}) but rendered color={color!r}"
                )

        print(f"buckets checked: {len(segments)} (supported={supported_seen}, "
              f"zero={zero_seen}, unsupported={unsupported_seen})")
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        assert not mismatches, (
            f"{len(mismatches)} bucket(s) rendered a color that disagrees with the "
            f"real computed sign/status"
        )
        assert unsupported_seen >= 1, (
            "the real LOCOS open window must have produced at least one genuine "
            "UNSUPPORTED_BY_MODEL bucket -- got none, the oxidation/strip recipe "
            "may need re-tuning"
        )
        # NOTE: this fixture does not reliably produce a genuinely-zero
        # bucket (measured: every x here is either near one of the 3
        # narrow implants' own real, non-negligible tail -- the domain
        # is only +-5um and the implants sit close to its edges -- or
        # inside the oxidation-converted zone, which is UNSUPPORTED_BY_
        # MODEL, not zero). zero_seen is printed for information; the
        # dedicated, deterministic zero-marker proof is
        # `scenario_zero_marker()` below, using CE-1's own real
        # etch-erasure technique on a SEPARATE, simpler fixture
        # (last_step_category is a single flat field -- see CE-1's own
        # "Problem 3" -- so mixing a removal-caused zero into THIS
        # oxidation-classified state would incorrectly reclassify the
        # UNSUPPORTED entries checked above as zero instead).

        colors = {c for _, _, c in segments if c not in (UNSUPPORTED_MARKER, ZERO_MARKER)}
        assert len(colors) >= 2, "B(acceptor) and P(donor) regions must render as genuinely different colors"
        print(f"distinct real colors rendered: {colors}; every bucket's color matches its real "
              f"WaferState.net_doping_at() sign/status, none inferred or assumed -- including "
              f"{unsupported_seen} bucket(s) genuinely reporting UNSUPPORTED_BY_MODEL (real "
              f"oxidation-converted Si) and {zero_seen} bucket(s) genuinely reporting net_doping="
              f"0.0 (undoped), each rendered as its own distinct marker, never blended into "
              f"blue/red.")

        print("\nGUI P/N doping color overlay reads REAL per-bucket "
              "WaferState.net_doping_at() -- a multi-implant region renders each "
              "bucket's own true sign, and a real oxidation-converted region "
              "(UNSUPPORTED_BY_MODEL) renders as a visibly distinct marker, never "
              "blended into the normal blue/red convention.")

        # --- Final-review Fix 5: a DETERMINISTIC genuinely-zero bucket,
        # on its own SEPARATE, small fixture (see the NOTE above for why
        # it cannot share the oxidation scenario's own state). Reuses
        # CE-1's own real etch-erasure technique
        # (test_ce1_order_sensitive_geometry_real.py): a real, blanket
        # isotropic etch (Si exposed everywhere) -> a real Gaussian
        # Implant AT a fixed x -> a real, MASKED isotropic etch that
        # removes Si COMPLETELY at that same x, queried immediately
        # (last_step_category="etching") -- a real, physically
        # meaningful geometry-gated zero, not UNSUPPORTED_BY_MODEL.
        ZERO_WIDTH_UM, ZERO_Y_EXTENT_UM, ZERO_SI_DEPTH_UM, ZERO_GRID_UM = 10.0, 8.0, 1.0, 0.1
        ERASE_X_UM = 0.0
        ZERO_WINDOW_HALF_UM = 1.0
        ZERO_HALF_DOMAIN_UM = ZERO_WIDTH_UM / 2.0

        with tempfile.TemporaryDirectory() as tmp2:
            base_step = registry.get("etching", "isotropic")()
            base_recipe = {
                "_process_category": "etching", "_process_model_key": "isotropic",
                "rate": -0.02, "etch_time_s": 5.0,
                "silicon_depth_um": ZERO_SI_DEPTH_UM, "grid_delta_um": ZERO_GRID_UM,
                "x_extent_um": ZERO_WIDTH_UM, "y_extent_um": ZERO_Y_EXTENT_UM,
                "mask_spans_um": [],
            }
            base_result = base_step.run(base_recipe, tmp2)
            base = build_process_result({"final_mesh": base_result["final_mesh"], "snapshots": []})

            from tcad.physics.doping import apply_gaussian_implant_doping
            implanted = apply_gaussian_implant_doping(
                base, region="Si", junction_axis="x", peak_position_um=ERASE_X_UM,
                straggle_um=0.3, donor_peak_conc_cm3=1e18, donor_species="As",
            )
            zero_state1 = advance_wafer_state(None, implanted, "doping")

            module = viennaps_session.require_viennaps()
            erase_step = registry.get("etching", "isotropic")(inherited_domain=base_step.last_domain)
            erase_recipe = {
                "_process_category": "etching", "_process_model_key": "isotropic",
                "remask_spans_um": [
                    [-ZERO_HALF_DOMAIN_UM, -ZERO_WINDOW_HALF_UM],
                    [ZERO_WINDOW_HALF_UM, ZERO_HALF_DOMAIN_UM],
                ],
                "mask_material": "Mask",
                "grid_delta_um": ZERO_GRID_UM, "x_extent_um": ZERO_WIDTH_UM, "pr_thickness_um": 0.3,
                "rate": -0.5, "etch_time_s": 3.0,
                "silicon_depth_um": ZERO_SI_DEPTH_UM,
            }
            erase_step.run(erase_recipe, tmp2)
            erase_step.last_domain.removeMaterial(module.Material.Mask)
            from tcad.backends.viennaps.io import save_volume_mesh
            stripped_mesh = save_volume_mesh(
                erase_step.last_domain, str(Path(tmp2) / "zero_marker_stripped"),
                floor_depth_um=ZERO_SI_DEPTH_UM,
            )
            stripped = build_process_result({"final_mesh": stripped_mesh, "snapshots": []})
            zero_state2 = advance_wafer_state(zero_state1, stripped, "etching")

            exposed_after = zero_state2.exposed_material_at(ERASE_X_UM)
            print(f"\n[zero-marker scenario] exposed_material_at({ERASE_X_UM}) after "
                  f"real masked etch = {exposed_after!r} (must NOT be 'Si')")
            assert exposed_after != "Si", (
                "fixture is broken: the etch must remove Si completely at ERASE_X_UM"
            )

            q = zero_state2.net_doping_at(ERASE_X_UM, 0.0)
            print(f"[zero-marker scenario] net_doping_at({ERASE_X_UM}) = {q.net_doping}, "
                  f"physics_status={q.physics_status}")
            assert q.net_doping == 0.0 and q.physics_status is None, (
                f"fixture is broken: expected a genuine geometry-gated zero (removal), "
                f"got net_doping={q.net_doping}, physics_status={q.physics_status}"
            )

            app.wafer_state = zero_state2
            zero_segments = app._doping_color_segments(
                "Si", x_min_um=-1.0, x_max_um=1.0, n_buckets=10,
            )
            erased_bucket = next(
                (seg for seg in zero_segments if seg[0] <= ERASE_X_UM <= seg[1]), None,
            )
            assert erased_bucket is not None, "no bucket covers ERASE_X_UM -- adjust n_buckets/range"
            print(f"[zero-marker scenario] app._doping_color_segments() rendered color "
                  f"at the erased bucket: {erased_bucket[2]!r} (expected {gui._DOPING_ZERO_MARKER!r})")
            assert erased_bucket[2] == gui._DOPING_ZERO_MARKER, (
                f"Fix 5: a genuinely-zero (erased) bucket must render as the ZERO "
                f"marker, got {erased_bucket[2]!r}"
            )

        print("\nFix 5 VERIFIED against the real GUI: a real geometry-gated zero "
              "(dopant erased by a real, registered etch) renders as its own "
              "distinct marker, never blended into N_COLOR just because 0.0 >= 0.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
