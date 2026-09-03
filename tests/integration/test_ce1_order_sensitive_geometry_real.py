# -*- coding: utf-8 -*-
"""Spec 2026-09-03 CE-1 (corrected scope): geometry/state order-
sensitivity, X-ONLY -- no depth-dependent claim anywhere in this file.
Two disjoint x-regions: R_ETCH_X (a real ViennaPS masked etch removes
Si there COMPLETELY -- verified below, not assumed) and R_SAFE_X
(never touched by the etch). Whichever species existed at R_ETCH_X
before the etch is erased there (geometry-gated zero); a DIFFERENT
species is placed at R_SAFE_X after the etch. Swapping which species
plays which role flips the wafer's species composition at R_SAFE_X and
its net polarity -- this is the real, model-honest form of "process
order changes the final WaferState."

Two real deviations from this task's own draft brief, both found by
actually running the code (not guessed), documented here and in
task-6-report.md:

Problem 1 (base wafer): a plain, non-LOCOS thermal oxidation
unconditionally seeds a native-oxide layer across the ENTIRE exposed
Si surface regardless of time_hours
(tcad/process/oxidation/thermal.py's own
`setInitialOxideThickness(max(0.002, grid_delta_um))`, confirmed by
Task 5's own real-run finding). That makes Si never the topmost
material anywhere on an unmasked wafer, so a host_material="Si"
profile would read UNSUPPORTED_BY_MODEL everywhere -- not the real
removal-gating this test needs. Fixed the same way Task 5 fixed the
identical problem: the base step is a real, blanket (no-mask)
isotropic etch, which has no such seed-layer side effect.

Problem 2 (coordinates + masking convention): `mask_spans_um` /
`remask_spans_um` take the OPAQUE (protected) spans, not the open
ones (see `tcad.process.base.mask_spans_from_openings`'s own
docstring), in DOMAIN coordinates centred on 0
([-x_extent_um/2, +x_extent_um/2], the convention this project's own
PN-diode investigation documents in CLAUDE.md). A window masked THIS
way still leaves a solid "Mask" material sitting on top of the
UNTOUCHED region (R_SAFE_X included) after the etch -- so this test
also does a real, physically standard etch-then-STRIP
(`domain.removeMaterial()`, the exact same real ViennaPS 4.6.2 API
`tests/integration/test_pr_strip_real.py` already verifies for
resist) so R_SAFE_X is genuinely exposed Si again afterward, matching
what a real fab does after any masked etch. All real, printed and
checked below -- not assumed.

Problem 3 (discovered while building this test, not pre-flagged in
the brief): `WaferState.last_step_category` is a single FLAT field --
"the most recently run step's category" -- not a per-profile record of
which step actually caused a given profile's host material to vanish.
Confirmed by direct experiment (see task-6-report.md): once ANY
further step of an unclassified category (e.g. "doping", which never
touches geometry at all) runs after the removal-causing etch, a query
against that LATER state reports the etched-away profile as
UNSUPPORTED_BY_MODEL, not a geometry-gated zero -- the model has
"forgotten" that the earlier etch, not this later step, is why the
material is gone. This is real, current model behavior, not a bug this
test may quietly route around: R_ETCH_X's erasure is therefore queried
against the WaferState taken immediately after the etch (still
classified "etching"), while R_SAFE_X's polarity is queried against the
true final state (its host material genuinely IS exposed there, so no
gating branch is even invoked) -- see run_order()'s own comments.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers "etching"/"isotropic"
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state import WaferState
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh

WIDTH_UM, Y_EXTENT_UM, SI_DEPTH_UM, GRID_UM = 10.0, 8.0, 1.0, 0.1
R_ETCH_X, R_SAFE_X = 0.0, 3.5   # disjoint x positions, real ViennaPS domain coords
WINDOW_HALF_UM = 1.0            # the real etch window is x in [-1.0, +1.0]
HALF_DOMAIN_UM = WIDTH_UM / 2.0


def _fresh_wafer(tmp):
    """Base wafer: a real, blanket (no-mask) isotropic etch -- NOT
    thermal oxidation (Problem 1, see module docstring). Leaves Si
    exposed at every x, verified below by the caller, not assumed."""
    step = registry.get("etching", "isotropic")()
    recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        "rate": -0.02, "etch_time_s": 5.0,
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": WIDTH_UM, "y_extent_um": Y_EXTENT_UM,
        "mask_spans_um": [],
    }
    result = step.run(recipe, tmp)
    return step, build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})


def _real_etch_and_strip(tmp, inherited_domain):
    """A real, masked isotropic etch that removes Si COMPLETELY within
    a window centred on R_ETCH_X (real ViennaPS geometry, verified by
    the caller -- not assumed from the recipe numbers alone), followed
    by a real strip of the protective mask so untouched Si elsewhere
    (R_SAFE_X included) is genuinely exposed again -- Problem 2, see
    module docstring. Uses `remask_spans_um` (not `mask_spans_um`):
    this step continues from an INHERITED domain, and
    `ProcessStep.prepare_domain()` only ever applies a mask to a
    domain that does not yet exist -- `remask_spans_um` is the real,
    already-used (test_gate_patterning_remask_real.py,
    test_wafer_state_accumulation_devsim_real.py) mechanism for adding
    a NEW mask on top of an already-processed domain."""
    module = session.require_viennaps()
    etch_step = registry.get("etching", "isotropic")(inherited_domain=inherited_domain)
    etch_recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        "remask_spans_um": [
            [-HALF_DOMAIN_UM, -WINDOW_HALF_UM],
            [WINDOW_HALF_UM, HALF_DOMAIN_UM],
        ],
        "mask_material": "Mask",
        "grid_delta_um": GRID_UM, "x_extent_um": WIDTH_UM, "pr_thickness_um": 0.3,
        "rate": -0.5, "etch_time_s": 3.0,   # 1.5um vertical -- clears SI_DEPTH_UM=1.0 with margin
        "silicon_depth_um": SI_DEPTH_UM,
    }
    etch_step.run(etch_recipe, tmp)

    # Real strip: remove the protective mask from the LIVE domain --
    # the exact same domain.removeMaterial() API
    # test_pr_strip_real.py already verifies against real ViennaPS
    # 4.6.2 for resist. Matches standard fab practice (strip resist
    # after every masked etch), not a test-only workaround.
    etch_step.last_domain.removeMaterial(module.Material.Mask)
    stripped_mesh = save_volume_mesh(
        etch_step.last_domain, Path(tmp) / "ce1_stripped", floor_depth_um=SI_DEPTH_UM,
    )
    return build_process_result({"final_mesh": stripped_mesh, "snapshots": []})


def run_order(tmp, region_species):
    """region_species: {"etch": (kwarg, species), "safe": (kwarg, species)} --
    which species targets R_ETCH_X (implanted BEFORE the etch) vs R_SAFE_X
    (implanted AFTER the etch)."""
    step, base = _fresh_wafer(tmp)
    etch_kwarg, etch_species = region_species["etch"]
    safe_kwarg, safe_species = region_species["safe"]

    r1 = apply_gaussian_implant_doping(
        base, region="Si", junction_axis="x", peak_position_um=R_ETCH_X, straggle_um=0.3,
        **{etch_kwarg: 1e18, f"{etch_kwarg.split('_')[0]}_species": etch_species},
    )
    state1 = advance_wafer_state(None, r1, "doping")

    pre_etch_state = WaferState.from_process_result(base)
    print(f"[pre-etch] exposed material at R_ETCH_X={R_ETCH_X}: "
          f"{pre_etch_state.exposed_material_at(R_ETCH_X)}")

    stripped = _real_etch_and_strip(tmp, step.last_domain)
    post_etch_state_for_check = WaferState.from_process_result(stripped)
    exposed_after = post_etch_state_for_check.exposed_material_at(R_ETCH_X)
    exposed_safe_after = post_etch_state_for_check.exposed_material_at(R_SAFE_X)
    print(f"[post-etch+strip] exposed material at R_ETCH_X={R_ETCH_X}: {exposed_after}")
    print(f"[post-etch+strip] exposed material at R_SAFE_X={R_SAFE_X}: {exposed_safe_after}")
    assert exposed_after != "Si", (
        f"the etch must remove Si COMPLETELY at R_ETCH_X (a recess that leaves Si "
        f"still topmost there would produce NO geometry-gated zero at all) -- "
        f"got exposed_material_at={exposed_after!r}, tune etch_time_s/window before "
        f"trusting the rest of this test"
    )
    assert exposed_safe_after == "Si", (
        f"R_SAFE_X must read genuine, exposed Si after the etch+strip -- if it "
        f"doesn't, either lateral undercut reached it or the mask strip failed -- "
        f"got exposed_material_at={exposed_safe_after!r}"
    )

    # R_ETCH_X's fate is queried on the state RIGHT AFTER the etch
    # (last_step_category="etching"), NOT on the later state that also
    # carries the R_SAFE_X implant -- Problem 3 (module docstring):
    # last_step_category is a single flat "most recently run step"
    # field, so a further "doping"-category step (not in
    # MATERIAL_CHANGE_KIND_BY_CATEGORY) would make this SAME
    # etched-away profile read UNSUPPORTED_BY_MODEL instead of a real
    # geometry-gated zero. Confirmed directly (see task-6-report.md);
    # this is current, real model behaviour, not something to route
    # around silently.
    state1_post_etch = advance_wafer_state(state1, stripped, "etching")
    q_etch = state1_post_etch.net_doping_at(R_ETCH_X, 0.0)
    print(f"  R_ETCH_X net_doping (queried immediately post-etch): "
          f"{q_etch.net_doping:.3e} (physics_status={q_etch.physics_status})")

    r2 = apply_gaussian_implant_doping(
        stripped, region="Si", junction_axis="x", peak_position_um=R_SAFE_X, straggle_um=0.3,
        **{safe_kwarg: 1e18, f"{safe_kwarg.split('_')[0]}_species": safe_species},
    )
    # The true final state -- both profiles present. R_SAFE_X's own
    # host_material ("Si") genuinely IS exposed there, so this query
    # takes the direct-apply branch regardless of last_step_category;
    # Problem 3 above never applies to this query.
    state2 = advance_wafer_state(state1_post_etch, r2, "doping")
    q_safe = state2.net_doping_at(R_SAFE_X, 0.0)
    print(f"  R_SAFE_X net_doping: {q_safe.net_doping:.3e} "
          f"(physics_status={q_safe.physics_status})")
    return q_etch, q_safe


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("=== Order 1: B at R_ETCH_X (erased), P at R_SAFE_X (survives) ===")
        q_etch_1, q_safe_1 = run_order(tmp, {
            "etch": ("acceptor_peak_conc_cm3", "B"),
            "safe": ("donor_peak_conc_cm3", "P"),
        })
    with tempfile.TemporaryDirectory() as tmp2:
        print("\n=== Order 2 (swapped): P at R_ETCH_X (erased), B at R_SAFE_X (survives) ===")
        q_etch_2, q_safe_2 = run_order(tmp2, {
            "etch": ("donor_peak_conc_cm3", "P"),
            "safe": ("acceptor_peak_conc_cm3", "B"),
        })

    # R_ETCH_X: whichever species was placed there before the etch is
    # erased either way -- both orders must read (near) zero there,
    # with NO physics_status gap (a real, physically meaningful zero,
    # not a hidden unsupported case).
    assert q_etch_1.physics_status is None and abs(q_etch_1.net_doping) < 1.0
    assert q_etch_2.physics_status is None and abs(q_etch_2.net_doping) < 1.0

    # R_SAFE_X: the SIGN must flip -- Order 1 ends with P (donor, positive)
    # surviving there; Order 2 ends with B (acceptor, negative) instead.
    print(f"\nR_SAFE_X net_doping: Order 1={q_safe_1.net_doping:.3e}, Order 2={q_safe_2.net_doping:.3e}")
    assert (q_safe_1.net_doping > 0) and (q_safe_2.net_doping < 0), (
        "swapping which species is assigned to the doomed (R_ETCH_X) vs safe "
        "(R_SAFE_X) role must flip R_SAFE_X's final polarity -- this is real "
        "geometry/state order-sensitivity, x-only, no depth claim involved"
    )
    print("\nOrder-sensitivity confirmed with real ViennaPS geometry: whichever species "
          "existed at the etched location is erased there regardless of order; the "
          "OTHER location's final species (and therefore polarity) depends entirely "
          "on which role each species was assigned -- a real, x-only, model-honest "
          "demonstration, not a claim about depth-selective physics.")


if __name__ == "__main__":
    main()
