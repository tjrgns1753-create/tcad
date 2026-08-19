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

That official example only runs in **3D** (a GDS-mask cantilever
release), and `direction100`/`direction010` above encode a specific
crystal-frame orientation *relative to the simulation axes*. Copying
them verbatim into a 2D simulation is NOT orientation-preserving, and
does real damage — see the next section.

--------------------------------------------------------------------
2D crystal-frame orientation: why `KOH_30PCT_70C`'s own vectors are
degenerate here, and what `KOH_30PCT_70C_2D` fixes
--------------------------------------------------------------------

`psWetEtching.hpp`'s rate formula (fetched verbatim from
github.com/ViennaTools/ViennaPS, not guessed) builds an orthonormal
crystal basis and projects the local surface normal onto it:

    directions[0] = normalize(direction100)
    directions[1] = direction010 orthogonalized against directions[0]
    directions[2] = cross(directions[0], directions[1])
    N[i] = |dot(directions[i], normal)|, then sorted DESCENDING
    if -N0 + N1 + 2*N2 < 0:
        v = (r100*(N0-N1-2*N2) + r110*(N1-N2) + 3*r311*N2) / N0
    else:
        v = (r111*((N1-N0)*0.5 + N2) + r110*(N1-N2) + 1.5*r311*(N0-N1)) / N0

With the 3D example's vectors, `directions[2]` comes out as
**(0, 0, 1)** — the z axis. This project is 2D, so every surface normal
has `normal[2] == 0`, which forces `N2 == 0` identically. Working the
algebra through with `N2 = 0` removes `r111` from the reachable branch
and multiplies `r311` by zero: **`rate111` and `rate311` become
mathematically inert for every possible 2D surface normal**, and the
velocity minimum degenerates to `rate100` (0.797 um/min) at 45°. In
other words the model stops being crystallographic at all — there is no
slow (111) facet anywhere, so a self-limiting V-groove is not merely
unachieved, it is unrepresentable.

Confirmed behaviourally against real ViennaPS 4.6.2, not just on paper:
multiplying `rate111` by 159x (up to `rate100`'s own magnitude) leaves
the exported Si area **bit-identical** (delta = 0.000e+00).

`KOH_30PCT_70C_2D` below uses the same real cited rate constants with a
crystal frame derived for this project's own 2D axes (x lateral, y
depth). Parametrizing a rotation by theta about the lateral axis as
`direction100 = [cos t, 0, sin t]`, `direction010 = [sin t, 0, -cos t]`
keeps `directions[2]` on the y (depth) axis for any theta, and solving
for when the magic-angle condition `N0 == N1 == N2` is reachable at all
picks out **theta = 45° uniquely**; at that theta the condition reduces
to exactly 54.7356° from horizontal — the real Si (111)/(100) angle
falling out of the algebra rather than being fitted. Evaluating the
formula above with these vectors gives `v = 0.0050 um/min` at the magic
angle, i.e. **exactly `rate111`**, and `rate111` becomes behaviourally
LIVE (same 159x test now shifts the Si area by 2.56e-02).

**Honest scope limit — read before trusting this for real process
design.** Fixing the crystal frame makes the (111) plane expressible
and is strictly more correct, but it does NOT yield a self-limiting
V-groove — and this is now ROOT-CAUSED, not just observed, with the
cause located precisely enough to know it cannot be fixed at this
project's own layer (recipe, frame, grid, scheme, or geometry).

The velocity field itself is correct: evaluating this module's own
rate formula (below) with `KOH_30PCT_70C_2D`'s frame gives exactly
`rate111` at a (111)-oriented surface (54.7356° from horizontal), and
the field's true velocity MINIMUM over all 2D tilts sits at 54.7400° —
0.005° from the real Si magic angle. The failure is at the CORNER: a
V-groove's apex has outward normal (0, 1, 0) by symmetry, at ANY
resolution — that is not a meshing choice, it follows from the groove
being symmetric about its centre — and evaluating the formula at that
exact normal gives **exactly `rate100`, 159x `rate111`**. So the one
point that must stop moving for the groove to close is the FASTEST
-moving point on the entire profile. Measured directly (real ViennaPS
4.6.2, a V-notch pre-carved to the exact ideal apex depth and magic
angle before any etch runs): the apex advances at ~100-145x `rate111`
(~0.6-0.85x `rate100`) from the very first timestep, while the
sidewall angle simultaneously reads 54.50° at R²=0.9998 (i.e. the
facet itself is genuinely present and correctly oriented — this is not
a mesh artifact corrupting the facet). Confirmed grid-INDEPENDENT
across a 4x refinement (0.68/0.78/0.75x `rate100` at gridDelta
0.2/0.1/0.05 um), which rules out apex rounding as the explanation.

Root cause, stated generally: `v(tilt)` is strongly NON-CONVEX (a deep
minimum at 54.74° rising to `rate110` at 90° and `rate100` at 0°), and
plain normal-velocity level-set advection (what `vps.Process()` runs)
moves every interface point using only ITS OWN local normal — so a
concave corner sitting between two slow facets is governed by neither
of them. Correct behaviour needs a Wulff/Frank convexification inside
the advection library itself, which is unreachable from any choice
available here. This single mechanism also explains every earlier
-recorded, previously-separate observation: why none of ViennaLS's 12
spatial schemes helped, why grid refinement never helped, and why the
facet angle wanders when starting from a flat mask window (it was never
anchored in the first place — the apex was always racing ahead at
`rate100` even while a sidewall looked briefly correct). An earlier
explanation recorded here — that mask-edge undercut from an initially
-vertical wall was the cause — was tested directly and refuted: even
starting a groove already carved to the exact magic-angle facet from
t=0, with no initial vertical wall to undercut at all, depth still
grows at an unchanged, non-decelerating rate (2.00 -> 2.60 -> 2.89 ->
3.32 um at t=60/120/150/180s for a window whose self-limited apex
should sit at 1.4142 um).

Treat this model as *anisotropic, genuinely (111)-aware* — not as
validated self-limiting KOH/TMAH physics, and not fixable into one by
any change at this project's layer. Full derivation, all measured
numbers, and the analytical velocity-vs-tilt table: search
`docs/investigation_log.md` for "the apex normal evaluates to
rate100".
"""

from __future__ import annotations

import math
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

#: theta = 45 degrees: the analytically unique crystal-frame rotation
#: (about this project's lateral axis) that BOTH keeps
#: `cross(direction100, direction010)` on the 2D depth axis AND makes the
#: magic-angle condition N0 == N1 == N2 reachable. See the module
#: docstring's "2D crystal-frame orientation" section for the derivation.
_THETA_2D_RAD = math.radians(45.0)

#: Same real, cited 30% KOH / 70C rate constants as `KOH_30PCT_70C`, but
#: with a crystal frame valid for this project's 2D axes. Prefer this in
#: 2D recipes: with `KOH_30PCT_70C`'s own (3D-provenance) vectors,
#: `rate111`/`rate311` are provably inert and no (111) facet exists at
#: all. Note the module docstring's scope limit: this makes the (111)
#: plane expressible, it does NOT deliver validated self-limiting
#: V-groove physics.
KOH_30PCT_70C_2D: Dict[str, Any] = {
    "direction100": [math.cos(_THETA_2D_RAD), 0.0, math.sin(_THETA_2D_RAD)],
    "direction010": [math.sin(_THETA_2D_RAD), 0.0, -math.cos(_THETA_2D_RAD)],
    "rate100": KOH_30PCT_70C["rate100"],
    "rate110": KOH_30PCT_70C["rate110"],
    "rate111": KOH_30PCT_70C["rate111"],
    "rate311": KOH_30PCT_70C["rate311"],
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

        process = module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        )

        # Optional ViennaLS spatial (advection) scheme, by enum member
        # name, e.g. "STENCIL_LOCAL_LAX_FRIEDRICHS_1ST_ORDER" -- which is
        # what ViennaPS's own cantileverWetEtching.py example sets. Absent,
        # ViennaLS's default (ENGQUIST_OSHER_1ST_ORDER) is left in place,
        # so every existing recipe behaves exactly as before.
        #
        # Measured, so callers know what this does and does not buy them:
        # the scheme visibly changes the facet angle the etch settles on,
        # but NO scheme produces a self-limiting V-groove (all 12 tested)
        # -- see the module docstring's scope limit.
        if "spatial_scheme" in recipe:
            import viennals as vls

            params = module.AdvectionParameters()
            params.spatialScheme = getattr(
                vls.SpatialSchemeEnum, recipe["spatial_scheme"]
            )
            process.setParameters(params)

        process.apply()

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
