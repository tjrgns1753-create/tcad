#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOSFET Vth EXTRACTION from a real, simulated Id-Vgs curve — via
tcad.characterization.vth_extraction.extract_vth_from_result's linear-
extrapolation method — as opposed to every prior "Vth" in this project,
which was a hand-derived ANALYTICAL value used only to sanity-check an
already-simulated curve after the fact (see CLAUDE.md's "MOSFET
Id-Vgs magnitude gap" investigation). This closes the gap
tcad/characterization/__init__.py's own docstring names ("Vth and
subthreshold slope are future work").

Same production device-build pipeline as
test_mosfet_id_vgs_real.py (gate_stack geometry, doping-derived graded
refinement, implant_windows doping, run_mosfet_id_vgs_sweep) — not
duplicated by copy-paste-and-hope: every step here is the same real
ViennaPS/DevSim call sequence that test already verifies converges for
this exact device, extended only in the gate-voltage LIST (denser
sampling in the strong-inversion linear region a linear-extrapolation
fit needs) and in what's computed AFTER the sweep (Vth extraction and
an analytical cross-check), not in the device/mesh/doping/refinement
code path itself.

AUDIT FINDING carried over from the MOS C-V audit (see
tests/integration/test_mosfet_gate_stack_cv_real.py's own "AUDIT
FINDING" docstring section for the full account): this device's
GRID=0.05 / GATE_OXIDE_UM=0.02 combination gets its gate oxide floored
by session.make_gate_stack()'s own 1.5*grid_delta_um export-safety
floor to an ACTUAL 0.075um, not the requested 0.02um. The "Vth≈1.77V"
figure recorded in docs/investigation_log.md's "MOSFET Id-Vgs magnitude
gap" section used the REQUESTED (0.02um) thickness in the standard
long-channel Vth formula, not the actual built one — the same stale-
-reference-value mistake found and fixed for C_ox. Recomputed with the
ACTUAL oxide thickness (now available via GateStack.run()'s own
`actual_gate_oxide_thickness_um`, see gate_stack.py), Cox is ~3.75x
smaller and the long-channel-formula Vth comes out well above 1.77V
(the exact number is computed and printed below, not hand-typed here,
so this docstring can't silently drift out of sync with the real
constants). That number is used ONLY as a loose sanity band in this
test (this device's channel is a short 2um, and the analytical formula
assumes idealized long-channel electrostatics with no 2D fringing —
real deviation from it is expected and is not itself a bug), not as an
exact target: the actual point of this test is that Vth is EXTRACTED
from the real simulated curve, landing somewhere physically sane
relative to where that curve visibly turns on.

Checks:
  1. real production run() -> filter -> doping-derived graded
     refinement -> implant_windows doping -> import -> apply_doping ->
     run_mosfet_id_vgs_sweep(), all succeed (same pipeline
     test_mosfet_id_vgs_real.py already verifies, denser gate sweep).
  2. extract_vth_from_result() runs on the real returned
     CharacterizationResult with no error and a positive gm_max.
  3. the extracted Vth falls strictly inside the swept gate-voltage
     range (a basic sanity bound: Id is near the noise floor at the
     sweep's lowest point and clearly on by its highest, so a
     meaningful extraction must land between them, not extrapolate
     wildly outside the data it came from).
  4. the extracted Vth is within a generous (2x, either direction)
     band of the long-channel analytical estimate RECOMPUTED with the
     device's own ACTUAL (post-floor) oxide thickness — loose because
     this is a short-channel 2D device the idealized formula does not
     exactly describe, tight enough to catch a genuinely broken
     extraction (e.g. picking up the wrong segment, or an off-by-one
     in the Vds/2 correction).
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

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
from tcad.characterization.vth_extraction import extract_vth_from_result

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
# Same contiguous channel/junction geometry test_mosfet_id_vgs_real.py
# already verified converges (see that test's own module docstring for
# why "contiguous" matters -- a gap here electrically severs the
# channel from the source/drain regardless of gate voltage).
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17  # p-type channel/body
SD_DOPING_CM3 = 1e20           # n+ source/drain
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4
DRAIN_VOLTAGE = 0.1  # linear region -- required for linear-extrapolation Vth

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


def _analytic_vth_v(t_ox_um: float) -> float:
    """Standard long-channel Vth = 2*phi_F + Qdep_max/Cox, using
    DevSim's own real constants (not re-derived textbook ones) and the
    device's ACTUAL oxide thickness -- see this module's own docstring
    "AUDIT FINDING" section for why the actual (not requested) value
    matters here.
    """
    from devsim.python_packages.simple_physics import eps_0, eps_ox, eps_si, k, n_i, q

    t_300k = 300.0
    v_t = k * t_300k / q
    na = abs(BACKGROUND_DOPING_CM3)
    phi_f = v_t * math.log(na / n_i)
    t_ox_cm = t_ox_um * LENGTH_SCALE_TO_CM
    c_ox = eps_ox * eps_0 / t_ox_cm
    q_dep_max = math.sqrt(2 * eps_si * eps_0 * q * na * 2 * phi_f)
    return 2 * phi_f + q_dep_max / c_ox


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        actual_t_ox_um = result["actual_gate_oxide_thickness_um"]
        print(f"[1/6] gate_stack built via real production run(): {result['final_mesh']}")
        print(f"      actual built gate oxide thickness = {actual_t_ox_um}um "
              f"(requested {GATE_OXIDE_UM}um)")

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

        # Doping-derived graded refinement -- same rationale as
        # test_mosfet_id_vgs_real.py (interface rings must be sized from
        # the PEAK, not body, concentration, or the inversion layer is
        # left one node thick -- see CLAUDE.md's 3.8e7x writeup).
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
            process_result, mesh_name="mosfet_vth_mesh", device_name="mosfet_vth_device",
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

        # Denser than test_mosfet_id_vgs_real.py's own [0,2,4,6,8] --
        # a linear-extrapolation fit needs several points actually past
        # threshold to find its steepest segment; this adds 3,5,7
        # without changing the proven 0/2/4/6/8 backbone.
        gate_voltages = [0.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        result_iv = run_mosfet_id_vgs_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages, drain_voltage=DRAIN_VOLTAGE,
        )
        assert len(result_iv.points) == len(gate_voltages)

        id_series = [pt.currents["Si_xmax"] for pt in result_iv.points]
        print(f"[5/6] Id-Vgs sweep converged at all {len(gate_voltages)} points")
        print(f"      Vgs (V): {gate_voltages}")
        print(f"      Id  (A): {[f'{i:.4e}' for i in id_series]}")

        vth_result = extract_vth_from_result(result_iv, drain_contact="Si_xmax")
        print(f"[6/6] EXTRACTED Vth = {vth_result.vth_v:.4f} V "
              f"(gm_max={vth_result.gm_max:.4e}, "
              f"at Vgs~{vth_result.vgs_at_gm_max:.2f}V, "
              f"intercept={vth_result.intercept_v:.4f}V before Vds/2 correction)")

        assert vth_result.gm_max > 0.0, "extracted transconductance must be positive"

        # Check 3: extracted Vth must fall strictly inside the swept range.
        assert gate_voltages[0] < vth_result.vth_v < gate_voltages[-1], (
            f"extracted Vth={vth_result.vth_v:.4f}V falls outside the swept "
            f"range [{gate_voltages[0]}, {gate_voltages[-1]}]V -- not a "
            f"meaningful extraction from this data"
        )

        # Check 4: loose (2x, either direction) sanity band against the
        # long-channel analytical estimate, recomputed with the ACTUAL
        # built oxide thickness (see module docstring's "AUDIT FINDING").
        analytic_vth = _analytic_vth_v(actual_t_ox_um)
        ratio = vth_result.vth_v / analytic_vth
        print(f"      analytic long-channel Vth (actual t_ox={actual_t_ox_um}um) "
              f"= {analytic_vth:.4f} V -- extracted/analytic ratio = {ratio:.2f}")
        assert 0.5 < ratio < 2.0, (
            f"extracted Vth={vth_result.vth_v:.4f}V is more than 2x away from "
            f"the analytic estimate {analytic_vth:.4f}V (ratio {ratio:.2f}) -- "
            f"outside the loose sanity band for a short-channel 2D device"
        )

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)
        assert devsim.get_device_list() == ()

    print()
    print("MOSFET Vth LINEAR-EXTRAPOLATION EXTRACTION (from a real simulated "
          "Id-Vgs curve, cross-checked against the analytic long-channel "
          "estimate) VERIFIED against real ViennaPS 4.6.2 + DevSim 2.10.1")


if __name__ == "__main__":
    main()
