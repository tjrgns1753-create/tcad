"""Canonical Process -> Device handoff.

interface.py defines ProcessResult (backend-independent).
viennaps_adapter.py builds one from a ViennaPS ProcessStep result.
Device backends (tcad/device/devsim/, and future others) consume only
ProcessResult, never viennaps directly.

Public API:
    from tcad.mesh.interface import ProcessResult, MaterialRegion, DopingProfile, DopingRegion
    from tcad.mesh.viennaps_adapter import build_process_result
"""

from tcad.mesh.interface import DopingProfile, DopingRegion, MaterialRegion, ProcessResult
from tcad.mesh.viennaps_adapter import build_process_result

__all__ = [
    "ProcessResult",
    "MaterialRegion",
    "DopingProfile",
    "DopingRegion",
    "build_process_result",
]
