#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arrhenius D(T) and cumulative thermal-budget physics, sourced only
from tcad.physics.tables.INTERACTION_COEFFICIENTS -- every number this
module returns traces back to a real citation there, or is UNKNOWN.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md
section 1: this is the model boundary a future NumericalDiffusionModel
(a real PDE time-integration) can be substituted behind, without
changing anything that calls arrhenius_diffusivity()/
thermal_budget_contribution() or anneal_profile() (added in a later
task of this same plan).

thermal_budget_contribution() computes ONE isothermal step's own D*t
contribution -- the v1 scope this plan implements. A profile's running
thermal_budget (see DopantProfile, extended in a later task) is the
SUM of these contributions across every anneal it has lived through:
sum(D(T_i) * t_i) approximates the real integral ∫D(T(t))dt as a
piecewise-constant (one temperature per step) integral. This is an
explicit v1 simplification, not an architectural limit: a future
caller with a continuous T(t) history could integrate that directly
and still only ever needs to update the same single accumulated
thermal_budget scalar this module already produces -- nothing here
assumes temperature is constant for a profile's WHOLE lifetime, only
that each individual anneal STEP is isothermal (true of every real
furnace/RTA anneal this project's reference case describes).
"""

from __future__ import annotations

import math

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.tables import INTERACTION_COEFFICIENTS
from tcad.physics.values import (
    Conditions, Coverage, PhysicalValue, Provenance, Resolution,
)

#: CODATA 2018 value, eV/K -- a physical constant, not a citation.
K_BOLTZMANN_EV_PER_K = 8.617333262e-5

_NO_CONDITIONS = Conditions(notes="not applicable")


def arrhenius_diffusivity(
    species: str, host_material: str, temperature_c: float,
) -> PhysicalValue:
    """D(T) = D0 * exp(-Ea / (k_B * T_kelvin)), both D0 and Ea read
    from real cited table entries. UNKNOWN if either constant has no
    table entry for (host_material, species). VERIFIED only when
    temperature_c falls inside BOTH constants' own measured window;
    a value computed outside that window is UNVERIFIED -- the formula
    still evaluates (Arrhenius behavior is physically continuous), but
    this project never treats an extrapolation as equally trustworthy
    as an in-window citation.
    """
    d0_entry = INTERACTION_COEFFICIENTS.get(
        (host_material, species, "diffusivity_D0_cm2_s"))
    ea_entry = INTERACTION_COEFFICIENTS.get(
        (host_material, species, "diffusivity_Ea_eV"))
    if d0_entry is None or ea_entry is None:
        return PhysicalValue(
            value=None, unit="cm^2/s", material=host_material,
            chemistry=species, conditions=d0_entry.conditions if d0_entry
            else ea_entry.conditions if ea_entry else _NO_CONDITIONS,
            source=None, resolution=Resolution.UNKNOWN,
            provenance=Provenance.DERIVED,
        )

    temperature_kelvin = temperature_c + 273.15
    value = d0_entry.value * math.exp(
        -ea_entry.value / (K_BOLTZMANN_EV_PER_K * temperature_kelvin)
    )

    requested = {"temperature_c": temperature_c}
    d0_inside = d0_entry.conditions.covers(requested) is Coverage.INSIDE
    ea_inside = ea_entry.conditions.covers(requested) is Coverage.INSIDE
    resolution = (
        Resolution.VERIFIED if (d0_inside and ea_inside) else Resolution.UNVERIFIED
    )

    return PhysicalValue(
        value=value, unit="cm^2/s", material=host_material,
        chemistry=species, conditions=d0_entry.conditions,
        source=d0_entry.source, resolution=resolution,
        provenance=Provenance.LITERATURE,
    )


def thermal_budget_contribution(
    species: str, host_material: str, temperature_c: float, time_s: float,
) -> PhysicalValue:
    """D(T) * t for ONE isothermal anneal step -- see this module's own
    docstring for why summing these across steps approximates
    integral D(T(t)) dt, and why that is a stated v1 scope limit, not
    an architectural one."""
    diffusivity = arrhenius_diffusivity(species, host_material, temperature_c)
    if diffusivity.value is None:
        return diffusivity
    return PhysicalValue(
        value=diffusivity.value * time_s, unit="cm^2",
        material=diffusivity.material, chemistry=diffusivity.chemistry,
        conditions=diffusivity.conditions, source=diffusivity.source,
        resolution=diffusivity.resolution, provenance=diffusivity.provenance,
    )


def anneal_profile(
    profile: DopantProfile, temperature_c: float, time_s: float,
) -> DopantProfile:
    """Real, dose-conserving Gaussian broadening under one isothermal
    anneal step. See this module's own docstring for the thermal-budget
    accumulation model.

    Dose Q = peak_conc_cm3 * straggle_um * sqrt(2*pi) (this plan's own
    1D convention) is conserved EXACTLY: sigma_new^2 = sigma_old^2 +
    2*Dt (the real Green's-function result for Gaussian diffusion),
    and peak_new = peak_old * (sigma_old / sigma_new) -- the unique
    rescaling that keeps Q unchanged while sigma grows.

    Returns the SAME profile, unchanged, when there is no defined shape
    (straggle_um is None) or no species label (no citation-backed D(T)
    is possible) -- never guesses.
    """
    if profile.straggle_um is None or profile.species is None:
        return profile

    contribution = thermal_budget_contribution(
        profile.species, "Si", temperature_c, time_s,
    )
    if contribution.value is None:
        return profile

    dt_um2 = contribution.value * 1e8  # cm^2 -> um^2 (1 cm = 1e4 um)
    new_straggle = math.sqrt(profile.straggle_um ** 2 + 2.0 * dt_um2)
    new_peak = profile.peak_conc_cm3 * (profile.straggle_um / new_straggle)
    new_thermal_budget = profile.thermal_budget + contribution.value

    position = profile.peak_position_um

    def new_shape(x_um: float, depth_um: float,
                  peak=new_peak, pos=position, straggle=new_straggle) -> float:
        return peak * math.exp(-((x_um - pos) ** 2) / (2.0 * straggle ** 2))

    return DopantProfile(
        species=profile.species, polarity=profile.polarity,
        concentration_at=new_shape, thermal_budget=new_thermal_budget,
        # The citation that just produced new_straggle/new_peak, not
        # profile.source (Stage B final-review Minor #4) -- carrying
        # profile.source forward silently drops the provenance of the
        # D(T) actually used for THIS widening (contribution.source is
        # real and available right here).
        source=contribution.source, peak_conc_cm3=new_peak,
        peak_position_um=position, straggle_um=new_straggle,
    )
