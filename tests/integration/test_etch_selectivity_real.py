#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-material etch selectivity -- real ViennaPS 4.6.2, through the actual
production entry points (registry -> DirectionalEtch / IsotropicEtch .run()),
on an EXPLICIT INITIAL Si/SiO2 stack with an EXPLICIT test mask.

Fixture provenance: DIRECT_EXPLICIT_GEOMETRY (tests/integration/_explicit_etch_fixture.py).
The SiO2 and the mask are structures this test STATES as inputs before any etch. The SiO2 is
NOT an oxidation growth result, NOT a deposited oxide, NOT a Deal-Grove result, and nothing
here says anything about oxidation kinetics or Si consumption. What is verified is how the
etch models treat materials.

Guards the optional `material_rates` recipe key of tcad/process/etching/{directional,isotropic}.py.
The two ViennaPS overloads DISAGREE on sign (Directional's materialRates removes for POSITIVE
rates, so the wrapper flips the recipe's sign; Isotropic's removes for NEGATIVE, so it must not).
A wrong sign is a SILENT no-op, so a regression looks like "the etch did nothing".

For BOTH models, from two INDEPENDENT copies of one saved post-mask/pre-etch state:
  unselective control : one rate for every non-mask material
  selective recipe    : SiO2 fast, Si slow (SELECTIVITY : 1), mask 0
Both clear the oxide and bite into Si. Verdicts are read at the CENTRAL CORE of the open
window (beyond every mask-edge effect) from the NATIVE level-set positions; the exported mesh is
reported alongside as a separate, corroborating view (it carries a grid-proportional exporter
representation offset of unidentified cause, never read as growth or Si consumption).

Expected values come from the recipe, INCLUDING the time spent clearing the oxide:
    t_clear  = Hox / |R_ox|
    Si depth = |R_si| * max(0, T - t_clear)
(not "total etch budget / selectivity"). Areas are not used for any verdict.
"""

import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcad.backends.viennaps import session as viennaps_session

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

import _explicit_etch_fixture as fx

# ---- explicit INPUT geometry (requested values; chosen before any measurement) -------------
GRID_UM = 0.05
X_EXTENT_UM = 8.0
Y_EXTENT_UM = 3.0
SILICON_DEPTH_UM = 3.0
OXIDE_UM = 0.2                    # Hox: 4 grid cells, a stated input, not a grown thickness
MASK_HEIGHT_UM = 0.5
MASK_MATERIAL = "Mask"
WINDOW_HALF_UM = 2.0              # open window x in [-2, 2]
MASK_SPANS_UM = [(-X_EXTENT_UM / 2.0, -WINDOW_HALF_UM), (WINDOW_HALF_UM, X_EXTENT_UM / 2.0)]

# ---- etch recipe, derived from inputs (um, s) -------------------------------------------------
R_ETCH = 0.20                     # oxide rate (both recipes) and the unselective rate
SELECTIVITY = 5.0                 # oxide : Si
R_SI_SELECTIVE = R_ETCH / SELECTIVITY
TARGET_SELECTIVE_SI_DEPTH_UM = 3 * GRID_UM      # 3 cells: measurable at this grid
T_CLEAR_S = OXIDE_UM / R_ETCH                    # time to clear the oxide at the oxide rate
T_TOTAL_S = T_CLEAR_S + TARGET_SELECTIVE_SI_DEPTH_UM / R_SI_SELECTIVE
EXPECTED_SI_SELECTIVE_UM = R_SI_SELECTIVE * max(0.0, T_TOTAL_S - T_CLEAR_S)
EXPECTED_SI_PLAIN_UM = R_ETCH * max(0.0, T_TOTAL_S - OXIDE_UM / R_ETCH)
REACH_UM = R_ETCH * T_TOTAL_S                    # largest lateral reach of an isotropic front
#: level-set resolution: depths are only meaningful to one grid cell (the original test's own bound)
DEPTH_TOLERANCE_UM = GRID_UM


def recipes():
    common = {"etch_time_s": T_TOTAL_S, "silicon_depth_um": SILICON_DEPTH_UM}
    return {
        "isotropic": {
            "plain": {"rate": -R_ETCH, "mask_material": MASK_MATERIAL, **common},
            "selective": {"material_rates": {"SiO2": -R_ETCH, "Si": -R_SI_SELECTIVE, MASK_MATERIAL: 0.0},
                          **common},
        },
        "directional": {
            "plain": {"direction": [0, -1, 0], "directional_velocity": -R_ETCH,
                      "mask_material": MASK_MATERIAL, "calculate_visibility": False, **common},
            "selective": {"direction": [0, -1, 0],
                          "material_rates": {"SiO2": (-R_ETCH, 0.0), "Si": (-R_SI_SELECTIVE, 0.0),
                                             MASK_MATERIAL: (0.0, 0.0)}, **common},
        },
    }


def check_protected(outcome, tag):
    """Beyond the mask edge: Si and oxide untouched, mask still present and unmoved."""
    for i, (before, after) in enumerate(zip(outcome.bands_before, outcome.bands_after)):
        rm = fx.native_removal(before, after)
        assert abs(rm["si_removed_um"]) <= fx.UNCHANGED_UM, (
            f"[{tag}] protected band {i}: Si moved {rm['si_removed_um']:+.6f} um")
        assert abs(rm["oxide_removed_um"]) <= fx.UNCHANGED_UM, (
            f"[{tag}] protected band {i}: oxide thickness changed {rm['oxide_removed_um']:+.6f} um")
        mb = before["exported"]["materials"][MASK_MATERIAL]
        ma = after["exported"]["materials"].get(MASK_MATERIAL, {})
        assert mb["columns_present"] == before["exported"]["n_columns"], "mask missing before the etch"
        assert ma.get("columns_present") == mb["columns_present"], (
            f"[{tag}] protected band {i}: mask present in {ma.get('columns_present')}/{mb['columns_present']} columns")
        assert abs(ma["top_mean"] - mb["top_mean"]) <= fx.UNCHANGED_UM, (
            f"[{tag}] protected band {i}: mask top moved {ma['top_mean'] - mb['top_mean']:+.6f}")


def report(tag, outcome):
    rm = fx.native_removal(outcome.core_before, outcome.core_after)
    ev = fx.exported_view(outcome.core_before, outcome.core_after)
    band = [fx.native_removal(b, a) for b, a in zip(outcome.bands_before, outcome.bands_after)]
    print(f"    [{tag}] NATIVE core: Si removed {rm['si_removed_um']:.5f} um, oxide "
          f"{rm['oxide_thickness_before_um']:.5f} -> {rm['oxide_thickness_after_um']:.5f} "
          f"(removed {rm['oxide_removed_um']:.5f}); Si flatness {outcome.core_after['native']['Si_flatness_um']:.2e}")
    print(f"    [{tag}] EXPORTED core (corroboration only): SiO2 columns "
          f"{ev['sio2_columns_present_before']} -> {ev['sio2_columns_present_after']}; "
          f"Si top {ev['si_top_before']:.5f} -> {ev['si_top_after']:.5f}")
    print(f"    [{tag}] protected bands: Si moved {[round(b['si_removed_um'], 6) for b in band]}, "
          f"oxide changed {[round(b['oxide_removed_um'], 6) for b in band]}")
    return rm


def gui_diagnostic_log(pre_mesh, post_mesh, window):
    """The GUI's REAL log path (`_log_etch_material_summary`) on two real exported meshes."""
    import tcad_2d_stagewise as gui
    logged = []
    gui.TCADApplication._log_etch_material_summary(SimpleNamespace(_log=logged.append), pre_mesh, post_mesh,
                                                   [list(window)])
    return "".join(logged)


def line_of(log, material):
    return next((l.strip() for l in log.splitlines() if l.strip().startswith(f"{material}:")), "")


def block_of(log, material):
    """The material's own line plus its indented detail lines (up to the next material / window line)."""
    out, on = [], False
    for l in log.splitlines():
        indent = len(l) - len(l.lstrip())
        if l.strip().startswith(f"{material}:") and indent == 4:
            on, out = True, [l.strip()]
        elif on and indent > 4:
            out.append(l.strip())
        elif on:
            break
    return "\n".join(out)


def structured_results(pre_mesh, post_mesh, window):
    """The analyzer's own structured results on the two real exported meshes (same reading as the GUI path)."""
    import meshio
    import numpy as np
    from tcad.mesh import etch_diagnostics as ed
    module = viennaps_session.require_viennaps()
    names = {int(getattr(module.Material, a)): a for a in dir(module.Material)
             if not a.startswith("_") and isinstance(getattr(module.Material, a), module.Material)}

    def load(path):
        m = meshio.read(path)
        tri = next(c for c in m.cells if c.type == "triangle")
        tags = m.cell_data["Material"][m.cells.index(tri)]
        return ed.TaggedMesh(m.points[:, :2], np.asarray(tri.data), tuple(names.get(int(t), str(t)) for t in tags))

    return {r.material: r for r in ed.analyze_window(load(pre_mesh), load(post_mesh), tuple(window))}


def check_diagnostic(model, tag, baseline, outcome, native_si_removed_um):
    """The user-visible diagnostic must (1) agree with the NATIVE core geometry for Si, (2) say what it measured
    (a vertical paired flat-interior displacement -- not an undercut, not a path length), and (3) keep BOTH facts
    when the exported mesh has a residual: centre cleared, boundary residual present. Batch 3B expectations:

        Directional/plain      SiO2 FULLY_CLEARED_IN_WINDOW                 Mask: no line
        Directional/selective  SiO2 CENTER_CLEARED_RESIDUAL_REMAINS         Mask POST_ONLY_RESIDUAL
        Isotropic/plain        SiO2 FULLY_CLEARED_IN_WINDOW                 Mask: no line
        Isotropic/selective    SiO2 FULLY_CLEARED_IN_WINDOW                 Mask: no line

    The Directional/selective residual is NOT ignored to make the test pass: it is asserted (metadata, evidence
    source, centre-clear span covering the fixture core) and no mask creation/motion is inferred from it."""
    from tcad.mesh import etch_diagnostics as ed
    window = baseline.requested["mask"]["open_window_um"]
    log = gui_diagnostic_log(baseline.baseline_mesh_path, outcome.final_mesh, window)
    st = structured_results(baseline.baseline_mesh_path, outcome.final_mesh, window)
    where = f"[{model}/{tag}]"
    si_blk, ox_blk, mask_blk = block_of(log, "Si"), block_of(log, "SiO2"), block_of(log, "Mask")
    print(f"    {where} GUI diagnostic log:\n" + "\n".join("        " + l for l in log.strip().splitlines()))

    # --- Si: numeric vertical displacement vs the native core (unchanged physics assertion) -------------------
    assert st["Si"].status == ed.ETCHED and st["Si"].contract_state == ed.PAIRED_VERTICAL_DISPLACEMENT, (where, st["Si"])
    assert "vertical paired flat-interior displacement" in si_blk and "not undercut/path length" in si_blk, (where, log)
    assert "evidence source: exported volume mesh" in si_blk, (where, log)
    m = re.search(r"etched (-?\d+\.\d+)um", si_blk)
    assert m, f"{where} no numeric Si displacement in {log!r}"
    got = float(m.group(1))
    assert abs(got - native_si_removed_um) <= fx.UNCHANGED_UM, (
        f"{where} diagnostic Si displacement {got:.4f} um vs native core {native_si_removed_um:.5f} um "
        f"(bound = the project's diagnostic comparison tolerance {fx.UNCHANGED_UM})")

    expect_residual = (model == "directional" and tag == "selective")
    if not expect_residual:
        assert st["SiO2"].status == ed.FULLY_CLEARED_IN_WINDOW and st["SiO2"].residual is None, (where, st["SiO2"])
        assert ox_blk.splitlines()[0] == "SiO2: fully cleared in the exported-mesh window", (where, log)
        assert "(no positive-area post-step intersection; evidence source: exported volume mesh)" in ox_blk, (where, log)
        assert "Mask" not in st and not mask_blk, f"{where} a Mask line/result appeared in a control: {log!r}"
        return got

    # --- Directional/selective: centre cleared AND boundary residual, both kept ------------------------------
    core_lo, core_hi = baseline.regions.core_um
    ox, mk = st["SiO2"], st["Mask"]
    assert ox.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS == ox.contract_state, (where, ox)
    assert ox.status != ed.FULLY_CLEARED_IN_WINDOW and "fully cleared in the exported-mesh window" not in ox_blk, (where, log)
    assert ox.center_clear_x_um[0] <= core_lo and ox.center_clear_x_um[1] >= core_hi, (
        f"{where} the centre-clear span {ox.center_clear_x_um} must cover the fixture core {(core_lo, core_hi)}")
    assert ox.n_center_clear_intervals >= 2
    res = ox.residual
    assert res is not None and res.component_count >= 1 and res.total_clipped_area_um2 > 0.0, (where, ox)
    assert res.evidence_source == "exported_volume_mesh" and ox.evidence_source == "exported_volume_mesh"
    for c in res.components:
        # every listed residual component lies wholly outside the core (it is a boundary residual) ...
        assert c.clipped_x_extent_um[0] >= core_hi or c.clipped_x_extent_um[1] <= core_lo, (where, c)
        assert c.whole_mesh_triangle_count >= c.triangles_intersecting_window >= 1, (where, c)
    # ... and nothing was dropped for being small: the component areas add up to the total
    assert abs(sum(c.clipped_area_um2 for c in res.components) - res.total_clipped_area_um2) < 1e-15
    assert ox_blk.splitlines()[0] == ("SiO2: cleared from the window center; residual exported-mesh material "
                                      "remains elsewhere in the window"), (where, log)
    assert "no whole-window full-clear claim" in ox_blk and "evidence source: exported volume mesh" in ox_blk, (where, log)
    assert "SiO2-tagged residual: total clipped area" in ox_blk and "component 1:" in ox_blk, (where, log)
    assert "whole-mesh triangles" in ox_blk and "isolated island" in ox_blk, (where, log)

    assert mk.status == ed.POST_ONLY_RESIDUAL and mk.residual is not None and mk.residual.component_count >= 1, (where, mk)
    assert mask_blk.splitlines()[0] == "Mask: post-step exported-mesh residual detected; no comparable pre-step support", (where, log)
    assert "Mask-tagged residual" in mask_blk and "physical creation or exposure is not inferred" in mask_blk, (where, log)
    for banned in ("created", "newly exposed", "mask moved"):
        assert banned not in mask_blk.lower(), (where, banned, mask_blk)
    return got


def check_model(model, baseline, out_dir):
    rec = recipes()[model]
    plain = fx.run_etch_on_independent_copy(baseline, model, rec["plain"], out_dir, f"{model}_plain")
    selective = fx.run_etch_on_independent_copy(baseline, model, rec["selective"], out_dir, f"{model}_selective")
    for tag, o in (("plain", plain), ("selective", selective)):
        # independence: each run started from a copy equal to the saved baseline
        assert o.copy_matches_baseline["exported_mesh_identical"], (model, tag, o.copy_matches_baseline)
        assert o.copy_matches_baseline["native_max_abs_dy_um"] == {"Si": 0.0, "SiO2": 0.0} or all(
            v <= 1e-12 for v in o.copy_matches_baseline["native_max_abs_dy_um"].values()), o.copy_matches_baseline
        assert o.oxidation_calls == 0
        assert not [w for w in o.warnings_raised if "initial-geometry" in w], o.warnings_raised
    # the two experiments began from the SAME pre-etch geometry
    for key in ("Si_top", "SiO2_top"):
        assert plain.core_before["native"][key] == selective.core_before["native"][key], key
    assert plain.bands_before == selective.bands_before

    print(f"  {model}:")
    rp = report("plain", plain)
    rs = report("selective", selective)

    # oxide punched through in BOTH (a wrong-sign selective recipe would leave oxide: silent no-op)
    for tag, o in (("plain", plain), ("selective", selective)):
        assert fx.exported_view(o.core_before, o.core_after)["sio2_columns_present_after"] == 0, (
            f"[{model}/{tag}] SiO2 still present in the core after the etch")
        assert fx.native_removal(o.core_before, o.core_after)["oxide_removed_um"] > 0.9 * OXIDE_UM, (
            f"[{model}/{tag}] oxide was not removed")
    # Si removed: unselective clearly, selective less
    assert rp["si_removed_um"] > rs["si_removed_um"] > 0.0, (
        f"[{model}] selective Si removal {rs['si_removed_um']:.5f} not in (0, plain {rp['si_removed_um']:.5f})")
    for tag, got, want in (("plain", rp["si_removed_um"], EXPECTED_SI_PLAIN_UM),
                           ("selective", rs["si_removed_um"], EXPECTED_SI_SELECTIVE_UM)):
        print(f"    [{tag}] Si depth measured {got:.5f} um vs recipe-derived {want:.5f} um "
              f"(difference {got - want:+.5f}; bound = one grid cell {DEPTH_TOLERANCE_UM})")
        assert abs(got - want) <= DEPTH_TOLERANCE_UM, (
            f"[{model}/{tag}] Si depth {got:.5f} differs from the recipe-derived {want:.5f} by more than one grid cell")
    check_protected(plain, f"{model}/plain")
    check_protected(selective, f"{model}/selective")
    check_diagnostic(model, "plain", baseline, plain, rp["si_removed_um"])
    check_diagnostic(model, "selective", baseline, selective, rs["si_removed_um"])
    print(f"    ratio selective/plain Si depth = {rs['si_removed_um'] / rp['si_removed_um']:.4f} "
          f"(recipe ratio {R_SI_SELECTIVE / R_ETCH:.4f})")


def main():
    print(f"recipe: R_ox=R_plain={R_ETCH} um/s, R_Si_selective={R_SI_SELECTIVE} um/s (selectivity {SELECTIVITY}:1), "
          f"Hox={OXIDE_UM} um -> t_clear=Hox/R_ox={T_CLEAR_S} s; T={T_TOTAL_S} s = t_clear + "
          f"{TARGET_SELECTIVE_SI_DEPTH_UM}/{R_SI_SELECTIVE}")
    print(f"expected Si depth: plain = R*(T - t_clear) = {EXPECTED_SI_PLAIN_UM:.4f} um, selective = "
          f"R_Si*(T - t_clear) = {EXPECTED_SI_SELECTIVE_UM:.4f} um; isotropic reach = R*T = {REACH_UM:.3f} um")
    with tempfile.TemporaryDirectory() as tmp:
        baseline = fx.build_masked_explicit_stack(
            tmp, x_extent_um=X_EXTENT_UM, y_extent_um=Y_EXTENT_UM, silicon_depth_um=SILICON_DEPTH_UM,
            oxide_top_um=OXIDE_UM, grid_delta_um=GRID_UM, mask_spans_um=MASK_SPANS_UM,
            mask_height_um=MASK_HEIGHT_UM, mask_material=MASK_MATERIAL, reach_um=REACH_UM)
        print(fx.describe_baseline(baseline))
        assert baseline.forbidden_call_counts == {"Oxidation": 0, "Process": 0}, baseline.forbidden_call_counts
        # mask creation must not have moved Si or SiO2 (native level sets, exact)
        assert all(v <= 1e-12 for v in baseline.mask_creation_native_shift_um.values()), \
            baseline.mask_creation_native_shift_um

        for model in ("directional", "isotropic"):
            check_model(model, baseline, tmp)

        pristine = fx.verify_baseline_pristine(baseline, tmp)
        print(f"independence: after all four etches the saved baseline is {pristine}")
        assert pristine == {"vpsd_sha256_unchanged": True, "fresh_copy_export_identical": True}

    print()
    print("ETCH SELECTIVITY TEST PASSED (explicit initial Si/SiO2 + explicit mask; DIRECT_EXPLICIT_GEOMETRY; "
          "not an oxidation result)")


if __name__ == "__main__":
    main()
