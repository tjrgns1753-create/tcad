"""DevSim device backend.

Consumes only tcad.mesh.interface.ProcessResult (see mesh_import.py) —
never imports viennaps or any process backend directly.

Public API:
    from tcad.device.devsim import is_available, require_devsim
    from tcad.device.devsim.mesh_import import import_process_result, ImportedDevice
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.device.devsim.resistor_equation import (
        setup_ohmic_equation, set_bias, solve_dc, read_terminal_currents,
    )
    from tcad.device.devsim.semiconductor_equation import (
        setup_semiconductor_potential_equation,
        setup_drift_diffusion_equation,
        read_drift_diffusion_terminal_currents,
    )
    from tcad.device.devsim.mos_equation import setup_mos_potential_equation
"""

from tcad.device.devsim.backend import is_available, require_devsim

__all__ = ["is_available", "require_devsim"]
