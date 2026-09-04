#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spec CE-2, executable, x-only (no depth claim): a dopant whose Si is
CONSUMED by a real oxidation (Si -> SiO2 conversion AT A FIXED ABSOLUTE
COORDINATE) must report UNSUPPORTED_BY_MODEL for its fate there -- never
a silent geometry-gated 0. A SEPARATE profile, protected by a real
oxidation mask so its own x-position stays real Si, must still return
its real value (the partial-aggregate contract, spec Sec6).

Three real deviations from this task's own draft brief, all found by
actually running the code (not guessed), documented here and in
task-7-report.md:

Problem 1 (pre-flagged risk, confirmed): a plain, non-LOCOS thermal
oxidation's own `setInitialOxideThickness(max(0.002, grid_delta_um))`
seeds a real, resolvable native-oxide layer across the ENTIRE unmasked
exposed Si surface on the VERY FIRST oxidation call, regardless of
time_hours -- measured directly: even at 900C/0.01hr, a probe at
X_CONVERTED already showed SiO2 starting ~0.07um above the original
surface. So the brief's own two-oxidation-calls-on-one-domain draft
(recipe0 as "baseline Si", recipe1 as "real conversion") cannot produce
a genuine before-Si/after-SiO2 pair: recipe0 ITSELF already shows SiO2
at X_CONVERTED. Fixed by using a genuinely SEPARATE, non-oxidation
"before" reference (a real bare-Si wafer, no mask, no oxide, built the
same way test_wafer_state_real.py's own _bare_wafer() and CE-1's
_fresh_wafer() are -- via session.make_mask_spans(spans_um=[]), no
Process() call at all) for the honest "before: Si" claim at BOTH
x-positions, and a separate, real oxidation run for the "after" claim.
WaferState's own geometry construction is mesh-based, not domain-
identity-based (from_process_result's docstring: "GEOMETRY-ONLY"), so
this is legitimate: the "before" and "after" facts are each real and
independently verified, even though they come from two different real
ViennaPS meshes rather than one continuously-advected domain.

Problem 2 (new finding, not pre-flagged): masking a plain (non-LOCOS)
oxidation via mask_spans_um/remask_spans_um WITHOUT setting
mask_material reproduces the EXACT bug CLAUDE.md's own pinned memory
documents ("oxide grown on top of the photoresist mask... separated
from the silicon it supposedly grew from by the full thickness of the
resist") -- confirmed directly: a Mask box built via mask_spans_um,
left untouched by setMaskMaterial(), still gets a ~0.13um SiO2 seed
layer floating on TOP of the (undisturbed, still ~1um thick) Mask box,
because the model apparently treats the domain's own current top
surface as the growth candidate regardless of what material occupies
it when it hasn't been told which material is the mask. Passing
mask_material ALSO (to invoke setMaskMaterial() and get real physical
blocking) on a domain that was NOT built via the dedicated LOCOS
pad-oxide-first geometry (_build_locos_geometry) does invoke real
LOCOS mask/oxide-coupling physics (confirmed in the solver log) but its
export then crashes (ValueError from meshio reading a corrupt/empty
VTU) -- save_volume_mesh's generic exporter cannot handle a
LOCOS-shaped level-set stack that wasn't built via the dedicated
LOCOS-only construction (this is exactly the documented reason
save_locos_volume_mesh exists at all). So masking a real oxidation, in
this codebase today, REQUIRES the dedicated LOCOS path (fresh,
mask_material set, mask_left_um/mask_right_um, not mask_spans_um) --
confirmed to correctly block growth under the mask (Mask stays exactly
on top of an un-grown pad oxide there; the open window's oxide
genuinely thickens with real time/temperature).

Problem 3 (new finding, not pre-flagged): LOCOS's own pad-oxide-first
construction (module docstring, tcad/process/oxidation/thermal.py)
means a REAL, resolvable oxide layer sits across the ENTIRE wafer --
masked span included -- from the moment the geometry is built, before
any growth. So even after stripping the mask (domain.removeMaterial,
the same real API CE-1's own test and test_pr_strip_real.py already
verify), the masked span's topmost material is the pad oxide (SiO2),
never bare Si -- confirmed directly (exposed_material_at reported
"SiO2" there post-strip, not "Si"). Real LOCOS fab practice always
follows mask removal with a timed HF dip that clears the (thin, known)
pad oxide while barely touching the (much thicker) field oxide grown
in the open window. Implemented as a REAL, registered ViennaPS
`IsotropicProcess` etch (SiO2-selective, Si rate 0), run BLANKET
(no mask) across the whole wafer with a FIXED etch depth (0.19um,
chosen ahead of time, not measured from this run's own result --
see task-7-report.md) -- a real, standard mechanism (same
material_rates pattern CE-1's own test and test_wafer_state_real.py's
"etched through" case already use), and, being a real selective etch
rather than a hand-drawn box, it is naturally surface-relative and
self-limiting at the Si boundary exactly like a real HF dip: measured
with a CORRECTLY re-registered LOCOS export (see the paragraph below --
an earlier measurement using the un-re-registered, generic exporter
was itself wrong, see task-7-report.md "fix round 2"), the real pad
oxide is ~0.14um and the real field oxide, grown for long enough to
get genuine separation from it (1100C/8.0hr, up from an initial
1100C/2.0hr that left them too close together to trust -- see
task-7-report.md), is ~0.36um -- comfortable margin on both sides of
the fixed 0.19um cut (pad fully clears with ~0.05um to spare; ~0.16um
of field oxide survives). Because the removal amount is FIXED rather
than calibrated to what this run's mask happened to produce -- this is
what an EARLIER version of this test got wrong (see task-7-report.md,
"fix round 1") -- a mask that FAILED to protect X_PROTECTED (leaving
full field-thickness oxide there instead of the thin pad) would NOT be
fully cleared by this same fixed-depth etch, so `after_protected ==
"Si"` genuinely has the power to catch that failure rather than always
passing regardless of what the mask actually did.

A REAL LOCOS export subtlety this step must also handle (also found
only in review, see task-7-report.md, "fix round 1"): the LOCOS run
above registers an export hint recording a 3-material stack ([Si,
SiO2, Mask]); domain.removeMaterial(Mask) below drops that to 2
materials without updating the hint, so io.py's own hint-mismatch
guard would silently fall back to the generic WriteVisualizationMesh
exporter -- exactly the "topmost wins" path save_locos_volume_mesh()
exists to avoid for a wrapped (SiO2 wraps Si) stack like this one. The
hint is explicitly re-registered with the real, current 2-material
list before the etch runs (the etch step's own run() calls
save_volume_mesh() internally at the end, using whatever hint is
registered for that domain at that time).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401 -- registers "oxidation"/"thermal"
import tcad.process.etching  # noqa: F401 -- registers "etching"/"isotropic"
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state import WaferState
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh, register_locos_export

#: Fixed, pre-chosen SiO2 etch depth (um) for the real post-LOCOS pad-oxide
#: strip below -- NOT calibrated from any run's own measured result (that
#: would make the "after_protected == Si" check unable to detect a mask
#: that failed to protect the region -- see Problem 3, module docstring,
#: and task-7-report.md's "fix round 1"). Measured once, ahead of time,
#: against this exact recipe (with the LOCOS export hint correctly
#: re-registered post-strip -- an earlier measurement without that fix
#: was itself wrong, see task-7-report.md "fix round 2"): real pad oxide
#: ~0.14um (comfortably cleared, ~0.05um/35% margin), real field oxide
#: ~0.36um (~0.16um survives) with the 1100C/8.0hr growth below.
PAD_STRIP_DEPTH_UM = 0.19

GRID_UM = 0.2
X_EXTENT_UM, Y_EXTENT_UM, SI_DEPTH_UM = 10.0, 8.0, 5.0
X_CONVERTED, X_PROTECTED = 0.0, -3.5   # real ViennaPS domain x coordinates
WINDOW_HALF_UM = 1.0                   # LOCOS open (growth) window is x in [-1.0, +1.0];
                                        # the masked (protected) span is |x| > 1.0 -- X_CONVERTED
                                        # sits inside the window, X_PROTECTED well outside it.


def _bare_si_base(tmp):
    """A real bare-Si wafer -- no mask, no oxide, no process step run at
    all -- the honest 'before' reference for BOTH x positions (Problem
    1, module docstring). Same construction as
    test_wafer_state_real.py's own _bare_wafer() and CE-1's
    _fresh_wafer(): session.make_mask_spans(spans_um=[]), never
    touched by vps.Oxidation()'s own native-oxide seed."""
    domain = session.make_mask_spans(
        grid_delta_um=GRID_UM, x_extent_um=X_EXTENT_UM, y_extent_um=Y_EXTENT_UM,
        spans_um=[], mask_height_um=0.1, substrate_depth_um=SI_DEPTH_UM + 1.0,
    )
    mesh = save_volume_mesh(domain, str(Path(tmp) / "base"), floor_depth_um=SI_DEPTH_UM)
    return build_process_result({"final_mesh": mesh, "snapshots": []})


def _real_locos_oxidation_then_strip(tmp):
    """A real, two-step LOCOS oxidation (fresh + LOCOS-on-LOCOS, this
    project's own verified chaining mechanism -- see CLAUDE.md,
    "LOCOS-on-LOCOS -- RESOLVED") that genuinely grows field oxide in
    the OPEN window (covers X_CONVERTED) while a real mask blocks all
    growth in the OUTER span (covers X_PROTECTED) -- Problem 2, module
    docstring. Then a real mask strip plus a real, registered, blanket
    (no mask) SiO2-selective isotropic etch at a FIXED depth (Problem 3,
    module docstring) so the protected span ends up genuinely exposed Si
    again, exactly as a real LOCOS fab flow leaves it after its own
    post-mask-removal HF dip -- and so that check genuinely can fail if
    the mask did not do its job (see PAD_STRIP_DEPTH_UM's own comment)."""
    step0 = registry.get("oxidation", "thermal")()
    recipe0 = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        "mask_left_um": -WINDOW_HALF_UM, "mask_right_um": WINDOW_HALF_UM,
        "mask_material": "Mask", "pr_thickness_um": 1.0,
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": X_EXTENT_UM, "y_extent_um": Y_EXTENT_UM,
        "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
    }
    step0.run(recipe0, tmp)

    # NOTE (Minor finding, task-7 review): thermal.py's chained-LOCOS
    # path deliberately does NOT re-apply mask_left_um/mask_right_um --
    # it reuses the inherited, already-deformed mask from step0 as-is
    # (see thermal.py's own run(), "is_chained_locos" branch). Copying
    # them into recipe1 below is therefore inert for the geometry (the
    # real window stays wherever step0's mask ended up, which is not
    # exactly [-1.0, +1.0] once bird's-beak deformation is real) --
    # harmless here since X_CONVERTED=0.0/X_PROTECTED=-3.5 sit far from
    # that boundary either way, but WINDOW_HALF_UM below describes the
    # NOMINAL window step0 asked for, not the real deformed edge.
    recipe1 = dict(recipe0)
    # 8.0hr (not the originally-tried 2.0hr): needed for the field oxide
    # to grow genuinely thicker than the (fixed, un-grown) pad oxide --
    # see PAD_STRIP_DEPTH_UM's own comment for the real measured numbers
    # that drove this.
    recipe1["temperature_c"], recipe1["time_hours"] = 1100.0, 8.0
    step1 = registry.get("oxidation", "thermal")(inherited_domain=step0.last_domain)
    step1.run(recipe1, tmp)

    module = session.require_viennaps()
    domain = step1.last_domain
    domain.removeMaterial(module.Material.Mask)

    # Re-register the LOCOS export hint for the post-strip 2-material
    # stack (Important #2, task-7 review) -- see module docstring,
    # Problem 3.
    register_locos_export(domain, [module.Material.Si, module.Material.SiO2], [False, True])

    # Real, registered ViennaPS etch standing in for the real HF dip a
    # LOCOS flow performs after mask removal (Important #1/#3, task-7
    # review) -- see module docstring, Problem 3, and
    # PAD_STRIP_DEPTH_UM's own comment for why the depth is fixed ahead
    # of time rather than measured from this run.
    strip_step = registry.get("etching", "isotropic")(inherited_domain=domain)
    strip_recipe = {
        "material_rates": {"SiO2": -PAD_STRIP_DEPTH_UM, "Si": 0.0},
        "default_rate": 0.0,
        "etch_time_s": 1.0,
        "silicon_depth_um": SI_DEPTH_UM,
    }
    strip_result = strip_step.run(strip_recipe, tmp)

    return build_process_result({"final_mesh": strip_result["final_mesh"], "snapshots": []})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = _bare_si_base(tmp)
        base_state = WaferState.from_process_result(base)
        before_converted = base_state.exposed_material_at(X_CONVERTED)
        before_protected = base_state.exposed_material_at(X_PROTECTED)
        print(f"[before oxidation, real bare-Si wafer] X_CONVERTED={X_CONVERTED}: "
              f"{before_converted}, X_PROTECTED={X_PROTECTED}: {before_protected}")
        assert before_converted == "Si" and before_protected == "Si", (
            f"the honest 'before' baseline must be real, unconverted Si at BOTH "
            f"coordinates -- got X_CONVERTED={before_converted!r}, "
            f"X_PROTECTED={before_protected!r}"
        )

        n_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=X_CONVERTED,
            straggle_um=0.3, donor_peak_conc_cm3=1e18, donor_species="P",
        )
        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=X_PROTECTED,
            straggle_um=0.3, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state1 = advance_wafer_state(None, n_result, "doping")
        state1 = advance_wafer_state(state1, p_result, "doping")

        oxidized = _real_locos_oxidation_then_strip(tmp)
        oxidized_state = WaferState.from_process_result(oxidized)
        after_converted = oxidized_state.exposed_material_at(X_CONVERTED)
        after_protected = oxidized_state.exposed_material_at(X_PROTECTED)
        print(f"[after real LOCOS oxidation + mask/pad-oxide strip] "
              f"X_CONVERTED={X_CONVERTED}: {after_converted}, "
              f"X_PROTECTED={X_PROTECTED}: {after_protected}")
        assert after_converted != "Si", (
            f"X_CONVERTED must genuinely flip material (real field-oxide growth in "
            f"the open LOCOS window) -- got {after_converted!r}; if this fails, "
            f"temperature_c/time_hours need real tuning"
        )
        assert after_protected == "Si", (
            f"X_PROTECTED must read genuine, exposed Si after the real mask+pad-oxide "
            f"strip (proves the mask genuinely protected it from growth) -- got "
            f"{after_protected!r}"
        )

        state2 = advance_wafer_state(state1, oxidized, "oxidation")

        q_converted = state2.net_doping_at(X_CONVERTED, 0.0)
        print(f"[X_CONVERTED] donor={q_converted.donor_concentration}, "
              f"physics_status={q_converted.physics_status}")
        # Both halves of "never a silent zero" (spec Sec6): the raw
        # number really is excluded (0.0, not some partial value) AND
        # that exclusion is disclosed, not silent.
        assert q_converted.donor_concentration == 0.0
        assert q_converted.physics_status is not None
        assert q_converted.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"

        q_protected = state2.net_doping_at(X_PROTECTED, 0.0)
        print(f"[X_PROTECTED] donor={q_protected.donor_concentration:.3e}, "
              f"acceptor={q_protected.acceptor_concentration:.3e}, "
              f"physics_status={q_protected.physics_status}")
        assert q_protected.physics_status is None
        # > 1e17, not just > 0: pins the real, near-peak value (the B
        # profile is centered exactly at X_PROTECTED with a 1e18 cm^-3
        # peak) rather than being satisfied by a negligible tail alone.
        assert q_protected.acceptor_concentration > 1e17

        print("Oxidation's real Si->SiO2 conversion (at a fixed absolute x, mask-verified) "
              "correctly reports UNSUPPORTED_BY_MODEL for the consumed dopant's fate (never "
              "a silent 0), while a mask-protected profile elsewhere stays fully computable "
              "-- CE-2 confirmed, x-only, no depth-penetration claim made anywhere.")


if __name__ == "__main__":
    main()
