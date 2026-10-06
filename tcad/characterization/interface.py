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
from typing import Any, Dict, List, Optional

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


def current_unit_metadata(dimension: Optional[int]) -> Dict[str, Any]:
    """Machine-readable unit of the terminal currents of a DevSim device of the given spatial `dimension`
    (`devsim.get_dimension(device=...)`). Only the 2D case is established (Batch 7H-E6I measured I = sigma (H / L) DeltaV
    with H, L in cm, i.e. the current per cm of out-of-plane depth): `A/cm`, normalisation `per_out_of_plane_depth`. Any other
    dimension is NOT verified, so its unit is None -- never silently assumed to be A. No depth is supplied or assumed here."""
    if dimension == 2:
        return {"current_unit": "A/cm", "current_normalization": "per_out_of_plane_depth", "device_dimension": 2,
                "current_convention": CURRENT_CONVENTION_NOTE}   # the 2D-specific note is attached to 2D results only
    return {"current_unit": None, "current_normalization": None, "device_dimension": dimension}


def established_current_unit(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    """The unit string a result's metadata established, or None (no metadata, None, empty / blank): the single place every
    consumer (GUI text, CSV header, plot axis) asks, so none of them can fall back to an assumed A."""
    unit = (metadata or {}).get("current_unit")
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def format_current(value: float, metadata: Optional[Dict[str, Any]], spec: str = ".6e") -> str:
    """`value` (unchanged) with the unit its result's metadata established, e.g. '1.600000e-04 A/cm'; a result with no
    established unit is shown as '<value> (unit not established)', never as plain A."""
    unit = established_current_unit(metadata)
    return f"{value:{spec}} {unit}" if unit else f"{value:{spec}} (unit not established)"


def current_unit_note(metadata: Optional[Dict[str, Any]]) -> str:
    """One sentence for the user when the current is per unit out-of-plane depth (2D device); '' otherwise."""
    if (metadata or {}).get("current_normalization") == "per_out_of_plane_depth":
        return ("Current per unit out-of-plane depth (A/cm) -- not the total current of a device; "
                "multiply by the real device depth in cm for a total current.")
    return ""


@dataclass
class BiasPoint:
    """One point in a sweep: the applied voltage on every contact, and
    the terminal current extracted at every contact, at that bias.

    currents : terminal currents in the unit the owning result's
        metadata["current_unit"] names (None = not established; never
        assume A). For a 2D DevSim device the unit is A/cm, per unit
        out-of-plane depth, not the total current of a real device with
        a specific physical width -- see CURRENT_CONVENTION_NOTE.
    converged : whether this point's own solve succeeded. Always True
        today (every BiasPoint producer in this package raises on a
        non-converging solve rather than recording a failed point --
        see the sweep functions' own docstrings) -- present so a
        future caller/consumer does not need a data-model migration
        if that changes.
    """

    voltages: Dict[str, float]
    currents: Dict[str, float]
    converged: bool = True


def validate_bias_point(point: BiasPoint, required_contacts=()) -> None:
    """Reject invalid terminal evidence, without replacing values or approving physics.

    This is a GUI result-boundary check, not a convergence/charge-conservation
    proof. Negative finite currents and zero are both legitimate values.
    """
    import math
    if point.converged is not True or not point.currents or not point.voltages:
        raise ValueError("Measurement result is empty or not converged; no current is reported.")
    for contact in required_contacts:
        if contact not in point.currents or contact not in point.voltages:
            raise ValueError(f"Measurement result is missing contact {contact!r}.")
    for values in (point.voltages, point.currents):
        if any(not math.isfinite(float(value)) for value in values.values()):
            raise ValueError("Measurement result contains a non-finite value; no current is reported.")


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
