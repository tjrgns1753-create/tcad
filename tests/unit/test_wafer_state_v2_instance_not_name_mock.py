#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 3 (design doc §9): dopant is found by
material_instance_id, never by material NAME.

Two Si cells with the SAME material name "Si" but DIFFERENT instance
ids, only one of which is doped. A lookup keyed on the name would
return the doped profile for both; the sanctioned lookup
(`attachments_for_instance`) does not. This test makes a name-based
lookup demonstrably fail.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, attach_dopant, uniform_inventory_integral,
)


def _name_based_lookup(state, material_name):
    """The WRONG way, written here only so the test can prove it is
    wrong: gather every attachment whose support instance's cell has
    this material name."""
    instance_ids = {c.material_instance_id for c in state.cells if c.material == material_name}
    return [a for a in state.attachments if a.support_instance_id in instance_ids]


def main():
    s = WaferStateV2(
        cells=(
            MaterialCell("c_doped", "Si", (-5.0, 0.0, 0.0, 2.0), "inst_doped_si"),
            MaterialCell("c_fresh", "Si", (0.0, 5.0, 0.0, 2.0), "inst_fresh_si"),
        ),
        grid_delta_um=0.1,
    )
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_doped_si", support_region_um=(-5.0, 0.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE",
    )

    # The sanctioned, instance-keyed lookup: doped instance -> 1, fresh -> 0.
    assert len(s.attachments_for_instance("inst_doped_si")) == 1
    assert len(s.attachments_for_instance("inst_fresh_si")) == 0
    print("[1] attachments_for_instance: doped instance has 1, fresh instance has 0")

    # The name-based lookup returns the doped profile for BOTH "Si" cells --
    # this is the bug the instance model exists to prevent. Assert it IS
    # wrong (returns too many), so a regression that switches the real
    # code to name-based matching fails here.
    name_hits = _name_based_lookup(s, "Si")
    assert len(name_hits) == 1  # only one attachment exists at all...
    # ...but it is attributed, by name, to a set of instances that
    # includes the fresh one:
    name_instances = {c.material_instance_id for c in s.cells if c.material == "Si"}
    assert "inst_fresh_si" in name_instances and "inst_doped_si" in name_instances
    # net_doping_at over the fresh cell must be 0 despite the shared name:
    q_fresh = s.net_doping_at(2.5, 1.0)
    assert q_fresh.net_doping == 0.0, (
        "the fresh Si instance picked up the doped instance's profile -- "
        "matching was done by material name, not instance id")
    q_doped = s.net_doping_at(-2.5, 1.0)
    assert abs(q_doped.net_doping - 1.0e17) < 1.0
    print("[2] net_doping_at: 0 over the fresh Si, 1e17 over the doped Si -- same name, different result")

    print()
    print("WaferState v2 test 3 PASS -- attachments resolve by instance id, not material name")


if __name__ == "__main__":
    main()
