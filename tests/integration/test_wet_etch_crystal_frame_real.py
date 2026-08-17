#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crystallographic wet etching — is the (111) plane EXPRESSIBLE at all?
Real ViennaPS 4.6.2, through the real production entry point.

This guards the one thing about this project's KOH wiring that is
provable rather than approximate, and that was silently wrong before:

`psWetEtching.hpp` projects the local surface normal onto a crystal
basis whose third axis is `cross(direction100, direction010)`. With the
vectors in `KOH_30PCT_70C` -- copied verbatim from ViennaPS's own
official *3D* cantileverWetEtching.py example -- that third axis lands
on **z**. Every normal in a 2D simulation has `normal[2] == 0`, so the
corresponding projection `N2` is identically zero, which algebraically
removes `rate111` from the reachable branch of the rate formula and
multiplies `rate311` by zero. The model degenerates: no slow (111)
facet exists anywhere, so crystallographic self-limiting is not merely
unachieved but unrepresentable.

`KOH_30PCT_70C_2D` uses the same real cited rate constants with a
crystal frame derived for this project's own 2D axes (see
wet_etching.py's module docstring for the derivation and for the honest
scope limit -- this makes (111) expressible, it does NOT deliver
validated self-limiting V-groove physics).

The test is a behavioural discriminator, not a re-implementation of the
library's formula: scale `rate111` up by ~159x (to `rate100`'s own
magnitude) and compare the exported Si area.

  - degenerate frame  -> area must be BIT-IDENTICAL (rate111 inert)
  - corrected 2D frame -> area must CHANGE        (rate111 live)

Deterministic and cheap (t=30 s, gridDelta 0.2 um). No fabricated
constants: the rate values are the cited real ones, and the comparison
is against the model's own output, not a target number.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session
from tcad.process import registry
from tcad.process.etching.wet_etching import KOH_30PCT_70C, KOH_30PCT_70C_2D

assert session.is_available(), "ViennaPS must be installed for this test"

BASE_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 6.0,
    "y_extent_um": 3.0,
    "mask_left_um": 2.0,
    "mask_right_um": 4.0,
    "pr_thickness_um": 0.3,
    "etch_time_s": 30.0,
    "material_rates": [{"material": "Si", "rate": -1.0}],
}


def si_area(recipe, module):
    """Total exported Si area -- a single scalar summarising the whole
    etched geometry, read from the real written mesh."""
    with tempfile.TemporaryDirectory() as tmp:
        result = registry.get("etching", "wet_etching")().run(dict(recipe), tmp)
        mesh = meshio.read(result["final_mesh"])
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    si_tag = int(module.Material.Si)
    area = 0.0
    for tri, tag in zip(block.data, tags):
        if int(tag) != si_tag:
            continue
        a, b, c = (mesh.points[i][:2] for i in tri)
        area += abs((b[0] - a[0]) * (c[1] - a[1])
                    - (c[0] - a[0]) * (b[1] - a[1])) / 2.0
    return area


def main():
    module = session.require_viennaps()

    # rate100 is ~159x rate111 for this real etchant condition, so this
    # is an enormous perturbation -- an inert parameter is the only way
    # the result can come back unchanged.
    boosted = KOH_30PCT_70C["rate100"]

    # 1/2: the 3D-provenance frame must be degenerate in 2D.
    degenerate = {**BASE_RECIPE, **KOH_30PCT_70C}
    area_nom = si_area(degenerate, module)
    area_big = si_area({**degenerate, "rate111": boosted}, module)
    print(f"[1/2] KOH_30PCT_70C (3D-provenance frame): "
          f"Si area {area_nom:.8f} -> {area_big:.8f} "
          f"when rate111 is scaled {boosted / KOH_30PCT_70C['rate111']:.0f}x")
    assert area_nom == area_big, (
        "expected rate111 to be provably INERT with the 3D-provenance "
        "crystal frame in 2D (cross(d100,d010) lands on z, forcing N2==0), "
        f"but the Si area moved by {abs(area_nom - area_big):.3e}. If "
        "ViennaPS changed its rate formula or basis construction, "
        "wet_etching.py's module docstring needs re-deriving."
    )

    # 2/2: the derived 2D frame must make rate111 actually do something.
    corrected = {**BASE_RECIPE, **KOH_30PCT_70C_2D}
    area_nom_2d = si_area(corrected, module)
    area_big_2d = si_area({**corrected, "rate111": boosted}, module)
    delta = abs(area_nom_2d - area_big_2d)
    print(f"[2/2] KOH_30PCT_70C_2D (derived 2D frame):   "
          f"Si area {area_nom_2d:.8f} -> {area_big_2d:.8f}  |delta|={delta:.3e}")
    assert delta > 1e-6, (
        "expected rate111 to be LIVE with the derived 2D crystal frame "
        "(the whole point of KOH_30PCT_70C_2D), but scaling it "
        f"{boosted / KOH_30PCT_70C['rate111']:.0f}x changed the Si area by "
        f"only {delta:.3e} -- the (111) plane is still not expressible."
    )

    print()
    print("CRYSTAL-FRAME FIX VERIFIED AGAINST REAL VIENNAPS 4.6.2: "
          "the (111) plane is inert under the 3D-provenance frame and "
          "live under the derived 2D frame")


if __name__ == "__main__":
    main()
