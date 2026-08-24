#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Physics value types: two orthogonal axes, condition windows, combination."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.values import (
    Conditions, Coverage, Provenance, Range, Resolution, combine,
)


def main():
    # --- condition windows -------------------------------------------
    window = Conditions(temperature_c=Range(20.0, 60.0), pressure_pa=None,
                        rf_power_w=None, gas_ratio=None, notes="")
    assert window.covers({"temperature_c": 40.0}) is Coverage.INSIDE
    assert window.covers({"temperature_c": 90.0}) is Coverage.OUTSIDE
    assert window.covers({"pressure_pa": 5.0}) is Coverage.INSIDE, (
        "a condition the window does not constrain must not read as OUTSIDE")

    unstated = Conditions(None, None, None, None, notes="source states no conditions")
    assert unstated.covers({"temperature_c": 40.0}) is Coverage.UNSTATED, (
        "a source with no stated conditions can never be confirmed INSIDE")

    # --- combination rule --------------------------------------------
    assert combine([Resolution.VERIFIED, Resolution.VERIFIED]) is Resolution.VERIFIED
    assert combine([Resolution.VERIFIED, Resolution.UNVERIFIED]) is Resolution.UNVERIFIED
    assert combine([Resolution.VERIFIED, Resolution.UNKNOWN]) is Resolution.PARTIAL
    assert combine([Resolution.UNKNOWN, Resolution.UNKNOWN]) is Resolution.UNKNOWN
    assert combine([]) is Resolution.UNKNOWN
    assert combine([Resolution.VERIFIED, Resolution.UNSUPPORTED_BY_MODEL]) \
        is Resolution.UNSUPPORTED_BY_MODEL, (
        "a material the model cannot represent dominates: the user's fix is "
        "different from supplying a missing constant")

    # --- the axes are orthogonal -------------------------------------
    assert not hasattr(Resolution, "LITERATURE")
    assert not hasattr(Provenance, "VERIFIED")

    print("PHYSICS VALUE TYPES OK")
    print("  condition windows: INSIDE / OUTSIDE / UNSTATED")
    print("  combination: VERIFIED / UNVERIFIED / PARTIAL / UNKNOWN / UNSUPPORTED")
    print("  Resolution and Provenance are separate axes")


if __name__ == "__main__":
    main()
