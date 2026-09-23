# -*- coding: utf-8 -*-
"""
CE-1, WaferState v2 contract: a real, masked ViennaPS isotropic etch
produces a CURVED sidewall front -- not an axis-aligned rectangle, so
the process layer cannot hand advance_wafer_state() a
`representable=True` GeometryTransform for it. The step is therefore
advanced with NO transform, which is the fail-closed path: the etched
region's dopant fate is `UNSUPPORTED_BY_MODEL`, NEVER a geometry-gated
zero, and the post-etch geometry is UNRESOLVED so a subsequent doping
call over it cannot produce a known active value either.

This replaces the old `last_step_category`-based demonstration ("an
etch means 0 there"): that flat heuristic is retired (design doc
2026-09-10 Sec7.4). What CE-1 now pins is exactly the honest v2
behaviour -- a real non-representable geometry step makes the dopant
state unresolvable, and v2 says so rather than inventing a number.

The real ViennaPS work is unchanged: a blanket base etch (Problem 1),
then a masked window etch that removes Si completely at R_ETCH_X, then
a real mask strip (`domain.removeMaterial()`) so R_SAFE_X is exposed
Si again -- all printed and geometry-checked below, not assumed.
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


def run_order(tmp):
    """Real ViennaPS: implant Si at R_ETCH_X, then a real masked etch
    removes it there (curved front -> no representable transform), then
    implant at R_SAFE_X. Returns (q_etch, q_safe, exposed_after,
    exposed_safe_after)."""
    step, base = _fresh_wafer(tmp)
    r1 = apply_gaussian_implant_doping(
        base, region="Si", junction_axis="x", peak_position_um=R_ETCH_X,
        straggle_um=0.3, acceptor_peak_conc_cm3=1e18, acceptor_species="B", chemical_state="ACTIVE",
    )
    state1 = advance_wafer_state(None, r1, "doping")
    print(f"[state1] attachments={len(state1.attachments)} "
          f"unresolved={len(state1.unresolved_inventory)}")

    pre_etch_state = WaferState.from_process_result(base)
    print(f"[pre-etch] exposed at R_ETCH_X={R_ETCH_X}: "
          f"{pre_etch_state.exposed_material_at(R_ETCH_X)}")

    stripped = _real_etch_and_strip(tmp, step.last_domain)
    post = WaferState.from_process_result(stripped)
    exposed_after = post.exposed_material_at(R_ETCH_X)
    exposed_safe_after = post.exposed_material_at(R_SAFE_X)
    print(f"[post-etch+strip] R_ETCH_X -> {exposed_after}  R_SAFE_X -> {exposed_safe_after}")

    # A real masked ViennaPS etch: curved sidewall, NOT an axis-aligned
    # rectangle -> no representable GeometryTransform -> fail-closed.
    state1_post_etch = advance_wafer_state(state1, stripped, "etching", transform=None)
    q_etch = state1_post_etch.net_doping_at(R_ETCH_X, 0.0)
    print(f"  R_ETCH_X net_doping post-etch: {q_etch.net_doping} "
          f"(physics_status={None if q_etch.physics_status is None else q_etch.physics_status['resolution']})")

    r2 = apply_gaussian_implant_doping(
        stripped, region="Si", junction_axis="x", peak_position_um=R_SAFE_X,
        straggle_um=0.3, donor_peak_conc_cm3=1e18, donor_species="P", chemical_state="ACTIVE",
    )
    state2 = advance_wafer_state(state1_post_etch, r2, "doping")
    q_safe = state2.net_doping_at(R_SAFE_X, 0.0)
    print(f"  R_SAFE_X net_doping: {q_safe.net_doping} "
          f"(physics_status={None if q_safe.physics_status is None else q_safe.physics_status['resolution']})")
    return q_etch, q_safe, exposed_after, exposed_safe_after


def main():
    with tempfile.TemporaryDirectory() as tmp:
        q_etch, q_safe, exposed_after, exposed_safe_after = run_order(tmp)

    # Real geometry: the masked etch removed Si at R_ETCH_X; R_SAFE_X
    # stays exposed Si.
    assert exposed_after != "Si", (
        f"the masked etch must remove Si at R_ETCH_X -- got {exposed_after!r}")
    assert exposed_safe_after == "Si", (
        f"R_SAFE_X must read exposed Si after the etch+strip -- got {exposed_safe_after!r}")

    # v2 fail-closed contract (design doc Sec7.4): a real curved etch is
    # not a representable GeometryTransform, so the etched region's
    # dopant fate is UNSUPPORTED_BY_MODEL -- NOT a geometry-gated zero.
    assert q_etch.physics_status is not None, (
        "a real non-representable etch must report UNSUPPORTED_BY_MODEL at the "
        "etched location, not a silent zero (the old last_step_category "
        "heuristic is retired)")
    assert q_etch.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert q_etch.net_doping is None, "UNSUPPORTED must give net_doping None, not 0.0"

    # After a fail-closed step the geometry is UNRESOLVED, so a further
    # doping call over it cannot produce a known active value either.
    assert q_safe.physics_status is not None
    assert q_safe.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert q_safe.net_doping is None

    print()
    print("CE-1 (v2): a real masked ViennaPS etch (curved front, no representable "
          "GeometryTransform) makes the dopant state unresolvable -- the etched "
          "region and any later doping over the resulting geometry both read "
          "UNSUPPORTED_BY_MODEL, never an invented zero or value.")


if __name__ == "__main__":
    main()
