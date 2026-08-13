"""Oxidation category — importing this package registers all built-in
oxidation models with tcad.process.registry.

Only one model file (thermal.py) at this stage: ViennaPS's
vps.Oxidation.setMaskMaterial() itself documents that it "activates
LOCOS physics", so fin-style (no mask) and LOCOS-style (mask present)
oxidation are both the same ProcessStep, distinguished by whether the
recipe supplies `mask_material` — not separate classes.
"""

from tcad.process.oxidation import thermal

__all__ = ["thermal"]
