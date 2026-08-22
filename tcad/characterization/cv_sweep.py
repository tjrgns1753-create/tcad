#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MOS capacitor C-V sweep — real gate charge extracted at each bias via
DevSim's get_contact_charge (same real API used in
devsim_data/examples/capacitance/cap2d.py), capacitance computed as a
real finite-difference dQ/dV between consecutive solved bias points.
No synthetic C-V data: every point comes from an actual DevSim solve.

Only this module (plus tcad.device.devsim.mos_equation, which it
calls) knows about the MOS-specific DevSim API — it returns the same
CharacterizationResult shape iv_sweep.py / pn_junction_iv_sweep.py use,
extended with a "capacitance_F" metadata series (not part of
BiasPoint's fixed shape, since capacitance is derived between
consecutive points rather than measured at one).
"""

from __future__ import annotations

from typing import List

from tcad.characterization.interface import CURRENT_CONVENTION_NOTE, BiasPoint, CharacterizationResult
from tcad.device.devsim import backend
from tcad.device.devsim.mos_equation import setup_mos_potential_equation
from tcad.device.devsim.resistor_equation import set_bias


def run_mos_cv_sweep(
    device: str,
    si_region: str,
    oxide_region: str,
    gate_contact: str,
    substrate_contact: str,
    interface_name: str,
    gate_voltages: List[float],
    temperature_k: float = 300.0,
    relative_error: float = 1.0e-6,
    maximum_iterations: int = 100,
) -> CharacterizationResult:
    """Sweep gate voltage, solving equilibrium at each point and reading
    real gate charge; capacitance is the real finite-difference dQ/dV
    between consecutive solved points (so it has one fewer entry than
    gate_voltages — stored in metadata, not as BiasPoint fields, since
    it is defined between points rather than at one).

    Every gate charge / capacitance value returned (metadata's
    "gate_charges_C" / "capacitance_F", below) is PER UNIT DEPTH —
    DevSim's own 2D-device convention (same one
    tcad.characterization.pn_junction_iv_sweep.run_pn_junction_iv_sweep's
    currents follow), not the total charge/capacitance of a real device
    with a specific physical gate width. See
    tcad.characterization.interface.CURRENT_CONVENTION_NOTE (also set
    on this result's own metadata["current_convention"], despite the
    name — it applies to charge/capacitance identically) for what that
    means and how to convert it to a real device's actual value.
    """
    module = backend.require_devsim()

    setup_mos_potential_equation(
        device, si_region, oxide_region, gate_contact, substrate_contact,
        interface_name, temperature_k,
    )
    set_bias(device, substrate_contact, 0.0)

    points: List[BiasPoint] = []
    gate_charges: List[float] = []

    for voltage in gate_voltages:
        set_bias(device, gate_contact, voltage)
        module.solve(
            type="dc", absolute_error=1.0, relative_error=relative_error,
            maximum_iterations=maximum_iterations,
        )

        gate_charge = module.get_contact_charge(device=device, contact=gate_contact, equation="PotentialEquation")
        gate_charges.append(gate_charge)

        points.append(BiasPoint(
            voltages={gate_contact: voltage, substrate_contact: 0.0},
            currents={},  # equilibrium solve: no transport, no terminal current
        ))

    capacitance_f: List[float] = []
    capacitance_voltages: List[float] = []
    for i in range(len(gate_voltages) - 1):
        dv = gate_voltages[i + 1] - gate_voltages[i]
        dq = gate_charges[i + 1] - gate_charges[i]
        capacitance_f.append(dq / dv if dv != 0 else float("nan"))
        capacitance_voltages.append(0.5 * (gate_voltages[i] + gate_voltages[i + 1]))

    return CharacterizationResult(
        name="mos_cv_sweep",
        device=device,
        region=si_region,
        sweep_contact=gate_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "oxide_region": oxide_region,
            "substrate_contact": substrate_contact,
            "interface": interface_name,
            "gate_charges_C": gate_charges,
            "capacitance_F": capacitance_f,
            "capacitance_voltages_V": capacitance_voltages,
            "current_convention": CURRENT_CONVENTION_NOTE,
        },
    )
