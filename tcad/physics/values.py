#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Physics value types.

Two axes, deliberately not merged into one enum:

  Resolution  — how settled a resolution is
  Provenance  — where the number came from

They are orthogonal because LITERATURE + UNVERIFIED (a cited constant used outside its measured
conditions) cannot be expressed on a single enum, so status and origin
are kept orthogonal. Conditions are windows, not points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional


class Resolution(Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED_BY_MODEL = "UNSUPPORTED_BY_MODEL"


class Provenance(Enum):
    LITERATURE = "LITERATURE"
    BACKEND_DEFAULT = "BACKEND_DEFAULT"
    USER_SUPPLIED = "USER_SUPPLIED"
    DERIVED = "DERIVED"


class UnknownPolicy(Enum):
    """What is passed to the backend when no value exists.

    Every option is itself a physical claim — INERT asserts the material
    does not react — so whichever applies, the result still carries
    UNKNOWN and records which policy was used. Which policy each
    parameter uses is declared in the table, never chosen at call time.
    """

    OMIT = "OMIT"
    BACKEND_DEFAULT = "BACKEND_DEFAULT"
    INERT = "INERT"


class Coverage(Enum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    UNSTATED = "UNSTATED"


@dataclass(frozen=True)
class Range:
    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class Conditions:
    """The window a value was measured in.

    A single number is not an absolute material property: the same
    chemistry gives different rates at different pressure, power,
    temperature and gas ratio. A value used outside its window is
    downgraded to UNVERIFIED for that use.
    """

    temperature_c: Optional[Range] = None
    pressure_pa: Optional[Range] = None
    rf_power_w: Optional[Range] = None
    gas_ratio: Optional[Mapping[str, Range]] = None
    notes: str = ""

    _SCALARS = ("temperature_c", "pressure_pa", "rf_power_w")

    def covers(self, requested: Mapping[str, float]) -> Coverage:
        """INSIDE only if every constrained condition is satisfied.

        A source that states no conditions at all yields UNSTATED and is
        never promoted to INSIDE — "we do not know where this applies"
        is not the same as "it applies everywhere".
        """
        constrained = [name for name in self._SCALARS
                       if getattr(self, name) is not None]
        if not constrained and not self.gas_ratio:
            return Coverage.UNSTATED

        for name in constrained:
            if name in requested and not getattr(self, name).contains(requested[name]):
                return Coverage.OUTSIDE

        for gas, window in (self.gas_ratio or {}).items():
            key = f"gas_ratio.{gas}"
            if key in requested and not window.contains(requested[key]):
                return Coverage.OUTSIDE

        return Coverage.INSIDE


@dataclass(frozen=True)
class Source:
    reference: str
    kind: Provenance


@dataclass(frozen=True)
class PhysicalValue:
    value: Optional[float]        # None means UNKNOWN
    unit: str
    material: str
    chemistry: Optional[str]
    conditions: Conditions
    source: Optional[Source]
    resolution: Resolution
    provenance: Provenance


def combine(resolutions: Iterable[Resolution]) -> Resolution:
    """Fold many lookups into one status for the step.

    UNDER_RESOLVED is deliberately absent: it is a numerical warning
    from WaferState, travels on its own axis, and is never merged here.
    """
    items = list(resolutions)
    if not items:
        return Resolution.UNKNOWN
    if Resolution.UNSUPPORTED_BY_MODEL in items:
        return Resolution.UNSUPPORTED_BY_MODEL
    if all(r is Resolution.UNKNOWN for r in items):
        return Resolution.UNKNOWN
    if Resolution.UNVERIFIED in items or Resolution.PARTIAL in items:
        return Resolution.UNVERIFIED
    if Resolution.UNKNOWN in items:
        return Resolution.PARTIAL
    return Resolution.VERIFIED
