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

When a region's DopingRegion instead carries `gaussian_terms` (multiple
independently-added implants on the same region -- see
apply_gaussian_implant_doping's `existing=` parameter, Stage B Task 3),
NetDoping is built the SAME Donors/Acceptors/NetDoping way as
step_junction above, generalized to N Gaussian terms: every
donor-polarity term's own Gaussian expression is summed into Donors,
every acceptor-polarity term's into Acceptors, and NetDoping is
Donors-Acceptors -- so a B implant and a P implant added separately
both stay present in the real solved device, instead of the second
node_model() call silently overwriting the first's NetDoping
registration (confirmed by direct execution:
test_gaussian_implant_terms_devsim_real.py):

    devsim.node_model(device=, region=, name="Donors",
        equation=f"{donor_term_1} + {donor_term_2} + ...")
    devsim.node_model(device=, region=, name="Acceptors",
        equation=f"{acceptor_term_1} + {acceptor_term_2} + ...")
    devsim.node_model(device=, region=, name="NetDoping",
        equation="Donors-Acceptors")

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

from typing import Dict, List, Optional

from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile


def _exclusion_factor_expr(
    exclude_windows: Optional[List[Dict[str, float]]],
    axis: str,
    length_scale_to_cm: float,
) -> str:
    """DevSim equation string: 1 everywhere, 0 inside any exclusion
    window. Windows are assumed non-overlapping (derive_barrier_covered_
    windows() only ever emits merged, disjoint windows), so summing
    each window's step()*step() indicator and subtracting from 1 is
    safe -- same step()-based windowing mechanism implant_windows
    already uses (see this module's own docstring), reused rather than
    inventing a second one.
    """
    if not exclude_windows:
        return "1"
    terms = []
    for w in exclude_windows:
        lo = w["min_um"] * length_scale_to_cm
        hi = w["max_um"] * length_scale_to_cm
        terms.append(f"step({axis}-({lo}))*step(({hi})-{axis})")
    return "(1 - (" + " + ".join(terms) + "))"


def apply_doping(
    device: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    window_scale: float = 1.0,
    exclude_windows: Optional[List[Dict[str, float]]] = None,
    exclude_axis: str = "x",
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

    exclude_windows : optional list of {"min_um": float, "max_um": float}
        dicts marking x-ranges where doping should be excluded (zeroed by
        multiplication with a step()-based exclusion factor). Used to
        block doping under barrier materials like SiO2. When None (default),
        no exclusion is applied and behavior is byte-identical to all
        existing callers. See derive_barrier_covered_windows() in
        tcad.device.devsim.mesh_import for how to derive these windows.

    exclude_axis : coordinate axis ("x", "y", or "z") along which to apply
        the exclusion windows. Default "x". Ignored when exclude_windows
        is None.

    "uniform", "step_junction", "gaussian_implant", and
    "implant_windows" are implemented; any other DopingProfile.kind
    raises, so a future profile type can't be silently mishandled here.
    """
    module = backend.require_devsim()
    exclusion = _exclusion_factor_expr(exclude_windows, exclude_axis, length_scale_to_cm)

    if doping.kind == "uniform":
        for region_doping in doping.regions:
            module.node_model(
                device=device,
                region=region_doping.region,
                name="NetDoping",
                equation=f"({region_doping.net_doping_cm3})*{exclusion}",
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
                equation=f"(Donors-Acceptors)*{exclusion}",
            )
    elif doping.kind == "gaussian_implant":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            exclusion_for_region = exclusion
            if region_doping.gaussian_terms:
                donor_terms = []
                acceptor_terms = []
                for term in region_doping.gaussian_terms:
                    position_native = term["peak_position_um"] * length_scale_to_cm
                    straggle_native = term["straggle_um"] * length_scale_to_cm
                    expr = (
                        f"{term['peak_conc_cm3']}*exp(-(({axis}-({position_native}))^2)"
                        f"/(2*({straggle_native})^2))"
                    )
                    if term["polarity"] == "donor":
                        donor_terms.append(expr)
                    else:
                        acceptor_terms.append(expr)
                donors_expr = " + ".join(donor_terms) if donor_terms else "0"
                acceptors_expr = " + ".join(acceptor_terms) if acceptor_terms else "0"
                module.node_model(
                    device=device, region=region_doping.region, name="Donors",
                    equation=f"({donors_expr})",
                )
                module.node_model(
                    device=device, region=region_doping.region, name="Acceptors",
                    equation=f"({acceptors_expr})",
                )
                module.node_model(
                    device=device, region=region_doping.region, name="NetDoping",
                    equation=f"(Donors-Acceptors)*{exclusion_for_region}",
                )
                continue

            position_native = region_doping.peak_position_um * length_scale_to_cm
            straggle_native = region_doping.straggle_um * length_scale_to_cm
            gaussian_expr = (
                f"{region_doping.peak_conc_cm3}*exp(-(({axis}-({position_native}))^2)"
                f"/(2*({straggle_native})^2))"
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({gaussian_expr})*{exclusion_for_region}",
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
            windows_expr = " + ".join(terms)
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({windows_expr})*{exclusion}",
            )
    else:
        raise NotImplementedError(
            f"doping_mapping.apply_doping supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant', "
            f"'implant_windows') so far, got {doping.kind!r}"
        )
