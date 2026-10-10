#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""실제 GUI의 donor/acceptor 입력·stale cache·chemical profile·barrier 계약.

순수 n/p ACTIVE 선언만 실제 측정한다. 보상 도핑 및 GUI implant CHEMICAL은
측정 성공으로 승격하지 않는다. 산화막은 DIRECT_EXPLICIT_GEOMETRY 입력이고,
실제 selective etch 이후 exact transition이 없으면 숫자 대신 거부해야 한다.
필수 Tk/ViennaPS/DEVSIM 결손은 실패다. 기존 scalar/species 입력 검증을 유지한다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_measurement_canonical_state_gate_real import _measure, _assert_supported

MESSAGEBOX = ("showinfo", "showerror", "showwarning", "askquestion",
              "askyesno", "askyesnocancel", "askokcancel", "askretrycancel")


def _configure(app):
    app.wafer.width_um = 4.0
    app.wafer.silicon_depth_um = 1.0
    app.grid_var.set(0.2)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")
    app.meas_voltage_var.set(0.01)


def _blocked(app, devsim, label, reason=None):
    b = _measure(app, devsim, label)
    assert b["solve_calls"] == b["doping_writes"] == 0, b
    assert not b["currents_in_log"] and not b["measurement_section_logged"], b
    assert b["history_entries_added"] == 0 and b["unsupported_in_log"], b
    assert b["last_physics_status"]["resolution"] == "UNSUPPORTED_BY_MODEL", b
    if reason:
        assert b["last_physics_status"]["reason_code"] == reason, b
    assert app._measurement_fields is None and app._measurement_fields_result is None
    assert not devsim.get_device_list()
    return b


def _chemical_apply(app, gui, devsim, calls, metrics, function_name, label):
    real = getattr(gui, function_name)
    requested = []

    def observe(*a, **kw):
        result = real(*a, **kw)
        requested.append(result)
        return result

    history, layer, cached = len(app.history), app.viewer_layer_var.get(), app.last_doped_result
    prior_ids = {a.attachment_id for a in app.wafer_state.attachments}
    with patch.object(gui, function_name, observe):
        assert app.run_doping() is False
    assert len(requested) == 1
    added = [a for a in app.wafer_state.attachments if a.attachment_id not in prior_ids]
    assert added and all(a.chemical_state == "CHEMICAL" for a in added)
    assert app.last_doped_result is cached and len(app.history) == history
    assert app.viewer_layer_var.get() == layer
    assert not calls, calls
    metrics[label] = _blocked(app, devsim, label, "DOPANT_ACTIVATION_MODEL_MISSING")
    metrics[label]["new_attachments"] = [
        {"model":a.model, "species":a.species, "polarity":a.polarity,
         "chemical_state":a.chemical_state, "model_params":a.model_params}
        for a in added]
    return requested[0].doping.regions[0]


def main():
    import tcad_2d_stagewise as gui
    from tcad.backends.viennaps import session
    from tcad.device.devsim import backend
    assert session.is_available(), "mandatory ViennaPS unavailable"
    assert backend.is_available(), "mandatory DEVSIM unavailable"
    devsim = backend.require_devsim()
    app = gui.TCADApplication()  # Tk error is a real test failure, never SKIP
    calls = []
    saved = {n:getattr(gui.messagebox,n) for n in MESSAGEBOX}
    for name in saved:
        setattr(gui.messagebox, name,
                lambda *a, _name=name, **kw: calls.append((_name,str(a))) or True)
    metrics = {}
    try:
        app.withdraw()
        app.update_idletasks()
        _configure(app)
        assert app._materialize_current_wafer()
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(5e15)
        before = app.log.get("1.0","end-1c")
        assert app.viewer_layer_var.get() == "geometry"
        assert app.run_doping() is True
        assert app.viewer_layer_var.get() == "doping"
        assert "Doping: Doping profile attached" in app.log.get("1.0","end-1c")[len(before):]
        r = app.last_doped_result.doping.regions[0]
        assert abs(r.net_doping_cm3 - 5e15) < 1.0
        q = app.wafer_state.net_doping_at(0.0,-0.5)
        assert q.donor_concentration == 1e16 and q.acceptor_concentration == 5e15
        assert q.net_doping == 5e15
        metrics["compensated"] = _blocked(
            app, devsim, "compensated", "COMPENSATED_TRANSPORT_MODEL_MISSING")

        # Stale cache is tested on SUPPORTED controls, not by bypassing compensation.
        for name, donor, acceptor in (("n",1e16,0.0),("p",0.0,5e15)):
            app.reset()
            _configure(app)
            assert app._materialize_current_wafer()
            app.doping_kind.set("Uniform")
            app.dope_uniform_region_var.set("Si")
            app.dope_uniform_donor_var.set(donor)
            app.dope_uniform_acceptor_var.set(acceptor)
            assert app.run_doping() is True
            old_mesh, state = app.last_final_mesh, app.wafer_state
            ids = [a.attachment_id for a in state.attachments]
            inventories = [a.inventory_cm_per_depth for a in state.attachments]
            events = len(state.events)
            assert app._materialize_current_wafer()
            assert app.last_final_mesh != old_mesh and app._doping_is_stale()
            metrics[name] = _measure(app, devsim, name)
            _assert_supported(name, metrics[name])
            assert not app._doping_is_stale()
            assert app.wafer_state is state
            assert [a.attachment_id for a in state.attachments] == ids
            assert [a.inventory_cm_per_depth for a in state.attachments] == inventories
            assert len(state.events) == events
            assert app._measurement_fields is not None
            assert app._measurement_fields_result is not None
            metrics[name]["reattach_identity"] = True
            metrics[name]["attachment_count"] = len(ids)
            assert not devsim.get_device_list()

        app.reset()
        _configure(app)
        assert app._materialize_current_wafer()
        # Gaussian Implant: donor/acceptor input fields (Task 8). Same
        # mesh as the Uniform scenario above -- this only checks the
        # Python-level DopingRegion the panel builds, no new DevSim
        # solve needed.
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(0.0)
        app.dope_gauss_straggle_var.set(0.5)
        app.dope_gauss_donor_var.set(2.0e17)
        app.dope_gauss_acceptor_var.set(3.0e16)
        app.dope_gauss_donor_species_var.set("P")
        app.dope_gauss_acceptor_species_var.set("B")
        gauss_region = _chemical_apply(app, gui, devsim, calls, metrics,
                                       "apply_gaussian_implant_doping", "gaussian")
        expected_gauss_net = 2.0e17 - 3.0e16
        assert abs(gauss_region.peak_conc_cm3 - expected_gauss_net) < 1.0, (
            f"Gaussian Implant peak_conc_cm3 must equal donor - acceptor = "
            f"{expected_gauss_net:.3e}, got {gauss_region.peak_conc_cm3:.3e}")
        assert abs(gauss_region.donor_peak_conc_cm3 - 2.0e17) < 1.0, (
            "raw donor_peak_conc_cm3 must be preserved on the DopingRegion "
            f"(not just collapsed into peak_conc_cm3), got "
            f"{gauss_region.donor_peak_conc_cm3!r}")
        assert abs(gauss_region.acceptor_peak_conc_cm3 - 3.0e16) < 1.0, (
            "raw acceptor_peak_conc_cm3 must be preserved on the "
            f"DopingRegion, got {gauss_region.acceptor_peak_conc_cm3!r}")
        assert gauss_region.donor_species == "P", gauss_region.donor_species
        assert gauss_region.acceptor_species == "B", gauss_region.acceptor_species

        print("Gaussian Implant donor/acceptor -> peak_conc_cm3="
              f"{gauss_region.peak_conc_cm3:.3e} (donor - acceptor); raw "
              f"donor={gauss_region.donor_peak_conc_cm3:.3e}({gauss_region.donor_species}) "
              f"acceptor={gauss_region.acceptor_peak_conc_cm3:.3e}"
              f"({gauss_region.acceptor_species}) preserved on the DopingRegion.")

        # ------------------------------------------------------------
        # Implant Windows: donor/acceptor background + per-window
        # fields (Task 8). Same mesh, same reasoning as above.
        app.doping_kind.set("Implant Windows")
        app.dope_win_region_var.set("Si")
        app.dope_win_axis_var.set("x")
        app.dope_win_donor_bg_var.set(1.0e14)
        app.dope_win_acceptor_bg_var.set(1.0e17)
        app.dope_win_src_min_var.set(-1.6)
        app.dope_win_src_max_var.set(-0.6)
        app.dope_win_src_donor_var.set(1.0e20)
        app.dope_win_src_acceptor_var.set(0.0)
        app.dope_win_drn_min_var.set(0.6)
        app.dope_win_drn_max_var.set(1.6)
        app.dope_win_drn_donor_var.set(9.0e19)
        app.dope_win_drn_acceptor_var.set(1.0e19)
        win_region = _chemical_apply(app, gui, devsim, calls, metrics,
                                     "apply_implant_windows_doping", "windows")
        expected_bg_net = 1.0e14 - 1.0e17
        assert abs(win_region.net_doping_cm3 - expected_bg_net) < 1.0, (
            f"Implant Windows background net_doping_cm3 must equal donor - "
            f"acceptor = {expected_bg_net:.3e}, got "
            f"{win_region.net_doping_cm3:.3e}")
        assert abs(win_region.donor_conc_cm3 - 1.0e14) < 1.0, (
            "raw background donor_conc_cm3 must be preserved on the "
            f"DopingRegion, got {win_region.donor_conc_cm3!r}")
        assert abs(win_region.acceptor_conc_cm3 - 1.0e17) < 1.0, (
            "raw background acceptor_conc_cm3 must be preserved on the "
            f"DopingRegion, got {win_region.acceptor_conc_cm3!r}")

        windows = win_region.implant_windows
        assert windows is not None and len(windows) == 2, windows
        src_window, drn_window = windows[0], windows[1]
        expected_src_net = 1.0e20 - 0.0
        expected_drn_net = 9.0e19 - 1.0e19
        assert abs(src_window["conc_cm3"] - expected_src_net) < 1.0, src_window
        assert abs(src_window["donor_conc_cm3"] - 1.0e20) < 1.0, (
            "raw source window donor_conc_cm3 must be preserved, not just "
            f"collapsed into conc_cm3, got {src_window!r}")
        assert abs(src_window["acceptor_conc_cm3"] - 0.0) < 1.0, src_window
        assert abs(drn_window["conc_cm3"] - expected_drn_net) < 1.0, drn_window
        assert abs(drn_window["donor_conc_cm3"] - 9.0e19) < 1.0, (
            "raw drain window donor_conc_cm3 must be preserved, not just "
            f"collapsed into conc_cm3, got {drn_window!r}")
        assert abs(drn_window["acceptor_conc_cm3"] - 1.0e19) < 1.0, drn_window

        print("Implant Windows donor/acceptor -> background net="
              f"{win_region.net_doping_cm3:.3e} (donor {win_region.donor_conc_cm3:.3e} "
              f"- acceptor {win_region.acceptor_conc_cm3:.3e}); source "
              f"conc_cm3={src_window['conc_cm3']:.3e}, drain "
              f"conc_cm3={drn_window['conc_cm3']:.3e}; raw donor/acceptor "
              "preserved on both region and window dicts.")

        # ------------------------------------------------------------
        # Explicit oxide input + real selective etch. NOT oxidation or activation.
        from _explicit_chain_fixture import build_explicit_chain_state, run_steps_from_state, native_eps
        from tcad.process.flow import FlowStep
        import tcad.process.etching  # registry
        from tcad.physics.wafer_state_accumulation import advance_wafer_state
        import tcad.device.devsim.mesh_import as mesh_import
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            stack = build_explicit_chain_state(
                tmp, x_extent_um=10.0, y_extent_um=8.0, silicon_depth_um=5.0,
                oxide_top_um=0.3, grid_delta_um=0.1)
            assert stack.provenance == "DIRECT_EXPLICIT_GEOMETRY"
            assert stack.forbidden_call_counts == {"Oxidation":0,"Process":0}
            recipe = dict(grid_delta_um=0.1, x_extent_um=10.0, y_extent_um=8.0,
                          silicon_depth_um=5.0, pr_thickness_um=0.5,
                          remask_spans_um=[[-5.0,-1.5],[1.5,5.0]], mask_material="PHS",
                          material_rates={"SiO2":-0.6,"Si":0.0,"PHS":0.0},
                          default_rate=0.0, etch_time_s=1.0)
            results, counts, stages = run_steps_from_state(
                stack, tmp, "selective_etch", [FlowStep("etching","isotropic",recipe)])
            assert len(results) == 1 and counts["Oxidation"] == 0 and counts["Process"] > 0
            stage = stages[0]
            assert np.max(np.abs(stage.native["Si"] - stack.native_tops["Si"])) <= native_eps(8.0)
            windows = mesh_import.derive_barrier_covered_windows(
                results[0], doped_region="Si", barrier_material="SiO2", axis="x",
                min_barrier_thickness_um=0.01)
            assert windows and not any(w["min_um"] < 0.0 < w["max_um"] for w in windows), windows
            assert any(w["min_um"] <= -4.0 <= w["max_um"] for w in windows), windows
            app.reset()
            _configure(app)
            app.last_final_mesh = results[0].volume_mesh_path
            app.last_domain_state = results[0].domain_state_path
            # No explicit transform exists for the actual curved etch: never infer one.
            app.wafer_state = advance_wafer_state(None, results[0], "etching")
            app.doping_kind.set("Uniform")
            app.dope_uniform_region_var.set("Si")
            app.dope_uniform_donor_var.set(1e17)
            app.dope_uniform_acceptor_var.set(0.0)
            app.dope_barrier_threshold_var.set(0.01)
            observed = []
            real_derive = mesh_import.derive_barrier_covered_windows

            def observe_derive(*a, **kw):
                found = real_derive(*a, **kw)
                observed.append({"axis":kw.get("axis"),"windows":found})
                return found

            for axis in ("x","y"):
                app.meas_axis_var.set(axis)
                with patch.object(mesh_import, "derive_barrier_covered_windows", observe_derive):
                    assert app.run_doping() is False
                assert observed[-1]["axis"] == "x" and observed[-1]["windows"] == windows
                assert not app.wafer_state.attachments
                assert app.wafer_state.unresolved_inventory
                b = _blocked(app, devsim, "barrier_"+axis)
                b["barrier_windows"] = windows
                b["detector_axis"] = observed[-1]["axis"]
                b["input_provenance"] = stack.provenance
                metrics["barrier_"+axis] = b
            assert len(observed) == 2
        assert not calls, calls
        assert not devsim.get_device_list()
        # Machine-readable evidence with all refusal/normal cases; runner sanitizes paths.
        print("METRICS " + json.dumps(metrics, default=str))
        print("PASS: 7 GUI cases; pure n/p stale reattach supported, compensated/chemical/"
              "unresolved barrier blocked; original donor/acceptor/species fields preserved.")
    finally:
        for name, callback in saved.items():
            setattr(gui.messagebox, name, callback)
        app.destroy()


if __name__ == "__main__":
    main()
