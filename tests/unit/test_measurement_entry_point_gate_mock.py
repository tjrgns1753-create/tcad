#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1-1 supplement: user entry points driven with an UNSUPPORTED
canonical state must never reach their characterization function.

Per entry point, with an unsupported canonical WaferStateV2:
  - the characterization function is called 0 times,
  - DevSim solve is called 0 times and no doping node model is written,
  - UNSUPPORTED_BY_MODEL surfaces: the GUI logs the blocked message (with
    the first blocked node) and returns None; the CLI lets
    UnsupportedDopingState propagate out of run_pipeline(),
  - the imported DevSim device is still cleaned up.
A supported control per entry point proves the same wiring DOES call the
characterization once the gate passes, so "0 calls" cannot be an
artifact of an earlier crash.

Covered here: GUI run_dc_operating_point, CLI run_pipeline pn_junction_iv,
CLI run_pipeline mos_cv. GUI run_measurement (both the implant-windows
robust branch and the apply_doping branch) is covered against real
DevSim by tests/integration/test_measurement_canonical_state_gate_real.py.

The DevSim module and the characterization functions are recorders; the
gate, the GUI/CLI orchestration and the canonical-state construction all
run for real. The CLI's process step, doping-profile attachment and mesh
import are replaced (they need ViennaPS meshes); _apply_device_doping's
canonical-state threading still runs unmodified.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.device.devsim import backend  # noqa: E402
from tcad.device.devsim.doping_mapping import UnsupportedDopingState  # noqa: E402
from tcad.mesh.interface import DopingProfile, DopingRegion  # noqa: E402
from tcad.physics import wafer_state_v2 as v2  # noqa: E402

UM_TO_CM = 1.0e-4
SI = (-2.0, 2.0, -2.0, 0.0)


class FakeDevsim:
    def __init__(self, xs_um, ys_um):
        self._nodes = {"x": [x * UM_TO_CM for x in xs_um], "y": [y * UM_TO_CM for y in ys_um]}
        self.doping_writes = []
        self.solves = 0
        self.deleted = []

    def get_node_model_values(self, device, region, name):
        return list(self._nodes[name])

    def node_model(self, device, region, name, equation):
        self.doping_writes.append(name)

    def set_node_values(self, device, region, name, values):
        self.doping_writes.append(name)
        self._nodes[name] = list(values)

    def solve(self, **kwargs):
        self.solves += 1

    def delete_device(self, device):
        self.deleted.append(("device", device))

    def delete_mesh(self, mesh):
        self.deleted.append(("mesh", mesh))

    def get_dimension(self, device):
        # Batch 7E Rev.1: canonical_node_doping() queries the real device
        # dimension only when a state carries an ACTIVE step_junction_v1
        # attachment. Every case in this file before Batch 7E used no such
        # attachment, so this method was never needed before and its
        # presence changes nothing for them (short-circuited).
        return 2


class Recorder:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    return lambda: setattr(obj, name, original)


def _virgin_doped():
    state = v2.initialize_wafer_state(cells=[("Si", SI, "si#0")])
    return v2.attach_dopant(
        state, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=v2.uniform_inventory_integral(1.0e17),
        support_instance_id="si#0", support_region_um=SI,
        model="uniform_v1", model_params={"conc_cm3": 1.0e17}, chemical_state="ACTIVE")


def _step_junction_2d_doped():
    """Batch 7E Rev.1 item 5: an ACTIVE step_junction_v1 attachment (the
    official DEVSIM step() convention -- donor x>=0, acceptor x<=0), the
    SAME `model` tag `_step_junction_profiles()` produces in production."""
    state = v2.initialize_wafer_state(cells=[("Si", SI, "si#0")])
    state = v2.attach_dopant(
        state, species="P", polarity="donor", chemical_state="ACTIVE",
        concentration_at=lambda x, y: 1.0e17 if x >= 0.0 else 0.0,
        inventory_integral=v2.uniform_inventory_integral(1.0e17),
        support_instance_id="si#0", support_region_um=SI,
        model="step_junction_v1", model_params={"conc_cm3": 1.0e17, "junction_position_um": 0.0},
        step_seed="sjd")
    state = v2.attach_dopant(
        state, species="B", polarity="acceptor", chemical_state="ACTIVE",
        concentration_at=lambda x, y: 1.0e17 if x <= 0.0 else 0.0,
        inventory_integral=v2.uniform_inventory_integral(1.0e17),
        support_instance_id="si#0", support_region_um=SI,
        model="step_junction_v1", model_params={"conc_cm3": 1.0e17, "junction_position_um": 0.0},
        step_seed="sja")
    return state


UNSUPPORTED_STATES = {
    "no canonical state": (lambda: None, [(-1.0, -1.0), (1.0, -1.0)]),
    "anneal fail-closed": (lambda: v2.advance(_virgin_doped(), None, step_seed="anneal"),
                           [(-1.0, -1.0), (1.0, -1.0)]),
    "node outside every cell": (_virgin_doped, [(-1.0, -1.0), (3.0, -1.0)]),
}


# ---------------------------------------------------------------------------
# GUI run_dc_operating_point
# ---------------------------------------------------------------------------

def _dc_operating_point(app, state, nodes):
    import tcad.characterization.dc_operating_point as dcop
    from tcad.mesh.pin import Pin

    fake = FakeDevsim(*zip(*nodes))
    recorder = Recorder(SimpleNamespace(currents={"Source": -1.0e-6, "Drain": 1.0e-6, "Gate": 0.0}))
    app.wafer_state = state
    app.last_physics_status = None
    app.electrode_pins = [Pin(name="Source", role="Source", x_um=1.0, y_um=0.0),
                          Pin(name="Drain", role="Drain", x_um=3.0, y_um=0.0),
                          Pin(name="Gate", role="Gate", x_um=2.0, y_um=0.1)]
    app._electrode_contact_regions = {"Source": "Si", "Drain": "Si", "Gate": "SiO2"}
    app.last_electrode_import = SimpleNamespace(
        device="dc_dev", mesh="dc_mesh", contacts=["Source", "Drain", "Gate"],
        interfaces=["Si_SiO2_interface"])
    log_before = app.log.get("1.0", "end-1c")
    restores = [_patched(dcop, "solve_mosfet_dc_operating_point", recorder),
                _patched(backend, "require_devsim", lambda: fake)]
    try:
        out = app.run_dc_operating_point(drain_voltage=0.1, gate_voltage=1.0)
    finally:
        for restore in restores:
            restore()
    return out, recorder, fake, app.log.get("1.0", "end-1c")[len(log_before):]


def _check(failures, label, fn):
    """Run one case; record a failure instead of stopping, so every case
    of an entry point is reported."""
    try:
        fn()
    except Exception as exc:
        failures.append(label)
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
    else:
        print(f"PASS {label}")


def test_gui_dc_operating_point():
    import tcad_2d_stagewise as gui

    app = gui.TCADApplication()
    app.withdraw()
    failures = []
    try:
        for label, (make_state, nodes) in UNSUPPORTED_STATES.items():
            def blocked(make_state=make_state, nodes=nodes, label=label):
                out, recorder, fake, log = _dc_operating_point(app, make_state(), nodes)
                assert recorder.calls == [], f"solve_mosfet_dc_operating_point called {len(recorder.calls)} time(s)"
                assert out is None
                assert fake.solves == 0 and fake.doping_writes == [], (fake.solves, fake.doping_writes)
                assert app.last_physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
                assert "UNSUPPORTED_BY_MODEL" in log and "DC operating point blocked" in log, log
                assert "First blocked node: x=" in log, log
                assert fake.deleted == [("device", "dc_dev"), ("mesh", "dc_mesh")], fake.deleted
                assert app.last_electrode_import is None

            _check(failures, f"GUI DC operating point blocked [{label}]", blocked)

        def supported():
            out, recorder, fake, log = _dc_operating_point(app, _virgin_doped(), [(-1.0, -1.0), (1.0, -0.5)])
            assert out is not None and len(recorder.calls) == 1, log
            assert fake._nodes["NetDoping"] == [1.0e17, 1.0e17]
            assert "UNSUPPORTED_BY_MODEL" not in log

        _check(failures, "GUI DC operating point supported control", supported)

        def step_junction_2d_blocked():
            # A 2D ACTIVE step_junction_v1 state -- geometry/ownership/
            # activation all pass, so this exercises the SAME
            # `app.run_dc_operating_point()` real method end to end as every
            # other case above, blocked for the NEW region-level reason
            # (not "no state" / "node outside every cell" like
            # UNSUPPORTED_STATES): STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED.
            out, recorder, fake, log = _dc_operating_point(
                app, _step_junction_2d_doped(), [(-1.0, -1.0), (1.0, -0.5)])
            assert recorder.calls == [], f"solve_mosfet_dc_operating_point called {len(recorder.calls)} time(s)"
            assert out is None
            assert fake.solves == 0 and fake.doping_writes == [], (fake.solves, fake.doping_writes)
            assert app.last_physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
            assert app.last_physics_status["reason_code"] == "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED", \
                app.last_physics_status
            assert "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED" in log and "DC operating point blocked" in log, log
            # numeric DC result: 0 -- "currents=" only ever appears in the
            # SUCCESS log line (run_dc_operating_point's own f"currents=
            # {op_point.currents}"), never in the blocked-exception path.
            assert "currents=" not in log, f"a numeric DC result leaked into the log: {log}"
            assert fake.deleted == [("device", "dc_dev"), ("mesh", "dc_mesh")], fake.deleted
            assert app.last_electrode_import is None

        _check(failures, "GUI DC operating point blocked [2D ACTIVE step_junction_v1]", step_junction_2d_blocked)
    finally:
        app.destroy()
    return failures


# ---------------------------------------------------------------------------
# CLI run_pipeline: pn_junction_iv and mos_cv
# ---------------------------------------------------------------------------

CHARACTERIZATIONS = {
    "pn_junction_iv": ("tcad.characterization.pn_junction_iv_sweep", "run_pn_junction_iv_sweep", {
        "type": "pn_junction_iv", "region": "Si", "sweep_contact": "Si_xmax",
        "sweep_voltages": [0.1], "fixed_contacts": {"Si_xmin": 0.0}}),
    "mos_cv": ("tcad.characterization.cv_sweep", "run_mos_cv_sweep", {
        "type": "mos_cv", "si_region": "Si", "oxide_region": "SiO2", "gate_contact": "gate",
        "substrate_contact": "substrate", "interface_name": "Si_SiO2", "gate_voltages": [0.0]}),
}
RECIPE = {"x_extent_um": 4.0, "silicon_depth_um": 2.0, "grid_delta_um": 0.1}


def _run_cli(kind, process_cfg, doping_cfg, nodes):
    import importlib

    import tcad.cli.run_pipeline as rp

    module_name, function_name, characterization = CHARACTERIZATIONS[kind]
    fake = FakeDevsim(*zip(*nodes))
    recorder = Recorder(SimpleNamespace(name=kind))
    doping = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=1.0e17, chemical_state="ACTIVE")])
    restores = [
        _patched(importlib.import_module(module_name), function_name, recorder),
        _patched(backend, "require_devsim", lambda: fake),
        _patched(rp, "_run_process_step", lambda cfg, workdir: {"final_mesh": None}),
        _patched(rp, "_build_process_result", lambda step: SimpleNamespace(doping=None, material_regions=[])),
        _patched(rp, "_apply_doping", lambda result, cfg: SimpleNamespace(
            doping=doping if cfg else None, material_regions=[])),
        _patched(rp, "_import_device", lambda result, cfg: SimpleNamespace(
            device="cli_dev", mesh="cli_mesh", contacts=["Si_xmin", "Si_xmax"], interfaces=[])),
        _patched(rp, "_save_outputs", lambda result, cfg, workdir: {}),
    ]
    config = {"process": process_cfg, "device": {"length_scale_to_cm": UM_TO_CM},
              "characterization": characterization}
    if doping_cfg:
        config["doping"] = doping_cfg
    raised = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rp.run_pipeline(config, Path(tmp))
    except UnsupportedDopingState as exc:
        raised = exc
    finally:
        for restore in reversed(restores):
            restore()
    return raised, recorder, fake


def test_cli_pipeline_characterizations():
    inside = [(-1.0, -1.0), (1.0, -1.0)]
    outside = [(-1.0, -1.0), (3.0, -1.0)]
    uniform = {"kind": "uniform", "doping_by_region_cm3": {"Si": 1.0e17}}
    etch = {"category": "etching", "model": "isotropic", "recipe": RECIPE}
    # No process category: only reachable because _run_process_step is
    # replaced -- a real CLI config always names one, and every real CLI
    # process step fail-closes the canonical state today.
    no_step = {"model": "none", "recipe": RECIPE}
    failures = []
    for kind in CHARACTERIZATIONS:
        for label, process_cfg, doping_cfg, nodes in (
            ("doping on a fail-closed process step", etch, uniform, inside),
            ("no doping configured", etch, None, inside),
            ("node outside every cell", no_step, uniform, outside),
        ):
            def blocked(kind=kind, process_cfg=process_cfg, doping_cfg=doping_cfg, nodes=nodes):
                raised, recorder, fake = _run_cli(kind, process_cfg, doping_cfg, nodes)
                assert recorder.calls == [], f"characterization called {len(recorder.calls)} time(s)"
                assert isinstance(raised, UnsupportedDopingState), "no explicit UnsupportedDopingState"
                assert "UNSUPPORTED_BY_MODEL" in str(raised) and "First blocked node" in str(raised), str(raised)
                assert fake.solves == 0 and fake.doping_writes == [], fake.doping_writes
                assert fake.deleted == [("device", "cli_dev"), ("mesh", "cli_mesh")], fake.deleted

            _check(failures, f"CLI {kind} blocked [{label}]", blocked)

        def supported(kind=kind):
            raised, recorder, fake = _run_cli(kind, no_step, uniform, inside)
            assert raised is None and len(recorder.calls) == 1, raised
            assert fake._nodes["NetDoping"] == [1.0e17, 1.0e17]

        _check(failures, f"CLI {kind} supported control", supported)
    return failures


def main():
    failures = test_gui_dc_operating_point() + test_cli_pipeline_characterizations()
    if failures:
        raise SystemExit(f"{len(failures)} entry-point case(s) failed: {failures}")
    print("Entry-point gate: GUI DC operating point and CLI pn_junction_iv / mos_cv never reach "
          "their characterization with an unsupported canonical state; supported controls do.")


if __name__ == "__main__":
    main()
