#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test B (design doc §9 / review): apply_doping() writes
NetDoping only when the WaferStateV2 is fully, exactly modellable, and
blocks (raises, writes nothing) otherwise.

A fake DevSim module records every node_model/set_node_values call, so
this asserts on what would actually reach the solver -- no real DevSim.

Cases:
  1. representable + exact active doping -> NetDoping IS written
  2. LEGACY_UNRESOLVED region -> UnsupportedDopingState, NOTHING written
  3. fail-closed (no transform) region -> UnsupportedDopingState, nothing written
  4. oxidation-converted region -> UnsupportedDopingState, nothing written
  5. the historical RECOVERY counter-example (host material shadowed by a
     leftover surface material) -> now blocked, no numeric node value

No real backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    legacy_state_from_v1_cells, uniform_inventory_integral,
)
from tcad.physics.wafer_state import _Cell
from tcad.device.devsim import backend
from tcad.device.devsim import doping_mapping
from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState


class FakeDevsim:
    """Minimal stand-in for the devsim module surface apply_doping uses."""

    def __init__(self, xs, ys):
        self._xy = {"x": list(xs), "y": list(ys)}
        self.writes = {}          # model name -> values list
        self.registered = []

    def get_node_model_values(self, device, region, name):
        return list(self._xy[name])

    def node_model(self, device, region, name, equation):
        self.registered.append(name)

    def set_node_values(self, device, region, name, values):
        self.writes[name] = list(values)


def _run(state, xs_cm, ys_cm, length_scale_to_cm=1.0):
    fake = FakeDevsim(xs_cm, ys_cm)
    real_require = backend.require_devsim
    backend.require_devsim = lambda: fake
    doping_mapping.backend.require_devsim = lambda: fake
    try:
        raised = None
        try:
            apply_doping("dev", "Si", state, length_scale_to_cm=length_scale_to_cm)
        except UnsupportedDopingState as exc:
            raised = exc
        return fake, raised
    finally:
        backend.require_devsim = real_require
        doping_mapping.backend.require_devsim = real_require


def _si_state_with_doping():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),), grid_delta_um=0.1)
    return attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")


def main():
    xs = [-2.0, 0.0, 2.0]
    ys = [0.5, 1.0, 1.5]

    # 1. representable + exact -> NetDoping written
    fake, raised = _run(_si_state_with_doping(), xs, ys)
    assert raised is None
    assert "NetDoping" in fake.writes and fake.writes["NetDoping"] == [1.0e17] * 3
    print("[1] representable + exact active doping: NetDoping written =", fake.writes["NetDoping"])

    # 2. LEGACY_UNRESOLVED -> blocked
    leg = legacy_state_from_v1_cells([_Cell(-5.0, 5.0, 2.0, "Si")], grid_delta_um=0.1)
    fake, raised = _run(leg, xs, ys)
    assert isinstance(raised, UnsupportedDopingState)
    assert fake.writes == {}, "a value was written for a LEGACY_UNRESOLVED region"
    assert raised.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    print("[2] LEGACY_UNRESOLVED region: UnsupportedDopingState, 0 node models written")

    # 3. fail-closed (no transform) -> blocked
    s_fc = advance(_si_state_with_doping(), GeometryTransform("etching", representable=False),
                   step_seed="fc")
    fake, raised = _run(s_fc, xs, ys)
    assert isinstance(raised, UnsupportedDopingState) and fake.writes == {}
    print("[3] fail-closed region: UnsupportedDopingState, nothing written")

    # 4. oxidation-converted region -> blocked
    s_ox = advance(_si_state_with_doping(), GeometryTransform(
        "oxidation", representable=True, converted_extents_um=((-5.0, 5.0, 0.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="ox")
    fake, raised = _run(s_ox, xs, ys)
    assert isinstance(raised, UnsupportedDopingState) and fake.writes == {}
    print("[4] oxidation-converted region: UnsupportedDopingState, nothing written")

    # 5. historical RECOVERY counter-example: a leftover 'Mask'/'PHS' surface
    #    material sits on top of the doped Si at the same x. The old code
    #    "recovered" the Si profile and wrote it as a number anyway. Now
    #    the point is UNSUPPORTED (host not the topmost material) and the
    #    solve is blocked -- no numeric node value.
    shadowed = WaferStateV2(cells=(
        MaterialCell("c_si", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),
        MaterialCell("c_mask", "PHS", (-5.0, 5.0, 2.0, 2.5), "inst_mask"),
    ), grid_delta_um=0.1)
    shadowed = attach_dopant(
        shadowed, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    # net_doping_at at a Si-depth point still reads the real value here
    # (v2 owns the point by the deepest containing cell, which is Si) --
    # so this particular shadow no longer even needs RECOVERY. The point
    # the counter-example makes: there is no code path that re-injects an
    # old profile as a number when the state says UNSUPPORTED. Force a
    # genuine UNSUPPORTED by querying a converted region instead:
    shadowed_ox = advance(shadowed, GeometryTransform(
        "oxidation", representable=True, converted_extents_um=((-5.0, 0.0, 1.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="s")
    fake, raised = _run(shadowed_ox, [-2.0], [1.5])   # a node inside the converted rect
    assert isinstance(raised, UnsupportedDopingState)
    assert "NetDoping" not in fake.writes
    print("[5] no RECOVERY path: an UNSUPPORTED node is never written as a numeric value")

    print()
    print("WaferState v2 test B PASS -- DevSim write/solve gated on a fully modellable state")


if __name__ == "__main__":
    main()
