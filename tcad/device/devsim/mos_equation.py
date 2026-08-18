#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MOS capacitor equation setup: doping-aware silicon Poisson-only in the
substrate, dielectric-only Poisson in the oxide, coupled by a
continuous-potential interface — the same equation set (not doping,
not drift-diffusion) as the PN junction's equilibrium step in Phase 8,
extended to a second (oxide) region and a real region-region interface.

Real API used (verified against installed DevSim 2.10.1 by reading
devsim_data/examples/mobility/gmsh_mos2d.py — an official MOSFET
example that sets up exactly this gate/oxide/bulk equation combination
— via inspect.getsource, not guessed):

    from devsim.python_packages.simple_physics import (
        SetSiliconParameters, CreateSiliconPotentialOnly,
        CreateSiliconPotentialOnlyContact,
        SetOxideParameters, CreateOxidePotentialOnly, CreateOxideContact,
        CreateSiliconOxideInterface,
    )
    SetSiliconParameters(device, si_region, T)
    CreateSiliconPotentialOnly(device, si_region)
    CreateSiliconPotentialOnlyContact(device, si_region, substrate_contact)

    SetOxideParameters(device, oxide_region, T)
    CreateOxidePotentialOnly(device, oxide_region, "log_damp")  # gmsh_mos2d.py's
                                                                  # own update_type,
                                                                  # not "default"
    CreateOxideContact(device, oxide_region, gate_contact)

    CreateSiliconOxideInterface(device, interface_name)

CreateOxideContact (read via inspect.getsource) registers
"contactcharge_edge" as the gate contact's edge_charge_model — that is
what makes devsim.get_contact_charge(device=, contact=gate,
equation="PotentialEquation") return a real, non-zero gate charge for
C-V extraction (tcad/characterization/cv_sweep.py).
"""

from __future__ import annotations

from tcad.device.devsim import backend


def setup_mos_potential_equation(
    device: str,
    si_region: str,
    oxide_region: str,
    gate_contact: str,
    substrate_contact: str,
    interface_name: str,
    temperature_k: float = 300.0,
) -> None:
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
    module.set_parameter(device=device, name=f"{substrate_contact}_bias", value=0.0)
    CreateSiliconPotentialOnlyContact(device, si_region, substrate_contact)

    SetOxideParameters(device, oxide_region, temperature_k)
    CreateOxidePotentialOnly(device, oxide_region, "log_damp")
    module.set_parameter(device=device, name=f"{gate_contact}_bias", value=0.0)
    CreateOxideContact(device, oxide_region, gate_contact)

    CreateSiliconOxideInterface(device, interface_name)
