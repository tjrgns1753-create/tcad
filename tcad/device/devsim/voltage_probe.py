#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Read the real, already-solved Potential field at an arbitrary point --
nearest-NODE lookup (Potential is a per-node field defined everywhere
DevSim's PotentialEquation was registered for a region, unlike a
contact, which only lives on a boundary edge subset -- see
tcad.device.devsim.contact_probe for that, deliberately different,
boundary-only lookup).

Reads only -- never solves. The caller is responsible for having
already run a real DC solve (e.g.
tcad.characterization.pn_junction_iv_sweep.run_pn_junction_iv_sweep)
on `device`/`region` first; this module has no opinion on how that
solve was set up.
"""

from __future__ import annotations

import numpy as np

from tcad.device.devsim import backend


def read_potential_at_point(
    device: str,
    region: str,
    raw_points: "np.ndarray",
    x_domain_um: float,
    y_um: float,
    length_scale_to_cm: float,
    tolerance_um: float = 0.5,
) -> float:
    """Nearest mesh node's real Potential value (volts) to
    (x_domain_um, y_um) -- domain-centered coordinates, same convention
    tcad.device.devsim.contact_probe.validate_pin_placement uses.

    raw_points : the mesh's own points array BEFORE length_scale_to_cm
        was applied (i.e. straight from meshio.read(...).points, in
        the same um units x_domain_um/y_um are given in) -- this
        module does the cm conversion internally when comparing
        against DevSim's own (cm-scale) node "x"/"y" node models, so a
        caller never has to pre-scale its target point.

    Raises ValueError if no node of `region` is within tolerance_um,
    or if `region` has no "Potential" node model registered (i.e. no
    equation using it was ever set up -- checked directly against
    DevSim's own node-model list, not assumed).
    """
    module = backend.require_devsim()

    node_models = module.get_node_model_list(device=device, region=region)
    if "Potential" not in node_models:
        raise ValueError(
            f"region {region!r} on device {device!r} has no 'Potential' node "
            f"model registered -- no equation using it has been solved yet "
            f"(node models present: {sorted(node_models)})"
        )

    xs_cm = np.array(module.get_node_model_values(device=device, region=region, name="x"))
    ys_cm = np.array(module.get_node_model_values(device=device, region=region, name="y"))
    potentials = np.array(module.get_node_model_values(device=device, region=region, name="Potential"))

    target_cm = np.array([x_domain_um, y_um]) * length_scale_to_cm
    node_coords_cm = np.column_stack([xs_cm, ys_cm])
    distances_cm = np.linalg.norm(node_coords_cm - target_cm, axis=1)
    nearest_index = int(np.argmin(distances_cm))
    nearest_distance_um = float(distances_cm[nearest_index]) / length_scale_to_cm

    if nearest_distance_um > tolerance_um:
        raise ValueError(
            f"no node of region {region!r} is within {tolerance_um}um of "
            f"({x_domain_um:.4f}, {y_um:.4f}) um -- nearest node is "
            f"{nearest_distance_um:.4f}um away"
        )

    value = float(potentials[nearest_index])
    if value != value:  # NaN check without importing math for one use
        raise ValueError(
            f"nearest node's own Potential value is NaN -- the solve at "
            f"this point never converged to a real number"
        )
    return value
