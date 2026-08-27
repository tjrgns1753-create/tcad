#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MOSFET Id-Vgs transfer-characteristic sweep — real electron/hole
drift-diffusion in the channel, gate-coupled through a real Si-SiO2
interface (tcad.device.devsim.mosfet_equation), as opposed to
cv_sweep.py's equilibrium-only gate C-V sweep (no transport, no
terminal current) or pn_junction_iv_sweep.py's two-terminal diode
sweep (no gate). This is the first sweep in this project actually
exercising source-to-drain current under gate control.

Sequence (mirrors pn_junction_iv_sweep.py's own real flow, extended
with the oxide/gate coupling mosfet_equation.py adds; the exact
tolerances/ramping strategy below were found necessary by real
execution against this project's own gate_stack + implant_windows
device — see CLAUDE.md's MOSFET Id-Vgs investigation, not assumed to
work just because Phase 8's plain-Si version and Phase 9's
plain-oxide-equilibrium version each separately converge fine):
  1. NetDoping must already be registered (tcad.device.devsim.
     doping_mapping.apply_doping) before calling this.
  2. setup_mosfet_potential_equation() + solve() — Si+oxide equilibrium
     (no transport yet). Converges readily at a tight tolerance —
     confirmed real execution, unlike steps 3-4 below.
  3. setup_drift_diffusion_equation() (unchanged from Phase 8) + solve()
     at DevSim's OWN official gmsh_mos2d.py example's exact tolerances
     (absolute_error=1e30, relative_error=1e-5) — turns on Electrons/
     Holes continuity in Si at the same converged equilibrium bias.
     Confirmed necessary, not just copied: this project's own existing
     drift-diffusion default (absolute_error=1e10,
     pn_junction_iv_sweep.py's own value) measurably does NOT converge
     for this Si+oxide+interface combination — it plateaus at a
     residual oscillation around 2-6e-5 rather than settling, even at
     100+ iterations; the official example's own, much looser
     1e30/1e-5 pair does.
  4. Ramp the drain bias up from 0V to `drain_voltage` via DevSim's own
     `devsim.python_packages.ramp.rampbias` (adaptive step size,
     automatically halves and retries on a convergence failure) —
     confirmed necessary by real execution: jumping straight from 0V
     to a nonzero drain bias in one Newton step (this project's
     original, simpler approach, matching pn_junction_iv_sweep.py's
     own single-jump style) produces a massive initial residual
     (~1e16) and fails outright; rampbias, starting from a fixed,
     physically-reasonable step size (matching the official example's
     own convention — see `_RAMP_STEP_SIZE`) and halving as needed,
     reaches the same converged state without any hand-tuned per-call
     step count.
  5. Sweep gate voltage the same way — via rampbias per target voltage,
     not a single jump — reading real source/drain terminal current at
     each converged point. Confirmed necessary specifically near the
     threshold-turn-on region (this project's own test device turns on
     around Vgs~1.4-1.5V): a plain single-step solve() at Vgs=1.5V
     fails outright, while rampbias reaches it via a sequence of
     automatically-shrinking sub-steps (down to sub-mV near the hardest
     point) with no manual tuning of where or how finely to step.
"""

from __future__ import annotations

from typing import List, Optional

from tcad.characterization.interface import CURRENT_CONVENTION_NOTE, BiasPoint, CharacterizationResult
from tcad.device.devsim import backend
from tcad.device.devsim.mosfet_equation import setup_mosfet_potential_equation
from tcad.device.devsim.semiconductor_equation import (
    read_drift_diffusion_terminal_currents,
    setup_drift_diffusion_equation,
)

#: DevSim's OWN official gmsh_mos2d.py example's drift-diffusion solve
#: tolerances (read via inspect.getsource, not guessed) -- confirmed by
#: real execution to be necessary for THIS project's Si+oxide+interface
#: MOSFET device too (see module docstring point 3).
_DD_ABSOLUTE_ERROR = 1.0e30
_DD_RELATIVE_ERROR = 1.0e-5

#: rampbias() parameters (see module docstring points 4-5). min_step is
#: deliberately far smaller than a physically meaningful voltage
#: increment -- it is a LAST-RESORT floor rampbias only reaches while
#: repeatedly halving from a failed larger step, not a target
#: resolution; real execution needed sub-mV steps specifically near
#: this device's own threshold-turn-on region (~1.4-1.5V) to get
#: through it at all.
_RAMP_MIN_STEP = 1.0e-6
_RAMP_MAX_ITER = 150

#: Initial (largest) step rampbias attempts before any halving -- a
#: fixed value, NOT derived from the target bias itself: passing the
#: target voltage as step_size would make rampbias's own
#: `next_bias = last_bias + step_sign * step_size` never move at all
#: whenever a target happens to be exactly 0.0 (step_size=0), an
#: infinite loop for any start_bias != 0. Matches DevSim's own official
#: gmsh_mos2d.py example's convention of a fixed, physically-reasonable
#: max step (they use 0.5 for their own gate ramp) rather than one
#: derived from wherever the sweep happens to be heading.
_RAMP_STEP_SIZE = 0.5


def run_mosfet_id_vgs_sweep(
    device: str,
    si_region: str,
    oxide_region: str,
    source_contact: str,
    drain_contact: str,
    gate_contact: str,
    interface_name: str,
    gate_voltages: List[float],
    drain_voltage: float,
    temperature_k: float = 300.0,
    relative_error: float = 1.0e-6,
    maximum_iterations: int = 100,
    body_contact: Optional[str] = None,
    body_voltage: float = 0.0,
) -> CharacterizationResult:
    """Solve Si+oxide equilibrium, enable Si drift-diffusion, ramp the
    drain bias, then sweep gate voltage — reading real source/drain
    terminal current at every point. Source is held at 0V (the
    reference every other bias in this sweep is relative to).

    relative_error / maximum_iterations : used ONLY for the initial
    Si+oxide equilibrium solve (step 2 in the module docstring), which
    converges readily — same looser-than-DevSim's-own-clean-1D-examples
    defaults pn_junction_iv_sweep.py already uses and documents. The
    drift-diffusion and bias-ramp stages use their own, separately
    -justified tolerances (see module docstring points 3-5) — real
    execution found this project's own single, shared `relative_error`
    convention insufficient for those stages on this device.

    One call per device, same restriction pn_junction_iv_sweep.py
    documents for the same underlying reason (DevSim's own equation
    registration is not meant to be re-run on an already-swept device):
    import and dope a fresh device for a different drain_voltage or
    sweep direction.

    Every current returned (source_contact/drain_contact in each
    BiasPoint.currents, below) is PER UNIT DEPTH — DevSim's own
    2D-device convention, not the total current of a real device with
    a specific physical channel width. See
    tcad.characterization.interface.CURRENT_CONVENTION_NOTE (also set
    on this result's own metadata["current_convention"]) for what that
    means and how to convert it to a real device's actual current.
    """
    module = backend.require_devsim()
    from devsim.python_packages.ramp import rampbias

    si_contacts = [source_contact, drain_contact]
    if body_contact is not None:
        si_contacts = si_contacts + [body_contact]
    no_op_callback = lambda _device: None  # noqa: E731 -- rampbias requires a callback; this sweep reads currents itself, per point, below

    # 1. Equilibrium: Si + oxide Poisson-only, coupled at the interface.
    setup_mosfet_potential_equation(
        device, si_region, oxide_region, si_contacts, gate_contact,
        interface_name, temperature_k,
    )
    module.solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)

    # 2. Enable drift-diffusion transport in Si at the same equilibrium bias.
    setup_drift_diffusion_equation(device, si_region, si_contacts)
    module.solve(
        type="dc", absolute_error=_DD_ABSOLUTE_ERROR, relative_error=_DD_RELATIVE_ERROR,
        maximum_iterations=maximum_iterations,
    )

    # 3. Ramp the drain bias up to its target (see module docstring point 4).
    rampbias(
        device, drain_contact, drain_voltage, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
        _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
    )

    if body_contact is not None:
        from tcad.device.devsim.resistor_equation import set_bias
        set_bias(device, body_contact, body_voltage)

    points: List[BiasPoint] = []
    for vg in gate_voltages:
        # 4. Ramp gate voltage to each target (see module docstring point 5).
        rampbias(
            device, gate_contact, vg, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
            _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
        )

        currents = read_drift_diffusion_terminal_currents(device, si_contacts)
        voltages = {source_contact: 0.0, drain_contact: drain_voltage, gate_contact: vg}
        if body_contact is not None:
            voltages[body_contact] = body_voltage

        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="mosfet_id_vgs_sweep",
        device=device,
        region=si_region,
        sweep_contact=gate_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "oxide_region": oxide_region,
            "source_contact": source_contact,
            "drain_contact": drain_contact,
            "drain_voltage": drain_voltage,
            "interface": interface_name,
            "physics": "drift_diffusion",
            "current_convention": CURRENT_CONVENTION_NOTE,
            "body_contact": body_contact,
            "body_voltage": body_voltage,
        },
    )


def run_mosfet_id_vds_sweep(
    device: str,
    si_region: str,
    oxide_region: str,
    source_contact: str,
    drain_contact: str,
    gate_contact: str,
    interface_name: str,
    drain_voltages: List[float],
    gate_voltage: float,
    temperature_k: float = 300.0,
    relative_error: float = 1.0e-6,
    maximum_iterations: int = 100,
    body_contact: Optional[str] = None,
    body_voltage: float = 0.0,
) -> CharacterizationResult:
    """Solve Si+oxide equilibrium, enable Si drift-diffusion, ramp the
    gate bias to its fixed target, then sweep drain voltage -- reading
    real source/drain terminal current at every point. Mirrors
    run_mosfet_id_vgs_sweep's own sequence exactly, with the gate and
    drain roles swapped (gate is ramped ONCE, drain is the swept
    variable) -- see that function's own docstring for why each
    tolerance/ramp constant below is what it is; this sweep reuses the
    identical values rather than re-deriving them, since it exercises
    the same Si+oxide+interface device under the same drift-diffusion
    equations.

    One call per device -- same restriction run_mosfet_id_vgs_sweep
    documents. Every current returned is PER UNIT DEPTH -- see
    tcad.characterization.interface.CURRENT_CONVENTION_NOTE.
    """
    module = backend.require_devsim()
    from devsim.python_packages.ramp import rampbias

    si_contacts = [source_contact, drain_contact]
    if body_contact is not None:
        si_contacts = si_contacts + [body_contact]
    no_op_callback = lambda _device: None  # noqa: E731

    # 1. Equilibrium: Si + oxide Poisson-only, coupled at the interface.
    setup_mosfet_potential_equation(
        device, si_region, oxide_region, si_contacts, gate_contact,
        interface_name, temperature_k,
    )
    module.solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)

    # 2. Enable drift-diffusion transport in Si at the same equilibrium bias.
    setup_drift_diffusion_equation(device, si_region, si_contacts)
    module.solve(
        type="dc", absolute_error=_DD_ABSOLUTE_ERROR, relative_error=_DD_RELATIVE_ERROR,
        maximum_iterations=maximum_iterations,
    )

    # 3. Ramp the gate bias up to its fixed target.
    rampbias(
        device, gate_contact, gate_voltage, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
        _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
    )

    if body_contact is not None:
        from tcad.device.devsim.resistor_equation import set_bias
        set_bias(device, body_contact, body_voltage)

    points: List[BiasPoint] = []
    for vd in drain_voltages:
        # 4. Ramp drain voltage to each target.
        rampbias(
            device, drain_contact, vd, _RAMP_STEP_SIZE, _RAMP_MIN_STEP,
            _RAMP_MAX_ITER, _DD_RELATIVE_ERROR, _DD_ABSOLUTE_ERROR, no_op_callback,
        )

        currents = read_drift_diffusion_terminal_currents(device, si_contacts)
        voltages = {source_contact: 0.0, gate_contact: gate_voltage, drain_contact: vd}
        if body_contact is not None:
            voltages[body_contact] = body_voltage

        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="mosfet_id_vds_sweep",
        device=device,
        region=si_region,
        sweep_contact=drain_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "oxide_region": oxide_region,
            "source_contact": source_contact,
            "gate_contact": gate_contact,
            "gate_voltage": gate_voltage,
            "interface": interface_name,
            "physics": "drift_diffusion",
            "current_convention": CURRENT_CONVENTION_NOTE,
            "body_contact": body_contact,
            "body_voltage": body_voltage,
        },
    )
