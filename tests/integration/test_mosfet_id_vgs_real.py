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

A SECOND real bug was found and fixed after that one, by an independent
Ohm's-law cross-check of the drain current against the simulation's own
node data (see CLAUDE.md): the Si-SiO2 interface refinement was sized
from the BODY doping's Debye length, but an inversion layer's carriers
reach the SOURCE/DRAIN doping scale, so its real thickness is ~2nm, not
the ~25nm the body-derived mesh provided. The inversion layer was
spanned by a single mesh node and the drain current was throttled by
3.8e7x (Id = 1.49e-12 A, i.e. the device read as essentially an open
circuit). Refinement is now DERIVED from the doping profile's own peak
concentration via `derive_implant_windows_refinement()` — Id = 5.68e-05
A, and confirmed converged (two more halvings, 79126 nodes, move it
only 1.7% to 5.78e-05 A).

Checks:
  1. real production run() -> filter -> doping-derived graded
     refinement -> implant_windows doping -> import -> apply_doping ->
     run_mosfet_id_vgs_sweep(), all succeed.
  2. NetDoping matches the requested implant_windows profile exactly.
  3. every gate-voltage point converges (the sweep itself raises on
     non-convergence).
  4. charge conservation: source current == -drain current, judged
     against the sweep's own current scale (see the check's own comment
     for why a per-point relative tolerance is meaningless in the off
     state).
  5. real transistor action: the drain current turns on by orders of
     magnitude across the sweep and rises monotonically with gate
     voltage. This is NOT a claim that the absolute magnitude matches an
     idealized long-channel square-law estimate — a residual ~800x gap
     against a sheet-conductance estimate built from the simulation's
     own node data remains open and is documented in CLAUDE.md.
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
    derive_implant_windows_refinement,
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

        def _dope(process_result):
            return apply_implant_windows_doping(
                process_result, region="Si", axis="x",
                background_doping_cm3=BACKGROUND_DOPING_CM3,
                windows=[
                    {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                    {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
                ],
            )

        # Refinement is DERIVED from the doping profile, not hand-picked
        # per doping level -- see derive_implant_windows_refinement's own
        # docstring for why both the lateral junction rings AND the
        # Si-SiO2 interface rings must be sized from the profile's PEAK
        # concentration (measured: sizing the interface from the body
        # doping instead leaves the inversion layer one node thick and
        # throttles Id by 3.8e7x).
        doping = _dope(build_process_result(
            {"final_mesh": filtered, "snapshots": []})).doping
        predicates = derive_implant_windows_refinement(
            doping, points, triangles, interface_position_um=0.0, interface_axis="y",
        )
        assert predicates, "no refinement derived from the implant_windows profile"

        refined_points, refined_tris, refined_tags = graded_refine_mesh_near(
            points, triangles, tags, predicates
        )
        refined_mesh = meshio.Mesh(
            points=refined_points, cells=[("triangle", refined_tris)],
            cell_data={"Material": [refined_tags]},
        )
        refined_path = f"{filtered}.refined.vtu"
        meshio.write(refined_path, refined_mesh)
        print(f"[3/6] doping-derived graded refinement: {len(points)} -> "
              f"{len(refined_points)} points ({len(predicates)} predicates)")

        step_result = {"final_mesh": refined_path, "snapshots": result["snapshots"]}
        process_result = _dope(build_process_result(step_result))

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

        id_series = [pt.currents["Si_xmax"] for pt in result_iv.points]
        is_series = [pt.currents["Si_xmin"] for pt in result_iv.points]
        print(f"      Vgs (V): {gate_voltages}")
        print(f"      Id  (A): {[f'{i:.4e}' for i in id_series]}")
        print(f"      Is  (A): {[f'{i:.4e}' for i in is_series]}")

        id_off = abs(id_series[0])
        id_on = abs(id_series[-1])
        id_scale = max(abs(i) for i in id_series)

        # Check 4: charge conservation. Judged against the sweep's OWN
        # current scale, not each point's own magnitude: in the off state
        # the terminal currents sit at the solver's numerical noise floor
        # (measured: Is=-2.75e-12 A vs Id=+2.22e-12 A at Vgs=0, while the
        # on-state carries ~1e-5 A), where a per-point RELATIVE tolerance
        # is meaningless -- it would be comparing two numbers that are
        # both, physically, zero. There is nowhere else for current to go
        # in this device (the gate contact carries no DC current: it has
        # only PotentialEquation, no continuity equation), so any real
        # imbalance would show up as a violation at the scale where
        # current is actually flowing.
        for vg, i_source, i_drain in zip(gate_voltages, is_series, id_series):
            assert abs(i_source + i_drain) < 0.02 * id_scale, (
                f"charge not conserved at Vgs={vg}: Is={i_source:.4e} "
                f"Id={i_drain:.4e} (sweep current scale {id_scale:.4e})"
            )

        # Check 5: real transistor action -- on-state current exceeds
        # off-state by orders of magnitude, not a marginal factor. This
        # threshold is only meaningful because the inversion layer is now
        # vertically resolved (see the module docstring): with the old,
        # body-doping-derived interface refinement the whole sweep sat at
        # the pA noise floor and moved by ~1.3x.
        assert id_on > 100.0 * id_off, (
            f"drain current did not turn on with gate voltage: "
            f"Vgs=0 -> {id_off:.4e}A, Vgs={gate_voltages[-1]} -> {id_on:.4e}A"
        )
        # Monotonic turn-on: every step of gate voltage increases current.
        for i in range(1, len(id_series)):
            assert abs(id_series[i]) > abs(id_series[i - 1]), (
                f"drain current not monotonic in gate voltage: {id_series}"
            )
        print(f"[6/6] Id-Vgs sweep converged at all {len(gate_voltages)} points; "
              f"charge conserved; drain current monotonically turns on "
              f"({id_off:.4e}A -> {id_on:.4e}A, {id_on / id_off:.3e}x)")

    print()
    print("MOSFET Id-Vgs TRANSFER CHARACTERISTIC (real gate-controlled "
          "source-to-drain current) VERIFIED against real ViennaPS 4.6.2 "
          "+ DevSim 2.10.1")


if __name__ == "__main__":
    main()
