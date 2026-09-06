#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final-review Fix 4 (2026-09-03 dopant-state-unification): the real
GUI's `run_measurement()` implant_windows branch solves ONLY
`doped_result.doping` (the single most-recent doping call) -- by
design, this project's real 1e20 cm^-3 convergence solution
(`run_robust_pn_junction_iv_sweep`) is not rewired to read
`self.wafer_state`'s full accumulated profile list. Task 10's canvas
color overlay DOES read that full accumulated list
(`self.wafer_state.dopant_profiles`), so a wafer carrying an EARLIER
accumulated profile (here, a Gaussian Implant, species "Sb") in
addition to the current Implant Windows call would show both on the
canvas while only the latter is actually solved -- this must be
disclosed honestly in the log, not left implicit.

Real GUI (`tcad_2d_stagewise.TCADApplication`), real ViennaPS 4.6.2, a
real accumulated WaferState, and the REAL profile-comparison logic Fix
4 adds. The one thing stubbed out is the DevSim drift-diffusion solve
itself (`run_robust_pn_junction_iv_sweep`) -- explicitly OUT OF SCOPE
for this fix (the task brief is explicit: "Do NOT rewire
implant_windows's solve path itself"), and known separately to be
slow/borderline-convergent on this exact recipe (CLAUDE.md OPEN item
2: the GUI's own 10x8um/1e20 default is a documented, sometimes very
slow or non-convergent equilibrium/bias-ramp case). The log line under
test is written BEFORE the solve is ever called, so stubbing the solve
to raise immediately (caught by run_measurement()'s own real
exception handling, which this test also exercises for real) proves
exactly what Fix 4 changed, without paying for -- or being blocked by
-- an unrelated, already-documented convergence question.
"""
import sys
from pathlib import Path

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

    # Trap messagebox so a real popup (success/error dialog, or a
    # downstream "Convergence failure!" error dialog) never blocks this
    # automated run -- same established pattern as
    # tests/unit/test_gui_no_forced_order_mock.py.
    originals = {name: getattr(gui.messagebox, name) for name in ("showinfo", "showerror")}
    for name in originals:
        setattr(gui.messagebox, name, lambda *a, **k: None)

    # Stub the DevSim solve itself -- deliberately out of scope for
    # Fix 4 (see module docstring) and known separately slow on this
    # exact recipe. run_measurement() does a LOCAL
    # `from tcad.characterization.robust_iv_sweep import
    # run_robust_pn_junction_iv_sweep` at call time, so patching the
    # module attribute here (before that local import executes) is
    # picked up correctly -- everything else in run_measurement() up to
    # and including Fix 4's own new log line still runs for real.
    import tcad.characterization.robust_iv_sweep as robust_iv_sweep_module
    original_solve = robust_iv_sweep_module.run_robust_pn_junction_iv_sweep

    def _stub_solve(*args, **kwargs):
        raise RuntimeError("solve intentionally stubbed for this test -- see module docstring")

    robust_iv_sweep_module.run_robust_pn_junction_iv_sweep = _stub_solve

    try:
        app.withdraw()
        app.update_idletasks()

        assert app._materialize_current_wafer(), "materializing a real ViennaPS wafer failed"

        # A Gaussian Implant FIRST (species "Sb", donor), positioned
        # well away from the Implant Windows source/drain positions
        # below -- accumulates on app.wafer_state.
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(3.0)
        app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(1.0e18)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("Sb")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)

        # THEN Implant Windows (the panel's own default field values) --
        # the kind this Fix targets.
        app.doping_kind.set("Implant Windows")
        assert app.run_doping(silent=True)

        species_before = {p.species for p in app.wafer_state.dopant_profiles}
        print(f"[setup] accumulated species on app.wafer_state before MEASURE: "
              f"{sorted(s for s in species_before if s)}")
        assert "Sb" in species_before, "fixture is broken: the earlier Gaussian Implant must have accumulated"

        app.run_measurement()

        log_text = app.log.get("1.0", "end")
        note_line = next(
            (line for line in log_text.splitlines() if line.startswith("NOTE: Implant Windows")),
            None,
        )
        print(f"[log] {note_line!r}")
        assert note_line is not None, (
            f"expected a real NOTE line disclosing the overlay/solve divergence, "
            f"found none in the log:\n{log_text}"
        )
        assert "Sb" in note_line, (
            f"expected the accumulated Gaussian Implant's own species (Sb) named "
            f"in the disclosure, got: {note_line!r}"
        )

        print("\nFix 4 VERIFIED against the real GUI: a MEASURE click on Implant "
              "Windows doping, with an earlier accumulated Gaussian Implant still "
              "on the wafer, honestly logs which accumulated profile(s) are NOT "
              "reflected in this solve.")
    finally:
        robust_iv_sweep_module.run_robust_pn_junction_iv_sweep = original_solve
        for name, fn in originals.items():
            setattr(gui.messagebox, name, fn)
        app.destroy()


if __name__ == "__main__":
    main()
