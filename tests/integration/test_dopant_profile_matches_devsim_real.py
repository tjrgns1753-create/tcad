#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The central canonical-state gate (Tier 1-1), for all 4 doping kinds,
on real DevSim: writes the exact right numbers when the canonical
geometry is known (Branch A), and refuses a non-canonical (v1) state
outright when it is not (Branch B).

History: this was the Stage A closing verification (2026-09-01),
Branch-A-only -- it built a v1 `WaferState` (one infinitely wide 'Si'
`_Cell`, no y_min, no material instance, no lifecycle) carrying each
kind's DopantProfiles, handed it to `apply_doping()`, and asserted
DevSim's stored NetDoping matched `WaferState.net_doping_at()` at every
node. Tier 1-1's canonical-state gate (`doping_mapping.
canonical_node_doping`) made that path unreachable: it accepts only a
canonical `WaferStateV2` and checks, per node, exactly one ACTIVE +
MODELLED owning cell of the region's material before it trusts a
number, so a v1 state has nothing to check ownership against and is
refused outright -- this file's first Tier 1-1 revision replaced the
whole file with that refusal (Branch B), which is real and worth
keeping, but on its own is a WEAKER check than the original: it never
again proves apply_doping() writes the CORRECT number for any kind.
Both branches now live here, printed and asserted separately.

Branch A (restored, on a canonical WaferStateV2 this time): an explicit-
rectangle virgin Si wafer -- the same construction
test_wafer_state_v2_initial_geometry_devsim_real.py uses --
`initial_wafer_state_from_recipe()` -> `advance_wafer_state(...,
"doping")` -> real DevSim import -> `apply_doping()`. For each of
uniform, step_junction, gaussian_implant, implant_windows (every one
exercising a real donor/acceptor split, not just a signed net), the
real Donors/Acceptors/NetDoping DevSim wrote are compared, at EVERY
node, against a SEPARATELY hand-written closed-form formula for that
kind (not calling into tcad.physics.dopant_profile or
tcad.physics.wafer_state_v2 at all) -- a genuine second implementation,
the same kind of independent check the original 2026-09-01 test made,
just against the canonical-state write path instead of the retired v1
one. No None/NaN/Inf anywhere.

Branch B (unchanged in substance from the first Tier 1-1 revision): the
same 4 kinds, geometry from a REAL ViennaPS isotropic etch (a curved
front with no exact 2D bounds), carried on a v1 `WaferState` --
`apply_doping()` must refuse it outright: `UnsupportedDopingState`,
every node blocked, 0 doping node models written, 0 solves, 0 leaked
devices.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState, _Cell
from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import UnsupportedDopingState, apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

# ---------------------------------------------------------------------------
# Branch A: canonical geometry, real DevSim write vs. an independent formula
# ---------------------------------------------------------------------------

#: Same explicit-rectangle virgin-Si recipe as
#: test_wafer_state_v2_initial_geometry_devsim_real.py -- x in
#: [-2, 2], y in [-2, 0].
A_RECIPE = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
A_SCALE = 1.0e-4  # um -> cm


def _virgin_rectangle_process_result(tmp):
    from tcad.backends.viennaps import session as _session
    from tcad.backends.viennaps.io import save_volume_mesh

    domain = _session.make_mask_spans(
        grid_delta_um=A_RECIPE["grid_delta_um"], x_extent_um=A_RECIPE["x_extent_um"],
        y_extent_um=A_RECIPE["y_extent_um"], spans_um=[], mask_height_um=0.1,
        substrate_depth_um=A_RECIPE["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, str(Path(tmp) / "virgin"), floor_depth_um=A_RECIPE["silicon_depth_um"])
    return build_process_result({"final_mesh": mesh_path, "snapshots": []})


def _independent_uniform(donor, acceptor):
    def f(x, y):
        return donor, acceptor, donor - acceptor
    return f


def _independent_step_junction(donor, acceptor, position):
    def f(x, y):
        d = donor if x >= position else 0.0
        a = acceptor if x <= position else 0.0
        return d, a, d - a
    return f


def _independent_gaussian(donor_peak, acceptor_peak, position, straggle):
    """gaussian_implant's own real semantics (dopant_profile.py's
    `_gaussian_implant_profiles`, module docstring 'deliberately does
    not handle donor+acceptor split'): donor_peak/acceptor_peak combine
    into ONE net peak = donor_peak - acceptor_peak BEFORE the Gaussian
    shape is applied, and the result is a SINGLE-polarity profile (all
    donor where the net is positive, all acceptor where negative) -- not
    two independent Gaussian humps subtracted node-by-node."""
    net_peak = donor_peak - acceptor_peak

    def f(x, y):
        shape = math.exp(-((x - position) ** 2) / (2.0 * straggle ** 2))
        net = net_peak * shape
        return (net, 0.0, net) if net >= 0.0 else (0.0, -net, net)
    return f


def _independent_windows(bg_donor, bg_acceptor, donor_windows, acceptor_windows):
    def f(x, y):
        d = bg_donor + sum(c for lo, hi, c in donor_windows if lo <= x <= hi)
        a = bg_acceptor + sum(c for lo, hi, c in acceptor_windows if lo <= x <= hi)
        return d, a, d - a
    return f


def _check_branch_a(label, doped_result, independent_formula, boundaries=()):
    """Real canonical-state write vs. an independently-written formula,
    at every real DevSim node EXCEPT one lying exactly on a
    `boundaries` x-coordinate -- a step-function discontinuity
    (junction position or an implant-window edge) where `_step()`'s own
    `>=`/`<=` split has a known, DELIBERATELY UNTOUCHED-this-round
    boundary-node ambiguity (see wafer_state_v2.py's `_covered_by`/
    half-open-boundary notes and CLAUDE.md's OPEN items; called Tier 2
    territory in review). Excluding it is a real, reported gap in
    coverage, not a silent one -- this function returns and PRINTS both
    `checked` (nodes actually compared) and `total` (every real DevSim
    node in the region), so "all N nodes matched" is never claimed when
    N is actually `total - len(boundaries)`."""
    state = initial_wafer_state_from_recipe(A_RECIPE)
    state = advance_wafer_state(state, doped_result, "doping")
    assert state.attachments, f"{label}: fixture is broken -- no attachment was created"

    imported = import_process_result(
        doped_result, mesh_name=f"a_{label}_mesh", device_name=f"a_{label}_device",
        contact_regions=["Si"], contact_axis="x", length_scale_to_cm=A_SCALE,
    )
    try:
        apply_doping(imported.device, "Si", state, length_scale_to_cm=A_SCALE)

        xs = [x / A_SCALE for x in devsim.get_node_model_values(device=imported.device, region="Si", name="x")]
        ys = [y / A_SCALE for y in devsim.get_node_model_values(device=imported.device, region="Si", name="y")]
        donors = devsim.get_node_model_values(device=imported.device, region="Si", name="Donors")
        acceptors = devsim.get_node_model_values(device=imported.device, region="Si", name="Acceptors")
        nets = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

        checked = 0
        skipped = 0
        max_rel_error = 0.0
        total = len(xs)
        for x, y, d_dev, a_dev, n_dev in zip(xs, ys, donors, acceptors, nets):
            for v in (d_dev, a_dev, n_dev):
                assert math.isfinite(v), f"{label}: non-finite DevSim value {v} at x={x}"
            if boundaries and any(x == b for b in boundaries):
                skipped += 1
                continue
            d_exp, a_exp, n_exp = independent_formula(x, y)
            for name, dev_v, exp_v in (("Donors", d_dev, d_exp), ("Acceptors", a_dev, a_exp), ("NetDoping", n_dev, n_exp)):
                assert math.isfinite(exp_v)
                denom = max(abs(exp_v), 1.0)
                rel = abs(dev_v - exp_v) / denom
                max_rel_error = max(max_rel_error, rel)
                assert rel < 1e-9, (
                    f"{label}: {name} mismatch at x={x:.4g},y={y:.4g}: devsim={dev_v!r} "
                    f"independent={exp_v!r} rel_error={rel:.3e}")
            checked += 1
        assert checked > 0, f"{label}: no nodes checked"
        assert checked + skipped == total
        scope = (f"{checked}/{total} non-discontinuity nodes (Tier 2: the {skipped} node(s) exactly on a "
                 f"junction/window-edge discontinuity at x in {list(boundaries)} are excluded from this "
                 f"check, not verified here)") if boundaries else f"all {checked}/{total} nodes"
        print(f"[Branch A][{label}] {scope} checked against an independent formula, "
              f"max relative error {max_rel_error:.3e}")
        return checked, skipped, total
    finally:
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)


def _run_branch_a():
    totals = {}

    # uniform, donor/acceptor split
    with tempfile.TemporaryDirectory() as tmp:
        result = _virgin_rectangle_process_result(tmp)
        donor, acceptor = 1.0e16, 3.0e15
        doped = apply_uniform_doping(result, donor_by_region_cm3={"Si": donor}, acceptor_by_region_cm3={"Si": acceptor}, chemical_state="ACTIVE")
        totals["uniform"] = _check_branch_a("uniform", doped, _independent_uniform(donor, acceptor))

    # step_junction, donor/acceptor split
    with tempfile.TemporaryDirectory() as tmp:
        result = _virgin_rectangle_process_result(tmp)
        donor, acceptor, position = 1.0e18, 1.0e18, 0.0
        doped = apply_step_junction_doping(
            result, region="Si", junction_axis="x", junction_position_um=position,
            donor_conc_cm3=donor, acceptor_conc_cm3=acceptor, chemical_state="ACTIVE",
        )
        totals["step_junction"] = _check_branch_a(
            "step_junction", doped, _independent_step_junction(donor, acceptor, position),
            boundaries=[position])

    # gaussian_implant, donor/acceptor split
    with tempfile.TemporaryDirectory() as tmp:
        result = _virgin_rectangle_process_result(tmp)
        donor_peak, acceptor_peak, position, straggle = 2.0e18, 1.0e17, 0.0, 0.5
        doped = apply_gaussian_implant_doping(
            result, region="Si", junction_axis="x", peak_position_um=position, straggle_um=straggle,
            donor_peak_conc_cm3=donor_peak, acceptor_peak_conc_cm3=acceptor_peak, chemical_state="ACTIVE",
        )
        totals["gaussian_implant"] = _check_branch_a(
            "gaussian_implant", doped,
            _independent_gaussian(donor_peak, acceptor_peak, position, straggle))

    # implant_windows: donor background + a donor window + an acceptor
    # window (exercises both polarities' window path, not just background).
    with tempfile.TemporaryDirectory() as tmp:
        result = _virgin_rectangle_process_result(tmp)
        bg_donor = 1.0e15
        donor_windows = [(-1.6, -0.6, 1.0e20)]
        acceptor_windows = [(0.6, 1.6, 5.0e19)]
        doped = apply_implant_windows_doping(
            result, region="Si", axis="x", donor_background_cm3=bg_donor,
            windows=[
                {"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1.0e20},
                {"min_um": 0.6, "max_um": 1.6, "acceptor_conc_cm3": 5.0e19},
            ], chemical_state="ACTIVE",
        )
        totals["implant_windows"] = _check_branch_a(
            "implant_windows", doped,
            _independent_windows(bg_donor, 0.0, donor_windows, acceptor_windows),
            boundaries=[-1.6, -0.6, 0.6, 1.6])

    assert devsim.get_device_list() == (), "Branch A leaked a device"
    total_checked = sum(c for c, s, t in totals.values())
    total_skipped = sum(s for c, s, t in totals.values())
    total_nodes = sum(t for c, s, t in totals.values())
    skip_detail = ", ".join(f"{k}={s}" for k, (c, s, t) in totals.items() if s)
    print(f"Branch A PASS: canonical-state apply_doping() writes match an independently-written "
          f"formula at {total_checked}/{total_nodes} real DevSim nodes across all 4 doping kinds "
          f"(donor/acceptor split included); no None/NaN/Inf. {total_skipped} node(s) excluded as "
          f"Tier 2 discontinuity boundaries, not verified here ({skip_detail or 'none'}).")


# ---------------------------------------------------------------------------
# Branch B: a real curved etch front has no canonical geometry -- a v1
# state must be refused outright, not silently written.
# ---------------------------------------------------------------------------

B_RECIPE = {
    "grid_delta_um": 0.1,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.3,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}


def _fresh_etched_process_result():
    """Run a fresh etch step in its own temp directory and build the
    ProcessResult. Returns (result, temp_dir). Caller must cleanup temp_dir."""
    step_cls = registry.get("etching", "isotropic")
    tmp = tempfile.TemporaryDirectory()
    try:
        step_result = step_cls().run(B_RECIPE, tmp.name)
        result = build_process_result(step_result)
        return result, tmp
    except:
        tmp.cleanup()
        raise


def _check_branch_b(label, doped_result):
    """Import into a fresh DevSim device, hand apply_doping() a v1
    WaferState built from a real curved-etch mesh, and require the gate
    to refuse it before any doping node model exists."""
    imported = import_process_result(
        doped_result, mesh_name=f"b_{label}_mesh", device_name=f"b_{label}_device",
        contact_regions=["Si"], contact_axis="x",
    )
    try:
        profiles = dopant_profiles_from_doping_profile(doped_result.doping)
        state = WaferState(materials=("Si",), stack=(), grid_delta_um=0.1,
                           _cells=(_Cell(-1e9, 1e9, 1.0, "Si"),), _thin_x=(),
                           dopant_profiles=profiles)
        assert state.net_doping_at(0.0, 0.0).net_doping is not None, (
            f"{label}: fixture is broken -- the v1 query must still offer a number")

        try:
            apply_doping(imported.device, "Si", state)
        except UnsupportedDopingState as exc:
            text = str(exc)
            status = exc.physics_status
        else:
            raise AssertionError(f"{label}: a v1 WaferState reached DevSim through apply_doping()")
        assert "not a canonical WaferStateV2" in text and "First blocked node: x=" in text, text
        assert status["blocked_nodes"] == status["total_nodes"] > 0, status

        for model in ("Donors", "Acceptors", "NetDoping"):
            try:
                devsim.get_node_model_values(device=imported.device, region="Si", name=model)
            except devsim.error:
                continue
            raise AssertionError(f"{label}: {model} node model exists although the gate blocked")

        print(f"[Branch B][{label}] v1 WaferState refused: {status['blocked_nodes']} of "
              f"{status['total_nodes']} nodes blocked, no doping node model created")
    finally:
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)


def _run_branch_b():
    # uniform, donor/acceptor split
    result, tmp = _fresh_etched_process_result()
    try:
        doped = apply_uniform_doping(
            result, donor_by_region_cm3={"Si": 1.0e16},
            acceptor_by_region_cm3={"Si": 3.0e15}, chemical_state="ACTIVE",
        )
        _check_branch_b("uniform", doped)
    finally:
        tmp.cleanup()

    # step_junction
    result, tmp = _fresh_etched_process_result()
    try:
        doped = apply_step_junction_doping(
            result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1.0e18, acceptor_conc_cm3=1.0e18, chemical_state="ACTIVE",
        )
        _check_branch_b("step_junction", doped)
    finally:
        tmp.cleanup()

    # gaussian_implant, donor/acceptor split
    result, tmp = _fresh_etched_process_result()
    try:
        doped = apply_gaussian_implant_doping(
            result, region="Si", junction_axis="x",
            peak_position_um=0.0, straggle_um=0.5,
            donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=1.0e17, chemical_state="ACTIVE",
        )
        _check_branch_b("gaussian_implant", doped)
    finally:
        tmp.cleanup()

    # implant_windows, background + one window
    result, tmp = _fresh_etched_process_result()
    try:
        doped = apply_implant_windows_doping(
            result, region="Si", axis="x",
            background_doping_cm3=-1.0e17,
            windows=[{"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20}], chemical_state="ACTIVE",
        )
        _check_branch_b("implant_windows", doped)
    finally:
        tmp.cleanup()

    assert devsim.get_device_list() == (), (
        "a device leaked past cleanup -- would poison a later, "
        "unrelated solve (see CLAUDE.md's documented DevSim-lifecycle trap)"
    )
    print("Branch B PASS: a v1 WaferState carrying each of the 4 doping kinds is refused by the "
          "central canonical-state gate on a real etched mesh: every node blocked, "
          "no doping node model written.")


def main():
    _run_branch_a()
    print()
    _run_branch_b()


if __name__ == "__main__":
    main()
