#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 P0-B: thermal anneal has no representable 2D
GeometryTransform in this model, so it is a fail-closed v2 transition,
not a write into the canonical WaferStateV2.

Scenario required by the user: dope -> anneal -> measurement.
  - no crash
  - the DevSim solver is called 0 times (apply_doping blocks first)
  - donor/acceptor/net are all None (never 0, never a partial number)
  - an UNSUPPORTED_BY_MODEL event exists
  - the exact-known inventory that existed before the anneal is
    preserved in the unresolved-inventory ledger, not silently dropped
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics import wafer_state_v2 as v2
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.device.devsim import doping_mapping
from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile, DopingRegion


class _FakeResult:
    def __init__(self, doping):
        self.doping = doping


class FakeDevsimWithSolveCounter:
    def __init__(self, xs, ys):
        self._xs = list(xs)
        self._ys = list(ys)
        self.writes = {}
        self.solve_calls = 0

    def get_node_model_values(self, device, region, name):
        return list(self._xs) if name == "x" else list(self._ys)

    def node_model(self, device, region, name, equation):
        pass

    def set_node_values(self, device, region, name, values):
        self.writes[name] = list(values)

    def solve(self, **kwargs):
        self.solve_calls += 1

    class error(RuntimeError):
        pass


def main():
    # dope -> anneal -> measurement, exactly the required scenario.
    state = v2.initialize_wafer_state(
        cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")], grid_delta_um=0.1)
    result = _FakeResult(DopingProfile(
        kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=1.0e17)]))
    state = advance_wafer_state(state, result, "doping")
    assert len(state.attachments) == 1
    known_inventory_before = state.attachments[0].inventory_cm_per_depth
    assert known_inventory_before is not None

    # ANNEAL: fail-closed v2 transition, exactly what
    # _on_thermal_anneal_clicked() does (result is unused on this
    # branch, category != "doping").
    state = advance_wafer_state(state, None, "anneal", transform=None)

    assert not state.attachments, "anneal must drop every active attachment"
    assert any(
        e.category == "UNSUPPORTED_BY_MODEL" and e.process_category == "anneal"
        for e in state.events
    ), "an UNSUPPORTED_BY_MODEL anneal event must exist"

    ledgered = [u for u in state.unresolved_inventory if u.quantity_status == "KNOWN_EXACT"]
    assert ledgered, "the exact prior inventory must be preserved in the ledger"
    assert abs(ledgered[-1].total_cm_per_depth - known_inventory_before) < 1e-6 * abs(known_inventory_before)

    q = state.net_doping_at(0.0, -1.0)
    assert q.donor_concentration is None
    assert q.acceptor_concentration is None
    assert q.net_doping is None
    assert q.physics_status is not None
    assert q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"

    # MEASUREMENT: mirrors run_measurement() -- apply_doping() first,
    # devsim.solve() only on success. Must block before any solve call.
    fake = FakeDevsimWithSolveCounter([0.0, 1.0], [-1.0, -1.0])
    orig = backend.require_devsim
    backend.require_devsim = lambda: fake
    doping_mapping.backend.require_devsim = lambda: fake
    solved = False
    try:
        try:
            doping_mapping.apply_doping("dev", "Si", state)
            fake.solve()  # would only run on success
            solved = True
        except doping_mapping.UnsupportedDopingState:
            pass
    finally:
        backend.require_devsim = orig
        doping_mapping.backend.require_devsim = orig

    assert not solved, "measurement after anneal must not reach a solve"
    assert fake.solve_calls == 0, f"solver must be called 0 times, got {fake.solve_calls}"
    assert "NetDoping" not in fake.writes, "nothing may be written after anneal fail-closes"

    print("dope -> anneal -> measurement: no crash, solver calls = 0, "
          "donor/acceptor/net all None, UNSUPPORTED_BY_MODEL event "
          f"present, prior exact inventory ({known_inventory_before:.3e} "
          "cm^-1) preserved in the unresolved ledger.")


if __name__ == "__main__":
    main()
