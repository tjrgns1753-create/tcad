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
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
