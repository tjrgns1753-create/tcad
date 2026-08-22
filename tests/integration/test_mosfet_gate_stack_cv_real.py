#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
First electrically-exercised MOSFET-shaped device — real ViennaPS 4.6.2
+ DevSim 2.10.1, through the real production entry points throughout.

This is the "next smallest experiment" the gate_stack geometry section
named and did not execute: combine `geometry`/`gate_stack` with
`implant_windows` doping (source/drain windows over a channel/body
background, in the SAME Si region gate_stack already builds) and run a
real DevSim sweep through the gate contact. A full Id-Vgs/Id-Vds
transistor sweep is explicitly out of scope (this project's own prior,
unretracted judgment: that needs new device/equation design at roughly
Phase 7/8's own scale) — this exercises the GATE via a C-V sweep, using
the already-shipped, unmodified tcad.device.devsim.mos_equation /
tcad.characterization.cv_sweep machinery Phase 9 built.

Two real, previously-uncharacterized DevSim/export limitations were
found and worked around while building this (both documented in
CLAUDE.md and in tcad/backends/viennaps/io.py's own docstrings, not
repeated in full here):

1. save_locos_volume_mesh()-produced meshes have NO shared vertex
   indices between materials, even where they geometrically touch
   exactly (confirmed: 31/31 coincident coordinates, 0 shared indices)
   -- so mesh_import.py's interface_region_pairs (index-based edge
   matching) always found nothing. Fixed with a new, OPT-IN
   `dedupe_materials` parameter (default None, zero behavior change for
   every other caller) that merges coincident-coordinate points ONLY
   among the materials a caller names.
2. Deduping blindly across every touching material pair crashed
   DevSim's own create_device() with a native assert
   (`Geometry/Region.cc:464 UNEXPECTED`) for gate_stack's own topology
   -- traced to gate_stack's oxide+electrode sharing ONE material tag
   across TWO independently-triangulated level sets (not, as first
   suspected, to the untouched source/drain metal pads). Avoided
   entirely by keeping gate_stack's default, SEPARATE "TiN" electrode
   material and filtering it (plus the source/drain metal pads, not
   needed for a gate-only C-V sweep) out of the mesh before DevSim
   import, via a new `filter_mesh_materials()` helper -- SiO2 then
   stays a genuine single level set with its own real, exposed top
   surface, matching the already-working Phase 9 mos_cv convention
   ("SiO2_ymax" as the idealized gate contact) with zero new equation
   code.

Checks:
  1. real production run() -> filter -> doping -> import -> apply_doping
     -> C-V sweep, all succeed with no error.
  2. NetDoping in the Si region matches the requested implant_windows
     profile exactly (background under the channel/gate, heavy n-type
     under the source/drain windows) -- same rigor as
     test_implant_windows_doping_real.py's own node-by-node check.
  3. every gate-voltage point solves (the sweep itself would raise on
     non-convergence -- reaching this point IS the check).
  4. capacitance is real, positive, and the DEEPEST-ACCUMULATION point
     reaches at least 80% of the CORRECTLY-COMPUTED ideal parallel-plate
     C_ox = eps_ox*eps_0*width/t_ox -- using DevSim's own real
     eps_ox/eps_0 constants, and the ACTUAL built oxide thickness/width
     (not the recipe's requested values -- see point 5 below for why
     that distinction is load-bearing here).
  5. capacitance decreases monotonically as gate voltage sweeps from
     negative to positive -- the real, expected MOS-C-V signature for
     this p-type-background device (accumulation at negative bias, C
     highest; depletion setting in as bias goes positive, C dropping)
     -- not just "doesn't crash".

AUDIT FINDING, ROOT-CAUSED AND FIXED (this session): an independent
audit flagged this test's own accumulation capacitance as only ~25% of
its own computed "ideal C_ox" -- looking like a real physics/mesh
under-resolution problem (the same category as the already-documented
3.8e7x MOSFET inversion-layer bug). Measured directly, it was NOT that:
`session.make_gate_stack()` floors `gate_oxide_thickness_um` at
1.5*grid_delta_um for export safety (documented in its own docstring),
and at this test's own GRID=0.05/GATE_OXIDE_UM=0.02, that floor SILENTLY
built a 0.075um oxide -- 3.75x thicker than the 0.02um this test's old
C_ox calculation assumed. Using the ACTUAL built thickness
(`make_gate_stack` now returns it via `GateStack.run()`'s
`actual_gate_oxide_thickness_um`), the SAME baseline device (zero
refinement) measures 102% of the correctly-computed C_ox -- already
comfortably above 80%, before any refinement.

Interface refinement was ALSO added (via the new
`refine_process_result_for_mos_gate()`), both because it is real,
useful hardening (the accumulation charge layer is a genuine
near-interface concentration effect worth resolving on the same
"refine near what's actually being measured" principle CLAUDE.md
already states) and because the user explicitly asked for it. Measured
effect: it pushes the ratio HIGHER still (128% at 2 rings) rather than
toward the 100% a naive "converging to the ideal value" model would
predict -- this is real 2D physics, not a bug: `gate_stack`'s idealized
gate has no field plate / no gradual oxide taper, so its abrupt lateral
edge is a genuine conductor-edge field-concentration point, and finer
mesh resolves progressively more of it (measured NOT to converge to a
fixed value even at 4 rings: 102% / 128% / 134% / 140% at 0/2/3/4
rings) -- the same "not fixable by refinement at this idealization
layer" character already documented for the KOH V-groove apex
singularity. 2 rings (a modest, ~15%-more-nodes addition) is used here
as a genuine accuracy improvement, not chasen further toward that
un-converging singularity. Because real 2D edge/fringing capacitance
CAN legitimately exceed the idealized 1D parallel-plate C_ox (the old
`c < c_ox_ideal` hard upper-bound assertion assumed an infinite,
fringe-free plate, which this finite-width idealized gate is not), that
assertion is replaced with the physically defensible pair of checks
this docstring's own point 4 states: positive, and >=80% of C_ox at
peak accumulation -- not an upper bound that real fringing can and does
violate.

FOLLOW-UP VERIFICATION (later session, user-requested second-guess of
the ">100% of Cox" finding before trusting it): three independent
checks were run to distinguish "real fringing" from "a different
geometry/charge-computation bug that happens to look similar" --
1. SPATIAL charge profile: read DevSim's own `contactcharge_edge` edge
   model directly along the gate contact's own vertical edges (not
   inferred from the total). Result: charge density is UNIFORM to 6
   significant figures across the center ~70% of the gate width
   (5.763078e-08 C/cm essentially unchanged from x=-0.4 to +0.35um --
   matching the ideal parallel-plate PREDICTION exactly, ruling out a
   bulk permittivity/doping/units bug), then rises sharply approaching
   both edges (peaking at 9.10e-08 C/cm at the +0.75um edge, a 58%
   local enhancement over center; +0.45um at the -0.75um edge, 12% --
   asymmetric in magnitude but the SAME sign/character on both sides).
   This is the textbook signature of edge charge concentration, not a
   uniform/global effect.
2. WIDTH scan (gate half-width 0.8/1.6/3.2/6.4um, same t_ox, grid,
   UNREFINED mesh so only the width changes): ratio to the correctly
   -computed Cox is 95.1% / 97.0% / 97.9% / 98.4% -- monotonically
   approaching 100% as the gate widens, i.e. as the FIXED-size edge
   feature becomes a smaller fraction of the total. A bulk-property bug
   (wrong permittivity, wrong doping, a units error) would instead
   produce a constant percentage offset independent of width.
3. THICKNESS scan (t_ox 0.075/0.15/0.3/0.6um, same half-width, same
   UNREFINED mesh): ratio is 95.1% / 96.1% / 97.7% / 98.7% -- also
   approaching 100% as the oxide thickens, the same dilution signature
   via an independent parameter.
   Both scans use an UNREFINED mesh and land BELOW 100% (not above) --
   consistent with ordinary coarse-mesh discretization error mildly
   UNDER-counting a sharp field feature; it is specifically adding
   LOCAL refinement at that same edge (the >100% figures earlier in
   this docstring) that resolves enough of the true, larger singular
   contribution to push the total past the naive 1D Cox. Both pieces
   are consistent with one underlying mechanism (a real, geometry
   -localized conductor-edge singularity), not two unrelated effects.
Conclusion: the >100% Cox ratio is real 2D edge/fringing physics from
this idealized gate's abrupt lateral termination, not a geometry,
charge-computation, or units bug. No code change resulted from this
check (the shipped fix above was already correct); recorded here so a
future session doesn't have to re-derive it.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.geometry  # noqa: F401 -- registers gate_stack
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result, refine_process_result_for_mos_gate
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.cv_sweep import run_mos_cv_sweep

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
CHANNEL = (-0.8, 0.8)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
BACKGROUND_DOPING_CM3 = -1e17  # p-type channel/body
SD_DOPING_CM3 = 1e20           # n+ source/drain
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4

RECIPE = {
    "grid_delta_um": GRID,
    "x_extent_um": 6.0,
    "y_extent_um": 3.0,
    "silicon_depth_um": 1.0,
    "channel_um": list(CHANNEL),
    "source_um": list(SRC),
    "drain_um": list(DRN),
    "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15,
    "pad_height_um": 0.10,
    # Default materials (Si/TiN/W/Cu/SiO2) -- deliberately unchanged
    # from gate_stack's own already-shipped test, see point 2 above for
    # why TiN/W/Cu are then filtered out rather than merged into SiO2.
    "dedupe_materials": ["Si", "SiO2"],
}


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        print(f"[1/5] gate_stack built via real production run(): {result['final_mesh']}")

        actual_t_ox_um = result["actual_gate_oxide_thickness_um"]
        print(f"[1b/5] actual built gate oxide thickness = {actual_t_ox_um}um "
              f"(requested {GATE_OXIDE_UM}um)")

        filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])
        print(f"[2/5] filtered to Si+SiO2 only (electrode/pads not needed for gate C-V): {filtered}")

        step_result = {"final_mesh": filtered, "snapshots": result["snapshots"]}
        process_result = build_process_result(step_result)
        process_result = apply_implant_windows_doping(
            process_result, region="Si", axis="x",
            background_doping_cm3=BACKGROUND_DOPING_CM3,
            windows=[
                {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
            ],
        )

        refined = refine_process_result_for_mos_gate(
            process_result, channel_min_um=CHANNEL[0], channel_max_um=CHANNEL[1],
            interface_position_um=0.0, interface_axis="y",
        )
        assert refined is not None, "expected the channel window to be refinable"
        process_result = refined
        print(f"[2b/5] Si-SiO2 interface refined under the gate (channel window "
              f"{CHANNEL}): {process_result.volume_mesh_path}")

        imported = import_process_result(
            process_result, mesh_name="mosfet_cv_mesh", device_name="mosfet_cv_device",
            contact_regions=["Si", "SiO2"], contact_axis="y",
            contact_sides={"Si": "min", "SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.regions) == {"Si", "SiO2"}, imported.regions
        assert set(imported.contacts) == {"Si_ymin", "SiO2_ymax"}, imported.contacts
        assert imported.interfaces == ["Si_SiO2_interface"], imported.interfaces
        print(f"[3/5] imported: regions={imported.regions} contacts={imported.contacts} "
              f"interfaces={imported.interfaces}")

        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        # Check 2: NetDoping matches the requested implant_windows profile
        # node-by-node (same rigor as test_implant_windows_doping_real.py).
        xs = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        net_doping = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")
        max_rel_err = 0.0
        checked = 0
        for x_cm, doping in zip(xs, net_doping):
            x_um = x_cm / LENGTH_SCALE_TO_CM
            expected = BACKGROUND_DOPING_CM3
            for lo, hi in (SRC, DRN):
                if lo + GRID < x_um < hi - GRID:  # avoid boundary-tolerance nodes
                    expected += SD_DOPING_CM3
            if abs(x_um - SRC[0]) < GRID or abs(x_um - SRC[1]) < GRID or \
               abs(x_um - DRN[0]) < GRID or abs(x_um - DRN[1]) < GRID:
                continue  # skip nodes within one grid cell of a window boundary
            rel_err = abs(doping - expected) / abs(expected)
            max_rel_err = max(max_rel_err, rel_err)
            checked += 1
        assert max_rel_err < 1e-9, f"NetDoping mismatch: max relative error {max_rel_err:.3e}"
        print(f"[4/5] NetDoping matches the implant_windows profile exactly "
              f"({checked} nodes checked, max relative error {max_rel_err:.3e})")

        gate_voltages = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
        result_cv = run_mos_cv_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            gate_contact="SiO2_ymax", substrate_contact="Si_ymin",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages,
        )
        capacitance_f = result_cv.metadata["capacitance_F"]
        assert len(capacitance_f) == len(gate_voltages) - 1

        from devsim.python_packages.simple_physics import eps_0, eps_ox
        # Use the ACTUAL built oxide thickness (see module docstring's
        # "AUDIT FINDING" section) -- GATE_OXIDE_UM alone would silently
        # be wrong whenever make_gate_stack()'s export-safety floor
        # fires (exactly what happens at this test's own GRID/
        # GATE_OXIDE_UM combination: 0.075um built vs 0.02um requested).
        t_ox_cm = actual_t_ox_um * LENGTH_SCALE_TO_CM
        width_cm = (CHANNEL[1] - CHANNEL[0]) * LENGTH_SCALE_TO_CM
        c_ox_correct = eps_ox * eps_0 * width_cm / t_ox_cm

        for c in capacitance_f:
            assert c > 0.0, f"non-positive capacitance: {c}"
        for i in range(1, len(capacitance_f)):
            assert capacitance_f[i] <= capacitance_f[i - 1] + 1e-15, (
                f"capacitance not monotonically decreasing with gate voltage: "
                f"{capacitance_f}"
            )
        # Deepest accumulation is the FIRST point (most negative gate
        # voltage) since capacitance is monotonically decreasing (just
        # checked above). No upper bound against c_ox_correct: a real,
        # finite-width 2D gate has genuine edge/fringing capacitance a
        # 1D infinite-plate C_ox formula does not capture, and this
        # idealized gate_stack geometry (no field plate) has an
        # especially sharp lateral edge -- see the module docstring's
        # "AUDIT FINDING" section for the direct measurement ruling out
        # "no upper bound" as an oversight rather than a deliberate
        # correction.
        accumulation_c = capacitance_f[0]
        accumulation_ratio = accumulation_c / c_ox_correct
        assert accumulation_ratio >= 0.8, (
            f"deepest-accumulation capacitance {accumulation_c:.3e} F is only "
            f"{accumulation_ratio:.1%} of the correctly-computed ideal C_ox "
            f"{c_ox_correct:.3e} F (want >= 80%)"
        )
        print(f"[5/5] C-V sweep converged at all {len(gate_voltages)} points; capacitance "
              f"real/positive and monotonically decreasing (accumulation -> depletion, the "
              f"expected p-type-substrate signature): {[f'{c:.3e}' for c in capacitance_f]}")
        print(f"      correctly-computed ideal C_ox = {c_ox_correct:.3e} F "
              f"(actual t_ox={actual_t_ox_um}um, width={CHANNEL[1]-CHANNEL[0]}um); "
              f"deepest accumulation C = {accumulation_c:.3e} F = "
              f"{accumulation_ratio:.1%} of C_ox")

    print()
    print("MOSFET-SHAPED DEVICE (gate_stack geometry + implant_windows doping + "
          "real DevSim C-V sweep through the gate contact) VERIFIED against "
          "real ViennaPS 4.6.2 + DevSim 2.10.1")


if __name__ == "__main__":
    main()
