#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-duration oxidation, seen from WaferState. Pure Python -- no
ViennaPS/DevSim/Tk.

Two DIFFERENT results, never conflated:

* INHERITED IDENTITY  {"kind": "identity", ..., "inherited": True}
  The backend was handed the prior domain and returned it untouched, so the
  prior WaferState still describes it and `out is prior_state`.

* FRESH MATERIALIZATION  {"kind": "materialization", ..., "inherited": False,
  "initial_geometry": {material "Si", bounds_um, material_instance_id, grid}}
  The backend received NO domain and built a NEW virgin Si wafer. Nothing
  proves an earlier WaferState (bounds, material instances, lineage, dopant,
  grid) describes it, so a prior state is never returned:
    - no prior state -> a MODELLED initial state from the exact bounds;
    - a prior state  -> fail-closed (attachments -> unresolved ledger, no
      device-active query), even when the bounds happen to be equal.

A inherited identity preserves the prior state
B fresh materialization, no prior state -> exact initial WaferState
C fresh materialization + same-bounds doped prior -> fail-closed
D fresh materialization + different-bounds prior -> fail-closed
E fresh materialization + prior with extra SiN / SiO2 lineage -> fail-closed
F malformed materialization metadata -> never canonical; fail-closed
G no resurrection after a fresh-mismatch fail-closed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tcad.mesh.interface import ProcessResult
from tcad.physics.wafer_state_accumulation import (
    ZERO_DURATION_INHERITED_IDENTITY, advance_wafer_state,
    fresh_zero_duration_materialization_transition, initial_wafer_state_from_recipe,
    is_canonical_fresh_zero_duration_materialization,
    is_canonical_inherited_zero_duration_identity,
)
from tcad.physics.wafer_state_v2 import (
    GeometryTransform, attach_dopant, initialize_wafer_state, uniform_inventory_integral,
)

RECIPE = {"x_extent_um": 2.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.05}


def _fresh():
    return fresh_zero_duration_materialization_transition(RECIPE)


def _doped(recipe=None):
    s = initial_wafer_state_from_recipe(recipe or RECIPE)
    return attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1e17,
        support_instance_id=s.cells[0].material_instance_id,
        support_region_um=tuple(s.cells[0].bounds_um), model="uniform_v1",
        inventory_integral=uniform_inventory_integral(1e17), chemical_state="ACTIVE")


def _result(transition="__absent__"):
    md = {} if transition == "__absent__" else {"state_transition": transition}
    return ProcessResult(volume_mesh_path="x", metadata=md)


def _assert_fail_closed(prior, out, label):
    assert out is not prior, f"{label}: prior state returned"
    assert out.attachments == (), f"{label}: active attachment survived"
    assert prior.attachments and any(
        u.origin_attachment_id == prior.attachments[0].attachment_id
        for u in out.unresolved_inventory), f"{label}: dopant not ledgered"
    assert all(c.lifecycle != "ACTIVE" for c in out.cells if c in prior.cells or
               c.material_instance_id in {p.material_instance_id for p in prior.cells}), (
        f"{label}: a prior cell is still ACTIVE")
    return out


def test_A_inherited_identity_preserves():
    prior = _doped()
    out = advance_wafer_state(prior, _result(dict(ZERO_DURATION_INHERITED_IDENTITY)), "oxidation")
    assert out is prior
    assert len(out.attachments) == 1 and out.attachments[0].species == "P"
    q = out.net_doping_at(0.0, -0.5)
    assert q.net_doping == 1e17 and q.physics_status is None, q
    assert ZERO_DURATION_INHERITED_IDENTITY["inherited"] is True
    assert is_canonical_inherited_zero_duration_identity(ZERO_DURATION_INHERITED_IDENTITY)
    assert not is_canonical_fresh_zero_duration_materialization(ZERO_DURATION_INHERITED_IDENTITY)
    assert not is_canonical_inherited_zero_duration_identity(_fresh())
    print("PASS A: inherited identity -> out is prior_state, attachment + 1e17 query intact; "
          "the two schemas are mutually exclusive")


def test_B_fresh_no_prior_builds_exact_initial_state():
    t = _fresh()
    assert t["kind"] == "materialization" and t["inherited"] is False
    g = t["initial_geometry"]
    assert g["material"] == "Si" and g["bounds_um"] == [-1.0, 1.0, -1.0, 0.0]
    assert g["grid_delta_um"] == 0.05 and g["material_instance_id"] == "si#substrate"
    # y_extent_um / exporter floor never enter the substrate bounds
    t2 = fresh_zero_duration_materialization_transition(dict(RECIPE, y_extent_um=8.0))
    assert t2 == t
    out = advance_wafer_state(None, _result(t), "oxidation")
    assert len(out.cells) == 1
    c = out.cells[0]
    assert c.material == "Si" and c.lifecycle == "ACTIVE" and c.is_modelled
    assert tuple(c.bounds_um) == (-1.0, 1.0, -1.0, 0.0)
    assert c.material_instance_id == "si#substrate"
    assert out.attachments == () and out.unresolved_inventory == ()
    assert out.grid_delta_um == 0.05
    assert all(e.process_category == "initial_geometry" for e in out.events), out.events
    q = out.net_doping_at(0.0, -0.5)
    assert q.net_doping == 0.0 and q.physics_status is None, q      # known undoped
    # outside the substrate rectangle there is no claim either way
    assert out.cells[0].bounds_um == (-1.0, 1.0, -1.0, 0.0)
    print("PASS B: fresh materialization + no prior -> exactly one MODELLED Si cell from the "
          "transition's bounds, 0 attachments, undoped query 0.0, grid matches, only initial-geometry provenance")


def test_C_fresh_with_same_bounds_prior_fails_closed():
    prior = _doped()
    assert tuple(prior.cells[0].bounds_um) == tuple(_fresh()["initial_geometry"]["bounds_um"])
    out = advance_wafer_state(prior, _result(_fresh()), "oxidation")
    _assert_fail_closed(prior, out, "same bounds")
    q = out.net_doping_at(0.0, -0.5)
    assert q.net_doping is None and (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", q
    print("PASS C: fresh materialization + same-bounds doped prior -> NOT preserved, 0 active attachments, "
          "ledgered, query None/UNSUPPORTED_BY_MODEL (equal bounds do not prove equal history)")


def test_D_fresh_with_different_bounds_prior_fails_closed():
    prior = _doped({"x_extent_um": 4.0, "silicon_depth_um": 2.0, "grid_delta_um": 0.1})
    assert tuple(prior.cells[0].bounds_um) == (-2.0, 2.0, -2.0, 0.0)
    fresh = fresh_zero_duration_materialization_transition(
        {"x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": 0.05})
    assert fresh["initial_geometry"]["bounds_um"] == [-1.0, 1.0, -0.5, 0.0]
    out = advance_wafer_state(prior, _result(fresh), "oxidation")
    _assert_fail_closed(prior, out, "different bounds")
    # the old bounds are NOT silently re-labelled as the new wafer, and no
    # cell claims the new bounds
    assert all(tuple(c.bounds_um) != (-1.0, 1.0, -0.5, 0.0) for c in out.cells if c.bounds_um)
    for x, y in ((0.0, -0.25), (1.5, -1.5), (0.0, -1.5)):
        q = out.net_doping_at(x, y)
        assert q.net_doping is None and (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", (x, y, q)
    print("PASS D: fresh materialization + different-bounds prior (x[-2,2] y[-2,0] vs x[-1,1] y[-0.5,0]) -> "
          "not preserved, old bounds not linked to the new mesh, every device query blocked")


def test_E_fresh_with_extra_material_lineage_fails_closed():
    for material in ("SiN", "SiO2"):
        prior = _doped()
        dep = GeometryTransform("deposition", representable=True,
                                added_cells=((material, (-1.0, 1.0, 0.0, 0.1), f"inst_{material}"),))
        prior = advance_wafer_state(prior, _result(), "deposition", transform=dep)
        assert any(c.material == material and c.lifecycle == "ACTIVE" for c in prior.cells)
        assert prior.attachments, "the dopant must still be active before the fresh step"
        out = advance_wafer_state(prior, _result(_fresh()), "oxidation")
        assert out is not prior and out.attachments == ()
        extra = [c for c in out.cells if c.material == material]
        assert extra and all(c.lifecycle != "ACTIVE" for c in extra), (
            f"{material}: the extra cell was kept ACTIVE although the fresh mesh has only Si")
        assert all(c.lifecycle != "ACTIVE" for c in out.cells)
        for x, y in ((0.0, 0.05), (0.0, -0.5)):
            q = out.net_doping_at(x, y)
            assert q.net_doping is None and (q.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL", (material, x, y, q)
    print("PASS E: fresh materialization + prior with an added SiN/SiO2 cell -> the extra cell is not active, "
          "no electrical state survives, 0 invented continuity")


def _malformed_cases():
    good = _fresh()

    def mut(**top):
        return {**{k: (dict(v) if isinstance(v, dict) else v) for k, v in good.items()}, **top}

    def geo(**g):
        d = dict(good["initial_geometry"])
        d.update(g)
        return mut(initial_geometry=d)

    cases = [
        ("metadata absent", None),
        ("state_transition None", None),
        ("state_transition {}", {}),
        ("not a dict", [1, 2]),
        ("geometry descriptor absent", {k: v for k, v in good.items() if k != "initial_geometry"}),
        ("geometry descriptor None", mut(initial_geometry=None)),
        ("geometry descriptor a list", mut(initial_geometry=[1, 2])),
        ("extra top-level key", mut(extra=1)),
        ("extra geometry key", geo(extra=1)),
        ("bounds 3 values", geo(bounds_um=[-1.0, 1.0, -1.0])),
        ("bounds 5 values", geo(bounds_um=[-1.0, 1.0, -1.0, 0.0, 1.0])),
        ("bounds not a list", geo(bounds_um="abc")),
        ("bounds NaN", geo(bounds_um=[-1.0, float("nan"), -1.0, 0.0])),
        ("bounds +Inf", geo(bounds_um=[-1.0, float("inf"), -1.0, 0.0])),
        ("bounds -Inf", geo(bounds_um=[float("-inf"), 1.0, -1.0, 0.0])),
        ("bounds bool", geo(bounds_um=[-1.0, True, -1.0, 0.0])),
        ("bounds str", geo(bounds_um=[-1.0, "1.0", -1.0, 0.0])),
        ("x width zero", geo(bounds_um=[1.0, 1.0, -1.0, 0.0])),
        ("x width negative", geo(bounds_um=[1.0, -1.0, -1.0, 0.0])),
        ("y height zero", geo(bounds_um=[-1.0, 1.0, 0.0, 0.0])),
        ("y height negative", geo(bounds_um=[-1.0, 1.0, 0.0, -1.0])),
        ("material not Si", geo(material="SiO2")),
        ("material lower-case si", geo(material="si")),
        ("instance id differs", geo(material_instance_id="si#other")),
        ("grid missing", mut(initial_geometry={k: v for k, v in good["initial_geometry"].items()
                                               if k != "grid_delta_um"})),
        ("grid zero", geo(grid_delta_um=0.0)),
        ("grid negative", geo(grid_delta_um=-0.05)),
        ("grid NaN", geo(grid_delta_um=float("nan"))),
        ("grid Inf", geo(grid_delta_um=float("inf"))),
        ("grid bool", geo(grid_delta_um=True)),
        ("inherited False but kind identity", mut(kind="identity")),
        ("kind materialization but inherited True", mut(inherited=True)),
        ("inherited 0", mut(inherited=0)),
        ("inherited None", mut(inherited=None)),
        ("reason differs", mut(reason="zero_duration")),
        ("category differs", mut(category="etching")),
        ("kind unsupported", mut(kind="unsupported")),
    ]
    for key in good:
        cases.append((f"missing top-level {key}", {k: v for k, v in good.items() if k != key}))
    return cases


def test_F_malformed_materialization_metadata():
    cases = _malformed_cases()
    for label, transition in cases:
        assert not is_canonical_fresh_zero_duration_materialization(transition), f"{label}: accepted"
        assert not is_canonical_inherited_zero_duration_identity(transition), f"{label}: read as identity"
        res = _result() if label == "metadata absent" else _result(transition)
        # with a prior state: fail-closed
        prior = _doped()
        out = advance_wafer_state(prior, res, "oxidation")
        _assert_fail_closed(prior, out, label)
        # with no prior state: never a MODELLED initial state from broken metadata
        # (it may only take the legacy/unresolved mesh route, which needs a real mesh; here
        #  there is none, so building anything is refused rather than invented)
        try:
            out2 = advance_wafer_state(None, res, "oxidation")
        except Exception:
            continue
        assert not any(c.is_modelled and c.lifecycle == "ACTIVE" for c in out2.cells), (
            f"{label}: a MODELLED active cell was built from malformed metadata")
    # the builder itself refuses a recipe that cannot state its bounds
    for bad in ({}, {"x_extent_um": 2.0, "grid_delta_um": 0.05},
                {"x_extent_um": 2.0, "silicon_depth_um": 1.0},
                {"silicon_depth_um": 1.0, "grid_delta_um": 0.05},
                {"x_extent_um": 0.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.05},
                {"x_extent_um": 2.0, "silicon_depth_um": 0.0, "grid_delta_um": 0.05},
                {"x_extent_um": 2.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.0},
                {"x_extent_um": float("nan"), "silicon_depth_um": 1.0, "grid_delta_um": 0.05}):
        try:
            fresh_zero_duration_materialization_transition(bad)
        except ValueError:
            continue
        raise AssertionError(f"builder accepted {bad!r}")
    print(f"PASS F: {len(cases)} malformed materialization variants -> never canonical, never identity, "
          f"fail-closed with a prior, no MODELLED cell without one; builder refuses 8 unstatable recipes")


def test_G_no_resurrection_after_fresh_mismatch():
    prior = _doped()
    old_id = prior.attachments[0].attachment_id
    s1 = advance_wafer_state(prior, _result(_fresh()), "oxidation")
    assert s1.attachments == ()
    # a valid, explicit deposition afterwards
    dep = GeometryTransform("deposition", representable=True,
                            added_cells=(("SiN", (-1.0, 1.0, 0.0, 0.1), "inst_sin"),))
    s2 = advance_wafer_state(s1, _result(), "deposition", transform=dep)
    assert s2.attachments == () and all(a.attachment_id != old_id for a in s2.attachments)
    assert s2.net_doping_at(0.0, -0.5).net_doping is None, "old region regained a number"
    # an inherited identity afterwards returns that SAME fail-closed state and adds nothing
    s3 = advance_wafer_state(s1, _result(dict(ZERO_DURATION_INHERITED_IDENTITY)), "oxidation")
    assert s3 is s1 and s3.attachments == ()
    assert s3.net_doping_at(0.0, -0.5).net_doping is None
    # and a SECOND fresh materialization on the already-failed state adds nothing back either
    s4 = advance_wafer_state(s1, _result(_fresh()), "oxidation")
    assert s4.attachments == () and s4.net_doping_at(0.0, -0.5).net_doping is None
    # the ledger still remembers the dopant
    assert any(u.origin_attachment_id == old_id for u in s2.unresolved_inventory)
    print("PASS G: after a fresh-mismatch fail-closed, a valid deposition, an inherited identity and a "
          "second fresh materialization never resurrect the old attachment")


def main():
    test_A_inherited_identity_preserves()
    test_B_fresh_no_prior_builds_exact_initial_state()
    test_C_fresh_with_same_bounds_prior_fails_closed()
    test_D_fresh_with_different_bounds_prior_fails_closed()
    test_E_fresh_with_extra_material_lineage_fails_closed()
    test_F_malformed_materialization_metadata()
    test_G_no_resurrection_after_fresh_mismatch()
    print("\nALL ZERO-DURATION IDENTITY / MATERIALIZATION STATE-CONTRACT TESTS PASS")


if __name__ == "__main__":
    main()
