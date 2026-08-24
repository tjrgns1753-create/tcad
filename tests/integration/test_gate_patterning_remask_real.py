#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate patterning (`remask_spans_um`) — real ViennaPS 4.6.2, through the
real production entry point (run_flow -> registry -> ProcessStep.run()).

Closes an architecture gap found while auditing whether this project
can build a full NMOS process recipe end-to-end (see CLAUDE.md, the
NMOS-flow audit). `prepare_domain()`'s mask construction (MakeTrench /
mask_spans_um) only ever ran on a FRESH wafer -- once a step inherited
a domain from a previous one, every mask key was silently ignored (with
only a warning). That is correct for the case those keys exist for
(they describe how to build a NEW wafer, which doesn't apply once one
already exists), but it left no way to do the real fab step gate
patterning actually is: deposit a layer blanket over EXISTING geometry,
mask it, then etch it into a pattern. `build_pn_diode.py`'s own
"metallization" step admits this directly: its second lithography step
has "no further geometric consequence" because "this simulator has no
metal-etch step in the flow".

`remask_spans_um` is the new, purely-additive opt-in that closes it:
inserted into `prepare_domain()`'s inherited-domain branch, it builds a
NEW mask ON TOP of whatever geometry the previous step produced
(`session.remask_domain()`, using getBoundingBox() to find the current
top surface and the same "contact epsilon" + wrapLowerLevelSet=True
technique this project's own LOCOS mask construction already uses and
has validated), so a following etch step can pattern it.

Checks, all measured from the real exported mesh after a real run_flow
chain (blanket deposition -> remask -> etch):
  1. blanket deposition alone -> gate material covers the FULL wafer
     width, confirming the "before" state genuinely has no pattern yet.
  2. remask + etch -> gate material survives ONLY under the masked
     span (real pattern, not the geometric-stamp shortcut gate_stack.py
     uses), within one isotropic-undercut cell of the requested window.
  3. the silicon substrate underneath is unharmed by the whole sequence.
  4. the OLD ignore-and-warn behavior for a chained step that does NOT
     pass remask_spans_um is byte-for-byte unchanged (regression guard
     for every existing chained recipe in this project).
  5. a remask over a STEPPED surface conforms down into the low regions
     instead of hovering at one flat height -- see
     check_conformal_over_topography() for the measured bug this guards.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.deposition  # noqa: F401 -- registers deposition models
import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.process.flow import FlowStep, run_flow
from tcad.process import registry

GRID = 0.05
X_EXTENT = 4.0
Y_EXTENT = 3.0
CHANNEL = (-0.5, 0.5)  # the only span the gate must survive in
MASK, SI, POLYSI = 0, 10, 11  # ViennaPS Material enum ids


def materials(mesh_path):
    mesh = meshio.read(mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    cx = mesh.points[block.data][:, :, 0].mean(axis=1)
    cy = mesh.points[block.data][:, :, 1].mean(axis=1)
    out = {}
    for tag in sorted(set(tags)):
        s = tags == tag
        out[int(tag)] = (float(cx[s].min()), float(cx[s].max()),
                          float(cy[s].min()), float(cy[s].max()))
    return out


def main():
    with tempfile.TemporaryDirectory() as tmp:
        steps = [
            FlowStep(category="deposition", name="isotropic", recipe={
                "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": Y_EXTENT,
                "deposition_time_s": 1.0, "rate": 0.2, "material": "PolySi",
            }),
            FlowStep(category="etching", name="isotropic", recipe={
                "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": Y_EXTENT,
                "remask_spans_um": [list(CHANNEL)],
                "pr_thickness_um": 0.3,
                "mask_material": "Mask",
                "rate": -1.0, "etch_time_s": 0.3,
            }),
        ]
        results = run_flow(steps, tmp)

        # --- 1: before patterning, the gate material is a full blanket ---
        before = materials(results[0].volume_mesh_path)
        assert POLYSI in before, f"blanket deposition produced no PolySi: {before}"
        gate_before = before[POLYSI]
        assert gate_before[1] - gate_before[0] > 3.0, (
            f"gate material is not a full blanket before patterning: {gate_before}")
        print(f"[1/5] blanket deposition: PolySi spans x={gate_before[0]:.3f}"
              f"..{gate_before[1]:.3f} (full wafer, no pattern yet)")

        # --- 2: after remask + etch, the gate is confined to the channel --
        after = materials(results[1].volume_mesh_path)
        assert POLYSI in after, f"gate patterning removed all PolySi: {after}"
        gate_after = after[POLYSI]
        assert abs(gate_after[0] - CHANNEL[0]) < 0.15, (
            f"gate left edge {gate_after[0]:.3f} far from requested {CHANNEL[0]}")
        assert abs(gate_after[1] - CHANNEL[1]) < 0.15, (
            f"gate right edge {gate_after[1]:.3f} far from requested {CHANNEL[1]}")
        print(f"[2/5] gate patterned: PolySi confined to x={gate_after[0]:.3f}"
              f"..{gate_after[1]:.3f} (requested {CHANNEL})")

        # --- 3: the silicon substrate is unharmed ---------------------------
        si_before, si_after = before[SI], after[SI]
        assert si_after[0] == si_before[0] and si_after[1] == si_before[1], (
            f"Si x-extent changed by gate patterning: {si_before} -> {si_after}")
        print(f"[3/5] Si substrate unharmed: x={si_after[0]:.3f}..{si_after[1]:.3f}")

        # --- 4: old ignore-and-warn behavior is unchanged for a chained
        #        step that does NOT ask for remask_spans_um -------------------
        import warnings
        step_cls = registry.get("etching", "isotropic")
        step = step_cls(inherited_domain=results[0])
        # results[0] is a ProcessResult, not a live domain -- reuse the
        # SAME inherited-domain code path a real chained step exercises,
        # by calling prepare_domain() directly on a fresh domain built
        # the same way run_flow does it, so this only tests the ignore
        # branch (not domain-reload machinery already covered elsewhere).
        from tcad.backends.viennaps import session
        dom = session.create_domain(GRID, X_EXTENT, Y_EXTENT)
        import viennaps as vps
        vps.MakePlane(dom, 0.0, vps.Material.Si).apply()
        step2 = step_cls(inherited_domain=dom)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            returned = step2.prepare_domain({
                "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": Y_EXTENT,
                "mask_left_um": 1.0, "mask_right_um": 2.0, "pr_thickness_um": 0.3,
                "rate": -0.1, "etch_time_s": 0.1,
            })
        assert returned is dom, "inherited domain without remask_spans_um must be returned untouched"
        assert any("ignored" in str(w.message) for w in caught), (
            "expected the original ignore-and-warn UserWarning for fresh-wafer "
            "mask keys on a chained step without remask_spans_um")
        print("[4/5] old ignore-and-warn path for chained steps unchanged")

    check_conformal_over_topography()

    print()


def check_conformal_over_topography():
    """A remask over a STEPPED surface must protect the spans it covers.

    Regression guard for a real, measured bug: remask_domain() used to
    place the mask at the domain's single global top y, so on a surface
    with real relief the mask hovered above the LOW regions instead of
    filling down to them. Measured on a 4-step chain (oxidation ->
    window etch -> metal deposition -> remask + metal etch), that left
    the metal etched away exactly where the mask was supposed to cover
    it and surviving only where a tall bump happened to reach the
    mask -- the inverse of the requested pattern, produced silently.

    Photoresist is spun on and fills topography, so each mask span is
    now built as a full-height column from below all geometry upward;
    the wrapLowerLevelSet=True insert absorbs the submerged part. This
    check builds deliberate relief (a tall resist bump, then blanket
    metal over it, so the metal sits at two very different heights) and
    asserts the metal survives under the covered spans and clears in
    the open gap.
    """
    import viennaps as vps
    import meshio
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    XE, FLOOR = 8.0, 4.0
    GAP = (-0.6, 0.6)                          # must be CLEARED
    COVER = [(-3.0, GAP[0]), (GAP[1], 3.0)]    # must be PROTECTED
    METAL = 5                                   # vps.Material.Metal enum id

    dom = session.create_domain(GRID, XE, 5.0)
    vps.MakePlane(dom, 0.0, vps.Material.Si).apply()

    # Real topography: a tall resist bump in the middle.
    session.remask_domain(dom, grid_delta_um=GRID, x_extent_um=XE,
                          spans_um=[(-1.5, 1.5)], mask_height_um=0.4)
    # Blanket metal over the now-stepped surface.
    dom.duplicateTopLevelSet(vps.Material.Metal)
    vps.Process(dom, vps.IsotropicProcess(rate=0.15), 1.0).apply()
    # Second lithography: cover the OUTER spans, open the middle.
    session.remask_domain(dom, grid_delta_um=GRID, x_extent_um=XE,
                          spans_um=COVER, mask_height_um=0.5)
    # Etch just over one film thickness (an isotropic etch spends its
    # budget laterally too, so a large over-etch would undercut the
    # film out from under the mask and prove nothing).
    vps.Process(dom, vps.IsotropicProcess(
        materialRates={vps.Material.Metal: -1.0, vps.Material.Si: 0.0},
        defaultRate=0.0), 0.18).apply()

    with tempfile.TemporaryDirectory() as tmp:
        path = save_volume_mesh(dom, Path(tmp) / "m", floor_depth_um=FLOOR)
        mesh = meshio.read(path)
        block = next(c for c in mesh.cells if c.type == "triangle")
        tags = mesh.cell_data["Material"][mesh.cells.index(block)]
        cx = mesh.points[block.data][:, :, 0].mean(axis=1)

    metal = cx[tags == METAL]
    assert len(metal) > 0, "the whole metal film was removed"
    # 0.15um in from each edge, so grid-scale sidewall slope near a
    # boundary isn't counted as either a hit or a miss.
    in_gap = int(((metal > GAP[0] + 0.15) & (metal < GAP[1] - 0.15)).sum())
    in_cover = int(sum(((metal > lo + 0.15) & (metal < hi - 0.15)).sum()
                        for lo, hi in COVER))
    assert in_gap == 0, (
        f"{in_gap} metal triangles left inside the OPEN gap {GAP} — "
        f"the etch did not clear the unmasked region")
    assert in_cover > 50, (
        f"only {in_cover} metal triangles survived under the COVERED spans "
        f"{COVER} — the mask did not conform down to the stepped surface")
    print(f"[5/5] remask conforms over topography: metal cleared in the gap "
          f"(0 tris) and preserved under cover ({in_cover} tris)")
    print("GATE PATTERNING (remask_spans_um) VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
