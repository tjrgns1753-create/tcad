#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""advance_wafer_state()'s `result` contract: metadata is optional, and
result=None is legal only for a non-doping step advanced from an existing
prior_state. Pure Python -- no ViennaPS/DevSim/Tk.

A. metadata-less valid doping result -> a real attachment
B. prior state + result=None + anneal -> fail-closed, no AttributeError
C. prior_state=None + result=None -> ValueError
D. doping + result=None -> ValueError
E. oxidation result with NO metadata -> fail-closed, never identity
F. the canonical inherited zero-duration identity -> `out is prior_state`; identity+inherited=False -> fail-closed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult
from tcad.physics.wafer_state_accumulation import (
    advance_wafer_state, initial_wafer_state_from_recipe,
)
from tcad.physics.wafer_state_v2 import attach_dopant, uniform_inventory_integral

IDENTITY = {"kind": "identity", "reason": "zero_duration_oxidation",
            "category": "oxidation", "inherited": True}


class _NoMetadata:
    """A result with only `.doping` -- no `.metadata` attribute at all."""
    def __init__(self, doping=None):
        self.doping = doping


def _uniform(conc):
    return DopingProfile(kind="uniform",
                         regions=[DopingRegion(region="Si", net_doping_cm3=conc, chemical_state="ACTIVE")])


def _state():
    return initial_wafer_state_from_recipe(
        {"x_extent_um": 2.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.05})


def _doped_state():
    s = _state()
    return attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1e17,
        support_instance_id=s.cells[0].material_instance_id,
        support_region_um=(-1.0, 1.0, -1.0, 0.0), model="uniform_v1",
        inventory_integral=uniform_inventory_integral(1e17), chemical_state="ACTIVE")


def test_A_metadata_less_doping_result_attaches():
    out = advance_wafer_state(_state(), _NoMetadata(_uniform(1e17)), "doping")
    assert len(out.attachments) == 1, out.attachments
    assert out.net_doping_at(0.0, -0.5).net_doping == 1e17
    print("PASS A: metadata-less doping result -> 1 real attachment, query 1e17")


def test_B_anneal_result_none_fails_closed():
    prior = _doped_state()
    assert prior.net_doping_at(0.0, -0.5).donor_concentration == 1e17
    out = advance_wafer_state(prior, None, "anneal", transform=None)
    assert not out.attachments, "active dopant must leave the active set"
    assert any(u.origin_attachment_id == prior.attachments[0].attachment_id
               for u in out.unresolved_inventory), "dopant must go to the ledger"
    q = out.net_doping_at(0.0, -0.5)
    assert q.net_doping is None
    assert (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"
    assert out.events[-1].process_category == "anneal"
    print("PASS B: anneal + result=None -> fail-closed, ledger entry, query UNSUPPORTED")


def test_C_no_prior_no_result_raises():
    try:
        advance_wafer_state(None, None, "anneal")
    except ValueError as exc:
        print(f"PASS C: prior=None + result=None -> ValueError ({exc})")
        return
    raise AssertionError("expected ValueError")


def test_D_doping_result_none_raises():
    for prior in (None, _state()):
        try:
            advance_wafer_state(prior, None, "doping")
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for doping/None (prior={prior is not None})")
    print("PASS D: doping + result=None -> ValueError (with and without prior)")


def test_E_oxidation_without_metadata_is_not_identity():
    prior = _doped_state()
    out = advance_wafer_state(prior, _NoMetadata(), "oxidation")
    assert out is not prior
    assert out.net_doping_at(0.0, -0.5).net_doping is None
    # also: metadata present but not a dict, and a dict without the transition
    for bad in (ProcessResult(volume_mesh_path="x", metadata={}),):
        out2 = advance_wafer_state(prior, bad, "oxidation")
        assert out2 is not prior and out2.net_doping_at(0.0, -0.5).net_doping is None
    class _BadMeta(_NoMetadata):
        metadata = "not-a-dict"
    out3 = advance_wafer_state(prior, _BadMeta(), "oxidation")
    assert out3 is not prior
    print("PASS E: oxidation with missing/non-dict/empty metadata -> fail-closed, never identity")


def test_F_exact_identity_preserves_object():
    prior = _doped_state()
    res = ProcessResult(volume_mesh_path="x", metadata={"state_transition": dict(IDENTITY)})
    assert advance_wafer_state(prior, res, "oxidation") is prior
    # `inherited=False` is NOT an identity: the step received no domain and built a
    # new one, so nothing proves `prior` describes it. The old "fresh identity"
    # dict (kind=identity + inherited=False) is malformed and fails closed; the
    # real fresh result is a `materialization` (see
    # test_zero_duration_identity_state_contract_mock.py).
    old_fresh = ProcessResult(volume_mesh_path="x",
                              metadata={"state_transition": dict(IDENTITY, inherited=False)})
    out = advance_wafer_state(prior, old_fresh, "oxidation")
    assert out is not prior and out.attachments == ()
    # A genuine near-miss (different reason) is still fail-closed.
    near = dict(IDENTITY, reason="zero_duration")
    res2 = ProcessResult(volume_mesh_path="x", metadata={"state_transition": near})
    assert advance_wafer_state(prior, res2, "oxidation") is not prior
    print("PASS F: inherited identity dict -> out is prior_state; identity+inherited=False and near-miss -> fail-closed")


def main():
    test_A_metadata_less_doping_result_attaches()
    test_B_anneal_result_none_fails_closed()
    test_C_no_prior_no_result_raises()
    test_D_doping_result_none_raises()
    test_E_oxidation_without_metadata_is_not_identity()
    test_F_exact_identity_preserves_object()
    print("\nALL advance_wafer_state RESULT-CONTRACT TESTS PASS")


if __name__ == "__main__":
    main()
