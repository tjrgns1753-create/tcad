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
from typing import Dict, List

from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult


def apply_uniform_doping(
    result: ProcessResult,
    doping_by_region_cm3: Dict[str, float],
) -> ProcessResult:
    """Return a new ProcessResult with uniform doping attached.

    doping_by_region_cm3 : {region_name: net_doping_cm3}. Each key
        should match a MaterialRegion.name already present on `result`
        (not enforced here — DevSim-side mapping will simply skip
        regions without a DopingRegion entry).
    """
    regions = [
        DopingRegion(region=name, net_doping_cm3=value)
        for name, value in doping_by_region_cm3.items()
    ]
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
    peak_conc_cm3: float,
) -> ProcessResult:
    """Return a new ProcessResult with a 1D Gaussian implant doping
    profile attached to one region: net doping along `junction_axis`
    is peak_conc_cm3 * exp(-((axis - peak_position_um)^2) /
    (2*straggle_um^2)) — a simple implant/diffusion approximation, not a
    full process simulation. peak_conc_cm3 sign follows net_doping_cm3's
    convention (positive = net donor, negative = net acceptor).
    """
    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        peak_position_um=peak_position_um,
        straggle_um=straggle_um,
        peak_conc_cm3=peak_conc_cm3,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[doping_region])
    return replace(result, doping=doping)


def apply_implant_windows_doping(
    result: ProcessResult,
    region: str,
    axis: str,
    background_doping_cm3: float,
    windows: List[Dict[str, float]],
) -> ProcessResult:
    """Return a new ProcessResult with a background doping plus zero or
    more laterally-windowed implants SUPERPOSED on top, all in one
    region: e.g. a body/channel background with source and drain
    implants laid out along `axis`.

    windows : list of {"min_um": float, "max_um": float,
        "conc_cm3": float}. Each window ADDS conc_cm3 (signed, same
        convention as background_doping_cm3: positive = net donor,
        negative = net acceptor) to the background wherever
        min_um <= axis-coordinate <= max_um. Windows may overlap (their
        contributions sum) — not validated here, since a caller may
        deliberately want graded overlap; DevSim-side mapping applies
        the windows exactly as given.

    This models the real physical relationship between an implant and
    whatever doping already existed where it lands (superposition), not
    a replacement — the same reason `apply_gaussian_implant_doping`
    doesn't split its result into separate Donors/Acceptors models.
    """
    doping_region = DopingRegion(
        region=region,
        net_doping_cm3=background_doping_cm3,
        junction_axis=axis,
        implant_windows=[dict(window) for window in windows],
    )
    doping = DopingProfile(kind="implant_windows", regions=[doping_region])
    return replace(result, doping=doping)
