#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pin — a user-placed LOGICAL electrode position, backend-independent
(mirrors tcad/mesh/interface.py's own Process/Device separation: this
module has no viennaps, meshio, or devsim import).

A Pin is where the user says an electrode goes; it becomes a real
DevSim Contact only after tcad.device.devsim.contact_probe validates
it against the actual mesh and tcad.device.devsim.mesh_import.
import_process_result() imports it. See that module's own docstring
for why the two are kept separate rather than merged into one object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Pin:
    """One user-placed electrode.

    name : unique label the user gave this pin (e.g. "Drain"). Used as
        the resulting DevSim contact's name once resolved.
    role : free-form electrical role (e.g. "Source"/"Drain"/"Gate"/
        "Body"), for GUI display and physical-invariant checks (e.g.
        "which pins carry DC current" — a Gate normally does not).
        Not read by contact_probe.py itself, which only cares about
        WHERE the pin is.
    x_um / y_um : WAFER coordinates (0..width_um / 0..y_extent_um),
        the same coordinate system Wafer.mask_left_um/mask_right_um
        already use. Converted to domain-centered coordinates only at
        the point of mesh lookup (see contact_probe.py) — never
        pre-converted here, so a Pin's own fields always read the same
        as what the user typed into the GUI.
    target_region : optional hint for which MaterialRegion.name this
        pin is expected to land on (e.g. "Si", "TiN") — purely
        informational; contact_probe.py determines the ACTUAL region
        from the real mesh regardless of this hint, and flags a
        mismatch rather than trusting it blindly.
    """

    name: str
    role: str
    x_um: float
    y_um: float
    target_region: Optional[str] = None
