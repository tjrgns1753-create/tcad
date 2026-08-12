"""Etching category — importing this package registers all built-in
etch models with tcad.process.registry.

Bosch DRIE is one implementation among several here, not the default
or the center of the design (see bosch_drie.py).
"""

from tcad.process.etching import (
    bosch_drie,
    directional,
    fluorocarbon,
    ion_beam,
    isotropic,
    sf6o2,
    wet_etching,
)

__all__ = [
    "bosch_drie",
    "sf6o2",
    "fluorocarbon",
    "ion_beam",
    "wet_etching",
    "isotropic",
    "directional",
]
