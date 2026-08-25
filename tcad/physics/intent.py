#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the user asked for — a request, not a result.

Deliberately carries no per-material rates. A user says "SF6/O2 for
30 s", not "SiO2 at 0.02 um/s"; turning the first into the second is the
resolver's job and depends on what is actually on the wafer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

#: Recipe keys that describe geometry or bookkeeping rather than the
#: physical request.
_NON_PHYSICAL_KEYS = frozenset({
    "_process_category", "_process_model_key", "chemistry", "material",
    "material_rates", "mask_spans_um", "remask_spans_um", "mask_left_um",
    "mask_right_um",
})


@dataclass(frozen=True)
class ProcessIntent:
    category: str
    method: str
    chemistry: Optional[str] = None
    target_material: Optional[str] = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


def intent_from(recipe: Mapping[str, Any]) -> ProcessIntent:
    return ProcessIntent(
        category=recipe.get("_process_category", ""),
        method=recipe.get("_process_model_key", ""),
        chemistry=recipe.get("chemistry"),
        target_material=recipe.get("material"),
        parameters={k: v for k, v in recipe.items()
                    if k not in _NON_PHYSICAL_KEYS},
    )
