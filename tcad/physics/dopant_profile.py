#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DopantProfile -- the process-layer, species-preserving doping
representation WaferState reads.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md,
section 2: DevSim's NetDoping is a device-layer concept, built exactly
once, only inside tcad/device/devsim/doping_mapping.py -- unchanged by
this module. Nothing upstream of that boundary computes or stores a
plain signed net value as ITS primary representation; a DopantProfile
keeps species and polarity (donor vs acceptor) separate for as long as
possible. A combined net value is always a DERIVED query
(WaferState.net_doping_at, added in a later task), never stored here.

dopant_profiles_from_doping_profile() is a pure, lossless adapter over
the EXISTING tcad.mesh.interface.DopingProfile/DopingRegion shape --
it does not replace that shape. doping_mapping.py, the GUI, and every
existing doping kind keep using DopingRegion exactly as they do today;
this module exists only so WaferState (which has never carried doping
information at all, deliberately, per the base wafer-state design) can
gain a doping query surface without touching the already-verified
DevSim NetDoping construction path.

Three things this module deliberately does NOT model, all belonging to
the DEVICE layer rather than the declared process-layer profile:
window_scale (doping_mapping.apply_doping's continuation-ramp
multiplier -- a solve-strategy detail, not part of what the process
declares), barrier-covered-window exclusion (derived from the real
mesh at DevSim import time, not from the DopingProfile alone), and
length_scale_to_cm (a coordinate-scaling parameter applied only
during DevSim NetDoping equation construction, not part of the
profile's specification).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from tcad.mesh.interface import DopingProfile, DopingRegion
from tcad.physics.values import Source


@dataclass(frozen=True)
class DopantProfile:
    """One species' concentration magnitude, as a real function of
    position -- always >= 0; sign/polarity is a separate field, never
    folded into the returned value.

    species : chemical identity ("P", "B", "As", ...) when the
        originating DopingRegion carried a donor_species/acceptor_species
        label; None otherwise. Never invented.
    polarity : "donor" or "acceptor".
    concentration_at : (x_um, depth_um) -> cm^-3, magnitude only.
        depth_um is accepted for interface symmetry with the base
        design's thickness_of(material, x) shape, but every doping kind
        this module converts is defined along one lateral axis only --
        depth_um is unused by every concentration_at built here today.
    thermal_budget : cumulative D*t (cm^2) this profile has experienced.
        Always 0.0 out of this module; no process in this project's
        registry contributes to it yet (Stage B, not this stage).
    source : provenance, when known. None for every existing caller.
    peak_conc_cm3 / peak_position_um / straggle_um : set together for a
        Gaussian-shaped profile -- the extra structure `anneal_profile()`
        (tcad.physics.diffusion_model) needs to re-broaden this profile
        under further thermal budget. None for every profile with no
        defined shape (this module's uniform/step_junction/
        implant_windows conversions never set these).
    """

    species: Optional[str]
    polarity: str
    concentration_at: Callable[[float, float], float]
    thermal_budget: float = 0.0
    source: Optional[Source] = None
    peak_conc_cm3: Optional[float] = None
    peak_position_um: Optional[float] = None
    straggle_um: Optional[float] = None


def _step(z: float) -> float:
    """DevSim's own step(): 1.0 for z >= 0, else 0.0 -- reproduced
    here (not imported; DevSim's step() is a symbolic equation-string
    function evaluated by DevSim's own solver, not a Python callable)
    so this matches tcad.device.devsim.doping_mapping.apply_doping()'s
    real DevSim equations node-for-node, including the boundary case."""
    return 1.0 if z >= 0.0 else 0.0


def _gaussian_shape(x_um: float, position_um: float, straggle_um: float) -> float:
    return math.exp(-((x_um - position_um) ** 2) / (2.0 * straggle_um ** 2))


def _split_net(net: Optional[float]) -> Tuple[float, float]:
    """This project's own documented sign convention (positive net =
    donor, negative net = acceptor) applied to recover a single
    polarity's magnitude when no explicit donor/acceptor split exists.
    Never produces a non-zero value for BOTH polarities from one net
    number -- that would invent data that was never supplied."""
    value = net or 0.0
    return (max(value, 0.0), max(-value, 0.0))


def dopant_profiles_from_doping_profile(
    doping: DopingProfile,
) -> Tuple[DopantProfile, ...]:
    """Convert an EXISTING DopingProfile into DopantProfiles.

    Lossless wherever a DopingRegion carries a real donor/acceptor
    split (every existing doping kind supports this). Falls back to
    _split_net() only where a caller used the original net-only input
    form.
    """
    # Validate and dispatch kind once, before iterating regions.
    if doping.kind == "uniform":
        helper = _uniform_profiles
    elif doping.kind == "step_junction":
        helper = _step_junction_profiles
    elif doping.kind == "gaussian_implant":
        helper = _gaussian_implant_profiles
    elif doping.kind == "implant_windows":
        helper = _implant_windows_profiles
    else:
        raise NotImplementedError(
            f"dopant_profiles_from_doping_profile supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant', "
            f"'implant_windows') so far, got {doping.kind!r}"
        )

    profiles: List[DopantProfile] = []
    for region in doping.regions:
        profiles.extend(helper(region))
    return tuple(profiles)


def _uniform_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.donor_conc_cm3 is not None or region.acceptor_conc_cm3 is not None:
        donor_mag = region.donor_conc_cm3 or 0.0
        acceptor_mag = region.acceptor_conc_cm3 or 0.0
    else:
        donor_mag, acceptor_mag = _split_net(region.net_doping_cm3)
    out: List[DopantProfile] = []
    if donor_mag:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor_mag: v,
        ))
    if acceptor_mag:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor_mag: v,
        ))
    return out


def _step_junction_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.junction_axis not in (None, "x"):
        raise NotImplementedError(
            f"dopant_profiles_from_doping_profile evaluates along x only; "
            f"got junction_axis={region.junction_axis!r}"
        )
    position = region.junction_position_um
    donor = region.donor_conc_cm3 or 0.0
    acceptor = region.acceptor_conc_cm3 or 0.0
    out: List[DopantProfile] = []
    if donor:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor, p=position: v * _step(x - p),
        ))
    if acceptor:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor, p=position: v * _step(p - x),
        ))
    return out


def _gaussian_implant_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.gaussian_terms:
        out: List[DopantProfile] = []
        for term in region.gaussian_terms:
            peak, position, straggle = (
                term["peak_conc_cm3"], term["peak_position_um"], term["straggle_um"],
            )
            out.append(DopantProfile(
                species=term["species"], polarity=term["polarity"],
                concentration_at=lambda x, d, v=peak, p=position, s=straggle:
                    v * _gaussian_shape(x, p, s),
                thermal_budget=term.get("thermal_budget_cm2", 0.0),
                peak_conc_cm3=peak, peak_position_um=position, straggle_um=straggle,
            ))
        return out

    if region.junction_axis not in (None, "x"):
        raise NotImplementedError(
            f"dopant_profiles_from_doping_profile evaluates along x only; "
            f"got junction_axis={region.junction_axis!r}"
        )
    position = region.peak_position_um
    straggle = region.straggle_um
    if region.donor_peak_conc_cm3 is not None or region.acceptor_peak_conc_cm3 is not None:
        donor_peak = region.donor_peak_conc_cm3 or 0.0
        acceptor_peak = region.acceptor_peak_conc_cm3 or 0.0
    else:
        donor_peak, acceptor_peak = _split_net(region.peak_conc_cm3)
    out: List[DopantProfile] = []
    if donor_peak:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor_peak, p=position, s=straggle:
                v * _gaussian_shape(x, p, s),
            peak_conc_cm3=donor_peak, peak_position_um=position, straggle_um=straggle,
        ))
    if acceptor_peak:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor_peak, p=position, s=straggle:
                v * _gaussian_shape(x, p, s),
            peak_conc_cm3=acceptor_peak, peak_position_um=position, straggle_um=straggle,
        ))
    return out


def _implant_windows_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.junction_axis not in (None, "x"):
        raise NotImplementedError(
            f"dopant_profiles_from_doping_profile evaluates along x only; "
            f"got junction_axis={region.junction_axis!r}"
        )
    if region.donor_conc_cm3 is not None or region.acceptor_conc_cm3 is not None:
        bg_donor = region.donor_conc_cm3 or 0.0
        bg_acceptor = region.acceptor_conc_cm3 or 0.0
    else:
        bg_donor, bg_acceptor = _split_net(region.net_doping_cm3)

    donor_windows: List[Tuple[float, float, float]] = []
    acceptor_windows: List[Tuple[float, float, float]] = []
    for window in region.implant_windows or []:
        if "donor_conc_cm3" in window or "acceptor_conc_cm3" in window:
            d = window.get("donor_conc_cm3", 0.0)
            a = window.get("acceptor_conc_cm3", 0.0)
        else:
            d, a = _split_net(window.get("conc_cm3"))
        if d:
            donor_windows.append((window["min_um"], window["max_um"], d))
        if a:
            acceptor_windows.append((window["min_um"], window["max_um"], a))

    out: List[DopantProfile] = []
    if bg_donor or donor_windows:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=_windowed_sum(bg_donor, donor_windows),
        ))
    if bg_acceptor or acceptor_windows:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=_windowed_sum(bg_acceptor, acceptor_windows),
        ))
    return out


def _windowed_sum(
    background: float,
    windows: List[Tuple[float, float, float]],
) -> Callable[[float, float], float]:
    def f(x_um: float, depth_um: float) -> float:
        total = background
        for lo, hi, mag in windows:
            total += mag * _step(x_um - lo) * _step(hi - x_um)
        return total
    return f
