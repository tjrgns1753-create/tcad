#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Material properties and interaction coefficients.

TWO tables, because the values differ in kind. `rho` is a property of a
material; `k_sigma` depends on the chemistry AND the conditions. Merging
them would make condition-dependent coefficients look like material
properties.

INTERACTION_COEFFICIENTS SHIPS EMPTY. Filling it is a separate research
step where each entry arrives with a citation and the conditions it was
measured at. Nothing here may be filled with an estimate, and a ViennaPS
default is never promoted to VERIFIED — it is the library author's
choice, which is not a guarantee for this material at these conditions.

A side effect worth having: with the table empty, the UNKNOWN path is
the most-exercised path rather than a rare branch.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from tcad.physics.values import (
    Conditions, Coverage, PhysicalValue, Provenance, Resolution, Source,
    UnknownPolicy,
)

_NO_CONDITIONS = Conditions(notes="not applicable — intrinsic property")

#: Intrinsic, condition-free. Only entries with an unambiguous basis.
MATERIAL_PROPERTIES: Dict[Tuple[str, str], PhysicalValue] = {
    ("Si", "oxidizable"): PhysicalValue(
        value=1.0, unit="bool", material="Si", chemistry=None,
        conditions=_NO_CONDITIONS,
        source=Source("thermal oxidation forms SiO2 from Si", Provenance.LITERATURE),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
    ("SiO2", "oxidizable"): PhysicalValue(
        value=0.0, unit="bool", material="SiO2", chemistry=None,
        conditions=_NO_CONDITIONS,
        source=Source("SiO2 is the oxide; it is not further oxidised",
                      Provenance.LITERATURE),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
}

#: (material, chemistry, parameter) -> PhysicalValue.
#: EMPTY ON PURPOSE. See the module docstring.
INTERACTION_COEFFICIENTS: Dict[Tuple[str, str, str], PhysicalValue] = {}

#: What is passed to the backend when a value is unknown. Declared per
#: parameter here, never decided at call time. Each option is itself a
#: physical claim, so the result carries UNKNOWN regardless.
_UNKNOWN_POLICIES: Dict[str, UnknownPolicy] = {
    "etch_rate": UnknownPolicy.OMIT,
    "deposition_rate": UnknownPolicy.OMIT,
}
_DEFAULT_POLICY = UnknownPolicy.OMIT


def policy_for(parameter: str) -> UnknownPolicy:
    return _UNKNOWN_POLICIES.get(parameter, _DEFAULT_POLICY)


def material_property(material: str, name: str) -> Optional[PhysicalValue]:
    return MATERIAL_PROPERTIES.get((material, name))


def interaction(material: str, chemistry: str, parameter: str,
                requested: Mapping[str, Any]) -> PhysicalValue:
    """Look up a coefficient, downgrading it if used outside its window.

    A cited value applied outside the conditions it was measured at is
    UNVERIFIED for that use, and a source that states no conditions is
    never promoted to VERIFIED. This is what stops a single number being
    treated as an absolute material property.
    """
    found = INTERACTION_COEFFICIENTS.get((material, chemistry, parameter))
    if found is None:
        return PhysicalValue(
            value=None, unit="", material=material, chemistry=chemistry,
            conditions=_NO_CONDITIONS, source=None,
            resolution=Resolution.UNKNOWN, provenance=Provenance.DERIVED,
        )

    coverage = found.conditions.covers(requested)
    if coverage is Coverage.INSIDE and found.provenance is Provenance.LITERATURE:
        return found
    return PhysicalValue(
        value=found.value, unit=found.unit, material=found.material,
        chemistry=found.chemistry, conditions=found.conditions,
        source=found.source, resolution=Resolution.UNVERIFIED,
        provenance=found.provenance,
    )
