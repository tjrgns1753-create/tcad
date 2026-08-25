#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The physics tables ship empty, and say so honestly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.intent import ProcessIntent, intent_from
from tcad.physics.tables import interaction, material_property, policy_for
from tcad.physics.values import Provenance, Resolution, UnknownPolicy


def main():
    # --- intent carries no per-material rates ------------------------
    intent = intent_from({
        "_process_category": "etching", "_process_model_key": "isotropic",
        "chemistry": "SF6O2", "rate": -0.2, "etch_time_s": 1.0,
    })
    assert isinstance(intent, ProcessIntent)
    assert intent.category == "etching"
    assert intent.method == "isotropic"
    assert intent.chemistry == "SF6O2"
    assert "material_rates" not in intent.parameters, (
        "ProcessIntent must not carry per-material rates — those are the "
        "resolver's job, derived from the wafer state")

    # --- geometry/bookkeeping keys must not leak into .parameters -----
    geometry_intent = intent_from({
        "_process_category": "etching", "_process_model_key": "isotropic",
        "chemistry": "SF6O2", "rate": -0.2, "etch_time_s": 1.0,
        "grid_delta_um": 0.05, "x_extent_um": 10.0, "y_extent_um": 8.0,
        "silicon_depth_um": 5.0, "pr_thickness_um": 1.0,
    })
    leaked = {"grid_delta_um", "x_extent_um", "y_extent_um",
              "silicon_depth_um", "pr_thickness_um"} & set(
                  geometry_intent.parameters)
    assert not leaked, (
        f"geometry/bookkeeping keys leaked into ProcessIntent.parameters: "
        f"{leaked}")

    # --- unknown combinations stay unknown ---------------------------
    value = interaction("W", "SF6O2", "etch_rate", {"temperature_c": 25.0})
    assert value.value is None, "no constant may be invented for an unknown pair"
    assert value.resolution is Resolution.UNKNOWN
    assert value.source is None

    # --- every parameter declares its policy in advance --------------
    assert isinstance(policy_for("etch_rate"), UnknownPolicy)

    # --- a material property that is genuinely known -----------------
    oxidizable = material_property("Si", "oxidizable")
    assert oxidizable is not None and oxidizable.value == 1.0
    assert oxidizable.provenance is Provenance.LITERATURE

    assert material_property("W", "oxidizable") is None or \
        material_property("W", "oxidizable").resolution is Resolution.UNKNOWN

    print("PHYSICS TABLES OK — empty of interaction constants, honest about it")


if __name__ == "__main__":
    main()
