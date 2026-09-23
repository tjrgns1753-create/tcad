#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 P0-A: explicit doping TARGET resolution.

`advance_wafer_state()` used to bind a doping application to "the
first ACTIVE+MODELLED cell whose material NAME matches" via
`_instance_for_host()`/`_support_for_host()` -- both deleted. That is
ambiguous whenever more than one instance of the same material exists
(an original substrate plus a later re-deposited layer of the same
material), and wrong whenever a single instance has been split across
more than one cell by an earlier etch/oxidation (it would silently
bind to whichever cell happened to be first in the list).

`_resolve_doping_target()` replaces it: an explicit `target_instance_id`
always wins (when it resolves to EXACTLY one ACTIVE+MODELLED cell); with
no explicit target, auto-selection is allowed ONLY when there is exactly
one candidate instance and it is exactly one cell. Every other case
fails closed -- no attachment, `UNSUPPORTED_BY_MODEL`, never a silent
first-match guess.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics import wafer_state_v2 as v2
from tcad.physics.wafer_state_accumulation import advance_wafer_state, _resolve_doping_target
from tcad.physics.dopant_profile import DopantProfile
from tcad.mesh.interface import DopingProfile, DopingRegion


class _FakeResult:
    """Minimal stand-in for ProcessResult -- advance_wafer_state only
    ever reads `.doping` in the doping branch when prior_state is
    already non-None (which every scenario here guarantees)."""
    def __init__(self, doping):
        self.doping = doping


def _profile(model_params):
    return DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, y: model_params["conc_cm3"],
        host_material="Si", model="uniform_v1", model_params=model_params,
    )


def _fake_uniform_doping_result(conc_cm3):
    """A real DopingProfile/DopingRegion (not a raw DopantProfile) so
    `dopant_profiles_from_doping_profile()` -- the real production
    adapter advance_wafer_state() calls -- is exercised end to end,
    matching exactly what run_doping()/apply_uniform_doping() build."""
    return _FakeResult(DopingProfile(
        kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=conc_cm3, chemical_state="ACTIVE")]))


def _two_si_instances():
    """original Si (x<0) + a later re-deposited Si (x>0) -- two DISTINCT
    ACTIVE+MODELLED instances sharing the same material name."""
    original = v2.MaterialCell(
        cell_id="c1", material="Si", bounds_um=(-2.0, 0.0, -2.0, 0.0),
        material_instance_id="si#original", lineage=(), lifecycle="ACTIVE")
    redeposited = v2.MaterialCell(
        cell_id="c2", material="Si", bounds_um=(0.0, 2.0, -2.0, 0.0),
        material_instance_id="si#redeposited", lineage=(), lifecycle="ACTIVE")
    return v2.WaferStateV2(cells=(original, redeposited))


def _split_single_instance(order=("a", "b")):
    """ONE instance ("si#0") split into two disjoint cells -- the
    geometry a real etch through the middle of a substrate produces."""
    left = v2.MaterialCell(
        cell_id="c1", material="Si", bounds_um=(-2.0, 0.0, -2.0, 0.0),
        material_instance_id="si#0", lineage=(), lifecycle="ACTIVE")
    right = v2.MaterialCell(
        cell_id="c2", material="Si", bounds_um=(0.0, 2.0, -2.0, 0.0),
        material_instance_id="si#0", lineage=(), lifecycle="ACTIVE")
    cells = (left, right) if order == ("a", "b") else (right, left)
    return v2.WaferStateV2(cells=cells)


def test_1_two_instances_no_target_is_unsupported():
    state = _two_si_instances()
    out = advance_wafer_state(state, _fake_uniform_doping_result(1.0e17), "doping")
    assert not out.attachments, "an ambiguous target must attach nothing"
    q_left = out.net_doping_at(-1.0, -1.0)
    q_right = out.net_doping_at(1.0, -1.0)
    assert q_left.physics_status is not None and q_left.net_doping is None
    assert q_right.physics_status is not None and q_right.net_doping is None


def test_2_original_target_attaches_only_to_original():
    state = _two_si_instances()
    out = advance_wafer_state(
        state, _fake_uniform_doping_result(1.0e17), "doping",
        target_instance_id="si#original")
    assert len(out.attachments) == 1
    assert out.attachments[0].support_instance_id == "si#original"
    q_left = out.net_doping_at(-1.0, -1.0)
    q_right = out.net_doping_at(1.0, -1.0)
    assert q_left.net_doping == 1.0e17
    assert q_right.net_doping == 0.0  # real Si, genuinely no attachment there


def test_3_redeposited_target_attaches_only_to_redeposited():
    state = _two_si_instances()
    out = advance_wafer_state(
        state, _fake_uniform_doping_result(2.0e17), "doping",
        target_instance_id="si#redeposited")
    assert len(out.attachments) == 1
    assert out.attachments[0].support_instance_id == "si#redeposited"
    q_left = out.net_doping_at(-1.0, -1.0)
    q_right = out.net_doping_at(1.0, -1.0)
    assert q_left.net_doping == 0.0
    assert q_right.net_doping == 2.0e17


def test_4_split_instance_never_attaches_to_only_the_first_cell():
    """Whether or not an explicit target is given, a split instance
    cannot be represented by one exact Bounds -- it must refuse
    entirely, never silently bind to whichever cell happened to be
    first."""
    for order in (("a", "b"), ("b", "a")):
        state = _split_single_instance(order)
        out = advance_wafer_state(
            state, _fake_uniform_doping_result(1.0e17), "doping",
            target_instance_id="si#0")
        assert not out.attachments, (
            f"a split instance must refuse the whole attachment "
            f"(order={order}), not bind to one cell")
        # Neither half may show a doping number -- if it had silently
        # bound to "the first cell", one half would read 1e17.
        assert out.net_doping_at(-1.0, -1.0).net_doping is None
        assert out.net_doping_at(1.0, -1.0).net_doping is None


def test_5_cell_list_order_never_changes_the_result():
    for order in (("a", "b"), ("b", "a")):
        state = _split_single_instance(order)
        inst, region = _resolve_doping_target(state, "Si", "si#0")
        assert inst is None and region is None, f"order={order}"

    # Two-instance ambiguous case, both list orders.
    fwd = _two_si_instances()
    rev = v2.WaferStateV2(cells=tuple(reversed(fwd.cells)))
    for state in (fwd, rev):
        inst, region = _resolve_doping_target(state, "Si", None)
        assert inst is None and region is None


def test_unambiguous_single_instance_auto_selects_without_a_target():
    """Backward-compatible convenience: exactly one candidate instance,
    exactly one cell -- no explicit target needed."""
    state = v2.initialize_wafer_state(
        cells=[("Si", (-2.0, 2.0, -2.0, 0.0), "si#0")], grid_delta_um=0.1)
    out = advance_wafer_state(state, _fake_uniform_doping_result(3.0e17), "doping")
    assert len(out.attachments) == 1
    assert out.attachments[0].support_instance_id == "si#0"


def test_instance_for_host_helpers_removed():
    import tcad.physics.wafer_state_accumulation as mod
    assert not hasattr(mod, "_instance_for_host")
    assert not hasattr(mod, "_support_for_host")


def main():
    test_1_two_instances_no_target_is_unsupported()
    test_2_original_target_attaches_only_to_original()
    test_3_redeposited_target_attaches_only_to_redeposited()
    test_4_split_instance_never_attaches_to_only_the_first_cell()
    test_5_cell_list_order_never_changes_the_result()
    test_unambiguous_single_instance_auto_selects_without_a_target()
    test_instance_for_host_helpers_removed()
    print("Explicit doping target resolution: ambiguous multi-instance "
          "material names and split instances fail closed instead of "
          "picking the first cell; an explicit target_instance_id binds "
          "correctly; order-independent; _instance_for_host/"
          "_support_for_host are gone.")


if __name__ == "__main__":
    main()
