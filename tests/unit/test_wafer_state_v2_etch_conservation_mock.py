#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 1 (design doc §9): etch conserves dopant inventory.

A uniformly-doped Si rectangle is partly etched via an explicit,
representable GeometryTransform. Asserts:
  - remaining + removed == initial inventory (exactly, design doc §6A)
  - removed inventory == C * removed_area_cm2
  - remaining inventory == C * remaining_area_cm2
  - doping whose support lies OUTSIDE the removed extent is untouched

No backend. Hand-built WaferStateV2 / GeometryTransform.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant, area_cm2,
    uniform_inventory_integral,
)

C = 1.0e17  # cm^-3, uniform donor


def _doped_si():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),),
        grid_delta_um=0.1,
    )
    return attach_dopant(
        s, species="P", polarity="donor",
        concentration_at=lambda x, y, v=C: v,
        inventory_integral=uniform_inventory_integral(C),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE",
    )


def main():
    s = _doped_si()
    initial = s.attachments[0].inventory_cm_per_depth
    expected_initial = C * area_cm2((-5.0, 5.0, 0.0, 2.0))
    assert abs(initial - expected_initial) < 1e-3 * expected_initial, (initial, expected_initial)
    print(f"[1] initial inventory {initial:.6e} cm^-1 (== C*area {expected_initial:.6e})")

    # Etch the right half: x in [0, 5], full y.
    removed_rect = (0.0, 5.0, 0.0, 2.0)
    t = GeometryTransform("etching", representable=True, removed_extents_um=(removed_rect,),
                      input_instance_ids=("inst_si",))
    s2 = advance(s, t, step_seed="etch1")

    remaining = sum(a.inventory_cm_per_depth for a in s2.attachments)
    etch_event = next(e for e in s2.events if e.category == "REMOVED")
    removed = etch_event.inventory_cm_per_depth

    assert abs((remaining + removed) - initial) <= 1e-6 * initial, (
        f"NOT conserved: remaining {remaining} + removed {removed} != initial {initial}")
    print(f"[2] remaining {remaining:.6e} + removed {removed:.6e} == initial (conserved)")

    exp_removed = C * area_cm2(removed_rect)
    exp_remaining = C * area_cm2((-5.0, 0.0, 0.0, 2.0))
    assert abs(removed - exp_removed) < 1e-3 * exp_removed, (removed, exp_removed)
    assert abs(remaining - exp_remaining) < 1e-3 * exp_remaining, (remaining, exp_remaining)
    print(f"[3] removed == C*removed_area; remaining == C*remaining_area")

    # The surviving attachment's support is exactly the surviving rectangle.
    assert len(s2.attachments) == 1
    assert s2.attachments[0].support_region_um == (-5.0, 0.0, 0.0, 2.0)
    # same instance id -- an etch does not create a new material instance
    assert s2.attachments[0].support_instance_id == "inst_si"
    assert s2.active_cells()[0].material_instance_id == "inst_si"
    print("[4] surviving support clipped to the surviving rectangle; instance id unchanged")

    # Doping whose support is entirely outside the removed extent survives untouched.
    s_out = attach_dopant(
        _doped_si(), species="B", polarity="acceptor",
        concentration_at=lambda x, y: 5.0e16,
        inventory_integral=uniform_inventory_integral(5.0e16),
        support_instance_id="inst_si", support_region_um=(-5.0, -4.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE",
    )
    b_initial = next(a for a in s_out.attachments if a.species == "B").inventory_cm_per_depth
    s_out2 = advance(s_out, t, step_seed="etch2")
    b_after = [a for a in s_out2.attachments if a.species == "B"]
    assert len(b_after) == 1
    assert b_after[0].support_region_um == (-5.0, -4.0, 0.0, 2.0)
    assert abs(b_after[0].inventory_cm_per_depth - b_initial) < 1e-9 * b_initial
    assert not any(u.origin_attachment_id == b_after[0].attachment_id
                   for u in s_out2.unresolved_inventory)
    print("[5] doping outside the removed extent: untouched, no ledger entry")

    print()
    print("WaferState v2 test 1 PASS -- etch conserves dopant inventory")


if __name__ == "__main__":
    main()
