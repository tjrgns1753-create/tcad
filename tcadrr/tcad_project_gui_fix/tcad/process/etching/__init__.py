"""Etching category — importing this package registers all built-in
etch models with tcad.process.registry.

Bosch DRIE is one implementation among several here, not the default
or the center of the design (see bosch_drie.py).
"""

from tcad.process.etching import (
    bosch_drie,
    cf4_o2,
    directional,
    faraday_cage,
    fluorocarbon,
    hbr_o2,
    ion_beam,
    isotropic,
    sf6_c4f8,
    sf6o2,
    wet_etching,
)

__all__ = [
    "bosch_drie",
    "sf6o2",
    "hbr_o2",
    "sf6_c4f8",
    "cf4_o2",
    "fluorocarbon",
    "ion_beam",
    "faraday_cage",
    "wet_etching",
    "isotropic",
    "directional",
]
