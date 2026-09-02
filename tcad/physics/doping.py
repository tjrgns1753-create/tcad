#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Doping application — deliberately separate from tcad/process/ (the 13
ViennaPS Etching/Deposition/Oxidation models never touch doping; none
of those files are modified by this module or import it).

This module only builds/attaches a DopingProfile to a ProcessResult —
it has no devsim import, and never mutates the ProcessResult it's
given (apply_uniform_doping returns a new one via dataclasses.replace).
tcad/device/devsim/doping_mapping.py is the only place that turns a
DopingProfile into actual DevSim node models.

Implements uniform (Phase 7), step-junction (Phase 8),
gaussian_implant, and implant_windows doping. gaussian_implant adds
position-dependent fields to DopingRegion (peak_conc_cm3,
peak_position_um, straggle_um) and this module's
apply_gaussian_implant_doping(). implant_windows adds a background
doping plus zero or more laterally-windowed implants SUPERPOSED on top
of it (implant_windows on DopingRegion) and this module's
apply_implant_windows_doping() — e.g. source/drain regions superposed
on a channel/body background within one MaterialRegion. Neither needed
a change to ProcessResult or DopingProfile's `regions` shape.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult
from tcad.physics.diffusion_model import anneal_profile, thermal_budget_contribution
from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.values import Resolution, combine

#: This project's own doping representation is defined along ONE
#: lateral axis only (every existing kind -- uniform, step_junction,
#: gaussian_implant, implant_windows -- has no depth/y variation at
#: all). A real anneal also moves the junction DEPTH; this module does
#: not compute that. Real, importable, testable -- not only a comment.
DEPTH_EVOLUTION_RESOLUTION = Resolution.UNSUPPORTED_BY_MODEL


def apply_uniform_doping(
    result: ProcessResult,
    doping_by_region_cm3: Optional[Dict[str, float]] = None,
    *,
    donor_by_region_cm3: Optional[Dict[str, float]] = None,
    acceptor_by_region_cm3: Optional[Dict[str, float]] = None,
    species_by_region: Optional[Dict[str, tuple]] = None,
) -> ProcessResult:
    """Return a new ProcessResult with uniform doping attached.

    Two mutually additive input shapes, so every existing caller stays
    unchanged:
      - doping_by_region_cm3: {region_name: net_doping_cm3} (original
        shape — net only, donor/acceptor stay None on the region).
      - donor_by_region_cm3 / acceptor_by_region_cm3: {region_name:
        concentration_cm3}, both >= 0. net_doping_cm3 is computed as
        donor - acceptor and the raw donor/acceptor values are kept on
        the DopingRegion. species_by_region, if given, is
        {region_name: (donor_species, acceptor_species)} — label only.

    A region present in BOTH dicts uses the donor/acceptor value (the
    net_doping_cm3-only dict is a fallback for regions not covered by
    the donor/acceptor one, not a second independent source of truth).
    """
    if (
        doping_by_region_cm3 is None
        and donor_by_region_cm3 is None
        and acceptor_by_region_cm3 is None
    ):
        raise ValueError(
            "apply_uniform_doping needs either doping_by_region_cm3 or "
            "donor_by_region_cm3/acceptor_by_region_cm3"
        )
    regions = [
        DopingRegion(region=name, net_doping_cm3=value)
        for name, value in (doping_by_region_cm3 or {}).items()
    ]
    donor_regions = set(donor_by_region_cm3 or {}) | set(acceptor_by_region_cm3 or {})
    regions = [r for r in regions if r.region not in donor_regions]
    for name in donor_regions:
        donor = (donor_by_region_cm3 or {}).get(name, 0.0)
        acceptor = (acceptor_by_region_cm3 or {}).get(name, 0.0)
        species = (species_by_region or {}).get(name, (None, None))
        regions.append(
            DopingRegion(
                region=name, net_doping_cm3=donor - acceptor,
                donor_conc_cm3=donor, acceptor_conc_cm3=acceptor,
                donor_species=species[0], acceptor_species=species[1],
            )
        )
    doping = DopingProfile(kind="uniform", regions=regions)
    return replace(result, doping=doping)


def apply_step_junction_doping(
    result: ProcessResult,
    region: str,
    junction_axis: str,
    junction_position_um: float,
    donor_conc_cm3: float,
    acceptor_conc_cm3: float,
) -> ProcessResult:
    """Return a new ProcessResult with a step-junction doping profile
    attached to one region: donor_conc_cm3 where `junction_axis`'s
    coordinate is greater than junction_position_um, acceptor_conc_cm3
    on the other side — a PN junction.

    Kept separate from apply_uniform_doping so a ProcessResult's
    DopingProfile.kind unambiguously tells the DevSim-side mapping
    (tcad.device.devsim.doping_mapping) which equation shape to build,
    rather than inferring it from which fields happen to be set.
    """
    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        junction_position_um=junction_position_um,
        donor_conc_cm3=donor_conc_cm3,
        acceptor_conc_cm3=acceptor_conc_cm3,
    )
    doping = DopingProfile(kind="step_junction", regions=[doping_region])
    return replace(result, doping=doping)


def apply_gaussian_implant_doping(
    result: ProcessResult,
    region: str,
    junction_axis: str,
    peak_position_um: float,
    straggle_um: float,
    peak_conc_cm3: Optional[float] = None,
    *,
    donor_peak_conc_cm3: Optional[float] = None,
    acceptor_peak_conc_cm3: Optional[float] = None,
    donor_species: Optional[str] = None,
    acceptor_species: Optional[str] = None,
    existing: Optional[ProcessResult] = None,
) -> ProcessResult:
    """Return a new ProcessResult with a 1D Gaussian implant doping
    profile attached to one region: net doping along `junction_axis`
    is peak_conc_cm3 * exp(-((axis - peak_position_um)^2) /
    (2*straggle_um^2)) — a simple implant/diffusion approximation, not a
    full process simulation.

    Either pass peak_conc_cm3 directly (original shape, signed net,
    positive = net donor, negative = net acceptor), or
    donor_peak_conc_cm3/acceptor_peak_conc_cm3 (both >= 0) -- both
    profiles share peak_position_um/straggle_um (see DopingRegion's
    own docstring for why: no implant-energy model exists to derive
    independent shapes). peak_conc_cm3 is computed as donor - acceptor
    when the donor/acceptor form is used, and is what every downstream
    consumer keeps reading.

    existing : Optional prior ProcessResult from an earlier implant
        call on the SAME region. When given, this call's term is ADDED
        to whatever terms `existing.doping` already carried (its
        legacy single-profile shape is normalized into a term first if
        needed) — B implant then P implant leaves BOTH profiles
        present, never just the latest one. `None` (the default) keeps
        every current caller byte-identical to before this parameter
        existed. Raises ValueError if `existing.doping.kind` is set to
        anything other than "gaussian_implant" — superposing implant
        terms onto a different doping kind's representation is out of
        scope (see this project's Stage B plan, Global Constraints).
    """
    if (
        peak_conc_cm3 is None
        and donor_peak_conc_cm3 is None
        and acceptor_peak_conc_cm3 is None
    ):
        raise ValueError(
            "apply_gaussian_implant_doping needs either peak_conc_cm3 or "
            "donor_peak_conc_cm3/acceptor_peak_conc_cm3"
        )

    new_terms = []
    if donor_peak_conc_cm3:
        new_terms.append({
            "species": donor_species, "polarity": "donor",
            "peak_conc_cm3": donor_peak_conc_cm3,
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })
    if acceptor_peak_conc_cm3:
        new_terms.append({
            "species": acceptor_species, "polarity": "acceptor",
            "peak_conc_cm3": acceptor_peak_conc_cm3,
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })
    if not new_terms and peak_conc_cm3 is not None:
        # net-only input form -- this project's own documented sign
        # convention (positive net = donor, negative = acceptor),
        # same as every other doping kind's net-only fallback.
        polarity = "donor" if peak_conc_cm3 >= 0 else "acceptor"
        new_terms.append({
            "species": None, "polarity": polarity,
            "peak_conc_cm3": abs(peak_conc_cm3),
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })

    all_terms = list(new_terms)
    if existing is not None:
        prior_doping = existing.doping
        if prior_doping is not None and prior_doping.kind != "gaussian_implant":
            raise ValueError(
                f"apply_gaussian_implant_doping's existing= only accepts a "
                f"prior gaussian_implant result (or none yet); got kind="
                f"{prior_doping.kind!r}. Superposing implant terms onto a "
                f"different doping kind's representation is out of scope -- "
                f"see this plan's Global Constraints."
            )
        if prior_doping is not None:
            prior_region = prior_doping.regions[0]
            if prior_region.gaussian_terms:
                all_terms = list(prior_region.gaussian_terms) + new_terms
            elif prior_region.peak_conc_cm3 is not None or \
                    prior_region.donor_peak_conc_cm3 is not None or \
                    prior_region.acceptor_peak_conc_cm3 is not None:
                # legacy single-implant region -- normalize it into one
                # or two terms (donor/acceptor) before appending the new one.
                prior_terms = []
                if prior_region.donor_peak_conc_cm3:
                    prior_terms.append({
                        "species": prior_region.donor_species, "polarity": "donor",
                        "peak_conc_cm3": prior_region.donor_peak_conc_cm3,
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                if prior_region.acceptor_peak_conc_cm3:
                    prior_terms.append({
                        "species": prior_region.acceptor_species, "polarity": "acceptor",
                        "peak_conc_cm3": prior_region.acceptor_peak_conc_cm3,
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                if not prior_terms and prior_region.peak_conc_cm3 is not None:
                    polarity = "donor" if prior_region.peak_conc_cm3 >= 0 else "acceptor"
                    prior_terms.append({
                        "species": None, "polarity": polarity,
                        "peak_conc_cm3": abs(prior_region.peak_conc_cm3),
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                all_terms = prior_terms + new_terms

    if donor_peak_conc_cm3 is not None or acceptor_peak_conc_cm3 is not None:
        donor = donor_peak_conc_cm3 or 0.0
        acceptor = acceptor_peak_conc_cm3 or 0.0
        peak_conc_cm3 = donor - acceptor

    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        peak_position_um=peak_position_um,
        straggle_um=straggle_um,
        peak_conc_cm3=peak_conc_cm3,
        donor_peak_conc_cm3=donor_peak_conc_cm3,
        acceptor_peak_conc_cm3=acceptor_peak_conc_cm3,
        donor_species=donor_species,
        acceptor_species=acceptor_species,
        gaussian_terms=all_terms if (existing is not None and all_terms) else None,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[doping_region])
    return replace(result, doping=doping)


def implant_windows_from_mask_spans(
    mask_spans_um: List[List[float]],
    x_extent_um: float,
    conc_cm3: float,
) -> List[Dict[str, float]]:
    """Turn a mask's OPAQUE spans into the implant windows they leave
    open — the complement of `mask_spans_um` within the domain.

    This is the physical relationship an implant step actually has to
    lithography: dopant lands where the mask is NOT. Passing implant
    windows as free-floating numbers (see apply_implant_windows_doping)
    lets them drift out of correspondence with the real mask geometry;
    deriving them removes that failure mode for the common case.

    mask_spans_um : the same value handed to a recipe's `mask_spans_um`
        (see tcad.backends.viennaps.session.make_mask_spans) — opaque
        regions, in domain x coordinates.
    x_extent_um : the domain's own x extent; the domain spans
        [-x_extent_um/2, +x_extent_um/2], matching every recipe in this
        project.
    conc_cm3 : implant concentration for every derived window (signed,
        same convention as net_doping_cm3). One value for all windows —
        a single implant step uses one dose, so per-window doses would
        represent two separate steps.

    Returns a list of {"min_um", "max_um", "conc_cm3"} ready to hand to
    apply_implant_windows_doping(). Overlapping or unsorted input spans
    are handled (they are merged first). An empty mask yields one window
    covering the whole domain; a mask covering everything yields none.
    """
    half_x = x_extent_um / 2.0
    merged: List[List[float]] = []
    for lo, hi in sorted((min(s), max(s)) for s in mask_spans_um):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    windows: List[Dict[str, float]] = []
    cursor = -half_x
    for lo, hi in merged:
        if lo > cursor:
            windows.append(
                {"min_um": cursor, "max_um": min(lo, half_x), "conc_cm3": conc_cm3}
            )
        cursor = max(cursor, hi)
    if cursor < half_x:
        windows.append({"min_um": cursor, "max_um": half_x, "conc_cm3": conc_cm3})
    return windows


def apply_implant_windows_doping(
    result: ProcessResult,
    region: str,
    axis: str,
    background_doping_cm3: Optional[float] = None,
    windows: Optional[List[Dict[str, float]]] = None,
    *,
    donor_background_cm3: Optional[float] = None,
    acceptor_background_cm3: Optional[float] = None,
) -> ProcessResult:
    """Return a new ProcessResult with a background doping plus zero or
    more laterally-windowed implants SUPERPOSED on top, all in one
    region: e.g. a body/channel background with source and drain
    implants laid out along `axis`.

    Background: either background_doping_cm3 (original shape, signed
    net) or donor_background_cm3/acceptor_background_cm3 (both >= 0,
    net computed as donor - acceptor).

    windows : list of {"min_um": float, "max_um": float,
        "conc_cm3": float} (original shape, signed net) OR
        {"min_um": float, "max_um": float, "donor_conc_cm3": float,
        "acceptor_conc_cm3": float} (both >= 0) -- "conc_cm3" is filled
        in as donor - acceptor either way, so doping_mapping.py and the
        renderer keep reading the same key unchanged. Each window ADDS
        conc_cm3 (signed, same convention as background_doping_cm3:
        positive = net donor, negative = net acceptor) to the
        background wherever min_um <= axis-coordinate <= max_um.
        Windows may overlap (their contributions sum) — not validated
        here, since a caller may deliberately want graded overlap;
        DevSim-side mapping applies the windows exactly as given.

    This models the real physical relationship between an implant and
    whatever doping already existed where it lands (superposition), not
    a replacement — the same reason `apply_gaussian_implant_doping`
    doesn't split its result into separate Donors/Acceptors models.
    """
    if donor_background_cm3 is not None or acceptor_background_cm3 is not None:
        background_doping_cm3 = (donor_background_cm3 or 0.0) - (acceptor_background_cm3 or 0.0)

    resolved_windows = []
    for window in windows or []:
        window = dict(window)
        if "donor_conc_cm3" in window or "acceptor_conc_cm3" in window:
            window["conc_cm3"] = window.get("donor_conc_cm3", 0.0) - window.get("acceptor_conc_cm3", 0.0)
        resolved_windows.append(window)

    doping_region = DopingRegion(
        region=region,
        net_doping_cm3=background_doping_cm3,
        junction_axis=axis,
        donor_conc_cm3=donor_background_cm3,
        acceptor_conc_cm3=acceptor_background_cm3,
        implant_windows=resolved_windows,
    )
    doping = DopingProfile(kind="implant_windows", regions=[doping_region])
    return replace(result, doping=doping)


def _normalize_gaussian_terms(region: DopingRegion) -> List[Dict]:
    """A DopingRegion's implant content as a flat term list, regardless
    of whether it already used gaussian_terms (Task 3) or only the
    legacy single-profile fields. Shared by apply_thermal_anneal() here
    and apply_gaussian_implant_doping's existing= path (Task 3) --
    kept as ONE function so the two paths cannot drift apart."""
    if region.gaussian_terms:
        return list(region.gaussian_terms)
    terms = []
    if region.donor_peak_conc_cm3:
        terms.append({
            "species": region.donor_species, "polarity": "donor",
            "peak_conc_cm3": region.donor_peak_conc_cm3,
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    if region.acceptor_peak_conc_cm3:
        terms.append({
            "species": region.acceptor_species, "polarity": "acceptor",
            "peak_conc_cm3": region.acceptor_peak_conc_cm3,
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    if not terms and region.peak_conc_cm3 is not None:
        polarity = "donor" if region.peak_conc_cm3 >= 0 else "acceptor"
        terms.append({
            "species": None, "polarity": polarity,
            "peak_conc_cm3": abs(region.peak_conc_cm3),
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    return terms


def apply_thermal_anneal(
    result: ProcessResult, temperature_c: float, time_s: float,
) -> ProcessResult:
    """Widen every EXISTING Gaussian implant term by its own species'
    real, cited D(T) (tcad.physics.diffusion_model) -- independently,
    never a species-pair interaction. Dose is conserved per term: the
    actual broadening math is tcad.physics.diffusion_model.
    anneal_profile(), called once per term here so this function and
    anneal_profile can never diverge (Stage B final-review Important
    #5) -- each term is wrapped in a throwaway DopantProfile (its
    concentration_at is never called by anneal_profile, only its
    species/polarity/peak/position/straggle fields are read).

    Real, honest no-op (returns `result` UNCHANGED, same object) when
    result.doping has no defined Gaussian shape to widen -- this
    function never invents a shape for uniform/step_junction/
    implant_windows doping, which this project has no anneal physics
    for.

    Depth/junction-depth evolution is NOT computed -- see this module's
    own DEPTH_EVOLUTION_RESOLUTION constant.

    result.physics_status is set to report, per widened species, whether
    its D(T) fell inside or outside that species' own citation's
    measured temperature window (Resolution.VERIFIED vs UNVERIFIED --
    see tcad.physics.diffusion_model.arrhenius_diffusivity) -- an
    out-of-window anneal still runs (the Arrhenius formula is physically
    continuous), it is just never presented as equally trustworthy as an
    in-window one (Stage B final-review Important #3). Left exactly as
    `result` carried it in when no term had a resolvable species
    (nothing new to report) -- physics_status is additive project-wide,
    so an anneal step with nothing to say about D(T) resolution must
    not erase an earlier step's real status.
    """
    if result.doping is None or result.doping.kind != "gaussian_implant":
        return result

    region = result.doping.regions[0]
    terms = _normalize_gaussian_terms(region)
    if not terms:
        return result

    updated_terms = []
    resolutions = []
    physics_entries = []
    for term in terms:
        species = term["species"]
        straggle_um = term.get("straggle_um")
        # Un-widenable terms (no species label, so no citation-backed
        # D(T) is possible; or a hand-built term missing straggle_um --
        # Stage B final-review Minor #3, matching anneal_profile's own
        # guard) are carried through unchanged -- as an independent
        # COPY (Minor #2), never the same dict object the input's
        # region still holds, so mutating the output can never mutate
        # the input.
        if species is None or straggle_um is None:
            updated_terms.append(dict(term))
            continue

        contribution = thermal_budget_contribution(species, "Si", temperature_c, time_s)
        if contribution.value is None:
            updated_terms.append(dict(term))
            continue

        resolutions.append(contribution.resolution)
        physics_entries.append({
            "parameter": "diffusivity_D(T)", "material": species,
            "value": contribution.value, "resolution": contribution.resolution.value,
            "provenance": contribution.provenance.value,
            "note": (
                f"T={temperature_c:.0f}C, t={time_s:.0f}s" if
                contribution.resolution is Resolution.VERIFIED else
                f"T={temperature_c:.0f}C outside {species}'s citation "
                f"window -- extrapolated"
            ),
        })

        dopant = DopantProfile(
            species=species, polarity=term["polarity"],
            concentration_at=lambda x_um, depth_um: 0.0,  # unused by anneal_profile
            peak_conc_cm3=term["peak_conc_cm3"],
            peak_position_um=term["peak_position_um"],
            straggle_um=straggle_um,
        )
        annealed = anneal_profile(dopant, temperature_c, time_s)
        updated_terms.append({
            "species": annealed.species, "polarity": annealed.polarity,
            "peak_conc_cm3": annealed.peak_conc_cm3,
            "peak_position_um": annealed.peak_position_um,
            "straggle_um": annealed.straggle_um,
            "thermal_budget_cm2": term.get("thermal_budget_cm2", 0.0) + annealed.thermal_budget,
        })

    new_region = replace(region, gaussian_terms=updated_terms)
    new_doping = DopingProfile(kind="gaussian_implant", regions=[new_region])
    if not physics_entries:
        # Nothing resolvable to report -- leave physics_status exactly
        # as the incoming result carried it (physics_status is additive
        # project-wide; an anneal step with nothing to say about D(T)
        # resolution must not erase an earlier step's real status).
        return replace(result, doping=new_doping)
    physics_status = {
        "resolution": combine(resolutions).value,
        "entries": physics_entries,
        "notes": [],
    }
    return replace(result, doping=new_doping, physics_status=physics_status)
