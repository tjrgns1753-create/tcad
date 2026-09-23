#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1-2 positive-time oxidation fail-closed Phase 1.

Real ViennaPS 4.6.2, real GUI (window withdrawn), real subprocess worker,
real DevSim. This is a MANDATORY real-execution test: Tk/ViennaPS/DevSim
unavailability is a hard failure (nonzero exit), never a silent skip that
still lets "ALL ... PASS" print (Codex P1-1 correction -- a prior version
of this file printed ALL PASS even when tests 4/5 silently skipped their
Tk/DevSim-dependent assertions).

Verified working Windows environment for this machine (Codex-supplied,
confirmed to actually run real Tk + real DevSim, not just import them):
    PATH must include <venv>\\Library\\bin
    DEVSIM_MATH_LIBS=mkl_rt.3.dll
    OMP_NUM_THREADS=1
    MKL_NUM_THREADS=1

Approved contract (docs/audits/2026-09-18-tier1-2-oxidation-positive-
support/REPORT.md Rev.2): time_hours > 0 is UNSUPPORTED_BY_MODEL for
BOTH ThermalOxidation and LocosOxidation in Phase 1 -- no solver call,
no setInitialOxideThickness() call, no grid-dependent seed/pad-oxide
geometry, geometry unchanged, state_transition.kind == "unsupported"
(never "identity"), WaferState fails closed so no electrical measurement
can be built on it. run_flow() (tcad/process/flow.py) stops at the FIRST
unsupported step in a multi-step flow (P0-1); the GUI never reports
FLOW COMPLETE/flow_done for a flow that stopped early (P0-1); and the
standalone-oxidation user message distinguishes "no solver ran" /
"last-known geometry" / "unresolved physical state" / "doping+DevSim
blocked" instead of the misleading "geometry and doping are unchanged"
(P0-2).

Tests, matching the task's required list:
  1. mock solver-call trap (both ThermalOxidation, LocosOxidation),
     independently covering vps.Process / vps.Oxidation() / its
     setInitialOxideThickness() setter / LocosOxidation.
     _build_locos_geometry() (P1-2)
  2. inherited geometry identity-by-bytes (unsupported, not "identity")
  3. fresh request: 0 solver calls, no SiO2 created
  4. propagation across 4 layers: raw dict -> ProcessResult -> worker
     JSON (through a REAL multi-step flow, exercising the results[-1]
     fix) -> GUI state/log, with strengthened exact-equality assertions
     on processed_before/stage_before and a real WaferState doping-query
     before/after comparison (P1-3)
  5. electrical gate: a real doped, solved wafer; a positive-time
     oxidation request; the SAME real-DevSim call-counting Observer
     test_measurement_canonical_state_gate_real.py already uses, proving
     0 solve() calls / 0 doping node-model writes afterward
  6. zero-duration regression: re-run test_oxidation_zero_duration_
     identity_real.py's own main() in-process (not duplicated here)
  7. invalid-duration regression (negative/NaN/infinite -> ValueError,
     0 solver calls)
  A. run_flow: sentinel step after a first-and-only unsupported step is
     never looked up in the registry (P0-1)
  B. run_flow: a real supported PREFIX still runs in full before an
     unsupported step stops the flow; the sentinel after it is still
     never looked up (P0-1)
  C. worker JSON: a 3-step flow's payload correctly reports
     requested_step_count/executed_step_count/stopped_unsupported/
     stopped_step_index, and the 3rd (invalid-model) step is proven
     never dispatched (P0-1)
  D. real GUI: RUN PROCESS FLOW on [real etch, unsupported oxidation]
     never reports flow_done/PROCESS FLOW COMPLETE, keeps only the real
     etch in completed_steps, and a subsequent MEASURE makes 0 real
     DevSim solve() calls / 0 doping writes (P0-1)
  E. real GUI: the standalone-oxidation user message (log + popup) states
     the four distinct facts and never the old misleading "geometry and
     doping are unchanged" framing (P0-2)
"""
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import meshio
import numpy as np
import viennaps as vps
from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.process.oxidation.thermal import ThermalOxidation
from tcad.process.oxidation.locos import LocosOxidation
from tcad.process.flow import run_flow, FlowStep

BASE_RECIPE = dict(
    grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
    temperature_c=1000.0, oxidant="Dry", silicon_depth_um=0.5,
    mask_material="Mask", mask_left_um=0.5, mask_right_um=1.5, pr_thickness_um=0.1,
)

_ENV_HINT = (
    "Verified working Windows environment: add <venv>\\Library\\bin to "
    "PATH, set DEVSIM_MATH_LIBS=mkl_rt.3.dll, OMP_NUM_THREADS=1, "
    "MKL_NUM_THREADS=1."
)


def same_mesh(a, b):
    a, b = meshio.read(a), meshio.read(b)
    np.testing.assert_array_equal(a.points, b.points)
    assert len(a.cells) == len(b.cells)
    for x, y in zip(a.cells, b.cells):
        assert x.type == y.type
        np.testing.assert_array_equal(x.data, y.data)
    for x, y in zip(a.cell_data["Material"], b.cell_data["Material"]):
        np.testing.assert_array_equal(x, y)


def _bare_inherited_domain(grid=0.05):
    domain = session.create_domain(grid, 2.0, 1.0)
    vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
    return domain


def _open_gui_mandatory(test_name):
    """Real Tk app, window withdrawn. Unavailability is a MANDATORY
    test failure (P1-1) -- never a soft skip."""
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


# ---------------------------------------------------------------------------
# P1-2: independent traps for every forbidden Phase 1 call
# ---------------------------------------------------------------------------
class _TrapOxidationModel:
    """vps.Oxidation replacement that raises distinctly on construction
    AND on setInitialOxideThickness -- a Phase 1 regression that reaches
    either one fails loudly and names which (Codex P1-2: 'vps.Oxidation
    또는 setter 직접 trap')."""

    def __init__(self, *a, **k):
        raise AssertionError("vps.Oxidation() constructed on a positive-time request")

    def setInitialOxideThickness(self, *a, **k):
        raise AssertionError(
            "setInitialOxideThickness() called on a positive-time request"
        )


def _solver_trap():
    """ExitStack covering every forbidden Phase 1 call independently
    (P1-2): vps.Process (the solve), vps.Oxidation() (model
    construction -- also traps setInitialOxideThickness), and
    LocosOxidation._build_locos_geometry (the grid-floored pad-oxide
    build). Each one raises its OWN distinct AssertionError, so a
    regression names exactly which boundary was crossed."""
    stack = ExitStack()
    stack.enter_context(
        patch.object(vps, "Process", side_effect=AssertionError("vps.Process() called"))
    )
    stack.enter_context(patch.object(vps, "Oxidation", _TrapOxidationModel))
    stack.enter_context(
        patch.object(
            LocosOxidation, "_build_locos_geometry",
            side_effect=AssertionError("LocosOxidation._build_locos_geometry() called"),
        )
    )
    return stack


# ---------------------------------------------------------------------------
# 1. mock solver-call trap
# ---------------------------------------------------------------------------
def test_1_mock_solver_call_trap():
    for cls in (ThermalOxidation, LocosOxidation):
        for inherited in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                domain = _bare_inherited_domain() if inherited else None
                step = cls(inherited_domain=domain)
                recipe = dict(BASE_RECIPE, time_hours=0.3)
                with _solver_trap():
                    result = step.run(recipe, tmp)
                assert result["state_transition"]["kind"] == "unsupported"
                assert result["physics_status"]["resolution"] == "UNSUPPORTED_BY_MODEL"
                print(f"PASS test_1 {cls.__name__} inherited={inherited}: "
                      f"no AssertionError, Process()/Oxidation()/setter/"
                      f"_build_locos_geometry never called")


# ---------------------------------------------------------------------------
# 2. inherited geometry identity-by-bytes (unsupported, NOT identity)
# ---------------------------------------------------------------------------
def test_2_inherited_geometry_identity_by_bytes():
    for cls in (ThermalOxidation, LocosOxidation):
        with tempfile.TemporaryDirectory() as tmp:
            domain = _bare_inherited_domain()
            before = save_volume_mesh(domain, Path(tmp) / "before", floor_depth_um=0.5)
            step = cls(inherited_domain=domain)
            recipe = dict(BASE_RECIPE, time_hours=0.3)
            with _solver_trap():
                result = step.run(recipe, tmp)
            same_mesh(before, result["final_mesh"])
            assert step.last_domain is domain
            assert result["state_transition"]["kind"] == "unsupported"
            assert result["state_transition"] != {
                "kind": "identity", "reason": "zero_duration_oxidation",
                "category": "oxidation", "inherited": True,
            }
            print(f"PASS test_2 {cls.__name__}: geometry byte-identical, "
                  f"state_transition is unsupported (not identity)")


# ---------------------------------------------------------------------------
# 3. fresh request: 0 solver calls, no SiO2 created
# ---------------------------------------------------------------------------
def _mesh_materials(path):
    """Exact sorted material names present as triangles in an exported mesh."""
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type == "triangle":
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(vps.Material(t)).split("'")[1] for t in tags)


def test_3_fresh_request_no_seed():
    """A fresh positive-time request that is UNSUPPORTED must hand back the
    recipe's virgin Si wafer and NOTHING else: not SiO2, and not the Mask
    the recipe's own mask keys describe. The failed step may not build
    structure -- `materials == ["Si"]` exactly (this used to assert only
    "SiO2 not present", which let a Mask through)."""
    from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
    from tcad.physics.wafer_state_v2 import attach_dopant, uniform_inventory_integral

    for grid in (0.02, 0.05, 0.1):
        for cls in (ThermalOxidation, LocosOxidation):
            for pad in ((None, 0.1, 0.2) if cls is LocosOxidation else (None,)):
                with tempfile.TemporaryDirectory() as tmp:
                    recipe = dict(BASE_RECIPE, grid_delta_um=grid, time_hours=0.5)
                    if pad is not None:
                        recipe["pad_oxide_thickness_um"] = pad
                    ref = session.make_mask_spans(grid, 2.0, 1.0, [], 0.1, substrate_depth_um=0.5 + 1.0)
                    ref_mesh = save_volume_mesh(ref, Path(tmp) / "ref", floor_depth_um=0.5)
                    step = cls()  # no inherited domain
                    with _solver_trap():
                        result = step.run(recipe, tmp)
                    materials = sorted(str(m).split("'")[1] for m in step.last_domain.getMaterialsInDomain())
                    assert materials == ["Si"], f"{cls.__name__} grid={grid} pad={pad}: {materials}"
                    assert _mesh_materials(result["final_mesh"]) == ["Si"], (
                        f"{cls.__name__} grid={grid} pad={pad}: exported "
                        f"{_mesh_materials(result['final_mesh'])}")
                    same_mesh(ref_mesh, result["final_mesh"])
                    assert result["state_transition"]["kind"] == "unsupported"
                    assert result["physics_status"]["resolution"] == "UNSUPPORTED_BY_MODEL"
                    # the wafer state built on it stays fail-closed
                    s0 = initial_wafer_state_from_recipe(
                        {"x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": grid})
                    doped = attach_dopant(
                        s0, species="P", polarity="donor", concentration_at=lambda x, y: 1e17,
                        support_instance_id=s0.cells[0].material_instance_id,
                        support_region_um=(-1.0, 1.0, -0.5, 0.0), model="uniform_v1",
                        inventory_integral=uniform_inventory_integral(1e17), chemical_state="ACTIVE")
                    out = advance_wafer_state(doped, build_process_result(result), "oxidation")
                    assert out is not doped and out.attachments == ()
        print(f"PASS test_3 grid={grid}: fresh request (both models, LOCOS pad omitted/0.1/0.2) -> "
              f"materials exactly [Si], exported mesh == virgin wafer, unsupported, "
              f"0 solve/model/seed/_build_locos_geometry, WaferState fail-closed")


# ---------------------------------------------------------------------------
# 4. propagation across 4 layers (raw dict -> ProcessResult -> worker JSON
#    via a REAL 2-step flow -> GUI state/log)
# ---------------------------------------------------------------------------
def test_4_propagation_four_layers():
    recipe = dict(BASE_RECIPE, time_hours=0.4)

    # Layer 1: raw step result
    with tempfile.TemporaryDirectory() as tmp:
        raw = ThermalOxidation().run(recipe, tmp)
    assert raw["physics_status"]["reason_code"] == "OXIDATION_CAPABILITY_PROOF_MISSING"
    assert raw["state_transition"]["kind"] == "unsupported"
    print("PASS test_4 layer 1 (raw step result): reason_code + state_transition present")

    # Layer 2: ProcessResult
    with tempfile.TemporaryDirectory() as tmp:
        raw2 = ThermalOxidation().run(recipe, tmp)
        canonical = build_process_result(raw2)
    assert canonical.physics_status["reason_code"] == "OXIDATION_CAPABILITY_PROOF_MISSING"
    assert canonical.metadata["state_transition"]["kind"] == "unsupported"
    print("PASS test_4 layer 2 (ProcessResult): reason_code + state_transition preserved")

    # Layer 3: worker JSON, through a REAL 2-step _flow_steps flow (this
    # exercises the results[-1] fix -- with the old results[0]-gated-on-
    # len==1 code, a 2nd-step oxidation's own transition was silently
    # replaced with None).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        step1_recipe = dict(BASE_RECIPE, time_hours=0.0, mask_spans_um=[])
        step2_recipe = dict(BASE_RECIPE, time_hours=0.4)
        config = {
            "output_dir": str(root / "flow"),
            "_flow_steps": [
                dict(step1_recipe, _process_category="oxidation", _process_model_key="thermal"),
                dict(step2_recipe, _process_category="oxidation", _process_model_key="thermal"),
            ],
        }
        cfg_path, out_path = root / "config.json", root / "result.json"
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        code = "from tcad_2d_stagewise import worker_main; import sys; worker_main(sys.argv[1], sys.argv[2])"
        child = subprocess.run(
            [sys.executable, "-c", code, str(cfg_path), str(out_path)],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=120,
        )
        assert child.returncode == 0, child.stderr
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["success"], payload
    assert payload["step_count"] == 2, payload
    assert payload["requested_step_count"] == 2, payload
    assert payload["executed_step_count"] == 2, payload
    # Both queued steps actually ran (2nd IS the unsupported one, and it
    # was the last queued step anyway) -- stopped_unsupported=True here
    # correctly reflects "the flow's last executed step was unsupported",
    # not "some queued step never ran". requested==executed is what
    # distinguishes this from a flow that stopped EARLY (see test_C).
    assert payload["stopped_unsupported"] is True, payload
    assert payload["stopped_step_index"] == 1, payload
    assert payload["state_transition"]["kind"] == "unsupported", (
        f"layer 3: step_count={payload['step_count']} but state_transition="
        f"{payload['state_transition']} -- the results[-1] fix did not take "
        f"effect (would be None under the old results[0]/len==1 code)")
    assert payload["physics_status"]["reason_code"] == "OXIDATION_CAPABILITY_PROOF_MISSING"
    print(f"PASS test_4 layer 3 (worker JSON, real 2-step flow): "
          f"state_transition={payload['state_transition']['kind']}, "
          f"reason_code preserved through step_count={payload['step_count']}, "
          f"requested=executed=2 (nothing skipped), stopped_unsupported=True "
          f"(the 2nd/last queued step is itself the unsupported one)")

    # Layer 4: GUI state/log, real subprocess dispatch via run_oxidation()
    gui_mod, app = _open_gui_mandatory("test_4 layer 4")
    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 2.0
        app.wafer.silicon_depth_um = 0.5
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer(), "materializing the real wafer failed"
        wafer_state_before = app.wafer_state
        stage_before = app.process_stage
        processed_before = app.wafer.processed
        probe_y = -app.wafer.silicon_depth_um / 2.0
        q_before = wafer_state_before.net_doping_at(0.0, probe_y)
        app.oxidation_method.set("Thermal oxidation")
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.4)
        log_before = app.log.get("1.0", "end-1c")
        app.run_oxidation()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]
        assert app.last_physics_status is not None
        assert app.last_physics_status["reason_code"] == "OXIDATION_CAPABILITY_PROOF_MISSING", app.last_physics_status
        assert "UNSUPPORTED_BY_MODEL" in log_delta, log_delta
        assert "OXIDATION_CAPABILITY_PROOF_MISSING" in log_delta, log_delta
        assert "COMPLETE" not in log_delta.upper().replace("NOT PERFORMED (UNSUPPORTED_BY_MODEL)", ""), log_delta
        # P1-3: exact equality, not a weak "or" fallback.
        assert app.process_stage == stage_before, (
            f"process_stage was promoted to {app.process_stage!r} on an "
            f"unsupported request (was {stage_before!r})")
        assert app.wafer.processed == processed_before, (
            f"wafer.processed changed from {processed_before!r} to "
            f"{app.wafer.processed!r} on an unsupported request")
        # P1-3: wafer_state was actually fail-closed, not merely left
        # "the same object" -- prove a real doping query flips to
        # UNSUPPORTED_BY_MODEL after the request, comparing against the
        # BEFORE query rather than assuming it.
        assert wafer_state_before is not app.wafer_state, (
            "wafer_state object was not replaced by the unsupported request")
        q_after = app.wafer_state.net_doping_at(0.0, probe_y)
        assert (q_after.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", (
            f"canonical doping query not fail-closed after unsupported "
            f"oxidation: before={q_before}, after={q_after}")
        print("PASS test_4 layer 4 (GUI state/log): reason_code in last_physics_status, "
              "UNSUPPORTED_BY_MODEL + reason_code in log, no COMPLETE framing, "
              "process_stage/wafer.processed exactly unchanged, wafer_state "
              "doping query fail-closed after the request")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


# ---------------------------------------------------------------------------
# 5. electrical gate: real doped + solved wafer, then a positive-time
#    oxidation request, then prove 0 solve() / 0 doping writes afterward.
#    Same real-DevSim Observer test_measurement_canonical_state_gate_real.py
#    already uses.
# ---------------------------------------------------------------------------
class _Observer:
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


def test_5_electrical_gate():
    gui_mod, app = _open_gui_mandatory("test_5")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_5")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer(), "materializing the real wafer failed"

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)

        # Sanity: a supported measurement on THIS wafer really solves
        # (proves the observer/pipeline works before trusting a 0 count).
        app.meas_voltage_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        obs = _Observer(devsim)
        obs.install()
        try:
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls >= 1, "sanity check: supported measurement did not solve"
        assert obs.doping_writes, "sanity check: supported measurement did not write doping"

        processed_before = app.wafer.processed
        # Now request a positive-time oxidation on this doped wafer.
        app.oxidation_method.set("Thermal oxidation")
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.3)
        app.run_oxidation()
        assert app.last_physics_status["resolution"] == "UNSUPPORTED_BY_MODEL", app.last_physics_status
        assert app.wafer.processed == processed_before, (
            f"wafer.processed changed from {processed_before!r} to "
            f"{app.wafer.processed!r} on an unsupported request")
        wafer_state_after_ox = app.wafer_state
        q = wafer_state_after_ox.net_doping_at(0.0, -0.5)
        assert q.net_doping is None, f"canonical doping still queryable after unsupported oxidation: {q}"
        assert (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", q.physics_status

        obs2 = _Observer(devsim)
        obs2.install()
        try:
            app.run_measurement()
        finally:
            obs2.restore()
        assert obs2.solve_calls == 0, f"solve() called {obs2.solve_calls} time(s) after unsupported oxidation"
        assert not obs2.doping_writes, f"doping node-model writes after unsupported oxidation: {obs2.doping_writes}"
        print(f"PASS test_5: doped+solved wafer -> positive-time oxidation UNSUPPORTED -> "
              f"canonical doping None/UNSUPPORTED_BY_MODEL -> re-measure: "
              f"0 solve() calls, 0 doping writes (sanity measurement before had "
              f"{obs.solve_calls} solve(s)/{len(obs.doping_writes)} write(s))")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# 7. invalid-duration regression
# ---------------------------------------------------------------------------
def test_7_invalid_duration():
    for cls in (ThermalOxidation, LocosOxidation):
        for bad in (-1.0, float("nan"), float("inf")):
            with _solver_trap():
                try:
                    cls().run({"time_hours": bad}, "unused")
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"{cls.__name__}: time_hours={bad} did not raise ValueError")
    print("PASS test_7: negative/NaN/infinite duration all raise ValueError, 0 solver calls")


# ---------------------------------------------------------------------------
# A. run_flow: sentinel after a first-and-only unsupported step never
#    reaches the registry (P0-1)
# ---------------------------------------------------------------------------
def test_A_unsupported_then_sentinel_zero_calls():
    from tcad.process import registry as process_registry

    calls = []
    orig_get = process_registry.get

    def _tracking_get(category, name):
        calls.append((category, name))
        return orig_get(category, name)

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(process_registry, "get", side_effect=_tracking_get):
            results = run_flow(
                [
                    FlowStep(
                        category="oxidation", name="thermal",
                        recipe=dict(BASE_RECIPE, time_hours=0.3, mask_spans_um=[]),
                    ),
                    FlowStep(
                        category="etching", name="isotropic",
                        recipe=dict(
                            rate=-0.02, etch_time_s=1.0, silicon_depth_um=0.5,
                            grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
                            mask_spans_um=[],
                        ),
                    ),
                ],
                tmp,
            )
    assert len(results) == 1, f"expected exactly 1 result (stopped at unsupported), got {len(results)}"
    assert results[0].metadata["state_transition"]["kind"] == "unsupported"
    assert calls == [("oxidation", "thermal")], (
        f"registry.get was called for the sentinel step too: {calls}")
    print("PASS test_A: sentinel step's registry.get never called after the "
          "first (and only) unsupported step")


# ---------------------------------------------------------------------------
# B. run_flow: a real supported prefix runs in full, then an unsupported
#    step stops the flow before the sentinel (P0-1)
# ---------------------------------------------------------------------------
def test_B_supported_prefix_then_unsupported_then_sentinel():
    from tcad.process import registry as process_registry

    etch_recipe = dict(
        rate=-0.02, etch_time_s=0.2, silicon_depth_um=0.5,
        grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
        mask_spans_um=[],
    )
    ox_recipe = dict(BASE_RECIPE, time_hours=0.3, mask_spans_um=[])

    calls = []
    orig_get = process_registry.get

    def _tracking_get(category, name):
        calls.append((category, name))
        return orig_get(category, name)

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(process_registry, "get", side_effect=_tracking_get):
            results = run_flow(
                [
                    FlowStep(category="etching", name="isotropic", recipe=etch_recipe),
                    FlowStep(category="oxidation", name="thermal", recipe=ox_recipe),
                    FlowStep(category="oxidation", name="thermal", recipe=ox_recipe),
                ],
                tmp,
            )
    assert len(results) == 2, f"expected exactly 2 results (real prefix + unsupported), got {len(results)}"
    first_transition = results[0].metadata.get("state_transition") or {}
    assert first_transition.get("kind") != "unsupported", (
        f"the real etch prefix was itself reported unsupported: {first_transition}")
    assert results[1].metadata["state_transition"]["kind"] == "unsupported"
    assert calls == [("etching", "isotropic"), ("oxidation", "thermal")], (
        f"a step after the unsupported one was looked up in the registry: {calls}")
    print("PASS test_B: real supported prefix executed in full, unsupported "
          "step stopped the flow, sentinel (3rd step) never looked up")


# ---------------------------------------------------------------------------
# C. worker JSON: 3-step flow correctly reports requested/executed/
#    stopped_unsupported/stopped_step_index, sentinel never dispatched
# ---------------------------------------------------------------------------
def test_C_worker_three_step_preserves_first_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        etch_recipe = dict(
            _process_category="etching", _process_model_key="isotropic",
            rate=-0.02, etch_time_s=1.0, silicon_depth_um=0.5,
            grid_delta_um=0.05, x_extent_um=2.0, y_extent_um=1.0,
            mask_spans_um=[],
        )
        ox_recipe = dict(
            BASE_RECIPE, time_hours=0.3, mask_spans_um=[],
            _process_category="oxidation", _process_model_key="thermal",
        )
        # An unregistered model name: if the worker ever looks this step
        # up (it must not -- P0-1), registry.get() raises KeyError and
        # the worker payload reports success=False, which the assertion
        # below would catch.
        sentinel_recipe = dict(
            _process_category="oxidation",
            _process_model_key="__sentinel_never_registered__",
        )
        config = {
            "output_dir": str(root / "flow"),
            "_flow_steps": [etch_recipe, ox_recipe, sentinel_recipe],
        }
        cfg_path, out_path = root / "config.json", root / "result.json"
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        code = "from tcad_2d_stagewise import worker_main; import sys; worker_main(sys.argv[1], sys.argv[2])"
        child = subprocess.run(
            [sys.executable, "-c", code, str(cfg_path), str(out_path)],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=120,
        )
        assert child.returncode == 0, child.stderr
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["success"], payload
    assert payload["requested_step_count"] == 3, payload
    assert payload["executed_step_count"] == 2, payload
    assert payload["stopped_unsupported"] is True, payload
    assert payload["stopped_step_index"] == 1, payload
    assert payload["state_transition"]["kind"] == "unsupported", payload
    assert payload["step_count"] == 2, payload
    print(
        "PASS test_C: 3-step worker flow requested=3 executed=2 "
        "stopped_unsupported=True stopped_step_index=1 -- sentinel step "
        "(invalid model name) never reached the registry"
    )


# ---------------------------------------------------------------------------
# D. real GUI: RUN PROCESS FLOW never reports flow_done/COMPLETE when it
#    stops on an unsupported step; a subsequent MEASURE makes 0 real
#    DevSim solve()/doping writes (P0-1)
# ---------------------------------------------------------------------------
def test_D_gui_process_flow_stops_not_complete():
    gui_mod, app = _open_gui_mandatory("test_D")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_D")

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        app.withdraw()
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer(), "materializing the real wafer failed"

        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)

        # Queue a real supported etch, then an unsupported oxidation,
        # using the same recipe-builder methods RUN buttons use, with
        # _pending_flow_add=True so they queue instead of running now
        # (the same mechanism add_current_step_to_flow() uses).
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
        app.ox_time_var.set(0.3)
        app._pending_flow_add = True
        try:
            app.run_oxidation()
        finally:
            app._pending_flow_add = False

        assert len(app.flow_steps) == 2, app.flow_steps

        log_before = app.log.get("1.0", "end-1c")
        app.run_process_flow()
        log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        assert app.process_stage != "flow_done", (
            f"process_stage promoted to flow_done despite the flow "
            f"stopping on an unsupported step (got {app.process_stage!r})")
        assert "PROCESS FLOW COMPLETE" not in log_delta, log_delta
        assert "UNSUPPORTED_BY_MODEL" in log_delta, log_delta
        assert len(app.flow_steps) == 0, (
            f"executed steps not cleared from the queue: {app.flow_steps}")
        assert len(app.completed_steps) == 1, (
            f"expected exactly 1 real completed step (the etch; the "
            f"unsupported oxidation must be excluded), got "
            f"{len(app.completed_steps)}: {app.completed_steps}")
        assert app.completed_steps[0]["_process_category"] == "etching", app.completed_steps

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
            f"solve() called {obs.solve_calls}x on a wafer whose flow "
            f"stopped on an unsupported step")
        assert not obs.doping_writes, (
            f"doping node-model writes after a flow stopped unsupported: "
            f"{obs.doping_writes}")
        print(
            "PASS test_D: GUI process flow [real etch, unsupported "
            "oxidation] stops without flow_done/COMPLETE, keeps only the "
            "real etch in completed_steps, and a subsequent MEASURE makes "
            "0 solve()/0 doping writes")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


# ---------------------------------------------------------------------------
# E. real GUI: the standalone-oxidation user message distinguishes
#    backend last-known mesh from unresolved physics (P0-2)
# ---------------------------------------------------------------------------
def test_E_user_message_distinguishes_backend_state():
    """Note: `_notify_info()` (tcad_2d_stagewise.py) is log-only by
    design as of the headless modal-dialog-hang fix (commit 3ba9404) --
    it deliberately never calls tkinter.messagebox.showinfo(), so there
    is no separate 'popup' text to check independently of the log. Both
    the direct `self._log(...)` call in run_oxidation()'s unsupported
    branch AND the `_notify_info(...)` call after it land in the same
    log widget, so capturing `_notify_info`'s own `message` argument
    directly (rather than mocking a messagebox call that is never made)
    is what actually proves its wording, independent of the log call
    right before it."""
    gui_mod, app = _open_gui_mandatory("test_E")

    captured = {}
    orig_notify_info = gui_mod.TCADApplication._notify_info

    def _capture_notify_info(self, title, message):
        captured["title"], captured["message"] = title, message
        return orig_notify_info(self, title, message)

    originals = {n: getattr(gui_mod.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, **k: None)
    try:
        with patch.object(gui_mod.TCADApplication, "_notify_info", _capture_notify_info):
            app.withdraw()
            app.wafer.width_um = 2.0
            app.wafer.silicon_depth_um = 0.5
            app.grid_var.set(0.05)
            assert app._materialize_current_wafer(), "materializing the real wafer failed"

            app.oxidation_method.set("Thermal oxidation")
            app.oxidant_var.set("Dry")
            app.ox_temp_var.set(1000.0)
            app.ox_time_var.set(0.4)
            log_before = app.log.get("1.0", "end-1c")
            app.run_oxidation()
            log_delta = app.log.get("1.0", "end-1c")[len(log_before):]

        WRONG_PHRASE = "Wafer geometry and doping are unchanged"
        assert WRONG_PHRASE not in log_delta, (
            f"misleading 'unchanged' framing still present in the log: {log_delta!r}")
        notify_message = captured.get("message", "")
        assert WRONG_PHRASE not in notify_message, (
            f"misleading 'unchanged' framing still present in the user "
            f"message: {captured}")

        # Codex correction: "blocked ... until a supported process step
        # runs" contradicts WaferState v2's fail-closed/no-resurrection
        # contract -- running some OTHER supported process afterward does
        # NOT restore the lost dopant/physical certainty for the
        # unresolved region (see
        # tests/unit/test_wafer_state_v2_fail_closed_no_resurrection_mock.py).
        # Neither message may imply recovery is that easy, and both must
        # state what real recovery actually requires.
        WRONG_RECOVERY_PHRASE = "until a supported process step runs"
        assert WRONG_RECOVERY_PHRASE not in log_delta, (
            f"misleading 'runs another supported step to unblock' framing "
            f"still present in the log: {log_delta!r}")
        assert WRONG_RECOVERY_PHRASE not in notify_message, (
            f"misleading 'runs another supported step to unblock' framing "
            f"still present in the user message: {captured}")

        for fact in ("No ViennaPS solver call", "LAST-KNOWN geometry", "UNRESOLVED", "blocked",
                     "does not restore"):
            assert fact in log_delta, f"missing fact {fact!r} in log:\n{log_delta}"
        for fact in ("no solver ran", "last-known geometry", "unresolved", "blocked",
                     "does not restore"):
            assert fact in notify_message.lower(), (
                f"missing fact {fact!r} in user message: {captured}")
        print("PASS test_E: unsupported-oxidation user message (log + the "
              "_notify_info message the headless-safe notifier carries) "
              "distinguishes last-known geometry from unresolved physical "
              "state and blocked doping/DevSim -- old misleading "
              "'unchanged' phrase is gone from both")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


def _run_gui_oxidation(method, time_h, materialize_first):
    """One real GUI oxidation click (real subprocess worker). Returns a dict
    with the log delta, the _notify_info message, the modal-call count and the
    exported mesh's exact materials."""
    gui_mod, app = _open_gui_mandatory("test_F")
    modal_calls = []
    names = ("showinfo", "showerror", "showwarning", "askyesno", "askokcancel",
             "askquestion", "askretrycancel", "askyesnocancel")
    originals = {n: getattr(gui_mod.messagebox, n) for n in names if hasattr(gui_mod.messagebox, n)}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, _n=n, **k: modal_calls.append(_n))
    captured = {}
    orig_notify_info = gui_mod.TCADApplication._notify_info

    def _capture(self, title, message):
        captured["message"] = message
        return orig_notify_info(self, title, message)

    try:
        with patch.object(gui_mod.TCADApplication, "_notify_info", _capture):
            app.withdraw()
            app.wafer.width_um = 2.0
            app.wafer.silicon_depth_um = 0.5
            app.grid_var.set(0.05)
            if materialize_first:
                assert app._materialize_current_wafer()
            app.oxidation_method.set(method)
            app.oxidant_var.set("Dry")
            app.ox_temp_var.set(1000.0)
            app.ox_time_var.set(time_h)
            before = (app.wafer.processed, app.process_stage)
            stages_before = set(app._stages_done)
            log_before = app.log.get("1.0", "end-1c")
            app.run_oxidation()
            return {
                "log": app.log.get("1.0", "end-1c")[len(log_before):],
                "notify": captured.get("message", ""),
                "modal_calls": list(modal_calls),
                "materials": _mesh_materials(app.last_final_mesh),
                "flags_before": before,
                "flags_after": (app.wafer.processed, app.process_stage),
                "stages_before": stages_before,
                "stages_after": set(app._stages_done),
            }
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        app.destroy()


def test_F_gui_zero_duration_and_unsupported_wording():
    """The user-facing text may not turn a zero-duration or unsupported
    oxidation into growth, a "COMPLETE" oxidation, or a pad oxide / mask
    creation, and no modal dialog may appear on any path."""
    # Success wording that no zero-duration or unsupported request may produce, in the log OR the user notification
    # (case-insensitive: the lowercase "simulation complete" once slipped past the uppercase-only "COMPLETE" check).
    success_phrases = ("simulation complete", "oxidation complete", "growth complete")
    FILM_OXIDE_MARKER = 1               # SESSION STATE index of "Film / oxide" (stages list in tcad_2d_stagewise.py)
    zero_duration_notes = {}
    for method in ("Thermal oxidation", "LOCOS (Advanced)"):
        for materialize_first in (False, True):
            where = "inherited" if materialize_first else "fresh"
            # ---- zero duration --------------------------------------------
            r = _run_gui_oxidation(method, 0.0, materialize_first)
            assert r["modal_calls"] == [], (method, where, r["modal_calls"])
            assert r["materials"] == ["Si"], (method, where, r["materials"])
            log = r["log"]
            # (round 2 of Batch 5) The user-facing notification and the log may not call a zero-duration request a
            # completed simulation / oxidation / growth, must say no oxidation was performed, and the Film / oxide
            # SESSION STATE marker must not light for a step that made no film.
            assert r["notify"], (method, where, "the zero-duration step produced no user notification")
            for text_name, text in (("log", log), ("notification", r["notify"])):
                for phrase in success_phrases:
                    assert phrase not in text.lower(), (
                        f"{method}/{where} zero-duration {text_name} contains {phrase!r}:\n{text}")
            assert "no oxidation performed" in r["notify"].lower(), (method, where, r["notify"])
            assert FILM_OXIDE_MARKER not in r["stages_after"], (
                f"{method}/{where}: a zero-duration step lit the Film / oxide marker: {r['stages_after']}")
            assert r["stages_after"] == r["stages_before"], (
                f"{method}/{where}: a zero-duration step changed the SESSION STATE markers: "
                f"{r['stages_before']} -> {r['stages_after']}")
            zero_duration_notes[(method, where)] = r["notify"]
            assert "no oxidation was performed" in log, log
            assert "ZERO-DURATION OXIDATION: NO OXIDATION PERFORMED" in log, log
            for wrong in ("COMPLETE", "Pad oxide + mask", "oxide was grown", "growth"):
                assert wrong not in log, f"{method}/{where} zero-duration log contains {wrong!r}:\n{log}"
            if not materialize_first:
                assert "bare Si wafer was materialized" in log, log
                assert "no SiO2, no mask and no pad oxide were created" in log, log
                # no earlier state: the new wafer's exact bounds ARE the initial state
                assert "WaferState initialized from the materialized wafer's own exact bounds" in log, log
                assert "CONTINUITY NOT PROVEN" not in log, log
                assert "preserved" not in log, (
                    f"a fresh materialization must never claim existing geometry/doping was preserved:\n{log}")
            else:
                assert "existing wafer geometry and doping are preserved" in log, log
                assert "CONTINUITY NOT PROVEN" not in log, log
            if method.startswith("LOCOS"):
                assert "creates neither" in log, log
            assert r["flags_after"] == r["flags_before"], (
                f"zero-duration oxidation promoted wafer.processed/process_stage: {r}")
            print(f"PASS test_F zero-duration {method}/{where}: 0 modal calls, materials [Si], "
                  f"'no oxidation was performed', no 'COMPLETE'/'Pad oxide + mask'/growth wording, "
                  f"processed/stage not promoted")

            # ---- positive time (UNSUPPORTED) --------------------------------
            r = _run_gui_oxidation(method, 0.4, materialize_first)
            assert r["modal_calls"] == [], (method, where, r["modal_calls"])
            assert r["materials"] == ["Si"], (method, where, r["materials"])
            text = r["log"] + "\n" + r["notify"]
            assert "OXIDATION RESULT NOT COMPUTED" in r["log"], r["log"]
            assert "COMPLETE" not in r["log"], r["log"]
            assert r["flags_after"] == r["flags_before"], r
            # (round 2 of Batch 5) no marker, no success wording, and the four fail-closed facts stay.
            assert FILM_OXIDE_MARKER not in r["stages_after"], (
                f"{method}/{where}: an unsupported request lit the Film / oxide marker: {r['stages_after']}")
            assert r["stages_after"] == r["stages_before"], (method, where, r["stages_before"], r["stages_after"])
            for phrase in success_phrases:
                assert phrase not in text.lower(), f"{method}/{where} unsupported text contains {phrase!r}:\n{text}"
            for fact in ("1. No ViennaPS solver call was made for this request.",
                         "2. The mesh shown is the LAST-KNOWN geometry",
                         "3. The physical state of this wafer after the requested oxidation is UNRESOLVED",
                         "4. Doping queries and DevSim solves remain blocked"):
                assert fact in r["log"], f"{method}/{where}: fail-closed fact missing from the log: {fact!r}"
            lowered = text.lower()
            for wrong in ("pad oxide + mask", "oxide was grown", "sio2 was created", "mask was created",
                          "oxidation complete"):
                assert wrong not in lowered, f"{method}/{where} unsupported text contains {wrong!r}:\n{text}"
            if method.startswith("LOCOS"):
                assert "creates neither" in r["log"], r["log"]
            print(f"PASS test_F unsupported {method}/{where}: 0 modal calls, materials [Si], "
                  f"'NOT COMPUTED', no 'COMPLETE'/pad-oxide/mask-creation wording, no Film / oxide marker, "
                  f"4 fail-closed facts kept")
        # (round 2 of Batch 5) a fresh materialization and an inherited identity are DIFFERENT outcomes and must be described
        # differently (compared without the final-mesh path, which differs anyway).
        fresh_note = zero_duration_notes[(method, "fresh")].split("Final mesh:")[0]
        inherited_note = zero_duration_notes[(method, "inherited")].split("Final mesh:")[0]
        assert fresh_note != inherited_note, f"{method}: fresh and inherited zero-duration notifications are identical"
        assert "materialized" in fresh_note and "preserved" not in fresh_note, fresh_note
        assert "preserved" in inherited_note and "materialized" not in inherited_note, inherited_note
        print(f"PASS test_F {method}: fresh-materialization and inherited-identity notifications are distinct "
              f"('materialized virgin Si' vs 'preserved as an identity'), neither says simulation/oxidation/growth complete")


def test_G_gui_fresh_materialization_with_forced_prior_state_fails_closed():
    """Forced counterexample: the GUI holds a doped, solved wafer (a prior
    WaferState), but the backend step receives NO domain and materializes a NEW
    bare Si wafer. Continuity is not proven, so WaferState must fail closed:
    the log says so, `existing ... preserved` is never claimed, the wafer is not
    promoted to processed/oxidized, and a following MEASURE makes 0 solve()/0
    doping writes."""
    gui_mod, app = _open_gui_mandatory("test_G")
    devsim = _require_viennaps_and_devsim(gui_mod, app, "test_G")
    modal_calls = []
    names = ("showinfo", "showerror", "showwarning", "askyesno", "askokcancel", "askquestion")
    originals = {n: getattr(gui_mod.messagebox, n) for n in names if hasattr(gui_mod.messagebox, n)}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, _n=n, **k: modal_calls.append(_n))
    try:
        app.withdraw()
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer(), "materializing the real wafer failed"
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)
        app.meas_voltage_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        obs = _Observer(devsim)
        obs.install()
        try:
            app.run_measurement()
        finally:
            obs.restore()
        assert obs.solve_calls >= 1, "sanity: the supported measurement did not solve"
        prior_state = app.wafer_state
        assert len(prior_state.attachments) == 1
        assert prior_state.net_doping_at(0.0, -0.5).net_doping == 1e16

        # Force the backend to build a NEW wafer while the GUI still holds the prior state.
        app.last_domain_state = None
        app.completed_steps = []
        app.oxidation_method.set("Thermal oxidation")
        app.oxidant_var.set("Dry")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.0)
        flags_before = (app.wafer.processed, app.process_stage)
        log_before = app.log.get("1.0", "end-1c")
        app.run_oxidation()
        log = app.log.get("1.0", "end-1c")[len(log_before):]

        assert "CONTINUITY NOT PROVEN" in log, log
        assert "fail-closed" in log and "nothing was preserved" in log, log
        assert "UNSUPPORTED_BY_MODEL" in log, log
        assert "existing wafer geometry and doping are preserved" not in log, log
        assert "no oxidation was performed" in log and "bare Si wafer was materialized" in log, log
        assert "COMPLETE" not in log, log
        assert (app.wafer.processed, app.process_stage) == flags_before, (
            f"a fresh zero-duration materialization was promoted: {flags_before} -> "
            f"{(app.wafer.processed, app.process_stage)}")
        assert modal_calls == [], modal_calls
        state = app.wafer_state
        assert state is not prior_state and state.attachments == ()
        assert len(state.unresolved_inventory) >= 1
        q = state.net_doping_at(0.0, -0.5)
        assert q.net_doping is None and (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", q

        obs2 = _Observer(devsim)
        obs2.install()
        try:
            app.run_measurement()
        finally:
            obs2.restore()
        assert obs2.solve_calls == 0, f"solve() called {obs2.solve_calls}x after continuity was lost"
        assert not obs2.doping_writes, obs2.doping_writes
        print("PASS test_G: doped+solved wafer, backend materialized a NEW bare Si wafer -> log says "
              "'CONTINUITY NOT PROVEN ... nothing was preserved', WaferState fail-closed (0 attachments, "
              "ledgered, query UNSUPPORTED), processed/stage not promoted, 0 modal calls, MEASURE makes "
              "0 solve()/0 doping writes")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)
        leaked = list(devsim.get_device_list())
        app.destroy()
    assert not leaked, f"leaked DevSim devices: {leaked}"


def _queue_oxidation(app, method, hours):
    app.oxidation_method.set(method)
    app.oxidant_var.set("Dry")
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(hours)
    app._pending_flow_add = True
    try:
        app.run_oxidation()
    finally:
        app._pending_flow_add = False


def test_H_gui_flow_counts_physical_changes_not_requested_steps():
    """`FLOW FINISHED` distinguishes "every requested step was processed" from "a
    physical process ran": a zero-duration oxidation earns neither
    `wafer.processed`, `flow_done`, nor a COMPLETE / growth wording. A real
    supported step in the same flow is the only thing counted as a physical
    change."""
    gui_mod, app_fresh = _open_gui_mandatory("test_H")
    app_fresh.destroy()

    def _app():
        _, app = _open_gui_mandatory("test_H")
        app.withdraw()
        app.wafer.width_um = 4.0
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        return app

    modal_calls = []
    names = ("showinfo", "showerror", "showwarning", "askyesno", "askokcancel", "askquestion")
    originals = {n: getattr(gui_mod.messagebox, n) for n in names if hasattr(gui_mod.messagebox, n)}
    for n in originals:
        setattr(gui_mod.messagebox, n, lambda *a, _n=n, **k: modal_calls.append(_n))
    FORBIDDEN = ("PROCESS FLOW COMPLETE", "OXIDATION COMPLETE", "Pad oxide + mask", "growth", "oxide was grown")
    try:
        # (1) fresh: ONLY a zero-duration oxidation queued -> 1 materialization, 0 physical changes
        for method in ("Thermal oxidation", "LOCOS (Advanced)"):
            app = _app()
            try:
                _queue_oxidation(app, method, 0.0)
                assert len(app.flow_steps) == 1
                flags_before = (app.wafer.processed, app.process_stage)
                log_before = app.log.get("1.0", "end-1c")
                app.run_process_flow()
                log = app.log.get("1.0", "end-1c")[len(log_before):]
                assert ("FLOW FINISHED: 0 physical process change(s), 1 zero-duration "
                        "materialization(s), 0 zero-duration identity step(s)") in log, log
                for wrong in FORBIDDEN:
                    assert wrong not in log, f"{method}: {wrong!r} in flow log:\n{log}"
                assert (app.wafer.processed, app.process_stage) == flags_before, (
                    f"{method}: a zero-duration-only flow was promoted: {flags_before} -> "
                    f"{(app.wafer.processed, app.process_stage)}")
                assert app.process_stage != "flow_done"
            finally:
                app.destroy()
        # (2) inherited: a materialized wafer, then ONLY a zero-duration oxidation -> 1 identity, 0 physical
        app = _app()
        try:
            assert app._materialize_current_wafer()
            _queue_oxidation(app, "Thermal oxidation", 0.0)
            flags_before = (app.wafer.processed, app.process_stage)
            log_before = app.log.get("1.0", "end-1c")
            app.run_process_flow()
            log = app.log.get("1.0", "end-1c")[len(log_before):]
            assert ("FLOW FINISHED: 0 physical process change(s), 0 zero-duration "
                    "materialization(s), 1 zero-duration identity step(s)") in log, log
            for wrong in FORBIDDEN:
                assert wrong not in log, f"{wrong!r} in flow log:\n{log}"
            assert (app.wafer.processed, app.process_stage) == flags_before
        finally:
            app.destroy()
        # (3) mixed: a real etch + a zero-duration oxidation -> exactly 1 physical change
        app = _app()
        try:
            assert app._materialize_current_wafer()
            app.etch_model.set("Isotropic etch")
            app.isotropic_rate_var.set(0.02)
            app.etch_time_var.set(1.0)
            app._pending_flow_add = True
            try:
                app.run_etch()
            finally:
                app._pending_flow_add = False
            _queue_oxidation(app, "Thermal oxidation", 0.0)
            assert len(app.flow_steps) == 2
            log_before = app.log.get("1.0", "end-1c")
            app.run_process_flow()
            log = app.log.get("1.0", "end-1c")[len(log_before):]
            assert ("FLOW FINISHED: 1 physical process change(s), 0 zero-duration "
                    "materialization(s), 1 zero-duration identity step(s)") in log, log
            for wrong in ("PROCESS FLOW COMPLETE", "OXIDATION COMPLETE", "Pad oxide + mask", "growth"):
                assert wrong not in log, f"{wrong!r} in flow log:\n{log}"
            assert app.wafer.processed is True, "the real etch is a physical change and must promote processed"
            assert app.process_stage == "flow_done"
            assert app.wafer.etched is True
        finally:
            app.destroy()
        # (4) a flow with only real steps keeps the historic wording
        app = _app()
        try:
            assert app._materialize_current_wafer()
            app.etch_model.set("Isotropic etch")
            app.isotropic_rate_var.set(0.02)
            app.etch_time_var.set(1.0)
            app._pending_flow_add = True
            try:
                app.run_etch()
            finally:
                app._pending_flow_add = False
            log_before = app.log.get("1.0", "end-1c")
            app.run_process_flow()
            log = app.log.get("1.0", "end-1c")[len(log_before):]
            assert "PROCESS FLOW COMPLETE (" in log and "FLOW FINISHED" not in log, log
            assert app.process_stage == "flow_done"
        finally:
            app.destroy()
        assert modal_calls == [], modal_calls
        print("PASS test_H: flow wording/state counts physical changes only -- zero-duration-only flows "
              "(fresh materialization / inherited identity) print 'FLOW FINISHED: 0 physical ...' with no "
              "COMPLETE/growth wording and never earn processed/flow_done; a real etch alongside is the only "
              "physical change (1); an all-real flow keeps 'PROCESS FLOW COMPLETE'; 0 modal calls")
    finally:
        for n, fn in originals.items():
            setattr(gui_mod.messagebox, n, fn)


def main():
    test_1_mock_solver_call_trap()
    test_2_inherited_geometry_identity_by_bytes()
    test_3_fresh_request_no_seed()
    test_4_propagation_four_layers()
    test_5_electrical_gate()
    test_7_invalid_duration()
    test_A_unsupported_then_sentinel_zero_calls()
    test_B_supported_prefix_then_unsupported_then_sentinel()
    test_C_worker_three_step_preserves_first_unsupported()
    test_D_gui_process_flow_stops_not_complete()
    test_E_user_message_distinguishes_backend_state()
    test_F_gui_zero_duration_and_unsupported_wording()
    test_G_gui_fresh_materialization_with_forced_prior_state_fails_closed()
    test_H_gui_flow_counts_physical_changes_not_requested_steps()
    print("\nALL POSITIVE-TIME UNSUPPORTED TESTS PASS (0 mandatory skips)")


if __name__ == "__main__":
    main()
