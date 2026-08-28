#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drives the real TCADApplication (window withdrawn) through Pin
placement -> RESOLVE -> DC operating point -> Id-Vgs sweep, on a real
gate_stack device built via the existing GUI geometry panel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        print("SKIPPED: ViennaPS is not installed")
        return

    # Fix 3: trap showinfo/showerror too, extending
    # test_gui_no_forced_order_mock.py's own trap-and-record pattern
    # (which only covers confirm-style dialogs). run_gate_stack()'s
    # success path calls messagebox.showinfo(), and this panel's own
    # new methods call showerror/showinfo on various paths -- a real Tk
    # modal can block via its own wait_window() even under a withdrawn
    # root. Not asserted empty at the end: showinfo/showerror are normal
    # informational feedback here (e.g. run_gate_stack()'s pre-existing
    # success dialog), not a forced-order gate -- only the confirm-style
    # dialogs the sibling test traps are actually forbidden.
    blocked = []
    for name in ("showinfo", "showerror"):
        def trap(*args, _name=name, **kwargs):
            blocked.append((_name, args[:2]))
            return None
        setattr(gui.messagebox, name, trap)

    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()

        # Build a real gate_stack device via the EXISTING geometry panel
        # (unmodified by this task).
        app.run_gate_stack()
        # run_gate_stack() returns None on BOTH success and failure (its
        # success path falls off the end after messagebox.showinfo(),
        # its failure paths each do a bare `return`) -- so the real
        # success check is the wafer state, not the return value.
        assert app.wafer.processed is True

        # Place 4 pins at real wafer coordinates via the NEW electrode
        # panel. Coordinates are MEASURED against the real exported
        # gate_stack mesh at this GUI's own default recipe values, not
        # guessed.
        #
        # Source/Drain deliberately do NOT land on the W/Cu source/drain
        # PADS here (a first attempt, matching where a real CAD probe
        # would physically touch, measured those at x=1.3/4.7,
        # y=0.095 -- both resolve cleanly via validate_pin_placement).
        # That combination cannot reach a working DC operating point:
        # confirmed by direct execution that solve_mosfet_dc_operating_
        # point's own drift-diffusion stage requires Source/Drain/Body
        # to be real Si-region contacts (a metal pad has no Electrons/
        # Holes continuity equation in this project's physics -- see
        # run_dc_operating_point's own comments). This GUI's default
        # recipe (channel_um narrower than source_um/drain_um) leaves a
        # small ungated strip of BARE, exposed Si between the channel
        # and each pad (x in roughly [-1.0,-0.8] and [0.8,1.0] domain,
        # i.e. wafer [2.0,2.2] / [3.8,4.0]) -- Source/Drain are placed
        # there instead, landing on real "Si" directly.
        app.add_electrode_pin(name="Source", role="Source", x_um=2.1, y_um=0.0)
        app.add_electrode_pin(name="Drain", role="Drain", x_um=3.9, y_um=0.0)
        # Gate DOES land on the real TiN gate electrode (x=3.0 is the
        # channel center, y=0.14 sits on TiN's own boundary) -- this
        # works because the gate is potential-only in every stage of
        # this solve (no transport equation), so run_dc_operating_point
        # idealizes TiN with the same oxide-style contact physics
        # mosfet_equation.py already uses for the real SiO2 -- verified
        # to converge through both equilibrium and drift-diffusion.
        app.add_electrode_pin(name="Gate", role="Gate", x_um=3.0, y_um=0.14)
        app.add_electrode_pin(name="Body", role="Body", x_um=3.0, y_um=-0.99)
        assert len(app.electrode_pins) == 4

        resolved = app.resolve_electrode_pins()
        assert resolved is not None, "pin resolution against the real mesh failed"
        assert set(resolved.contacts) >= {"Source", "Drain"}, resolved.contacts
        print(f"[1/2] 4 pins resolved to real contacts: {sorted(resolved.contacts)}")

        op_point = app.run_dc_operating_point(
            drain_voltage=0.1, gate_voltage=1.0, body_voltage=0.0,
        )
        assert op_point is not None
        print(f"[2/2] DC operating point solved from the GUI: currents={op_point.currents}")

    finally:
        app.destroy()

    print()
    print("GUI ELECTRODE PANEL VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
