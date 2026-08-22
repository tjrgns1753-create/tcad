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

#: DevSim's own 2D-device convention (not this project's invention): a
#: 2D device has no explicit extent in the third (out-of-plane)
#: dimension, so DevSim implicitly treats it as 1cm deep there. Every
#: current/charge/capacitance value any real (DevSim-backed) sweep in
#: this package produces is therefore PER UNIT DEPTH (effectively "per
#: cm of device width in the unmodeled dimension"), not the total
#: terminal current/charge of a real device with a specific physical
#: width. A caller who wants a real device's actual current must
#: multiply by that device's real depth in cm (e.g. a real 1um-wide
#: device: multiply by 1e-4). Found worth stating explicitly (an audit
#: of this project's own real-TCAD-workflow completeness flagged that
#: this convention, while real DevSim behavior and not a bug, was only
#: ever recorded once in docs/investigation_log.md and nowhere any
#: sweep function's own docstring or output actually said so) — every
#: real sweep function below sets this on its own
#: CharacterizationResult.metadata under the key named in that
#: function's own docstring, so a caller reading `metadata` (not just
#: source comments) can discover the convention programmatically.
CURRENT_CONVENTION_NOTE = (
    "DevSim 2D device convention: every current/charge/capacitance "
    "value in this result is PER UNIT DEPTH in the unmodeled 3rd "
    "dimension (DevSim implicitly assumes 1cm of device depth "
    "out-of-plane for a 2D device) -- NOT the total value of a real "
    "device with a specific physical width. To get a real device's "
    "actual current/charge, multiply by that device's real depth in "
    "cm (e.g. a real 1um-wide device: multiply by 1e-4)."
)


@dataclass
class BiasPoint:
    """One point in a sweep: the applied voltage on every contact, and
    the terminal current extracted at every contact, at that bias.

    currents : PER UNIT DEPTH (DevSim's own 2D-device convention, not
        the total current of a real device with a specific physical
        width) — see this module's CURRENT_CONVENTION_NOTE.
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
