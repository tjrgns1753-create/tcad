#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn "what the user asked for" plus "what the wafer is" into a recipe.

PURE. Stateless. Does not touch the domain, does not run a process, does
not write files.

There is NO history parameter, and that is the design's central
guarantee: order cannot influence the result because no channel exists
to carry it. Two different orders may still produce different results —
often they must — but only because the wafer state differs when the
second process runs, never because anything here asked what ran before.

Physical decisions read `state.exposed_materials()`, never
`state.materials`: a fully etched layer keeps a zero-thickness level set
and stays declared, and computing physics for it would be computing for
material that is no longer there. `state.materials` is for backend model
registration, where an unregistered material makes the model fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from tcad.physics.intent import ProcessIntent
from tcad.physics.tables import interaction, policy_for
from tcad.physics.values import (
    Provenance, Resolution, UnknownPolicy, combine,
)

#: Which coefficient each category needs per exposed material.
_PARAMETER_FOR_CATEGORY = {
    "etching": "etch_rate",
    "deposition": "deposition_rate",
}


@dataclass(frozen=True)
class ResolvedValue:
    parameter: str
    material: str
    value: Optional[float]
    resolution: Resolution
    provenance: Provenance
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "material": self.material,
            "value": self.value,
            "resolution": self.resolution.value,
            "provenance": self.provenance.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class ResolvedRecipe:
    backend_kwargs: Mapping[str, Any] = field(default_factory=dict)
    resolution: Resolution = Resolution.UNKNOWN
    entries: Tuple[ResolvedValue, ...] = ()
    under_resolved_x: Tuple[float, ...] = ()
    notes: Tuple[str, ...] = ()

    def as_status_dict(self) -> dict:
        return {
            "resolution": self.resolution.value,
            "entries": [e.as_dict() for e in self.entries],
            "notes": list(self.notes),
        }

    def as_numerical_dict(self) -> dict:
        return {"under_resolved_x": list(self.under_resolved_x)}


def resolve(intent: ProcessIntent, state: Any,
            user_supplied: Optional[Mapping[str, Any]] = None) -> ResolvedRecipe:
    parameter = _PARAMETER_FOR_CATEGORY.get(intent.category)
    if parameter is None:
        # Nothing to resolve for this category yet. Not a refusal: the
        # step runs on whatever the recipe already carries.
        return ResolvedRecipe(
            resolution=Resolution.UNKNOWN,
            under_resolved_x=tuple(state.under_resolved_x()),
            notes=(f"no resolver mapping for category {intent.category!r}",),
        )

    supplied_rates = dict((user_supplied or {}).get("material_rates") or {})
    rates: dict = {}
    entries = []

    for material in sorted(state.exposed_materials()):
        if material in supplied_rates:
            rates[material] = supplied_rates[material]
            entries.append(ResolvedValue(
                parameter=parameter, material=material,
                value=supplied_rates[material],
                resolution=Resolution.UNVERIFIED,
                provenance=Provenance.USER_SUPPLIED,
                note="supplied by the caller; not verified by this project",
            ))
            continue

        found = interaction(material, intent.chemistry or "", parameter,
                            intent.parameters)
        if found.value is None:
            policy = policy_for(parameter)
            if policy is UnknownPolicy.INERT:
                rates[material] = 0.0
            entries.append(ResolvedValue(
                parameter=parameter, material=material, value=None,
                resolution=Resolution.UNKNOWN, provenance=found.provenance,
                note=f"no verified constant; policy {policy.value}",
            ))
            continue

        rates[material] = found.value
        entries.append(ResolvedValue(
            parameter=parameter, material=material, value=found.value,
            resolution=found.resolution, provenance=found.provenance,
            note=found.source.reference if found.source else "",
        ))

    backend_kwargs = {"materialRates": rates} if rates else {}
    return ResolvedRecipe(
        backend_kwargs=backend_kwargs,
        resolution=combine(e.resolution for e in entries),
        entries=tuple(entries),
        under_resolved_x=tuple(state.under_resolved_x()),
    )
