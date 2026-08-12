#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Map a ProcessResult's DopingProfile onto DevSim's NetDoping node model.

Real API used (verified against installed DevSim 2.10.1 — same
node_model() used elsewhere in this project, confirmed here specifically
for a constant-expression doping value by running it and reading back
get_node_model_values(), and cross-checked physically: the resulting
device solve's built-in potential matched the analytic
V_t*ln(NetDoping/n_i) prediction for both signs of doping — see
tests/test_phase7_doping_real.py):

    devsim.node_model(device=, region=, name="NetDoping", equation=str(value))

Real API used (verified against installed DevSim 2.10.1 — confirmed
here specifically for both a constant-expression doping value and a
step-junction doping value, by running each and reading back
get_node_model_values(), and cross-checked physically: the resulting
equilibrium solve's potential spread matched the analytic
V_t*ln(Nd*Na/n_i^2) built-in potential for a step junction to full
floating-point precision — see tests/test_phase8_pn_junction_real.py):

    devsim.node_model(device=, region=, name="NetDoping", equation=str(value))
    # step junction (real DevSim built-in step() function, found by
    # reading devsim_data/examples/diode/diode_common.py's own
    # SetNetDoping(), not guessed):
    devsim.node_model(device=, region=, name="Donors",
                       equation=f"{donor}*step(x-({junction_position}))")
    devsim.node_model(device=, region=, name="Acceptors",
                       equation=f"{acceptor}*step(({junction_position})-x)")
    devsim.node_model(device=, region=, name="NetDoping",
                       equation="Donors-Acceptors")

"uniform", "step_junction", and "gaussian_implant" are implemented.
gaussian_implant's equation ("exp"/"^" confirmed supported by DevSim's
own equation parser: devsim/python_packages/simple_physics.py uses both,
e.g. `"n_i*exp(Potential/V_t)"`, `"NetDoping^2"`) sets NetDoping directly
to a Gaussian, the same way "uniform" sets it directly to a constant —
no separate Donors/Acceptors split, since a Gaussian implant isn't a
donor/acceptor pair the way a step junction is:

    devsim.node_model(device=, region=, name="NetDoping",
        equation=f"{peak}*exp(-(({axis}-({position}))^2)/(2*({straggle})^2))")
"""

from __future__ import annotations

from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile


def apply_doping(device: str, doping: DopingProfile, length_scale_to_cm: float = 1.0) -> None:
    """Register NetDoping (and, for step junctions, Donors/Acceptors)
    node models for every region named in `doping`.

    length_scale_to_cm : must match whatever
        tcad.device.devsim.mesh_import.import_process_result's
        length_scale_to_cm was for this device, so junction_position_um
        (given in the same "um" units as ProcessResult, see
        tcad/mesh/interface.py) converts into the same coordinate scale
        DevSim's own "x"/"y"/"z" node models use. Irrelevant for
        "uniform" doping, which has no position dependence. Default 1.0
        matches the default (and every Phase 7 caller's) import scale.

    "uniform", "step_junction", and "gaussian_implant" are implemented;
    any other DopingProfile.kind raises, so a future profile type can't
    be silently mishandled here.
    """
    module = backend.require_devsim()

    if doping.kind == "uniform":
        for region_doping in doping.regions:
            module.node_model(
                device=device,
                region=region_doping.region,
                name="NetDoping",
                equation=str(region_doping.net_doping_cm3),
            )
    elif doping.kind == "step_junction":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.junction_position_um * length_scale_to_cm
            module.node_model(
                device=device, region=region_doping.region, name="Donors",
                equation=f"{region_doping.donor_conc_cm3}*step({axis}-({position_native}))",
            )
            module.node_model(
                device=device, region=region_doping.region, name="Acceptors",
                equation=f"{region_doping.acceptor_conc_cm3}*step(({position_native})-{axis})",
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation="Donors-Acceptors",
            )
    elif doping.kind == "gaussian_implant":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.peak_position_um * length_scale_to_cm
            straggle_native = region_doping.straggle_um * length_scale_to_cm
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=(
                    f"{region_doping.peak_conc_cm3}*exp(-(({axis}-({position_native}))^2)"
                    f"/(2*({straggle_native})^2))"
                ),
            )
    else:
        raise NotImplementedError(
            f"doping_mapping.apply_doping supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant') so far, got {doping.kind!r}"
        )
