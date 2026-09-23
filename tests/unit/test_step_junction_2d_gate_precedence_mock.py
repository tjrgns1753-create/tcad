#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7E Rev.1 -- the required reason-PRECEDENCE tests (section 2).

`canonical_node_doping()`'s correct judgment order (Batch 7E Rev.1's own
contract, restated in its and `UnsupportedDopingState`'s docstrings):
  1. canonical state exists
  2. bounded geometry
  3. exact per-node cell ownership
  4. lifecycle / activation state
  5. donor/acceptor/net all fully known
  6. THEN region-level transport capability: compensated transport, then
     (only if that found nothing) 2D step-junction mesh convergence
  7. only then are the donor/acceptor/net arrays returned
  8. the actual node-model write happens later still, in apply_doping()

Every case here builds a state that -- before Batch 7E Rev.1's reordering
-- risked being masked by the wrong reason, and confirms which reason
actually surfaces, with 0 node-model writes and 0 solves in every case
(canonical_node_doping() itself never writes or solves either way).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tcad.device.devsim import backend  # noqa: E402
from tcad.device.devsim.doping_mapping import (  # noqa: E402
    UnsupportedDopingState, apply_doping, canonical_node_doping,
)
from tcad.physics import wafer_state_v2 as v2  # noqa: E402
from tcad.physics.wafer_state_v2 import MaterialCell, WaferStateV2  # noqa: E402

STEP_REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"
COMP_REASON = "COMPENSATED_TRANSPORT_MODEL_MISSING"


class FakeDevsim:
    """Like the established pattern in test_measurement_canonical_state_gate_mock.py,
    plus get_dimension() -- called only when a step_junction_v1 ACTIVE attachment is
    actually present (short-circuited), so every non-step-junction case below never
    needs it at all."""

    def __init__(self, xs, ys, dimension=2):
        self._nodes = {"x": list(xs), "y": list(ys)}
        self.writes = []
        self.solves = 0
        self.dimension_calls = 0
        self._dimension = dimension

    def get_node_model_values(self, device, region, name):
        return list(self._nodes[name])

    def node_model(self, device, region, name, equation):
        self.writes.append(("node_model", name))

    def set_node_values(self, device, region, name, values):
        self.writes.append(("set_node_values", name))
        self._nodes[name] = list(values)

    def solve(self, **kwargs):
        self.solves += 1

    def get_dimension(self, device):
        self.dimension_calls += 1
        return self._dimension


def _with_fake(fake, fn):
    original = backend.require_devsim
    backend.require_devsim = lambda: fake
    try:
        return fn()
    finally:
        backend.require_devsim = original


def _step_junction(state, instance_id, bounds, position_um=0.0, conc=1.0e17, chemical_state="ACTIVE", seed="sj"):
    """Attach an official-convention step junction (donor: x>=position, acceptor:
    x<=position) to `instance_id`, mirroring _step_junction_profiles()'s own model
    tag exactly ("step_junction_v1")."""
    state = v2.attach_dopant(
        state, species="P", polarity="donor", chemical_state=chemical_state,
        concentration_at=lambda x, y, p=position_um, c=conc: c if x >= p else 0.0,
        support_instance_id=instance_id, support_region_um=bounds,
        model="step_junction_v1", model_params={"conc_cm3": conc, "junction_position_um": position_um},
        inventory_integral=v2.uniform_inventory_integral(conc), step_seed=f"{seed}d",
    )
    state = v2.attach_dopant(
        state, species="B", polarity="acceptor", chemical_state=chemical_state,
        concentration_at=lambda x, y, p=position_um, c=conc: c if x <= p else 0.0,
        support_instance_id=instance_id, support_region_um=bounds,
        model="step_junction_v1", model_params={"conc_cm3": conc, "junction_position_um": position_um},
        inventory_integral=v2.uniform_inventory_integral(conc), step_seed=f"{seed}a",
    )
    return state


def _uniform(state, instance_id, bounds, conc=1.0e17, polarity="acceptor", seed="u"):
    return v2.attach_dopant(
        state, species="B" if polarity == "acceptor" else "P", polarity=polarity, chemical_state="ACTIVE",
        concentration_at=lambda x, y, c=conc: c,
        inventory_integral=v2.uniform_inventory_integral(conc),
        support_instance_id=instance_id, support_region_um=bounds,
        model="uniform_v1", model_params={"conc_cm3": conc}, step_seed=seed,
    )


def _clean_2d_step_junction_state():
    state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#0")])
    return _step_junction(state, "si#0", (-2.0, 2.0, -1.0, 0.0))


# ---------------------------------------------------------------------- 1. valid geometry + 2D step junction
def test_1_valid_geometry_2d_step_junction_blocked_by_mesh_convergence():
    state = _clean_2d_step_junction_state()
    fake = FakeDevsim([1.0], [-0.5], dimension=2)
    try:
        _with_fake(fake, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=1.0))
    except UnsupportedDopingState as exc:
        assert exc.physics_status["reason_code"] == STEP_REASON, exc.physics_status
        assert fake.dimension_calls == 1, "get_dimension must be queried exactly once for this state"
    else:
        raise AssertionError("expected UnsupportedDopingState")
    assert fake.writes == [] and fake.solves == 0
    print(f"1. valid geometry + ACTIVE step_junction + 2D -> {STEP_REASON} (get_dimension called {fake.dimension_calls}x)")


# ---------------------------------------------------------------------- 2. overlapping cells + step junction + 2D
def test_2_geometry_overlap_reason_not_masked_by_mesh_convergence():
    """Two cells overlap with POSITIVE area (a real geometry inconsistency,
    test_measurement_canonical_state_gate_mock.py's own
    test_positive_area_overlap_still_blocks pattern) on an instance that ALSO
    carries an ACTIVE step_junction_v1 attachment elsewhere on the SAME
    region. The per-node ownership check must block on the OVERLAP reason,
    never reaching the region-level step-junction check at all."""
    state = WaferStateV2(cells=(
        MaterialCell("csi", "Si", (-2.0, 2.0, -1.0, 0.05), "si#0"),
        MaterialCell("cox", "SiO2", (-2.0, 2.0, 0.0, 0.1), "ox#0"),
    ))
    state = _step_junction(state, "si#0", (-2.0, 2.0, -1.0, 0.05))
    assert v2.active_step_junction_instances(state, "Si") == ["si#0"], \
        "fixture check: this state DOES carry an ACTIVE step_junction_v1 on Si"

    fake = FakeDevsim([0.5], [0.02], dimension=2)  # the node sits IN the overlap band (y in [0, 0.05])
    try:
        _with_fake(fake, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=1.0))
    except UnsupportedDopingState as exc:
        assert "reason_code" not in exc.physics_status or exc.physics_status.get("reason_code") != STEP_REASON, \
            f"the overlap must not be masked by the mesh-convergence reason: {exc.physics_status}"
        assert "physically overlap over a positive area" in str(exc), str(exc)
        assert fake.dimension_calls == 0, \
            "get_dimension must never be reached -- the per-node overlap block happens first"
    else:
        raise AssertionError("expected UnsupportedDopingState (overlap)")
    assert fake.writes == [] and fake.solves == 0
    print("2. overlapping bounded cells + ACTIVE step_junction + 2D -> the pre-existing geometry/ownership "
          "reason (positive-area overlap), NOT masked by STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED "
          "(get_dimension never even called)")


# ---------------------------------------------------------------------- 3. LEGACY_UNRESOLVED + attempted step junction
def test_3_legacy_unresolved_reason_not_masked_by_mesh_convergence():
    """A LEGACY_UNRESOLVED instance cannot carry a real ACTIVE attachment at
    all (attach_dopant refuses -- it is not ACTIVE + MODELLED), so an
    attempted step-junction doping on it produces no active attachment; the
    gate blocks with the PRE-EXISTING LEGACY_UNRESOLVED reason, unaffected
    by the new region-level check."""
    legacy = v2.legacy_state_from_v1_cells([SimpleNamespace(material="Si")])
    attempted = _step_junction(legacy, "legacy#does-not-exist", (-2.0, 2.0, -1.0, 0.0))
    assert v2.active_step_junction_instances(attempted, "Si") == [], \
        "fixture check: attach_dopant must have refused -- no ACTIVE attachment on a LEGACY_UNRESOLVED instance"
    assert any(e.model_status == "UNSUPPORTED_BY_MODEL" for e in attempted.events), \
        "the refused attach attempt must still be recorded as its own event"

    fake = FakeDevsim([0.0], [-0.5], dimension=2)
    try:
        _with_fake(fake, lambda: apply_doping("dev", "Si", attempted, length_scale_to_cm=1.0))
    except UnsupportedDopingState as exc:
        assert exc.physics_status.get("reason_code") != STEP_REASON, exc.physics_status
        assert "LEGACY_UNRESOLVED" in str(exc) and "has no exact bounds" in str(exc), str(exc)
        assert fake.dimension_calls == 0, "get_dimension must never be reached for a state-level block"
    else:
        raise AssertionError("expected UnsupportedDopingState (LEGACY_UNRESOLVED)")
    assert fake.writes == [] and fake.solves == 0
    print("3. LEGACY_UNRESOLVED + attempted step-junction doping -> the pre-existing canonical geometry "
          "reason (attach_dopant already refused the attachment), get_dimension never called")


# ---------------------------------------------------------------------- 4. CHEMICAL/UNKNOWN step junction
def test_4_chemical_unknown_step_junction_blocked_by_activation_reason():
    for chemical_state in ("CHEMICAL", "UNKNOWN"):
        state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#0")])
        state = _step_junction(state, "si#0", (-2.0, 2.0, -1.0, 0.0), chemical_state=chemical_state)
        assert v2.active_step_junction_instances(state, "Si") == [], \
            f"fixture check: a {chemical_state} attachment must not count as ACTIVE for the new gate"

        fake = FakeDevsim([1.0], [-0.5], dimension=2)
        try:
            _with_fake(fake, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=1.0))
        except UnsupportedDopingState as exc:
            assert exc.physics_status.get("reason_code") != STEP_REASON, exc.physics_status
            assert "dopant_activation_state" in str(exc) or f"chemical_state '{chemical_state}'" in str(exc), str(exc)
            assert fake.dimension_calls == 0, "get_dimension must never be reached for a per-node activation block"
        else:
            raise AssertionError(f"expected UnsupportedDopingState ({chemical_state})")
        assert fake.writes == [] and fake.solves == 0
        print(f"4. {chemical_state} step_junction_v1 -> the pre-existing activation reason, "
              f"get_dimension never called")


# ---------------------------------------------------------------------- 5. finite-area compensated (unaffected regression)
def test_5_compensated_doping_unaffected_by_step_junction_gate():
    state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#0")])
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.0), 1.0e17, polarity="donor", seed="d")
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.0), 1.0e17, polarity="acceptor", seed="a")
    assert v2.active_step_junction_instances(state, "Si") == [], "fixture check: no step_junction_v1 here at all"

    fake = FakeDevsim([0.0], [-0.5], dimension=2)
    try:
        _with_fake(fake, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=1.0))
    except UnsupportedDopingState as exc:
        assert exc.physics_status["reason_code"] == COMP_REASON, exc.physics_status
        assert fake.dimension_calls == 0, "get_dimension must never be called -- no step_junction_v1 attachment exists"
    else:
        raise AssertionError("expected UnsupportedDopingState (compensated)")
    assert fake.writes == [] and fake.solves == 0
    print(f"5. finite-area compensated uniform doping (no step_junction_v1) -> {COMP_REASON}, unchanged "
          "by the new gate")


# ---------------------------------------------------------------------- 6. co-occurrence: both problems on the same region
def test_6_cooccurring_compensation_and_step_junction_neither_silently_dropped():
    """A real, if unusual, state: an ACTIVE step_junction_v1 (donor x>=0,
    acceptor x<=0) PLUS a separately-attached uniform ACTIVE acceptor
    covering the WHOLE instance -- the uniform acceptor overlaps the step
    junction's donor half (x>=0) with positive area, so this region has
    BOTH a compensated-transport problem AND an ACTIVE step_junction_v1
    attachment simultaneously. COMPENSATED_TRANSPORT_MODEL_MISSING is the
    reported reason_code (checked first), but the co-occurring step-
    junction problem must be named in the message/notes, not silently
    dropped."""
    state = v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#0")])
    state = _step_junction(state, "si#0", (-2.0, 2.0, -1.0, 0.0), seed="sj")
    state = _uniform(state, "si#0", (-2.0, 2.0, -1.0, 0.0), 1.0e16, polarity="acceptor", seed="extra")
    assert v2.active_step_junction_instances(state, "Si") == ["si#0"], "fixture check: step_junction_v1 present"
    assert v2.compensated_transport_problems(state, "Si"), "fixture check: a compensated pair must also exist"

    fake = FakeDevsim([1.0], [-0.5], dimension=2)
    try:
        _with_fake(fake, lambda: apply_doping("dev", "Si", state, length_scale_to_cm=1.0))
    except UnsupportedDopingState as exc:
        status = exc.physics_status
        assert status["reason_code"] == COMP_REASON, \
            f"compensation takes precedence as the reported reason_code: {status}"
        assert STEP_REASON in str(exc), \
            f"the co-occurring step-junction problem must be named, not silently dropped: {exc}"
        assert any(STEP_REASON in n for n in status.get("notes", [])), status["notes"]
        # get_dimension IS still called here (unlike cases 2-5): the gate must
        # evaluate whether a step-junction problem ALSO exists (to name it in
        # the notes, not silently drop it) even though compensation ends up
        # as the reported reason_code.
        assert fake.dimension_calls == 1, fake.dimension_calls
    else:
        raise AssertionError("expected UnsupportedDopingState (compensated, with step-junction noted)")
    assert fake.writes == [] and fake.solves == 0
    print(f"6. co-occurring compensation + step_junction on the SAME region -> reason_code={COMP_REASON} "
          f"(precedence), step-junction problem still named in notes (not silently dropped), reasons never merged")


def main():
    test_1_valid_geometry_2d_step_junction_blocked_by_mesh_convergence()
    test_2_geometry_overlap_reason_not_masked_by_mesh_convergence()
    test_3_legacy_unresolved_reason_not_masked_by_mesh_convergence()
    test_4_chemical_unknown_step_junction_blocked_by_activation_reason()
    test_5_compensated_doping_unaffected_by_step_junction_gate()
    test_6_cooccurring_compensation_and_step_junction_neither_silently_dropped()
    print("\nPASS: canonical_node_doping()'s judgment order is geometry/ownership/activation FIRST, "
          "region-level transport capability (compensation, then 2D step-junction mesh convergence) LAST -- "
          "no reason is ever masked or silently dropped, and every blocked case writes 0 node models and "
          "runs 0 solves.")


if __name__ == "__main__":
    main()
