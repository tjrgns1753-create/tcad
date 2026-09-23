#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Implant Windows MEASURE solves the canonical accumulated doping --
no overlay/solve divergence left to disclose (Tier 1-1 contract).

This file used to pin Final-review Fix 4 (2026-09-03): the
implant_windows branch of `run_measurement()` solved ONLY
`doped_result.doping` (the most recent doping call) and logged a
"NOTE: Implant Windows measurement reflects only its own doping
profile; N other accumulated profile(s) ... are not included in this
solve." That NOTE disclosed a real divergence between what the canvas
overlay showed (the full accumulated state) and what DevSim solved.
Tier 1-1 removed the divergence itself: the robust continuation is now
driven by the canonical `self.wafer_state` through the central gate, so
the old assertion ("the NOTE line must exist") would pin the bug as the
expected behaviour. The contract here is the replacement:

  - no divergence NOTE is logged,
  - `run_robust_pn_junction_iv_sweep` receives `app.wafer_state` itself,
  - the NetDoping DevSim actually solved with is the canonical
    accumulated value at every node -- the earlier Gaussian Implant
    (species "Sb") included -- and differs from an Implant-Windows-only
    NetDoping wherever that Gaussian contributes,
  - the real solve returns finite, equal-and-opposite terminal currents.

Real GUI (withdrawn), real ViennaPS 4.6.2, real DevSim. The robust
function and the devsim calls are wrapped by pass-through recorders
that always call the originals -- nothing is stubbed. Small wafer
(4 x 1 um, grid 0.2 um) and low concentrations keep the real solve
fast; this file does not test heavy (1e20 cm^-3) convergence.
"""
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

LENGTH_SCALE_TO_CM = 1.0e-4


def _gaussian_part(state, x_um, y_um):
    part = 0.0
    for a in state.attachments:
        b = a.support_region_um
        if a.model == "gaussian_v1" and b[0] <= x_um <= b[1] and b[2] <= y_um <= b[3]:
            mag = max(0.0, float(a.concentration_at(x_um, y_um)))
            part += mag if a.polarity == "donor" else -mag
    return part


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    from tcad.backends.viennaps import session as viennaps_session
    from tcad.device.devsim import backend as devsim_backend
    if not viennaps_session.is_available() or not devsim_backend.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS or DevSim is not installed")
        return
    devsim = devsim_backend.require_devsim()

    originals = {name: getattr(gui.messagebox, name) for name in ("showinfo", "showerror")}
    for name in originals:
        setattr(gui.messagebox, name, lambda *a, **k: None)

    # Pass-through recorders: the real robust sweep and the real devsim
    # calls still run. run_measurement() imports the robust function
    # locally at call time, so the module attribute is what it calls.
    import tcad.characterization.robust_iv_sweep as robust_iv_sweep_module
    original_sweep = robust_iv_sweep_module.run_robust_pn_junction_iv_sweep
    sweep_calls = []

    def recording_sweep(*args, **kwargs):
        sweep_calls.append(kwargs)
        return original_sweep(*args, **kwargs)

    original_delete = devsim.delete_device
    final_nodes = {}

    def snapshot_then_delete(*args, **kwargs):
        for model in ("x", "y", "NetDoping"):
            final_nodes[model] = list(devsim.get_node_model_values(
                device=kwargs.get("device"), region="Si", name=model))
        return original_delete(*args, **kwargs)

    robust_iv_sweep_module.run_robust_pn_junction_iv_sweep = recording_sweep
    devsim.delete_device = snapshot_then_delete
    try:
        app.withdraw()
        app.update_idletasks()
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        app.meas_voltage_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        assert app._materialize_current_wafer(), "materializing a real ViennaPS wafer failed"

        # A Gaussian Implant FIRST (species "Sb", donor) -- accumulates on
        # app.wafer_state.
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(0.0)
        app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_donor_var.set(1.0e16)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("Sb")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)

        # THEN Implant Windows, at low concentrations for a fast real solve.
        app.doping_kind.set("Implant Windows")
        for name, value in {
            "dope_win_donor_bg_var": 1.0e15, "dope_win_acceptor_bg_var": 0.0,
            "dope_win_src_donor_var": 1.0e16, "dope_win_src_acceptor_var": 0.0,
            "dope_win_drn_donor_var": 1.0e16, "dope_win_drn_acceptor_var": 0.0,
        }.items():
            getattr(app, name).set(value)
        assert app.run_doping(silent=True)

        species = {p.species for p in app.wafer_state.dopant_profiles}
        print(f"[setup] accumulated species on app.wafer_state before MEASURE: "
              f"{sorted(s for s in species if s)}")
        assert "Sb" in species, "fixture is broken: the earlier Gaussian Implant must have accumulated"

        log_before = app.log.get("1.0", "end-1c")
        app.run_measurement()
        log = app.log.get("1.0", "end-1c")[len(log_before):]
        state = app.wafer_state
    finally:
        robust_iv_sweep_module.run_robust_pn_junction_iv_sweep = original_sweep
        devsim.delete_device = original_delete
        for name, fn in originals.items():
            setattr(gui.messagebox, name, fn)
        app.destroy()

    note_lines = [line for line in log.splitlines() if line.startswith("NOTE: Implant Windows")]
    print(f"[log] divergence NOTE lines: {note_lines!r}")
    assert not note_lines and "not included in this solve" not in log, (
        f"the old overlay/solve divergence NOTE is still logged: {note_lines}")

    assert len(sweep_calls) == 1, f"expected one robust sweep call, got {len(sweep_calls)}"
    assert sweep_calls[0].get("state") is state, "the robust sweep did not receive app.wafer_state"
    assert "doping" not in sweep_calls[0], "the robust sweep was handed a DopingProfile"
    assert any(a.species == "Sb" and a.model == "gaussian_v1" for a in sweep_calls[0]["state"].attachments)

    assert final_nodes.get("NetDoping"), f"DevSim never held a solved NetDoping; log:\n{log}"
    xs = [x / LENGTH_SCALE_TO_CM for x in final_nodes["x"]]
    ys = [y / LENGTH_SCALE_TO_CM for y in final_nodes["y"]]
    solved = final_nodes["NetDoping"]
    canonical = [state.net_doping_at(x, y).net_doping for x, y in zip(xs, ys)]
    mismatched = sum(1 for s, c in zip(solved, canonical) if s != c)
    gauss = [_gaussian_part(state, x, y) for x, y in zip(xs, ys)]
    windows_only = [s - g for s, g in zip(solved, gauss)]
    needing_gauss = sum(1 for s, w in zip(solved, windows_only) if abs(s - w) > 0.01 * abs(s))
    print(f"[solve] nodes={len(solved)} mismatched_vs_canonical={mismatched} "
          f"max_Sb_part={max(gauss):.3e} nodes_where_Sb_changes_NetDoping_by_>1%={needing_gauss}")
    assert mismatched == 0, f"solved NetDoping differs from canonical at {mismatched} node(s)"
    assert max(gauss) >= 0.9e16 and needing_gauss > 0, (
        "the earlier Gaussian (Sb) is not part of the solved NetDoping")

    currents = [float(m) for m in re.findall(r"I = ([-+0-9.eE]+) A", log)][:2]
    print(f"[solve] terminal currents: {currents}")
    assert len(currents) == 2 and all(math.isfinite(i) for i in currents), log
    assert abs(currents[0] + currents[1]) <= 1e-4 * abs(currents[0]), currents

    print("\nVERIFIED against the real GUI: Implant Windows MEASURE with an earlier accumulated "
          "Gaussian Implant logs no divergence NOTE, hands app.wafer_state to the robust "
          "sweep, and DevSim solves the canonical accumulated NetDoping (Sb included).")


if __name__ == "__main__":
    main()
