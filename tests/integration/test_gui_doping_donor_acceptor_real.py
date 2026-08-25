#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Donor/Acceptor doping, the color-overlay auto-switch, and the
stale-doping re-attachment popup fix -- real TCADApplication (window
withdrawn), real ViennaPS + DevSim.

Root causes this pins (see docs/investigation_log.md, "Doping: five
confirmed gaps"):

  1. Uniform doping used to take one net-concentration field; it now
     takes independent Donor/Acceptor fields (net = donor - acceptor),
     matching how Step Junction already worked.
  2. The P/N color overlay (_doping_color_segments) was already
     correct but invisible by default (viewer_layer_var defaulted to
     "geometry"); a successful run_doping() now switches it to
     "doping" automatically.
  3. run_measurement()'s internal stale-doping re-attachment used to
     call the SAME run_doping() a direct button click uses, popping
     "No DevSim solve was run" in the middle of a MEASURE click --
     exactly when a real DevSim solve is about to run a few lines
     later. run_doping() gained a `silent` parameter; the internal
     re-attachment call passes silent=True, a direct click does not.

No ViennaPS-installed check up front: driving the real GUI needs a Tk
display too, so both are treated as environment gaps and reported as
SKIPPED, matching this project's other _real.py tests that also need
optional infra.
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
    from tcad.device.devsim import backend as devsim_backend
    if not devsim_backend.is_available():
        app.destroy()
        print("SKIPPED: DevSim is not installed")
        return

    calls = []

    def make_trap(name):
        def trap(*args, **kwargs):
            calls.append((name, args[:2]))
            return True
        return trap

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        if hasattr(gui.messagebox, name):
            setattr(gui.messagebox, name, make_trap(name))

    try:
        app.withdraw()
        app.update_idletasks()

        # Keep the solve cheap -- this project's own finding: grid 0.2
        # keeps a 2-terminal solve a few seconds; the raw GUI default
        # (0.05) can take 5+ minutes on the default 10x8um wafer.
        app.grid_var.set(0.2)

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"
        mesh_a = app.last_final_mesh

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1.0e16)
        app.dope_uniform_acceptor_var.set(5.0e15)

        assert app.viewer_layer_var.get() == "geometry"
        calls.clear()
        assert app.run_doping() is True

        assert app.viewer_layer_var.get() == "doping", (
            "a successful doping apply must auto-switch the color-overlay "
            f"layer, got {app.viewer_layer_var.get()!r}")
        doping_popups = [c for c in calls if c[0] == "showinfo" and c[1][0] == "Doping"]
        assert len(doping_popups) == 1, (
            f"a direct doping click must still show its result popup, "
            f"got {doping_popups}")

        net = app.last_doped_result.doping.regions[0].net_doping_cm3
        assert abs(net - 5.0e15) < 1.0, (
            f"net doping must equal donor - acceptor = 5e15, got {net:.3e}")

        # Make the doping stale: a later real step replaces the mesh.
        ok = app._materialize_current_wafer()
        assert ok
        assert app.last_final_mesh != mesh_a
        assert app._doping_is_stale()

        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        app.meas_voltage_var.set(0.3)
        calls.clear()
        app.run_measurement()

        stale_popups = [c for c in calls if c[0] == "showinfo" and c[1][0] == "Doping"]
        assert not stale_popups, (
            f"MEASURE's internal stale-doping re-attachment must stay silent, "
            f"got {stale_popups}")
        errors = [c for c in calls if c[0] == "showerror"]
        assert not errors, f"MEASURE reported an error: {errors}"
        measurement_popups = [
            c for c in calls if c[0] == "showinfo" and c[1][0] == "Measurement"
        ]
        assert len(measurement_popups) == 1, (
            f"a real DevSim solve must still report its own result, "
            f"got {measurement_popups}")
        assert not app._doping_is_stale(), (
            "doping must be re-attached to the new mesh after MEASURE, not "
            "left stale")

        print("Donor/Acceptor doping -> correct net concentration; color "
              "layer auto-switches; a direct click still pops up; MEASURE's "
              "internal re-attachment stays silent while its own real "
              "DevSim result still reports:", measurement_popups[0][1])

        # ------------------------------------------------------------
        # SiO2-barrier exclusion, through the REAL run_measurement()
        # path -- see docs/investigation_log.md, "SiO2 doesn't block
        # doping". Mirrors Task 1's own fixture
        # (tests/integration/test_doping_barrier_windows_real.py:
        # blanket oxidation, then a lithography-masked isotropic etch
        # that clears SiO2 only through the developed opening) but
        # drives it through the real GUI process panels instead of a
        # hand-built recipe, to prove the new field is actually read
        # and derive_barrier_covered_windows()'s call args are correct
        # end-to-end, not just that the library function works in
        # isolation.
        import tcad.device.devsim.doping_mapping as doping_mapping_module
        from tcad.device.devsim import backend as devsim_backend

        app.reset()

        # Real ViennaPS worker runs as a subprocess per RUN click; grid
        # 0.1 matches test_doping_barrier_windows_real.py's own BASE
        # (already real-verified: fine enough to resolve a thin real
        # SiO2 barrier, cheap enough to run in a regression suite).
        app.grid_var.set(0.1)

        # --- Step 1: blanket thermal oxidation. Plain oxidation is
        # ALWAYS blanket (run_oxidation() never invents a mask), so
        # this needs no lithography first -- it grows real SiO2 over
        # the whole wafer surface.
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(1.0)
        calls.clear()
        app.run_oxidation()
        errors = [c for c in calls if c[0] == "showerror"]
        assert not errors, f"oxidation reported an error: {errors}"
        mesh_after_ox = app.last_final_mesh
        assert mesh_after_ox, "oxidation produced no mesh"

        # --- Step 2: lithography, left at every GUI default. The
        # default mask_openings_um [[3.5, 6.5]] on the default 10um
        # -wide wafer develops to a domain-centered opening at
        # x=[-1.5, 1.5] (PATTERNED_SPANS in
        # tests/unit/test_gui_litho_lifecycle_mock.py) -- resist covers
        # everywhere else.
        app.process_pr_coat()
        app.process_mask_alignment()
        app.process_exposure()
        app.process_develop()
        assert app.wafer.developed

        # --- Step 3: isotropic etch, masked by the just-developed
        # resist (_mask_recipe_keys_for_current_step() remasks a
        # chained step from the real resist state). Clears the SiO2
        # down to Si through the opening while the resist protects the
        # SiO2 everywhere else -- exactly Task 1's fixture geometry,
        # built through real GUI panels instead of a hand-written
        # recipe.
        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.3)
        app.etch_time_var.set(1.0)
        calls.clear()
        app.run_etch()
        errors = [c for c in calls if c[0] == "showerror"]
        assert not errors, f"etch reported an error: {errors}"
        assert app.last_final_mesh != mesh_after_ox, "etch produced no new mesh"

        # --- Step 4: Uniform doping on Si. ---
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1.0e17)
        app.dope_uniform_acceptor_var.set(0.0)
        calls.clear()
        assert app.run_doping() is True

        # --- Step 5: set the new barrier-threshold field, then
        # MEASURE. run_measurement() deletes its DevSim device in its
        # own `finally`, so NetDoping is captured by wrapping the real
        # apply_doping() (called internally by run_measurement()) --
        # this also captures the exact `exclude_windows` kwarg
        # run_measurement() computed and passed, proving the GUI
        # wiring end-to-end rather than re-deriving it separately here.
        app.dope_barrier_threshold_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        app.meas_voltage_var.set(0.0)

        captured = {}
        real_apply_doping = doping_mapping_module.apply_doping

        def spy_apply_doping(device, doping, **kwargs):
            real_apply_doping(device, doping, **kwargs)
            captured["exclude_windows"] = kwargs.get("exclude_windows")
            region_name = doping.regions[0].region
            module_ds = devsim_backend.require_devsim()
            captured["x"] = module_ds.get_node_model_values(
                device=device, region=region_name, name="x")
            captured["net"] = module_ds.get_node_model_values(
                device=device, region=region_name, name="NetDoping")

        doping_mapping_module.apply_doping = spy_apply_doping
        calls.clear()
        try:
            app.run_measurement()
        finally:
            doping_mapping_module.apply_doping = real_apply_doping

        errors = [c for c in calls if c[0] == "showerror"]
        assert not errors, f"MEASURE reported an error: {errors}"
        assert captured.get("exclude_windows"), (
            f"run_measurement() must derive real barrier-covered windows "
            f"and pass them into apply_doping(), got "
            f"{captured.get('exclude_windows')!r}")

        # run_measurement() imports with length_scale_to_cm=1.0e-4 (real
        # um -> cm physical scaling), so DevSim's own "x" node model is
        # in that NATIVE (cm) scale, while exclude_windows' min_um/max_um
        # are raw mesh microns -- apply_doping() itself converts between
        # them internally (see doping_mapping.py's own
        # `w["min_um"] * length_scale_to_cm`), so the same conversion is
        # applied here to compare on the same axis.
        length_scale_to_cm = 1.0e-4
        node_x = captured["x"]
        net = captured["net"]
        windows = captured["exclude_windows"]
        covered_vals = [
            n for x, n in zip(node_x, net)
            if any(
                w["min_um"] * length_scale_to_cm <= x <= w["max_um"] * length_scale_to_cm
                for w in windows
            )
        ]
        open_vals = [
            n for x, n in zip(node_x, net)
            if not any(
                w["min_um"] * length_scale_to_cm <= x <= w["max_um"] * length_scale_to_cm
                for w in windows
            )
        ]
        assert covered_vals and max(abs(v) for v in covered_vals) < 1.0, (
            f"NetDoping must be excluded (~0) under the real SiO2 barrier "
            f"the GUI derived, got max |v|="
            f"{max(abs(v) for v in covered_vals):.3e}")
        assert open_vals and min(abs(v) for v in open_vals) > 1.0e16, (
            f"NetDoping must still be the full concentration in the "
            f"lithography-opened window, got min |v|="
            f"{min(abs(v) for v in open_vals):.3e}")

        print("GUI-driven SiO2 barrier exclusion -> run_measurement() derived "
              f"{len(windows)} real barrier-covered window(s) "
              f"({windows}) from the actual mesh; NetDoping excluded "
              f"(max |v|={max(abs(v) for v in covered_vals):.3e}) under the "
              f"barrier and intact (min |v|="
              f"{min(abs(v) for v in open_vals):.3e}) in the open window.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
