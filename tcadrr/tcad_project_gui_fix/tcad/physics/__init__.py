"""Doping and device physics setup — separate from tcad/process/.

doping.py builds a DopingProfile (backend-independent) attached to a
ProcessResult. It never imports devsim; tcad/device/devsim/
doping_mapping.py is what turns that into real DevSim node models.

Public API:
    from tcad.physics.doping import apply_uniform_doping, apply_step_junction_doping
"""

from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping

__all__ = ["apply_uniform_doping", "apply_step_junction_doping"]
