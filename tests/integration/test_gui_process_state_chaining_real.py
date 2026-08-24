#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process-state / geometry-chaining regression, real ViennaPS 4.6.2.

Reproduces a real bug reported by the user: running a chained step
(deposition, specifically) through the GUI made a Mask material
suddenly appear in the geometry, and made an earlier step's shape
appear to "come back" -- neither of which the user had asked for.

Root cause, confirmed by reading the actual GUI code (not assumed):
tcad_2d_stagewise.py's `_mask_recipe_keys_for_current_step()` used to
return `remask_spans_um` -- inserting a NEW mask via
session.remask_domain() -- for EVERY chained etch/deposition step
unconditionally, derived from self.wafer.mask_openings_um (a GUI field
that persists from whatever it last was, e.g. the fixed 3.5-6.5 GUI
default, and never clears itself). So a plain blanket deposition run
after an earlier step silently got masked using stale/default litho
state the user never set up FOR THIS STEP. Compounding it:
deposition's own duplicateTopLevelSet() duplicates the domain's
CURRENT top level set, which the just-inserted mask now was -- so the
"new" material's starting shape was the mask box, not the real prior
surface, which is why an unrelated earlier step's geometry appeared to
resurface.

Fixed by gating mask application on whether the user has explicitly
gone through the Lithography sequence (PR COAT through DEVELOP) since
the last real step -- the same condition that already controls the
canvas's PR/mask preview overlay, so what's shown is exactly what's
applied. This test verifies the FIXED behavior directly at the library
level (the same recipes _mask_recipe_keys_for_current_step() now
builds when no lithography was done for a step), independent of Tk:

  Si -> Oxidation (blanket) -> check
     -> Deposition (chained, NO litho done) -> check: prior geometry
        UNCHANGED, only the new film added, NO Mask material
     -> Etching (chained, NO litho done) -> check: prior geometry
        UNCHANGED, only the new film's own shape changed, NO Mask
     -> Doping (analytical) -> check: attaches to the Si region of the
        FINAL mesh, doesn't touch/require any Mask material

Each step's own check re-verifies every EARLIER step's own measurement
is still true on the new mesh, not just that step's own new feature --
that is what "process state accumulates, nothing else changes"
actually means.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
import tcad.process.deposition  # noqa: F401
from tcad.process.flow import FlowStep, run_flow
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping

GRID, XE, YE = 0.1, 8.0, 5.0
NM = {0: "Mask", 5: "Metal", 10: "Si", 30: "SiO2"}


TOL = 0.01  # um -- one grid-cell-scale slack for independent
            # re-triangulation/export noise between separate mesh
            # exports of the SAME geometry (not a real change).


def _same(a, b):
    return all(abs(x - y) < TOL for x, y in zip(a, b))


def materials(mesh_path):
    m = meshio.read(mesh_path)
    block = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(block)]
    cx = m.points[block.data][:, :, 0].mean(axis=1)
    cy = m.points[block.data][:, :, 1].mean(axis=1)
    out = {}
    for tag in sorted(set(int(t) for t in tags)):
        s = tags == tag
        out[NM.get(tag, tag)] = (
            round(float(cx[s].min()), 3), round(float(cx[s].max()), 3),
            round(float(cy[s].min()), 3), round(float(cy[s].max()), 3),
        )
    return out


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # --- Step 1: Oxidation, blanket, first step -----------------------
        # mask_spans_um: [] mirrors run_oxidation()'s own "LOCOS
        # unchecked" recipe -- no mask at all on a fresh wafer.
        steps = [
            FlowStep(category="oxidation", name="thermal", recipe={
                "grid_delta_um": GRID, "x_extent_um": XE, "y_extent_um": YE,
                "mask_spans_um": [],
                "pr_thickness_um": 0.5, "silicon_depth_um": 4.0,
                "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.2,
            }),
            # --- Step 2: Deposition, chained, NO lithography done -----------
            # This is the exact recipe shape
            # _mask_recipe_keys_for_current_step() now produces for a
            # chained step when self.process_stage is NOT one of
            # pr_coated/aligned/exposed/developed: no mask_* key at all.
            FlowStep(category="deposition", name="isotropic", recipe={
                "grid_delta_um": GRID, "x_extent_um": XE, "y_extent_um": YE,
                "silicon_depth_um": 4.0,
                "deposition_time_s": 1.0, "rate": 0.15, "material": "Metal",
            }),
            # --- Step 3: Etching, chained, NO lithography done ---------------
            # Blanket etch of ONLY the metal film (selectivity, not a
            # mask) -- proves a chained step with no mask keys touches
            # ONLY what its own physical parameters say, nothing else.
            FlowStep(category="etching", name="isotropic", recipe={
                "grid_delta_um": GRID, "x_extent_um": XE, "y_extent_um": YE,
                "silicon_depth_um": 4.0,
                "material_rates": {"Metal": -1.0, "SiO2": 0.0, "Si": 0.0},
                "default_rate": 0.0,
                "etch_time_s": 0.6,
            }),
        ]
        results = run_flow(steps, tmp)

        # --- Check 1: Oxidation result -------------------------------------
        after_ox = materials(results[0].volume_mesh_path)
        assert set(after_ox) == {"Si", "SiO2"}, (
            f"blanket oxidation produced unexpected materials: {after_ox}")
        ox_si_x = after_ox["Si"][:2]
        assert ox_si_x[1] - ox_si_x[0] > XE - 1.0, (
            f"Si does not span the full wafer after oxidation: {after_ox}")
        si_top_after_ox = after_ox["Si"][3]
        print(f"[1/4] Oxidation: {after_ox}")

        # --- Check 2: Deposition result -------------------------------------
        after_dep = materials(results[1].volume_mesh_path)
        assert "Mask" not in after_dep, (
            f"Mask material appeared from a blanket deposition with no "
            f"lithography done -- THE REPORTED BUG: {after_dep}")
        assert "Metal" in after_dep, f"deposited film missing: {after_dep}"
        # The prior step's own materials must be UNCHANGED in extent --
        # "accumulates, doesn't get replaced."
        assert _same(after_dep["Si"], after_ox["Si"]), (
            f"Si changed shape from a deposition step: "
            f"{after_ox['Si']} -> {after_dep['Si']}")
        assert _same(after_dep["SiO2"], after_ox["SiO2"]), (
            f"SiO2 changed shape from a deposition step: "
            f"{after_ox['SiO2']} -> {after_dep['SiO2']}")
        assert after_dep["Metal"][1] - after_dep["Metal"][0] > XE - 1.0, (
            f"deposited Metal is not a full blanket film: {after_dep}")
        print(f"[2/4] Deposition (unmasked, blanket): {after_dep}")
        print("      no Mask material, Si/SiO2 unchanged from step 1")

        # --- Check 3: Etching result -----------------------------------------
        after_etch = materials(results[2].volume_mesh_path)
        assert "Mask" not in after_etch, (
            f"Mask material appeared from a blanket etch with no "
            f"lithography done: {after_etch}")
        assert _same(after_etch["Si"], after_ox["Si"]), (
            f"Si changed shape from an etch step that should only touch "
            f"Metal: {ox_si_x} -> {after_etch['Si']}")
        assert _same(after_etch["SiO2"], after_ox["SiO2"]), (
            f"SiO2 changed shape from an etch step that should only "
            f"touch Metal: {after_ox['SiO2']} -> {after_etch['SiO2']}")
        # The etch (rate=-1.0 on Metal only, 0.6s, film was 0.15um) must
        # have genuinely thinned the Metal film, proving the etch's own
        # intended effect DID apply (this isn't a no-op check).
        metal_before = after_dep["Metal"][3] - after_dep["Metal"][2]
        if "Metal" in after_etch:
            metal_after = after_etch["Metal"][3] - after_etch["Metal"][2]
            assert metal_after < metal_before, (
                f"etch had no effect on Metal thickness: "
                f"{metal_before:.3f} -> {metal_after:.3f}")
            print(f"[3/4] Etching (unmasked, blanket): {after_etch}")
            print(f"      Metal thinned {metal_before:.3f} -> {metal_after:.3f} um, "
                  "Si/SiO2 unchanged from step 1")
        else:
            print(f"[3/4] Etching (unmasked, blanket) fully cleared Metal: {after_etch}")
            print("      Si/SiO2 unchanged from step 1")

        # --- Check 4: Doping (analytical, not a ViennaPS geometry step) -----
        process_result = build_process_result(
            {"final_mesh": results[2].volume_mesh_path, "snapshots": []}
        )
        doped = apply_uniform_doping(process_result, {"Si": 1e17})
        assert doped.doping is not None and doped.doping.regions, (
            "doping profile was not attached")
        assert doped.doping.regions[0].region == "Si", (
            f"doping attached to the wrong region: {doped.doping.regions[0].region}")
        assert doped.material_regions == process_result.material_regions, (
            "applying doping must not alter the geometry it was attached to")
        print(f"[4/4] Doping: attached to region 'Si' of the FINAL mesh "
              f"(post oxidation+deposition+etch), geometry unchanged by doping")

    print()
    print("PROCESS STATE / GEOMETRY CHAINING VERIFIED AGAINST REAL VIENNAPS 4.6.2")
    print("(Si -> Oxidation -> Deposition -> Etching -> Doping, each step")
    print(" preserving every earlier step's geometry, no unrequested Mask)")


if __name__ == "__main__":
    main()
