#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit test for tcad.process.base.mask_spans_from_openings() -- pure
geometry, no backend needed.

A photomask is described by where it is OPEN, but `mask_spans_um` takes
the OPAQUE regions, and the two live in different coordinate systems
(GUI 0..width vs. domain centred on 0). Both halves of that conversion
are easy to get subtly wrong, so they are pinned here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.process.base import mask_spans_from_openings


def close(a, b, tol=1e-9):
    return len(a) == len(b) and all(
        abs(x0 - y0) < tol and abs(x1 - y1) < tol
        for (x0, x1), (y0, y1) in zip(a, b)
    )


def main():
    # One centred opening on a 10um wafer: mask is opaque on both sides.
    got = mask_spans_from_openings([(3.5, 6.5)], 10.0)
    assert close(got, [(-5.0, -1.5), (1.5, 5.0)]), got
    print(f"[1/6] single centred opening -> {got}")

    # Two openings (the case the GUI could not express before): three
    # opaque spans, and the gap between the openings stays masked.
    got = mask_spans_from_openings([(1.0, 2.0), (8.0, 9.0)], 10.0)
    assert close(got, [(-5.0, -4.0), (-3.0, 3.0), (4.0, 5.0)]), got
    print(f"[2/6] two openings -> {got}")

    # An opening touching the left edge produces no span there.
    got = mask_spans_from_openings([(0.0, 2.0)], 10.0)
    assert close(got, [(-3.0, 5.0)]), got
    print(f"[3/6] opening at the wafer edge -> {got}")

    # Unsorted and overlapping input is merged, not duplicated.
    got = mask_spans_from_openings([(8.0, 9.0), (1.0, 3.0), (2.0, 4.0)], 10.0)
    assert close(got, [(-5.0, -4.0), (-1.0, 3.0), (4.0, 5.0)]), got
    print(f"[4/6] overlapping/unsorted openings merged -> {got}")

    # No openings at all -> fully opaque mask (one span, whole wafer).
    got = mask_spans_from_openings([], 10.0)
    assert close(got, [(-5.0, 5.0)]), got
    print(f"[5/6] no openings -> fully opaque {got}")

    # Opening covering everything -> no mask at all.
    got = mask_spans_from_openings([(0.0, 10.0)], 10.0)
    assert got == [], got
    print(f"[6/6] full-width opening -> no mask {got}")

    print()
    print("mask_spans_from_openings VERIFIED")


if __name__ == "__main__":
    main()
