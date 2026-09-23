#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1-1: every electrical measurement must pass ONE central
canonical-state gate before any doping is written or any DevSim solve
runs. Real GUI (window withdrawn), real ViennaPS, real DevSim.

B0 (Batch 7C) the same Gaussian Implant and Implant Windows requests made
   through the GUI are process-like implant inputs; this project has no
   implantation/activation model, so they are recorded CHEMICAL only:
   run_doping() returns False, the attachments are CHEMICAL, and a MEASURE
   afterwards writes 0 doping and runs 0 solves.

B1 (supported, accumulated) virgin 4 x 1 um wafer (grid 0.2 um) ->
   Gaussian donor (P, peak 1e16 at x=0, straggle 0.5 um) ->
   Implant Windows (donor background 1e16, source/drain windows 1e16),
   both DECLARED electrically ACTIVE through the recipe helpers
   (chemical_state="ACTIVE": a user-declared analytic profile, not a
   simulated implant) ->
   MEASURE (the Implant Windows robust branch). Required: both
   applications are attachments of the canonical state; the solve
   really runs; the NetDoping DevSim actually solved with equals the
   canonical per-node value exactly AND equals the independent sum of
   the two attachments -- so the earlier Gaussian is not dropped; the
   terminal currents are finite and satisfy KCL.

A  (blocked)   the same wafer after a thermal anneal. The anneal
   fail-closes the canonical WaferStateV2 (cells UNRESOLVED, net_doping
   None). Required: 0 devsim.solve calls, 0 doping node model writes, no
   current reported, and the GUI log shows UNSUPPORTED_BY_MODEL with the
   blocking diagnostics -- first blocked node x/y, DevSim region, the
   material instance(s) found there, their lifecycle/material, the
   canonical query's physics status with its original (anneal) reason,
   and blocked/total node counts; the canonical state object unchanged.

B2 (supported) a fresh wafer with Uniform doping (the non-robust
   apply_doping + run_pn_junction_iv_sweep path): real solve, finite
   currents, NetDoping equal to the canonical values.

Nothing is mocked. The observers wrap the real devsim functions and
ALWAYS call the original, so a gate that failed to block runs the real
solver and shows up as a nonzero count.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

DOPING_MODELS = {"Donors", "Acceptors", "NetDoping"}
LENGTH_SCALE_TO_CM = 1.0e-4  # run_measurement's own um -> cm scale


class _Observer:
    """Pass-through call recorder on the real devsim module."""

    def __init__(self, devsim):
        self.devsim = devsim
        self.solve_calls = 0
        self.doping_writes = []
        self.final_nodes = None
        self._originals = {}

    def install(self):
        d = self.devsim
        for name in ("solve", "node_model", "set_node_values", "delete_device"):
            self._originals[name] = getattr(d, name)
        orig = self._originals

        def solve(*args, **kwargs):
            self.solve_calls += 1
            return orig["solve"](*args, **kwargs)

        def node_model(*args, **kwargs):
            if kwargs.get("name") in DOPING_MODELS:
                self.doping_writes.append(("node_model", kwargs.get("name")))
            return orig["node_model"](*args, **kwargs)

        def set_node_values(*args, **kwargs):
            if kwargs.get("name") in DOPING_MODELS:
                self.doping_writes.append(("set_node_values", kwargs.get("name")))
            return orig["set_node_values"](*args, **kwargs)

        def delete_device(*args, **kwargs):
            # Snapshot what DevSim ACTUALLY holds right before the GUI
            # deletes its measurement device.
            snap = {}
            for model in ("x", "y", "NetDoping"):
                try:
                    snap[model] = list(d.get_node_model_values(
                        device=kwargs.get("device"), region="Si", name=model))
                except Exception:
                    snap[model] = None
            self.final_nodes = snap
            return orig["delete_device"](*args, **kwargs)

        d.solve = solve
        d.node_model = node_model
        d.set_node_values = set_node_values
        d.delete_device = delete_device

    def restore(self):
        for name, fn in self._originals.items():
            setattr(self.devsim, name, fn)


def _configure(app):
    app.wafer.width_um = 4.0
    app.wafer.silicon_depth_um = 1.0
    app.grid_var.set(0.2)
    app.meas_voltage_var.set(0.01)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")


def _attachment_part(state, model, x_um, y_um):
    """Signed contribution of the canonical attachments of one model at
    a point -- summed independently of net_doping_at()."""
    total = 0.0
    for a in state.attachments:
        b = a.support_region_um
        if a.model != model or not (b[0] <= x_um <= b[1] and b[2] <= y_um <= b[3]):
            continue
        mag = max(0.0, float(a.concentration_at(x_um, y_um)))
        total += mag if a.polarity == "donor" else -mag
    return total


def _canonical_vs_solved(app, final_nodes, parts=()):
    """Compare DevSim's final NetDoping with the canonical state at the
    same nodes. None when DevSim never held a NetDoping model. `parts`
    names attachment models whose independent sum must reproduce it."""
    if not final_nodes or final_nodes.get("NetDoping") is None:
        return None
    state = app.wafer_state
    xs = [x / LENGTH_SCALE_TO_CM for x in final_nodes["x"]]
    ys = [y / LENGTH_SCALE_TO_CM for y in final_nodes["y"]]
    solved = final_nodes["NetDoping"]
    canonical = [state.net_doping_at(x, y).net_doping for x, y in zip(xs, ys)]
    if any(c is None for c in canonical):
        return {"nodes": len(solved), "canonical_has_none": True}
    diffs = [abs(a - b) for a, b in zip(solved, canonical)]
    out = {
        "nodes": len(solved),
        "mismatched_nodes": sum(1 for d in diffs if d != 0.0),
        "max_abs_diff_cm3": max(diffs) if diffs else 0.0,
    }
    if parts:
        by_model = {m: [_attachment_part(state, m, x, y) for x, y in zip(xs, ys)] for m in parts}
        summed = [sum(values) for values in zip(*by_model.values())]
        out["max_rel_diff_vs_independent_sum"] = max(
            abs(s - n) / max(abs(n), 1.0) for s, n in zip(summed, solved))
        for m, values in by_model.items():
            rest = [n - v for n, v in zip(solved, values)]
            out[f"max_{m}_part_cm3"] = max(abs(v) for v in values)
            # nodes where leaving this attachment out would change the
            # solved NetDoping by more than 1 %
            out[f"nodes_needing_{m}"] = sum(
                1 for n, r in zip(solved, rest) if abs(n - r) > 0.01 * abs(n))
    return out


def _measure(app, devsim, label, parts=()):
    observer = _Observer(devsim)
    log_before = app.log.get("1.0", "end-1c")
    history_before = len(app.history)
    state_before = app.wafer_state
    observer.install()
    try:
        app.run_measurement()
    finally:
        observer.restore()
    log_delta = app.log.get("1.0", "end-1c")[len(log_before):]
    status = app.last_physics_status
    return {
        "label": label,
        "solve_calls": observer.solve_calls,
        "doping_writes": len(observer.doping_writes),
        "doping_write_kinds": sorted(set(observer.doping_writes)),
        "currents_in_log": [float(m) for m in re.findall(r"I = ([-+0-9.eE]+) A", log_delta)],
        "measurement_section_logged": "DEVSIM MEASUREMENT" in log_delta,
        "unsupported_in_log": "UNSUPPORTED_BY_MODEL" in log_delta,
        "log_delta": log_delta,
        "last_physics_status": status if isinstance(status, dict) else None,
        "canonical_state_object_unchanged": app.wafer_state is state_before,
        "history_entries_added": len(app.history) - history_before,
        "canonical_vs_solved_netdoping": _canonical_vs_solved(app, observer.final_nodes, parts),
    }


def _set_implant_windows_1e16(app):
    app.doping_kind.set("Implant Windows")
    for name, value in {
        "dope_win_donor_bg_var": 1e16, "dope_win_acceptor_bg_var": 0,
        "dope_win_src_donor_var": 1e16, "dope_win_src_acceptor_var": 0,
        "dope_win_drn_donor_var": 1e16, "dope_win_drn_acceptor_var": 0,
    }.items():
        getattr(app, name).set(value)


def _set_gaussian_p_1e16(app):
    app.doping_kind.set("Gaussian Implant")
    app.dope_gauss_region_var.set("Si")
    app.dope_gauss_axis_var.set("x")
    app.dope_gauss_position_var.set(0.0)
    app.dope_gauss_straggle_var.set(0.5)
    app.dope_gauss_donor_var.set(1e16)
    app.dope_gauss_acceptor_var.set(0.0)
    app.dope_gauss_donor_species_var.set("P")


def _assert_supported(key, b):
    assert b["solve_calls"] >= 1, f"{key}: no real solve ran"
    assert b["doping_writes"] >= 1, f"{key}: doping was never written"
    currents = b["currents_in_log"][:2]
    assert len(currents) == 2 and all(math.isfinite(i) for i in currents), (
        f"{key}: expected two finite terminal currents, got {b['currents_in_log']}")
    assert abs(currents[0] + currents[1]) <= 1e-4 * abs(currents[0]), (
        f"{key}: terminal currents not equal and opposite (KCL): {currents}")
    cmp = b["canonical_vs_solved_netdoping"]
    assert cmp is not None and not cmp.get("canonical_has_none"), f"{key}: {cmp}"
    assert cmp["mismatched_nodes"] == 0, (
        f"{key}: solved NetDoping differs from the canonical state at "
        f"{cmp['mismatched_nodes']}/{cmp['nodes']} node(s), max |diff| {cmp['max_abs_diff_cm3']:.3e}")
    assert b["canonical_state_object_unchanged"]
    assert "UNSUPPORTED_BY_MODEL" not in b["log_delta"], f"{key}: {b['log_delta']}"


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

    if not viennaps_session.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS is not installed")
        return
    if not devsim_backend.is_available():
        app.destroy()
        print("SKIPPED: DevSim is not installed")
        return
    devsim = devsim_backend.require_devsim()

    originals = {n: getattr(gui.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, **k: None)

    metrics = {}
    try:
        app.withdraw()
        _configure(app)
        assert app._materialize_current_wafer(), "materializing the real ViennaPS wafer failed"
        # B0: through the GUI these two kinds are CHEMICAL records (Batch 7C).
        _set_gaussian_p_1e16(app)
        assert app.run_doping(silent=True) is False, "a GUI Gaussian Implant must not be reported as an applied active doping"
        _set_implant_windows_1e16(app)
        assert app.run_doping(silent=True) is False, "a GUI Implant Windows must not be reported as an applied active doping"
        metrics["B0_states"] = [(a.model, a.chemical_state) for a in app.wafer_state.attachments]
        assert app.last_doped_result is None
        metrics["B0"] = _measure(app, devsim, "B0 blocked: GUI Gaussian + Implant Windows are CHEMICAL")

        # B1: the same physics, DECLARED electrically active through the recipe helpers.
        app.reset()
        _configure(app)
        assert app._materialize_current_wafer(), "materializing the real ViennaPS wafer failed"
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.physics.doping import apply_gaussian_implant_doping, apply_implant_windows_doping
        from tcad.physics.wafer_state_accumulation import advance_wafer_state
        pr = build_process_result({"final_mesh": app.last_final_mesh, "snapshots": []})
        gauss = apply_gaussian_implant_doping(
            pr, region="Si", junction_axis="x", peak_position_um=0.0, straggle_um=0.5,
            donor_peak_conc_cm3=1e16, acceptor_peak_conc_cm3=0.0, donor_species="P",
            chemical_state="ACTIVE")
        windows_result = apply_implant_windows_doping(
            pr, region="Si", axis="x", donor_background_cm3=1e16, acceptor_background_cm3=0.0,
            windows=[
                {"min_um": float(app.dope_win_src_min_var.get()), "max_um": float(app.dope_win_src_max_var.get()),
                 "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0},
                {"min_um": float(app.dope_win_drn_min_var.get()), "max_um": float(app.dope_win_drn_max_var.get()),
                 "donor_conc_cm3": 1e16, "acceptor_conc_cm3": 0.0},
            ],
            chemical_state="ACTIVE")
        app.wafer_state = advance_wafer_state(
            advance_wafer_state(app.wafer_state, gauss, "doping"), windows_result, "doping")
        app.last_doped_result = windows_result
        metrics["B1_attachments"] = [
            (a.model, a.species, a.polarity, a.support_instance_id, a.support_region_um)
            for a in app.wafer_state.attachments]

        metrics["B1"] = _measure(app, devsim, "B1 supported: Gaussian then Implant Windows, robust path",
                                 parts=("gaussian_v1", "implant_windows_v1"))

        app._on_thermal_anneal_clicked()
        q = app.wafer_state.net_doping_at(0.0, -0.5)
        metrics["A_state_before_measure"] = {
            "net_doping": q.net_doping,
            "resolution": (q.physics_status or {}).get("resolution"),
            "active_attachments": len(app.wafer_state.attachments),
            "cells": [(c.material_instance_id, c.material, c.lifecycle, c.bounds_um)
                      for c in app.wafer_state.cells],
        }
        metrics["A"] = _measure(app, devsim, "A blocked: implant_windows robust path after anneal")
        metrics["A"]["canonical_net_after_measure"] = app.wafer_state.net_doping_at(0.0, -0.5).net_doping

        app.reset()
        _configure(app)
        assert app._materialize_current_wafer(), "materializing the second real wafer failed"
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True) is True
        metrics["B2"] = _measure(app, devsim, "B2 supported: uniform apply_doping path")
    finally:
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
        app.destroy()

    leaked = list(devsim.get_device_list())
    printable = {
        k: ({kk: vv for kk, vv in v.items() if kk != "log_delta"} if isinstance(v, dict) else v)
        for k, v in metrics.items()
    }
    printable["leaked_devices"] = leaked
    print("METRICS " + json.dumps(printable, default=str))
    print("A_LOG_DELTA " + json.dumps(metrics["A"]["log_delta"]))

    # ---- B0: the GUI kinds are CHEMICAL records, never measurable ----
    b0 = metrics["B0"]
    assert metrics["B0_states"] and all(state == "CHEMICAL" for _, state in metrics["B0_states"]), metrics["B0_states"]
    assert b0["solve_calls"] == 0 and b0["doping_writes"] == 0 and not b0["currents_in_log"], b0

    # ---- B1: supported, accumulated ----
    b1 = metrics["B1"]
    models = [m for m, *_ in metrics["B1_attachments"]]
    assert "gaussian_v1" in models and "implant_windows_v1" in models, (
        f"B1: both applications must be canonical attachments, got {metrics['B1_attachments']}")
    assert all(att[3] == "si#substrate" for att in metrics["B1_attachments"])
    _assert_supported("B1", b1)
    cmp = b1["canonical_vs_solved_netdoping"]
    assert cmp["max_rel_diff_vs_independent_sum"] <= 1e-12, (
        f"B1: solved NetDoping is not the Gaussian + Implant Windows sum: {cmp}")
    assert cmp["max_gaussian_v1_part_cm3"] >= 0.9e16 and cmp["nodes_needing_gaussian_v1"] > 0, (
        f"B1: the earlier Gaussian is missing from the solved NetDoping: {cmp}")

    # ---- A: blocked, with diagnostics ----
    a = metrics["A"]
    log = a["log_delta"]
    assert metrics["A_state_before_measure"]["net_doping"] is None
    assert metrics["A_state_before_measure"]["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert a["solve_calls"] == 0, f"A: devsim.solve called {a['solve_calls']} time(s)"
    assert a["doping_writes"] == 0, f"A: doping node-model writes {a['doping_write_kinds']}"
    assert not a["currents_in_log"], f"A: current reported {a['currents_in_log']}"
    assert not a["measurement_section_logged"], "A: a DEVSIM MEASUREMENT result section was logged"
    assert a["history_entries_added"] == 0, "A: a measurement was recorded in history"
    assert a["unsupported_in_log"], "A: UNSUPPORTED_BY_MODEL not shown in the GUI log"
    counts = re.search(r"(\d+) of (\d+) mesh node\(s\) blocked", log)
    assert counts and counts.group(1) == counts.group(2) and int(counts.group(1)) > 0, (
        f"A: blocked/total node counts missing: {log}")
    node = re.search(r"First blocked node: x=(\S+) um, y=(\S+) um in DevSim region 'Si'", log)
    assert node, f"A: first blocked node / DevSim region missing: {log}"
    x_um, y_um = float(node.group(1)), float(node.group(2))
    assert -2.0 <= x_um <= 2.0 and -1.0 <= y_um <= 0.0, (x_um, y_um)
    assert "Canonical material instance(s) containing it: si#substrate." in log, log
    assert "material Si, lifecycle UNRESOLVED" in log, f"A: lifecycle/material missing: {log}"
    assert ("physics_status UNSUPPORTED_BY_MODEL -- point lies in a region an "
            "UNSUPPORTED_BY_MODEL 'anneal' event covers") in log, f"A: original reason missing: {log}"
    status = a["last_physics_status"]
    assert status and status["resolution"] == "UNSUPPORTED_BY_MODEL", status
    assert status["first_blocked_node"]["material_instance_ids"] == ["si#substrate"], status
    assert status["blocked_nodes"] == status["total_nodes"] == int(counts.group(1)), status
    assert a["canonical_state_object_unchanged"], "A: measurement replaced the canonical state"
    assert a["canonical_net_after_measure"] is None, "A: canonical state gained a doping number"
    assert a["canonical_vs_solved_netdoping"] is None, "A: DevSim held a NetDoping model"

    # ---- B2: supported, uniform ----
    _assert_supported("B2", metrics["B2"])

    assert not leaked, f"leaked DevSim devices: {leaked}"
    print("PASS: accumulated Gaussian + Implant Windows doping solves on exactly the canonical "
          "sum; the unsupported (annealed) state blocks the robust measurement with 0 solves / "
          "0 doping writes / no current and full node diagnostics in the GUI log; uniform "
          "doping still solves on the canonical NetDoping.")


if __name__ == "__main__":
    main()
