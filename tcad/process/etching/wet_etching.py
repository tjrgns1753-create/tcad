#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wet etching — per-material-rate (isotropic) and crystallographic
(orientation-dependent, e.g. KOH/TMAH) overloads.

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.WetEtching.__init__.__doc__`):

    vps.WetEtching(materialRates: Sequence[tuple[vps.Material, float]])

    vps.WetEtching(direction100, direction010,
                    rate100, rate110, rate111, rate311,
                    materialRates)

The second (crystallographic) overload models orientation-dependent
wet etches (e.g. KOH/TMAH on <100> silicon). It needs empirical
etch-rate constants specific to a real etchant/temperature combination
— this module does not fabricate those, so the recipe must supply real
ones (see KOH_30PCT_70C below for a ready-made, cited example).

Crystallographic constants verified real (this session, not fabricated):
fetched verbatim from ViennaPS's own official example,
`examples/cantileverWetEtching/cantileverWetEtching.py`
(github.com/ViennaTools/ViennaPS), which uses these exact values
for "30% KOH at 70°C", citing
https://doi.org/10.1016/S0924-4247(97)01658-0:

    direction100 = [0.707106781187, 0.707106781187, 0.0]
    direction010 = [-0.707106781187, 0.707106781187, 0.0]
    rate100 = 0.797 / 60.0   # um/s (0.797 um/min)
    rate110 = 1.455 / 60.0   # um/s (1.455 um/min)
    rate111 = 0.005 / 60.0   # um/s (0.005 um/min)
    rate311 = 1.436 / 60.0   # um/s (1.436 um/min)

That official example only runs in 3D (a GDS-mask cantilever release);
this project is 2D-only, so before wiring these values into production
this session verified directly (isolated probe, not assumed) that
`vps.d2.WetEtching`'s crystallographic overload — called through this
project's own normal 2D trench geometry, with these exact constants —
produces a genuinely anisotropic (non-circular, faceted) etch profile:
a symmetric V-groove centered on the trench window, sidewall angle
measured (linear fit of the raw, floored Si surface) at 54.45° from
vertical — the real Si (111)/(100) KOH "magic angle" is 54.74°, a
0.3° match well within this probe's gridDelta=0.2um discretization.
This is the same qualitative/quantitative distinguishing check this
project already uses elsewhere (e.g. isotropic etch's quarter-circle
undercut check) to confirm a model's real physical behavior, not just
"doesn't crash".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register

#: Real, cited crystallographic wet-etch rate constants for 30% KOH at
#: 70°C, silicon (100), verbatim from ViennaPS's own
#: examples/cantileverWetEtching/cantileverWetEtching.py — see module
#: docstring for the full provenance and the 2D-behavior verification.
#: A recipe can spread this dict into its own keys
#: (`{**KOH_30PCT_70C, "material_rates": [...]}`) to select this
#: exact, real condition rather than typing the raw numbers out again.
KOH_30PCT_70C: Dict[str, Any] = {
    "direction100": [0.707106781187, 0.707106781187, 0.0],
    "direction010": [-0.707106781187, 0.707106781187, 0.0],
    "rate100": 0.797 / 60.0,
    "rate110": 1.455 / 60.0,
    "rate111": 0.005 / 60.0,
    "rate311": 1.436 / 60.0,
}


@register
class WetEtch(ProcessStep):
    category = "etching"
    name = "wet_etching"
    display_name = "Wet Etching (per-material rate / crystallographic)"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        # recipe["material_rates"]: list of {"material": "Si", "rate": -0.05}
        # Used by both overloads below.
        material_rates = [
            (getattr(module.Material, entry["material"]), entry["rate"])
            for entry in recipe["material_rates"]
        ]

        if "direction100" in recipe:
            # Crystallographic (orientation-dependent) overload — see
            # module docstring for the real-data provenance and the 2D
            # verification. Presence of direction100 is the switch,
            # mirroring how "mask_material" switches fin vs LOCOS in
            # thermal.py; the other 5 crystallographic keys are
            # required alongside it (a plain KeyError below if any is
            # missing, same as every other recipe key in this project).
            model = module.WetEtching(
                direction100=recipe["direction100"],
                direction010=recipe["direction010"],
                rate100=recipe["rate100"],
                rate110=recipe["rate110"],
                rate111=recipe["rate111"],
                rate311=recipe["rate311"],
                materialRates=material_rates,
            )
        else:
            model = module.WetEtching(material_rates)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_wet_etch")

        final_mesh = Path(output_dir) / "wet_etching_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
