#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PN junction I-V bias sweep — real doping-aware Poisson + electron/hole
drift-diffusion, as opposed to iv_sweep.py's doping-free Ohmic model
(kept unchanged; both coexist as separate, independent characterization
paths sharing the same CharacterizationResult output shape).

Sequence (matches devsim_data/examples/diode/diode_1d.py's own real
flow, read via source inspection, not guessed):
  1. NetDoping must already be registered (tcad.device.devsim.
     doping_mapping.apply_doping) before calling this.
  2. setup_semiconductor_potential_equation() + solve() — Poisson-only
     equilibrium (no transport yet).
  3. setup_drift_diffusion_equation() + solve() — turns on Electrons/
     Holes continuity at the same (already-converged) equilibrium bias.
  4. Sweep one contact's bias, solving and reading real terminal
     current (electron + hole) at every step.

Only this module (plus tcad.device.devsim.semiconductor_equation, which
it calls) knows about devsim's drift-diffusion API — the returned
CharacterizationResult is the same backend-independent shape iv_sweep.py
produces, so io.py/plotting.py need no changes.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from tcad.characterization.interface import CURRENT_CONVENTION_NOTE, BiasPoint, CharacterizationResult
from tcad.device.devsim import backend
from tcad.device.devsim.resistor_equation import set_bias
from tcad.device.devsim.semiconductor_equation import (
    read_drift_diffusion_terminal_currents,
    setup_drift_diffusion_equation,
    setup_semiconductor_potential_equation,
)


def run_pn_junction_iv_sweep(
    device: str,
    region: str,
    all_contacts: List[str],
    sweep_contact: str,
    sweep_voltages: List[float],
    fixed_contacts: Optional[Dict[str, float]] = None,
    temperature_k: float = 300.0,
    relative_error: float = 1.0e-6,
    maximum_iterations: int = 100,
) -> CharacterizationResult:
    """Solve equilibrium, enable drift-diffusion, then sweep
    `sweep_contact`'s voltage, reading real terminal current at every
    contact for each point.

    relative_error / maximum_iterations : looser than the 1e-10 /30
    DevSim's own clean 1D examples use — confirmed necessary for a
    real, unstructured 2D ViennaPS-derived mesh (see this project's
    Phase 8 verification: 1e-10 failed to converge even at 100
    iterations on such a mesh; 1e-6 converged and reproduced the
    analytic built-in potential to full floating-point precision).

    doping (NetDoping) must already be registered on `region` — see
    tcad.device.devsim.doping_mapping.apply_doping — before calling
    this.

    Every current returned (in each BiasPoint.currents, below) is PER
    UNIT DEPTH — DevSim's own 2D-device convention, not the total
    current of a real device with a specific physical width. See
    tcad.characterization.interface.CURRENT_CONVENTION_NOTE (also set
    on this result's own metadata["current_convention"]) for what that
    means and how to convert it to a real device's actual current.

    One call per device: this function always (re-)registers the
    equilibrium and drift-diffusion equations from scratch, assuming
    `device` is fresh from doping (matching DevSim's own diode_1d.py,
    which likewise only ramps bias in one direction per run). Calling
    it a second time on the same device — e.g. to sweep the opposite
    bias direction after this call already ran a forward ramp —
    reproducibly fails to reconverge (confirmed by real execution, not
    guessed); import and dope a second device for a reverse sweep
    instead (see tests/test_phase8_pn_junction_real.py).
    """
    module = backend.require_devsim()
    fixed_contacts = fixed_contacts or {}

    # 1. Equilibrium: Poisson-only
    setup_semiconductor_potential_equation(device, region, all_contacts, temperature_k)
    module.solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)

    # 2. Enable drift-diffusion transport at the same equilibrium bias
    setup_drift_diffusion_equation(device, region, all_contacts)
    module.solve(type="dc", absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)

    for contact, voltage in fixed_contacts.items():
        set_bias(device, contact, voltage)

    points: List[BiasPoint] = []
    for voltage in sweep_voltages:
        set_bias(device, sweep_contact, voltage)
        module.solve(type="dc", absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)

        currents = read_drift_diffusion_terminal_currents(device, all_contacts)
        voltages = {c: fixed_contacts.get(c, 0.0) for c in all_contacts}
        voltages[sweep_contact] = voltage

        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="pn_junction_iv_sweep",
        device=device,
        region=region,
        sweep_contact=sweep_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "fixed_contacts": fixed_contacts,
            "physics": "drift_diffusion",
            "current_convention": CURRENT_CONVENTION_NOTE,
        },
    )
