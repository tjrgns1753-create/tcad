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
from typing import Dict, List, Optional, Tuple

from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult
from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.wafer_state_v2 import validate_chemical_state
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
    chemical_state: str,
) -> ProcessResult:
    """Return a new ProcessResult with uniform doping attached.

    `chemical_state` is the DECLARED activation state stored on every
    region built here (see DopingRegion.chemical_state). It is a REQUIRED
    keyword-only argument with no default: nothing here may become
    electrically ACTIVE by omission. "ACTIVE" means a user-declared,
    electrically active analytic profile; a process-like implant with no
    activation model must be declared "CHEMICAL" (or "UNKNOWN"). Omitting
    it is a TypeError; an invalid string raises ValueError.

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
    validate_chemical_state(chemical_state)
    regions = [
        DopingRegion(region=name, net_doping_cm3=value, chemical_state=chemical_state)
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
                chemical_state=chemical_state,
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
    *,
    chemical_state: str,
) -> ProcessResult:
    """Return a new ProcessResult with a step-junction doping profile
    attached to one region: donor_conc_cm3 where `junction_axis`'s
    coordinate is greater than junction_position_um, acceptor_conc_cm3
    on the other side — a PN junction.

    `chemical_state`: the declared activation state, REQUIRED and
    keyword-only (see apply_uniform_doping); "ACTIVE" = a user-declared
    active analytic profile. Invalid strings raise ValueError.

    Kept separate from apply_uniform_doping so a ProcessResult's
    DopingProfile.kind unambiguously tells the DevSim-side mapping
    (tcad.device.devsim.doping_mapping) which equation shape to build,
    rather than inferring it from which fields happen to be set.
    """
    validate_chemical_state(chemical_state)
    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        junction_position_um=junction_position_um,
        donor_conc_cm3=donor_conc_cm3,
        acceptor_conc_cm3=acceptor_conc_cm3,
        chemical_state=chemical_state,
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
    chemical_state: str,
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

    `chemical_state`: the declared activation state, REQUIRED and
    keyword-only (see apply_uniform_doping). This project has no implantation (energy/dose)
    or anneal-activation model, so a caller presenting this as a process
    implant must declare "CHEMICAL"; "ACTIVE" is only a user-declared
    analytic profile. With explicit donor/acceptor peaks the two stay two
    separate canonical profiles downstream -- never collapsed to a net.

    One implant call attaches one profile to `result`, replacing
    whatever doping it carried before -- multi-implant accumulation
    across calls is WaferState's job (dopant_profiles, Task 5), not
    this function's.
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

    validate_chemical_state(chemical_state)
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
        chemical_state=chemical_state,
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
    chemical_state: str,
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

    `chemical_state`: the declared activation state, REQUIRED and
    keyword-only (see apply_uniform_doping and apply_gaussian_implant_doping).

    This models the real physical relationship between an implant and
    whatever doping already existed where it lands (superposition), not
    a replacement — the same reason `apply_gaussian_implant_doping`
    doesn't split its result into separate Donors/Acceptors models.
    """
    validate_chemical_state(chemical_state)
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
        chemical_state=chemical_state,
    )
    doping = DopingProfile(kind="implant_windows", regions=[doping_region])
    return replace(result, doping=doping)


def apply_thermal_anneal(
    profiles: Tuple[DopantProfile, ...], temperature_c: float, time_s: float,
) -> Tuple[Tuple[DopantProfile, ...], Optional[dict]]:
    """Dispatch every profile to its own model's anneal handler
    (tcad.physics.dopant_models.ANNEAL_HANDLERS, keyed by profile.model)
    rather than a single hardcoded Gaussian formula -- per-model
    redistribution physics, not a species-pair interaction and not a
    single formula assumed to fit every doping kind.

    Every profile ALWAYS gets a ThermalEvent(temperature_c, time_s)
    appended to its thermal_history -- it really was exposed to this
    anneal, whether or not this project has a handler that knows how to
    redistribute its shape. A profile whose model has no registered
    handler is returned with model_params UNCHANGED (never silently
    skipped, never run through the wrong model's formula) and reported
    UNSUPPORTED_BY_MODEL in physics_status -- e.g. uniform_v1/
    step_junction_v1/implant_windows_v1 today, which this project has no
    anneal physics for.

    A profile that WAS widened by a registered handler, but whose real
    D(T) computation (tcad.physics.diffusion_model.arrhenius_diffusivity)
    had to extrapolate outside that species' own cited validity window
    (e.g. Christensen et al. 2003's measured 810-1100C range for P), is
    separately reported UNVERIFIED (final-review Fix 1,
    2026-09-03 dopant-state-unification) -- the anneal still runs (the
    Arrhenius formula is physically continuous), it is just never
    presented as equally trustworthy as an in-window result. Both
    resolutions can appear together in one returned physics_status,
    distinguished by each entry's own "resolution" field -- exactly how
    WaferState.net_doping_at() already reports its own two distinct gap
    reasons.

    Depth/junction-depth evolution is NOT computed by any handler this
    project registers today -- see this module's own
    DEPTH_EVOLUTION_RESOLUTION constant.

    Operates on the profile tuple directly (signature changed from
    (ProcessResult, ...) -> ProcessResult): profiles now live on
    WaferState, not ProcessResult.doping, per spec 2026-09-03 Sec9.
    """
    from tcad.physics.dopant_models import ANNEAL_HANDLERS
    from tcad.physics.dopant_profile import ThermalEvent

    updated = []
    entries = []
    for profile in profiles:
        with_event = replace(
            profile, thermal_history=profile.thermal_history + (
                ThermalEvent(temperature_c=temperature_c, time_s=time_s),
            ),
        )
        handler = ANNEAL_HANDLERS.get(profile.model)
        if handler is None:
            entries.append({
                "parameter": "anneal_redistribution", "material": profile.species,
                "resolution": "UNSUPPORTED_BY_MODEL", "provenance": "DERIVED",
                "note": f"no anneal/redistribution handler registered for model={profile.model!r}",
            })
            updated.append(with_event)
            continue
        annealed_profile, anneal_resolution = handler(with_event, temperature_c, time_s)
        updated.append(annealed_profile)
        if anneal_resolution is Resolution.UNVERIFIED:
            entries.append({
                "parameter": "anneal_diffusivity_D(T)", "material": profile.species,
                "resolution": "UNVERIFIED", "provenance": "LITERATURE",
                "note": (
                    f"T={temperature_c:.0f}C outside {profile.species}'s "
                    f"citation validity window -- D(T) extrapolated, not "
                    f"verified in-window"
                ),
            })
    if not entries:
        return tuple(updated), None
    resolutions = [Resolution(e["resolution"]) for e in entries]
    physics_status = {"resolution": combine(resolutions).value, "entries": entries, "notes": []}
    return tuple(updated), physics_status
