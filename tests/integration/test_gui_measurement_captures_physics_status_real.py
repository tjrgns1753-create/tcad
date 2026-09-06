#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final-review Fix 3 (2026-09-03 dopant-state-unification):
run_measurement()'s own call to
tcad.device.devsim.doping_mapping.apply_doping() used to discard its
returned physics_status entirely (a bare expression statement, no
assignment) -- every OTHER real process step already captures its own
physics_status into self.last_physics_status (see run_etch/
run_oxidation/run_deposition/_on_thermal_anneal_clicked), so doping's
own real gaps (e.g. a Fix-2 CONVERSION-caused RECOVERY entry) were the
one real process step whose status never reached that attribute at
all.

Proven here with a real, unambiguous sentinel: self.last_physics_status
is set to a value apply_doping() could never itself produce
("SENTINEL_BEFORE_MEASURE") immediately before a real MEASURE click,
then checked to have genuinely changed afterward -- proving the
assignment fires on the real code path, not merely that it happens to
already be None both before and after.

Real GUI (tcad_2d_stagewise.TCADApplication), real ViennaPS 4.6.2, real
DevSim. Uses the same fast, small, blanket (no-oxidation) wafer this
project's own test_ce1_order_sensitive_geometry_real.py base wafer
uses, and a plain Gaussian Implant (no barrier, no gap) so the real
underlying physics_status is None -- irrelevant to what this fix
proves (that the return value REACHES self.last_physics_status at
all), and keeps this test fast.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_SENTINEL = "SENTINEL_BEFORE_MEASURE"


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

    originals = {name: getattr(gui.messagebox, name) for name in ("showinfo", "showerror")}
    for name in originals:
        setattr(gui.messagebox, name, lambda *a, **k: None)

    try:
        app.withdraw()
        app.update_idletasks()

        assert app._materialize_current_wafer(), "materializing a real ViennaPS wafer failed"

        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(0.0)
        app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_donor_var.set(1.0e17)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)

        app.last_physics_status = _SENTINEL
        print(f"[before MEASURE] app.last_physics_status = {app.last_physics_status!r}")

        app.run_measurement()

        print(f"[after MEASURE]  app.last_physics_status = {app.last_physics_status!r}")
        assert app.last_physics_status != _SENTINEL, (
            "Fix 3: run_measurement()'s apply_doping() call must capture its "
            "returned physics_status into self.last_physics_status -- the "
            "sentinel value survived unchanged, meaning nothing was assigned"
        )

        print("\nFix 3 VERIFIED against the real GUI: run_measurement()'s "
              "apply_doping() return value now reaches self.last_physics_status "
              "(sentinel value was genuinely overwritten by a real MEASURE click).")
    finally:
        for name, fn in originals.items():
            setattr(gui.messagebox, name, fn)
        app.destroy()


if __name__ == "__main__":
    main()
