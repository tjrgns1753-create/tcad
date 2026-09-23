#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7C Rev.2 / 7D -- no implicit ACTIVE, exact reattach support, compensated transport fail-closed.

A. helper contract   the four apply_*_doping helpers have NO default activation state: omitting it is a TypeError, an explicit
                     ACTIVE / CHEMICAL / UNKNOWN is preserved, an invalid string is a ValueError; and no production call site omits it (AST scan --
                     it proves only that the keyword is written at every call, not what value the caller chose).
B. CLI contract      `tcad.cli.run_pipeline._apply_doping`: a doping config without `chemical_state` is rejected; ACTIVE for gaussian_implant /
                     implant_windows needs the explicit `profile_semantics: DIRECT_ANALYTIC_ACTIVE` as well; CHEMICAL/UNKNOWN are accepted and then
                     blocked by the DevSim gate; uniform / step_junction may declare ACTIVE.
C. compensated       canonical concentrations stay (N_D, N_A, N_D - N_A) but a finite-area donor + acceptor coexistence, or one whose relation
                     cannot be proven, makes the central DevSim gate (`canonical_node_doping` via `apply_doping`) raise UNSUPPORTED_BY_MODEL /
                     COMPENSATED_TRANSPORT_MODEL_MISSING: 0 DevSim writes, 0 solves. Single polarity and an ideal step junction (opposite sides)
                     stay supported. (Batch 7D: the step junction uses DEVSIM's own official step() convention -- Donors=Nd*step(x-xj),
                     Acceptors=Na*step(xj-x) -- so BOTH fire on the junction line; that line is measure-zero, not a finite area, so it is
                     correctly NOT compensated. Rev.2's strict one-sided junction was reverted per Codex: it changed a real device's current
                     ratio, which was mesh/discontinuity sensitivity, not a physical improvement.)
D. exact reattach    the request's desired support (current geometry + the same barrier carve as an application) must equal the attachment's
                     support EXACTLY -- subset, superset, another carve, unknown or outside support all fail; a geometry step that clips both
                     identically still matches. Judged through the real GUI run_doping(reattach=True) with the exact last_doped_result / history /
                     overlay change or non-change asserted.

Unit test: real TCADApplication (withdrawn), real run_doping/run_measurement, real recipe helpers, advance_wafer_state and WaferStateV2; DevSim is a
recording fake (real-device evidence: test_dopant_activation_devsim_gate_real.py).
"""
import ast
import contextlib
import io
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import tcad.device.devsim.doping_mapping as dm
import tcad.physics.wafer_state_v2 as v2
import importlib
from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult
from tcad.physics.doping import (
    apply_gaussian_implant_doping, apply_implant_windows_doping, apply_step_junction_doping, apply_uniform_doping,
)
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state_accumulation import advance_wafer_state, canonical_doping_request_matches

cli = importlib.import_module("tcad.cli.run_pipeline")
REASON = "COMPENSATED_TRANSPORT_MODEL_MISSING"
SI = (-2.0, 2.0, -1.0, 0.0)
PR = ProcessResult(volume_mesh_path="unused.vtu")
HELPERS = ("apply_uniform_doping", "apply_step_junction_doping", "apply_gaussian_implant_doping", "apply_implant_windows_doping")


def base():
    return v2.initialize_wafer_state(cells=[("Si", SI, "si#substrate")], grid_delta_um=0.2)


def raises(exc, fn, needle=None):
    try:
        fn()
    except exc as e:
        assert needle is None or needle in str(e), f"{type(e).__name__} message {str(e)!r} lacks {needle!r}"
        return str(e)
    raise AssertionError(f"expected {exc.__name__}, nothing was raised")


# ---------------------------------------------------------------------------------------------------- A. helpers
def part_a():
    calls = {
        "apply_uniform_doping": lambda **kw: apply_uniform_doping(PR, {"Si": 1e17}, **kw),
        "apply_step_junction_doping": lambda **kw: apply_step_junction_doping(PR, "Si", "x", 0.0, 1e17, 1e16, **kw),
        "apply_gaussian_implant_doping": lambda **kw: apply_gaussian_implant_doping(PR, "Si", "x", 0.0, 0.3, 1e17, **kw),
        "apply_implant_windows_doping": lambda **kw: apply_implant_windows_doping(PR, "Si", "x", 1e16, [{"min_um": 0.0, "max_um": 1.0, "conc_cm3": 1e17}], **kw),
    }
    for name, call in calls.items():
        raises(TypeError, lambda: call(), "chemical_state")                       # omitted -> nothing becomes ACTIVE
        for state in ("ACTIVE", "CHEMICAL", "UNKNOWN"):
            r = call(chemical_state=state)
            assert [x.chemical_state for x in r.doping.regions] == [state], (name, state)
            assert {p.chemical_state for p in dopant_profiles_from_doping_profile(r.doping)} == {state}, (name, state)
        raises(ValueError, lambda: call(chemical_state="active"), "chemical_state")
        raises(ValueError, lambda: call(chemical_state=None), "chemical_state")
    # static scan: every production call site writes the keyword (proves the keyword is present, not the value)
    bad, seen = [], 0
    for path in list((ROOT / "tcad").rglob("*.py")) + [ROOT / "tcad_2d_stagewise.py"] + list((ROOT / "examples").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in HELPERS:
                seen += 1
                if not any(k.arg == "chemical_state" for k in n.keywords):
                    bad.append(f"{path.relative_to(ROOT)}:{n.lineno}")
    assert not bad and seen >= 9, f"production call sites without chemical_state: {bad} (seen {seen})"
    print(f"A helpers: 4/4 raise TypeError when the state is omitted; explicit ACTIVE/CHEMICAL/UNKNOWN preserved; invalid -> ValueError; "
          f"{seen} production call sites all write the keyword")


# ---------------------------------------------------------------------------------------------------- B. CLI
CLI_CFG = {
    "uniform": {"kind": "uniform", "doping_by_region_cm3": {"Si": 1e17}},
    "step_junction": {"kind": "step_junction", "region": "Si", "junction_axis": "x", "junction_position_um": 0.0,
                      "donor_conc_cm3": 1e17, "acceptor_conc_cm3": 1e17},
    "gaussian_implant": {"kind": "gaussian_implant", "region": "Si", "junction_axis": "x", "peak_position_um": 0.0,
                         "straggle_um": 0.3, "peak_conc_cm3": 1e17},
    "implant_windows": {"kind": "implant_windows", "region": "Si", "axis": "x", "background_doping_cm3": 1e16,
                        "windows": [{"min_um": 0.5, "max_um": 1.5, "conc_cm3": 1e18}]},
}


def cli_apply(cfg):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        return cli._apply_doping(PR, cfg), err.getvalue()


def part_b():
    outcomes = {}
    for kind, cfg in CLI_CFG.items():
        raises(ValueError, lambda: cli._apply_doping(PR, dict(cfg)), "chemical_state")     # no state -> explicit rejection
        raises(ValueError, lambda: cli._apply_doping(PR, {**cfg, "chemical_state": "guess"}), "chemical_state")
        for bad_sem in ("DIRECT_ANALYTIC_ACTIVE",):
            raises(ValueError, lambda: cli._apply_doping(PR, {**cfg, "chemical_state": "CHEMICAL", "profile_semantics": bad_sem}), "profile_semantics")
        raises(ValueError, lambda: cli._apply_doping(PR, {**cfg, "chemical_state": "ACTIVE", "profile_semantics": "PROCESS"}), "profile_semantics")
        if kind in ("gaussian_implant", "implant_windows"):
            raises(ValueError, lambda: cli._apply_doping(PR, {**cfg, "chemical_state": "ACTIVE"}), "DIRECT_ANALYTIC_ACTIVE")   # bare ACTIVE refused
            for state in ("CHEMICAL", "UNKNOWN"):
                r, err = cli_apply({**cfg, "chemical_state": state})
                assert [x.chemical_state for x in r.doping.regions] == [state] and "DECLARED ANALYTIC ACTIVE" not in err
                s = advance_wafer_state(base(), r, "doping")
                assert s.attachments and all(a.chemical_state == state for a in s.attachments), state
                assert s.net_doping_at(1.0, -0.5).net_doping is None, "a chemical/unknown CLI implant must not be electrical"
                assert dm_blocked(s)[0], "the DevSim gate must block it"
            r, err = cli_apply({**cfg, "chemical_state": "ACTIVE", "profile_semantics": "DIRECT_ANALYTIC_ACTIVE"})
            assert r.doping.regions[0].chemical_state == "ACTIVE" and "DECLARED ANALYTIC ACTIVE PROFILE" in err and "not a simulated implant" in err, err
            outcomes[kind] = "no state -> rejected | bare ACTIVE -> rejected | CHEMICAL/UNKNOWN -> recorded + DevSim-blocked | ACTIVE + DIRECT_ANALYTIC_ACTIVE -> declared analytic"
        else:
            r, err = cli_apply({**cfg, "chemical_state": "ACTIVE"})
            assert r.doping.regions[0].chemical_state == "ACTIVE" and "DECLARED ANALYTIC ACTIVE PROFILE" in err, err
            r, _ = cli_apply({**cfg, "chemical_state": "CHEMICAL"})
            assert r.doping.regions[0].chemical_state == "CHEMICAL"
            outcomes[kind] = "no state -> rejected | ACTIVE -> declared analytic | CHEMICAL/UNKNOWN allowed"
    for kind, text in outcomes.items():
        print(f"B CLI {kind:16s}: {text}")


# ---------------------------------------------------------------------------------------------------- C. compensated transport
class FakeDevsim:
    def __init__(self, points):
        self.points, self.writes, self.solves = points, [], 0

    def get_node_model_values(self, device, region, name):
        return [p[0] if name == "x" else p[1] for p in self.points]

    def node_model(self, **k):
        self.writes.append(k.get("name"))

    def set_node_values(self, **k):
        self.writes.append(k.get("name"))

    def solve(self, **k):
        self.solves += 1

    def get_dimension(self, device):
        # Batch 7E: canonical_node_doping() now queries the real device
        # DIMENSION whenever a state carries an ACTIVE step_junction_v1
        # attachment (docs/audits/2026-09-21-batch7d-step-junction-convergence
        # /rev2). This FakeDevsim never modelled device geometry/dimension at
        # all before this gate existed, so "1" (not 2D) is the most honest
        # simulation of "this mock has no real device dimension" -- it keeps
        # this file's own step-junction "controls that must keep working"
        # section (C, testing the ACTIVE-declaration/compensation gates, NOT
        # 2D mesh convergence) testing exactly what it always tested, with
        # zero assertion changes.
        return 1


def dm_blocked(state, points=((-1.0, -0.5), (0.0, -0.5), (0.5, -0.25), (1.0, -0.25))):
    """(blocked?, reason_code, writes, solves, message) of the central gate on `state`."""
    fake = FakeDevsim(list(points))
    with patch.object(dm.backend, "require_devsim", lambda: fake):
        try:
            dm.apply_doping("dev", "Si", state)
            return False, None, fake.writes, fake.solves, ""
        except dm.UnsupportedDopingState as exc:
            return True, exc.physics_status.get("reason_code"), fake.writes, fake.solves, str(exc)


def active(kind_call):
    return advance_wafer_state(base(), kind_call, "doping")


def part_c():
    uni = lambda d, a, s="ACTIVE": apply_uniform_doping(PR, donor_by_region_cm3={"Si": d}, acceptor_by_region_cm3={"Si": a}, chemical_state=s)
    q = lambda s, x=0.0, y=-0.5: (lambda r: (r.donor_concentration, r.acceptor_concentration, r.net_doping))(s.net_doping_at(x, y))

    # uniform compensated: canonical values kept, transport blocked
    s = active(uni(1e17, 1e17))
    blocked, reason, writes, solves, msg = dm_blocked(s)
    assert q(s) == (1e17, 1e17, 0.0), q(s)
    assert blocked and reason == REASON and writes == [] and solves == 0, (blocked, reason, writes, solves)
    assert REASON in msg and "UNSUPPORTED_BY_MODEL" in msg
    print(f"C uniform ACTIVE 1e17/1e17: canonical donor/acceptor/net {q(s)}; gate -> blocked, reason_code {reason}, DevSim writes {len(writes)}, solves {solves}, no current")

    # Gaussian ACTIVE, same shape donor + acceptor (direct analytic fixture)
    g = apply_gaussian_implant_doping(PR, "Si", "x", 0.0, 0.3, donor_peak_conc_cm3=1e18, acceptor_peak_conc_cm3=1e18, chemical_state="ACTIVE")
    sg = active(g)
    b, rc, w, sv, _ = dm_blocked(sg)
    assert q(sg) == (1e18, 1e18, 0.0) and b and rc == REASON and w == [] and sv == 0, (q(sg), b, rc)
    print(f"C Gaussian ACTIVE donor=acceptor=1e18 (same support/shape): canonical {q(sg)}; blocked {rc}, writes {len(w)}, solves {sv}")

    # different shapes overlapping over a finite area: uniform acceptor background + Gaussian donor
    two = advance_wafer_state(active(uni(0.0, 1e16)), apply_gaussian_implant_doping(PR, "Si", "x", 0.0, 0.3, donor_peak_conc_cm3=1e18, chemical_state="ACTIVE"), "doping")
    b, rc, w, sv, _ = dm_blocked(two)
    assert b and rc == REASON and w == [] and sv == 0
    # an MOSFET-style counter-doped window over an acceptor body is a finite-area coexistence too
    win = apply_implant_windows_doping(PR, "Si", "x", background_doping_cm3=-1e17, windows=[{"min_um": 0.5, "max_um": 1.5, "conc_cm3": 1e20}], chemical_state="ACTIVE")
    sw = active(win)
    b, rc, w, sv, _ = dm_blocked(sw)
    assert b and rc == REASON and w == [] and sv == 0
    print("C different-shape overlap (uniform acceptor + Gaussian donor) and a counter-doped implant window over an acceptor body: blocked, writes 0, solves 0")

    # relation that cannot be proven: donor + acceptor whose model has no exact positive region
    def diag(polarity, state):
        return dict(species=None, polarity=polarity, chemical_state="ACTIVE", concentration_at=lambda x, y: 1e17, support_instance_id="si#substrate",
                    support_region_um=(-2.0, -1.0, -1.0, 0.0), model="diagnostic",
                    inventory_integral=v2.uniform_inventory_integral(1e17))
    sd = v2.attach_dopant(v2.attach_dopant(base(), step_seed="d", **diag("donor", 0)), step_seed="a", **diag("acceptor", 0))
    b, rc, w, sv, msg = dm_blocked(sd)
    assert b and rc == REASON and "cannot be proven" in msg and w == [] and sv == 0, msg
    print("C donor + acceptor of an unknown model: relation cannot be proven -> blocked (fail closed)")

    # controls that must keep working: single polarity, disjoint windows, ideal step junction
    s1 = active(uni(1e17, 0.0))
    b, rc, w, sv, _ = dm_blocked(s1)
    assert not b and sorted(set(w)) == ["Acceptors", "Donors", "NetDoping"], (b, w)
    disjoint = apply_implant_windows_doping(PR, "Si", "x", donor_background_cm3=0.0, acceptor_background_cm3=0.0, chemical_state="ACTIVE",
                                            windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1e19, "acceptor_conc_cm3": 0.0},
                                                     {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": 0.0, "acceptor_conc_cm3": 1e19}])
    b, rc, w, sv, _ = dm_blocked(active(disjoint))
    assert not b, "donor and acceptor windows on disjoint x-ranges are not a compensated region"
    step = apply_step_junction_doping(PR, "Si", "x", 0.0, 1e17, 1e17, chemical_state="ACTIVE")
    ss = active(step)
    assert [a.polarity for a in ss.attachments] == ["donor", "acceptor"]
    b, rc, w, sv, _ = dm_blocked(ss, points=((-1.0, -0.5), (0.0, -0.5), (1.0, -0.5)))
    assert not b and sorted(set(w)) == ["Acceptors", "Donors", "NetDoping"], (b, rc)
    # official DEVSIM step() convention (diode_common.py::SetNetDoping): BOTH fire on the
    # junction line itself (Donors=Nd, Acceptors=Na there), net = Nd-Na; this is a measure-zero
    # LINE, not a finite area, so it is correctly NOT flagged as a compensated region (below).
    on_junction, left, right = q(ss, 0.0), q(ss, -1.0), q(ss, 1.0)
    assert on_junction == (1e17, 1e17, 0.0), f"official step() convention: both polarities on the junction line, got {on_junction}"
    assert left == (0.0, 1e17, -1e17) and right == (1e17, 0.0, 1e17), (left, right)
    print(f"C controls: single polarity -> gate passes, {len(set(w))} DevSim models written; disjoint donor/acceptor windows pass; "
          f"ideal Step Junction 1e17/1e17 passes; at the junction x=0 donor/acceptor/net = {on_junction} (official step() convention, both fire), "
          f"left {left}, right {right}")

    # state-level analysis is pure and exact
    assert v2.compensated_transport_problems(s1, "Si") == [] and v2.compensated_transport_problems(ss, "Si") == []
    assert len(v2.compensated_transport_problems(s, "Si")) == 1 and v2.compensated_transport_problems(s, "SiO2") == []


# ---------------------------------------------------------------------------------------------------- D. exact reattach (GUI)
def part_d():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend as devsim_backend
    import tcad.device.devsim.mesh_import as mesh_import_mod

    app = gui.TCADApplication()
    real = (gui.build_process_result, gui.messagebox, devsim_backend.is_available, devsim_backend.require_devsim,
            mesh_import_mod.import_process_result, mesh_import_mod.derive_barrier_covered_windows)
    barrier = {"windows": []}
    try:
        app.withdraw()
        mesh_a, mesh_b = str(Path(__file__).resolve()), sys.executable
        gui.messagebox = SimpleNamespace(**{n: (lambda *a, **k: None) for n in ("showinfo", "showwarning", "showerror", "askyesno")})
        gui.build_process_result = lambda step_result: ProcessResult(volume_mesh_path=app.last_final_mesh)
        mesh_import_mod.derive_barrier_covered_windows = lambda *a, **k: list(barrier["windows"])

        def fresh(state=None):
            app.wafer_state = state if state is not None else base()
            app.last_final_mesh, app.last_doped_result = mesh_a, None
            app.history.clear()
            app.viewer_layer_var.set("geometry")
            app.doping_kind.set("Uniform")
            app.dope_uniform_region_var.set("Si")
            app.dope_uniform_donor_var.set("1e16")
            app.dope_uniform_acceptor_var.set("0")
            barrier["windows"] = []

        def apply_once(state=None):
            fresh(state)
            assert app.run_doping(silent=True) is True
            return app.last_doped_result

        def reattach(expect, label):
            """One reattach on a stale result: assert the EXACT last_doped_result / history / overlay change (True) or non-change (False)."""
            # a later step moved the mesh on: point the current mesh at a path the last result is NOT bound to
            app.last_final_mesh = mesh_b if getattr(app.last_doped_result, "volume_mesh_path", None) != mesh_b else mesh_a
            assert app._doping_is_stale()
            res0, hist0, layer0, atts0 = app.last_doped_result, list(app.history), app.viewer_layer_var.get(), tuple(app.wafer_state.attachments)
            app.viewer_layer_var.set("geometry")
            layer0 = "geometry"
            ret = app.run_doping(silent=True, reattach=True)
            assert tuple(app.wafer_state.attachments) == atts0, f"{label}: a reattach must never change the attachments"
            if expect:
                assert ret is True, f"{label}: expected a successful reattach, got {ret!r}"
                assert app.last_doped_result is not res0 and app.last_doped_result is not None, f"{label}: last_doped_result must be refreshed"
                assert app.history == hist0 + ["Doping: Uniform"], f"{label}: history {app.history}"
                assert app.viewer_layer_var.get() == "doping", f"{label}: overlay must switch to doping"
            else:
                assert ret is False, f"{label}: expected a refused reattach, got {ret!r}"
                assert app.last_doped_result is res0, f"{label}: last_doped_result must be UNCHANGED"
                assert app.history == hist0, f"{label}: history must be unchanged: {app.history}"
                assert app.viewer_layer_var.get() == layer0, f"{label}: overlay must be unchanged"
            return ret

        results = []
        # 1. exactly the same support -> success
        apply_once()
        reattach(True, "1 same support")
        results.append("1 same support: True (result refreshed, history +1, overlay doping)")

        # 2. the attachment is a strict SUBSET of the requested support -> failure
        fresh()
        att = dict(species=None, polarity="donor", chemical_state="ACTIVE", concentration_at=lambda x, y: 1e16, support_instance_id="si#substrate",
                   model="uniform_v1", model_params={"conc_cm3": 1e16}, inventory_integral=v2.uniform_inventory_integral(1e16))
        sub = v2.attach_dopant(base(), support_region_um=(-2.0, 0.0, -1.0, 0.0), **att)
        fresh(sub)
        app.last_doped_result = SimpleNamespace(volume_mesh_path=mesh_a, doping=SimpleNamespace(kind="uniform", regions=[SimpleNamespace(region="Si")]))
        reattach(False, "2 strict subset")
        results.append("2 attachment = strict subset of the requested support: False (all unchanged)")

        # 3. the attachment is a strict SUPERSET of the requested support (the cell shrank, the attachment did not) -> failure
        full = v2.attach_dopant(base(), support_region_um=SI, **att)
        shrunk = replace(full, cells=tuple(replace(c, bounds_um=(-2.0, 2.0, -1.0, -0.3)) for c in full.cells))
        fresh(shrunk)
        app.last_doped_result = SimpleNamespace(volume_mesh_path=mesh_a, doping=SimpleNamespace(kind="uniform", regions=[SimpleNamespace(region="Si")]))
        reattach(False, "3 strict superset")
        results.append("3 attachment = strict superset of the requested support: False (all unchanged)")

        # 4. same concentration and model, different barrier carve -> failure; the same carve -> success
        fresh()
        barrier["windows"] = [{"min_um": 1.0, "max_um": 2.0}]
        assert app.run_doping(silent=True) is True
        assert [a.support_region_um for a in app.wafer_state.attachments] == [(-2.0, 1.0, -1.0, 0.0)], app.wafer_state.attachments
        reattach(True, "4a same carve")
        barrier["windows"] = [{"min_um": 1.5, "max_um": 2.0}]
        reattach(False, "4b different carve")
        barrier["windows"] = []
        reattach(False, "4c no carve")
        results.append("4 same barrier carve: True; another carve: False; no carve: False")

        # 5. after a geometry step clipped the cell AND the attachment identically the two are equal again -> success
        apply_once()
        etch = v2.GeometryTransform(process_category="etching", representable=True, removed_extents_um=((-2.0, 2.0, -0.3, 0.0),),
                                    input_instance_ids=("si#substrate",))
        app.wafer_state = advance_wafer_state(app.wafer_state, None, "etching", etch)
        cells = [c.bounds_um for c in app.wafer_state.active_cells()]
        atts = [a.support_region_um for a in app.wafer_state.attachments]
        assert cells == [(-2.0, 2.0, -1.0, -0.3)] and atts == cells, (cells, atts)
        reattach(True, "5 clipped geometry")
        results.append(f"5 geometry clipped (cell {cells[0]}, attachment {atts[0]}): True")

        # 6. support None / outside the geometry -> failure
        apply_once()
        none_sup = replace(app.wafer_state, attachments=tuple(replace(a, support_region_um=None) for a in app.wafer_state.attachments))
        app.wafer_state = none_sup
        reattach(False, "6a support None")
        apply_once()
        app.wafer_state = replace(app.wafer_state, attachments=tuple(replace(a, support_region_um=(5.0, 6.0, -1.0, 0.0)) for a in app.wafer_state.attachments))
        reattach(False, "6b support outside the geometry")
        results.append("6 support None / outside the geometry: False (both)")
        for r in results:
            print("D reattach " + r)
    finally:
        (gui.build_process_result, gui.messagebox, devsim_backend.is_available, devsim_backend.require_devsim,
         mesh_import_mod.import_process_result, mesh_import_mod.derive_barrier_covered_windows) = real
        app.destroy()


def main():
    part_a()
    part_b()
    part_c()
    part_d()
    print("BATCH 7C REV.2 / 7D CONTRACT: no implicit ACTIVE (helpers + CLI), compensated transport fail-closed at the central gate, "
          "ideal step junction uses DEVSIM's official step() convention (both polarities on the junction LINE, not compensated), "
          "reattach compares the exact desired support")


if __name__ == "__main__":
    main()
