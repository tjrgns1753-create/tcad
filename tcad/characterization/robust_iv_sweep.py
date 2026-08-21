#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A more robust 2-terminal drift-diffusion I-V sweep than
pn_junction_iv_sweep.run_pn_junction_iv_sweep(), for heavily-doped
`implant_windows` devices where that function's single-jump strategy
fails outright.

pn_junction_iv_sweep.py is deliberately left untouched: it is what
every Phase 8 / doping-kind regression test already validates, and its
simpler strategy is sufficient (and faster) for the doping levels those
tests use. This module is the opt-in path for the harder cases.

Three differences from that function, each one separately measured on
this project's own failing device (the GUI's default 10x8um wafer with
1e20 cm^-3 implant windows on a -1e17 body), NOT assumed:

1. DOPING-LEVEL CONTINUATION for the equilibrium solve.
   Setting NetDoping to its full 1e20 cm^-3 in one step makes the
   Poisson-only equilibrium solve fail outright ("Convergence failure!",
   RelError climbing 1.0 -> 1.52). Ramping the implant windows'
   concentration 1e17 -> 1e20 in five geometric steps, re-solving at
   each and letting the previous step's converged Potential seed the
   next, converges reliably on the identical mesh. This is the same
   mechanism DevSim's own bias ramping uses, applied to a doping-level
   parameter instead of a contact voltage.

2. DevSim's OWN official drift-diffusion tolerances
   (absolute_error=1e30, relative_error=1e-5, from its gmsh_mos2d.py
   example) for the transport-enable solve, instead of
   pn_junction_iv_sweep.py's absolute_error=1e10. Already validated
   inside this project by the passing MOSFET Id-Vgs test at the same
   1e20 doping, whose own module docstring records that 1e10
   "plateaus at a residual oscillation around 2-6e-5 rather than
   settling, even at 100+ iterations" -- reproduced here exactly.
   DevSim requires BOTH its absolute and relative criteria to be met
   (confirmed from this project's own solver logs: a solve showing
   RelError 9.08e-06 against a 1e-5 tolerance kept iterating because
   AbsError 2.86e10 exceeded the 1e10 absolute tolerance), so an
   absolute tolerance of 1e10 is unreachable once carrier densities
   are ~1e20 and effectively blocks convergence.

3. A BIAS RAMP THAT RESTORES THE SOLUTION on a failed step. DevSim's
   own `devsim.python_packages.ramp.rampbias` restores only the bias
   PARAMETER when a step fails, never the Potential/Electrons/Holes
   node solutions -- so a diverged attempt leaves the device in the
   corrupted state its failed Newton iteration produced, and every
   subsequent (halved) step starts from there. This ramp snapshots the
   solution before each attempt and restores it before retrying.

Verified not to change answers: on this project's own known-passing
4x3um implant_windows recipe, this path returns +3.475281e-11 A where
`run_pn_junction_iv_sweep` returns +3.475285e-11 A -- the same current
to six significant figures, with equal-and-opposite terminal currents.

KNOWN LIMIT, measured rather than assumed: this does NOT make every
`implant_windows` device converge. A configuration that puts an
implant-window edge within about half a grid cell of an ETCHED
SIDEWALL -- forming a full-thickness strip of the heavily-doped
material narrower than one mesh cell -- still fails in the bias ramp at
1e20 cm^-3, while converging normally at 1e19 and below on the
identical mesh and geometry. See CLAUDE.md's implant_windows OPEN item
for the full characterization and everything ruled out.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from tcad.characterization.interface import BiasPoint, CharacterizationResult
from tcad.device.devsim import backend
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.semiconductor_equation import (
    read_drift_diffusion_terminal_currents,
    setup_drift_diffusion_equation,
    setup_semiconductor_potential_equation,
)
from tcad.mesh.interface import DopingProfile

#: DevSim's own official gmsh_mos2d.py drift-diffusion tolerances (see
#: module docstring point 2). Not this project's invention, and already
#: validated here by the passing MOSFET Id-Vgs test at 1e20 doping.
_DD_ABSOLUTE_ERROR = 1.0e30
_DD_RELATIVE_ERROR = 1.0e-5

#: Equilibrium (Poisson-only) tolerances -- pn_junction_iv_sweep.py's
#: own already-validated values, unchanged.
_EQ_ABSOLUTE_ERROR = 1.0
_EQ_RELATIVE_ERROR = 1.0e-6

#: Window-concentration multipliers for the equilibrium continuation
#: (module docstring point 1). Geometric, ending at 1.0 (the real
#: profile). Verified sufficient on the 10x8um / 1e20 cm^-3 device that
#: fails without it; the first step is deliberately near the background
#: doping's own magnitude, which the solve handles trivially.
_DOPING_RAMP_SCALES = (1.0e-3, 1.0e-2, 0.1, 0.3, 1.0)

_SOLUTION_NAMES = ("Potential", "Electrons", "Holes")


def ramp_doping_to_equilibrium(
    device: str,
    region: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    scales: Optional[List[float]] = None,
    contacts: Optional[List[str]] = None,
    temperature_k: float = 300.0,
) -> None:
    """Register the equilibrium (Poisson-only) equations and reach the
    full doping profile by CONTINUATION rather than in one step.

    Only meaningful for `implant_windows` (the only kind `apply_doping`
    can scale); any other kind is applied once at full strength, which
    is exactly what the non-continuation path already does.
    """
    module = backend.require_devsim()
    ramp = list(scales) if scales is not None else list(_DOPING_RAMP_SCALES)
    if doping.kind != "implant_windows":
        ramp = [1.0]

    # NetDoping must exist before the potential equation is registered:
    # DevSim's CreateSiliconPotentialOnly references it at setup time.
    apply_doping(device, doping, length_scale_to_cm, window_scale=ramp[0])
    setup_semiconductor_potential_equation(
        device, region, contacts or [], temperature_k
    )
    for scale in ramp:
        apply_doping(device, doping, length_scale_to_cm, window_scale=scale)
        module.solve(
            type="dc",
            absolute_error=_EQ_ABSOLUTE_ERROR,
            relative_error=_EQ_RELATIVE_ERROR,
            maximum_iterations=100,
        )


def ramp_bias_with_restore(
    device: str,
    region: str,
    contact: str,
    target_voltage: float,
    initial_step: float = 0.05,
    min_step: float = 1.0e-7,
    relative_error: float = _DD_RELATIVE_ERROR,
    absolute_error: float = _DD_ABSOLUTE_ERROR,
    maximum_iterations: int = 100,
    max_attempts: int = 400,
) -> float:
    """Backtracking bias continuation that RESTORES the node solutions
    when a step fails (see module docstring point 3), returning the
    voltage actually reached.

    Raises RuntimeError if the step size has to shrink below
    `min_step`, or `max_attempts` is exceeded, rather than silently
    reporting a bias the device never actually reached.
    """
    module = backend.require_devsim()
    current = module.get_parameter(device=device, name=f"{contact}_bias")
    step = initial_step
    attempts = 0

    while abs(target_voltage - current) > 1.0e-12:
        snapshot = {
            name: module.get_node_model_values(
                device=device, region=region, name=name
            )
            for name in _SOLUTION_NAMES
        }
        delta = min(step, abs(target_voltage - current))
        nxt = current + math.copysign(delta, target_voltage - current)
        module.set_parameter(device=device, name=f"{contact}_bias", value=nxt)
        attempts += 1
        try:
            module.solve(
                type="dc",
                absolute_error=absolute_error,
                relative_error=relative_error,
                maximum_iterations=maximum_iterations,
            )
            current = nxt
            step = min(step * 1.5, initial_step)
        except Exception:
            for name, values in snapshot.items():
                module.set_node_values(
                    device=device, region=region, name=name, values=values
                )
            module.set_parameter(device=device, name=f"{contact}_bias", value=current)
            step *= 0.5
            if step < min_step:
                raise RuntimeError(
                    f"bias ramp stalled at {current:.6g} V (target "
                    f"{target_voltage:.6g} V) after {attempts} solve attempts: "
                    f"step size fell below {min_step:g}"
                )
        if attempts > max_attempts:
            raise RuntimeError(
                f"bias ramp gave up at {current:.6g} V (target "
                f"{target_voltage:.6g} V) after {attempts} solve attempts"
            )
    return current


def run_robust_pn_junction_iv_sweep(
    device: str,
    region: str,
    all_contacts: List[str],
    sweep_contact: str,
    sweep_voltages: List[float],
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    fixed_contacts: Optional[Dict[str, float]] = None,
    temperature_k: float = 300.0,
) -> CharacterizationResult:
    """Equilibrium by doping continuation, drift-diffusion at DevSim's
    own official tolerances, then a state-restoring bias ramp to each
    requested voltage.

    `doping` is required (unlike `run_pn_junction_iv_sweep`, which only
    needs NetDoping already registered) because the continuation has to
    re-register NetDoping at each ramp step. Do NOT call `apply_doping`
    yourself first — this function owns that.

    Voltages are visited in the order given; each is reached by ramping
    from wherever the previous one left off, so a caller sweeping
    monotonically gets the cheapest path.
    """
    fixed_contacts = fixed_contacts or {}

    ramp_doping_to_equilibrium(
        device, region, doping, length_scale_to_cm,
        contacts=all_contacts, temperature_k=temperature_k,
    )

    module = backend.require_devsim()
    setup_drift_diffusion_equation(device, region, all_contacts)
    module.solve(
        type="dc",
        absolute_error=_DD_ABSOLUTE_ERROR,
        relative_error=_DD_RELATIVE_ERROR,
        maximum_iterations=100,
    )

    for contact, voltage in fixed_contacts.items():
        ramp_bias_with_restore(device, region, contact, voltage)

    points: List[BiasPoint] = []
    for voltage in sweep_voltages:
        ramp_bias_with_restore(device, region, sweep_contact, voltage)
        currents = read_drift_diffusion_terminal_currents(device, all_contacts)
        voltages = {c: fixed_contacts.get(c, 0.0) for c in all_contacts}
        voltages[sweep_contact] = voltage
        points.append(BiasPoint(voltages=voltages, currents=currents))

    return CharacterizationResult(
        name="robust_pn_junction_iv_sweep",
        device=device,
        region=region,
        sweep_contact=sweep_contact,
        points=points,
        metadata={
            "temperature_k": temperature_k,
            "fixed_contacts": fixed_contacts,
            "physics": "drift_diffusion",
            "strategy": "doping_continuation + devsim_dd_tolerances + restoring_bias_ramp",
        },
    )
