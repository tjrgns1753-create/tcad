#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Adapter: ViennaPS ProcessStep result dict -> canonical ProcessResult.

This is the only place that knows both "ViennaPS" and "ProcessResult" —
tcad/device/devsim/ never imports viennaps, and tcad/process/ never
imports devsim. Everything crosses through the ProcessResult this
module builds.

Real, verified facts this module relies on (found by inspecting an
actual ViennaPS-generated volume mesh with meshio, not guessed):
  - The .vtu volume mesh saved by tcad.backends.viennaps.io.save_volume_mesh
    carries a per-triangle cell_data array named "Material" whose
    integer values match vps.Material's own enum values exactly
    (confirmed: Mask=0, Si=10 in a real run).
  - `vps.Material(value)` reverse-looks-up the enum; its repr is
    "Material('Name')", so `str(...).split("'")[1]` extracts the plain
    name (vps.Material has no `.name` attribute, unlike a standard
    Python enum — confirmed by direct inspection).
"""

from __future__ import annotations

from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.mesh.interface import MaterialRegion, ProcessResult


def _material_name(module: Any, tag: int) -> str:
    """Real Material enum name for an integer tag, e.g. 10 -> "Si"."""
    return str(module.Material(int(tag))).split("'")[1]


def build_process_result(
    step_result: Dict[str, Any],
    domain_state_path: Any = None,
    structure: Any = None,
) -> ProcessResult:
    """Build a ProcessResult from a ProcessStep.run() return value.

    step_result is the raw dict any tcad.process.base.ProcessStep.run()
    returns (at least {"final_mesh": ..., "snapshots": [...]}).

    domain_state_path / structure are supplied only by the process-flow
    layer (tcad.process.flow) so a following step can continue from
    this one; both default to None, which is exactly what every
    single-step Phase 1-12 caller gets.
    """
    module = session.require_viennaps()

    try:
        import meshio
    except ImportError as exc:
        raise RuntimeError(
            "meshio is required to inspect process-generated meshes.\n"
            "Install it first:\n"
            "python -m pip install meshio"
        ) from exc

    mesh_path = step_result["final_mesh"]
    mesh = meshio.read(mesh_path)

    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise ValueError(f"No triangle cells found in mesh: {mesh_path}")

    block_index = mesh.cells.index(triangle_block)
    material_field = "Material"
    if material_field not in mesh.cell_data:
        raise ValueError(
            f"Mesh {mesh_path} has no '{material_field}' cell_data array "
            f"(found: {list(mesh.cell_data.keys())})"
        )
    tags = mesh.cell_data[material_field][block_index]

    unique_tags = sorted(set(int(t) for t in tags))
    material_regions = [
        MaterialRegion(name=_material_name(module, tag), tag=tag)
        for tag in unique_tags
    ]

    return ProcessResult(
        volume_mesh_path=mesh_path,
        material_field=material_field,
        material_regions=material_regions,
        doping=None,
        units="um",
        metadata={"snapshots": step_result.get("snapshots", [])},
        domain_state_path=domain_state_path,
        structure=structure,
    )
