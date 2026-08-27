#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DC operating point -- solve a MOSFET device at ONE arbitrary bias
point and read real terminal currents. Deliberately NOT a separate
physics implementation: this is exactly what
tcad.characterization.mosfet_sweep.run_mosfet_id_vgs_sweep already
does at every point of its own sweep loop, called here with a
single-element gate_voltages list. Kept as its own thin function
rather than asking every DC-operating-point caller to remember "pass
a 1-element list and take points[0]" -- the same reasoning
tcad_2d_stagewise.py's own run_measurement() already applies for the
2-terminal case (sweep_voltages=[voltage]).
"""

from __future__ import annotations

from typing import Optional

from tcad.characterization.interface import BiasPoint
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep


def solve_mosfet_dc_operating_point(
    device: str,
    si_region: str,
    oxide_region: str,
    source_contact: str,
    drain_contact: str,
    gate_contact: str,
    interface_name: str,
    drain_voltage: float,
    gate_voltage: float,
    body_contact: Optional[str] = None,
    body_voltage: float = 0.0,
    temperature_k: float = 300.0,
) -> BiasPoint:
    """Solve equilibrium, enable drift-diffusion, ramp drain/gate (and
    body, if given) to the requested bias, and return the single
    resulting BiasPoint (real source/drain/[body] currents).

    Same one-call-per-device restriction as run_mosfet_id_vgs_sweep --
    `device` must be freshly imported and doped, not already solved.
    """
    result = run_mosfet_id_vgs_sweep(
        device=device, si_region=si_region, oxide_region=oxide_region,
        source_contact=source_contact, drain_contact=drain_contact,
        gate_contact=gate_contact, interface_name=interface_name,
        gate_voltages=[gate_voltage], drain_voltage=drain_voltage,
        body_contact=body_contact, body_voltage=body_voltage,
        temperature_k=temperature_k,
    )
    return result.points[0]
