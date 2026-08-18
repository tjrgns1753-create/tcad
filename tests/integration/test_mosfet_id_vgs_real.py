#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOSFET Id-Vgs transfer characteristic — real electron/hole
drift-diffusion under gate control, through the real production entry
points. This is the "실제 전류 흐름 추출" (extract real current flow)
step beyond "First electrically-exercised MOSFET-shaped device"
(test_mosfet_gate_stack_cv_real.py, a gate-only C-V sweep with no
transport at all) — the first sweep in this project that actually
drives source-to-drain current and reads it as a function of gate
voltage.

A REAL geometry bug was found and fixed while building this — not a
solver/tolerance issue. gate_stack's own default recipe (channel_um
narrower than source_um/drain_um, e.g. channel (-0.8,0.8) vs. source/
drain edges at mp1.0) leaves a genuinely UNGATED, undoped-beyond
-background strip between the gate and each junction. Measured directly
(electron-density profile along the channel-to-source transition, real
device, real solve): with a gap, electron density falls from ~1e20
cm^-3 (source) to ~1e3-1e4 cm^-3 (the gap, near-intrinsic) back up to
~1e18 (the inverted channel) — a 10-order-of-magnitude double cliff
that severs the channel from the source/drain electrically, regardless
of how strongly the gate inverts the channel itself (confirmed
separately: the channel DOES invert correctly even with the gap
present — Potential and Electrons at the channel center both respond
correctly to gate voltage either way; the gap breaks the CONNECTION,
not the channel physics). Fixed by making channel_um exactly CONTIGUOUS
with source_um/drain_um (no numeric gap) — confirmed by re-measuring
the same profile: no more cliff, a smooth, physically continuous
density profile from source through channel to drain.

Real ViennaPS 4.6.2 + DevSim 2.10.1 tolerances/ramping strategy notes:
see tcad/characterization/mosfet_sweep.py's own module docstring for
the full account (DevSim's official gmsh_mos2d.py example's exact
drift-diffusion tolerances, and devsim.python_packages.ramp.rampbias
for adaptive bias stepping) — both confirmed necessary by real
execution, not assumed.

Checks:
  1. real production run() -> filter -> graded refinement (source/drain
     junctions AND the Si-SiO2 interface under the gate, both needed —
     see mesh_refine notes below) -> implant_windows doping -> import
     -> apply_doping -> run_mosfet_id_vgs_sweep(), all succeed.
  2. NetDoping matches the requested implant_windows profile exactly.
  3. every gate-voltage point converges (the sweep itself raises on
     non-convergence).
  4. charge conservation: source current ~= -drain current at every
     point (no artificial current sink/source in the device).
  5. real transistor action: drain current at high Vgs is meaningfully
     larger than at Vgs=0 (the channel turning on measurably increases
     current) — NOT a claim that the absolute magnitude matches an
     idealized long-channel square-law estimate, which this project's
     own investigation found does not hold quantitatively for this
     device/mesh (see CLAUDE.md's "What remains uncertain" for why).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.geometry  # noqa: F401 -- registers gate_stack
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import (
    _debye_length_um,
    _estimate_mesh_spacing_um,
    import_process_result,
)
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
# Contiguous channel/junction windows -- no ungated gap (see module
# docstring for the bug this avoids). source_um/drain_um are gate_stack's
# own metal-pad windows (unused electrically here, filtered out below),
# kept identical to the channel's outer edge so the geometry stays
# self-consistent even though only Si/SiO2 are imported.
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17  # p-type channel/body
SD_DOPING_CM3 = 1e20           # n+ source/drain
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4
DRAIN_VOLTAGE = 0.1

RECIPE = {
    "grid_delta_um": GRID,
    "x_extent_um": X_EXTENT,
    "y_extent_um": 3.0,
    "silicon_depth_um": 1.0,
    "channel_um": list(CHANNEL),
    "source_um": list(SRC),
    "drain_um": list(DRN),
    "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15,
    "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def _graded_ring_half_widths(spacing_um, concentration_cm3, ratio=2.5, max_rings=4):
    """Same telescoping-ring formula import_process_result's own
    auto_refine_from_doping uses internally (_derive_refine_from_doping)
    -- duplicated here, not imported, because that function only reads
    step_junction/gaussian_implant positions, not implant_windows (see
    CLAUDE.md's own "what remains uncertain" note on that limitation).
    """
    debye_um = _debye_length_um(concentration_cm3)
    target_edge_um = ratio * debye_um
    rings = []
    half_width = spacing_um
    edge = spacing_um
    while edge > target_edge_um and len(rings) < max_rings:
        rings.append(half_width)
        half_width /= 2.0
        edge /= 2.0
    if not rings:
        rings = [spacing_um]
    return rings


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        print(f"[1/6] gate_stack built via real production run(): {result['final_mesh']}")

        filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])
        print(f"[2/6] filtered to Si+SiO2 only: {filtered}")

        mesh = meshio.read(filtered)
        block = next(c for c in mesh.cells if c.type == "triangle")
        idx = mesh.cells.index(block)
        points, triangles, tags = mesh.points, block.data, mesh.cell_data["Material"][idx]

        spacing_um = _estimate_mesh_spacing_um(points, triangles)
        sd_rings = _graded_ring_half_widths(spacing_um, SD_DOPING_CM3)
        body_rings = _graded_ring_half_widths(spacing_um, abs(BACKGROUND_DOPING_CM3))

        predicates = []
        for junction_x in (SRC[1], DRN[0]):  # lateral: source/drain step junctions
            for hw in sd_rings:
                predicates.append(lambda c, jx=junction_x, hw=hw: abs(c[0] - jx) < hw)
        for hw in body_rings:  # vertical: Si-SiO2 interface under the whole device
            predicates.append(lambda c, hw=hw: abs(c[1]) < hw)

        refined_points, refined_tris, refined_tags = graded_refine_mesh_near(
            points, triangles, tags, predicates
        )
        refined_mesh = meshio.Mesh(
            points=refined_points, cells=[("triangle", refined_tris)],
            cell_data={"Material": [refined_tags]},
        )
        refined_path = f"{filtered}.refined.vtu"
        meshio.write(refined_path, refined_mesh)
        print(f"[3/6] graded refinement: {len(points)} -> {len(refined_points)} points "
              f"({len(sd_rings)} S/D-junction rings x2, {len(body_rings)} interface ring(s))")

        step_result = {"final_mesh": refined_path, "snapshots": result["snapshots"]}
        process_result = build_process_result(step_result)
        process_result = apply_implant_windows_doping(
            process_result, region="Si", axis="x",
            background_doping_cm3=BACKGROUND_DOPING_CM3,
            windows=[
                {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
            ],
        )

        imported = import_process_result(
            process_result, mesh_name="mosfet_iv_mesh", device_name="mosfet_iv_device",
            contact_regions=["Si", "SiO2"], contact_axis="x",
            contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.regions) == {"Si", "SiO2"}, imported.regions
        assert set(imported.contacts) == {"Si_xmin", "Si_xmax", "SiO2_ymax"}, imported.contacts
        assert imported.interfaces == ["Si_SiO2_interface"], imported.interfaces
        print(f"[4/6] imported: contacts={imported.contacts} interfaces={imported.interfaces}")

        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        # Check 2: NetDoping matches the requested implant_windows profile.
        xs = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        net_doping = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
        max_rel_err, checked = 0.0, 0
        for x_cm, doping in zip(xs, net_doping):
            x_um = x_cm / LENGTH_SCALE_TO_CM
            if any(abs(x_um - edge) < GRID for edge in (SRC[0], SRC[1], DRN[0], DRN[1])):
                continue  # skip nodes within one grid cell of a window boundary
            expected = BACKGROUND_DOPING_CM3
            for lo, hi in (SRC, DRN):
                if lo < x_um < hi:
                    expected += SD_DOPING_CM3
            max_rel_err = max(max_rel_err, abs(doping - expected) / abs(expected))
            checked += 1
        assert max_rel_err < 1e-9, f"NetDoping mismatch: max relative error {max_rel_err:.3e}"
        print(f"[5/6] NetDoping matches implant_windows profile exactly ({checked} nodes checked)")

        gate_voltages = [0.0, 2.0, 4.0, 6.0, 8.0]
        result_iv = run_mosfet_id_vgs_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages, drain_voltage=DRAIN_VOLTAGE,
        )
        assert len(result_iv.points) == len(gate_voltages)

        # Check 4: charge conservation (source ~= -drain at every point).
        for pt in result_iv.points:
            i_source = pt.currents["Si_xmin"]
            i_drain = pt.currents["Si_xmax"]
            assert abs(i_source + i_drain) < 0.02 * max(abs(i_source), abs(i_drain)), (
                f"charge not conserved: Is={i_source:.4e} Id={i_drain:.4e}"
            )

        # Check 5: real transistor action -- on-state current exceeds off-state.
        id_off = abs(result_iv.points[0].currents["Si_xmax"])
        id_on = abs(result_iv.points[-1].currents["Si_xmax"])
        assert id_on > 1.2 * id_off, (
            f"drain current did not increase with gate voltage: "
            f"Vgs=0 -> {id_off:.4e}A, Vgs={gate_voltages[-1]} -> {id_on:.4e}A"
        )
        id_series = [pt.currents["Si_xmax"] for pt in result_iv.points]
        print(f"[6/6] Id-Vgs sweep converged at all {len(gate_voltages)} points; "
              f"charge conserved at every point; drain current increases with "
              f"gate voltage ({id_off:.4e}A -> {id_on:.4e}A, "
              f"{id_on / id_off:.2f}x): {[f'{i:.3e}' for i in id_series]}")

    print()
    print("MOSFET Id-Vgs TRANSFER CHARACTERISTIC (real gate-controlled "
          "source-to-drain current) VERIFIED against real ViennaPS 4.6.2 "
          "+ DevSim 2.10.1")


if __name__ == "__main__":
    main()
