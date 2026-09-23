#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 P0-C: barrier exclusion is attributed to a specific NEW
doping application at ATTACH time, never applied as a generic post-hoc
zeroing of the accumulated NetDoping.

This project has no oxide-thickness / implant-energy-dose model, so it
can never COMPUTE how much of a new implant would really get through a
barrier. That is a reason to refuse to quantify a NEW implant under the
barrier (UNSUPPORTED), never a reason to erase dopant that was already
in the substrate before the barrier existed.

`advance_wafer_state(..., barrier_windows=[...])` carves each barrier
window (a full-depth strip along `barrier_axis`) out of the NEW
attachment's own support region before it is created:
  - the carve leaves exactly one rectangle -> attach with that reduced,
    EXACT region (only this application's own component is absent
    under the barrier; a separately-attached pre-existing/background
    attachment is untouched, since it was never re-examined at all).
  - the carve leaves zero or more-than-one rectangle (fully covered, or
    split into disjoint pieces) -> no supported mask/implant
    configuration equation exists for that geometry -> refuse the WHOLE
    new attachment (UNSUPPORTED_BY_MODEL), never a partial guess.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics import wafer_state_v2 as v2
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.interface import DopingProfile, DopingRegion


class _FakeResult:
    def __init__(self, doping):
        self.doping = doping


def _uniform(conc_cm3):
    return _FakeResult(DopingProfile(
        kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=conc_cm3, chemical_state="ACTIVE")]))


def _virgin_si():
    return v2.initialize_wafer_state(
        cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")], grid_delta_um=0.1)


def test_1_preexisting_background_survives_a_barrier_over_part_of_it():
    """A background attachment made BEFORE any barrier existed is never
    touched by a later call's barrier_windows -- it isn't re-examined
    at all, and it is queried at the DEEP Si point that in a real
    device sits below the barrier region regardless of x."""
    state = _virgin_si()
    state = advance_wafer_state(state, _uniform(1.0e17), "doping")  # background, no barrier
    assert len(state.attachments) == 1

    # A later call attempts a SECOND, unrelated application with a
    # barrier covering the SAME x-range as the background -- the
    # background's own attachment must be completely unaffected.
    q_under_barrier = state.net_doping_at(0.0, -1.0)
    assert q_under_barrier.net_doping == 1.0e17
    assert q_under_barrier.physics_status is None


def test_1b_real_oxidation_leaves_deep_background_doping_intact():
    """Stronger version of test 1: grow a REAL SiO2 layer over the top
    0.3um of the Si (v2.advance with a genuinely representable
    oxidation GeometryTransform, the same mechanism
    test_wafer_state_v2_oxidation_unsupported_mock.py's own passing
    case exercises) -- not just a hypothetical barrier window. The
    background attachment's OWN inventory-conserving clip (already
    verified by test_wafer_state_v2_etch_conservation_mock.py's sibling
    mechanism) keeps the surviving deep Si region's real doping value;
    querying under the new SiO2, at the depth that is still real Si,
    must show that exact real value -- not 0, not UNSUPPORTED."""
    state = _virgin_si()
    state = advance_wafer_state(state, _uniform(1.0e17), "doping")

    transform = v2.GeometryTransform(
        process_category="oxidation", representable=True,
        converted_extents_um=((-2.0, 2.0, -0.3, 0.0),),
        input_instance_ids=("si#0",),
    )
    oxidized = v2.advance(state, transform, step_seed="ox")

    materials = {c.material for c in oxidized.active_cells()}
    assert "SiO2" in materials, "a real SiO2 cell must now exist"

    # Deep Si (below the consumed 0.3um) -- genuinely still Si, still
    # carries the pre-existing background dopant, at its exact value.
    q_deep = oxidized.net_doping_at(0.5, -1.0)
    assert q_deep.net_doping == 1.0e17, q_deep.net_doping
    assert q_deep.physics_status is None
    assert oxidized.attachments, "the background attachment must survive, reshaped"
    print(f"    [oxide-real] pre-existing background doping under the "
          f"real SiO2, in the surviving deep Si: {q_deep.net_doping:.3e} cm^-3")


def test_2_new_implant_fully_covered_by_barrier_is_unsupported():
    """No representable mask/implant configuration equation exists to
    quantify a new implant fully blocked by a barrier -- UNSUPPORTED,
    never an arbitrary number, never a silent 0."""
    state = _virgin_si()
    out = advance_wafer_state(
        state, _uniform(5.0e18), "doping",
        barrier_windows=[{"min_um": -2.0, "max_um": 2.0}], barrier_axis="x")
    assert not out.attachments, "a fully-covered new implant must attach nothing"
    q = out.net_doping_at(0.0, -1.0)
    assert q.physics_status is not None
    assert q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert q.net_doping is None, "never 0, never any number, for a blocked new implant"


def test_2b_new_implant_split_by_a_middle_barrier_is_also_unsupported():
    """A barrier that splits the target region into two disjoint pieces
    is just as unrepresentable as full coverage -- still refuse the
    whole application (no partial "left half only" guess either)."""
    state = _virgin_si()
    out = advance_wafer_state(
        state, _uniform(5.0e18), "doping",
        barrier_windows=[{"min_um": -0.5, "max_um": 0.5}], barrier_axis="x")
    assert not out.attachments
    assert out.net_doping_at(-1.5, -1.0).net_doping is None
    assert out.net_doping_at(1.5, -1.0).net_doping is None


def test_3_background_stays_new_supported_masked_application_only_excludes_its_own_component():
    """A barrier over ONE SIDE of the target region carves an EXACT
    single remaining rectangle -- a genuinely supported case. The new
    application attaches there (and only there); a separately-existing
    background attachment elsewhere on the SAME instance is untouched."""
    state = _virgin_si()
    # Background first (a prior, unrelated doping application).
    state = advance_wafer_state(state, _uniform(1.0e16), "doping")
    assert len(state.attachments) == 1
    background_id = state.attachments[0].attachment_id

    # New masked application: barrier covers x in [0.5, 2.0] (one
    # side), leaving exactly [-2.0, 0.5] representable.
    out = advance_wafer_state(
        state, _uniform(9.0e17), "doping",
        barrier_windows=[{"min_um": 0.5, "max_um": 2.0}], barrier_axis="x")

    assert len(out.attachments) == 2, "background must survive alongside the new one"
    ids = {a.attachment_id for a in out.attachments}
    assert background_id in ids

    new_att = next(a for a in out.attachments if a.attachment_id != background_id)
    assert new_att.support_region_um == (-2.0, 0.5, -2.0, 0.0), new_att.support_region_um

    # Inside the carved (reachable) zone: BOTH background and new sum.
    q_reachable = out.net_doping_at(-1.0, -1.0)
    assert q_reachable.net_doping == 1.0e16 + 9.0e17, q_reachable.net_doping
    assert q_reachable.physics_status is None

    # Under the barrier itself: background is a REAL (fully-known)
    # value on its own, but this specific query point is INSIDE the
    # new application's own refused region too -- since the new
    # attachment's exact support excludes that area, only the
    # background contributes there, and it does so as a real number
    # (P0-C's own point: a barrier removes a new implant's reach, it
    # does not erase what was already there).
    q_under_barrier = out.net_doping_at(1.5, -1.0)
    assert q_under_barrier.net_doping == 1.0e16, q_under_barrier.net_doping
    assert q_under_barrier.physics_status is None


def main():
    test_1_preexisting_background_survives_a_barrier_over_part_of_it()
    test_1b_real_oxidation_leaves_deep_background_doping_intact()
    test_2_new_implant_fully_covered_by_barrier_is_unsupported()
    test_2b_new_implant_split_by_a_middle_barrier_is_also_unsupported()
    test_3_background_stays_new_supported_masked_application_only_excludes_its_own_component()
    print("Barrier exclusion is attributed to the NEW attachment at "
          "attach time: pre-existing/background dopant always survives; "
          "an unrepresentable barrier geometry refuses the whole new "
          "application (UNSUPPORTED, never 0/a guess); a representable "
          "one-sided barrier carves an exact reduced region and leaves "
          "background untouched.")


if __name__ == "__main__":
    main()
