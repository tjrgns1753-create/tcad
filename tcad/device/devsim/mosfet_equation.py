#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MOSFET equation setup: full electron/hole drift-diffusion in the
silicon (source/drain Ohmic contacts, real terminal current) coupled
through a real Si-SiO2 interface to a potential-only oxide region with
an idealized gate contact — the combination Phase 8 (drift-diffusion,
tcad.device.devsim.semiconductor_equation) and Phase 9 (oxide coupling,
tcad.device.devsim.mos_equation) each built separately, never combined
in one device before this module.

Real API used — every call here already exists and is already verified
elsewhere in this project; this module only combines them in a new
order (verified this ordering solves, via
tests/integration/test_mosfet_id_vgs_real.py, not assumed to work just
because each piece works alone):

    from devsim.python_packages.simple_physics import (
        SetSiliconParameters, CreateSiliconPotentialOnly,
        CreateSiliconPotentialOnlyContact,
        SetOxideParameters, CreateOxidePotentialOnly, CreateOxideContact,
        CreateSiliconOxideInterface,
    )

Sequence, matching devsim_data/examples/mobility/gmsh_mos2d.py's own
real flow (an official MOSFET example, read via inspect.getsource) as
closely as this project's simpler, doping-region-per-material-region
model allows:
  1. setup_mosfet_potential_equation() — Si POTENTIAL-ONLY (Boltzmann
     statistics, doping-aware, requires NetDoping already registered —
     see tcad.device.devsim.doping_mapping.apply_doping) with an Ohmic
     contact at EVERY silicon contact named (source AND drain, unlike
     mos_equation.py's own setup_mos_potential_equation(), which only
     ever takes ONE substrate_contact — a MOSFET needs at least two),
     plus the oxide's potential-only equation and its own single gate
     contact, plus the interface tying them together.
  2. solve() at this equilibrium (no transport yet, matching Phase 8's
     own two-stage approach: get a converged linear-Boltzmann solution
     BEFORE turning on the nonlinear continuity equations, since the
     latter's own initial guess is built from the former).
  3. tcad.device.devsim.semiconductor_equation.setup_drift_diffusion_equation()
     (UNCHANGED, already handles multiple contacts) turns on real
     Electrons/Holes transport in Si, at the SAME already-converged
     equilibrium bias.
  4. solve() again, then sweep biases and read real terminal current
     via read_drift_diffusion_terminal_currents() (also unchanged).
"""

from __future__ import annotations

from typing import List

from tcad.device.devsim import backend


def setup_mosfet_potential_equation(
    device: str,
    si_region: str,
    oxide_region: str,
    si_contacts: List[str],
    gate_contact: str,
    interface_name: str,
    temperature_k: float = 300.0,
) -> None:
    """Doping-aware Si Poisson-only (multi-contact) + oxide Poisson-only
    + a real Si-SiO2 interface, all on `device` — the equilibrium stage
    every subsequent drift-diffusion solve builds on (call
    tcad.device.devsim.semiconductor_equation.setup_drift_diffusion_equation()
    next, after solving this equilibrium first).

    si_contacts : every Ohmic contact ON THE SILICON region (e.g.
        source and drain) — NOT the gate, which belongs to
        `oxide_region` instead (see module docstring for why: DevSim's
        CreateOxideContact ties a contact's equation to the region it
        is actually registered on, confirmed by reading its source —
        see CLAUDE.md's gate_stack/MOSFET C-V investigation for the
        directly-measured consequence of getting this backwards).
    """
    module = backend.require_devsim()
    from devsim.python_packages.simple_physics import (
        CreateOxideContact,
        CreateOxidePotentialOnly,
        CreateSiliconOxideInterface,
        CreateSiliconPotentialOnly,
        CreateSiliconPotentialOnlyContact,
        SetOxideParameters,
        SetSiliconParameters,
    )

    SetSiliconParameters(device, si_region, temperature_k)
    CreateSiliconPotentialOnly(device, si_region)
    for contact in si_contacts:
        module.set_parameter(device=device, name=f"{contact}_bias", value=0.0)
        CreateSiliconPotentialOnlyContact(device, si_region, contact)

    SetOxideParameters(device, oxide_region, temperature_k)
    CreateOxidePotentialOnly(device, oxide_region, "log_damp")
    module.set_parameter(device=device, name=f"{gate_contact}_bias", value=0.0)
    CreateOxideContact(device, oxide_region, gate_contact)

    CreateSiliconOxideInterface(device, interface_name)
