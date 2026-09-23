#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-step process-flow -> WaferStateV2 sequencing, real-execution part.

Real ViennaPS 4.6.2, real subprocess worker, real Tk GUI (window
withdrawn), real DevSim. MANDATORY: Tk/ViennaPS/DevSim unavailability is
a hard failure (nonzero exit), never a silent skip -- same discipline as
tests/integration/test_oxidation_positive_time_unsupported_real.py.

Verified working Windows environment for this machine:
    PATH must include <venv>\\Library\\bin
    DEVSIM_MATH_LIBS=mkl_rt.3.dll
    OMP_NUM_THREADS=1
    MKL_NUM_THREADS=1

Covers required tests 2, 3, 4, 5, 7, 8, 9 from the WaferStateV2
sequencing task. Tests 1, 6, 10 (pure-Python, no ViennaPS) are in
tests/unit/test_waferstate_sequential_advance_mock.py.
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_ENV_HINT = (
    "Verified working Windows environment: add <venv>\\Library\\bin to "
    "PATH, set DEVSIM_MATH_LIBS=mkl_rt.3.dll, OMP_NUM_THREADS=1, "
    "MKL_NUM_THREADS=1."
)


def _open_gui_mandatory(test_name):
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui_mod
        app = gui_mod.TCADApplication()
    except Exception as exc:
        raise RuntimeError(
            f"MANDATORY {test_name} requires a real Tk display -- cannot "
            f"skip: {exc!r}\n{_ENV_HINT}"
        ) from exc
    return gui_mod, app


def _require_viennaps_and_devsim(gui_mod, app, test_name):
    from tcad.backends.viennaps import session as viennaps_session
    from tcad.device.devsim import backend as devsim_backend

    if not viennaps_session.is_available() or not devsim_backend.is_available():
        app.destroy()
        raise RuntimeError(
            f"MANDATORY {test_name} requires real ViennaPS AND real "
            f"DevSim -- cannot skip.\n{_ENV_HINT}"
        )
    return devsim_backend.require_devsim()


def _etch_recipe(**overrides):
    base = dict(
        _process_category="etching", _process_model_key="isotropic",
        rate=-0.02, etch_time_s=1.0, silicon_depth_um=0.5,
        grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
        mask_spans_um=[],
    )
    base.update(overrides)
    return base


def _deposition_recipe(**overrides):
    base = dict(
        _process_category="deposition", _process_model_key="isotropic",
        rate=0.02, deposition_time_s=1.0, silicon_depth_um=0.5,
        grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
        mask_spans_um=[],
    )
    base.update(overrides)
    return base


def _oxidation_recipe(time_hours, **overrides):
    base = dict(
        _process_category="oxidation", _process_model_key="thermal",
        time_hours=time_hours, grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
        temperature_c=1000.0, oxidant="Dry", silicon_depth_um=0.5,
        mask_spans_um=[],
    )
    base.update(overrides)
    return base


class _Observer:
    """Real-DevSim call-counting spy (same technique as
    test_oxidation_positive_time_unsupported_real.py's own _Observer --
    duplicated here rather than imported, to keep this file
    self-contained)."""

    def __init__(self, devsim):
        self.devsim = devsim
        self.solve_calls = 0
        self.doping_writes = []
        self._originals = {}

    def install(self):
        d = self.devsim
        for name in ("solve", "node_model", "set_node_values"):
            self._originals[name] = getattr(d, name)
        orig = self._originals
        DOPING_MODELS = {"Donors", "Acceptors", "NetDoping"}

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

        d.solve = solve
        d.node_model = node_model
        d.set_node_values = set_node_values

    def restore(self):
        for name, fn in self._originals.items():
            setattr(self.devsim, name, fn)


def _run_worker_flow(steps, resume_state=None):
    """Dispatch worker_main's real `_flow_steps` branch in a real
    subprocess (real ViennaPS), returning the JSON payload. Uses
    mkdtemp (not a context manager) deliberately -- the returned mesh
    paths must still exist after this call returns, for a later
    _step_results_to_entries() call to read them."""
    root = Path(tempfile.mkdtemp(prefix="tcad2d_seq_test_"))
    config = {"output_dir": str(root / "flow"), "_flow_steps": steps}
    if resume_state:
        config["_resume_state"] = resume_state
    cfg_path, out_path = root / "config.json", root / "result.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    code = "from tcad_2d_stagewise import worker_main; import sys; worker_main(sys.argv[1], sys.argv[2])"
    child = subprocess.run(
        [sys.executable, "-c", code, str(cfg_path), str(out_path)],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    assert child.returncode == 0, child.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 2. explicit unsupported terminal
# ---------------------------------------------------------------------------
def test_2_explicit_unsupported_terminal():
    """supported etch -> positive oxidation (UNSUPPORTED_BY_MODEL,
    terminal) -> sentinel (invalid model name): etch gets exactly 1
    WaferState transition, oxidation gets exactly 1, sentinel gets 0 --
    and the sentinel's registry lookup/solver never happens (proven by
    the worker payload's own success=True despite an unregistered model
    name for step 3)."""
    import tcad_2d_stagewise as gui_mod
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe

    steps = [
        _etch_recipe(),
        _oxidation_recipe(0.3),
        dict(_process_category="oxidation", _process_model_key="__sentinel_never_registered__"),
    ]
    payload = _run_worker_flow(steps)
    assert payload["success"], payload
    assert payload["requested_step_count"] == 3, payload
    assert payload["executed_step_count"] == 2, payload
    assert payload["stopped_unsupported"] is True, payload
    step_results = payload["step_results"]
    assert len(step_results) == 2, step_results
    assert step_results[0]["category"] == "etching", step_results
    assert step_results[1]["category"] == "oxidation", step_results
    assert step_results[1]["state_transition"]["kind"] == "unsupported", step_results

    state = initial_wafer_state_from_recipe({
        "x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": 0.05,
    })
    entries = gui_mod._step_results_to_entries(step_results)
    state = gui_mod.advance_wafer_state_sequence(state, entries)

    unsupported_events = [e for e in state.events if e.category == "UNSUPPORTED_BY_MODEL"]
    assert len(unsupported_events) == 2, (
        f"expected exactly 2 WaferState transitions (etch + oxidation), "
        f"sentinel must contribute 0: {[e.process_category for e in unsupported_events]}")
    assert [e.process_category for e in unsupported_events] == ["etching", "oxidation"], (
        f"transition order/category mismatch: "
        f"{[e.process_category for e in unsupported_events]}")

    q = state.net_doping_at(0.0, -0.25)
    assert q.net_doping is None
    assert (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"
    print("PASS test_2: etch transition x1, oxidation-unsupported transition "
          "x1, sentinel transition x0 (registry lookup never happened), "
          "final query UNSUPPORTED_BY_MODEL")


# ---------------------------------------------------------------------------
# 3. zero-duration identity in the middle
# ---------------------------------------------------------------------------
def test_3_zero_duration_identity_in_middle():
    """etch -> oxidation(time=0, inherited domain -> identity) ->
    deposition: the identity step must change NOTHING (same object,
    zero new events) and must not shift the index/order of the steps
    around it."""
    import tcad_2d_stagewise as gui_mod
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe

    steps = [_etch_recipe(), _oxidation_recipe(0.0), _deposition_recipe()]
    payload = _run_worker_flow(steps)
    assert payload["success"], payload
    assert payload["executed_step_count"] == 3, payload
    step_results = payload["step_results"]
    assert len(step_results) == 3, step_results
    assert step_results[1]["state_transition"] == {
        "kind": "identity", "reason": "zero_duration_oxidation",
        "category": "oxidation", "inherited": True,
    }, step_results[1]

    state0 = initial_wafer_state_from_recipe({
        "x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": 0.05,
    })
    entries = gui_mod._step_results_to_entries(step_results)
    assert [c for c, _ in entries] == ["etching", "oxidation", "deposition"], (
        "step order must be preserved exactly, not reordered/merged")

    state_after_etch = gui_mod.advance_wafer_state_sequence(state0, entries[:1])
    state_after_ox = gui_mod.advance_wafer_state_sequence(state_after_etch, entries[1:2])
    state_after_dep = gui_mod.advance_wafer_state_sequence(state_after_ox, entries[2:])

    assert state_after_ox is state_after_etch, (
        "zero-duration identity must return the prior state object "
        "COMPLETELY unchanged, not a new equivalent one")
    assert len(state_after_ox.events) == len(state_after_etch.events), (
        "identity must add zero new events")

    all_events_direct = gui_mod.advance_wafer_state_sequence(state0, entries)
    events_seq = [e.process_category for e in all_events_direct.events]
    # Exactly 2 new fail-closed transitions (etch, deposition); identity
    # contributes none, and etch/deposition keep their relative order.
    unsupported = [e.process_category for e in all_events_direct.events
                   if e.category == "UNSUPPORTED_BY_MODEL"]
    assert unsupported == ["etching", "deposition"], (
        f"identity step must not appear as a transition, and etch/"
        f"deposition order must be preserved: {unsupported}")
    print("PASS test_3: zero-duration identity leaves state object "
          "unchanged (0 new events), etch/deposition order preserved "
          "around it (etching, deposition -- oxidation identity invisible)")


# ---------------------------------------------------------------------------
# 4. resume path
# ---------------------------------------------------------------------------
def test_4_resume_path():
    """A real GUI RUN PROCESS FLOW with an existing completed step
    (domain_state resumable): only the NEWLY queued step's own
    WaferState transition is added -- the prior step's is never
    duplicated."""
    gui_mod, app = _open_gui_mandatory("test_4")
    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        raise RuntimeError(f"MANDATORY test_4 requires real ViennaPS.\n{_ENV_HINT}")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        assert len(app.flow_steps) == 1
        app.run_process_flow()
        assert app.last_domain_state and Path(app.last_domain_state).exists()
        assert len(app.completed_steps) == 1
        events_after_etch = len(app.wafer_state.events)

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.03)
        app.etch_time_var.set(0.5)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        assert len(app.flow_steps) == 1

        captured_entries = []
        orig_seq = gui_mod.advance_wafer_state_sequence

        def _spy(state, entries):
            entries = list(entries)
            captured_entries.append(entries)
            return orig_seq(state, entries)

        with patch.object(gui_mod, "advance_wafer_state_sequence", side_effect=_spy):
            app.run_process_flow()

        assert len(app.completed_steps) == 2, app.completed_steps
        assert len(captured_entries) == 1, captured_entries
        assert len(captured_entries[0]) == 1, (
            f"resume: exactly 1 NEW step must be advanced, not the prior "
            f"one again: {captured_entries[0]}")
        assert captured_entries[0][0][0] == "etching", captured_entries[0]

        events_after_second = len(app.wafer_state.events)
        assert events_after_second == events_after_etch + 1, (
            f"expected exactly +1 new event (the 2nd etch), got "
            f"{events_after_second - events_after_etch}: prior "
            f"completed step's event must not be duplicated")
        print(f"PASS test_4: resume path added exactly 1 new WaferState "
              f"event ({events_after_etch} -> {events_after_second}), "
              f"prior completed step's event not duplicated")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


# ---------------------------------------------------------------------------
# 5. replay path
# ---------------------------------------------------------------------------
def test_5_replay_path():
    """can_resume=False (forced by clearing last_domain_state, the same
    real trigger the GUI itself uses when no resumable .vpsd exists):
    the worker replays the completed history to rebuild backend
    geometry, but WaferState must advance ONLY the genuinely new step --
    the replayed prefix must not be re-applied (no duplicate events/
    inventory)."""
    gui_mod, app = _open_gui_mandatory("test_5")
    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        raise RuntimeError(f"MANDATORY test_5 requires real ViennaPS.\n{_ENV_HINT}")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        app.run_process_flow()
        assert len(app.completed_steps) == 1
        events_after_etch = len(app.wafer_state.events)

        # Force the real replay path: no resumable .vpsd, exactly the
        # condition _chained_flow_config()/run_process_flow() itself
        # checks (`state and Path(state).exists()`).
        app.last_domain_state = None

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.03)
        app.etch_time_var.set(0.5)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False

        captured_entries = []
        orig_seq = gui_mod.advance_wafer_state_sequence

        def _spy(state, entries):
            entries = list(entries)
            captured_entries.append(entries)
            return orig_seq(state, entries)

        with patch.object(gui_mod, "advance_wafer_state_sequence", side_effect=_spy):
            app.run_process_flow()

        assert len(app.completed_steps) == 2, app.completed_steps
        assert len(captured_entries) == 1, captured_entries
        assert len(captured_entries[0]) == 1, (
            f"replay: the replayed (already-completed) prefix must NOT be "
            f"re-advanced into WaferState, only the genuinely new step: "
            f"{captured_entries[0]}")

        events_after_replay = len(app.wafer_state.events)
        assert events_after_replay == events_after_etch + 1, (
            f"replay must add exactly +1 new event, not duplicate the "
            f"replayed prefix's own event: "
            f"{events_after_replay - events_after_etch}")
        print(f"PASS test_5: replay path (can_resume=False) re-ran backend "
              f"geometry for the completed prefix but added exactly +1 new "
              f"WaferState event ({events_after_etch} -> "
              f"{events_after_replay}), no duplication")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


# ---------------------------------------------------------------------------
# 7. step_results alignment
# ---------------------------------------------------------------------------
def test_7_step_results_alignment():
    """Each step_results[i] must be exactly that step's own
    category/model/mesh/state_transition/physics_status/
    numerical_status -- never another step's."""
    steps = [_etch_recipe(), _deposition_recipe(), _oxidation_recipe(0.3)]
    payload = _run_worker_flow(steps)
    assert payload["success"], payload
    step_results = payload["step_results"]
    assert len(step_results) == 3, step_results

    expected_categories = ["etching", "deposition", "oxidation"]
    expected_models = ["isotropic", "isotropic", "thermal"]
    mesh_paths = set()
    for i, (sr, exp_cat, exp_model, recipe) in enumerate(
        zip(step_results, expected_categories, expected_models, steps)
    ):
        assert sr["index"] == i, sr
        assert sr["category"] == exp_cat, sr
        assert sr["model_key"] == exp_model, sr
        assert sr["executed"] is True, sr
        assert sr["final_mesh"], sr
        assert Path(sr["final_mesh"]).exists(), sr
        mesh_paths.add(sr["final_mesh"])
    assert len(mesh_paths) == 3, (
        f"each step must have its OWN distinct mesh file, got "
        f"{len(mesh_paths)} distinct paths for 3 steps: {mesh_paths}")

    # Only the oxidation (index 2) step is UNSUPPORTED_BY_MODEL /
    # carries an oxidation-specific reason_code -- etch/deposition
    # (indices 0,1) must not, and etch's own physics_status (the
    # resolver is wired for isotropic etching -- CLAUDE.md) must name
    # only ITS OWN parameter, never cross-contaminated with oxidation's.
    assert step_results[0]["state_transition"] is None, step_results[0]
    assert step_results[1]["state_transition"] is None, step_results[1]
    assert step_results[2]["state_transition"]["kind"] == "unsupported", step_results[2]
    assert step_results[2]["physics_status"]["reason_code"] == "OXIDATION_CAPABILITY_PROOF_MISSING", step_results[2]
    assert not (step_results[0]["physics_status"] or {}).get("reason_code"), step_results[0]
    assert not (step_results[1]["physics_status"] or {}).get("reason_code"), step_results[1]
    if step_results[0]["physics_status"]:
        params0 = [e["parameter"] for e in step_results[0]["physics_status"]["entries"]]
        assert params0 == ["etch_rate"], (
            f"step 0 (etch) physics_status entries must be its OWN "
            f"parameter, never another step's: {params0}")
    print("PASS test_7: step_results[i] alignment verified for all 3 "
          "indices -- distinct mesh per step, state_transition/"
          "physics_status each belong to their own step only")


# ---------------------------------------------------------------------------
# 8. GUI real flow
# ---------------------------------------------------------------------------
def test_8_gui_real_flow():
    """A real small ViennaPS flow through the actual GUI:
    completed_steps/flow_step_meshes index alignment, step sequencing
    order matches execution order, unsupported prefix/suffix handling
    consistent, GUI log shows each step's state-transfer result, and
    the final electrical gate agrees with WaferState."""
    import tcad_2d_stagewise as gui_mod
    gui_mod2, app = _open_gui_mandatory("test_8")
    devsim = _require_viennaps_and_devsim(gui_mod2, app, "test_8")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False

        app.oxidation_method.set("Thermal oxidation")
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.4)
        app._pending_flow_add = True
        try:
            app.run_oxidation()
        finally:
            app._pending_flow_add = False

        assert len(app.flow_steps) == 2

        captured_entries = []
        orig_seq = gui_mod.advance_wafer_state_sequence

        def _spy(state, entries):
            entries = list(entries)
            captured_entries.append(entries)
            return orig_seq(state, entries)

        log_before = app.log.get("1.0", "end-1c")
        with patch.object(gui_mod, "advance_wafer_state_sequence", side_effect=_spy):
            app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert len(captured_entries) == 1, captured_entries
        entries = captured_entries[0]
        assert [c for c, _ in entries] == ["etching", "oxidation"], (
            f"sequencing order must match real execution order: "
            f"{[c for c, _ in entries]}")

        assert len(app.completed_steps) == 1, app.completed_steps
        assert app.completed_steps[0]["_process_category"] == "etching"
        assert len(app.flow_step_meshes) == len(app.completed_steps), (
            "completed_steps/flow_step_meshes must stay index-aligned")

        assert "WaferState sequencing (per-step, in execution order):" in log_delta, log_delta
        assert "[1/2] etching:" in log_delta, log_delta
        assert "[2/2] oxidation: unsupported" in log_delta, log_delta
        assert "PROCESS FLOW COMPLETE" not in log_delta, log_delta

        # Final electrical gate: doping/DevSim must be blocked, matching
        # WaferState's own fail-closed state (both etch AND oxidation
        # ended up UNSUPPORTED_BY_MODEL in WaferState -- etch because no
        # GeometryTransform exists anywhere yet, oxidation because it
        # is the explicit Phase 1 UNSUPPORTED_BY_MODEL contract).
        q = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q.net_doping is None
        assert (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        app.run_doping(silent=True)

        obs = _Observer(devsim)
        obs.install()
        try:
            app.meas_voltage_var.set(0.01)
            app.meas_axis_var.set("x")
            app.meas_source_pin.set("max")
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls == 0, f"solve() called {obs.solve_calls}x on a WaferState-unsupported wafer"
        assert not obs.doping_writes, f"doping writes on a WaferState-unsupported wafer: {obs.doping_writes}"
        print("PASS test_8: real GUI flow [etch, unsupported oxidation] -- "
              "sequencing order etching->oxidation, completed_steps/"
              "flow_step_meshes aligned, log shows per-step state-transfer, "
              "electrical gate agrees with WaferState (0 solve/0 writes)")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# 9. DevSim gate
# ---------------------------------------------------------------------------
def test_9_devsim_gate():
    """A flow where EVERY step's backend geometry genuinely succeeds
    (no Phase 1 rejection anywhere -- plain etch + deposition, nothing
    UNSUPPORTED at the process-result level) must STILL block DevSim:
    no GeometryTransform exists anywhere in production yet, so every
    step fails closed in WaferState regardless of backend success
    (absolute principle: backend success != WaferState state-transfer
    success)."""
    import tcad_2d_stagewise as gui_mod
    gui_mod2, app = _open_gui_mandatory("test_9")
    devsim = _require_viennaps_and_devsim(gui_mod2, app, "test_9")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False

        app.deposition_model.set("Isotropic Deposition")
        app.dep_isotropic_rate_var.set(0.02)
        app.dep_isotropic_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_deposition()
        finally:
            app._pending_flow_add = False

        assert len(app.flow_steps) == 2
        app.run_process_flow()

        # Backend genuinely succeeded for BOTH steps -- process_stage IS
        # promoted to flow_done, unlike the unsupported-terminal case.
        assert app.process_stage == "flow_done", app.process_stage
        assert len(app.completed_steps) == 2, app.completed_steps

        # WaferState is nonetheless fail-closed: neither step ever had a
        # real GeometryTransform built for it.
        q = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q.net_doping is None, (
            f"backend succeeded but WaferState must still be fail-closed "
            f"(no GeometryTransform exists for etching/deposition in "
            f"production yet): {q}")
        assert (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        app.run_doping(silent=True)

        obs = _Observer(devsim)
        obs.install()
        try:
            app.meas_voltage_var.set(0.01)
            app.meas_axis_var.set("x")
            app.meas_source_pin.set("max")
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls == 0, (
            f"solve() called {obs.solve_calls}x -- a backend-successful "
            f"but WaferState-unsupported flow must still block DevSim")
        assert not obs.doping_writes, (
            f"doping writes despite WaferState fail-closed state: {obs.doping_writes}")
        # No numeric fallback reused the last mesh's materials as a
        # doping proxy: the measurement must not have silently
        # regenerated a number from stale/backend-only data.
        q_final = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_final.net_doping is None
        print("PASS test_9: backend etch+deposition both genuinely "
              "succeeded (process_stage=flow_done), but WaferState stayed "
              "fail-closed (no GeometryTransform exists yet) -- DevSim "
              "gate blocked: 0 solve() calls, 0 doping writes, 0 fallback "
              "numeric regeneration")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# P1-1 (Codex correction). GUI E2E: validate_step_results() rejection ->
# no final-step-only fallback, no state adopted, 1 explicit fail-closed
# event, doping query None, DevSim blocked.
# ---------------------------------------------------------------------------
def test_P1_1_gui_malformed_payload_e2e():
    """`validate_step_results()` itself is proven against 10 malformed
    payload shapes in tests/unit/test_waferstate_sequential_advance_mock.py
    (test_P1_1_malformed_step_results_payloads) -- every one of those
    cases funnels through the SAME `if not is_valid: ...` branch inside
    run_process_flow(), so this test proves that branch's real GUI/
    DevSim consequences ONCE, end to end, for a representative
    rejection (forced via a patched validate_step_results that always
    reports invalid, so the exercised code path is the real production
    one, not a hand-simulated substitute)."""
    gui_mod, app = _open_gui_mandatory("test_P1_1_gui_malformed_payload_e2e")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_P1_1_gui_malformed_payload_e2e")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        # Real dopant, really queryable -- before ANY process step ran,
        # so its loss can only be attributed to what this test does.
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)
        q_before = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_before.donor_concentration == 1e16, q_before

        obs_sanity = _Observer(devsim)
        obs_sanity.install()
        try:
            app.meas_voltage_var.set(0.01)
            app.meas_axis_var.set("x")
            app.meas_source_pin.set("max")
            app.run_measurement()
        finally:
            obs_sanity.restore()
        assert obs_sanity.solve_calls >= 1, "sanity: a real measurement should solve"

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        assert len(app.flow_steps) == 1

        events_before = len(app.wafer_state.events)
        last_final_mesh_before = app.last_final_mesh
        last_domain_state_before = app.last_domain_state
        completed_steps_before = list(app.completed_steps)
        flow_steps_before = list(app.flow_steps)

        log_before = app.log.get("1.0", "end-1c")
        with patch.object(
            gui_mod, "validate_step_results",
            side_effect=lambda result, expected_steps: (False, "INJECTED_TEST_FAILURE_FOR_P1_1"),
        ):
            app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert app.last_final_mesh == last_final_mesh_before, (
            "an invalid payload must not adopt any backend final_mesh")
        assert app.last_domain_state == last_domain_state_before, (
            "an invalid payload must not adopt any backend domain_state")
        assert app.completed_steps == completed_steps_before, (
            f"an invalid payload must not touch completed_steps: {app.completed_steps}")
        assert app.flow_steps == flow_steps_before, (
            f"an invalid payload must leave the queue untouched: {app.flow_steps}")
        assert app.process_stage != "flow_done"

        events_after = len(app.wafer_state.events)
        assert events_after == events_before + 1, (
            f"expected exactly +1 explicit fail-closed event, got "
            f"{events_after - events_before}")
        new_event = app.wafer_state.events[-1]
        assert new_event.category == "UNSUPPORTED_BY_MODEL", new_event
        assert new_event.process_category == "flow_step_sequence_invalid", new_event

        assert app.last_physics_status["reason_code"] == "FLOW_STEP_SEQUENCE_METADATA_INVALID"
        assert "FLOW_STEP_SEQUENCE_METADATA_INVALID" in log_delta, log_delta
        assert "PROCESS FLOW COMPLETE" not in log_delta, log_delta

        q_after = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_after.net_doping is None, (
            f"previously-real dopant must be UNSUPPORTED after an "
            f"invalid-payload fail-close: {q_after}")

        obs = _Observer(devsim)
        obs.install()
        try:
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls == 0, f"solve() called {obs.solve_calls}x after an invalid payload"
        assert not obs.doping_writes, f"doping writes after an invalid payload: {obs.doping_writes}"
        print("PASS test_P1_1_gui_malformed_payload_e2e: invalid step_results "
              "-> 0 state adopted (final_mesh/domain_state/completed_steps/"
              "flow_steps all preserved), +1 explicit "
              "FLOW_STEP_SEQUENCE_METADATA_INVALID event, previously-real "
              "dopant now UNSUPPORTED, DevSim blocked (0 solve/0 writes)")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# K (cross-layer provenance). GUI E2E with the ACTUAL, non-monkeypatched
# validate_step_results() -- the worker's own JSON response (from a
# REAL subprocess run) is corrupted so its recorded category disagrees
# with what was actually requested, exactly the "requested etch
# recorded as deposition" physical-provenance failure this whole task
# exists to catch. Never mocks validate_step_results() itself.
# ---------------------------------------------------------------------------
def test_K_gui_e2e_actual_validator_category_mismatch():
    """User requests a real etch (etching/isotropic). The worker's OWN
    real subprocess actually runs it -- but its JSON response is
    corrupted (category rewritten to "deposition", consistently, at
    the one place the worker payload records it) before
    run_process_flow() reads it, simulating exactly the physical
    scenario Codex named: a mismatch between the requested process and
    the recorded one. The REAL, unmodified validate_step_results() (no
    monkeypatch on the validator itself) must reject it."""
    gui_mod, app = _open_gui_mandatory("test_K")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_K")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)
        q_before = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_before.donor_concentration == 1e16, q_before

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        assert len(app.flow_steps) == 1
        assert app.flow_steps[0]["_process_category"] == "etching"

        events_before = len(app.wafer_state.events)
        last_final_mesh_before = app.last_final_mesh
        last_domain_state_before = app.last_domain_state
        completed_steps_before = list(app.completed_steps)

        orig_json_loads = gui_mod.json.loads

        def _corrupting_json_loads(text, *a, **k):
            data = orig_json_loads(text, *a, **k)
            # Only touch the flow-worker's own result payload (the
            # single JSON shape carrying "step_results") -- every other
            # json.loads call in this app (config files, other worker
            # payloads) is untouched.
            if isinstance(data, dict) and data.get("step_results"):
                corrupted = copy.deepcopy(data)
                # Consistent, internally-plausible corruption: category
                # rewritten to a real, valid process category
                # ("deposition"), never a garbage string -- proving the
                # validator catches a PHYSICALLY WRONG but well-formed
                # record, not just a malformed one.
                corrupted["step_results"][0]["category"] = "deposition"
                return corrupted
            return data

        log_before = app.log.get("1.0", "end-1c")
        with patch.object(gui_mod.json, "loads", side_effect=_corrupting_json_loads):
            app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert "FLOW_STEP_SEQUENCE_METADATA_INVALID" in log_delta, (
            f"the ACTUAL validator must reject a category mismatch: {log_delta}")
        assert "REQUESTED/RECORDED PROCESS MISMATCH" in log_delta, log_delta

        # 0 wrongly-categorized "deposition" SpatialEvent -- the whole
        # flow's WaferState sync must be refused BEFORE any per-step
        # advance runs, so nothing tagged "deposition" ever enters the
        # event history for this click.
        new_events = app.wafer_state.events[events_before:]
        assert len(new_events) == 1, (
            f"expected exactly 1 explicit fail-closed event, got "
            f"{len(new_events)}: {[e.process_category for e in new_events]}")
        assert new_events[0].process_category == "flow_step_sequence_invalid", new_events[0]
        assert not any(e.process_category == "deposition" for e in new_events), (
            f"a wrongly-recorded 'deposition' event must never be "
            f"created from an unverifiable payload: "
            f"{[e.process_category for e in new_events]}")

        assert app.last_final_mesh == last_final_mesh_before, (
            "the corrupted payload's backend final_mesh must not be adopted")
        assert app.last_domain_state == last_domain_state_before, (
            "the corrupted payload's backend domain_state must not be adopted")
        assert app.completed_steps == completed_steps_before, (
            f"completed_steps must not be touched by an unverifiable "
            f"payload: {app.completed_steps}")

        q_after = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_after.net_doping is None, (
            f"WaferState must be fail-closed (UNSUPPORTED_BY_MODEL) after "
            f"a provenance-mismatched payload: {q_after}")
        assert (q_after.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"

        obs = _Observer(devsim)
        obs.install()
        try:
            app.meas_voltage_var.set(0.01)
            app.meas_axis_var.set("x")
            app.meas_source_pin.set("max")
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls == 0, f"solve() called {obs.solve_calls}x after a provenance mismatch"
        assert not obs.doping_writes, f"doping writes after a provenance mismatch: {obs.doping_writes}"

        print("PASS test_K: ACTUAL (non-monkeypatched) validate_step_results() "
              "rejected a real worker response whose recorded category "
              "(deposition) disagreed with what was actually requested "
              "(etching) -- 0 wrongly-tagged deposition events, backend "
              "geometry/domain/history not adopted, WaferState "
              "UNSUPPORTED_BY_MODEL, DevSim blocked (0 solve/0 writes)")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# P1-2 (Codex correction). Replay equality-boundary anomaly: prior_
# completed_len=1, replay stops UNSUPPORTED at index 0 (INSIDE the
# already-completed prefix), executed_count==prior_completed_len==1 --
# the boundary the OLD count-only condition
# (`executed_count < prior_completed_len`) missed.
# ---------------------------------------------------------------------------
def test_P1_2_replay_equality_boundary_anomaly():
    """Deliberately-constructed precondition: this session's
    completed_steps BELIEVES a positive-time oxidation step already
    completed successfully. In reality any positive-time oxidation is
    ALWAYS UNSUPPORTED_BY_MODEL (Phase 1 contract, deterministic) --
    this codebase has no recipe that is genuinely "sometimes
    supported", so this is the only way to reach the exact boundary
    Codex named without waiting for real nondeterminism. Reproduced
    through the REAL run_process_flow()/worker path, not a hand-built
    JSON payload."""
    gui_mod, app = _open_gui_mandatory("test_P1_2")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_P1_2")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)
        q_before = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_before.donor_concentration == 1e16, q_before

        app.completed_steps = [_oxidation_recipe(0.3)]
        app.last_domain_state = None  # forces the real replay path
        sentinel_recipe = dict(
            _process_category="oxidation",
            _process_model_key="__sentinel_never_registered_p1_2__",
        )
        app.flow_steps = [sentinel_recipe]

        events_before = len(app.wafer_state.events)
        last_final_mesh_before = app.last_final_mesh
        last_domain_state_before = app.last_domain_state
        completed_steps_before = list(app.completed_steps)
        flow_steps_before = list(app.flow_steps)

        # patch.object on process_registry.get would NOT observe a call
        # made inside the real subprocess run_process_flow() dispatches
        # (a separate Python process, its own fresh import) -- proving
        # "the sentinel's garbage model name was never looked up" has
        # to go through the subprocess's own OBSERVABLE consequence
        # instead: registry.get() on an unregistered name raises
        # KeyError inside worker_main, which is caught and reported as
        # `payload["success"] = False`, which run_process_flow() turns
        # into "PROCESS FLOW FAILED" in the log and an early return
        # (never reaching completed_steps/flow_steps preservation or
        # the replay-anomaly log line below). Reaching those below,
        # with no "PROCESS FLOW FAILED", is exactly the same proof
        # test_C (test_oxidation_positive_time_unsupported_real.py)
        # used at the worker-payload level, now at the GUI level.
        log_before = app.log.get("1.0", "end-1c")
        app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert "PROCESS FLOW FAILED" not in log_delta, (
            f"the subprocess must have succeeded (sentinel never reached "
            f"the registry) -- a real failure would mean the sentinel's "
            f"garbage model name WAS looked up: {log_delta}")

        assert app.completed_steps == completed_steps_before, (
            f"replay anomaly must not overwrite completed_steps: {app.completed_steps}")
        assert app.flow_steps == flow_steps_before, (
            f"replay anomaly must leave the new queue untouched: {app.flow_steps}")
        assert app.last_final_mesh == last_final_mesh_before, (
            "replay anomaly must not adopt the partial replay's final_mesh")
        assert app.last_domain_state == last_domain_state_before, (
            "replay anomaly must not adopt the partial replay's domain_state "
            "as the current resume state")
        assert app.process_stage != "flow_done"
        assert "PROCESS FLOW COMPLETE" not in log_delta, log_delta
        assert "REPLAY ANOMALY" in log_delta, log_delta

        events_after = len(app.wafer_state.events)
        assert events_after == events_before + 1, (
            f"expected exactly +1 fail-closed event, got "
            f"{events_after - events_before}")
        new_event = app.wafer_state.events[-1]
        assert new_event.category == "UNSUPPORTED_BY_MODEL", new_event
        assert new_event.process_category == "replay_anomaly", new_event
        assert app.last_physics_status["reason_code"] == "REPLAY_ANOMALY_STALE_HISTORY"

        q_after = app.wafer_state.net_doping_at(0.0, -0.25)
        assert q_after.net_doping is None, (
            f"WaferState must be fail-closed entirely after a replay "
            f"anomaly: {q_after}")

        obs = _Observer(devsim)
        obs.install()
        try:
            app.meas_voltage_var.set(0.01)
            app.meas_axis_var.set("x")
            app.meas_source_pin.set("max")
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls == 0, f"solve() called {obs.solve_calls}x after a replay anomaly"
        assert not obs.doping_writes, f"doping writes after a replay anomaly: {obs.doping_writes}"

        print("PASS test_P1_2: prior_completed_len=1, replay stopped "
              "UNSUPPORTED at index 0 (INSIDE the completed prefix), "
              "executed_count==prior_completed_len==1 -- correctly detected "
              "as a replay anomaly (the boundary the old count-only "
              "condition missed): sentinel never dispatched, queue/history "
              "preserved, WaferState fail-closed (+1 event), DevSim blocked")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# P1-3 (Codex correction). Contrast case: prior_completed_len=1, the
# REPLAYED prior step is normal, and the UNSUPPORTED step is in the NEW
# suffix (stopped_step_index=1, NOT < prior_completed_len=1) -- must
# NOT be flagged as a replay anomaly.
# ---------------------------------------------------------------------------
def test_P1_3_normal_new_suffix_not_anomaly():
    """1 < prior_completed_len(1) is False -- the unsupported step is a
    genuinely NEW one, not inside the replayed prefix, so this must be
    handled as the ORDINARY stopped_unsupported case, not the anomaly
    path: the replayed prior step's event must not be duplicated, only
    the new unsupported step gets a new event, and it is excluded from
    completed_steps/queue exactly like every other terminal-unsupported
    case."""
    gui_mod, app = _open_gui_mandatory("test_P1_3")
    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        raise RuntimeError(f"MANDATORY test_P1_3 requires real ViennaPS.\n{_ENV_HINT}")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02)
        app.etch_time_var.set(1.0)
        app._pending_flow_add = True
        try:
            app.run_etch()
        finally:
            app._pending_flow_add = False
        app.run_process_flow()
        assert len(app.completed_steps) == 1
        events_after_etch = len(app.wafer_state.events)

        app.last_domain_state = None  # forces the real replay path
        app.oxidation_method.set("Thermal oxidation")
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.3)
        app._pending_flow_add = True
        try:
            app.run_oxidation()
        finally:
            app._pending_flow_add = False

        # process_stage was ALREADY "flow_done" from the first (fully
        # successful, single-real-etch) run_process_flow() call above --
        # this second, unsupported-terminal call must LEAVE it exactly
        # as it was (never re-promote it, but also never a reason to
        # revert it), matching run_oxidation()'s own unsupported-
        # standalone precedent of not touching process_stage at all.
        stage_before_second_call = app.process_stage

        log_before = app.log.get("1.0", "end-1c")
        app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert "REPLAY ANOMALY" not in log_delta, (
            f"a genuinely NEW suffix's own unsupported step must NOT be "
            f"flagged as a replay anomaly: {log_delta}")
        assert "UNSUPPORTED_BY_MODEL" in log_delta, log_delta

        events_after_replay = len(app.wafer_state.events)
        assert events_after_replay == events_after_etch + 1, (
            f"expected exactly +1 new event (the new suffix's own "
            f"unsupported oxidation) -- the replayed etch's event must "
            f"not be duplicated: {events_after_replay - events_after_etch}")

        # The unsupported oxidation is excluded from completed_steps
        # (same contract as every other terminal-unsupported case);
        # the replayed etch stays the only real completed step.
        assert len(app.completed_steps) == 1, app.completed_steps
        assert app.completed_steps[0]["_process_category"] == "etching"
        assert app.process_stage == stage_before_second_call, (
            f"process_stage must stay exactly as it was going into this "
            f"unsupported-terminal call ({stage_before_second_call!r}), "
            f"got {app.process_stage!r}")

        # This IS the ordinary stopped_unsupported path (not an
        # anomaly), so the new (partial, but VALID) result genuinely
        # updates last-known geometry.
        assert app.last_domain_state is not None
        print("PASS test_P1_3: replayed prior step normal, new suffix's own "
              "unsupported oxidation correctly NOT flagged as a replay "
              "anomaly -- +1 new event only (no duplication of the "
              "replayed etch), unsupported step excluded from "
              "completed_steps, prefix geometry/history preserved")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


def main():
    test_2_explicit_unsupported_terminal()
    test_3_zero_duration_identity_in_middle()
    test_4_resume_path()
    test_5_replay_path()
    test_7_step_results_alignment()
    test_8_gui_real_flow()
    test_9_devsim_gate()
    test_P1_1_gui_malformed_payload_e2e()
    test_K_gui_e2e_actual_validator_category_mismatch()
    test_P1_2_replay_equality_boundary_anomaly()
    test_P1_3_normal_new_suffix_not_anomaly()
    print("\nALL WAFERSTATE SEQUENTIAL FLOW (REAL) TESTS PASS (0 mandatory skips)")


if __name__ == "__main__":
    main()
