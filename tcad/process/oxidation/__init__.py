"""Oxidation category — importing this package registers all built-in
oxidation models with tcad.process.registry.

Two independent models, selectable the same way any two etch or
deposition models are:

    ("oxidation", "thermal")  -- Thermal Oxidation, CORE. Plain
        fin-style oxidation of whatever Si is exposed; no mask, no
        mask/oxide mechanics. Always available, unaffected by anything
        below.
    ("oxidation", "locos")    -- LOCOS, ADVANCED / OPTIONAL. A
        selective-oxidation recipe built on the SAME vps.Oxidation()
        engine, using its real mask/oxide elastic-contact mechanics
        (vps.Oxidation.setMaskMaterial()'s own docstring: "activates
        LOCOS physics"). Not required for the core process flow.

Until 2026-09-08 these were one ProcessStep (thermal.py alone),
dispatched on whether the recipe carried `mask_material`. They are now
separate classes/files/registry entries so LOCOS-only geometry, mask,
and mask/oxide-mechanics code can never be reached by selecting Thermal
Oxidation, and vice versa — see thermal.py's and locos.py's own module
docstrings.
"""

from tcad.process.oxidation import locos, thermal

__all__ = ["thermal", "locos"]
