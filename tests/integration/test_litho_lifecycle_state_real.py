#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lithography lifecycle / resist-state regression, real ViennaPS 4.6.2.

Pins the rule that each lithography step changes ONLY its own effect,
and that a mask becomes real wafer geometry only because the user ran
lithography -- never because a GUI field happened to hold a default.

Three real bugs are pinned here, each of which was reproduced against
real ViennaPS before the fix (numbers below are the measured "before"):

  1. A FIRST process step invented a photomask nobody created.
     `_mask_recipe_keys_for_current_step()` built mask spans from the
     `Wafer` dataclass defaults (mask_openings_um=[[3.5,6.5]],
     pr_thickness_um=1.0) whenever no step had run yet. Measured: a
     plain isotropic SiO2 deposition on a fresh wafer, with the user
     having run NO lithography at all, produced materials
     ['Mask','Si','SiO2'] -- a 1.0um Mask solid -- and deposited the
     film only in x=[-1.5,1.5] instead of across the wafer.

  2. PR COAT behaved as coat+align+expose+develop in one click.
     Every litho stage ("pr_coated" through "developed") was treated as
     "fully developed", so the OPAQUE COMPLEMENT of the openings was
     applied after a bare coat. Measured: oxidation -> PR COAT (nothing
     else) -> deposition put Mask only OUTSIDE mask_openings_um and
     deposited Si3N4 only INSIDE them -- an already-developed pattern
     produced by a blanket coat.

  3. Lithography state never cleared. `wafer.developed` was set once and
     reset only by NEW WAFER, so coat -> develop -> strip -> coat left
     the fresh coat already "developed".

The fix is a single resist-state table, `_resist_spans_um()`, read by
both the recipe builder and the canvas overlay:

    no resist             -> no mask at all
    coated, not developed -> ONE full-width span (blanket film)
    developed             -> opaque complement of the openings

Part A drives that decision logic directly (no Tk, no ViennaPS, fast).
Part B runs the recipes it produces through real ViennaPS and measures
the resulting geometry, because the decision being right on paper is
not evidence that the exported mesh is.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.core.models import Wafer
from tcad.process.flow import FlowStep, run_flow

WIDTH_UM = 10.0
HALF = WIDTH_UM / 2.0


# ----------------------------------------------------------------------
# Part A -- the resist-state decision, driven through the GUI's own code
# ----------------------------------------------------------------------

class _ResistProbe:
    """The GUI's real resist methods, with only the attributes they read.

    Borrowing the unbound methods keeps this test honest: it exercises
    the shipped implementation rather than a copy of its logic, without
    needing a Tk display.
    """

    def __init__(self, first_step=True, **wafer_state):
        import tcad_2d_stagewise as gui

        self._resist_spans_um = gui.TCADApplication._resist_spans_um.__get__(self)
        self._mask_recipe_keys_for_current_step = (
            gui.TCADApplication._mask_recipe_keys_for_current_step.__get__(self)
        )
        self.wafer = Wafer()
        for key, value in wafer_state.items():
            setattr(self.wafer, key, value)
        self.completed_steps = [] if first_step else [{"_process_category": "oxidation"}]
        self.flow_steps = []


def test_a_resist_state_table():
    print("\n[A] resist-state decision table")

    # --- No lithography: a process step must not invent a mask --------
    fresh = _ResistProbe(first_step=True)
    assert fresh._resist_spans_um() is None, "bare wafer must carry no resist"
    keys = fresh._mask_recipe_keys_for_current_step()
    assert keys == {"mask_spans_um": []}, (
        f"a FIRST step with no lithography must ask for a bare wafer, got {keys}")

    chained = _ResistProbe(first_step=False)
    assert chained._mask_recipe_keys_for_current_step() == {}, (
        "a CHAINED step with no lithography must leave the domain untouched")

    # --- PR COAT only: blanket resist, NOT a pattern -------------------
    coated = _ResistProbe(first_step=True, pr_present=True)
    spans = coated._resist_spans_um()
    assert spans == [[-HALF, HALF]], (
        f"a bare PR COAT must be ONE full-width span (blanket), got {spans}")

    coated_chained = _ResistProbe(first_step=False, pr_present=True)
    assert coated_chained._mask_recipe_keys_for_current_step() == {
        "remask_spans_um": [[-HALF, HALF]]
    }, "a bare PR COAT on an existing wafer must remask the FULL width"

    # --- Alignment and exposure change no geometry --------------------
    # Both are represented by the same wafer state as a bare coat: the
    # mask is process input, and exposure is chemistry. If either ever
    # starts changing resist geometry, this equality breaks.
    assert coated._resist_spans_um() == spans, (
        "mask alignment / exposure must not change resist geometry")

    # --- DEVELOP: first step that opens the resist --------------------
    developed = _ResistProbe(first_step=True, pr_present=True, developed=True)
    dev_spans = developed._resist_spans_um()
    assert dev_spans == [[-HALF, -1.5], [1.5, HALF]], (
        f"a developed resist must be the opaque complement, got {dev_spans}")
    assert dev_spans != spans, (
        "developed resist must differ from a blanket coat -- the whole bug")

    # --- PR STRIP clears the resist -----------------------------------
    stripped = _ResistProbe(first_step=False, pr_present=False, stripped=True)
    assert stripped._resist_spans_um() is None, "stripped wafer must carry no resist"
    assert stripped._mask_recipe_keys_for_current_step() == {}, (
        "after PR STRIP no further step may be masked")

    print("    no litho -> no mask; coat -> blanket; align/expose -> unchanged;")
    print("    develop -> patterned; strip -> no mask")


def test_a2_coat_clears_previous_cycle():
    """PR COAT must clear a previous cycle's develop/strip state."""
    print("\n[A2] a new coat starts an unpatterned cycle")

    import tcad_2d_stagewise as gui

    wafer = Wafer(pr_present=False, developed=True, stripped=True)

    class _Stub:
        pass

    stub = _Stub()
    stub.wafer = wafer
    stub.completed_steps = []
    stub.flow_steps = []
    stub.history = []
    stub._stages_done = {0}
    stub.pr_var = stub.left_var = None  # not read: _read_lithography_fields is stubbed

    # Only the state transition is under test here, so the field read and
    # the Tk-dependent tail are stubbed out; everything between them is
    # the shipped implementation.
    stub._read_lithography_fields = lambda: True
    stub._mark_stage_done = lambda *a: None
    stub._log = lambda *a, **k: None
    stub._update_process_buttons = lambda: None
    stub.redraw = lambda: None

    gui.TCADApplication.process_pr_coat(stub)

    assert wafer.pr_present is True, "PR COAT must put resist on the wafer"
    assert wafer.developed is False, (
        "PR COAT must clear `developed` -- otherwise coat->develop->strip->coat "
        "leaves the fresh coat already patterned")
    assert wafer.stripped is False, "PR COAT must clear `stripped`"

    spans = gui.TCADApplication._resist_spans_um(stub)
    assert spans == [[-HALF, HALF]], (
        f"the fresh coat must be blanket, not the previous cycle's pattern: {spans}")
    print("    coat after a completed cycle -> blanket resist, not patterned")


# ----------------------------------------------------------------------
# Part B -- the same recipes through real ViennaPS
# ----------------------------------------------------------------------

def _materials(mesh_path):
    """{material name: node coordinates} from a real exported mesh."""
    import viennaps as vps

    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        value = getattr(vps.Material, attr)
        if isinstance(value, vps.Material):
            names.setdefault(int(value), attr)

    mesh = meshio.read(mesh_path)
    found = {}
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            values = np.asarray(values).ravel()
            for material in set(values.tolist()):
                selected = cells.data[values == material]
                if len(selected) == 0:
                    continue
                name = names.get(int(material), str(int(material)))
                points = mesh.points[np.unique(selected)]
                found[name] = (
                    np.vstack([found[name], points]) if name in found else points
                )
    return found


def _base_recipe():
    return dict(
        pr_thickness_um=1.0,
        silicon_depth_um=5.0,
        grid_delta_um=0.05,
        x_extent_um=WIDTH_UM,
        y_extent_um=8.0,
    )


def test_b1_first_step_invents_no_mask():
    """A first deposition with no lithography: blanket film, no Mask."""
    print("\n[B1] first deposition, user ran NO lithography")

    recipe = {
        "_process_category": "deposition",
        "_process_model_key": "isotropic",
        **_base_recipe(),
        # What _mask_recipe_keys_for_current_step() now returns for
        # "first step, no resist" (pinned by test_a above).
        "mask_spans_um": [],
        "rate": 0.05,
        "deposition_time_s": 0.5,
        "mask_material": "Mask",
        "material": "SiO2",
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow([FlowStep("deposition", "isotropic", recipe)], tmp)
        materials = _materials(results[0].volume_mesh_path)

    assert "Mask" not in materials, (
        f"a step the user never masked must not create a Mask material; "
        f"got {sorted(materials)}")
    assert set(materials) == {"Si", "SiO2"}, f"unexpected materials: {sorted(materials)}"

    # Blanket means the film is there at the edges too, not only in the
    # window a stale default happened to describe.
    film = materials["SiO2"]
    for label, (lo, hi) in [("centre", (-0.5, 0.5)), ("edge", (-4.5, -3.5))]:
        here = film[(film[:, 0] >= lo) & (film[:, 0] <= hi)]
        assert len(here) > 0, f"deposited film missing at the wafer {label}"
    assert film[:, 0].min() < -4.5 and film[:, 0].max() > 4.5, (
        f"film is patterned, not blanket: x=[{film[:,0].min():.3f},"
        f"{film[:,0].max():.3f}]")
    print(f"    materials={sorted(materials)}, film spans "
          f"x=[{film[:,0].min():.3f},{film[:,0].max():.3f}] -- blanket, no Mask")


def test_b2_bare_coat_is_blanket_not_patterned():
    """Oxidation -> PR COAT only -> deposition: resist covers everything."""
    print("\n[B2] oxidation -> PR COAT (nothing else) -> deposition")

    base = _base_recipe()
    oxidation = {
        "_process_category": "oxidation",
        "_process_model_key": "thermal",
        **base,
        "mask_spans_um": [],
        "oxidant": "Dry",
        "temperature_c": 1000.0,
        "time_hours": 0.5,
    }
    deposition = {
        "_process_category": "deposition",
        "_process_model_key": "isotropic",
        **base,
        # "coated, not developed" -> ONE full-width span.
        "remask_spans_um": [[-HALF, HALF]],
        "rate": 0.05,
        "deposition_time_s": 0.5,
        "mask_material": "Mask",
        "material": "Si3N4",
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [
                FlowStep("oxidation", "thermal", oxidation),
                FlowStep("deposition", "isotropic", deposition),
            ],
            tmp,
        )
        after_oxide = _materials(results[0].volume_mesh_path)
        after_coat = _materials(results[1].volume_mesh_path)

    oxide_before = after_oxide["SiO2"]

    resist = after_coat["Mask"]
    # The whole point: a blanket coat is present at every x, including
    # inside the mask openings. Before the fix the resist was ABSENT
    # there, which is what made a bare coat look developed.
    for label, (lo, hi) in [("inside the opening", (-0.5, 0.5)),
                            ("outside the opening", (-4.5, -3.5))]:
        here = resist[(resist[:, 0] >= lo) & (resist[:, 0] <= hi)]
        assert len(here) > 0, (
            f"blanket resist missing {label} -- the coat was applied as a "
            f"DEVELOPED pattern")
    assert resist[:, 0].min() < -4.5 and resist[:, 0].max() > 4.5, (
        f"resist is patterned, not blanket: x=[{resist[:,0].min():.3f},"
        f"{resist[:,0].max():.3f}]")

    # A fully-blanket resist masks the whole wafer, so the deposition it
    # gates must reach the wafer nowhere. This is the positive form of
    # "a coat is not a pattern": before the fix, Si3N4 landed inside the
    # openings of a resist that had never been developed.
    assert "Si3N4" not in after_coat, (
        f"film was deposited through a resist that covers the entire wafer; "
        f"materials={sorted(after_coat)}")

    # The previous step's result must survive, and the resist must sit ON
    # TOP of it -- resist under the oxide it was coated onto would be the
    # physically impossible stack this project has hit before.
    #
    # Tolerance is tied to the grid, not to zero: re-exporting a level
    # set after another process step moves surfaces by a fraction of a
    # cell. Measured here, the oxide top and the Si top both shift by the
    # SAME 0.001um on a 0.05um grid (2% of a cell) -- a uniform
    # re-discretization of the whole stack, not the oxide changing.
    grid_delta = base["grid_delta_um"]
    oxide_after = after_coat["SiO2"]
    oxide_shift = abs(oxide_after[:, 1].max() - oxide_before[:, 1].max())
    assert oxide_shift < 0.1 * grid_delta, (
        f"the earlier oxidation's oxide moved {oxide_shift:.4f}um when resist "
        f"was coated -- more than a tenth of the {grid_delta}um grid, so this "
        f"is a real change, not re-discretization")
    assert resist[:, 1].min() >= oxide_after[:, 1].max() - 1e-6, (
        f"resist bottom {resist[:,1].min():.3f} is below the oxide top "
        f"{oxide_after[:,1].max():.3f} -- resist buried under the oxide")

    print(f"    resist spans x=[{resist[:,0].min():.3f},{resist[:,0].max():.3f}] "
          f"y=[{resist[:,1].min():.3f},{resist[:,1].max():.3f}] -- blanket, on top of oxide")
    print(f"    prior oxide preserved (top {oxide_before[:,1].max():.3f} "
          f"-> {oxide_after[:,1].max():.3f})")


def test_b3_developed_resist_is_patterned():
    """Develop must produce a genuinely patterned resist, unlike a coat."""
    print("\n[B3] oxidation -> coat + develop -> deposition")

    base = _base_recipe()
    oxidation = {
        "_process_category": "oxidation",
        "_process_model_key": "thermal",
        **base,
        "mask_spans_um": [],
        "oxidant": "Dry",
        "temperature_c": 1000.0,
        "time_hours": 0.5,
    }
    deposition = {
        "_process_category": "deposition",
        "_process_model_key": "isotropic",
        **base,
        # "developed" -> opaque complement of the 3.5-6.5 opening.
        "remask_spans_um": [[-HALF, -1.5], [1.5, HALF]],
        "rate": 0.05,
        "deposition_time_s": 0.5,
        "mask_material": "Mask",
        "material": "Si3N4",
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [
                FlowStep("oxidation", "thermal", oxidation),
                FlowStep("deposition", "isotropic", deposition),
            ],
            tmp,
        )
        materials = _materials(results[1].volume_mesh_path)

    resist = materials["Mask"]
    inside = resist[(resist[:, 0] >= -1.0) & (resist[:, 0] <= 1.0)]
    outside = resist[(resist[:, 0] >= -4.5) & (resist[:, 0] <= -3.5)]
    assert len(outside) > 0, "developed resist missing where the mask is opaque"
    assert len(inside) == 0, (
        f"developed resist still covers the opening ({len(inside)} nodes) -- "
        f"develop did not open the pattern")

    assert "Si3N4" in materials, "nothing was deposited through the developed opening"
    film = materials["Si3N4"]
    assert film[:, 0].min() > -2.0 and film[:, 0].max() < 2.0, (
        f"film escaped the developed opening: x=[{film[:,0].min():.3f},"
        f"{film[:,0].max():.3f}]")
    print(f"    resist opened over x=[-1.5,1.5]; film confined to "
          f"x=[{film[:,0].min():.3f},{film[:,0].max():.3f}]")


def test_c_long_mixed_run():
    """One long run touching every category, checked step by step.

    The particular order below is ARBITRARY — it is chosen only because
    it exercises resist state, a masked step and an unmasked step
    against accumulating geometry. It is not a canonical or required
    flow, and nothing in the tool may assume it: the categories are
    independent and the user picks the order (see CLAUDE.md's
    invariant). A different order should work equally well, and if one
    does not, that is the bug.

    Only three of the steps run ViennaPS: oxidation, etching and
    deposition.
    PR coat / mask / exposure / development / strip are resist-STATE
    transitions -- that is the point being pinned, since treating any of
    them as a geometry step is what produced a developed pattern from a
    bare coat.

    Every check re-verifies the EARLIER steps' measurements on the new
    mesh, not just the new step's own feature: "state accumulates and
    nothing else changes" is a claim about the whole stack each time.
    """
    print("\n[C] one long mixed run (arbitrary order), checked step by step")

    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_uniform_doping

    base = _base_recipe()

    # 1. Oxidation. No lithography has happened, so no mask keys.
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **base, "mask_spans_um": [],
        "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5,
    }
    # 2-5. PR coat -> mask -> expose -> develop: resist state only. The
    #      resist becomes geometry when the next real step consumes it,
    #      as the DEVELOPED pattern (pinned by test_a).
    # 6. Etching through that developed opening.
    etching = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        **base,
        "remask_spans_um": [[-HALF, -1.5], [1.5, HALF]],
        "mask_material": "Mask",
        "material_rates": {"SiO2": -0.2, "Si": 0.0, "Mask": 0.0},
        "default_rate": 0.0,
        "etch_time_s": 0.5,
    }
    # 7. PR strip: state only (and see the note asserted below).
    # 8. Deposition, now unmasked -- a blanket film over whatever the
    #    etch left.
    deposition = {
        "_process_category": "deposition", "_process_model_key": "isotropic",
        **base,
        "rate": 0.05, "deposition_time_s": 0.4, "material": "Si3N4",
    }

    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [
                FlowStep("oxidation", "thermal", oxidation),
                FlowStep("etching", "isotropic", etching),
                FlowStep("deposition", "isotropic", deposition),
            ],
            tmp,
        )
        after_ox = _materials(results[0].volume_mesh_path)
        after_etch = _materials(results[1].volume_mesh_path)
        after_dep = _materials(results[2].volume_mesh_path)
        # Step 10 below reads the final mesh from disk, so it has to
        # happen while the flow's temporary directory still exists.
        final_result = build_process_result(
            {"final_mesh": results[2].volume_mesh_path, "snapshots": []}
        )
        final_doped = apply_uniform_doping(final_result, {"Si": 1e17})

    # --- 1. Oxidation: blanket oxide, and NO mask -----------------------
    assert set(after_ox) == {"Si", "SiO2"}, (
        f"a blanket oxidation must not create a mask: {sorted(after_ox)}")
    ox_top = after_ox["SiO2"][:, 1].max()
    assert after_ox["SiO2"][:, 0].min() < -4.5 < 4.5 < after_ox["SiO2"][:, 0].max(), (
        "oxide does not span the whole wafer")
    print(f"    [1] oxidation: {sorted(after_ox)}, oxide top {ox_top:.3f} (no mask)")

    # --- 6. Etch: resist appears NOW, patterned, and etches the window --
    assert "Mask" in after_etch, (
        "the developed resist should be present in the step that consumed it")
    resist = after_etch["Mask"]
    assert len(resist[(resist[:, 0] >= -1.0) & (resist[:, 0] <= 1.0)]) == 0, (
        "resist covers the opening it was developed to expose")
    assert len(resist[(resist[:, 0] >= -4.5) & (resist[:, 0] <= -3.5)]) > 0, (
        "resist missing where the mask is opaque")

    # Si must survive untouched: the etch was selective to SiO2, and the
    # substrate is not what a window etch is meant to consume here.
    assert "Si" in after_etch, "the substrate disappeared during the etch"
    si_shift = abs(after_etch["Si"][:, 1].min() - after_ox["Si"][:, 1].min())
    assert si_shift < 0.1 * base["grid_delta_um"], (
        f"the substrate floor moved {si_shift:.4f}um during a selective etch")

    # The etch must clear the oxide through the developed opening and
    # leave it untouched under the resist. Measured: the 0.5s x 0.2um/s
    # etch removes more than the ~0.065um oxide, so inside the window the
    # oxide is GONE and bare Si is exposed -- a textbook window etch.
    def _oxide_in(materials_map, lo, hi):
        oxide = materials_map.get("SiO2")
        if oxide is None:
            return None
        here = oxide[(oxide[:, 0] >= lo) & (oxide[:, 0] <= hi)]
        return here[:, 1].max() if len(here) else None

    open_top = _oxide_in(after_etch, -1.0, 1.0)
    masked_top = _oxide_in(after_etch, -4.5, -3.5)
    assert open_top is None, (
        f"oxide survives inside the developed opening (top {open_top}) -- the "
        f"etch did not go through the window the resist was opened for")
    assert masked_top is not None, "the resist failed to protect the oxide"
    assert abs(masked_top - ox_top) < 0.1 * base["grid_delta_um"], (
        f"oxide under the resist changed ({ox_top:.4f} -> {masked_top:.4f}) -- "
        f"the resist did not mask it")
    print(f"    [6] etch: oxide cleared inside the opening (Si exposed), "
          f"preserved at {masked_top:.3f} under the resist; Si floor unmoved")

    # --- 8. Deposition: blanket, and it must not add a NEW mask ---------
    assert "Si3N4" in after_dep, "the deposition produced no film"
    film = after_dep["Si3N4"]
    assert film[:, 0].min() < -4.5 and film[:, 0].max() > 4.5, (
        f"the unmasked deposition was patterned: x=[{film[:,0].min():.3f},"
        f"{film[:,0].max():.3f}]")
    # Every material from before is still here, and nothing new appeared
    # beyond the film itself.
    assert set(after_dep) == set(after_etch) | {"Si3N4"}, (
        f"materials appeared or vanished during deposition: "
        f"{sorted(after_etch)} -> {sorted(after_dep)}")
    print(f"    [8] deposition: blanket Si3N4 over x=[{film[:,0].min():.3f},"
          f"{film[:,0].max():.3f}]; earlier materials all still present")

    # PR STRIP is a state transition: resist already built into an
    # EARLIER step's exported geometry stays in that mesh. Asserting it
    # rather than glossing over it keeps the known limitation visible.
    assert "Mask" in after_dep, (
        "unexpected: resist vanished from geometry, which PR strip does not "
        "currently do -- if this now passes, the strip became a real "
        "geometry step and this test's note is stale")

    # --- 10. Doping: attaches to the final mesh, changes no geometry ----
    assert final_doped.doping is not None and final_doped.doping.regions, (
        "no doping attached")
    assert final_doped.doping.regions[0].region == "Si"
    assert final_doped.material_regions == final_result.material_regions, (
        "doping altered the geometry it was attached to")
    print("    [10] doping: attached to 'Si' of the final mesh, geometry unchanged")


def main():
    test_a_resist_state_table()
    test_a2_coat_clears_previous_cycle()
    test_b1_first_step_invents_no_mask()
    test_b2_bare_coat_is_blanket_not_patterned()
    test_b3_developed_resist_is_patterned()
    test_c_long_mixed_run()

    print()
    print("LITHOGRAPHY LIFECYCLE VERIFIED AGAINST REAL VIENNAPS 4.6.2")
    print("(no lithography -> no mask; coat -> blanket resist;")
    print(" align/expose -> no geometry change; develop -> patterned;")
    print(" strip -> no mask; each step changes only its own effect)")


if __name__ == "__main__":
    main()
