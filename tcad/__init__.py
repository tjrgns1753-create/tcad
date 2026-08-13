"""tcad — open-source TCAD pipeline.

    Process (ViennaPS: Etching/Deposition/Oxidation)
      -> Mesh/Structure (ProcessResult)
        -> Doping (tcad.physics)
          -> DevSim device (regions/contacts/interfaces)
            -> Characterization (I-V, PN-junction I-V, MOS C-V)

This top-level package intentionally stays import-light: it does not
import viennaps or devsim itself, and does not re-export subpackage
contents, so `import tcad` always succeeds even with neither backend
installed (see tcad.backends.viennaps.is_available() /
tcad.device.devsim.is_available()). Import the subpackage you need:

    from tcad.core import Wafer, BoschRecipe
    from tcad.process import registry
    import tcad.process.etching, tcad.process.deposition, tcad.process.oxidation
    from tcad.mesh.interface import ProcessResult, MaterialRegion, DopingProfile
    from tcad.physics.doping import apply_uniform_doping, apply_step_junction_doping
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.characterization.interface import CharacterizationResult

See each subpackage's own __init__.py for its public API, and README.md
for installation and a runnable end-to-end example.
"""

__version__ = "0.9.0"
