#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
implant_windows_from_mask_spans() — pure-geometry unit checks, no
ViennaPS/DevSim needed.

Guards the complement arithmetic that ties implant windows to the real
mask geometry (dopant lands where the mask is NOT), including the edge
cases a hand-written span list actually hits: unsorted input,
overlapping spans, spans touching the domain edge, an empty mask, and a
fully-covered domain.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.doping import implant_windows_from_mask_spans

CONC = 1e20
X = 6.0          # domain spans [-3, +3]
HALF = X / 2.0


def spans_of(windows):
    return [(round(w["min_um"], 9), round(w["max_um"], 9)) for w in windows]


def check(label, mask_spans, expected):
    got = spans_of(implant_windows_from_mask_spans(mask_spans, X, CONC))
    assert got == expected, f"{label}: expected {expected}, got {got}"
    for w in implant_windows_from_mask_spans(mask_spans, X, CONC):
        assert w["conc_cm3"] == CONC, f"{label}: concentration not carried through"
    print(f"  OK  {label}: mask {mask_spans} -> windows {got}")


def main():
    # The MOSFET S/D case: one central opaque gate span leaves exactly
    # two implant windows, one per side.
    check("central gate span", [[-0.8, 0.8]],
          [(-HALF, -0.8), (0.8, HALF)])

    # The MakeTrench-equivalent case: mask everywhere except a window
    # leaves exactly that one window.
    check("MakeTrench equivalent", [[-HALF, -0.8], [0.8, HALF]],
          [(-0.8, 0.8)])

    # Unsorted and overlapping input must be merged, not trusted as-is.
    check("unsorted + overlapping", [[0.8, 2.0], [-0.8, 1.0]],
          [(-HALF, -0.8), (2.0, HALF)])

    # Reversed pair (max first) is normalised.
    check("reversed pair", [[0.8, -0.8]],
          [(-HALF, -0.8), (0.8, HALF)])

    # Degenerate ends.
    check("no mask at all", [], [(-HALF, HALF)])
    check("mask covers everything", [[-HALF, HALF]], [])

    # Two separate gates -> three windows.
    check("two gates", [[-2.0, -1.0], [1.0, 2.0]],
          [(-HALF, -2.0), (-1.0, 1.0), (2.0, HALF)])

    print()
    print("ALL implant_windows_from_mask_spans CHECKS PASSED")


if __name__ == "__main__":
    main()
