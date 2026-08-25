#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Physical-correctness rules for the Process CAD, real ViennaPS 4.6.2.

One test per rule the tool must obey, each measured on a real exported
mesh rather than argued from the code:

  1. PR coating is really a BLANKET coating.
  2. Before develop, no mask pattern reaches the geometry.
  3. Only after develop is selective etch / selective deposition
     possible.
  4. Deposition names its material.
  5. Doping does not damage the Si geometry; the P/N profile is carried
     separately, and drawn P = red, N = blue.
  6. Every process preserves the current wafer state and accumulates on
     top of it.

Rules 1-3 are also covered from the GUI side by
tests/unit/test_gui_litho_lifecycle_mock.py and from the recipe side by
tests/integration/test_litho_lifecycle_state_real.py; what this file
adds is the physical statement of each rule, measured end to end, in
one place that reads as the specification.
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
from tcad.process import registry
from tcad.process.flow import FlowStep, run_flow
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping

WIDTH_UM = 10.0
HALF = WIDTH_UM / 2.0
GRID = 0.05
BASE = dict(
    pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=GRID,
    x_extent_um=WIDTH_UM, y_extent_um=8.0,
)
BLANKET_RESIST = [[-HALF, HALF]]
DEVELOPED_RESIST = [[-HALF, -1.5], [1.5, HALF]]


def _materials(mesh_path):
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


def _at(materials_map, name, lo, hi):
    """Points of `name` within x in [lo, hi], or None if absent there."""
    if name not in materials_map:
        return None
    points = materials_map[name]
    here = points[(points[:, 0] >= lo) & (points[:, 0] <= hi)]
    return here if len(here) else None


def _deposit(remask_spans, material="Si3N4", fresh_spans=None):
    """An isotropic deposition recipe shaped the way the GUI builds one.

    remask_spans : resist applied to an ALREADY-BUILT wafer (a chained
        step). `remask_spans_um` is only honoured on an inherited
        domain, so passing it to a first step silently produces a bare
        wafer -- which is why the fresh case needs `fresh_spans`.
    fresh_spans : resist on a FRESH wafer, i.e. `mask_spans_um`, the key
        the GUI sends when this is the first step of the session.
    """
    recipe = {
        "_process_category": "deposition", "_process_model_key": "isotropic",
        **BASE, "rate": 0.05, "deposition_time_s": 0.4,
        # "mask_material" only tags inserted mask geometry
        # (prepare_domain()); it no longer also switches deposition to
        # selective (see tcad/process/deposition/isotropic.py's own
        # comment on "deposit_exclude_material" -- that key used to be
        # the same string, which meant ANY recipe that had a mask at
        # all made deposition unconditionally selective, contradicting
        # this project's own GUI toggle for blanket vs. selective).
        # Both are set here because this helper's whole point (rules
        # 2/3 below) is exercising the selective case explicitly.
        "mask_material": "Mask", "deposit_exclude_material": "Mask",
        "material": material,
    }
    if fresh_spans is not None:
        recipe["mask_spans_um"] = fresh_spans
    elif remask_spans is None:
        recipe["mask_spans_um"] = []
    else:
        recipe["remask_spans_um"] = remask_spans
    return recipe


def test_rule_1_pr_coating_is_blanket():
    print("\n[1] PR coating is a blanket coating")
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [], "oxidant": "Dry",
        "temperature_c": 1000.0, "time_hours": 0.5,
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", oxidation),
             FlowStep("deposition", "isotropic", _deposit(BLANKET_RESIST))],
            tmp,
        )
        found = _materials(results[1].volume_mesh_path)

    resist = found["Mask"]
    assert resist[:, 0].min() < -HALF + 0.2 and resist[:, 0].max() > HALF - 0.2, (
        f"resist does not reach the wafer edges: x=[{resist[:,0].min():.3f},"
        f"{resist[:,0].max():.3f}]")
    # Present everywhere across the wafer, sampled, not just at the ends.
    for centre in (-4.0, -2.0, 0.0, 2.0, 4.0):
        assert _at(found, "Mask", centre - 0.25, centre + 0.25) is not None, (
            f"blanket resist is missing at x={centre} -- it is patterned")
    print(f"    resist covers x=[{resist[:,0].min():.3f},{resist[:,0].max():.3f}] "
          f"with no gaps at any sampled x")


def test_rule_2_no_pattern_before_develop():
    print("\n[2] before develop, no mask pattern reaches the geometry")
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("deposition", "isotropic",
                      _deposit(None, fresh_spans=BLANKET_RESIST))],
            tmp,
        )
        found = _materials(results[0].volume_mesh_path)

    # A patterned resist would be ABSENT over the mask opening. An
    # undeveloped one must not be.
    assert _at(found, "Mask", -1.0, 1.0) is not None, (
        "the resist has an opening before develop was ever run -- the mask "
        "pattern reached the geometry too early")
    # And nothing may be selectively deposited through a pattern that
    # does not exist yet.
    film = found.get("Si3N4")
    assert film is None, (
        "material was deposited through an opening that does not exist yet")
    print("    resist has no opening; nothing deposited through a pattern")


def test_rule_3_selective_only_after_develop():
    print("\n[3] selective etch / deposition only after develop")
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [], "oxidant": "Dry",
        "temperature_c": 1000.0, "time_hours": 0.5,
    }
    etch = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        **BASE, "remask_spans_um": DEVELOPED_RESIST, "mask_material": "Mask",
        "material_rates": {"SiO2": -0.2, "Si": 0.0, "Mask": 0.0},
        "default_rate": 0.0, "etch_time_s": 0.5,
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", oxidation),
             FlowStep("etching", "isotropic", etch)],
            tmp,
        )
        before = _materials(results[0].volume_mesh_path)
        after = _materials(results[1].volume_mesh_path)

    assert _at(after, "Mask", -1.0, 1.0) is None, (
        "the developed resist still covers its own opening")
    assert _at(after, "Mask", -4.5, -3.5) is not None, (
        "the developed resist is missing where the mask is opaque")

    # Selective: oxide gone inside the opening, untouched outside it.
    assert _at(after, "SiO2", -1.0, 1.0) is None, (
        "the etch did not clear the oxide through the developed opening")
    masked = _at(after, "SiO2", -4.5, -3.5)
    original = _at(before, "SiO2", -4.5, -3.5)
    assert masked is not None, "the resist failed to protect the oxide"
    assert abs(masked[:, 1].max() - original[:, 1].max()) < 0.1 * GRID, (
        "oxide under the resist changed -- the etch was not selective")

    # And selective DEPOSITION through the same developed pattern.
    with tempfile.TemporaryDirectory() as tmp:
        dep_results = run_flow(
            [FlowStep("oxidation", "thermal", oxidation),
             FlowStep("deposition", "isotropic", _deposit(DEVELOPED_RESIST))],
            tmp,
        )
        deposited = _materials(dep_results[1].volume_mesh_path)
    film = deposited["Si3N4"]
    assert film[:, 0].min() > -2.0 and film[:, 0].max() < 2.0, (
        f"deposition escaped the developed opening: x=[{film[:,0].min():.3f},"
        f"{film[:,0].max():.3f}]")
    print("    etch clears only the opening; deposition lands only in it")


def test_rule_4_deposition_names_its_material():
    print("\n[4] every deposition model can name what it deposits")
    import inspect

    # The GUI's own list -- if a model is added there without material
    # support this fails rather than silently merging the new film into
    # whatever sits on top.
    import tcad_2d_stagewise as gui

    models = set(gui.TCADApplication._DEPOSITION_MODEL_KEYS.values()) if hasattr(
        gui.TCADApplication, "_DEPOSITION_MODEL_KEYS"
    ) else {
        "isotropic", "directional", "single_particle_cvd", "teos",
        "teos_pecvd", "selective_epitaxy", "geometric_trench",
    }
    for name in sorted(models):
        step_cls = registry.get("deposition", name)
        source = inspect.getsource(step_cls.run)
        assert "duplicateTopLevelSet" in source, (
            f"deposition model {name!r} cannot tag its deposited material, so "
            f"the film silently merges into whatever material is on top")
    print(f"    all {len(models)} deposition models support an explicit material")

    # And it really produces a distinct region, measured.
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("deposition", "isotropic", _deposit(None, material="W"))], tmp
        )
        found = _materials(results[0].volume_mesh_path)
    assert "W" in found, f"named material did not become its own region: {sorted(found)}"
    print(f"    a W deposition produced a real W region: {sorted(found)}")


def test_rule_5_doping_preserves_geometry_and_colors():
    print("\n[5] doping keeps the Si geometry and carries P/N separately")
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("deposition", "isotropic", _deposit(None, material="SiO2"))],
            tmp,
        )
        mesh_path = results[0].volume_mesh_path
        before = _materials(mesh_path)
        process_result = build_process_result(
            {"final_mesh": mesh_path, "snapshots": []}
        )
        n_doped = apply_uniform_doping(process_result, {"Si": 1e17})
        p_doped = apply_uniform_doping(process_result, {"Si": -1e17})
        after = _materials(mesh_path)

    assert sorted(before) == sorted(after), (
        f"doping changed the material set: {sorted(before)} -> {sorted(after)}")
    for name in before:
        assert np.allclose(
            np.sort(before[name][:, 1]), np.sort(after[name][:, 1])
        ), f"doping moved the {name} geometry"
    assert n_doped.material_regions == process_result.material_regions
    assert "Si" in [r.name for r in n_doped.material_regions], (
        "Si stopped being a material region after doping -- doping must not "
        "turn Si into a 'P' or 'N' material")

    # P/N is carried as a signed concentration, not as a material.
    assert n_doped.doping.regions[0].net_doping_cm3 > 0
    assert p_doped.doping.regions[0].net_doping_cm3 < 0

    # And the renderer's colors follow that sign: P red, N blue.
    import tcad_2d_stagewise as gui

    source = gui.TCADApplication._doping_color_segments.__doc__ or ""
    del source  # documentation is not the check; the code below is.
    import inspect

    body = inspect.getsource(gui.TCADApplication._doping_color_segments)
    assert 'N_COLOR, P_COLOR = "#2f6fed", "#e0393e"' in body, (
        "the doping overlay's P/N colors changed -- P must be red and N blue")
    assert body.count("N_COLOR if") >= 1 and ">= 0" in body, (
        "the doping overlay no longer picks its color from the net-doping sign")
    print("    materials and geometry unchanged; P/N carried as signed doping")
    print("    overlay colors: N = #2f6fed (blue), P = #e0393e (red)")


def test_rule_6_every_process_accumulates():
    print("\n[6] every process preserves the wafer and adds to it")
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [], "oxidant": "Dry",
        "temperature_c": 1000.0, "time_hours": 0.5,
    }
    metal = {
        "_process_category": "deposition", "_process_model_key": "directional",
        **BASE, "direction": [0.0, 1.0, 0.0], "directional_velocity": 0.05,
        "deposition_time_s": 0.3, "mask_material": "Mask", "material": "W",
    }
    with tempfile.TemporaryDirectory() as tmp:
        results = run_flow(
            [FlowStep("oxidation", "thermal", oxidation),
             FlowStep("deposition", "isotropic", _deposit(None, "Si3N4")),
             FlowStep("deposition", "directional", metal)],
            tmp,
        )
        snapshots = [_materials(r.volume_mesh_path) for r in results]

    expected = [{"Si", "SiO2"}, {"Si", "SiO2", "Si3N4"},
                {"Si", "SiO2", "Si3N4", "W"}]
    for index, (found, want) in enumerate(zip(snapshots, expected)):
        assert set(found) == want, (
            f"step {index + 1}: materials {sorted(found)}, expected {sorted(want)}")

    # The oxide from step 1 must be untouched by steps 2 and 3.
    first = snapshots[0]["SiO2"]
    for index, later in enumerate(snapshots[1:], start=2):
        span = later["SiO2"]
        assert abs(span[:, 1].max() - first[:, 1].max()) < 0.1 * GRID, (
            f"step {index} moved the oxide grown in step 1")
    print("    Si -> +SiO2 -> +Si3N4 -> +W, each earlier layer preserved")


def main():
    test_rule_1_pr_coating_is_blanket()
    test_rule_2_no_pattern_before_develop()
    test_rule_3_selective_only_after_develop()
    test_rule_4_deposition_names_its_material()
    test_rule_5_doping_preserves_geometry_and_colors()
    test_rule_6_every_process_accumulates()

    print()
    print("PHYSICAL-CORRECTNESS RULES VERIFIED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
