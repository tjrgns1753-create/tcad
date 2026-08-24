#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blanket (mask-less) process steps — real ViennaPS 4.6.2.

Why this exists: `prepare_domain()` used to build a photoresist mask
unconditionally on every fresh wafer, because the whole process layer
assumed "a process step always follows lithography". That is true for
etching and false for any BLANKET step. The consequence was not a
cosmetic extra material — it was physically impossible geometry:
measured on a plain Dry/1000C/0.5hr oxidation, SiO2 grew on TOP of the
photoresist (y +0.496..+0.556) while the silicon underneath it was
consumed (top at -0.017), leaving oxide separated from the silicon it
supposedly grew out of by the full 0.5um resist thickness. The mask also
blocked nothing at all (oxide area per unit width 0.02597 masked vs
0.02579 open, a 0.7% difference), because fin-style oxidation never
calls setMaskMaterial().

There was no way to ask for a bare wafer, either: `pr_thickness_um: 0.0`
was clamped up to a 0.1um mask by make_trench(), and a fully-open mask
(`mask_spans_from_openings` over the whole wafer) returns an empty span
list, which the old truthiness test treated as "no spans given" and sent
down the MakeTrench path — silently producing a masked wafer.

Checks (all against a real ViennaPS run, judged from the exported mesh):
  1. no mask keys at all           -> Si + SiO2 only, no Mask
  2. mask_spans_um: []             -> same
  3. oxide is physically coherent  -> it straddles the original wafer
     surface and is CONTIGUOUS with the silicon, rather than floating
     above a resist layer
  4. blanket deposition            -> deposited layer sits on top of Si,
     no Mask
  5. the masked path is UNCHANGED  -> mask_left_um/mask_right_um still
     produce a Mask material
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.deposition  # noqa: F401 -- registers deposition models
import tcad.process.oxidation  # noqa: F401 -- registers thermal oxidation
from tcad.process import registry
from tcad.process.base import mask_spans_from_openings

GRID = 0.05
X_EXTENT = 4.0
BASE = {"grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0}
OXIDATION = {"oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5}

MASK, SI, SIO2 = 0, 10, 30  # ViennaPS Material enum ids


def materials(category, model, recipe):
    """Run a real step and return {material_id: (y_min, y_max)} measured
    from the exported mesh's triangle centroids."""
    step = registry.get(category, model)()
    with tempfile.TemporaryDirectory() as tmp:
        result = step.run({**BASE, **recipe}, tmp)
        mesh = meshio.read(result["final_mesh"])
        block = next(c for c in mesh.cells if c.type == "triangle")
        tags = mesh.cell_data["Material"][mesh.cells.index(block)]
        cy = mesh.points[block.data][:, :, 1].mean(axis=1)
        return {int(t): (float(cy[tags == t].min()), float(cy[tags == t].max()))
                for t in sorted(set(tags))}


def main():
    # --- 1: no mask keys at all -> bare wafer ---------------------------
    bare = materials("oxidation", "thermal", OXIDATION)
    assert MASK not in bare, f"blanket oxidation still built a mask: {bare}"
    assert set(bare) == {SI, SIO2}, f"expected Si+SiO2 only, got {bare}"
    print(f"[1/5] no mask keys -> Si+SiO2 only, no Mask: {bare}")

    # --- 2: an explicitly EMPTY mask means the same thing ---------------
    open_mask = mask_spans_from_openings([(0.0, X_EXTENT)], X_EXTENT)
    assert open_mask == [], f"a fully-open mask should have no opaque spans: {open_mask}"
    spans = materials("oxidation", "thermal", {**OXIDATION, "mask_spans_um": open_mask})
    assert MASK not in spans, f"mask_spans_um=[] still built a mask: {spans}"
    assert spans == bare, f"empty-mask and no-mask recipes disagree: {spans} vs {bare}"
    print(f"[2/5] mask_spans_um=[] -> identical bare wafer")

    # --- 3: the oxide is physically coherent ----------------------------
    # Thermal oxidation consumes silicon and grows oxide across the
    # original surface, so the oxide must span y=0 and must not be
    # separated from the silicon by anything. One grid cell of slack:
    # these are triangle CENTROIDS, so each surface reads half a cell
    # inside its own material.
    si_top, ox_lo, ox_hi = bare[SI][1], bare[SIO2][0], bare[SIO2][1]
    assert ox_lo < 0.0 < ox_hi, (
        f"oxide does not straddle the original wafer surface: {ox_lo}..{ox_hi}")
    assert si_top < 0.0, f"silicon was not consumed by oxidation: top at {si_top}"
    assert ox_lo - si_top < GRID, (
        f"oxide bottom ({ox_lo:.4f}) is detached from the silicon top "
        f"({si_top:.4f}) by more than one grid cell -- this is the "
        f"'oxide grown on top of the photoresist' failure mode")
    print(f"[3/5] oxide coherent: Si consumed to {si_top:+.4f}, "
          f"oxide {ox_lo:+.4f}..{ox_hi:+.4f} straddling the surface")

    # --- 4: blanket deposition ------------------------------------------
    dep = materials("deposition", "isotropic",
                    {"deposition_time_s": 1.0, "rate": 0.1, "material": "SiO2"})
    assert MASK not in dep, f"blanket deposition still built a mask: {dep}"
    assert dep[SIO2][1] > dep[SI][1], (
        f"deposited SiO2 is not on top of the Si: {dep}")
    print(f"[4/5] blanket deposition -> SiO2 on top of Si, no Mask: {dep}")

    # --- 5: the masked path is untouched --------------------------------
    masked = materials("oxidation", "thermal", {
        **OXIDATION, "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    })
    assert MASK in masked, f"masked recipe lost its mask: {masked}"
    print(f"[5/5] mask_left/right path unchanged, Mask present: "
          f"y {masked[MASK][0]:+.4f}..{masked[MASK][1]:+.4f}")

    print()
    print("BLANKET (MASK-LESS) PROCESS STEPS VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
