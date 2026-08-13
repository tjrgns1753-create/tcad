#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Basic semiconductor device physics (Poisson-only, doping-aware) — an
addition alongside tcad/device/devsim/resistor_equation.py, which is
unchanged and still available for the doping-free Ohmic characterization
from Phase 6.

Real API used: DevSim's own official helpers from
devsim.python_packages.simple_physics, read directly from source
(inspect.getsource) rather than guessed, then run against a real
ViennaPS-imported device with real doping (see
tests/test_phase7_doping_real.py):

    from devsim.python_packages.simple_physics import (
        SetSiliconParameters, CreateSiliconPotentialOnly,
        CreateSiliconPotentialOnlyContact,
    )
    SetSiliconParameters(device, region, temperature_k)   # sets Permittivity,
                                                            # n_i, V_t, mu_n/mu_p, etc.
    CreateSiliconPotentialOnly(device, region)             # requires NetDoping
                                                            # already registered
                                                            # (see doping_mapping.py)
    CreateSiliconPotentialOnlyContact(device, region, contact)  # Ohmic contact:
        # Potential - bias + V_t*ln(...) built-in-potential term, sign
        # following NetDoping — read from source, not guessed.

CreateSiliconPotentialOnlyContact internally uses a bias parameter
named "{contact}_bias" (via its own GetContactBiasName helper) — the
exact same naming tcad/device/devsim/resistor_equation.py already uses,
so tcad.device.devsim.resistor_equation.set_bias() works unchanged for
this equation too.

This is still not full drift-diffusion (no carrier continuity
equations, no mobility-dependent current) — it solves for the
electrostatic potential using Boltzmann carrier statistics and real
doping, which is the standard first physics step in DevSim's own
bundled diode example before continuity equations are added. Full
drift-diffusion is future work.
"""

from __future__ import annotations

from typing import Dict, List

from tcad.device.devsim import backend


def setup_semiconductor_potential_equation(
    device: str,
    region: str,
    contacts: List[str],
    temperature_k: float = 300.0,
) -> None:
    """Set up the doping-aware Poisson-only equation on `region`.

    NetDoping must already be registered on `region` (see
    tcad.device.devsim.doping_mapping.apply_doping) before calling this
    — CreateSiliconPotentialOnly references it directly.
    """
    backend.require_devsim()  # raises if devsim is unavailable
    from devsim.python_packages.simple_physics import (
        CreateSiliconPotentialOnly,
        CreateSiliconPotentialOnlyContact,
        SetSiliconParameters,
    )

    SetSiliconParameters(device, region, temperature_k)
    CreateSiliconPotentialOnly(device, region)

    module = backend.require_devsim()
    for contact in contacts:
        # CreateSiliconPotentialOnlyContact references "{contact}_bias"
        # (via its own GetContactBiasName helper) but does not
        # initialize it — verified by reading its source. Without this,
        # the parameter is undefined the first time solve() evaluates
        # the contact equation.
        module.set_parameter(device=device, name=f"{contact}_bias", value=0.0)
        CreateSiliconPotentialOnlyContact(device, region, contact)


def setup_drift_diffusion_equation(
    device: str,
    region: str,
    contacts: List[str],
) -> None:
    """Enable full electron/hole drift-diffusion transport on `region`,
    on top of an equilibrium Potential solution already produced by
    setup_semiconductor_potential_equation() (call that first, then
    solve, then call this).

    Real API used (verified against installed DevSim 2.10.1 — matches
    devsim_data/examples/diode/diode_common.py's
    DriftDiffusionInitialSolution() exactly, read via inspect.getsource,
    not guessed):

        from devsim.python_packages.simple_physics import (
            CreateSolution, CreateSiliconDriftDiffusion,
            CreateSiliconDriftDiffusionAtContact,
        )
        CreateSolution(device, region, "Electrons")
        CreateSolution(device, region, "Holes")
        devsim.set_node_values(device=, region=, name="Electrons",
                                init_from="IntrinsicElectrons")
        devsim.set_node_values(device=, region=, name="Holes",
                                init_from="IntrinsicHoles")
        CreateSiliconDriftDiffusion(device, region)
        # per contact:
        CreateSiliconDriftDiffusionAtContact(device, region, contact)
    """
    module = backend.require_devsim()
    from devsim.python_packages.simple_physics import (
        CreateSiliconDriftDiffusion,
        CreateSiliconDriftDiffusionAtContact,
        CreateSolution,
    )

    # SetSiliconParameters' own SRH lifetime defaults (1e-5 s) were
    # found by real testing to make the drift-diffusion equilibrium
    # solve fail to converge on a real ViennaPS-derived mesh; 1e-8 s
    # (the value DevSim's own diode_1d.py example itself overrides to)
    # converges reliably. Not a guess — matches diode_1d.py's own
    # `set_parameter(..., name="taun", value=1e-8)` call, read from
    # source, and confirmed by real execution here.
    module.set_parameter(device=device, region=region, name="taun", value=1.0e-8)
    module.set_parameter(device=device, region=region, name="taup", value=1.0e-8)

    CreateSolution(device, region, "Electrons")
    CreateSolution(device, region, "Holes")
    module.set_node_values(device=device, region=region, name="Electrons", init_from="IntrinsicElectrons")
    module.set_node_values(device=device, region=region, name="Holes", init_from="IntrinsicHoles")

    CreateSiliconDriftDiffusion(device, region)
    for contact in contacts:
        CreateSiliconDriftDiffusionAtContact(device, region, contact)


def read_drift_diffusion_terminal_currents(device: str, contacts: List[str]) -> Dict[str, float]:
    """Read total (electron + hole) terminal current at each contact,
    for a device with setup_drift_diffusion_equation() already applied
    and solved.

    Real API used (matches PrintCurrents() in
    devsim.python_packages.simple_physics, read via inspect.getsource):

        devsim.get_contact_current(device=, contact=, equation="ElectronContinuityEquation")
        devsim.get_contact_current(device=, contact=, equation="HoleContinuityEquation")
        total = electron_current + hole_current
    """
    module = backend.require_devsim()
    from devsim.python_packages.simple_physics import ece_name, hce_name

    currents = {}
    for contact in contacts:
        electron_current = module.get_contact_current(device=device, contact=contact, equation=ece_name)
        hole_current = module.get_contact_current(device=device, contact=contact, equation=hce_name)
        currents[contact] = electron_current + hole_current
    return currents
