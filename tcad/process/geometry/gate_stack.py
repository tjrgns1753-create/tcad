#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gate-stack geometry: Si body, a gate oxide + electrode confined to a
channel window, and separate source/drain pads -- the geometry rung the
MOSFET ladder was still missing after mask_spans_um (arbitrary masks),
implant_windows (S/D-over-channel doping), and the confirmed-working
contact_sides API (see CLAUDE.md, "Gate-over-channel + separate
source/drain contacts — VERIFIED").

Why this is its OWN category ("geometry"), not another
ProcessStep.prepare_domain() branch like mask_spans_um: mask_spans_um
still fits prepare_domain()'s contract because a caller then runs a REAL
physical process (an etch/deposition/oxidation with a real rate/time) on
top of it, exactly like the MakeTrench path it replaces. A gate stack
has no such single physical process to run -- it IS the finished
geometry (oxide + electrode + pads are all deposited/patterned layers a
real fab builds in separate steps this project does not simulate
individually). So this model, like deposition/geometric_trench.py's
"geometric processes typically have zero duration" precedent, has no
Process() call at all: it builds the 5-material stack via
session.make_gate_stack() and exports directly.

TERMINAL GEOMETRY -- DO NOT CHAIN A FURTHER PROCESS STEP ONTO IT.
Verified directly (not assumed; see session.make_gate_stack's own
docstring for the full ordering investigation): only the gate electrode
level set is wrapped (the one insertion order that exports correctly).
This means Si, the source pad, the drain pad, and the gate oxide do NOT
satisfy ViennaLS Advect's containment precondition -- chaining ANY
further vps.Process() call (whether via another ProcessStep or a
tcad.process.flow.FlowStep) destroys all four (confirmed: their level
sets collapse to 0 points) and the next export does not even produce a
readable mesh file, with NO warning (save_volume_mesh's own missing-
-material safety net silently gives up when meshio can't read the file
at all -- confirmed directly, not assumed). This is why __init__ refuses
inherited_domain outright: there is no sensible way to CONTINUE a flow
INTO this geometry either (it always builds its own fresh 5-material
stack from scratch, the same restriction prepare_domain() already
documents for MakeTrench). Downstream (chaining something AFTER this
step) cannot be prevented at the Python level for a caller who reaches
into `last_domain` directly -- this docstring and CLAUDE.md are the
guard for that side.

No mask/lithography step precedes this in the recipe -- unlike
prepare_domain()'s MakeTrench/mask_spans_um paths, there is no
`pr_thickness_um`/mask-height convention to reuse, since a MOSFET gate
stack's oxide/electrode thicknesses are independent physical layers with
their own values, not a photoresist height.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import SnapshotRecorder, save_locos_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register

DEFAULT_SILICON_DEPTH_UM = 1.0


@register
class GateStack(ProcessStep):
    category = "geometry"
    name = "gate_stack"
    display_name = "MOSFET Gate Stack (Si + gate oxide + electrode + S/D pads)"

    def __init__(self, inherited_domain: Any = None):
        if inherited_domain is not None:
            raise NotImplementedError(
                "GateStack always builds its own fresh 5-material geometry from "
                "scratch -- there is no sensible way to continue an inherited "
                "domain into a gate stack (mirrors the same restriction "
                "ProcessStep.prepare_domain() already documents for MakeTrench)."
            )
        super().__init__(inherited_domain=None)

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        silicon_depth_um = recipe.get("silicon_depth_um", DEFAULT_SILICON_DEPTH_UM)

        geometry, materials, wrap_flags, actual_dims = session.make_gate_stack(
            grid_delta_um=recipe["grid_delta_um"],
            x_extent_um=recipe["x_extent_um"],
            y_extent_um=recipe["y_extent_um"],
            channel_um=tuple(recipe["channel_um"]),
            source_um=tuple(recipe["source_um"]),
            drain_um=tuple(recipe["drain_um"]),
            gate_oxide_thickness_um=recipe["gate_oxide_thickness_um"],
            gate_height_um=recipe["gate_height_um"],
            pad_height_um=recipe["pad_height_um"],
            silicon_depth_um=silicon_depth_um,
            gate_material=recipe.get("gate_material", "TiN"),
            source_material=recipe.get("source_material", "W"),
            drain_material=recipe.get("drain_material", "Cu"),
            oxide_material=recipe.get("oxide_material", "SiO2"),
        )
        self.last_domain = geometry

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_gate_stack")

        dedupe_materials = None
        if recipe.get("dedupe_materials"):
            # See save_locos_volume_mesh's own docstring for why this
            # is opt-in, not automatic: deduplicating EVERY touching
            # material pair crashes DevSim's create_device() for this
            # geometry's own source/drain-pad topology (a native,
            # uncatchable assert, not root-caused at the C++ level).
            # Only pass the material NAMES a caller explicitly names
            # here (e.g. ["Si", "SiO2"] to enable a Si-SiO2 DevSim
            # interface) -- default (key absent) is byte-for-byte the
            # same export every existing caller already gets.
            module = session.require_viennaps()
            dedupe_materials = [
                getattr(module.Material, name) for name in recipe["dedupe_materials"]
            ]

        final_mesh = Path(output_dir) / "gate_stack_final"
        final_mesh_path = save_locos_volume_mesh(
            geometry, materials, wrap_flags, final_mesh,
            floor_depth_um=silicon_depth_um,
            dedupe_materials=dedupe_materials,
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
            # ACTUAL applied dimensions (post export-safety floor -- see
            # session.make_gate_stack()'s own docstring): a caller doing
            # any physics reference computation from this geometry (e.g.
            # ideal C_ox = eps_ox*eps_0*width/t_ox for a C-V sanity
            # check) must use these, not the recipe's requested values,
            # since grid_delta_um can silently floor a thin requested
            # layer to 1.5x itself. Equal to the requested recipe values
            # whenever nothing needed flooring.
            "actual_gate_oxide_thickness_um": actual_dims["gate_oxide_thickness_um"],
            "actual_gate_height_um": actual_dims["gate_height_um"],
            "actual_pad_height_um": actual_dims["pad_height_um"],
        }
