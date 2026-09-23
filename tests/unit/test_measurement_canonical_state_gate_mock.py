#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1-1 central canonical-state gate -- unit contract plus a static
scan for DopingProfile / fallback-state bypasses.

`tcad.device.devsim.doping_mapping.canonical_node_doping` is the one
check every electrical measurement passes before doping is written or
a solve runs. FakeDevsim below records every node-model write and
solve, so "blocked" is measured as zero calls, not assumed. The real
GUI + real DevSim version of the same contract is
tests/integration/test_measurement_canonical_state_gate_real.py.

Geometry coverage (Tier 1-1 supplement): net_doping_at()'s number alone
is not trusted. A node passes only when EXACTLY ONE ACTIVE + MODELLED
cell of the canonical WaferStateV2 contains it and that cell's material
is the DevSim region's material. Each counter-example below builds a
state the old gate accepted and wrote a number for (zero owning cells,
two owning cells, LEGACY_UNRESOLVED / UNRESOLVED cell, material/region
mismatch, a cell without bounds, a v1 WaferState) and asserts 0 doping
writes, 0 solves and the blocking diagnostics.

What the static scan proves -- and what it does NOT: it finds 0
production calls that hand a `.doping` DopingProfile / `doping=` keyword
to a solve-path function, 0 production callers of the DopingProfile
writer `apply_doping_symbolic`, and 0 fallback-state rebuilds inside the
GUI measurement methods. It does NOT prove that every DevSim solve is
preceded by the gate: it does not trace control flow from each solve
back to canonical_node_doping(). That per-entry-point claim is carried
by the entry-point table and by
tests/unit/test_measurement_entry_point_gate_mock.py, which drives each
user entry point with an unsupported state and counts calls.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tcad.physics import wafer_state_v2 as v2  # noqa: E402
from tcad.physics.wafer_state_v2 import DopingQueryResult, MaterialCell, WaferStateV2  # noqa: E402
from tcad.device.devsim import backend  # noqa: E402
from tcad.device.devsim.doping_mapping import (  # noqa: E402
    UnsupportedDopingState, apply_doping, canonical_node_doping,
)


class FakeDevsim:
    def __init__(self, xs, ys):
        self._nodes = {"x": list(xs), "y": list(ys)}
        self.reads = []
        self.writes = []
        self.solves = 0

    def get_node_model_values(self, device, region, name):
        self.reads.append(name)
        return list(self._nodes[name])

    def node_model(self, device, region, name, equation):
        self.writes.append(("node_model", name))

    def set_node_values(self, device, region, name, values):
        self.writes.append(("set_node_values", name))
        self._nodes[name] = list(values)

    def solve(self, **kwargs):
        self.solves += 1


def _with_fake(fake, fn):
    original = backend.require_devsim
    backend.require_devsim = lambda: fake
    try:
        return fn()
    finally:
        backend.require_devsim = original


def _uniform(state, instance_id, bounds, conc=1.0e17, seed="u"):
    return v2.attach_dopant(
        state, species="P", polarity="donor",
        concentration_at=lambda x, y: conc,
        inventory_integral=v2.uniform_inventory_integral(conc),
        support_instance_id=instance_id, support_region_um=bounds,
        model="uniform_v1", model_params={"conc_cm3": conc}, step_seed=seed, chemical_state="ACTIVE",
    )


def _supported_state(conc=1.0e17):
    state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")])
    return _uniform(state, "si#0", (-2.0, 2.0, -2.0, 0.0), conc)


def _cells_state(*cells):
    return WaferStateV2(cells=tuple(cells))


def _expect_blocked(state, xs=(-1.0, 1.0), ys=(-1.0, -1.0), region="Si", scale=1.0):
    fake = FakeDevsim(xs, ys)
    try:
        _with_fake(fake, lambda: apply_doping("dev", region, state, length_scale_to_cm=scale))
    except UnsupportedDopingState as exc:
        assert "UNSUPPORTED_BY_MODEL" in str(exc)
        assert "The device solve must not proceed" in str(exc)
        assert exc.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
        assert fake.writes == [], f"blocked gate wrote {fake.writes}"
        assert fake.solves == 0
        assert set(fake.reads) <= {"x", "y"}, fake.reads
        return exc, fake
    raise AssertionError(f"expected UnsupportedDopingState; the gate wrote {fake.writes}")


def _first(exc):
    return exc.physics_status["first_blocked_node"]


def _assert_diagnostics(exc, *, x, y, instance_ids, blocked, total, region="Si", because):
    text = str(exc)
    status = exc.physics_status
    first = _first(exc)
    assert (first["x_um"], first["y_um"]) == (x, y), first
    assert f"First blocked node: x={x:.10g} um, y={y:.10g} um in DevSim region {region!r}" in text, text
    assert status["region"] == region and first["region"] == region
    assert first["material_instance_ids"] == list(instance_ids), first
    shown = (", ".join(instance_ids[:10]) + (f" (+{len(instance_ids) - 10} more)" if len(instance_ids) > 10 else "")
             if instance_ids else "none")
    assert f"Canonical material instance(s) containing it: {shown}." in text, text
    assert (status["blocked_nodes"], status["total_nodes"]) == (blocked, total), status
    assert f"{blocked} of {total} mesh node(s) blocked" in text, text
    assert because in first["reason"] and f"Blocked because: {first['reason']}" in text, (because, text)
    assert "Canonical query at this node:" in text


# ---------------------------------------------------------------------------
# No canonical state / not a canonical state
# ---------------------------------------------------------------------------

def test_no_canonical_state_blocks_with_node_diagnostics():
    exc, fake = _expect_blocked(None, xs=(0.5, 1.0), ys=(-1.0, -1.5))
    assert fake.reads == ["x", "y"], "only the node coordinates may be read"
    _assert_diagnostics(exc, x=0.5, y=-1.0, instance_ids=[], blocked=2, total=2,
                        because="no canonical WaferStateV2 exists for this wafer")


def test_v1_wafer_state_is_not_a_canonical_state():
    from tcad.physics.wafer_state import WaferState, _Cell

    v1 = WaferState(materials=("Si",), stack=(), grid_delta_um=0.1,
                    _cells=(_Cell(-1e9, 1e9, 1.0, "Si"),), _thin_x=())
    assert v1.net_doping_at(0.0, 0.0).net_doping == 0.0, "the v1 query claims known-undoped"
    exc, _ = _expect_blocked(v1)
    _assert_diagnostics(exc, x=-1.0, y=-1.0, instance_ids=[], blocked=2, total=2,
                        because="not a canonical WaferStateV2")


# ---------------------------------------------------------------------------
# Geometry coverage counter-examples (each was written as a number before)
# ---------------------------------------------------------------------------

def test_zero_owning_cells_blocks():
    state = _supported_state()
    assert state.net_doping_at(3.0, -0.5).net_doping == 0.0, "old query: a silent known-undoped 0.0"
    exc, _ = _expect_blocked(state, xs=(0.0, 3.0), ys=(-0.5, -0.5))
    _assert_diagnostics(exc, x=3.0, y=-0.5, instance_ids=[], blocked=1, total=2,
                        because="no ACTIVE modelled cell contains this node")
    assert "si#0" in _first(exc)["reason"], "the reason names the Si cell the node fell outside"


def test_two_instances_sharing_an_edge_block():
    state = _cells_state(MaterialCell("ca", "Si", (-2.0, 0.0, -1.0, 0.0), "si#a"),
                         MaterialCell("cb", "Si", (0.0, 2.0, -1.0, 0.0), "si#b"))
    state = _uniform(state, "si#a", (-2.0, 0.0, -1.0, 0.0), 1.0e17)
    assert state.net_doping_at(0.0, -0.5).net_doping == 1.0e17, "old query: si#a silently wins the tie"
    exc, _ = _expect_blocked(state, xs=(-1.0, 0.0), ys=(-0.5, -0.5))
    _assert_diagnostics(exc, x=0.0, y=-0.5, instance_ids=["si#a", "si#b"], blocked=1, total=2,
                        because="2 ACTIVE modelled cells contain this node")


def test_si_sio2_interface_node_is_not_ambiguous():
    """A Si node exactly on a shared Si/SiO2 edge (y=0, Si's y_max ==
    SiO2's y_min, a zero-area shared boundary -- not an overlap) is NOT
    ambiguous: DevSim region='Si' already names which material this node
    belongs to, so the SiO2 cell merely touching that same boundary is
    not a second owner. Exactly the Si cell resolves as owner, and the
    real Si attachment's value reaches the node -- not blocked, not the
    SiO2 cell's unrelated 0.

    History: this used to assert the interface node BLOCKS ("2 ACTIVE
    modelled cells contain this node"), treating a normal heterogeneous
    material boundary as ambiguity that pinned a real bug (WaferStateV2.
    net_doping_at()'s own y_max tie-break silently returning the SiO2
    cell's 0 for a doped Si node) as the expected contract. Fixed two
    ways: canonical_node_doping()'s ownership check now only considers
    cells of the DevSim region's OWN material as candidates (see
    _ownership_problem()), and it passes its resolved owner into
    net_doping_at(owning_cell=...) instead of letting that method's own,
    coarser tie-break pick a different cell (see that method's own
    docstring in wafer_state_v2.py) -- every OTHER caller of
    net_doping_at() (GUI overlay, hover note, ...) that omits
    owning_cell keeps that same tie-break unchanged."""
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.0), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.0, 0.1), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.0), 1.0e17)
    assert state.net_doping_at(0.5, 0.0).net_doping == 0.0, (
        "net_doping_at()'s OWN default tie-break is unchanged (still picks SiO2) -- "
        "the gate must not rely on it directly at a shared boundary")

    fake = FakeDevsim([0.5], [0.0])
    donors, acceptors, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "Si", state))
    assert (donors, acceptors, nets) == ([1.0e17], [0.0], [1.0e17]), (
        "the real Si attachment must reach the interface node, not SiO2's 0")
    assert fake.writes == [] and fake.solves == 0, "the gate itself must be read-only"

    fake2 = FakeDevsim([0.5], [0.0])
    _with_fake(fake2, lambda: apply_doping("dev", "Si", state))
    assert fake2._nodes["NetDoping"] == [1.0e17], "the write/solve path is not blocked"

    # Same interface, no dopant attached anywhere -- known-undoped 0.0,
    # still resolved (not blocked), distinct from an unknown None.
    virgin = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.0), "si#0"),
                          MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.0, 0.1), "ox#0"))
    fake3 = FakeDevsim([0.5], [0.0])
    _, _, nets3 = _with_fake(fake3, lambda: canonical_node_doping("dev", "Si", virgin))
    assert nets3 == [0.0], "known-undoped 0.0 at the interface, not a block"


def test_positive_area_overlap_still_blocks():
    """Unlike a zero-area shared edge, two cells whose rectangles
    overlap with REAL (positive) area is a genuine geometry
    inconsistency -- two solids occupying the same space -- and blocks
    regardless of material, even though only one of them matches the
    DevSim region."""
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.05), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.0, 0.1), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.05), 1.0e17)
    exc, _ = _expect_blocked(state, xs=(0.5,), ys=(0.02,))
    _assert_diagnostics(exc, x=0.5, y=0.02, instance_ids=["si#0", "ox#0"], blocked=1, total=1,
                        because="physically overlap over a positive area")
    assert "(-2.0, 2.0, 0.0, 0.05)" in str(exc), str(exc)


def test_one_instance_split_into_two_cells_blocks_on_their_shared_edge():
    state = _cells_state(MaterialCell("c1", "Si", (-2.0, 0.0, -1.0, 0.0), "si#0"),
                         MaterialCell("c2", "Si", (0.0, 2.0, -1.0, 0.0), "si#0"))
    exc, _ = _expect_blocked(state, xs=(0.0,), ys=(-0.5,))
    _assert_diagnostics(exc, x=0.0, y=-0.5, instance_ids=["si#0"], blocked=1, total=1,
                        because="2 ACTIVE modelled cells contain this node")


def test_legacy_unresolved_cell_blocks():
    legacy = v2.legacy_state_from_v1_cells([SimpleNamespace(material="Si")])
    exc, _ = _expect_blocked(legacy)
    first = _first(exc)
    assert first["cells"][0]["lifecycle"] == "LEGACY_UNRESOLVED" and first["cells"][0]["bounds_um"] is None
    assert "LEGACY_UNRESOLVED" in str(exc) and "has no exact bounds" in first["reason"], str(exc)
    assert "physics_status UNSUPPORTED_BY_MODEL" in str(exc), "the canonical query's own status is reported"


def test_many_legacy_cells_keep_the_message_bounded():
    """A state migrated from a real mesh carries one LEGACY_UNRESOLVED
    cell per mesh column -- 1136 and 2500 in two real integration tests.
    Listing every one produced 120k-265k character lines per blocked
    measurement in the GUI log; the message must stay bounded."""
    legacy = v2.legacy_state_from_v1_cells([SimpleNamespace(material="Si")] * 2500)
    xs = [i * 1.0e-3 for i in range(3000)]
    exc, _ = _expect_blocked(legacy, xs=xs, ys=[-0.5] * 3000)
    _assert_diagnostics(exc, x=0.0, y=-0.5, instance_ids=[c.material_instance_id for c in legacy.cells],
                        blocked=3000, total=3000, because="as may 2499 more cell(s) without bounds")
    assert len(str(exc)) < 3000, len(str(exc))
    assert "(+2490 more)" in str(exc) and "(+2497 more)" in str(exc), str(exc)


def test_unresolved_cell_without_an_event_blocks():
    state = _cells_state(MaterialCell("c1", "Si", (-2.0, 2.0, -2.0, 0.0), "si#0", lifecycle="UNRESOLVED"))
    assert state.net_doping_at(0.0, -1.0).net_doping == 0.0, "old query: 0 owning ACTIVE cells -> silent 0"
    exc, _ = _expect_blocked(state)
    _assert_diagnostics(exc, x=-1.0, y=-1.0, instance_ids=["si#0"], blocked=2, total=2,
                        because="lifecycle UNRESOLVED")
    assert "material Si" in str(exc) and "lifecycle UNRESOLVED" in str(exc)


def test_unresolved_cell_under_a_new_active_cell_blocks():
    """A fail-closed step leaves the old Si UNRESOLVED; a later cell over
    the same point un-covers the event in net_doping_at, which then
    reads the new cell's 0. The stale cell still contains the node."""
    old = _supported_state()
    failed = v2.advance(old, None, step_seed="etching")
    state = v2.advance(failed, v2.GeometryTransform(
        "deposition", representable=True,
        added_cells=(("Si", (-2.0, 2.0, -1.0, 0.5), "si#redeposited"),)), step_seed="dep")
    assert state.net_doping_at(0.0, -0.5).net_doping == 0.0, "old query: stale Si read as undoped"
    exc, _ = _expect_blocked(state, xs=(0.0,), ys=(-0.5,))
    assert _first(exc)["material_instance_ids"] == ["si#0", "si#redeposited"], _first(exc)
    assert "lifecycle UNRESOLVED" in _first(exc)["reason"], _first(exc)


def test_material_region_mismatch_blocks():
    state = _cells_state(MaterialCell("cox", "SiO2", (-2.0, 2.0, -2.0, 0.0), "ox#0"))
    assert state.net_doping_at(0.0, -1.0).net_doping == 0.0, "old query: oxide answered for a Si node"
    exc, _ = _expect_blocked(state)
    _assert_diagnostics(exc, x=-1.0, y=-1.0, instance_ids=["ox#0"], blocked=2, total=2,
                        because="not the DevSim region's material 'Si'")
    assert "material SiO2" in str(exc)


def test_cell_without_bounds_blocks():
    state = _cells_state(MaterialCell("cs", "Si", (-2.0, 2.0, -2.0, 0.0), "si#0"),
                         MaterialCell("cn", "Si", None, "si#unknown"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -2.0, 0.0), 1.0e17)
    assert state.net_doping_at(0.0, -1.0).net_doping == 1.0e17, "old query: the unbounded cell was skipped"
    exc, _ = _expect_blocked(state)
    _assert_diagnostics(exc, x=-1.0, y=-1.0, instance_ids=["si#0", "si#unknown"], blocked=2, total=2,
                        because="has no exact bounds")


def test_each_unknown_query_condition_blocks_even_on_one_node():
    status = {"resolution": "UNSUPPORTED_BY_MODEL", "entries": [
        {"parameter": "p", "note": "stub reason"}], "notes": []}
    for bad, because in (
        (DopingQueryResult(None, None, None, status), "stub reason"),
        (DopingQueryResult(None, 0.0, 1.0e17, None), "donor/acceptor/net is None"),
        (DopingQueryResult(1.0e17, None, 1.0e17, None), "donor/acceptor/net is None"),
        (DopingQueryResult(1.0e17, 0.0, None, None), "donor/acceptor/net is None"),
    ):
        state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")])
        object.__setattr__(state, "net_doping_at", lambda x, y, bad=bad, **kw: (
            bad if x > 0 else DopingQueryResult(1.0e17, 0.0, 1.0e17, None)))
        exc, _ = _expect_blocked(state)
        _assert_diagnostics(exc, x=1.0, y=-1.0, instance_ids=["si#0"], blocked=1, total=2,
                            because=because)


def test_anneal_fail_closed_reports_the_original_reason():
    state = v2.advance(_supported_state(), None, step_seed="anneal")
    exc, _ = _expect_blocked(state)
    _assert_diagnostics(exc, x=-1.0, y=-1.0, instance_ids=["si#0"], blocked=2, total=2,
                        because="lifecycle UNRESOLVED")
    text = str(exc)
    assert "physics_status UNSUPPORTED_BY_MODEL -- point lies in a region an UNSUPPORTED_BY_MODEL 'anneal' event covers" in text, text
    assert _first(exc)["query_physics_status"]["resolution"] == "UNSUPPORTED_BY_MODEL"


# ---------------------------------------------------------------------------
# Supported controls
# ---------------------------------------------------------------------------

def test_supported_state_passes_exact_canonical_values_read_only():
    state = _supported_state()
    # both nodes on the cell's closed boundary still have exactly one owner
    fake = FakeDevsim([-2.0, 2.0, 0.5], [0.0, -2.0, -0.5])
    donors, acceptors, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "Si", state))
    assert (donors, acceptors, nets) == ([1.0e17] * 3, [0.0] * 3, [1.0e17] * 3)
    assert fake.writes == [] and fake.solves == 0, "the gate itself must be read-only"


def test_known_undoped_zero_needs_exactly_one_supported_cell():
    virgin = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")])
    fake = FakeDevsim([0.0, 1.0], [-1.0, -1.0])
    _with_fake(fake, lambda: apply_doping("dev", "Si", virgin))
    assert ("set_node_values", "NetDoping") in fake.writes
    assert fake._nodes["NetDoping"] == [0.0, 0.0]


def test_another_material_elsewhere_does_not_block():
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.0), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.0, 0.1), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.0), 1.0e17)
    fake = FakeDevsim([-1.0, 1.0], [-0.5, -0.1])
    _, _, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "Si", state))
    assert nets == [1.0e17, 1.0e17]


def test_float32_boundary_node_snaps_within_1ulp():
    """DevSim nodes carry the mesh's float32 coordinates scaled to cm
    (mesh_import.py multiplies the float32 point array): 2.4 um reads
    back as 2.4000001 um, one float32 ULP outside a cell edge at exactly
    2.4. The gate corrects for this ONE mechanism -- coordinate
    round-trip serialization -- by snapping onto the boundary, only
    within that boundary's own float32 ULP tolerance
    (_float32_roundtrip_ulp_um), and only once exact containment already
    failed. A node genuinely 2 um DEFAULT-inside (well within tolerance
    for real) needs no snap and is unaffected.

    History: this used to assert such a node BLOCKS ("zero owning
    cells"), pinning the coordinate round-trip error itself as an
    ownership problem. Real GUI+DevSim evidence
    (docs/audits/2026-09-17-tier1-1-r2/post_fix_float32_boundary_evidence.log)
    showed the fixed-r2 gate blocking a real uniformly-doped measurement
    at width=4.8um purely because of this -- 12 real, well-inside-tolerance
    boundary nodes. The real-DevSim regression for this fix is
    tests/integration/test_float32_boundary_snap_real.py."""
    scale = 1.0e-4
    x_in = float((np.array([2.0], dtype=np.float32) * scale)[0])
    x_out = float((np.array([2.4], dtype=np.float32) * scale)[0])
    assert x_in != 2.0 and x_out != 2.4, "fixture is broken: no float32 rounding occurred"

    inside = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#0")])
    _, _, nets = _with_fake(FakeDevsim([x_in], [-0.5e-4]),
                            lambda: canonical_node_doping("dev", "Si", inside, scale))
    assert nets == [0.0], "an interior node (not at a boundary) needs no snap"

    on_edge = v2.initialize_wafer_state(cells=[("Si", (-2.4, 2.4, -1.0, 0.0), "si#0")])
    on_edge = v2.attach_dopant(
        on_edge, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e16,
        inventory_integral=v2.uniform_inventory_integral(1.0e16),
        support_instance_id="si#0", support_region_um=(-2.4, 2.4, -1.0, 0.0),
        model="uniform_v1", model_params={"conc_cm3": 1.0e16}, chemical_state="ACTIVE",
    )
    fake = FakeDevsim([x_out], [-0.5e-4])
    donors, acceptors, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "Si", on_edge, scale))
    assert x_out / scale > 2.4, "fixture is broken: the raw node must genuinely fall outside [-2.4, 2.4]"
    assert nets == [1.0e16], "within 1 ULP: the node snaps onto the real edge and reads its real attachment"
    assert fake.writes == [] and fake.solves == 0, "the gate itself must be read-only"

    fake2 = FakeDevsim([x_out], [-0.5e-4])
    _with_fake(fake2, lambda: apply_doping("dev", "Si", on_edge, length_scale_to_cm=scale))
    assert fake2._nodes["NetDoping"] == [1.0e16], "the write/solve path is not blocked"


def test_a_real_gap_beyond_1ulp_still_blocks():
    """A node genuinely outside a cell -- by far more than one float32
    ULP, e.g. a whole grid cell -- is a real geometry mismatch, not a
    serialization artifact, and must still block exactly as before.

    FakeDevsim/_expect_blocked's xs/ys are the NATIVE (pre-division)
    coordinates canonical_node_doping() divides by `scale` -- exactly
    what get_node_model_values() would really return -- not already-
    um values; this test originally passed `x_far_native / scale`
    (dividing back to um) into `xs`, and -0.5 (already um) into `ys`,
    so both axes landed thousands of um away regardless of the real
    ~0.2um gap under test, passing only because ANY absurd coordinate
    blocks -- not because it actually exercised a 0.2um-beyond-the-edge
    gap. Fixed to pass genuinely native coordinates on both axes."""
    scale = 1.0e-4
    outside = v2.initialize_wafer_state(cells=[("Si", (-2.4, 2.4, -1.0, 0.0), "si#0")])
    x_far = 2.4 + 0.2  # one grid cell past the edge
    x_far_native = float((np.array([x_far], dtype=np.float32) * scale)[0])
    y_native = -0.5 * scale
    exc, fake = _expect_blocked(outside, xs=(x_far_native,), ys=(y_native,), scale=scale)
    assert abs(_first(exc)["x_um"] - x_far) < 1e-6, _first(exc)
    assert _first(exc)["material_instance_ids"] == []
    assert "no ACTIVE modelled cell contains this node" in _first(exc)["reason"]


def test_ambiguous_snap_blocks_rather_than_guessing():
    """A raw coordinate within tolerance of TWO DIFFERENT cell edges --
    a real (if unusual) tiny gap between two cells, smaller than the
    float32 ULP at that magnitude -- must not be arbitrarily assigned to
    either side. Constructed at a large coordinate magnitude
    (boundary~100) where the float32 ULP (~1.2e-5) is itself larger than
    a genuine 1e-5 gap between two cells -- confirmed reachable from both
    sides before asserting the block (see docs/audits/2026-09-17-tier1-1-r3/
    for the derivation)."""
    scale = 1.0
    left = MaterialCell("cl", "Si", (0.0, 100.0, -1.0, 0.0), "si#l")
    right = MaterialCell("cr", "Si", (100.00001, 200.0, -1.0, 0.0), "si#r")
    state = _cells_state(left, right)
    x_mid = 100.000005  # equidistant from both edges, 5e-6 from each
    tol = float(np.spacing(np.float32(100.0)))  # 1 float32 ULP at this magnitude (~7.6e-6)
    assert abs(x_mid - 100.0) <= tol and abs(x_mid - 100.00001) <= tol, "fixture is broken: not ambiguous"
    exc, _ = _expect_blocked(state, xs=(x_mid,), ys=(-0.5,), scale=scale)
    assert _first(exc)["material_instance_ids"] == [], (
        "an ambiguous snap must not resolve to either cell")


# ---------------------------------------------------------------------------
# Tier 1-1 r4: the r3 snap only triggered when `found` was EMPTY, so a
# float32 round-trip error that pushed a node a few ULPs INTO a
# neighboring material's cell (found non-empty, just the wrong material)
# never got a snap chance at all -- a real, Codex-reported false block on
# a genuinely supported interface node. Fixed by deciding ownership at
# the RAW coordinate first, and -- only when that has no same-region
# owner -- searching ACTIVE+MODELLED cells of the region's OWN material
# specifically for a snap target, then re-deciding ownership at the
# snapped point against every present cell.
#
# Task D (a real 2-material DevSim mesh with a NON-ZERO Si/SiO2
# interface) was investigated directly, not assumed impossible: every
# real multi-material geometry model in this project (gate_stack.py,
# confirmed by reading a real exported mesh -- Si at y in [-1,0], the
# gate oxide at y in [0,0.075], every other material likewise) anchors
# the Si surface, and so every Si-to-other-material interface, at
# EXACTLY y=0 -- trivially float32-exact, not useful for this bug. The
# only real process that produces a Si/SiO2 interface AWAY from y=0 is
# oxidation, whose CONVERTED-region dopant fate this project's own
# WaferStateV2 design already marks UNSUPPORTED_BY_MODEL by construction
# (`_apply_conversion` / `_apply_geometry_change` in wafer_state_v2.py) --
# so no oxidation-derived interface can ever become the TWO ACTIVE +
# MODELLED cells this bug needs, and building one would mean either
# touching oxidation conversion physics (explicitly out of scope this
# round) or writing an entirely new, bespoke geometry-construction path
# with no existing production caller -- disproportionate to what the
# deterministic unit regressions below already prove rigorously (with
# EXACT, numpy-verified float32 arithmetic, not an approximation a real
# mesh's own meshing/export noise could obscure). Pinned here as
# deterministic unit regressions instead, per the task's own fallback.
# ---------------------------------------------------------------------------

def _f32_native(v_um: float, scale: float) -> float:
    """What DevSim's get_node_model_values() would actually return for a
    canonical boundary value `v_um` at this length_scale_to_cm -- the
    mesh's own float32 serialization, exactly as mesh_import.py computes
    it (`points = raw_points * length_scale_to_cm`). This -- NOT `v_um`
    itself -- is the value FakeDevsim's xs/ys (and _expect_blocked's)
    must carry: canonical_node_doping() divides whatever
    get_node_model_values() returns by `length_scale_to_cm` to recover
    um. A caller here must never pass an already-um value into
    FakeDevsim/_expect_blocked; scale it to native first (bare `v * scale`
    for a value with no float32 error of its own, e.g. a synthetic
    "far away" test coordinate)."""
    return float((np.array([v_um], dtype=np.float32) * scale)[0])


def test_r4_snap_up_into_a_neighboring_material_resolves_to_the_real_owner():
    """The exact Codex repro: Si (-2,2,-1,0.6) / SiO2 (-2,2,0.6,1),
    region='Si', exact interface 0.6um. float32(0.6)*float32(1e-4)/1e-4
    = 0.6000000212225132um -- +2.122251319e-08um, INSIDE SiO2's range,
    one float32 ULP (3.638e-08um at this magnitude) past the true
    boundary. `found` at the raw coordinate is the SiO2 cell (not
    empty), so the r3 gate never tried a snap at all and blocked a
    genuinely supported Si node with 'the only cell containing this
    node is material SiO2 ..., not ... Si'. Required: canonical donor
    1e17 is returned, apply_doping() writes it, not UNSUPPORTED."""
    scale = 1.0e-4
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.6), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.6, 1.0), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.6), 1.0e17)

    y_native = _f32_native(0.6, scale)
    x_native = 0.5 * scale
    y_raw = y_native / scale  # for the sanity checks only -- never passed to FakeDevsim
    assert y_raw > 0.6, "fixture is broken: this repro needs the round-trip to land INSIDE SiO2"
    tol = float(np.spacing(np.float32(0.6) * np.float32(scale))) / scale
    assert 0.0 < y_raw - 0.6 <= tol, (y_raw, tol)

    fake = FakeDevsim([x_native], [y_native])
    donors, acceptors, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "Si", state, scale))
    assert (donors, acceptors, nets) == ([1.0e17], [0.0], [1.0e17]), (
        f"the Si attachment's real value must reach this node, not SiO2's 0 (y_raw={y_raw!r})")
    assert fake.writes == [] and fake.solves == 0, "the gate itself must be read-only"

    fake2 = FakeDevsim([x_native], [y_native])
    _with_fake(fake2, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=scale))
    assert fake2._nodes["NetDoping"] == [1.0e17], "the write/solve path is not blocked"


def test_r4_snap_down_needs_the_upper_regions_owner():
    """Opposite direction: interface at 0.7um, Si (-1,0.7) below,
    SiO2 (0.7,1.0) above. float32(0.7)*float32(1e-4)/1e-4 =
    0.6999999459367245um -- rounds DOWN, landing INSIDE Si's range
    while the DevSim region being queried is 'SiO2' (the UPPER
    material) -- the query must snap UP to find the real SiO2 owner,
    not stay stuck on the Si cell that already (wrongly) contains it."""
    scale = 1.0e-4
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.7), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.7, 1.0), "ox#0"))
    state = v2.attach_dopant(
        state, species="B", polarity="acceptor", concentration_at=lambda x, y: 5.0e16,
        inventory_integral=v2.uniform_inventory_integral(5.0e16),
        support_instance_id="ox#0", support_region_um=(-2.0, 2.0, 0.7, 1.0),
        model="uniform_v1", model_params={"conc_cm3": 5.0e16}, chemical_state="ACTIVE",
    )

    y_native = _f32_native(0.7, scale)
    x_native = 0.5 * scale
    y_raw = y_native / scale
    tol = float(np.spacing(np.float32(0.7) * np.float32(scale))) / scale
    assert 0.0 < 0.7 - y_raw <= tol, (
        f"fixture is broken: this repro needs the round-trip to land INSIDE Si, "
        f"within tolerance (y_raw={y_raw!r}, tol={tol!r})")

    fake = FakeDevsim([x_native], [y_native])
    donors, acceptors, nets = _with_fake(fake, lambda: canonical_node_doping("dev", "SiO2", state, scale))
    assert (donors, acceptors, nets) == ([0.0], [5.0e16], [-5.0e16]), (
        f"the SiO2 (upper region) attachment's real value must be returned (y_raw={y_raw!r})")

    fake2 = FakeDevsim([x_native], [y_native])
    _with_fake(fake2, lambda: apply_doping("dev", "SiO2", state, length_scale_to_cm=scale))
    assert fake2._nodes["NetDoping"] == [-5.0e16]


def test_r4_gap_beyond_1ulp_at_the_interface_still_blocks():
    """Same Si/SiO2 interface as the first r4 test, but the node is
    genuinely 1e-6um past the boundary (~27x the ~3.6e-8um tolerance at
    this magnitude) -- a real mismatch, not a serialization artifact,
    and must still block with 0 writes / 0 solves."""
    scale = 1.0e-4
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.6), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.6, 1.0), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.6), 1.0e17)
    y_far = 0.6 + 1.0e-6
    y_far_native = y_far * scale
    x_native = 0.5 * scale
    tol = float(np.spacing(np.float32(0.6) * np.float32(scale))) / scale
    assert (y_far - 0.6) > tol, "fixture is broken: this gap must exceed the 1-ULP tolerance"
    exc, fake = _expect_blocked(state, xs=(x_native,), ys=(y_far_native,), region="Si", scale=scale)
    assert abs(_first(exc)["y_um"] - y_far) < 1e-12, _first(exc)
    assert "material SiO2" in str(exc) and "not the DevSim region's material 'Si'" in str(exc)


def test_r4_overlap_at_the_interface_still_blocks_after_a_snap_attempt():
    """Si (-2,2,-1,0.6) and SiO2 (-2,2,0.55,1) genuinely overlap over
    y in [0.55, 0.6] (positive area, not a shared edge). A raw node at
    float32(0.6)'s round-trip (0.6000000212...um, just past Si's own
    y_max) has NO same-region owner at the raw point (only SiO2
    contains it there), so a snap IS attempted and succeeds -- onto
    Si's y_max=0.6 -- but re-deciding ownership at that snapped point
    finds both cells (0.6 lies inside SiO2's [0.55,1] too) and their
    genuine overlap, and correctly blocks anyway."""
    scale = 1.0e-4
    state = _cells_state(MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.6), "si#0"),
                         MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.55, 1.0), "ox#0"))
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.6), 1.0e17)
    y_native = _f32_native(0.6, scale)
    x_native = 0.5 * scale
    exc, _ = _expect_blocked(state, xs=(x_native,), ys=(y_native,), region="Si", scale=scale)
    assert "physically overlap over a positive area" in str(exc), str(exc)


def test_r4_ambiguous_same_region_snap_at_the_interface_still_blocks():
    """Two Si cells stacked with a real gap of 2e-8um between them
    (smaller than the ~3.6e-8um float32 ULP at this magnitude) -- a
    query point in the gap is within tolerance of BOTH boundaries, so
    the region-targeted snap search must refuse to guess either side."""
    scale = 1.0e-4
    gap = 2.0e-8
    state = _cells_state(MaterialCell("cl", "Si", (-2.0, 2.0, -1.0, 0.6), "si#l"),
                         MaterialCell("cu", "Si", (-2.0, 2.0, 0.6 + gap, 1.6), "si#u"))
    y_mid = 0.6 + gap / 2.0
    y_mid_native = y_mid * scale
    x_native = 0.5 * scale
    tol = float(np.spacing(np.float32(0.6) * np.float32(scale))) / scale
    assert abs(y_mid - 0.6) <= tol and abs(y_mid - (0.6 + gap)) <= tol, (
        "fixture is broken: both boundaries must be reachable")
    exc, _ = _expect_blocked(state, xs=(x_native,), ys=(y_mid_native,), region="Si", scale=scale)
    assert _first(exc)["material_instance_ids"] == [], (
        "an ambiguous same-region snap must not resolve to either cell")


# ---------------------------------------------------------------------------
# Robust continuation and CLI helper
# ---------------------------------------------------------------------------

def test_robust_sweep_blocks_before_any_write_or_solve():
    from tcad.characterization.robust_iv_sweep import run_robust_pn_junction_iv_sweep

    fake = FakeDevsim([-1.0, 1.0], [-1.0, -1.0])
    try:
        _with_fake(fake, lambda: run_robust_pn_junction_iv_sweep(
            device="dev", region="Si", all_contacts=["a", "b"], sweep_contact="b",
            sweep_voltages=[0.1], state=v2.advance(_supported_state(), None, step_seed="anneal")))
    except UnsupportedDopingState:
        assert fake.writes == [] and fake.solves == 0, (fake.writes, fake.solves)
        return
    raise AssertionError("robust sweep ran on an unsupported state")


def test_robust_continuation_ends_exactly_on_canonical_values():
    import tcad.characterization.robust_iv_sweep as robust

    state = _supported_state(1.0e17)
    state = v2.attach_dopant(
        state, species="As", polarity="donor", concentration_at=lambda x, y: 1.0e20,
        inventory_integral=v2.uniform_inventory_integral(1.0e20),
        support_instance_id="si#0", support_region_um=(0.0, 2.0, -2.0, 0.0),
        model="uniform_v1", model_params={"conc_cm3": 1.0e20}, step_seed="second", chemical_state="ACTIVE")
    fake = FakeDevsim([-1.0, 1.0], [-1.0, -1.0])
    history = []
    real_set = fake.set_node_values

    def recording_set(device, region, name, values):
        history.append(list(values))
        real_set(device, region, name, values)

    fake.set_node_values = recording_set
    original_setup = robust.setup_semiconductor_potential_equation
    robust.setup_semiconductor_potential_equation = lambda *a, **k: None
    try:
        _with_fake(fake, lambda: robust.ramp_doping_to_equilibrium("dev", "Si", state))
    finally:
        robust.setup_semiconductor_potential_equation = original_setup
    canonical = [state.net_doping_at(-1.0, -1.0).net_doping, state.net_doping_at(1.0, -1.0).net_doping]
    assert history[-1] == canonical, (history[-1], canonical)
    assert history[1][0] == 1.0e17, "the least-doped canonical level stays fixed while ramping"
    assert fake.solves == len(robust._DOPING_RAMP_SCALES)


def test_cli_netdoping_characterization_without_doping_is_blocked():
    from tcad.cli.run_pipeline import _apply_device_doping, _netdoping_region

    assert _netdoping_region({"type": "pn_junction_iv", "region": "Si"}) == "Si"
    assert _netdoping_region({"type": "mos_cv", "si_region": "Si"}) == "Si"
    assert _netdoping_region({"type": "iv", "region": "Si"}) is None

    fake = FakeDevsim([0.0], [0.0])
    imported = SimpleNamespace(device="cli_dev")
    no_doping = SimpleNamespace(doping=None)
    try:
        _with_fake(fake, lambda: _apply_device_doping(
            imported, no_doping, {"length_scale_to_cm": 1e-4}, None, netdoping_region="Si"))
    except UnsupportedDopingState:
        assert fake.writes == [] and fake.solves == 0 and set(fake.reads) <= {"x", "y"}
    else:
        raise AssertionError("pn_junction_iv/mos_cv without doping reached DevSim ungated")

    # A doping-independent characterization with no doping is unchanged.
    assert _with_fake(fake, lambda: _apply_device_doping(
        imported, no_doping, {}, None, netdoping_region=None)) is None


# ---------------------------------------------------------------------------
# Static scan: no production path hands a DopingProfile (the latest
# process result's `.doping`) or a rebuilt fallback state to a solve-path
# function. See the module docstring for what this does NOT prove.
# ---------------------------------------------------------------------------

PRODUCTION_FILES = sorted(
    [ROOT / "tcad_2d_stagewise.py", *(ROOT / "tcad").rglob("*.py"), *(ROOT / "examples").glob("*.py")]
)
SOLVE_PATH_FUNCTIONS = {
    "apply_doping", "canonical_node_doping", "apply_doping_symbolic",
    "run_robust_pn_junction_iv_sweep", "ramp_doping_to_equilibrium",
    "run_pn_junction_iv_sweep", "run_mos_cv_sweep", "run_iv_sweep",
    "run_mosfet_id_vgs_sweep", "run_mosfet_id_vds_sweep",
    "solve_mosfet_dc_operating_point",
}
GUI_MEASUREMENT_METHODS = {"run_measurement", "run_dc_operating_point"}


def _call_name(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def production_bypass_violations():
    violations = []
    for path in PRODUCTION_FILES:
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in SOLVE_PATH_FUNCTIONS:
                name = _call_name(node)
                if name == "apply_doping_symbolic":
                    violations.append(f"{rel}:{node.lineno} calls the DopingProfile writer apply_doping_symbolic")
                for kw in node.keywords:
                    if kw.arg == "doping":
                        violations.append(f"{rel}:{node.lineno} passes doping= to {name}")
                for value in list(node.args) + [kw.value for kw in node.keywords]:
                    for sub in ast.walk(value):
                        if isinstance(sub, ast.Attribute) and sub.attr == "doping":
                            violations.append(f"{rel}:{node.lineno} passes a .doping profile to {name}")
            if (isinstance(node, ast.FunctionDef) and node.name in GUI_MEASUREMENT_METHODS
                    and path.name == "tcad_2d_stagewise.py"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and _call_name(sub) == "advance_wafer_state":
                        violations.append(
                            f"{rel}:{sub.lineno} {node.name} rebuilds a fallback state via advance_wafer_state")
    return violations


def test_static_no_doping_profile_or_fallback_state_reaches_a_solve():
    violations = production_bypass_violations()
    assert not violations, "production measurement bypasses:\n" + "\n".join(violations)


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # report every failing check, then fail the file
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    if failed:
        raise SystemExit(f"{len(failed)} of {len(tests)} checks failed: {failed}")
    print(f"Central canonical-state gate: {len(tests)} checks passed -- every geometry-coverage and "
          "unknown-query counter-example blocks with 0 writes / 0 solves and full node "
          "diagnostics; supported states pass exact canonical values; static scan of "
          f"{len(PRODUCTION_FILES)} production files found 0 DopingProfile/fallback-state bypasses "
          "(it does not trace every solve back to the gate).")


if __name__ == "__main__":
    main()
