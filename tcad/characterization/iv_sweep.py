#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
I-V bias sweep — the only characterization module that imports the
DevSim backend directly (via tcad.device.devsim.resistor_equation's
string/float-only interface; see that module's docstring for the
device/contact/solution state-exposure design). Everything this
function returns is a CharacterizationResult — plain dataclasses, no
devsim references — so CSV/JSON writers, plotting, and the GUI never
need to import devsim.
"""

from __future__ import annotations

from typing import Dict, List

from tcad.characterization.interface import BiasPoint, CharacterizationResult
from tcad.device.devsim import resistor_equation as devsim_solve


def run_iv_sweep(
    device: str,
    region: str,
    all_contacts: List[str],
    sweep_contact: str,
    sweep_voltages: List[float],
    fixed_contacts: Dict[str, float] | None = None,
    conductivity: float = 1.0,
) -> CharacterizationResult:
    """Sweep `sweep_contact`'s voltage, solving and reading terminal
    currents at every contact for each point.

    fixed_contacts : other contacts' bias, held constant through the
        sweep (default 0.0 for any contact not named here).
    conductivity : Ohmic conductivity used for the doping-free equation
        set up by resistor_equation.setup_ohmic_equation (see that
        module's docstring — this Ohmic path is intentionally
        doping-free; doping-aware I-V uses
        tcad.characterization.pn_junction_iv_sweep instead).
    """
    fixed_contacts = fixed_contacts or {}

    devsim_solve.setup_ohmic_equation(device, region, all_contacts, conductivity=conductivity)

    for contact, voltage in fixed_contacts.items():
        devsim_solve.set_bias(device, contact, voltage)

    points: List[BiasPoint] = []
    for voltage in sweep_voltages:
        devsim_solve.set_bias(device, sweep_contact, voltage)
        devsim_solve.solve_dc()

        currents = devsim_solve.read_terminal_currents(device, all_contacts)
        voltages = {c: fixed_contacts.get(c, 0.0) for c in all_contacts}
        voltages[sweep_contact] = voltage

        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="iv_sweep",
        device=device,
        region=region,
        sweep_contact=sweep_contact,
        points=points,
        metadata={"conductivity": conductivity, "fixed_contacts": fixed_contacts},
    )
