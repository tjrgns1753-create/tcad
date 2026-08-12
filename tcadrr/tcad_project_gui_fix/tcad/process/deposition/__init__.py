"""Deposition category — importing this package registers all built-in
deposition models with tcad.process.registry.
"""

from tcad.process.deposition import (
    directional,
    isotropic,
    selective_epitaxy,
    single_particle_cvd,
    teos,
    teos_pecvd,
)

__all__ = [
    "teos",
    "teos_pecvd",
    "selective_epitaxy",
    "single_particle_cvd",
    "directional",
    "isotropic",
]
