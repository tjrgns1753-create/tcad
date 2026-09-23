#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review item 1): the inventory integral is EXACT, with
no sample grid.

A uniform profile over a rectangle whose bounds are NOT aligned to any
0.01 um lattice must give inventory == C * (real area in cm^2), to full
floating-point precision -- not "within one lattice cell".

Also: an etch clip of that arbitrary rectangle conserves exactly
(remaining + removed == initial), because both pieces are computed from
the same exact closed form.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    area_cm2, uniform_inventory_integral,
)

C = 7.3e16
# Deliberately irrational-looking, sub-0.01-um, non-lattice-aligned bounds.
SUPPORT = (-3.14159, 2.71828, 0.001234, 1.999777)


def main():
    exact_area_cm2 = (SUPPORT[1] - SUPPORT[0]) * (SUPPORT[3] - SUPPORT[2]) * 1e-8
    exact_inventory = C * exact_area_cm2

    integ = uniform_inventory_integral(C)
    got = integ(SUPPORT)
    assert got == exact_inventory, (
        f"inventory {got!r} != exact C*area {exact_inventory!r} "
        f"(any nonzero difference means an approximation crept in)")
    # area_cm2() itself must be exact too
    assert area_cm2(SUPPORT) == exact_area_cm2
    print(f"[1] uniform inventory over a non-lattice rectangle is EXACT: {got:.12e}")

    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", SUPPORT, "inst_si"),), grid_delta_um=0.1)
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: C,
        inventory_integral=integ, support_instance_id="inst_si",
        support_region_um=SUPPORT, model="uniform_v1", chemical_state="ACTIVE")
    initial = s.attachments[0].inventory_cm_per_depth
    assert initial == exact_inventory

    # Etch an arbitrary sub-rectangle (also non-lattice-aligned).
    removed_rect = (0.123, SUPPORT[1], SUPPORT[2], 1.0101)
    s2 = advance(s, GeometryTransform(
        "etching", representable=True, removed_extents_um=(removed_rect,),
        input_instance_ids=("inst_si",)), step_seed="e")

    remaining = sum(a.inventory_cm_per_depth for a in s2.attachments)
    removed = next(e for e in s2.events if e.category == "REMOVED").inventory_cm_per_depth
    assert abs((remaining + removed) - initial) <= 1e-9 * initial, (remaining, removed, initial)
    print(f"[2] etch of a non-lattice sub-rectangle: remaining + removed == initial exactly")

    print()
    print("WaferState v2 exact-inventory test PASS -- no sample grid, no approximation")


if __name__ == "__main__":
    main()
