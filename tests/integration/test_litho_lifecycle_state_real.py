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

WHAT CHANGED IN THIS MIGRATION (Batch 4). B2, B3 and C used to start with a
positive-time thermal oxidation to obtain a Si/SiO2 wafer. Positive-time
oxidation is UNSUPPORTED_BY_MODEL, so that first step stopped the flow and
the tests never reached what they exist to check (resist state and
pattern fidelity); oxide growth was never their subject. They now start
from an EXPLICIT INITIAL Si/SiO2 stack (tests/integration/
_explicit_chain_fixture.py, provenance DIRECT_EXPLICIT_GEOMETRY): input
geometry the test states, saved as a `.vpsd` state, of which every
scenario loads its own independent copy for `run_flow(initial_domain=...)`.
It is not a process result and no thickness is claimed for it. Parts A, A2
and B1 are unchanged. Every geometric claim is measured at the SAME x
column on the real native domain and on the real exported mesh (kept
apart); the tolerance definitions and their limits are stated in the helper
(the native-vs-requested bound is observational, its cause UNKNOWN); a final
set of sensitivity checks proves each assertion FAILS FOR ITS OWN EXPECTED
REASON when its subject is broken (`fx.assert_fails(check, label, expected)`:
a check that passes is a FALSE GREEN, one failing for another reason is a
WRONG FAILURE REASON).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.core.models import Wafer
from tcad.process.flow import FlowStep, run_flow

import _explicit_chain_fixture as fx

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
        self._RESIST_MATERIAL = gui.TCADApplication._RESIST_MATERIAL
        self.wafer = Wafer()
        for key, value in wafer_state.items():
            setattr(self.wafer, key, value)
        self.completed_steps = [] if first_step else [{"_process_category": "oxidation"}]
        self.flow_steps = []
        # 2026-09-08 fix: _mask_recipe_keys_for_current_step() also reads
        # these two now (has_resumable_domain / whether the current
        # resist was already baked into geometry by an earlier chained
        # step) -- see that method's own docstring. This probe has no
        # real domain/run history, so both default to "nothing has run
        # yet", matching every scenario this test constructs by hand via
        # completed_steps/first_step above.
        self.last_domain_state = None
        self._resist_baked_since_coat = False


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
        "remask_spans_um": [[-HALF, HALF]],
        # Resist that becomes real geometry is tagged _RESIST_MATERIAL
        # ("PHS"), not "Mask" -- see CLAUDE.md's Doping/PR-Strip fix.
        "mask_material": coated_chained._RESIST_MATERIAL,
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



# ----------------------------------------------------------------------
# Part B (continued) -- resist state on an EXPLICIT initial Si/SiO2 stack
# ----------------------------------------------------------------------
# B2, B3 and C start from an explicit initial Si/SiO2 domain STATE (input
# geometry, provenance DIRECT_EXPLICIT_GEOMETRY), never from a process.

GRID_L = 0.05                        # um -- the level-set grid of these scenarios
YE_L = 8.0
SI_DEPTH_L = 5.0
OXIDE_TOP_L = 4 * GRID_L             # requested INPUT: four grid cells of SiO2 on the Si surface (y = 0)
PR_THICKNESS_UM = 1.0                # requested resist thickness (an input value)
OPENING = (-1.5, 1.5)                # the developed opening, an input pattern (the complement of DEVELOPED_SPANS)
BLANKET_SPANS = [[-HALF, HALF]]
DEVELOPED_SPANS = [[-HALF, OPENING[0]], [OPENING[1], HALF]]
# two extra columns on each side of an opening edge, two cells away, so pattern fidelity is measured NEAR the edge too
EDGE_COLUMNS = [OPENING[0] - 2 * GRID_L, OPENING[0] + 2 * GRID_L, OPENING[1] - 2 * GRID_L, OPENING[1] + 2 * GRID_L]
EXPORT_TOL_L = fx.exported_tolerance(GRID_L)
NATIVE_EPS_L = fx.native_eps(YE_L)

C_ETCH_RATE, C_ETCH_TIME_S = -0.2, 1.5        # SiO2 rate and time of the developed-window etch in C (Si and Mask rate 0)


def _explicit_state(tmp, **kwargs):
    return fx.build_explicit_chain_state(
        tmp, x_extent_um=WIDTH_UM, y_extent_um=YE_L, silicon_depth_um=SI_DEPTH_L,
        oxide_top_um=OXIDE_TOP_L, grid_delta_um=GRID_L, extra_columns_um=EDGE_COLUMNS, **kwargs)


def _chain_base():
    """Keys a step CONSUMES when it continues an existing wafer (grid / width / resist thickness feed the re-mask)."""
    return dict(pr_thickness_um=PR_THICKNESS_UM, silicon_depth_um=SI_DEPTH_L, grid_delta_um=GRID_L, x_extent_um=WIDTH_UM)


def _resist_deposition(spans):
    """Si3N4 deposition through the resist state `spans` (a re-mask of the wafer that already exists)."""
    return FlowStep("deposition", "isotropic", {
        **_chain_base(), "remask_spans_um": spans, "rate": 0.05, "deposition_time_s": 0.5,
        # "mask_material" tags the inserted mask geometry; growth exclusion needs its own key
        # (see tcad/process/deposition/isotropic.py), so both are set: this is what exercises exclusion through the resist.
        "mask_material": "Mask", "deposit_exclude_material": "Mask", "material": "Si3N4",
    })


def _present(stage, material):
    """Per state column: is `material` present in the EXPORTED mesh at that column?"""
    if material not in stage.exported:
        return np.zeros(len(stage.native["Si"]), dtype=bool)
    return ~np.isnan(stage.exported[material]["ymax"])


def _native_film_present(stage, material, base_material):
    """Per state column: native thickness of `material` (its level-set top minus the one below it) above a tenth of a cell."""
    if material not in stage.native:
        return np.zeros(len(stage.native["Si"]), dtype=bool)
    return (stage.native[material] - stage.native[base_material]) > EXPORT_TOL_L


def _check_resist_on_oxide(state, stage, where):
    """Wherever resist exists it sits ON the oxide: no resist bottom below the oxide top, at the same column, measured natively
    and on the mesh; and its native thickness is the requested resist thickness."""
    cols = _present(stage, "Mask")
    assert cols.any(), f"{where}: no resist anywhere"
    eps = fx.geometry_eps(fx.read_exported(stage.result.volume_mesh_path, state.module)["points"])     # float32 serialization bound
    gap = stage.exported["Mask"]["ymin"][cols] - stage.exported["SiO2"]["ymax"][cols]
    assert np.all(gap >= -eps), f"{where}: resist bottom is BELOW the exported oxide top by {-gap.min():.4g} um (buried resist)"
    native_t = (stage.native["Mask"] - stage.native["SiO2"])[cols]
    assert np.all(native_t >= -NATIVE_EPS_L), f"{where}: native resist level set lies below the oxide level set"
    assert np.all(np.abs(native_t - PR_THICKNESS_UM) <= EXPORT_TOL_L), (
        f"{where}: native resist thickness {np.round(native_t, 4)} != the requested {PR_THICKNESS_UM}")


def assert_blanket_pattern(state, stage, where):
    """The resist PATTERN of a bare coat: present at every column (the middle included), across the whole width, and it gates the
    deposition so no film reaches the wafer."""
    present = _present(stage, "Mask")
    assert present.all(), (
        f"{where}: blanket resist missing at x={np.round(state.columns_um[~present], 3)} -- the coat was applied as a DEVELOPED pattern")
    x0, x1 = stage.summary["Mask"]["x_range"]
    assert x0 <= -HALF + GRID_L and x1 >= HALF - GRID_L, f"{where}: resist is patterned, not blanket: x=[{x0:.3f}, {x1:.3f}]"
    assert "Si3N4" not in stage.exported, f"{where}: film was deposited through a resist that covers the entire wafer; {stage.materials}"
    if "Si3N4" in stage.native:
        assert not _native_film_present(stage, "Si3N4", "Mask").any(), f"{where}: a native Si3N4 film exists on top of the blanket resist"
    assert _native_film_present(stage, "Mask", "SiO2").all(), f"{where}: native resist is not present at every column"


def check_blanket_resist(state, stage, where="B2"):
    """A bare coat is BLANKET, sits on the oxide, and gates the deposition; Si and SiO2 are preserved."""
    assert stage.materials == ["Mask", "Si", "SiO2"], f"{where}: unexpected materials {stage.materials}"
    assert_blanket_pattern(state, stage, where)
    _check_resist_on_oxide(state, stage, where)
    fx.assert_si_sio2_preserved(state, stage, GRID_L, where)


def assert_developed_pattern(state, stage, opening, where):
    """The resist PATTERN after develop: resist only where the mask is opaque, none in the opening, and the film confined to (and
    filling) the opening. The opening edges are the developed INPUT pattern; the film extent is measured on the real mesh."""
    lo, hi = opening
    x = state.columns_um
    inside = (x > lo + GRID_L) & (x < hi - GRID_L)
    outside = (x < lo - GRID_L) | (x > hi + GRID_L)
    assert inside.any() and outside.any() and (inside | outside).all(), "the sample columns must classify against the opening"
    mask, film = _present(stage, "Mask"), _present(stage, "Si3N4")
    assert not mask[inside].any(), (
        f"{where}: developed resist still covers the opening at x={np.round(x[inside & mask], 3)} -- develop did not open the pattern")
    assert mask[outside].all(), f"{where}: developed resist missing where the mask is opaque, x={np.round(x[outside & ~mask], 3)}"
    assert film[inside].all(), f"{where}: nothing was deposited through the developed opening at x={np.round(x[inside & ~film], 3)}"
    assert not film[outside].any(), f"{where}: film escaped the opening at x={np.round(x[outside & film], 3)}"
    assert np.array_equal(_native_film_present(stage, "Mask", "SiO2"), mask), f"{where}: native and exported resist patterns differ"
    f0, f1 = stage.summary["Si3N4"]["x_range"]
    assert f0 >= lo - GRID_L and f1 <= hi + GRID_L, f"{where}: film x=[{f0:.4f}, {f1:.4f}] escapes the opening [{lo}, {hi}] by more than a cell"
    assert f0 <= lo + GRID_L and f1 >= hi - GRID_L, f"{where}: film x=[{f0:.4f}, {f1:.4f}] does not fill the opening [{lo}, {hi}]"


def check_developed_resist(state, stage, opening=OPENING, where="B3"):
    """A developed resist is PATTERNED, sits on the oxide, and the oxide under it is preserved."""
    assert stage.materials == ["Mask", "Si", "Si3N4", "SiO2"], f"{where}: unexpected materials {stage.materials}"
    assert_developed_pattern(state, stage, opening, where)
    _check_resist_on_oxide(state, stage, where)
    fx.assert_si_sio2_preserved(state, stage, GRID_L, where)


def test_b2_bare_coat_is_blanket_not_patterned():
    """Explicit Si/SiO2 -> PR COAT only -> deposition: the resist covers everything."""
    print("\n[B2] explicit Si/SiO2 stack -> PR COAT (nothing else) -> deposition")
    with tempfile.TemporaryDirectory() as tmp:
        state = _explicit_state(tmp)
        print(fx.describe(state))
        results, calls, stages = fx.run_steps_from_state(state, tmp, "b2", [_resist_deposition(BLANKET_SPANS)])
        assert len(results) == 1 and calls["Oxidation"] == 0, (len(results), calls)
        stage = stages[0]
        check_blanket_resist(state, stage)
        print(f"    materials={stage.materials}; resist present at all {len(state.columns_um)} columns "
              f"(x={stage.summary['Mask']['x_range'][0]:.2f}..{stage.summary['Mask']['x_range'][1]:.2f}), no Si3N4 reached the wafer")
        print(f"    resist native thickness {np.round((stage.native['Mask'] - stage.native['SiO2'])[:3], 4)} um on the oxide; "
              f"Si / SiO2 native level sets unchanged, exported within {EXPORT_TOL_L:.4f} um")


def test_b3_developed_resist_is_patterned():
    """Develop must produce a genuinely patterned resist, unlike a coat."""
    print("\n[B3] explicit Si/SiO2 stack -> coat + develop -> deposition")
    with tempfile.TemporaryDirectory() as tmp:
        state = _explicit_state(tmp)
        results, calls, stages = fx.run_steps_from_state(state, tmp, "b3", [_resist_deposition(DEVELOPED_SPANS)])
        assert len(results) == 1 and calls["Oxidation"] == 0, (len(results), calls)
        stage = stages[0]
        check_developed_resist(state, stage)
        f0, f1 = stage.summary["Si3N4"]["x_range"]
        print(f"    resist opened over x={OPENING}; measured film confined to x=[{f0:.4f}, {f1:.4f}]; "
              f"resist present at {int(_present(stage, 'Mask').sum())}/{len(state.columns_um)} columns (all of them outside the opening)")


# ---- C: a mixed sequence --------------------------------------------------------------------------------------------
ZERO_DURATION_RECIPE = {"time_hours": 0.0, "oxidant": "Dry", "temperature_c": 1000.0, "silicon_depth_um": SI_DEPTH_L}


def c_steps(si_rate=0.0, sio2_rate=C_ETCH_RATE):
    """Inherited-domain zero-duration thermal step (an exact identity) -> selective oxide etch through the DEVELOPED window
    -> unmasked blanket deposition. (PR coat / align / expose / develop / strip are resist STATE transitions, not steps.)"""
    return [
        FlowStep("oxidation", "thermal", dict(ZERO_DURATION_RECIPE)),
        FlowStep("etching", "isotropic", {
            **_chain_base(), "remask_spans_um": DEVELOPED_SPANS, "mask_material": "Mask",
            "material_rates": {"SiO2": sio2_rate, "Si": si_rate, "Mask": 0.0}, "default_rate": 0.0, "etch_time_s": C_ETCH_TIME_S,
        }),
        FlowStep("deposition", "isotropic", {
            "silicon_depth_um": SI_DEPTH_L, "rate": 0.05, "deposition_time_s": 0.4, "material": "Si3N4"}),
    ]


def _c_columns(state):
    """Column classes for the developed-window etch, derived from the input pattern and the recipe (nothing measured from
    the result): `opening` columns lie inside the window; `protected` columns are beyond the window edge by more than the
    isotropic lateral reach |rate| x time (plus a cell), where the resist must fully protect the oxide."""
    x = np.abs(state.columns_um)
    reach = abs(C_ETCH_RATE) * C_ETCH_TIME_S
    opening = x < OPENING[1] - GRID_L
    protected = x > OPENING[1] + reach + GRID_L
    assert opening.any() and protected.any()
    return opening, protected


def c_opening_native_residual(state, etch):
    """(native SiO2 residual thickness at each sampled opening column, the declared model-resolution bound): the residual is the
    SiO2 level-set top minus the Si level-set top at the SAME column; the bound is a tenth of a cell (`fx.exported_tolerance`)."""
    opening, _ = _c_columns(state)
    return (etch.native["SiO2"] - etch.native["Si"])[opening], EXPORT_TOL_L


def check_c_identity(state, tmp):
    """The inherited-domain zero-duration step alone: an exact IDENTITY, no oxidation solver, no process solver."""
    results, calls, stages = fx.run_steps_from_state(state, tmp, "c_zero", [c_steps()[0]])
    assert len(results) == 1, f"the zero-duration step did not complete: {len(results)} results"
    assert calls == {"Oxidation": 0, "Process": 0}, f"the zero-duration step called a solver: {calls}"
    t = stages[0].transition
    assert t is not None and t.get("kind") == "identity" and t.get("inherited") is True, f"not an inherited identity: {t}"
    assert stages[0].materials == ["Si", "SiO2"] and stages[0].native_order == ["Si", "SiO2"], (
        f"the identity changed the material set: {stages[0].materials} / {stages[0].native_order}")
    fx.assert_si_sio2_preserved(state, stages[0], GRID_L, "zero-duration identity")
    return t, calls


def check_c_flow(state, chain, where="C"):
    results, calls, (ident, etch, dep) = chain
    opening, protected = _c_columns(state)
    assert len(results) == 3, f"{where}: the flow stopped early: {len(results)} of 3 results"
    assert calls["Oxidation"] == 0, f"{where}: an oxidation solver was called: {calls}"
    assert calls["Process"] == 2, f"{where}: expected exactly the etch and the deposition as Process calls: {calls}"
    assert ident.transition and ident.transition.get("kind") == "identity", ident.transition
    for later in (etch, dep):
        assert later.transition is None or later.transition.get("kind") not in ("identity", "unsupported"), later.transition

    # --- the developed-window etch --------------------------------------------------------------------------------
    assert etch.materials == ["Mask", "Si", "SiO2"], f"{where}: unexpected materials after the etch: {etch.materials}"
    mask = _present(etch, "Mask")
    assert not mask[opening].any() and mask[protected].all(), f"{where}: the resist pattern is wrong: present at {np.round(state.columns_um[mask], 3)}"
    # Contract (the same words everywhere): SiO2 is absent from the EXPORTED mesh at the sampled opening columns, and the NATIVE
    # residual SiO2 thickness there is at or below the declared model-resolution bound (0.1 x grid). It is a clearance to the
    # resolution of this model, not a claim about the continuum.
    sio2 = _present(etch, "SiO2")
    assert not sio2[opening].any(), (
        f"{where}: SiO2 is present in the exported mesh at sampled opening columns x={np.round(state.columns_um[opening & sio2], 3)}")
    native_ox, bound = c_opening_native_residual(state, etch)
    assert np.all(native_ox <= bound), (
        f"{where}: native SiO2 residual thickness at the sampled opening columns exceeds the declared model-resolution bound "
        f"{bound:.4g} um: {np.round(native_ox, 6)}")
    fx.assert_si_sio2_preserved(state, etch, GRID_L, f"{where} after the etch", sio2_columns=protected)   # Si everywhere, SiO2 under the resist

    # --- the unmasked deposition ------------------------------------------------------------------------------------
    assert dep.materials == sorted(set(etch.materials) | {"Si3N4"}), (
        f"{where}: materials appeared or vanished during deposition: {etch.materials} -> {dep.materials}")
    assert _present(dep, "Si3N4").all(), f"{where}: the unmasked deposition was patterned"
    x0, x1 = dep.summary["Si3N4"]["x_range"]
    assert x0 <= -HALF + GRID_L and x1 >= HALF - GRID_L, f"{where}: Si3N4 is not a blanket film: x=[{x0:.3f}, {x1:.3f}]"
    assert np.array_equal(_present(dep, "SiO2"), sio2), f"{where}: the deposition resurrected or removed oxide"
    fx.assert_si_sio2_preserved(state, dep, GRID_L, f"{where} after the deposition", sio2_columns=protected)
    # PR STRIP is a state transition: resist already built into an EARLIER step's exported geometry stays in that mesh.
    # Asserting it rather than glossing over it keeps the known limitation visible.
    assert "Mask" in dep.materials, (
        "unexpected: resist vanished from geometry, which PR strip does not currently do -- if this now passes, the "
        "strip became a real geometry step and this test's note is stale")


def test_c_long_mixed_run():
    """One mixed run touching several categories, checked step by step.

    The order below is ARBITRARY -- chosen only because it exercises an inherited zero-duration step, a masked etch and an
    unmasked deposition against accumulating geometry. It is not a canonical or required flow and nothing in the tool may
    assume it (see CLAUDE.md's invariant): the user picks the order.

    Two facts are kept apart. (1) The initial oxide is an explicit INPUT structure, not a process result. (2) The
    inherited-domain zero-duration thermal step is an exact IDENTITY: it returns the domain it was given and calls no
    solver. The etch and the deposition that follow legitimately call the process solver, so solver calls are COUNTED
    (pass-through) per run, never blocked globally.

    PR coat / mask / exposure / development / strip are resist-STATE transitions -- treating any of them as a geometry step
    is what produced a developed pattern from a bare coat. Every check re-verifies the EARLIER materials on the new
    mesh, not just the new step's own feature.
    """
    print("\n[C] explicit Si/SiO2 -> zero-duration thermal step (identity) -> selective oxide etch through the developed window "
          "-> unmasked deposition -> doping")

    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_uniform_doping

    with tempfile.TemporaryDirectory() as tmp:
        state = _explicit_state(tmp)
        transition, id_calls = check_c_identity(state, tmp)
        print(f"    [1] zero-duration step alone: state_transition={transition}; solver calls {id_calls} "
              f"(no oxidation solver, no native seed, no Process); Si/SiO2 native and exported geometry identical")

        results, calls, stages = fx.run_steps_from_state(state, tmp, "c_flow", c_steps())
        check_c_flow(state, (results, calls, stages))
        etch, dep = stages[1], stages[2]
        opening, protected = _c_columns(state)
        print(f"    [1'] the same step inside the flow: identity, then the flow proceeded to the next step; "
              f"whole-flow solver calls {calls} (= the etch and the deposition only)")
        residual, bound = c_opening_native_residual(state, etch)
        print(f"    [6] etch: SiO2 is absent from the exported mesh at the {int(opening.sum())} sampled opening columns "
              f"x={np.round(state.columns_um[opening], 3)}, and the native residual SiO2 thickness there is at or below the declared "
              f"model-resolution bound ({bound:.4g} um = 0.1 x grid); native residual (um) = {residual}; Si level set unmoved (rate 0); "
              f"SiO2 preserved at the {int(protected.sum())} protected columns; resist only where the mask is opaque")
        print(f"    [8] deposition: blanket Si3N4 at all {len(state.columns_um)} columns; materials {dep.materials}; "
              f"earlier materials neither resurrected nor removed")
        print("    [7] PR strip: state only -- the resist already in the etch step's mesh stays (known limitation, asserted)")

        final_mesh = dep.result.volume_mesh_path
        sha_before = fx.sha256_file(final_mesh)
        final_result = build_process_result({"final_mesh": final_mesh, "snapshots": []})
        final_doped = apply_uniform_doping(final_result, {"Si": 1e17}, chemical_state="UNKNOWN")
        assert final_doped.doping is not None and final_doped.doping.regions, "no doping attached"
        assert final_doped.doping.regions[0].region == "Si"
        assert final_doped.material_regions == final_result.material_regions, "doping altered the geometry it was attached to"
        assert fx.sha256_file(final_mesh) == sha_before, "the final mesh file changed when doping was attached"
        print("    [10] doping: attached to 'Si' of the final mesh, geometry unchanged (state attachment only, no kinetics claimed)")


def test_sensitivity_false_green_guards():
    """Each assertion above must FAIL when its subject is broken; a set of deliberately wrong inputs proves it."""
    print("\n[S] sensitivity: every assertion fails when its subject is broken")
    with tempfile.TemporaryDirectory() as tmp:
        state = _explicit_state(tmp)
        r_blanket = fx.run_steps_from_state(state, tmp, "s_blanket", [_resist_deposition(BLANKET_SPANS)])[2][0]
        r_devel = fx.run_steps_from_state(state, tmp, "s_devel", [_resist_deposition(DEVELOPED_SPANS)])[2][0]
        check_blanket_resist(state, r_blanket, "reference B2")               # the references themselves pass
        check_developed_resist(state, r_devel, where="reference B3")
        # 2. blanket span replaced by the patterned span
        # Each call names the reason the check must fail FOR; a check failing for another reason is a WRONG FAILURE REASON.
        fx.assert_fails(lambda: assert_blanket_pattern(state, r_devel, "B2 pattern with a patterned span"),
                        "the blanket span is replaced by a patterned span (B2 pattern)",
                        ("B2 pattern with a patterned span: blanket resist missing at x=", "the coat was applied as a DEVELOPED pattern"))
        fx.assert_fails(lambda: check_blanket_resist(state, r_devel, "B2 with a patterned span"),
                        "the blanket span is replaced by a patterned span (B2 full check)",
                        ("B2 with a patterned span: unexpected materials", "'Si3N4'"))          # film deposited through the opening
        # 3. developed span replaced by the blanket span
        fx.assert_fails(lambda: assert_developed_pattern(state, r_blanket, OPENING, "B3 pattern with a blanket span"),
                        "the developed span is replaced by a blanket span (B3 pattern)",
                        ("B3 pattern with a blanket span: developed resist still covers the opening at x=", "develop did not open the pattern"))
        fx.assert_fails(lambda: check_developed_resist(state, r_blanket, where="B3 with a blanket span"),
                        "the developed span is replaced by a blanket span (B3 full check)",
                        lambda m: "B3 with a blanket span: unexpected materials" in m and "'Si3N4'" not in m)    # no film reached the wafer
        # 1. the initial oxide removed
        no_oxide = _explicit_state(tmp, name="explicit_chain_no_oxide", include_oxide=False)
        bare = fx.run_steps_from_state(no_oxide, tmp, "s_no_oxide", [_resist_deposition(BLANKET_SPANS)])[2][0]
        fx.assert_fails(lambda: check_blanket_resist(state, bare, "B2 without the initial oxide"),
                        "the initial oxide is missing (B2 SiO2 preservation)",
                        lambda m: "B2 without the initial oxide: unexpected materials" in m and "'SiO2'" not in m)   # SiO2 absent from the set
        # C: a nonzero Si rate (the Si level set must stay where it was) and a zero SiO2 rate (the etch does nothing to the oxide)
        good = fx.run_steps_from_state(state, tmp, "s_c_good", c_steps())
        check_c_flow(state, good, "reference C")
        si_hit = fx.run_steps_from_state(state, tmp, "s_c_si", c_steps(si_rate=-0.2))
        fx.assert_fails(lambda: check_c_flow(state, si_hit, "C with a nonzero Si rate"), "the Si rate is nonzero (Si preservation, C)",
                        "C with a nonzero Si rate after the etch: native Si level set moved by")
        inert = fx.run_steps_from_state(state, tmp, "s_c_inert", c_steps(sio2_rate=0.0))
        fx.assert_fails(lambda: check_c_flow(state, inert, "C with a zero SiO2 rate"), "the SiO2 etch rate is 0 (the etch must clear the window, C)",
                        "C with a zero SiO2 rate: SiO2 is present in the exported mesh at sampled opening columns")
        # 6/7. one saved file, never mutated; every scenario performed its own load; all domains are distinct live objects
        state.assert_independent_loads(["s_blanket", "s_devel", "s_c_good", "s_c_si", "s_c_inert"])
        fresh = fx.native_column_tops(state.load_independent_copy("fresh_copy"), state.columns_um)
        for mat in ("Si", "SiO2"):
            assert np.max(np.abs(fresh[mat] - state.native_tops[mat])) <= NATIVE_EPS_L, f"a fresh copy no longer equals the initial state ({mat})"
        state.assert_independent_loads(["s_blanket", "s_devel", "s_c_good", "s_c_si", "s_c_inert", "fresh_copy"])
        assert no_oxide.load_labels == ["s_no_oxide"]
        print(f"    [sensitivity OK] {len(state.copies_loaded)} loads {state.load_labels} gave distinct held domain objects from one saved "
              f".vpsd (sha256 {state.vpsd_sha256[:16]}...); the file is unchanged and a fresh copy still equals the initial state")


def main():
    test_a_resist_state_table()
    test_a2_coat_clears_previous_cycle()
    test_b1_first_step_invents_no_mask()
    test_b2_bare_coat_is_blanket_not_patterned()
    test_b3_developed_resist_is_patterned()
    test_c_long_mixed_run()
    test_sensitivity_false_green_guards()

    print()
    print("LITHOGRAPHY LIFECYCLE VERIFIED AGAINST REAL VIENNAPS 4.6.2")
    print("(no lithography -> no mask; coat -> blanket resist; align/expose -> no geometry change;")
    print(" develop -> patterned; strip -> no mask; each step changes only its own effect;")
    print(" the initial Si/SiO2 is an explicit input structure -- oxide growth is neither used nor claimed)")


if __name__ == "__main__":
    main()
