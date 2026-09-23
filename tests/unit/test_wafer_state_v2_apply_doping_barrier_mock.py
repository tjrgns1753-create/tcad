#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`apply_doping()` no longer takes `exclude_windows` at all (P0-C, user
correction of this file's own earlier version). The earlier version's
`test_known_node_inside_barrier_window_is_a_real_zero` encoded WRONG
physics: it zeroed the accumulated NetDoping of every node in an
`exclude_windows` rectangle regardless of which attachment produced it
-- which would also erase real pre-existing/background dopant that
predates the barrier. That assertion is removed here, not merely
adjusted.

The new contract: a barrier only ever carves a NEW attachment's own
support region, at ATTACH time
(`wafer_state_accumulation.advance_wafer_state`'s `barrier_windows`
parameter -- see `test_wafer_state_v2_barrier_physics_mock.py` for that
contract). By the time a state reaches `apply_doping()`,
`net_doping_at()` already reflects every attachment's real support
correctly, and `apply_doping()` just writes it -- this file now only
proves `apply_doping()` itself still gets the ordering right: unknown
nodes always block (never a silent zero, regardless of what geometry
they sit inside), and a real known-undoped virgin cell's 0 stays
distinct from an unknown None.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics import wafer_state_v2 as v2
from tcad.device.devsim import doping_mapping
from tcad.device.devsim import backend


class FakeDevsim:
    def __init__(self, xs, ys):
        self._xs = list(xs)
        self._ys = list(ys)
        self.writes = {}
        self.models = {}

    def get_node_model_values(self, device, region, name):
        if name == "x":
            return list(self._xs)
        if name == "y":
            return list(self._ys)
        raise self.error(f"no model {name}")

    def node_model(self, device, region, name, equation):
        self.models[name] = equation

    def set_node_values(self, device, region, name, values):
        self.writes[name] = list(values)

    class error(RuntimeError):
        pass


def _modelled_si_state():
    state = v2.initialize_wafer_state(
        cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")], grid_delta_um=0.1)
    state = v2.attach_dopant(
        state, species="P", polarity="donor",
        concentration_at=lambda x, y: 1.0e17,
        inventory_integral=v2.uniform_inventory_integral(1.0e17),
        support_instance_id="si#0",
        support_region_um=(-2.0, 2.0, -2.0, 0.0),
        model="uniform_v1", model_params={"conc_cm3": 1.0e17},
        provenance="test", chemical_state="ACTIVE",
    )
    return state


def _run_apply(state, xs, ys):
    fake = FakeDevsim(xs, ys)
    orig = backend.require_devsim
    backend.require_devsim = lambda: fake
    doping_mapping.backend.require_devsim = lambda: fake
    try:
        out = doping_mapping.apply_doping("dev", "Si", state)
        return fake, out, None
    except doping_mapping.UnsupportedDopingState as exc:
        return fake, None, exc
    finally:
        backend.require_devsim = orig
        doping_mapping.backend.require_devsim = orig


def test_apply_doping_has_no_exclude_windows_parameter():
    """The generic device-layer masking parameter is gone entirely
    (P0-C) -- a caller cannot accidentally reintroduce it."""
    import inspect
    params = inspect.signature(doping_mapping.apply_doping).parameters
    assert "exclude_windows" not in params
    assert "exclude_axis" not in params


def test_unknown_node_blocks_regardless_of_where_it_sits():
    """A fail-closed (LEGACY) state still blocks the whole solve and
    writes nothing -- this has nothing to do with barrier windows any
    more, just the base UNSUPPORTED contract."""
    legacy = v2.legacy_state_from_v1_cells(
        [__import__("tcad.physics.wafer_state", fromlist=["_Cell"])._Cell(
            -2.0, 2.0, 0.0, "Si")])
    xs = [-1.0, 0.0, 1.0]
    ys = [-0.5, -0.5, -0.5]
    fake, out, exc = _run_apply(legacy, xs, ys)
    assert exc is not None
    assert "NetDoping" not in fake.writes, "nothing may be written when blocked"
    assert exc.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"


def test_virgin_known_undoped_zero_is_distinct_from_unknown_none():
    """A MODELLED virgin cell with no dopant attached returns a real 0
    (known-undoped, a physical claim). A LEGACY cell returns None
    (unknown). apply_doping writes the first, blocks on the second."""
    virgin = v2.initialize_wafer_state(
        cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")], grid_delta_um=0.1)
    q = virgin.net_doping_at(0.0, -1.0)
    assert q.net_doping == 0.0 and q.physics_status is None

    fake, out, exc = _run_apply(virgin, [0.0, 1.0], [-1.0, -1.0])
    assert exc is None
    assert fake.writes["NetDoping"] == [0.0, 0.0]


def test_real_attachment_writes_its_real_value_everywhere():
    """No exclude_windows means apply_doping just trusts net_doping_at()
    as-is -- a real background attachment's value reaches every node it
    covers, full stop."""
    state = _modelled_si_state()
    fake, out, exc = _run_apply(state, [-1.5, 0.0, 1.5], [-1.0, -1.0, -1.0])
    assert exc is None
    assert fake.writes["NetDoping"] == [1.0e17, 1.0e17, 1.0e17]


def main():
    test_apply_doping_has_no_exclude_windows_parameter()
    test_unknown_node_blocks_regardless_of_where_it_sits()
    test_virgin_known_undoped_zero_is_distinct_from_unknown_none()
    test_real_attachment_writes_its_real_value_everywhere()
    print("apply_doping() no longer masks the accumulated NetDoping with "
          "a generic exclude_windows -- unknown always blocks, known-"
          "undoped 0 stays distinct from unknown None, and a real "
          "attachment's value reaches every node it covers.")


if __name__ == "__main__":
    main()
