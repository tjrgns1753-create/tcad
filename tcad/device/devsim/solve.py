#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimal device solve skeleton — a charge-free (no doping) potential
equation, i.e. Laplace's equation div(grad Potential) = 0, solved with
simple Dirichlet contacts.

This is intentionally NOT a real semiconductor device solve: no
NetDoping, no carrier continuity equations, no mobility model. DevSim's
own official Poisson helper (devsim.python_packages.simple_physics.
CreateSiliconPotentialOnly) was checked and requires a "NetDoping" node
model — since doping is explicitly out of scope until a later phase,
that helper is not used here. This module exists to prove the
Process -> ProcessResult -> DevSim device -> solve() pipeline actually
runs end-to-end on real ViennaPS-generated geometry; the real device
physics (doping, drift-diffusion) is future work.

Real API used (verified against installed DevSim 2.10.1). The
derivative-model naming convention below ("{model}:{variable}@n0" for
edges, a plain "1" for a linear contact residual) is not invented —
it is DevSim's own convention, found by reading the source of
devsim.python_packages.model_create.CreateEdgeModelDerivatives /
CreateNodeModelDerivative (used by DevSim's bundled diode examples,
which were run and confirmed working in this environment first, to
isolate a real equation-setup mistake from an environment problem):

    from devsim.python_packages.model_create import (
        CreateSolution, CreateEdgeModel, CreateEdgeModelDerivatives,
    )
    CreateSolution(device, region, "Potential")
    CreateEdgeModel(device, region, "PotentialEdgeFlux",
                     "(Potential@n0-Potential@n1)*EdgeCouple")
    CreateEdgeModelDerivatives(device, region, "PotentialEdgeFlux",
                                "(Potential@n0-Potential@n1)*EdgeCouple",
                                "Potential")
    devsim.equation(device=, region=, name=, variable_name="Potential",
                     edge_model="PotentialEdgeFlux")
    # per Dirichlet contact:
    devsim.contact_node_model(device=, contact=, name=f"{c}_bc",
                               equation=f"Potential-{bias}")
    devsim.contact_node_model(device=, contact=, name=f"{c}_bc:Potential",
                               equation="1")
    devsim.contact_equation(device=, contact=, name=, node_model=f"{c}_bc")
    devsim.solve(type="dc", solver_type="direct", ...)

Skipping CreateEdgeModelDerivatives (i.e. omitting the bulk equation's
Jacobian contribution) was tried and reproducibly fails with a DevSim
"UMFPACK ... required argument(s) missing" error even in DevSim's own
minimal 1D example — that is what led to finding this convention.
"""

from __future__ import annotations

from typing import Any, Dict

from tcad.device.devsim import backend


def run_basic_potential_solve(
    device: str,
    region: str,
    contact_bias: Dict[str, float],
) -> Dict[str, Any]:
    """Solve div(grad Potential) = 0 on `region` with Dirichlet contacts.

    contact_bias : {contact_name: bias_volts}. Every contact named here
        must already exist on `device` (e.g. from
        tcad.device.devsim.mesh_import.import_process_result's
        contact_regions option) and be attached to `region`.
    """
    module = backend.require_devsim()
    from devsim.python_packages.model_create import (
        CreateEdgeModel,
        CreateEdgeModelDerivatives,
        CreateSolution,
    )

    CreateSolution(device, region, "Potential")
    CreateEdgeModel(device, region, "PotentialEdgeFlux", "(Potential@n0-Potential@n1)*EdgeCouple")
    CreateEdgeModelDerivatives(
        device, region, "PotentialEdgeFlux",
        "(Potential@n0-Potential@n1)*EdgeCouple", "Potential",
    )
    module.equation(
        device=device,
        region=region,
        name="PotentialEquation",
        variable_name="Potential",
        edge_model="PotentialEdgeFlux",
    )

    for contact, bias in contact_bias.items():
        module.contact_node_model(
            device=device, contact=contact, name=f"{contact}_bc",
            equation=f"Potential-{bias}",
        )
        module.contact_node_model(
            device=device, contact=contact, name=f"{contact}_bc:Potential",
            equation="1",
        )
        module.contact_equation(
            device=device, contact=contact, name="PotentialEquation",
            node_model=f"{contact}_bc",
        )

    module.solve(
        type="dc",
        solver_type="direct",
        absolute_error=1.0e-10,
        relative_error=1.0e-10,
        maximum_iterations=30,
    )

    values = module.get_node_model_values(device=device, region=region, name="Potential")
    return {
        "num_nodes": len(values),
        "potential_min": min(values),
        "potential_max": max(values),
    }
