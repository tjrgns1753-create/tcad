"""Process category modules (Etching / Deposition / Oxidation).

Public API:
    from tcad.process.base import ProcessStep
    from tcad.process import registry
    registry.list_categories() -> ["deposition", "etching", "oxidation"]
    registry.list_models("etching") -> 7 model names
    registry.get(category, name) -> ProcessStep subclass

Importing tcad.process itself does NOT register any models (keeps
`import tcad.process` cheap and side-effect-free). Import the category
subpackage you need to register its models:
    import tcad.process.etching      # registers 7 models
    import tcad.process.deposition   # registers 5 models
    import tcad.process.oxidation    # registers 1 model
"""

from tcad.process.base import ProcessStep
from tcad.process import registry

__all__ = ["ProcessStep", "registry"]
