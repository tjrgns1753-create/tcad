#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Positive-time LOCOS request -> DevSim: the request is UNSUPPORTED_BY_MODEL and no device may be authorized from it.
Real ViennaPS 4.6.2 + DevSim, real production entry points and the real GUI measurement path.

WHAT THIS TEST PINS NOW (Batch 7).
  1. A positive-time LOCOS request through the real entry point (registry -> LocosOxidation.run()) is refused before
     any solver call:  state_transition.kind == "unsupported", physics_status.resolution == "UNSUPPORTED_BY_MODEL",
     reason (both fields) "LOCOS_CAPABILITY_PROOF_MISSING". `vps.Process`, `vps.Oxidation` (construction and
     `setInitialOxideThickness`) and `LocosOxidation._build_locos_geometry` are trapped and counted (0 calls). The
     returned geometry is the fresh virgin-Si wafer only: no SiO2, no Mask, no mask-retention number.
  2. `build_process_result()` (a geometry adapter) is called on that result and keeps the unsupported
     `physics_status` and `state_transition` exactly as the step returned them -- nothing is lost on the way to the
     device layer, and it adds no doping.
  3. GEOMETRY-ONLY IMPORT IS NOT AN AUTHORIZATION. `import_process_result()` turns a mesh into a DevSim device; it
     does not read `physics_status` or `state_transition`, so it is NOT a physics gate and this test never calls it
     on the refused LOCOS result and never calls the outcome "a LOCOS device". Authorization to write doping and solve
     is decided by the canonical WaferState gate (`canonical_node_doping()` / `apply_doping()` raising
     `UnsupportedDopingState`, and the GUI's `run_measurement()`, which catches it). Real GUI, two variants: a wafer
     materialized BEFORE the request (the canonical cell becomes UNRESOLVED) and a wafer with no earlier state
     (LEGACY_UNRESOLVED cells). After the refused LOCOS request:
       (a) the user's doping request is refused at the source (Tier 1): `run_doping()` returns False, no active
           attachment, one refusal event + one unresolved-inventory entry in the canonical state, `last_doped_result`,
           history and viewer layer untouched, the log says DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL) with the input
           labelled REQUESTED, NOT APPLIED and never DOPING APPLIED;
       (b) a MEASURE right after stops with "no doping profile": 0 mesh/device imports, 0 `devsim.solve`, 0 doping
           writes, no current;
       (c) defence in depth (constructed on purpose: a real doping result bound to the current mesh, as if a doping
           application had survived): the canonical gate still blocks -- 0 `devsim.solve`, 0 doping node-model writes,
           no current, `UNSUPPORTED_BY_MODEL` with blocked-node diagnostics, canonical state unchanged and answering
           None, no leaked DevSim device.
     The pass-through observers on the real DevSim functions do the counting. The one geometry-only import that
     happens on the way to the gate in (c) is OBSERVED and described exactly: "One temporary device was imported
     from last-known Si geometry; no post-LOCOS device or electrical result was claimed." It is not a LOCOS result
     import and not a solve authorization; it is staging to obtain node coordinates for the canonical gate.
     Making it 0 would be a production change that is out of scope here.

WHAT IS NOT PINNED ANY MORE (historical). This file used to import a positive-time LOCOS result into DevSim as
a three-region Si/SiO2/Mask device with two contacts on Si, and to check a >=90% mask-retention area. That was
the result of a positive-time LOCOS the backend no longer computes; it is history (the pad-oxide-first geometry
fix, `save_locos_volume_mesh()` and the mask-retention numbers), not a current contract. A virgin-Si mesh
imported into DevSim would not be "a LOCOS device", and none is presented as one.

Solver-call absence inside the GUI's worker subprocess cannot be trapped from this process; it rests on the GUI
log/physics status (and on item 1, which traps the same production entry point in-process).

False-green guards at the end prove each check fails, for its own reason, when its subject is broken.
"""

import copy
import inspect
import re
import sys
import tempfile
import types
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401 -- registers the model
from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim import doping_mapping, mesh_import
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping
from tcad.process import registry
from tcad.process.oxidation.locos import LocosOxidation

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"
MODULE = viennaps_session.require_viennaps()

# The historical LOCOS/DevSim recipe, used ONLY as the REQUEST that must be refused (0.02 h is > 0).
RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.02,
    "mask_material": "Mask",
}
EXPECTED_REASON = "LOCOS_CAPABILITY_PROOF_MISSING"
RESULT_KEYS = {"final_mesh", "snapshots", "physics_status", "state_transition"}
STATUS_KEYS = {"resolution", "entries", "reason_code", "requested_initial_oxide_um", "grid_delta_um", "measured_min_oxide_um"}
DOPING_MODELS = {"Donors", "Acceptors", "NetDoping"}
MESSAGEBOX = ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel")


# ------------------------------------------------------------------------------------------ solver-call traps
class SolverTrap:
    """Recorders that also raise (a regression fails loudly); the counts catch a call a broad `except` swallowed."""

    FORBIDDEN = ("vps.Process", "vps.Oxidation", "setInitialOxideThickness", "LocosOxidation._build_locos_geometry")

    def __init__(self):
        self.calls = []
        self._stack = None

    def __enter__(self):
        trap = self

        def process(*a, **k):
            trap.calls.append("vps.Process")
            raise AssertionError("vps.Process() called on a positive-time request")

        class OxidationModel:
            def __init__(self, *a, **k):
                trap.calls.append("vps.Oxidation")
                raise AssertionError("vps.Oxidation() constructed on a positive-time request")

            def setInitialOxideThickness(self, *a, **k):
                trap.calls.append("setInitialOxideThickness")
                raise AssertionError("setInitialOxideThickness() called on a positive-time request")

        def build(*a, **k):
            trap.calls.append("LocosOxidation._build_locos_geometry")
            raise AssertionError("LocosOxidation._build_locos_geometry() called on a positive-time request")

        self._stack = ExitStack()
        self._stack.enter_context(patch.object(MODULE, "Process", process))
        self._stack.enter_context(patch.object(MODULE, "Oxidation", OxidationModel))
        self._stack.enter_context(patch.object(LocosOxidation, "_build_locos_geometry", build))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    def assert_not_entered(self, where):
        if self.calls:
            raise AssertionError(f"{where}: solver/oxidation path was entered: {self.calls}")


def calibrate_trap():
    """Each trapped path, called directly, must be recorded and raise: a trap that never fires proves nothing."""
    with SolverTrap() as trap:
        for label, call in (
            ("vps.Process", lambda: MODULE.Process()),
            ("vps.Oxidation", lambda: MODULE.Oxidation()),
            ("setInitialOxideThickness", lambda: MODULE.Oxidation.setInitialOxideThickness(None, 0.1)),
            ("LocosOxidation._build_locos_geometry", lambda: LocosOxidation()._build_locos_geometry({}, MODULE)),
        ):
            try:
                call()
            except AssertionError:
                continue
            raise AssertionError(f"the trap for {label} did not fire")
        assert trap.calls == list(SolverTrap.FORBIDDEN), trap.calls


# ------------------------------------------------------------------------------------------ DevSim observers
class DevsimObserver:
    """Pass-through recorder on a devsim-like module (the real call still happens) plus the mesh->device import."""

    def __init__(self, devsim, importer_owner=None):
        self.devsim, self.importer_owner = devsim, importer_owner
        self.solve_calls, self.doping_writes, self.import_calls = 0, [], 0
        self.imported_meshes = []
        self._originals = {}

    def install(self):
        d = self.devsim
        for name in ("solve", "node_model", "set_node_values"):
            self._originals[name] = getattr(d, name)
        orig = self._originals

        def solve(*a, **k):
            self.solve_calls += 1
            return orig["solve"](*a, **k)

        def node_model(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.doping_writes.append(("node_model", k.get("name")))
            return orig["node_model"](*a, **k)

        def set_node_values(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.doping_writes.append(("set_node_values", k.get("name")))
            return orig["set_node_values"](*a, **k)

        d.solve, d.node_model, d.set_node_values = solve, node_model, set_node_values
        if self.importer_owner is not None:
            self._orig_import = self.importer_owner.import_process_result

            def counted(*a, **k):
                self.import_calls += 1
                self.imported_meshes.append(getattr(a[0], "volume_mesh_path", None) if a else None)
                return self._orig_import(*a, **k)

            self.importer_owner.import_process_result = counted

    def restore(self):
        for name, fn in self._originals.items():
            setattr(self.devsim, name, fn)
        if self.importer_owner is not None:
            self.importer_owner.import_process_result = self._orig_import


def calibrate_observer():
    """The observer must count solve, doping writes (by model name) and ignore non-doping node models -- on a fake module."""
    fake = types.SimpleNamespace(solve=lambda *a, **k: None, node_model=lambda *a, **k: None, set_node_values=lambda *a, **k: None)
    obs = DevsimObserver(fake)
    obs.install()
    fake.solve(type="dc")
    fake.node_model(name="NetDoping")
    fake.set_node_values(name="Donors")
    fake.node_model(name="Potential")
    obs.restore()
    assert obs.solve_calls == 1 and obs.doping_writes == [("node_model", "NetDoping"), ("set_node_values", "Donors")], (obs.solve_calls, obs.doping_writes)


# ------------------------------------------------------------------------------------------ contract checks
def mesh_materials(path):
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type == "triangle":
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(MODULE.Material(t)).split("'")[1] for t in tags)


def check_unsupported(result, where):
    assert set(result) == RESULT_KEYS, f"{where}: unexpected result keys {sorted(result)}"
    status, transition = result["physics_status"], result["state_transition"]
    if transition.get("kind") != "unsupported":
        raise AssertionError(f"{where}: state_transition.kind is {transition.get('kind')!r}, expected 'unsupported': {transition}")
    if status.get("resolution") != "UNSUPPORTED_BY_MODEL":
        raise AssertionError(f"{where}: physics_status.resolution is {status.get('resolution')!r}, expected 'UNSUPPORTED_BY_MODEL'")
    if status.get("reason_code") != EXPECTED_REASON or transition.get("reason") != EXPECTED_REASON:
        raise AssertionError(f"{where}: reason code is {status.get('reason_code')!r} / {transition.get('reason')!r}, expected {EXPECTED_REASON!r}")
    assert transition == {"kind": "unsupported", "category": "oxidation", "reason": EXPECTED_REASON}, f"{where}: {transition}"
    assert status["measured_min_oxide_um"] is None, f"{where}: an oxide thickness was reported: {status['measured_min_oxide_um']}"
    assert set(status) == STATUS_KEYS, sorted(status)


def check_fresh_materials(materials, where):
    if materials != ["Si"]:
        raise AssertionError(f"{where}: the returned geometry is not the virgin Si wafer only: materials {materials}")


def check_process_result_preserves(step_result, process_result, where="build_process_result"):
    if process_result.physics_status != step_result["physics_status"]:
        raise AssertionError(f"{where}: the unsupported physics_status was not preserved: {process_result.physics_status}")
    if process_result.metadata["state_transition"] != step_result["state_transition"]:
        raise AssertionError(f"{where}: the unsupported state_transition was not preserved: {process_result.metadata['state_transition']}")
    assert [r.name for r in process_result.material_regions] == ["Si"], [r.name for r in process_result.material_regions]
    assert process_result.doping is None, f"{where}: doping appeared on an unsupported result"


def check_gui_blocked(m, where):
    """The real GUI measurement after a refused LOCOS request: nothing written to DevSim, nothing solved, no current, and a
    logged UNSUPPORTED_BY_MODEL with the blocked-node diagnostics; the canonical state was not changed or given a number."""
    if m["solve_calls"] != 0:
        raise AssertionError(f"{where}: devsim.solve was called {m['solve_calls']} time(s) on an unsupported state")
    if m["doping_writes"]:
        raise AssertionError(f"{where}: {len(m['doping_writes'])} DevSim doping write(s) on an unsupported state: {sorted(set(m['doping_writes']))}")
    log = m["log"]
    assert not re.search(r"I = [-+0-9.eE]+ A", log), f"{where}: a terminal current was reported:\n{log}"
    if "UNSUPPORTED_BY_MODEL" not in log:
        raise AssertionError(f"{where}: UNSUPPORTED_BY_MODEL not shown in the measurement log:\n{log}")
    assert "Measurement blocked: no doping was written to DevSim, no solve was run, and no current is reported." in log, log
    counts = re.search(r"(\d+) of (\d+) mesh node\(s\) blocked", log)
    assert counts and counts.group(1) == counts.group(2) and int(counts.group(1)) > 0, f"{where}: blocked/total node counts: {log}"
    for wrong in ("imported successfully", "LOCOS device", "device imported"):
        assert wrong.lower() not in log.lower(), f"{where}: the log presents the unsupported result as a device: {wrong!r}"
    status = m["physics_status"]
    assert status and status["resolution"] == "UNSUPPORTED_BY_MODEL" and status["blocked_nodes"] == status["total_nodes"] == int(counts.group(1)), status
    assert m["history_added"] == 0, f"{where}: a measurement was recorded in the history"
    assert m["state_unchanged"], f"{where}: the measurement replaced the canonical state"
    assert m["net_doping_after"] is None and m["attachments_after"] == 0, f"{where}: the canonical state gained a doping number: {m['net_doping_after']}"
    assert m["modal_calls"] == 0, f"{where}: {m['modal_calls']} modal dialog call(s)"
    assert not m["leaked_devices"], f"{where}: leaked DevSim devices {m['leaked_devices']}"


IMPORT_MEANING = ("One temporary device was imported from last-known Si geometry; no post-LOCOS device or electrical result was claimed.")
SUCCESS_WORDS = ("DOPING APPLIED", "profile attached", "Doping profile attached", "net_doping_cm3=")


def check_doping_refused(d, where):
    """Tier 1: the doping request after a refused LOCOS is refused at the source, and the canonical state says so."""
    assert d["ret"] is False, f"{where}: run_doping() returned {d['ret']!r} for a refused doping request, expected False"
    assert d["attachments_added"] == 0, f"{where}: {d['attachments_added']} active attachment(s) were created on an unresolved state"
    assert d["refusal_events"] >= 1 and d["ledger_added"] >= 1, f"{where}: no refusal provenance/ledger was recorded: {d}"
    assert d["last_doped_result_replaced"] is False, f"{where}: the refused request replaced last_doped_result"
    assert d["history_added"] == 0, f"{where}: a refused doping request was added to the history"
    assert d["layer_after"] == d["layer_before"], f"{where}: the viewer layer was switched by a refused doping request"
    found = [w for w in SUCCESS_WORDS if w in d["log"]]
    assert not found, f"{where}: the refusal log carries success wording {found}"
    for text in ("DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL)", "REQUESTED, NOT APPLIED", "No DevSim write or solve is run"):
        assert text in d["log"], f"{where}: {text!r} missing from the refusal log:\n{d['log']}"
    assert d["modal_calls"] == 0, f"{where}: {d['modal_calls']} modal dialog call(s)"


def check_gui_stopped(m, where):
    """MEASURE right after the refused doping request: there is no doping profile, so it stops before any import, DevSim write or solve."""
    assert m["import_calls"] == 0, f"{where}: {m['import_calls']} mesh/device import(s) although no doping application exists"
    assert m["solve_calls"] == 0, f"{where}: devsim.solve was called {m['solve_calls']} time(s)"
    assert not m["doping_writes"], f"{where}: {len(m['doping_writes'])} DevSim doping write(s)"
    assert not re.search(r"I = [-+0-9.eE]+ A", m["log"]), f"{where}: a terminal current was reported:\n{m['log']}"
    assert "carries no doping profile" in m["log"], f"{where}: the stop reason is missing from the log:\n{m['log']}"
    assert m["state_unchanged"] and m["history_added"] == 0 and m["modal_calls"] == 0 and not m["leaked_devices"], m


def check_import_meaning(m, statement, where):
    """What the one geometry-only import on the way to the canonical gate is, and is not."""
    assert m["import_calls"] == 1, f"{where}: expected exactly one temporary geometry import on the way to the gate, observed {m['import_calls']}"
    assert m["imported_materials"] == [["Si"]], f"{where}: the imported geometry is {m['imported_materials']}, expected last-known virgin Si only"
    assert not m["leaked_devices"], f"{where}: leaked DevSim devices {m['leaked_devices']}"
    assert statement == IMPORT_MEANING, (f"{where}: the geometry-only import is described as {statement!r}, expected {IMPORT_MEANING!r} "
                                         f"(it is neither a LOCOS result import nor a solve authorization)")


# ------------------------------------------------------------------------------------------ the real GUI path
def configure(app):
    app.wafer.width_um = 4.0
    app.wafer.silicon_depth_um = 1.0
    app.grid_var.set(0.2)
    app.meas_voltage_var.set(0.01)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")


def gui_scenario(app, devsim, modal, materialize_first):
    configure(app)
    if materialize_first:
        assert app._materialize_current_wafer(), "materializing the wafer failed"
    app.panel_category.set(app._PANEL_LABELS["oxidation"])
    app._show_panel_category()
    app.oxidation_method.set("LOCOS (Advanced)")
    app.oxidant_var.set("Dry")
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(0.1)

    log0 = app.log.get("1.0", "end-1c")
    app.run_oxidation()
    ox_log = app.log.get("1.0", "end-1c")[len(log0):]
    ox = {
        "log": ox_log, "status": app.last_physics_status, "completed_steps": len(app.completed_steps),
        "q": app.wafer_state.net_doping_at(0.0, -0.5), "cells": sorted({c.lifecycle for c in app.wafer_state.cells}),
    }

    app.doping_kind.set("Uniform")
    app.dope_uniform_region_var.set("Si")
    app.dope_uniform_donor_var.set(1e16)
    app.dope_uniform_acceptor_var.set(0.0)

    # (a) the user's next action: apply a doping. It must be refused at the source (Tier 1), not reported as applied.
    st = app.wafer_state
    att0, ev0, un0 = {a.attachment_id for a in st.attachments}, len(st.events), len(st.unresolved_inventory)
    res0, hist0, layer0 = app.last_doped_result, len(app.history), app.viewer_layer_var.get()
    log_d, modal_d = app.log.get("1.0", "end-1c"), len(modal)
    ret = app.run_doping(silent=True)
    st = app.wafer_state
    d = {
        "ret": ret, "attachments_added": sum(a.attachment_id not in att0 for a in st.attachments),
        "refusal_events": sum(e.model_status == "UNSUPPORTED_BY_MODEL" for e in st.events[ev0:]), "ledger_added": len(st.unresolved_inventory) - un0,
        "last_doped_result_replaced": app.last_doped_result is not res0, "history_added": len(app.history) - hist0,
        "layer_before": layer0, "layer_after": app.viewer_layer_var.get(), "log": app.log.get("1.0", "end-1c")[len(log_d):],
        "modal_calls": len(modal) - modal_d,
    }

    # (b) MEASURE now: with no doping application there is nothing to measure -> stops before any import, DevSim write or solve.
    stopped = measure(app, devsim, modal)

    # (c) Defence in depth, constructed on purpose: bind a real doping result (real recipe helpers, on the current virgin-Si mesh) to
    #     the current mesh, as if a doping application had survived. The canonical gate must still refuse the device.
    app.last_doped_result = apply_uniform_doping(build_process_result({"final_mesh": app.last_final_mesh, "snapshots": []}), {"Si": 1e16}, chemical_state="ACTIVE")
    gated = measure(app, devsim, modal)
    return ox, d, stopped, gated


def measure(app, devsim, modal):
    obs = DevsimObserver(devsim, importer_owner=mesh_import)
    state_before, history_before = app.wafer_state, len(app.history)
    log1, modal_before = app.log.get("1.0", "end-1c"), len(modal)
    obs.install()
    try:
        app.run_measurement()
    finally:
        obs.restore()
    return {
        "log": app.log.get("1.0", "end-1c")[len(log1):], "solve_calls": obs.solve_calls, "doping_writes": obs.doping_writes,
        "import_calls": obs.import_calls, "imported_materials": [mesh_materials(p) for p in obs.imported_meshes],
        "physics_status": app.last_physics_status if isinstance(app.last_physics_status, dict) else None,
        "history_added": len(app.history) - history_before, "state_unchanged": app.wafer_state is state_before,
        "net_doping_after": app.wafer_state.net_doping_at(0.0, -0.5).net_doping, "attachments_after": len(app.wafer_state.attachments),
        "modal_calls": len(modal) - modal_before, "leaked_devices": list(devsim.get_device_list()),
    }


def check_gui_oxidation_refused(ox, where):
    assert ox["status"] and ox["status"]["resolution"] == "UNSUPPORTED_BY_MODEL" and ox["status"]["reason_code"] == EXPECTED_REASON, ox["status"]
    for text in ("OXIDATION RESULT NOT COMPUTED (UNSUPPORTED_BY_MODEL)", f"Reason: {EXPECTED_REASON}", "1) No solver ran.", "3) Post-oxidation physical state is unresolved."):
        assert text in ox["log"], f"{where}: {text!r} missing from the log:\n{ox['log']}"
    assert "simulation complete" not in ox["log"].lower() and "ERROR —" not in ox["log"], ox["log"]
    assert ox["completed_steps"] == 0, f"{where}: the refused request was recorded as a completed step"
    if ox["q"].net_doping is not None or (ox["q"].physics_status or {}).get("resolution") != "UNSUPPORTED_BY_MODEL":
        raise AssertionError(f"{where}: the canonical state still answers after a refused LOCOS: {ox['q'].net_doping}, {ox['q'].physics_status}")


# ------------------------------------------------------------------------------------------ false-green machinery
def expect_fail(check, label, expected):
    """A guard passes only if `check` raises AssertionError whose message contains `expected` (str, tuple of str that must
    all appear, or predicate). A passing check is FALSE GREEN; another reason is WRONG FAILURE REASON."""
    try:
        check()
    except AssertionError as exc:
        message = str(exc)
        parts = (expected,) if isinstance(expected, str) else expected
        ok = expected(message) if callable(expected) else all(p in message for p in parts)
        if not ok:
            raise AssertionError(f"WRONG FAILURE REASON for {label!r}:\n  expected: {expected!r}\n  actual:   {message[:300]}") from exc
        print(f"    [guard OK] {label}: fails for the expected reason ({message.splitlines()[0][:90]})")
        return
    raise AssertionError(f"FALSE GREEN: the check did not fail when {label}")


def run_guards(sample, materials, doping_metrics, stopped_metrics, gui_metrics):
    print("\n[guards] every contract check fails, for its own reason, when its subject is broken")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["reason_code"] = bad["state_transition"]["reason"] = "OXIDATION_CAPABILITY_PROOF_MISSING"      # LOCOS <-> thermal swapped
    expect_fail(lambda: check_unsupported(bad, "swapped"), "the LOCOS request carries the thermal reason code",
                "reason code is 'OXIDATION_CAPABILITY_PROOF_MISSING'")
    bad = copy.deepcopy(sample)
    bad["state_transition"] = {"kind": "identity", "category": "oxidation", "reason": "zero_duration_oxidation", "inherited": True}
    expect_fail(lambda: check_unsupported(bad, "identity"), "the transition kind is identity", "state_transition.kind is 'identity'")
    bad = copy.deepcopy(sample)
    bad["physics_status"]["resolution"] = "MODELLED"
    expect_fail(lambda: check_unsupported(bad, "MODELLED"), "the physics resolution is MODELLED", "physics_status.resolution is 'MODELLED'")
    expect_fail(lambda: check_fresh_materials(materials + ["SiO2"], "fresh+SiO2"), "the fresh result contains SiO2",
                "not the virgin Si wafer only: materials ['Si', 'SiO2']")
    expect_fail(lambda: check_fresh_materials(sorted(materials + ["Mask"]), "fresh+Mask"), "the fresh result contains a Mask",
                "not the virgin Si wafer only: materials ['Mask', 'Si']")
    with SolverTrap() as trap:
        try:
            MODULE.Process()
        except AssertionError:
            pass
        expect_fail(lambda: trap.assert_not_entered("probe"), "the solver trap was actually called",
                    "probe: solver/oxidation path was entered: ['vps.Process']")
    expect_fail(lambda: check_gui_blocked({**gui_metrics, "doping_writes": [("node_model", "NetDoping")]}, "mutant"),
                "a DevSim doping write happens on the unsupported state", "mutant: 1 DevSim doping write(s) on an unsupported state")
    expect_fail(lambda: check_gui_blocked({**gui_metrics, "solve_calls": 1}, "mutant"),
                "a devsim.solve happens on the unsupported state", "mutant: devsim.solve was called 1 time(s)")
    expect_fail(lambda: check_gui_blocked({**gui_metrics, "log": gui_metrics["log"].replace("UNSUPPORTED_BY_MODEL", "ok")}, "mutant"),
                "the measurement log does not say UNSUPPORTED_BY_MODEL", "mutant: UNSUPPORTED_BY_MODEL not shown")
    expect_fail(lambda: check_gui_blocked({**gui_metrics, "log": gui_metrics["log"] + "\nLOCOS device imported successfully\n"}, "mutant"),
                "the log presents the refused LOCOS as an imported device", "the log presents the unsupported result as a device")
    # Tier 1 -- refused doping must never read as applied
    expect_fail(lambda: check_doping_refused({**doping_metrics, "ret": True}, "mutant"),
                "the refused doping request returns True", "mutant: run_doping() returned True")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "attachments_added": 1}, "mutant"),
                "an active attachment appears on an unresolved state", "mutant: 1 active attachment(s) were created")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "last_doped_result_replaced": True}, "mutant"),
                "the refused request replaces last_doped_result", "mutant: the refused request replaced last_doped_result")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "history_added": 1}, "mutant"),
                "the refused request is added to the history", "mutant: a refused doping request was added to the history")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "layer_after": "doping"}, "mutant"),
                "the refused request switches the overlay", "mutant: the viewer layer was switched")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "log": doping_metrics["log"] + "DOPING APPLIED: UNIFORM"}, "mutant"),
                "the refusal log prints DOPING APPLIED", "the refusal log carries success wording ['DOPING APPLIED']")
    expect_fail(lambda: check_doping_refused({**doping_metrics, "log": doping_metrics["log"].replace("REQUESTED, NOT APPLIED", "value")}, "mutant"),
                "the requested value is not labelled REQUESTED, NOT APPLIED", "'REQUESTED, NOT APPLIED' missing")
    expect_fail(lambda: check_gui_stopped({**stopped_metrics, "solve_calls": 1}, "mutant"),
                "a solve follows the refused doping request", "mutant: devsim.solve was called 1 time(s)")
    expect_fail(lambda: check_gui_stopped({**stopped_metrics, "doping_writes": [("node_model", "NetDoping")]}, "mutant"),
                "a DevSim doping write follows the refused doping request", "mutant: 1 DevSim doping write(s)")
    expect_fail(lambda: check_gui_stopped({**stopped_metrics, "import_calls": 1}, "mutant"),
                "a device import follows the refused doping request", "mutant: 1 mesh/device import(s) although no doping application exists")
    # the geometry-only import must not be described as a LOCOS result or an authorization
    expect_fail(lambda: check_import_meaning(gui_metrics, "The refused LOCOS result was imported into DevSim as a LOCOS device.", "mutant"),
                "the temporary geometry import is labelled a LOCOS result import", "the geometry-only import is described as")
    expect_fail(lambda: check_import_meaning({**gui_metrics, "import_calls": 0}, IMPORT_MEANING, "mutant"),
                "the import is claimed but was not observed", "expected exactly one temporary geometry import")
    expect_fail(lambda: check_import_meaning({**gui_metrics, "imported_materials": [["Si", "SiO2", "Mask"]]}, IMPORT_MEANING, "mutant"),
                "the imported geometry is presented as a LOCOS geometry", "expected last-known virgin Si only")


def main():
    devsim = devsim_backend.require_devsim()
    calibrate_trap()
    calibrate_observer()
    print("[0] solver traps and the DevSim observers calibrated (each fires/counts when touched directly)")

    # ---- 1 + 2: the real entry point, then the adapter ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        with SolverTrap() as trap:
            step_result = registry.get("oxidation", "locos")().run(dict(RECIPE), tmp)
        trap.assert_not_entered("positive-time LOCOS request")
        check_unsupported(step_result, "positive-time LOCOS request")
        materials = mesh_materials(step_result["final_mesh"])
        check_fresh_materials(materials, "positive-time LOCOS request")
        print(f"[1/4] positive-time LOCOS request ({RECIPE['time_hours']} h): {step_result['state_transition']}; resolution "
              f"{step_result['physics_status']['resolution']}/{step_result['physics_status']['reason_code']}; solver-path counts "
              f"{dict.fromkeys(SolverTrap.FORBIDDEN, 0)}; returned materials {materials} (fresh virgin Si, NOT a LOCOS result: no SiO2, no Mask, "
              f"no mask-retention number)")
        process_result = build_process_result(step_result)
        check_process_result_preserves(step_result, process_result)
        print(f"[2/4] build_process_result() preserved the unsupported verdict unchanged: physics_status {process_result.physics_status['resolution']}/"
              f"{process_result.physics_status['reason_code']}, state_transition {process_result.metadata['state_transition']}, regions "
              f"{[r.name for r in process_result.material_regions]}, doping {process_result.doping}")

    # ---- 3: what import_process_result is (observation, not an assertion) ---------------------------------------------------
    tokens = ("physics_status", "state_transition", "UNSUPPORTED", "unsupported")
    import_src = inspect.getsource(mesh_import.import_process_result)
    gate_src = inspect.getsource(doping_mapping.canonical_node_doping) + inspect.getsource(doping_mapping.apply_doping)
    print(f"[3/4] observation: import_process_result() source mentions {[t for t in tokens if t in import_src] or 'none of'} {tokens} -> a geometry-only "
          f"adapter, NOT a physics gate (it is not called here on the refused result); the gate is canonical_node_doping()/apply_doping() "
          f"(raises UnsupportedDopingState: {'UnsupportedDopingState' in gate_src}) and the GUI measurement path that catches it")

    # ---- 4: the real GUI measurement path ----------------------------------------------------------------------------------
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui

    modal = []
    originals = {n: getattr(gui.messagebox, n) for n in MESSAGEBOX if hasattr(gui.messagebox, n)}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, _n=n, **k: modal.append(_n))
    app = gui.TCADApplication()
    metrics = {}
    try:
        app.withdraw()
        for variant, materialize_first in (("materialized wafer before the request", True), ("no earlier canonical state", False)):
            app.reset()
            ox, d, stopped, m = gui_scenario(app, devsim, modal, materialize_first)
            check_gui_oxidation_refused(ox, variant)
            check_doping_refused(d, variant)
            check_gui_stopped(stopped, variant)
            check_gui_blocked(m, variant)
            check_import_meaning(m, IMPORT_MEANING, variant)
            if materialize_first:
                assert "lifecycle UNRESOLVED" in m["log"] and "si#substrate" in m["log"], m["log"]
            else:
                assert "LEGACY_UNRESOLVED" in m["log"], m["log"]
            metrics[variant] = (d, stopped, m)
            print(f"[4/4] GUI, {variant}: LOCOS request -> {ox['status']['resolution']}/{ox['status']['reason_code']} (canonical cells {ox['cells']}, "
                  f"query {ox['q'].net_doping})")
            print(f"      (a) doping request -> run_doping() returned {d['ret']}, active attachments added {d['attachments_added']}, refusal events "
                  f"{d['refusal_events']}, unresolved-ledger entries {d['ledger_added']}, last_doped_result replaced {d['last_doped_result_replaced']}, "
                  f"history added {d['history_added']}, viewer layer {d['layer_before']!r}->{d['layer_after']!r}, modal calls {d['modal_calls']}; "
                  f"log says DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL) with the input labelled REQUESTED, NOT APPLIED")
            print(f"      (b) MEASURE right after -> stops with 'no doping profile': mesh/device imports {stopped['import_calls']}, devsim.solve "
                  f"{stopped['solve_calls']}, DevSim doping writes {len(stopped['doping_writes'])}, currents 0, leaked devices {stopped['leaked_devices']}")
            print(f"      (c) canonical gate, defence in depth (a real doping result bound to the current mesh): devsim.solve {m['solve_calls']}, DevSim "
                  f"doping writes {len(m['doping_writes'])}, currents 0, UNSUPPORTED_BY_MODEL with blocked-node diagnostics in the log, canonical state "
                  f"unchanged (query {m['net_doping_after']}, attachments {m['attachments_after']}), modal calls {m['modal_calls']}, leaked devices "
                  f"{m['leaked_devices']}")
            print(f"          temporary import observed on the way to the gate: {m['import_calls']} from {m['imported_materials']} -- {IMPORT_MEANING}")
    finally:
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
        app.destroy()
    assert not list(devsim.get_device_list()), f"leaked DevSim devices: {list(devsim.get_device_list())}"

    run_guards(step_result, materials, *next(iter(metrics.values())))

    print()
    print("LOCOS -> DEVSIM: a positive-time LOCOS request is UNSUPPORTED_BY_MODEL / LOCOS_CAPABILITY_PROOF_MISSING with 0 solver and LOCOS-builder "
          "calls and only the fresh virgin Si returned; build_process_result() preserves that verdict; the canonical measurement gate then blocks the "
          "device: 0 devsim.solve, 0 DevSim doping writes, no current, UNSUPPORTED_BY_MODEL logged. The refused doping request is reported as NOT "
          "APPLIED. One temporary device was imported from last-known Si geometry; no post-LOCOS device or electrical result was claimed.")


if __name__ == "__main__":
    main()
