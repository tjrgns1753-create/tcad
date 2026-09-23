"""Oxidation state-transition contracts shared by ThermalOxidation and
LocosOxidation: zero-duration is an exact IDENTITY on an inherited
wafer (the prior domain is returned untouched) and a MATERIALIZATION of the
recipe's own virgin Si wafer on a fresh step (a new domain: NOT an identity,
so no earlier WaferState is assumed to describe it); positive duration is
UNSUPPORTED_BY_MODEL in Phase 1 (see
docs/audits/2026-09-18-tier1-2-oxidation-positive-support/REPORT.md
Rev.2) -- no production capability certificate yet proves geometry
provenance/coverage/thickness/exporter-topology for an arbitrary
positive-time oxidation request, so none is attempted.

A step that has NO inherited domain (a "fresh" step) still has to hand
back some geometry. It hands back the recipe's own virgin Si wafer and
NOTHING else: no SiO2, no Mask, no LOCOS pad/mask stack, no grid-floored
seed. A zero-duration or unsupported oxidation must never invent a
structure the user did not ask for, and a failed step must never change
its input structure (see `virgin_si_domain()`)."""
import math
from pathlib import Path

from tcad.backends.viennaps.io import SnapshotRecorder, save_volume_mesh, DEFAULT_FLOOR_DEPTH_UM
from tcad.physics.wafer_state_accumulation import (
    ZERO_DURATION_INHERITED_IDENTITY, fresh_zero_duration_materialization_transition,
)

#: Set by run() ONLY for the cases explicitly proven safe:
#: (1) an inherited domain re-exported unchanged (`inherited_identity`, an
#:     IDENTITY: the backend domain is the prior domain),
#: (2) a virgin Si wafer materialized from the recipe's own bounds with
#:     nothing done to it (`fresh_materialization`, a MATERIALIZATION -- NOT an
#:     identity: the backend built a new domain, so no earlier WaferState is
#:     known to describe it), (3) UNSUPPORTED_BY_MODEL.
#: Never for a real oxidation result. The schemas live in
#: tcad.physics.wafer_state_accumulation, the one place that decides what each
#: means, so producer and consumer cannot drift apart.
IDENTITY_TRANSITION = ZERO_DURATION_INHERITED_IDENTITY


def duration_hours(recipe):
    duration = float(recipe["time_hours"])
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Oxidation time_hours must be finite and nonnegative")
    return duration


def virgin_si_domain(step, recipe):
    """The recipe's own bare Si wafer, for a step that has no inherited
    domain -- and nothing else.

    Only the wafer bounds are read (grid, x/y extent, silicon depth). The
    recipe's mask keys (`mask_spans_um`, `mask_left_um`/`mask_right_um`,
    `mask_material`, `pr_thickness_um`), its `pad_oxide_thickness_um` and
    its `remask_spans_um` are deliberately NOT forwarded: with no mask key
    at all, `ProcessStep.prepare_domain()` builds a bare Si wafer
    (`mask_spans_um=[]` -- no mask level set is inserted), which is the
    neutral construction this needs. No oxide, no mask and no LOCOS stack
    is created, and `LocosOxidation._build_locos_geometry()` (whose pad
    oxide is floored at the grid) is never reached.
    """
    bounds = {k: recipe[k] for k in
              ("grid_delta_um", "x_extent_um", "y_extent_um", "silicon_depth_um")
              if k in recipe}
    return step.prepare_domain(bounds)


def _export_unchanged(step, geometry, recipe, output_dir, snapshot_label, mesh_name):
    step.last_domain = geometry
    recorder = SnapshotRecorder(output_dir)
    recorder.capture(geometry, snapshot_label)
    mesh = save_volume_mesh(
        geometry, Path(output_dir) / mesh_name,
        floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
    )
    return mesh, recorder.snapshots


def fresh_materialization(step, recipe, output_dir):
    """Zero-duration oxidation with no inherited domain: materialize the
    recipe's virgin Si wafer, change nothing, and report exactly that geometry
    (`kind="materialization"`, `inherited=False`, the exact bounds). This is
    not an oxidation result and NOT an identity: no prior domain was handed
    over, so nothing proves an earlier WaferState describes what was built.

    The transition (and so the recipe's bounds) is validated BEFORE any
    geometry exists; a recipe that cannot state `x_extent_um`,
    `silicon_depth_um` and `grid_delta_um` raises ValueError instead of
    guessing a substrate."""
    transition = fresh_zero_duration_materialization_transition(recipe)
    geometry = virgin_si_domain(step, recipe)
    mesh, snapshots = _export_unchanged(
        step, geometry, recipe, output_dir,
        "000_zero_duration_fresh_wafer", "oxidation_zero_duration")
    return {
        "final_mesh": mesh, "snapshots": snapshots,
        "state_transition": transition,
    }


def inherited_identity(step, recipe, output_dir):
    """Export the existing domain without preparation, remasking or solving."""
    geometry = step._inherited_domain
    step.last_domain = geometry
    recorder = SnapshotRecorder(output_dir)
    recorder.capture(geometry, "000_zero_duration_identity")
    mesh = save_volume_mesh(
        geometry, Path(output_dir) / "oxidation_zero_duration",
        floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
    )
    return {
        "final_mesh": mesh, "snapshots": recorder.snapshots,
        "state_transition": dict(IDENTITY_TRANSITION),
    }


def unsupported_positive_time(step, recipe, output_dir, *, reason_code, note):
    """Phase 1 fail-closed result for a positive-time oxidation request
    (`time_hours > 0`) -- the ViennaPS oxidation solver is never invoked,
    `setInitialOxideThickness()` is never called, and no grid-dependent
    seed/pad-oxide geometry is created.

    Exports whatever geometry ALREADY exists rather than an "oxidation
    result": an inherited domain is re-exported completely unchanged
    (identical mechanism to `inherited_identity()` above, just tagged
    "unsupported" instead of "identity" -- the two must never be
    confused, see wafer_state_accumulation.advance_wafer_state's exact
    dict-equality check against IDENTITY_TRANSITION only). A FRESH
    request (no inherited domain) has no prior geometry to preserve, so
    only the recipe's virgin Si wafer is built (`virgin_si_domain()`): no
    SiO2, no Mask (the recipe's mask keys are NOT applied -- a failed
    request must not create the structure it was asked to oxidize around),
    no LOCOS pad/mask stack -- never treated as an "oxidation succeeded"
    result.
    """
    if step._inherited_domain is not None:
        geometry = step._inherited_domain
    else:
        geometry = virgin_si_domain(step, recipe)
    step.last_domain = geometry

    recorder = SnapshotRecorder(output_dir)
    recorder.capture(geometry, "000_positive_time_unsupported")
    mesh = save_volume_mesh(
        geometry, Path(output_dir) / "oxidation_unsupported",
        floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
    )
    return {
        "final_mesh": mesh, "snapshots": recorder.snapshots,
        "physics_status": {
            "resolution": "UNSUPPORTED_BY_MODEL",
            "entries": [{
                "parameter": "positive_time_oxidation",
                "material": "Si/SiO2",
                "resolution": "UNSUPPORTED_BY_MODEL",
                "provenance": "VIENNAPS_4_6_2_CAPABILITY_AUDIT",
                "note": note,
            }],
            "reason_code": reason_code,
            "requested_initial_oxide_um": recipe.get("pad_oxide_thickness_um"),
            "grid_delta_um": recipe.get("grid_delta_um"),
            "measured_min_oxide_um": None,
        },
        "state_transition": {
            "kind": "unsupported",
            "category": "oxidation",
            "reason": reason_code,
        },
    }
