#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7C -- dopant activation state + compensation truthfulness, at the state-engine level (no GUI, no ViennaPS, no DevSim install).

Fixed physical contract under test:
  * donor N_D and acceptor N_A are two separate canonical quantities; a net is only ever derived (net = N_D - N_A). N_D == N_A != 0 is a
    compensated profile, neither a zero doping nor a no-op: one donor and one acceptor attachment must both exist.
  * chemical_state is exactly CHEMICAL | ACTIVE | UNKNOWN and is a real gate: only ACTIVE dopant is electrically usable. A CHEMICAL or
    UNKNOWN attachment covering a point makes donor/acceptor/net all None + UNSUPPORTED_BY_MODEL (never 0.0, never summed as ACTIVE), and the
    DevSim mapping then writes 0 node models and runs 0 solves.
  * an invalid state string raises ValueError at every entry (attach_dopant, DopantAttachment, DopantProfile, the doping helpers).
  * a re-attach is only THIS request's own canonical attachment(s): same material instance, model, exact params, species, polarity and
    chemical state -- another, unrelated attachment on the wafer never counts.
  * one doping request is atomic: if any of its profiles cannot be attached, NO active attachment of it remains; prior attachments are
    preserved, refusal provenance + ledger are recorded, and no number is invented.

The DevSim boundary here is a recording fake; the same contract on a REAL DevSim device is test_dopant_activation_devsim_gate_real.py.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.device.devsim.doping_mapping as dm
import tcad.physics.wafer_state_v2 as v2
from tcad.mesh.interface import DopingProfile, DopingRegion
from tcad.physics.doping import (
    apply_gaussian_implant_doping, apply_implant_windows_doping, apply_step_junction_doping, apply_uniform_doping,
)
from tcad.mesh.interface import ProcessResult
from tcad.physics.dopant_profile import DopantProfile, dopant_profiles_from_doping_profile
from tcad.physics.wafer_state_accumulation import advance_wafer_state, canonical_doping_request_matches

SI = (-2.0, 2.0, -1.0, 0.0)
PR = ProcessResult(volume_mesh_path="unused.vtu")


def expect_fail(check, label, expected):
    """A mutant must fail `check`, for the stated reason (str, or tuple that must all appear)."""
    try:
        check()
    except AssertionError as exc:
        text = str(exc)
        missing = [n for n in ((expected,) if isinstance(expected, str) else tuple(expected)) if n not in text]
        assert not missing, f"WRONG FAILURE REASON for guard {label!r}: expected {missing} in {text!r}"
        return
    raise AssertionError(f"FALSE GREEN: guard {label!r} was accepted")


def base():
    return v2.initialize_wafer_state(cells=[("Si", SI, "si#substrate")], grid_delta_um=0.2)


def uniform(donor, acceptor, state="ACTIVE"):
    return apply_uniform_doping(PR, donor_by_region_cm3={"Si": donor}, acceptor_by_region_cm3={"Si": acceptor}, chemical_state=state)


def q(state, x=0.0, y=-0.5):
    r = state.net_doping_at(x, y)
    return r.donor_concentration, r.acceptor_concentration, r.net_doping, r.physics_status


# ---- the contract checks (the same functions judge the real runs and the guards' mutants) ----------------------------------------
def check_compensated(state, donor, acceptor):
    atts = state.attachments
    by = {a.polarity: [x for x in atts if x.polarity == a.polarity] for a in atts}
    assert sorted(by) == ["acceptor", "donor"] and len(by["donor"]) == 1 and len(by["acceptor"]) == 1, \
        f"compensation needs exactly one donor and one acceptor attachment, got {[(a.polarity) for a in atts]}"
    assert all(a.chemical_state == "ACTIVE" for a in atts), [a.chemical_state for a in atts]
    assert by["donor"][0].model_params["conc_cm3"] == donor and by["acceptor"][0].model_params["conc_cm3"] == acceptor, \
        "both requested values must be kept in the canonical provenance"
    d, a, n, status = q(state)
    assert (d, a, n) == (donor, acceptor, donor - acceptor) and status is None, f"query {(d, a, n, status)}"
    assert not state.unresolved_inventory, "a compensated profile must not create a ledger entry"


def check_gate_none(state, label):
    d, a, n, status = q(state)
    assert (d, a, n) == (None, None, None), f"{label}: expected all three None, got {(d, a, n)}"
    assert status and status["resolution"] == "UNSUPPORTED_BY_MODEL", f"{label}: physics_status {status}"
    assert "dopant_activation_state" in str(status), f"{label}: the status must name the activation state: {status}"


class FakeDevsim:
    """Recording DevSim: only what canonical_node_doping()/apply_doping() call."""

    def __init__(self, points):
        self.points, self.writes, self.solves = points, [], 0

    def get_node_model_values(self, device, region, name):
        return [p[0] if name == "x" else p[1] for p in self.points]

    def node_model(self, **k):
        self.writes.append(("node_model", k.get("name")))

    def set_node_values(self, **k):
        self.writes.append(("set_node_values", k.get("name")))

    def solve(self, **k):
        self.solves += 1


def run_mapping(state, points=((0.0, -0.5), (1.0, -0.25))):
    fake = FakeDevsim(list(points))
    with patch.object(dm.backend, "require_devsim", lambda: fake):
        try:
            dm.apply_doping("dev", "Si", state)
            outcome = "written"
        except dm.UnsupportedDopingState as exc:
            outcome = ("blocked", str(exc))
    return outcome, fake


def check_devsim_blocked(state, label):
    outcome, fake = run_mapping(state)
    assert isinstance(outcome, tuple) and outcome[0] == "blocked", f"{label}: the mapping must be blocked, got {outcome}"
    assert fake.writes == [] and fake.solves == 0, f"{label}: DevSim writes {fake.writes} / solves {fake.solves}, expected 0 / 0"
    assert "UNSUPPORTED_BY_MODEL" in outcome[1], outcome[1]


def main():
    # ---- A. Uniform compensated ACTIVE profile ------------------------------------------------------------------------------------
    s_comp = advance_wafer_state(base(), uniform(1e17, 1e17), "doping")
    check_compensated(s_comp, 1e17, 1e17)
    profs = dopant_profiles_from_doping_profile(uniform(1e17, 1e17).doping)
    assert sorted(p.polarity for p in profs) == ["acceptor", "donor"], "the converter must keep both polarities"
    print(f"A compensated uniform 1e17/1e17: attachments {[(a.polarity, a.chemical_state, a.model_params['conc_cm3']) for a in s_comp.attachments]}, "
          f"query donor/acceptor/net {q(s_comp)[:3]}")

    # ---- B. one-polarity control ---------------------------------------------------------------------------------------------------
    s_one = advance_wafer_state(base(), uniform(1e17, 0.0), "doping")
    assert [a.polarity for a in s_one.attachments] == ["donor"] and q(s_one)[:3] == (1e17, 0.0, 1e17), q(s_one)
    print(f"B one-polarity control 1e17/0: attachments {[a.polarity for a in s_one.attachments]}, query {q(s_one)[:3]}")

    # ---- C. Gaussian explicit compensation ---------------------------------------------------------------------------------------------
    gauss = apply_gaussian_implant_doping(PR, region="Si", junction_axis="x", peak_position_um=0.0, straggle_um=0.3,
                                          donor_peak_conc_cm3=1e18, acceptor_peak_conc_cm3=1e18,
                                          donor_species="P", acceptor_species="B", chemical_state="CHEMICAL")
    gp = dopant_profiles_from_doping_profile(gauss.doping)
    assert sorted((p.polarity, p.species, p.model_params["peak_conc_cm3"], p.chemical_state) for p in gp) == \
        [("acceptor", "B", 1e18, "CHEMICAL"), ("donor", "P", 1e18, "CHEMICAL")], [(p.polarity, p.species) for p in gp]
    assert gauss.doping.regions[0].peak_conc_cm3 == 0.0, "the derived net peak is 0 and must not delete the two profiles"
    legacy = DopingProfile(kind="gaussian_implant", regions=[DopingRegion(
        region="Si", junction_axis="x", peak_position_um=0.0, straggle_um=0.3, peak_conc_cm3=-5e17, acceptor_species="B", chemical_state="CHEMICAL")])
    lp = dopant_profiles_from_doping_profile(legacy)
    assert [(p.polarity, p.species, p.model_params["peak_conc_cm3"]) for p in lp] == [("acceptor", "B", 5e17)], "legacy signed peak keeps its single-polarity fallback"
    both = DopingProfile(kind="gaussian_implant", regions=[DopingRegion(
        region="Si", junction_axis="x", peak_position_um=0.0, straggle_um=0.3, peak_conc_cm3=123.0,
        donor_peak_conc_cm3=1e18, acceptor_peak_conc_cm3=2e17, chemical_state="CHEMICAL")])
    bp = dopant_profiles_from_doping_profile(both)
    assert sorted((p.polarity, p.model_params["peak_conc_cm3"]) for p in bp) == [("acceptor", 2e17), ("donor", 1e18)], "explicit peaks must beat a legacy net peak"
    s_gauss = advance_wafer_state(base(), gauss, "doping")
    assert sorted(a.polarity for a in s_gauss.attachments) == ["acceptor", "donor"] and all(a.chemical_state == "CHEMICAL" for a in s_gauss.attachments)
    check_gate_none(s_gauss, "Gaussian CHEMICAL")
    check_devsim_blocked(s_gauss, "Gaussian CHEMICAL")
    print(f"C Gaussian donor=acceptor=1e18: {len(gp)} DopantProfiles {[(p.polarity, p.species) for p in gp]}, canonical states "
          f"{[a.chemical_state for a in s_gauss.attachments]}, query {q(s_gauss, 0.0, -0.25)[:3]} -> DevSim mapping blocked")

    # ---- D. chemical / unknown query gate (+ 0 DevSim writes / solves) ------------------------------------------------------------------
    gated = {}
    for st in ("CHEMICAL", "UNKNOWN"):
        s = advance_wafer_state(base(), uniform(1e17, 0.0, st), "doping")
        check_gate_none(s, st)
        check_devsim_blocked(s, st)
        gated[st] = s
        print(f"D {st}: donor/acceptor/net = {q(s)[:3]}, physics_status {q(s)[3]['resolution']}, DevSim writes 0, solves 0")
    # a CHEMICAL attachment covering only part of the cell blocks exactly there; an ACTIVE one elsewhere stays numeric
    partial = v2.attach_dopant(base(), species="P", polarity="donor", chemical_state="ACTIVE", concentration_at=lambda x, y: 1e17,
                               support_instance_id="si#substrate", support_region_um=(-2.0, 0.0, -1.0, 0.0),
                               inventory_integral=v2.uniform_inventory_integral(1e17), model="uniform_v1")
    partial = v2.attach_dopant(partial, species="B", polarity="acceptor", chemical_state="CHEMICAL", concentration_at=lambda x, y: 1e16,
                               support_instance_id="si#substrate", support_region_um=(0.5, 1.5, -1.0, 0.0),
                               inventory_integral=v2.uniform_inventory_integral(1e16), model="uniform_v1", step_seed="c")
    assert q(partial, -1.0)[:3] == (1e17, 0.0, 1e17) and q(partial, -1.0)[3] is None, "the ACTIVE attachment must stay numeric away from the CHEMICAL one"
    assert q(partial, 1.0)[:3] == (None, None, None), "a CHEMICAL attachment covering the point must block even beside an ACTIVE one"
    assert q(partial, 1.9)[:3] == (0.0, 0.0, 0.0), "outside every attachment the known-undoped 0.0 is unchanged"
    # invalid strings are rejected at every entry
    bad = "active"
    for label, call in (
        ("attach_dopant", lambda: v2.attach_dopant(base(), species="P", polarity="donor", chemical_state=bad, concentration_at=lambda x, y: 1.0,
                                                   support_instance_id="si#substrate", support_region_um=SI, model="m")),
        ("DopantAttachment", lambda: v2.DopantAttachment("a", "P", "donor", bad, lambda x, y: 1.0, "i", SI, "e", "m")),
        ("DopantProfile", lambda: DopantProfile(species="P", polarity="donor", concentration_at=lambda x, d: 1.0, host_material="Si",
                                                 model="m", chemical_state=bad)),
        ("apply_uniform_doping", lambda: apply_uniform_doping(PR, {"Si": 1.0}, chemical_state=bad)),
        ("apply_step_junction_doping", lambda: apply_step_junction_doping(PR, "Si", "x", 0.0, 1.0, 1.0, chemical_state=bad)),
        ("apply_gaussian_implant_doping", lambda: apply_gaussian_implant_doping(PR, "Si", "x", 0.0, 0.3, 1.0, chemical_state=bad)),
        ("apply_implant_windows_doping", lambda: apply_implant_windows_doping(PR, "Si", "x", 1.0, [], chemical_state=bad)),
        ("region -> profiles", lambda: dopant_profiles_from_doping_profile(DopingProfile(kind="uniform", regions=[DopingRegion(
            region="Si", donor_conc_cm3=1.0, chemical_state=bad)]))),
    ):
        try:
            call()
        except ValueError as exc:
            assert "chemical_state" in str(exc), f"{label}: {exc}"
        else:
            raise AssertionError(f"{label}: an invalid chemical_state {bad!r} was accepted")
    print("D invalid chemical_state strings raise ValueError at all 8 entries; mixed ACTIVE+CHEMICAL support gates exactly where CHEMICAL covers")
    # an undeclared region is UNKNOWN (fail closed), never ACTIVE
    undeclared = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", donor_conc_cm3=1e17, acceptor_conc_cm3=0.0)])
    assert [p.chemical_state for p in dopant_profiles_from_doping_profile(undeclared)] == ["UNKNOWN"]
    check_gate_none(advance_wafer_state(base(), ProcessResult(volume_mesh_path="x", doping=undeclared), "doping"), "undeclared")

    # ---- E. active query control: numeric + DevSim write possible (single polarity; a compensated region is blocked, see the Rev.2 test) ------
    outcome, fake = run_mapping(s_one)
    assert outcome == "written" and fake.solves == 0, outcome
    assert [w[1] for w in fake.writes] == ["Donors", "Donors", "Acceptors", "Acceptors", "NetDoping", "NetDoping"], fake.writes
    print(f"E ACTIVE control (single polarity): numeric query {q(s_one)[:3]}, DevSim writes {[w[1] for w in fake.writes]}")
    # the compensated state keeps its canonical concentrations but is NOT transport-capable
    assert q(s_comp)[:3] == (1e17, 1e17, 0.0)
    check_devsim_blocked(s_comp, "compensated")

    # ---- F. exact reattach ------------------------------------------------------------------------------------------------------------
    req = uniform(1e17, 1e17).doping
    ok, matched, why = canonical_doping_request_matches(s_comp, req)
    assert ok and len(matched) == 2, (ok, why)
    negatives = {
        "different concentration": uniform(2e17, 1e17).doping,
        "different chemical state": uniform(1e17, 1e17, "CHEMICAL").doping,
        "different model": apply_step_junction_doping(PR, "Si", "x", 0.0, 1e17, 1e17, chemical_state="ACTIVE").doping,
        "different polarity (acceptor-only request, no acceptor attachment on a donor-only state)": None,
        "different host material (no such instance)": apply_uniform_doping(
            PR, donor_by_region_cm3={"SiO2": 1e17}, acceptor_by_region_cm3={"SiO2": 1e17}, chemical_state="ACTIVE").doping,
    }
    dsp = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", donor_conc_cm3=1e17, donor_species="As", acceptor_conc_cm3=1e17, chemical_state="ACTIVE")])
    negatives["different species"] = dsp
    negatives["different polarity (acceptor-only request, no acceptor attachment on a donor-only state)"] = uniform(0.0, 1e17).doping
    for label, d in negatives.items():
        target = s_one if label.startswith("different polarity") else s_comp
        assert canonical_doping_request_matches(target, d)[0] is False, f"reattach must fail for {label}"
    # a request is matched by ITS OWN attachments; the canonical state is not changed by a re-attach, so a donor-only request is satisfied by
    # the donor attachment of a compensated wafer (the extra acceptor is part of the canonical state, not of this request)
    assert canonical_doping_request_matches(s_comp, uniform(1e17, 0.0).doping)[0] is True
    assert canonical_doping_request_matches(s_one, req)[0] is False, "an unrelated (donor-only) attachment must not satisfy a compensated request"
    assert canonical_doping_request_matches(base(), req)[0] is False, "no attachment at all must not match"
    assert canonical_doping_request_matches(None, req)[0] is False
    # support: an attachment with unknown support, or lying outside the instance's geometry, never matches
    from dataclasses import replace
    outside = replace(s_one, attachments=(replace(s_one.attachments[0], support_region_um=(5.0, 6.0, -1.0, 0.0)),))
    unknown = replace(s_one, attachments=(replace(s_one.attachments[0], support_region_um=None),))
    one_req = uniform(1e17, 0.0).doping
    assert canonical_doping_request_matches(s_one, one_req)[0] is True
    assert canonical_doping_request_matches(outside, one_req)[0] is False, "support outside the instance geometry must not match"
    assert canonical_doping_request_matches(unknown, one_req)[0] is False, "an unknown support must not match"
    # after the SAME request twice, one existing attachment cannot satisfy two profiles
    assert canonical_doping_request_matches(s_one, uniform(1e17, 0.0).doping)[0] and not canonical_doping_request_matches(
        s_one, DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", donor_conc_cm3=1e17, acceptor_conc_cm3=0.0, chemical_state="ACTIVE"),
                                                      DopingRegion(region="Si", donor_conc_cm3=1e17, acceptor_conc_cm3=0.0, chemical_state="ACTIVE")]))[0], \
        "each requested profile needs its OWN attachment"
    print(f"F exact reattach: same fingerprint -> True; refused for {sorted(negatives)} + unrelated-attachment-only, no attachment, "
          f"unknown/outside support, duplicate-need")

    # ---- G. partial atomicity ----------------------------------------------------------------------------------------------------------
    prior = advance_wafer_state(base(), uniform(3e16, 0.0), "doping")           # a real prior attachment that must survive
    partial_req = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", donor_conc_cm3=1e17, acceptor_conc_cm3=0.0, chemical_state="ACTIVE"),      # attachable
        DopingRegion(region="SiO2", donor_conc_cm3=1e16, acceptor_conc_cm3=0.0, chemical_state="ACTIVE"),    # no SiO2 instance -> refused
    ])
    out = advance_wafer_state(prior, ProcessResult(volume_mesh_path="x", doping=partial_req), "doping")
    new_att = [a for a in out.attachments if a.attachment_id not in {p.attachment_id for p in prior.attachments}]
    refusals = [e for e in out.events[len(prior.events):] if e.model_status == "UNSUPPORTED_BY_MODEL"]
    assert new_att == [], f"a partly refused request must leave NO new active attachment, got {[(a.attachment_id, a.polarity) for a in new_att]}"
    assert out.attachments == prior.attachments, "prior attachments must be preserved exactly"
    assert len(refusals) == 2 and len(out.unresolved_inventory) == len(prior.unresolved_inventory) + 2, (len(refusals), len(out.unresolved_inventory))
    assert all(u.total_cm_per_depth is None and u.quantity_status == "UNKNOWN_GEOMETRIC_SUPPORT" for u in out.unresolved_inventory[len(prior.unresolved_inventory):]), \
        "no inventory number may be invented for the refused request"
    assert any("atomic" in e.note for e in refusals), "the attachable sibling must be refused BECAUSE of the atomic request"
    # (the prior attachment's electrical value is not silently kept where the refusal covers it)
    print(f"G partial atomicity: 2 profiles (1 attachable, 1 not) -> 0 new attachments, prior attachments preserved "
          f"({len(prior.attachments)}), {len(refusals)} refusal events, +{len(out.unresolved_inventory) - len(prior.unresolved_inventory)} ledger entries with no numbers")
    all_refused = advance_wafer_state(prior, ProcessResult(volume_mesh_path="x", doping=DopingProfile(kind="uniform", regions=[
        DopingRegion(region="SiO2", donor_conc_cm3=1e16, chemical_state="ACTIVE")])), "doping")
    assert all_refused.attachments == prior.attachments, "a fully refused request must preserve prior attachments too"

    # ---- H. all-zero control --------------------------------------------------------------------------------------------------------------
    zero = uniform(0.0, 0.0).doping
    assert dopant_profiles_from_doping_profile(zero) == (), "zero donor and zero acceptor -> no profile"
    z = advance_wafer_state(prior, ProcessResult(volume_mesh_path="x", doping=zero), "doping")
    assert (z.attachments, z.events, z.unresolved_inventory) == (prior.attachments, prior.events, prior.unresolved_inventory), \
        "a zero request must change nothing: no attachment, event or ledger entry"
    print("H all-zero request: no profile, state identical (attachments/events/ledger unchanged)")

    # ---- guards ----------------------------------------------------------------------------------------------------------------------------
    from dataclasses import replace as rep
    collapsed = rep(s_comp, attachments=s_comp.attachments[:1])
    expect_fail(lambda: check_compensated(collapsed, 1e17, 1e17), "compensation collapsed to one attachment", "exactly one donor and one acceptor")
    as_chem = rep(s_comp, attachments=tuple(rep(a, chemical_state="CHEMICAL") for a in s_comp.attachments))
    expect_fail(lambda: check_compensated(as_chem, 1e17, 1e17), "compensated attachments are not ACTIVE", "['CHEMICAL', 'CHEMICAL']")
    expect_fail(lambda: check_gate_none(s_comp, "ACTIVE mutant"), "an ACTIVE state answers numerically where None is expected", "expected all three None")
    expect_fail(lambda: check_devsim_blocked(s_one, "ACTIVE mutant"), "the mapping is not blocked for an ACTIVE single-polarity state", "the mapping must be blocked")
    print("GUARDS: 4 mutant states were rejected for the stated reason")
    print("DOPANT ACTIVATION + COMPENSATION: compensation kept, chemical_state gates the query and DevSim, reattach exact, request atomic, invalid state rejected")


if __name__ == "__main__":
    main()
