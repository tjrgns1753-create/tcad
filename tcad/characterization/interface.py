#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Canonical Characterization result — the boundary between the DevSim
backend (which drives the actual solves) and everything that consumes
characterization data (CSV/JSON writers, plotting, the GUI, future
extraction routines like Vth/subthreshold-slope).

No devsim import here, mirroring tcad/mesh/interface.py's separation
between ProcessResult and the ViennaPS backend. Only
tcad/characterization/iv_sweep.py (and future cv_sweep.py etc.) knows
about devsim; everything downstream only sees these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class BiasPoint:
    """One point in a sweep: the applied voltage on every contact, and
    the terminal current extracted at every contact, at that bias.
    """

    voltages: Dict[str, float]
    currents: Dict[str, float]


@dataclass
class CharacterizationResult:
    """A generic terminal-characteristics sweep result.

    name : short label for the sweep type, e.g. "iv_sweep" today;
        "cv_sweep", "vth_extraction", "subthreshold_slope" are the
        intended future values — this shape (device/region + a list of
        BiasPoint) is meant to already fit those without a redesign,
        though only iv_sweep.py populates it in this phase.
    sweep_contact : which contact's voltage was swept to produce `points`.
    """

    name: str
    device: str
    region: str
    sweep_contact: str
    points: List[BiasPoint] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
