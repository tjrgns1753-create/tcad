#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MOSFET threshold-voltage (Vth) extraction from a real Id-Vgs sweep, by
the standard LINEAR EXTRAPOLATION method: find the point of maximum
transconductance (dId/dVgs) in a LINEAR-region sweep (small, fixed
Vds -- drain current approximately proportional to Vgs-Vth once
inverted), draw that point's own secant line, extrapolate it to Id=0,
then subtract Vds/2 -- the standard textbook correction for a finite,
nonzero drain bias.

Pure function, no devsim import (mirrors this package's own
Process/Device-independence discipline -- see
tcad/characterization/interface.py): operates on plain
(gate_voltages, drain_currents) sequences, or directly on a
CharacterizationResult already produced by
tcad.characterization.mosfet_sweep.run_mosfet_id_vgs_sweep via
extract_vth_from_result().

Closes a real, previously-named gap: tcad/characterization/__init__.py's
own docstring has long named "Vth and subthreshold slope" as future
work, and every "Vth" this project computed before this module existed
was a hand-derived ANALYTICAL value (the standard long-channel formula
Vth = 2*phi_F + sqrt(2*eps_si*eps_0*q*Na*2*phi_F)/Cox) used only to
sanity-check an already-simulated Id-Vgs curve after the fact (see
CLAUDE.md's "MOSFET Id-Vgs magnitude gap" investigation) -- never
EXTRACTED from a real simulated curve the way a real characterization
lab (or a real TCAD tool's own post-processing) would. See
tests/integration/test_mosfet_vth_extraction_real.py for this run
against a real ViennaPS+DevSim Id-Vgs sweep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tcad.characterization.interface import CharacterizationResult


@dataclass
class VthExtractionResult:
    """Result of one linear-extrapolation Vth extraction.

    vth_v : extracted threshold voltage (V) -- the steepest segment's
        own secant line's Vgs-intercept, minus drain_voltage/2.
    gm_max : the transconductance (dId/dVgs) of the steepest segment
        found among the swept points, in whatever current unit the
        input used -- for a DevSim-backed sweep this is PER UNIT DEPTH,
        see tcad.characterization.interface.CURRENT_CONVENTION_NOTE.
    vgs_at_gm_max : midpoint gate voltage of the steepest segment (i.e.
        where gm_max was measured).
    intercept_v : the secant line's own Vgs-axis intercept (Id=0),
        BEFORE the drain_voltage/2 correction -- vth_v = intercept_v -
        drain_voltage/2.
    """

    vth_v: float
    gm_max: float
    vgs_at_gm_max: float
    intercept_v: float


def extract_vth_linear_extrapolation(
    gate_voltages: Sequence[float],
    drain_currents: Sequence[float],
    drain_voltage: float,
) -> VthExtractionResult:
    """Standard linear-extrapolation Vth extraction from raw Id-Vgs data.

    gate_voltages / drain_currents : same length; every point must come
        from the SAME LINEAR-REGION sweep (one fixed, small
        drain_voltage) -- this method is not meaningful for a
        saturation-region (Vds >= Vgs-Vth) sweep. Need not be
        pre-sorted (sorted internally by gate_voltages).
    drain_voltage : the fixed Vds the whole sweep was run at -- used
        only for the standard Vth = Vgs_intercept - Vds/2 correction.

    Method: compute the transconductance gm[i] = (Id[i+1]-Id[i]) /
    (Vgs[i+1]-Vgs[i]) between every adjacent pair of (sorted) points,
    take the segment with the LARGEST gm (the steepest part of the
    curve -- physically, past the subthreshold-to-strong-inversion
    transition, where Id first becomes quasi-linear in Vgs), and
    extrapolate that segment's own secant line forward to Id=0. Using
    the single steepest MEASURED segment (rather than a least-squares
    fit across several points) keeps this robust to a coarse or
    non-uniformly-spaced sweep, at the cost of being sensitive to noise
    in that one segment -- a caller wanting a smoother fit should
    pre-average/densify its own (gate_voltages, drain_currents) before
    calling this.

    Raises ValueError if fewer than 2 points are given, or if no
    segment has positive transconductance (the sweep never turns on --
    nothing to extrapolate).
    """
    if len(gate_voltages) != len(drain_currents):
        raise ValueError(
            f"gate_voltages ({len(gate_voltages)}) and drain_currents "
            f"({len(drain_currents)}) must be the same length"
        )
    if len(gate_voltages) < 2:
        raise ValueError("need at least 2 (Vgs, Id) points to extract Vth")

    pairs = sorted(zip(gate_voltages, drain_currents), key=lambda p: p[0])

    best_gm = None
    best_index = None
    for i in range(len(pairs) - 1):
        vg0, _ = pairs[i]
        vg1, _ = pairs[i + 1]
        dv = vg1 - vg0
        if dv <= 0.0:
            continue
        gm = (pairs[i + 1][1] - pairs[i][1]) / dv
        if best_gm is None or gm > best_gm:
            best_gm = gm
            best_index = i

    if best_gm is None or best_gm <= 0.0:
        raise ValueError(
            "no segment of the sweep has positive transconductance -- "
            "the device never turns on in this data, nothing to "
            "extrapolate"
        )

    vg0, id0 = pairs[best_index]
    vg1, _id1 = pairs[best_index + 1]
    # Secant line through (vg0,id0)-(vg1,id1): Id = id0 + gm*(Vgs - vg0).
    # Id=0 at Vgs = vg0 - id0/gm.
    intercept_v = vg0 - id0 / best_gm
    vth_v = intercept_v - drain_voltage / 2.0
    vgs_at_gm_max = 0.5 * (vg0 + vg1)

    return VthExtractionResult(
        vth_v=vth_v, gm_max=best_gm, vgs_at_gm_max=vgs_at_gm_max,
        intercept_v=intercept_v,
    )


def extract_vth_from_result(
    result: CharacterizationResult,
    drain_contact: str,
) -> VthExtractionResult:
    """Convenience wrapper: pulls (gate_voltages, drain_currents) out of
    a CharacterizationResult shaped like
    tcad.characterization.mosfet_sweep.run_mosfet_id_vgs_sweep's own
    output (the swept gate contact's voltage via
    `points[i].voltages[result.sweep_contact]`, drain current via
    `points[i].currents[drain_contact]`) and the fixed drain voltage
    from `result.metadata["drain_voltage"]`, then calls
    extract_vth_linear_extrapolation().
    """
    if "drain_voltage" not in result.metadata:
        raise ValueError(
            "result.metadata has no 'drain_voltage' key -- "
            "extract_vth_from_result expects a CharacterizationResult "
            "from run_mosfet_id_vgs_sweep (metadata keys present: "
            f"{sorted(result.metadata.keys())})"
        )
    gate_voltages = [pt.voltages[result.sweep_contact] for pt in result.points]
    drain_currents = [pt.currents[drain_contact] for pt in result.points]
    return extract_vth_linear_extrapolation(
        gate_voltages, drain_currents, result.metadata["drain_voltage"],
    )
