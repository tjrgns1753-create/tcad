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

"uniform", "step_junction", "gaussian_implant", and "implant_windows"
are implemented. gaussian_implant's equation ("exp"/"^" confirmed
supported by DevSim's own equation parser:
devsim/python_packages/simple_physics.py uses both, e.g.
`"n_i*exp(Potential/V_t)"`, `"NetDoping^2"`) sets NetDoping directly to
a Gaussian, the same way "uniform" sets it directly to a constant — no
separate Donors/Acceptors split, since a Gaussian implant isn't a
donor/acceptor pair the way a step junction is:

    devsim.node_model(device=, region=, name="NetDoping",
        equation=f"{peak}*exp(-(({axis}-({position}))^2)/(2*({straggle})^2))")

implant_windows sets NetDoping to a background constant plus zero or
more `step()*step()` window terms SUMMED on top — real DevSim
`step(x)*step(-x)`-style windowing (the same `step()` function
diode_common.py uses for the step junction above), confirmed by direct
execution reading get_node_model_values() back and comparing to an
independently-computed value per node (0.000e+00 max error across all
nodes — see test_implant_windows_doping_real.py):

    devsim.node_model(device=, region=, name="NetDoping",
        equation=(
            f"{background}"
            f" + {conc_1}*step({axis}-({min_1}))*step(({max_1})-{axis})"
            f" + {conc_2}*step({axis}-({min_2}))*step(({max_2})-{axis})"
            " + ..."
        ))
"""

from __future__ import annotations

from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile


def apply_doping(
    device: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    window_scale: float = 1.0,
) -> None:
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

    window_scale : multiplies every implant WINDOW's concentration (not
        the background), for "implant_windows" only. Default 1.0 leaves
        every existing caller byte-identical. Its purpose is
        doping-level CONTINUATION: re-registering NetDoping at a
        sequence of increasing scales, re-solving at each, lets the
        equilibrium solve reach a heavily-doped target it cannot reach
        in one step — see
        tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium,
        which is the only intended caller. Real-execution-verified: the
        GUI's own default 10x8um implant_windows device fails outright
        ("Convergence failure!", RelError rising) when NetDoping is set
        to its full 1e20 cm^-3 in one step, and converges reliably when
        ramped 1e17 -> 1e20 in five steps on the identical mesh.

    "uniform", "step_junction", "gaussian_implant", and
    "implant_windows" are implemented; any other DopingProfile.kind
    raises, so a future profile type can't be silently mishandled here.
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
    elif doping.kind == "implant_windows":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            background = region_doping.net_doping_cm3 or 0.0
            terms = [str(background)]
            for window in region_doping.implant_windows or []:
                lo_native = window["min_um"] * length_scale_to_cm
                hi_native = window["max_um"] * length_scale_to_cm
                terms.append(
                    f"{window['conc_cm3'] * window_scale}*step({axis}-({lo_native}))"
                    f"*step(({hi_native})-{axis})"
                )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=" + ".join(terms),
            )
    else:
        raise NotImplementedError(
            f"doping_mapping.apply_doping supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant', "
            f"'implant_windows') so far, got {doping.kind!r}"
        )
