#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CAD-style validation for a (start, stop, step) sweep specification --
pure Python, no backend import, checked BEFORE any real solve is
attempted (matching this project's own established pattern of
rejecting an invalid recipe early rather than letting a real ViennaPS/
DevSim call fail confusingly deep inside a sweep).
"""

from __future__ import annotations

from typing import List


class SweepRangeError(ValueError):
    """Raised by validate_sweep_range for a (start, stop, step) triple
    that can never produce a real sweep."""


def validate_sweep_range(start: float, stop: float, step: float) -> None:
    """Raises SweepRangeError if this (start, stop, step) can never
    reach `stop` from `start` -- step == 0 (would never move), or a
    positive step with start > stop (moves the wrong direction), or a
    negative step with start < stop (same, other direction)."""
    if step == 0.0:
        raise SweepRangeError(f"step must be nonzero (got start={start}, stop={stop}, step=0.0)")
    if step > 0.0 and start > stop:
        raise SweepRangeError(
            f"start ({start}) > stop ({stop}) with a positive step ({step}) -- "
            f"this sweep would never reach stop"
        )
    if step < 0.0 and start < stop:
        raise SweepRangeError(
            f"start ({start}) < stop ({stop}) with a negative step ({step}) -- "
            f"this sweep would never reach stop"
        )


def sweep_point_count(start: float, stop: float, step: float) -> int:
    """Number of points an (start, stop, step) sweep produces,
    INCLUSIVE of both endpoints -- floor((stop-start)/step) + 1,
    matching every sweep_voltages/gate_voltages list this project's
    own callers already build by hand (e.g.
    tests/integration/test_mosfet_id_vgs_real.py's own
    [0.0, 2.0, 4.0, 6.0, 8.0] is exactly this formula for
    start=0, stop=8, step=2). Calls validate_sweep_range() first."""
    validate_sweep_range(start, stop, step)
    import math
    return int(math.floor((stop - start) / step + 1e-9)) + 1


def build_sweep_values(start: float, stop: float, step: float) -> List[float]:
    """The actual [start, start+step, ..., stop] list a sweep function
    consumes, length == sweep_point_count(start, stop, step)."""
    n = sweep_point_count(start, stop, step)
    return [start + i * step for i in range(n)]
