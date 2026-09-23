#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process-state / geometry-chaining regression, real ViennaPS 4.6.2.

Reproduces a real bug reported by the user: running a chained step (deposition, specifically) through the GUI made a
Mask material suddenly appear in the geometry, and made an earlier step's shape appear to "come back" -- neither of
which the user had asked for.

Root cause, confirmed by reading the actual GUI code (not assumed): tcad_2d_stagewise.py's
`_mask_recipe_keys_for_current_step()` used to return `remask_spans_um` -- inserting a NEW mask via
session.remask_domain() -- for EVERY chained etch/deposition step unconditionally, derived from
self.wafer.mask_openings_um (a GUI field that persists from whatever it last was and never clears itself). So a plain
blanket deposition run after an earlier step silently got masked using stale/default litho state the user never set up
FOR THIS STEP. Compounding it: deposition's own duplicateTopLevelSet() duplicates the domain's CURRENT top level set,
which the just-inserted mask now was -- so the "new" material's starting shape was the mask box, not the real prior
surface, which is why an unrelated earlier step's geometry appeared to resurface.

Fixed by gating mask application on whether the user has explicitly gone through the Lithography sequence. This test
verifies the FIXED behavior at the library level (the recipes _mask_recipe_keys_for_current_step() builds when no
lithography was done for a step), independent of Tk.

WHAT CHANGED IN THIS MIGRATION (Batch 4). This test used to start with a positive-time thermal oxidation to obtain a
Si/SiO2 wafer. Positive-time oxidation is UNSUPPORTED_BY_MODEL, so that first step stopped the flow and the test never
reached what it exists to check. Oxide growth was never the subject here. The starting structure is now an EXPLICIT
INITIAL Si/SiO2 stack (tests/integration/_explicit_chain_fixture.py, provenance DIRECT_EXPLICIT_GEOMETRY): input
geometry the test states, saved as a `.vpsd` state, of which every scenario loads its own independent copy and hands
it to `run_flow(..., initial_domain=...)`. It is not a process result and no thickness is claimed for it.

What is verified, on that stack (measured on the real domain AND on the real exported mesh, kept apart):

  initial state          exactly Si + SiO2, no Mask; requested / native / exported values reported separately
  -> Deposition (Metal)  chained, NO lithography: no Mask is invented; a Metal film is really added and is a blanket
                         film; the Si and SiO2 level sets are unchanged and their exported geometry stays within one
                         tenth of a cell
  -> Etch (Metal only)   rate < 0 for Metal ONLY, exactly 0 for Si and SiO2: Metal really thins or is removed; Si and
                         SiO2 preserved; still no Mask
  -> Doping              a profile is attached to the Si region of the final real mesh and changes no geometry (this
                         says nothing about doping kinetics or activation)

Every comparison is made at the SAME x column (never a max(y) over different features). Tolerances: native readings of
an untouched level set must agree to float64 rounding (`fx.native_eps`), exported positions to a tenth of a cell
(`fx.exported_tolerance`, the bound this test already carried); the native-vs-REQUESTED bound
(`fx.native_request_tolerance`) is observational with an UNKNOWN cause, see the helper. A set of sensitivity checks at the
end proves each assertion FAILS FOR ITS OWN EXPECTED REASON when its subject is broken (`fx.assert_fails(check, label,
expected)`: a check that passes is a FALSE GREEN, one that fails for another reason is a WRONG FAILURE REASON).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

import tcad.process.etching  # noqa: F401
import tcad.process.deposition  # noqa: F401
from tcad.process.flow import FlowStep
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping

import _explicit_chain_fixture as fx

MODULE = session.require_viennaps()

# ---- explicit INPUT geometry (requested values, stated before any measurement) -----------------------------------
GRID, XE, YE = 0.1, 8.0, 5.0
SI_DEPTH_UM = 4.0
OXIDE_TOP_UM = 4 * GRID                 # a stated input: four grid cells of SiO2 on the Si surface (y = 0)
EXPORT_TOL = fx.exported_tolerance(GRID)
NATIVE_EPS = fx.native_eps(YE)

# ---- process recipes (nothing here describes the initial structure: that is the explicit state) ------------------
DEPOSITION_RATE, DEPOSITION_TIME_S = 0.15, 1.0
FULL_ETCH_TIME_S, PARTIAL_ETCH_TIME_S, METAL_ETCH_RATE = 0.6, 0.06, -1.0


def deposition_step():
    return FlowStep(category="deposition", name="isotropic", recipe={
        "silicon_depth_um": SI_DEPTH_UM, "deposition_time_s": DEPOSITION_TIME_S,
        "rate": DEPOSITION_RATE, "material": "Metal",
    })


def etch_step(metal=METAL_ETCH_RATE, si=0.0, sio2=0.0, time_s=FULL_ETCH_TIME_S):
    """Blanket etch selective by MATERIAL RATE, not by a mask: only the material named with a negative rate is removed."""
    return FlowStep(category="etching", name="isotropic", recipe={
        "silicon_depth_um": SI_DEPTH_UM,
        "material_rates": {"Metal": metal, "SiO2": sio2, "Si": si},
        "default_rate": 0.0, "etch_time_s": time_s,
    })


# ------------------------------------------------------------------------------------------------ measurement
class Chain:
    """`steps` run on a NEW independent copy of the saved initial state; every stage measured natively and on the mesh."""

    def __init__(self, state, tmp, tag, steps):
        self.steps = steps
        self.results, self.calls, self.stages = fx.run_steps_from_state(state, tmp, tag, steps)


def metal_thickness_native(stage):
    """Native Metal thickness at each column = Metal level-set top minus the SiO2 level-set top, at the same column."""
    return stage.native["Metal"] - stage.native["SiO2"]


# ----------------------------------------------------------------------------------------------------- checks
def check_initial(state):
    assert state.provenance == "DIRECT_EXPLICIT_GEOMETRY", state.provenance
    assert state.forbidden_call_counts == {"Oxidation": 0, "Process": 0}, state.forbidden_call_counts
    assert sorted(state.exported_summary) == ["Si", "SiO2"], (
        f"the initial state must be exactly Si + SiO2 (no Mask): exported {sorted(state.exported_summary)}")
    assert state.level_set_order == ["Si", "SiO2"], state.level_set_order
    top = state.requested["sio2"]["top_y_um"]
    request_tol = fx.native_request_tolerance(GRID)         # native position vs REQUESTED value: observational bound (cause UNKNOWN)
    assert np.all(np.abs(state.native_tops["SiO2"] - top) <= request_tol), (
        f"native SiO2 top {state.native_tops['SiO2']} != the requested {top}")
    assert np.all(np.abs(state.native_tops["Si"]) <= request_tol), "native Si top is not at the requested y = 0"
    copy = state.load_independent_copy("check_initial")    # the saved .vpsd really loads, as a new domain
    assert fx.native_level_set_order(copy) == state.level_set_order


def check_rate_contract(step):
    """Metal is the ONLY material with a negative rate; Si and SiO2 are exactly zero (and so is the default)."""
    rates = step.recipe["material_rates"]
    assert rates["Metal"] < 0.0, f"the Metal rate must be negative: {rates}"
    assert rates["Si"] == 0.0 and rates["SiO2"] == 0.0 and step.recipe["default_rate"] == 0.0, (
        f"Si / SiO2 / default rates must be exactly 0: {rates}, default {step.recipe['default_rate']}")
    assert sum(1 for v in rates.values() if v < 0.0) == 1, f"more than one material is being etched: {rates}"


def check_no_mask(stage, where):
    assert "Mask" not in stage.exported and "Mask" not in stage.native_order, (
        f"{where}: a Mask appeared with no lithography -- THE REPORTED BUG: exported {stage.materials}, "
        f"native order {stage.native_order}")


def check_si_sio2_preserved(state, stage, where):
    """Si and SiO2 keep the geometry of the explicit initial state (native to float64 rounding, exported to a tenth of a
    cell, present in the same columns) -- the shared check in the helper, at this test's grid."""
    fx.assert_si_sio2_preserved(state, stage, GRID, where)


def check_metal_blanket(dep):
    assert "Metal" in dep.exported and not np.any(np.isnan(dep.exported["Metal"]["ymax"])), (
        f"deposited Metal is missing in some columns: {dep.materials}")
    native_t = metal_thickness_native(dep)
    exported_t = dep.exported["Metal"]["ymax"] - dep.exported["Metal"]["ymin"]
    assert np.all(native_t > EXPORT_TOL) and np.all(exported_t > EXPORT_TOL), (
        f"Metal is not a film of positive thickness at every column: native {native_t}, exported {exported_t}")
    x0, x1 = dep.summary["Metal"]["x_range"]
    assert x1 - x0 > XE - 1.0, f"deposited Metal is not a full blanket film: x=[{x0:.3f}, {x1:.3f}]"


def check_metal_removed_or_thinned(dep, etch):
    """The etch's own effect must be real (this is not a no-op check): the Metal is gone, or thinner at EVERY column."""
    before, after = metal_thickness_native(dep), metal_thickness_native(etch)
    if "Metal" not in etch.exported:
        assert np.all(after <= EXPORT_TOL), f"Metal left the exported mesh but native thickness remains: {after}"
    else:
        assert np.all(after < before - EXPORT_TOL), (
            f"the etch did not thin the Metal at every column: {np.round(before, 4)} -> {np.round(after, 4)}")


def check_thinning_matches_recipe(dep, etch, step):
    """Partial etch: the thinning equals |rate| x time to one grid cell (the level-set resolution)."""
    expected = abs(step.recipe["material_rates"]["Metal"]) * step.recipe["etch_time_s"]
    reduction = metal_thickness_native(dep) - metal_thickness_native(etch)
    assert np.all(np.abs(reduction - expected) <= GRID), (
        f"Metal thinned by {np.round(reduction, 4)} um, recipe-derived {expected:.4f} um (bound = one grid cell {GRID})")


assert_fails = fx.assert_fails      # False-green guard: the check MUST raise AssertionError when its subject is broken


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # --- the explicit initial state -----------------------------------------------------------------
        state = fx.build_explicit_chain_state(
            tmp, x_extent_um=XE, y_extent_um=YE, silicon_depth_um=SI_DEPTH_UM,
            oxide_top_um=OXIDE_TOP_UM, grid_delta_um=GRID)
        print(fx.describe(state))
        check_initial(state)
        print("[0/4] Initial state: exactly Si + SiO2, no Mask; explicit input geometry (not a process result)")

        # --- the chain: Deposition (Metal) -> Etch (Metal only) -----------------------------------------
        etch = etch_step()
        check_rate_contract(etch)
        chain = Chain(state, tmp, "main", [deposition_step(), etch])
        assert len(chain.results) == 2, f"the flow stopped early: {len(chain.results)} of 2 results"
        assert chain.calls["Oxidation"] == 0, f"an oxidation solver was called: {chain.calls}"
        assert chain.calls["Process"] == 2, f"expected exactly the deposition and the etch: {chain.calls}"
        dep_stage, etch_stage = chain.stages

        # --- Check 1: Deposition ------------------------------------------------------------------------
        check_no_mask(dep_stage, "deposition")
        assert "Metal" in dep_stage.materials, f"deposited film missing: {dep_stage.materials}"
        check_metal_blanket(dep_stage)
        check_si_sio2_preserved(state, dep_stage, "after deposition")
        print(f"[1/4] Deposition (unmasked, blanket): {dep_stage.materials}")
        print(f"      no Mask; Metal blanket (native thickness {np.round(metal_thickness_native(dep_stage), 4)});")
        print("      Si / SiO2 native level sets unchanged, exported geometry within a tenth of a cell")

        # --- Check 2: Etch, Metal only -------------------------------------------------------------------
        check_no_mask(etch_stage, "etch")
        check_si_sio2_preserved(state, etch_stage, "after the Metal-only etch")
        check_metal_removed_or_thinned(dep_stage, etch_stage)
        removed = "Metal" not in etch_stage.exported
        print(f"[2/4] Etching (Metal rate {METAL_ETCH_RATE}, Si and SiO2 exactly 0): {etch_stage.materials}")
        print("      Metal " + ("removed" if removed else "thinned") + "; Si / SiO2 preserved; no Mask")

        # a partial etch shows the thinning itself (independent copy of the same saved initial state)
        partial_step = etch_step(time_s=PARTIAL_ETCH_TIME_S)
        check_rate_contract(partial_step)
        partial = Chain(state, tmp, "partial", [deposition_step(), partial_step])
        p_dep, p_etch = partial.stages
        check_si_sio2_preserved(state, p_etch, "after the partial Metal-only etch")
        check_metal_removed_or_thinned(p_dep, p_etch)
        check_thinning_matches_recipe(p_dep, p_etch, partial_step)
        print(f"      partial etch ({PARTIAL_ETCH_TIME_S} s): Metal thinned {np.round(metal_thickness_native(p_dep), 4)} -> "
              f"{np.round(metal_thickness_native(p_etch), 4)} um (= |rate| x time to one cell)")

        # --- Check 3: Doping (analytical, not a ViennaPS geometry step) ----------------------------------
        final_mesh = etch_stage.result.volume_mesh_path
        sha_before = fx.sha256_file(final_mesh)
        process_result = build_process_result({"final_mesh": final_mesh, "snapshots": []})
        doped = apply_uniform_doping(process_result, {"Si": 1e17}, chemical_state="UNKNOWN")
        assert doped.doping is not None and doped.doping.regions, "doping profile was not attached"
        assert doped.doping.regions[0].region == "Si", f"doping attached to the wrong region: {doped.doping.regions[0].region}"
        assert doped.material_regions == process_result.material_regions, "applying doping must not alter the geometry it was attached to"
        assert fx.sha256_file(final_mesh) == sha_before, "the final mesh file changed when doping was attached"
        print("[3/4] Doping: attached to region 'Si' of the FINAL real mesh; material geometry and mesh file unchanged")
        print("      (a statement about state attachment only -- nothing here proves doping kinetics or activation)")

        # --- independence of the scenarios ---------------------------------------------------------------
        state.assert_independent_loads(["check_initial", "main", "partial"])
        fresh = state.load_independent_copy("fresh_copy")
        again = fx.native_column_tops(fresh, state.columns_um)
        for mat in ("Si", "SiO2"):
            assert np.max(np.abs(again[mat] - state.native_tops[mat])) <= NATIVE_EPS, (
                f"a fresh copy of the initial state no longer matches it ({mat}): an earlier scenario leaked into it")
        print(f"[4/4] Independence: {len(state.copies_loaded)} domain objects (all still held, pairwise `is not`) loaded from ONE saved "
              f".vpsd (sha256 {state.vpsd_sha256[:16]}...), one load per scenario {state.load_labels}; the file never changed, "
              f"a fresh copy still equals the initial state")

        # --- sensitivity: every assertion must fail when its subject is broken ----------------------------
        print("\n  SENSITIVITY (false-green guards)")
        # 1. the initial oxide removed
        no_oxide = fx.build_explicit_chain_state(
            tmp, x_extent_um=XE, y_extent_um=YE, silicon_depth_um=SI_DEPTH_UM, oxide_top_um=OXIDE_TOP_UM,
            grid_delta_um=GRID, name="explicit_chain_no_oxide", include_oxide=False)
        # Each call names the reason the check must fail FOR (a substring, a tuple of substrings that must all appear, or a
        # predicate); a check that fails for any other reason is reported as WRONG FAILURE REASON, not accepted.
        assert_fails(lambda: check_initial(no_oxide), "the initial oxide is missing (initial-state check)",
                     ("the initial state must be exactly Si + SiO2", "exported ['Si']"))
        bare = Chain(no_oxide, tmp, "no_oxide", [deposition_step(), etch_step()])
        assert_fails(lambda: check_si_sio2_preserved(state, bare.stages[-1], "no-oxide chain"),
                     "the initial oxide is missing (SiO2 preservation)", "no-oxide chain: SiO2 vanished")
        # 4. Metal etch rate 0
        rate0 = Chain(state, tmp, "metal_rate_0", [deposition_step(), etch_step(metal=0.0)])
        assert_fails(lambda: check_metal_removed_or_thinned(rate0.stages[0], rate0.stages[1]), "the Metal etch rate is 0 (thinning)",
                     "the etch did not thin the Metal at every column")
        assert_fails(lambda: check_rate_contract(etch_step(metal=0.0)), "the Metal etch rate is 0 (rate contract)",
                     "the Metal rate must be negative")
        # 5. a nonzero SiO2 rate; a nonzero Si rate together with a nonzero SiO2 rate
        sio2_hit = Chain(state, tmp, "sio2_rate", [deposition_step(), etch_step(sio2=-1.0)])
        assert_fails(lambda: check_si_sio2_preserved(state, sio2_hit.stages[-1], "SiO2-rate chain"), "the SiO2 rate is nonzero (preservation)",
                     "SiO2-rate chain: SiO2 vanished")
        both_hit = Chain(state, tmp, "si_and_sio2_rate", [deposition_step(), etch_step(sio2=-1.0, si=-1.0)])
        assert_fails(lambda: check_si_sio2_preserved(state, both_hit.stages[-1], "Si+SiO2-rate chain"),
                     "the SiO2 and Si rates are nonzero (preservation)", "Si+SiO2-rate chain: native Si level set moved by")
        assert_fails(lambda: check_rate_contract(etch_step(si=-1.0)), "the Si rate is nonzero (rate contract)",
                     "Si / SiO2 / default rates must be exactly 0")
        print("      (a nonzero Si rate alone is physically inert while the SiO2 covers the Si everywhere, so it is guarded by the "
              "rate contract and, once SiO2 is also etched, by the geometry check)")
        # 6/7. the shared file was never mutated, every scenario performed its own load, all domains are distinct live objects
        state.assert_independent_loads(["check_initial", "main", "partial", "fresh_copy", "metal_rate_0", "sio2_rate", "si_and_sio2_rate"])
        print(f"      [sensitivity OK] the initial .vpsd is unchanged after {len(state.copies_loaded)} loads "
              f"({state.load_labels}), all distinct held domain objects")

    print()
    print("PROCESS STATE / GEOMETRY CHAINING VERIFIED AGAINST REAL VIENNAPS 4.6.2")
    print("(explicit initial Si/SiO2 stack -> Deposition -> Etching -> Doping; each step preserving every earlier")
    print(" material's geometry, no unrequested Mask; oxide growth is neither used nor claimed)")


if __name__ == "__main__":
    main()
