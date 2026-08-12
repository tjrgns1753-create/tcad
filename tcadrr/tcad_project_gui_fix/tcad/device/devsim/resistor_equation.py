#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Device/contact/solution state exposure design (read this before
iv_sweep.py):

DevSim itself has no "device object" to hand back to a caller — every
piece of state (regions, contacts, node/edge models, solved values)
lives inside DevSim's own global C++ state, addressed only by
string names (device=, region=, contact=, name=...). tcad.device.devsim
exposes that state to the rest of the project the same way DevSim
itself does — as plain strings and floats, never a devsim object:

  - a device/contact "handle" is just the string names returned by
    mesh_import.ImportedDevice (device, region list, contact list) —
    already the case since Phase 5.
  - "set a bias" is set_bias(device, contact, voltage) -> None.
  - "read solved state" is read_terminal_currents(device, contacts)
    -> Dict[str, float] — plain floats, not a devsim handle.

This means tcad/characterization/iv_sweep.py (and any future
consumer) only ever exchanges strings/dicts/floats with this module —
never a devsim.Device, node model object, or anything else that would
tie characterization code to DevSim's internal representation. Only
this module and mesh_import.py import devsim directly.

Physics scope: doping is not implemented yet (see
tcad/mesh/interface.py's DopingProfile), so there is no carrier
transport equation available. What is implemented here is a plain
Ohmic (linear resistor) equation: J = sigma * E, i.e. current
proportional to the potential gradient with a constant, user-supplied
conductivity — enough to drive a real bias sweep and extract a real
terminal I-V curve without doping. A doping-aware drift-diffusion
equation is future work once doping is implemented.

Real API used (verified against installed DevSim 2.10.1 by reading
devsim_data/examples/capacitance/cap2d.py — the officially bundled
example for exactly this "electrostatic contact equation +
get_contact_<quantity>" pattern — and adapting its `edge_charge_model`
current pattern into `edge_current_model`, then confirming a real bias
sweep on a real ViennaPS-imported mesh produces the physically
expected result: current linear in voltage, equal and opposite at the
two contacts):

    devsim.node_solution(device=, region=, name="Potential")
    devsim.edge_from_node_model(device=, region=, node_model="Potential")
    devsim.edge_model(device=, region=, name="ElectricField",
                       equation="(Potential@n0-Potential@n1)*EdgeInverseLength")
    devsim.edge_model(device=, region=, name="ElectricField:Potential@n0",
                       equation="EdgeInverseLength")
    devsim.edge_model(device=, region=, name="ElectricField:Potential@n1",
                       equation="-EdgeInverseLength")
    devsim.set_parameter(device=, region=, name="Conductivity", value=...)
    devsim.edge_model(device=, region=, name="CurrentFlow",
                       equation="Conductivity*ElectricField")
    devsim.edge_model(device=, region=, name="CurrentFlow:Potential@n0",
                       equation="diff(Conductivity*ElectricField, Potential@n0)")
    devsim.edge_model(device=, region=, name="CurrentFlow:Potential@n1",
                       equation="-CurrentFlow:Potential@n0")
    devsim.equation(device=, region=, name="PotentialEquation",
                     variable_name="Potential", edge_model="CurrentFlow")
    # per contact:
    devsim.contact_node_model(device=, contact=, name=f"{c}_bc",
                               equation=f"Potential-{c}_bias")
    devsim.contact_node_model(device=, contact=, name=f"{c}_bc:Potential",
                               equation="1")
    devsim.contact_equation(device=, contact=, name="PotentialEquation",
                             node_model=f"{c}_bc", edge_current_model="CurrentFlow")
    devsim.set_parameter(device=, name=f"{c}_bias", value=...)
    devsim.solve(type="dc", solver_type="direct", ...)
    devsim.get_contact_current(device=, contact=, equation="PotentialEquation")
"""

from __future__ import annotations

from typing import Dict, List

from tcad.device.devsim import backend


def setup_ohmic_equation(
    device: str,
    region: str,
    contacts: List[str],
    conductivity: float = 1.0,
) -> None:
    """Register the Potential/current equation and per-contact Dirichlet
    conditions on `region`. Call once before any bias_and_solve().
    """
    module = backend.require_devsim()

    module.node_solution(device=device, region=region, name="Potential")
    module.edge_from_node_model(device=device, region=region, node_model="Potential")

    module.edge_model(
        device=device, region=region, name="ElectricField",
        equation="(Potential@n0-Potential@n1)*EdgeInverseLength",
    )
    module.edge_model(
        device=device, region=region, name="ElectricField:Potential@n0",
        equation="EdgeInverseLength",
    )
    module.edge_model(
        device=device, region=region, name="ElectricField:Potential@n1",
        equation="-EdgeInverseLength",
    )

    module.set_parameter(device=device, region=region, name="Conductivity", value=conductivity)
    module.edge_model(
        device=device, region=region, name="CurrentFlow",
        equation="Conductivity*ElectricField",
    )
    module.edge_model(
        device=device, region=region, name="CurrentFlow:Potential@n0",
        equation="diff(Conductivity*ElectricField, Potential@n0)",
    )
    module.edge_model(
        device=device, region=region, name="CurrentFlow:Potential@n1",
        equation="-CurrentFlow:Potential@n0",
    )

    module.equation(
        device=device, region=region, name="PotentialEquation",
        variable_name="Potential", edge_model="CurrentFlow", variable_update="default",
    )

    for contact in contacts:
        module.contact_node_model(
            device=device, contact=contact, name=f"{contact}_bc",
            equation=f"Potential-{contact}_bias",
        )
        module.contact_node_model(
            device=device, contact=contact, name=f"{contact}_bc:Potential",
            equation="1",
        )
        module.contact_equation(
            device=device, contact=contact, name="PotentialEquation",
            node_model=f"{contact}_bc", edge_current_model="CurrentFlow",
        )
        module.set_parameter(device=device, name=f"{contact}_bias", value=0.0)


def set_bias(device: str, contact: str, voltage: float) -> None:
    """Set one contact's applied voltage (does not solve)."""
    module = backend.require_devsim()
    module.set_parameter(device=device, name=f"{contact}_bias", value=voltage)


def solve_dc() -> None:
    """Run one DC Newton solve on whatever equations are registered."""
    module = backend.require_devsim()
    module.solve(
        type="dc", solver_type="direct",
        absolute_error=1.0e-10, relative_error=1.0e-10, maximum_iterations=30,
    )


def read_terminal_currents(device: str, contacts: List[str]) -> Dict[str, float]:
    """Read the solved terminal current at each contact.

    Returns plain floats keyed by contact name — never a devsim handle.
    """
    module = backend.require_devsim()
    return {
        contact: module.get_contact_current(device=device, contact=contact, equation="PotentialEquation")
        for contact in contacts
    }
