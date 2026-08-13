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

Implements uniform (Phase 7), step-junction (Phase 8), and
gaussian_implant doping. gaussian_implant adds position-dependent
fields to DopingRegion (peak_conc_cm3, peak_position_um, straggle_um)
and this module's apply_gaussian_implant_doping() — no change needed to
ProcessResult or DopingProfile's `regions` shape, matching the design
this module already anticipated for it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict

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
