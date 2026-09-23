#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7C -- the dopant activation gate on a REAL DevSim device (real ViennaPS mesh, real DevSim, the real GUI measurement path).

A canonical WaferStateV2 is built by the real advance_wafer_state() from a real recipe helper that DECLARES the activation state:
  * ACTIVE   -> the measurement runs: DevSim Donors/Acceptors/NetDoping are written from the canonical query, devsim.solve runs, a current is
                reported (control).
  * CHEMICAL -> the canonical query is None/UNSUPPORTED_BY_MODEL, so the central gate blocks the measurement: 0 DevSim doping writes, 0
  * UNKNOWN     devsim.solve calls, no current, UNSUPPORTED_BY_MODEL with the activation-state reason in the log, canonical state unchanged.
  * ACTIVE single polarity control (N_D or N_A only) runs a real PN solve.
  * An ACTIVE ideal Step Junction (donor on one side, acceptor on the other, both fire on the junction node itself per DEVSIM's own official
    step() convention -- diode_common.py::SetNetDoping -- since that line is measure-zero, not a finite area) is now BLOCKED on this 2D device
    (Batch 7E): reason_code STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED. Batch 7D Rev.2's own real L0-L5 mesh-refinement study
    (docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2) found the 2D step-junction terminal current, peak ElectricField and R1/R2
    representation agreement do not converge -- so this device no longer solves; the canonical donor/acceptor/net concentration stays real and
    directly queryable (state.net_doping_at()), only 2D DevSim transport is refused. (A real 1D reference device DOES converge, but that is not
    generalized as 2D production capability -- see tests/integration/test_step_junction_2d_gate_real.py for that control.)
  * A compensated ACTIVE profile (N_D == N_A != 0) keeps its CANONICAL concentrations (donor N_D, acceptor N_A, net N_D - N_A = 0), but a finite
    area holding both polarities has no compensation-aware ionized-impurity scattering / mobility in the drift-diffusion model, so the central gate
    blocks it: reason_code COMPENSATED_TRANSPORT_MODEL_MISSING, 0 DevSim doping writes, 0 devsim.solve calls, no current. (Batch 7C Rev.2: this
    replaces the earlier assertion that a 2.4e-9 A current was reported for the compensated device -- that number was never a validated current.)

The counting is pass-through observation of the real devsim.solve / node_model / set_node_values; nothing DevSim is mocked. The one temporary
geometry-only mesh->device import that precedes the canonical gate is observed and reported, not treated as an authorization.
False-green guards at the end prove each check fails, for its own reason, when its subject is broken.
"""
import os
import re
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
warnings.simplefilter("ignore")

import tkinter  # noqa: F401,E402
import tcad_2d_stagewise as gui  # noqa: E402
from tcad.device.devsim import backend as devsim_backend  # noqa: E402
from tcad.device.devsim import mesh_import  # noqa: E402
from tcad.mesh.viennaps_adapter import build_process_result  # noqa: E402
from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping  # noqa: E402
from tcad.physics.wafer_state_accumulation import advance_wafer_state  # noqa: E402

DOPING_MODELS = {"Donors", "Acceptors", "NetDoping"}
REASON = "COMPENSATED_TRANSPORT_MODEL_MISSING"
MESSAGEBOX = ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel")


class DevsimObserver:
    """Pass-through recorder on the real devsim module (the real call still happens) plus the mesh->device import."""

    def __init__(self, devsim):
        self.devsim, self.solves, self.writes, self.values, self.imports = devsim, 0, [], {}, 0
        self.x = None
        self._orig = {}

    def install(self):
        d = self.devsim
        for n in ("solve", "node_model", "set_node_values"):
            self._orig[n] = getattr(d, n)
        o = dict(self._orig, get_x=d.get_node_model_values)

        def solve(*a, **k):
            self.solves += 1
            return o["solve"](*a, **k)

        def node_model(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.writes.append(("node_model", k.get("name")))
            return o["node_model"](*a, **k)

        def set_node_values(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.writes.append(("set_node_values", k.get("name")))
                self.values[k["name"]] = list(k.get("values", []))
                self.x = list(o["get_x"](device=k["device"], region=k["region"], name="x"))
            return o["set_node_values"](*a, **k)

        d.solve, d.node_model, d.set_node_values = solve, node_model, set_node_values
        self._orig_import = mesh_import.import_process_result

        def counted(*a, **k):
            self.imports += 1
            return self._orig_import(*a, **k)

        mesh_import.import_process_result = counted

    def restore(self):
        for n, fn in self._orig.items():
            setattr(self.devsim, n, fn)
        mesh_import.import_process_result = self._orig_import


def measure(app, devsim, modal, state, doped):
    """One real GUI MEASURE on the canonical `state` that the real recipe/advance path produced for `doped`."""
    app.wafer_state, app.last_doped_result = state, doped
    obs = DevsimObserver(devsim)
    log0, modal0, hist0 = app.log.get("1.0", "end-1c"), len(modal), len(app.history)
    obs.install()
    try:
        app.run_measurement()
    finally:
        obs.restore()
    return {
        "log": app.log.get("1.0", "end-1c")[len(log0):], "solves": obs.solves, "writes": obs.writes, "values": obs.values, "x": obs.x, "imports": obs.imports,
        "modal": len(modal) - modal0, "history_added": len(app.history) - hist0, "leaked": list(devsim.get_device_list()),
        "state_unchanged": app.wafer_state is state, "status": app.last_physics_status if isinstance(app.last_physics_status, dict) else None,
    }


def check_active(m, donor, acceptor):
    assert m["solves"] >= 1, f"ACTIVE control: devsim.solve must run, got {m['solves']}"
    assert sorted(set(n for _, n in m["writes"])) == ["Acceptors", "Donors", "NetDoping"], f"ACTIVE control: DevSim writes {m['writes']}"
    assert set(m["values"]["Donors"]) == {donor} and set(m["values"]["Acceptors"]) == {acceptor}, \
        f"Donors/Acceptors written must equal the requested values: {set(m['values']['Donors'])} / {set(m['values']['Acceptors'])}"
    assert set(m["values"]["NetDoping"]) == {donor - acceptor}, f"NetDoping is derived (N_D - N_A): {set(m['values']['NetDoping'])}"
    assert re.search(r"I = [-+0-9.eE]+ A", m["log"]), f"ACTIVE control: a current must be reported:\n{m['log'][-600:]}"
    assert "UNSUPPORTED_BY_MODEL" not in m["log"], "ACTIVE control must not be blocked"
    assert m["modal"] == 0 and not m["leaked"], m


def _blocked_common(m, label):
    assert m["writes"] == [], f"{label}: {len(m['writes'])} DevSim doping write(s) {sorted(set(m['writes']))}, expected 0"
    assert m["solves"] == 0, f"{label}: devsim.solve was called {m['solves']} time(s), expected 0"
    assert not re.search(r"I = [-+0-9.eE]+ A", m["log"]), f"{label}: a terminal current was reported"
    assert "UNSUPPORTED_BY_MODEL" in m["log"], f"{label}: UNSUPPORTED_BY_MODEL is not shown:\n{m['log'][-800:]}"
    counts = re.search(r"(\d+) of (\d+) mesh node\(s\) blocked", m["log"])
    assert counts and counts.group(1) == counts.group(2) and int(counts.group(1)) > 0, f"{label}: blocked/total node counts: {m['log'][-800:]}"
    assert m["state_unchanged"] and m["history_added"] == 0 and m["modal"] == 0 and not m["leaked"], m


def check_blocked(m, state_name):
    _blocked_common(m, state_name)
    assert "dopant_activation_state" in str(m["status"]) or f"chemical_state '{state_name}'" in m["log"], \
        f"{state_name}: the log/status must name the activation state as the reason:\n{m['log'][-800:]}"


def check_compensated_blocked(m, label, canonical, expected_canonical):
    """Concentration preservation is separate from transport capability."""
    _blocked_common(m, label)
    status = m["status"] or {}
    assert status.get("reason_code") == REASON, f"{label}: physics_status.reason_code is {status.get('reason_code')!r}, expected {REASON!r}"
    assert status.get("resolution") == "UNSUPPORTED_BY_MODEL", status
    assert REASON in m["log"], f"{label}: {REASON} is not in the GUI log:\n{m['log'][-800:]}"
    assert canonical == expected_canonical, f"{label}: the canonical donor/acceptor/net must be preserved: {canonical} != {expected_canonical}"


STEP_2D_REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"


def check_step_junction_2d_blocked(m, canonical_right, canonical_left, donor, acceptor):
    """Batch 7E: an ACTIVE step_junction_v1 attachment on THIS 2D device is
    now refused by the central gate before any doping write or solve --
    Batch 7D Rev.2's own real L0-L5 mesh-refinement study found the 2D
    step-junction terminal current, peak ElectricField and R1/R2
    representation agreement do not converge. `canonical_right`/`_left` are
    the caller's own direct `state.net_doping_at()` query results (donor,
    acceptor) either side of the junction -- proving the canonical
    concentration itself is untouched by this gate, exactly like the
    compensated-region case above."""
    _blocked_common(m, "ACTIVE step junction (2D)")
    status = m["status"] or {}
    assert status.get("reason_code") == STEP_2D_REASON, f"physics_status.reason_code is {status.get('reason_code')!r}, expected {STEP_2D_REASON!r}"
    assert status.get("resolution") == "UNSUPPORTED_BY_MODEL", status
    assert STEP_2D_REASON in m["log"], f"{STEP_2D_REASON} is not in the GUI log:\n{m['log'][-800:]}"
    assert canonical_right == (donor, 0.0) and canonical_left == (0.0, acceptor), \
        f"the canonical donor/acceptor must be preserved on both sides of the junction: right={canonical_right}, left={canonical_left}"


def expect_fail(check, label, expected):
    try:
        check()
    except AssertionError as exc:
        assert expected in str(exc), f"WRONG FAILURE REASON for guard {label!r}: expected {expected!r} in {str(exc)[:300]!r}"
        print(f"    [guard OK] {label}: fails for the expected reason ({str(exc).splitlines()[0][:90]})")
        return
    raise AssertionError(f"FALSE GREEN: guard {label!r} was accepted")


def main():
    devsim = devsim_backend.require_devsim()
    modal = []
    originals = {n: getattr(gui.messagebox, n) for n in MESSAGEBOX if hasattr(gui.messagebox, n)}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, _n=n, **k: modal.append(_n))
    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.wafer.width_um, app.wafer.silicon_depth_um = 4.0, 1.0
        app.grid_var.set(0.2)
        app.meas_voltage_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        assert app._materialize_current_wafer(), "materializing the wafer failed"
        base_state, mesh = app.wafer_state, app.last_final_mesh
        assert {c.lifecycle for c in base_state.cells} == {"ACTIVE"}, "the base state must be an exact MODELLED wafer"
        process_result = build_process_result({"final_mesh": mesh, "snapshots": []})

        def declared(donor, acceptor, state):
            doped = apply_uniform_doping(process_result, donor_by_region_cm3={"Si": donor}, acceptor_by_region_cm3={"Si": acceptor}, chemical_state=state)
            return advance_wafer_state(base_state, doped, "doping"), doped

        results = {}
        for name, donor, acceptor in (("ACTIVE", 1e16, 0.0), ("ACTIVE compensated", 1e17, 1e17), ("CHEMICAL", 1e16, 0.0), ("UNKNOWN", 1e16, 0.0)):
            state, doped = declared(donor, acceptor, name.split()[0])
            assert [a.chemical_state for a in state.attachments] == [name.split()[0]] * len(state.attachments) and len(state.attachments) == (2 if acceptor else 1), \
                [a.chemical_state for a in state.attachments]
            m = measure(app, devsim, modal, state, doped)
            results[name] = m
            if name == "ACTIVE":
                check_active(m, donor, acceptor)
                cur = re.search(r"I = ([-+0-9.eE]+) A", m["log"]).group(1)
                print(f"[{name}] single-polarity control, donor/acceptor {donor:g}/{acceptor:g}: devsim.solve {m['solves']}, DevSim writes {sorted(set(n for _, n in m['writes']))} "
                      f"(Donors {sorted(set(m['values']['Donors']))}, Acceptors {sorted(set(m['values']['Acceptors']))}, NetDoping {sorted(set(m['values']['NetDoping']))}), "
                      f"current reported {cur} A, geometry-only imports observed {m['imports']}")
            elif name == "ACTIVE compensated":
                q = state.net_doping_at(0.0, -0.5)
                canonical = (q.donor_concentration, q.acceptor_concentration, q.net_doping)
                check_compensated_blocked(m, name, canonical, (donor, acceptor, donor - acceptor))
                print(f"[{name}] canonical donor/acceptor/net {canonical} (preserved) -> measurement blocked: reason_code {m['status']['reason_code']}, "
                      f"DevSim doping writes {len(m['writes'])}, devsim.solve {m['solves']}, no current; geometry-only imports observed {m['imports']}; "
                      f"canonical state unchanged, modal calls {m['modal']}, leaked devices {m['leaked']}")
            else:
                check_blocked(m, name)
                n_blocked = re.search(r"(\d+ of \d+ mesh node\(s\) blocked)", m["log"]).group(1)
                print(f"[{name}] canonical query None/None/None -> measurement blocked: DevSim doping writes {len(m['writes'])}, devsim.solve {m['solves']}, "
                      f"no current, {n_blocked}, reason names the activation state; geometry-only imports observed {m['imports']}; "
                      f"canonical state unchanged, modal calls {m['modal']}, leaked devices {m['leaked']}")
        # ideal Step Junction on this 2D device: BLOCKED (Batch 7E) -- donor
        # on one side, acceptor on the other (opposite sides, NOT a
        # compensated region), but 2D step-junction mesh convergence is
        # unverified (Batch 7D Rev.2), so no DevSim doping write or solve
        # happens; the canonical donor/acceptor stays queryable directly.
        step = apply_step_junction_doping(process_result, region="Si", junction_axis="x", junction_position_um=0.0,
                                          donor_conc_cm3=1e17, acceptor_conc_cm3=1e17, chemical_state="ACTIVE")
        step_state = advance_wafer_state(base_state, step, "doping")
        assert [a.polarity for a in step_state.attachments] == ["donor", "acceptor"], [a.polarity for a in step_state.attachments]
        m = measure(app, devsim, modal, step_state, step)
        results["ACTIVE step junction"] = m
        q_right = step_state.net_doping_at(1.0, -0.5)
        q_left = step_state.net_doping_at(-1.0, -0.5)
        canonical_right = (q_right.donor_concentration, q_right.acceptor_concentration)
        canonical_left = (q_left.donor_concentration, q_left.acceptor_concentration)
        check_step_junction_2d_blocked(m, canonical_right, canonical_left, 1e17, 1e17)
        print(f"[ACTIVE step junction] donor 1e17 (x > 0) / acceptor 1e17 (x < 0): BLOCKED as {STEP_2D_REASON} -- "
              f"devsim.solve {m['solves']}, DevSim doping writes {len(m['writes'])}, no current; "
              f"canonical donor/acceptor preserved: right of junction {canonical_right}, left {canonical_left}; "
              f"geometry-only imports observed {m['imports']}; canonical state unchanged, modal calls {m['modal']}, leaked devices {m['leaked']}")
        assert not list(devsim.get_device_list()), f"leaked DevSim devices: {list(devsim.get_device_list())}"

        print("\n[guards] every check fails, for its own reason, when its subject is broken")
        chem = results["CHEMICAL"]
        expect_fail(lambda: check_blocked({**chem, "writes": [("node_model", "NetDoping")]}, "CHEMICAL"), "a DevSim doping write happens for a CHEMICAL state", "1 DevSim doping write(s)")
        expect_fail(lambda: check_blocked({**chem, "solves": 1}, "CHEMICAL"), "a devsim.solve happens for a CHEMICAL state", "devsim.solve was called 1 time(s)")
        expect_fail(lambda: check_blocked({**chem, "log": chem["log"].replace("UNSUPPORTED_BY_MODEL", "ok")}, "CHEMICAL"), "the block is not reported as UNSUPPORTED_BY_MODEL", "UNSUPPORTED_BY_MODEL is not shown")
        expect_fail(lambda: check_blocked({**chem, "log": chem["log"] + "\nI = 1.0e-12 A\n"}, "CHEMICAL"), "a current is reported for a CHEMICAL state", "a terminal current was reported")
        expect_fail(lambda: check_active({**results["ACTIVE"], "solves": 0}, 1e16, 0.0), "the ACTIVE control does not solve", "devsim.solve must run")
        expect_fail(lambda: check_active({**results["ACTIVE"], "writes": []}, 1e16, 0.0), "the ACTIVE control writes nothing", "DevSim writes []")
        comp = results["ACTIVE compensated"]
        expect_fail(lambda: check_compensated_blocked({**comp, "solves": 1}, "compensated", (1e17, 1e17, 0.0), (1e17, 1e17, 0.0)),
                    "a solve is allowed for a compensated region", "devsim.solve was called 1 time(s)")
        expect_fail(lambda: check_compensated_blocked({**comp, "writes": [("node_model", "NetDoping")]}, "compensated", (1e17, 1e17, 0.0), (1e17, 1e17, 0.0)),
                    "a DevSim write is allowed for a compensated region", "1 DevSim doping write(s)")
        expect_fail(lambda: check_compensated_blocked({**comp, "log": comp["log"] + "\nI = 2.4e-09 A\n"}, "compensated", (1e17, 1e17, 0.0), (1e17, 1e17, 0.0)),
                    "a current is reported for a compensated region", "a terminal current was reported")
        expect_fail(lambda: check_compensated_blocked({**comp, "status": {**comp["status"], "reason_code": "SOMETHING_ELSE"}}, "compensated", (1e17, 1e17, 0.0), (1e17, 1e17, 0.0)),
                    "the reason code is not COMPENSATED_TRANSPORT_MODEL_MISSING", "physics_status.reason_code is 'SOMETHING_ELSE'")
        expect_fail(lambda: check_compensated_blocked(comp, "compensated", (1e17, 1e17, 0.0), (1e17, 0.0, 1e17)),
                    "the canonical concentrations were collapsed", "the canonical donor/acceptor/net must be preserved")
        step_m = results["ACTIVE step junction"]
        expect_fail(lambda: check_step_junction_2d_blocked({**step_m, "solves": 1}, canonical_right, canonical_left, 1e17, 1e17),
                    "a solve is allowed for a 2D step junction", "devsim.solve was called 1 time(s)")
        expect_fail(lambda: check_step_junction_2d_blocked({**step_m, "writes": [("node_model", "NetDoping")]}, canonical_right, canonical_left, 1e17, 1e17),
                    "a DevSim write is allowed for a 2D step junction", "1 DevSim doping write(s)")
        expect_fail(lambda: check_step_junction_2d_blocked({**step_m, "log": step_m["log"] + "\nI = 3.1e-11 A\n"}, canonical_right, canonical_left, 1e17, 1e17),
                    "a current is reported for a blocked 2D step junction", "a terminal current was reported")
        expect_fail(lambda: check_step_junction_2d_blocked({**step_m, "status": {**step_m["status"], "reason_code": "SOMETHING_ELSE"}}, canonical_right, canonical_left, 1e17, 1e17),
                    "the reason code is not STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED", "physics_status.reason_code is 'SOMETHING_ELSE'")
        # Mutation 6 (Batch 7E section 6): the 2D step-junction reason must never be merged
        # with -- or silently reported as -- the unrelated compensated-transport reason.
        expect_fail(lambda: check_step_junction_2d_blocked({**step_m, "status": {**step_m["status"], "reason_code": REASON}}, canonical_right, canonical_left, 1e17, 1e17),
                    "the 2D step-junction reason is merged into COMPENSATED_TRANSPORT_MODEL_MISSING", f"physics_status.reason_code is {REASON!r}")
        expect_fail(lambda: check_step_junction_2d_blocked(step_m, (1e17, 0.0), (0.0, 0.0), 1e17, 1e17),
                    "the canonical concentration was collapsed", "the canonical donor/acceptor must be preserved")
    finally:
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
        app.destroy()
    assert not list(devsim.get_device_list()), f"leaked DevSim devices: {list(devsim.get_device_list())}"
    print("\nDOPANT ACTIVATION GATE (real DevSim): ACTIVE solves and writes; CHEMICAL and UNKNOWN are blocked with 0 doping writes and 0 solves; "
          "a compensated N_D == N_A region keeps its canonical values but is transport-blocked (COMPENSATED_TRANSPORT_MODEL_MISSING, 0 writes, "
          "0 solves, no current); a 2D ACTIVE Step Junction (official step() convention, both polarities on the junction line, not compensated) "
          "keeps its canonical values but is now transport-blocked too (STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED, Batch 7E, 0 writes, "
          "0 solves, no current)")


if __name__ == "__main__":
    main()
