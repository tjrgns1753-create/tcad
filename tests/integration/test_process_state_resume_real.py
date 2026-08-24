#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process-state accumulation across RUN clicks, real ViennaPS 4.6.2.

Pins the rule that each RUN takes the PREVIOUS run's result as its
input — one wafer accumulating state — rather than rebuilding that
state from scratch every time.

The GUI runs every process step in its own subprocess, so it cannot
hold a live ViennaPS Domain between clicks. It used to solve that by
REPLAYING: the Nth click re-ran all N recipes from a bare wafer. The
geometry that produced was correct, but the cost was O(N^2) and it
re-paid for the slowest step on every later click — measured here, the
oxidation alone is ~25s, so every subsequent click carried it again.

Now each run persists the accumulated domain to a `.vpsd`
(`run_flow` already wrote one; nothing read it back) and the next run
resumes from it via `run_flow(..., initial_domain=...)`. This test
drives `tcad_2d_stagewise.worker_main` directly — the GUI's own worker
entry point, same JSON config a real click writes — four times, passing
only the state file between them.

What is checked at each step:
  * the worker executed exactly ONE step (proving it resumed rather
    than replayed),
  * every earlier step's material is still present and unmoved,
  * the new step's own effect is there,
  * no material appeared that no step asked for.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad_2d_stagewise as gui

WIDTH_UM = 10.0
HALF = WIDTH_UM / 2.0
GRID = 0.05
BASE = dict(
    pr_thickness_um=1.0,
    silicon_depth_um=5.0,
    grid_delta_um=GRID,
    x_extent_um=WIDTH_UM,
    y_extent_um=8.0,
)


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


def _run_click(recipe, resume_state):
    """One RUN click: worker_main with the GUI's own config shape."""
    out = tempfile.mkdtemp(prefix="resume_click_")
    config = {"_flow_steps": [recipe], "output_dir": out}
    if resume_state:
        config["_resume_state"] = resume_state
    config_file = os.path.join(out, "recipe.json")
    result_file = os.path.join(out, "result.json")
    Path(config_file).write_text(json.dumps(config), encoding="utf-8")

    gui.worker_main(config_file, result_file)

    result = json.loads(Path(result_file).read_text(encoding="utf-8"))
    assert result.get("success"), f"worker failed: {result.get('error')}"
    return result


def _y_range(materials_map, name, lo=None, hi=None):
    points = materials_map[name]
    if lo is not None:
        points = points[(points[:, 0] >= lo) & (points[:, 0] <= hi)]
    if len(points) == 0:
        return None
    return float(points[:, 1].min()), float(points[:, 1].max())


def test_state_accumulates_across_runs():
    print("\n[A] four RUN clicks, carrying only the .vpsd between them")

    recipes = [
        ("oxidation", {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            **BASE, "mask_spans_um": [],
            "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5,
        }),
        ("deposition Si3N4", {
            "_process_category": "deposition", "_process_model_key": "isotropic",
            **BASE, "rate": 0.05, "deposition_time_s": 0.4, "material": "Si3N4",
        }),
        ("etch through developed resist", {
            "_process_category": "etching", "_process_model_key": "isotropic",
            **BASE,
            "remask_spans_um": [[-HALF, -1.5], [1.5, HALF]],
            "mask_material": "Mask",
            "material_rates": {"Si3N4": -0.3, "SiO2": 0.0, "Si": 0.0, "Mask": 0.0},
            "default_rate": 0.0, "etch_time_s": 0.5,
        }),
        ("deposition W", {
            "_process_category": "deposition", "_process_model_key": "isotropic",
            **BASE, "rate": 0.04, "deposition_time_s": 0.3, "material": "W",
        }),
    ]

    state = None
    seen = []
    for index, (label, recipe) in enumerate(recipes):
        result = _run_click(recipe, state)

        if index > 0:
            # The whole point: a resumed click runs ONE step, not the
            # whole history. If this ever reads 2/3/4 the GUI has fallen
            # back to replaying and the O(N^2) cost is back.
            assert result["step_count"] == 1, (
                f"click {index + 1} ran {result['step_count']} steps -- it "
                f"replayed the history instead of resuming the wafer")

        assert result.get("domain_state"), (
            f"click {index + 1} returned no domain_state, so the NEXT click "
            f"cannot resume from it")
        assert Path(result["domain_state"]).exists(), (
            "domain_state path does not exist -- note ViennaPS silently "
            "writes nothing for a non-ASCII path; see session._ascii_io_path")

        state = result["domain_state"]
        seen.append(_materials(result["final_mesh"]))
        print(f"    RUN {index + 1}: {label:32s} ran {result['step_count']} step(s), "
              f"materials={sorted(seen[-1])}")

    after_ox, after_nitride, after_etch, after_metal = seen

    # --- each step added exactly its own material ---------------------
    assert set(after_ox) == {"Si", "SiO2"}
    assert set(after_nitride) == {"Si", "SiO2", "Si3N4"}, (
        f"deposition changed the material set unexpectedly: {sorted(after_nitride)}")
    assert set(after_etch) == {"Si", "SiO2", "Si3N4", "Mask"}, (
        f"etch changed the material set unexpectedly: {sorted(after_etch)}")
    assert set(after_metal) == {"Si", "SiO2", "Si3N4", "Mask", "W"}, (
        f"metal deposition changed the material set unexpectedly: "
        f"{sorted(after_metal)}")

    # --- the oxide from click 1 survives all three later clicks -------
    ox_span = _y_range(after_ox, "SiO2")
    for label, snapshot in [("nitride", after_nitride), ("etch", after_etch),
                            ("metal", after_metal)]:
        span = _y_range(snapshot, "SiO2")
        assert all(abs(a - b) < 0.1 * GRID for a, b in zip(ox_span, span)), (
            f"the oxide from click 1 moved by the {label} click: "
            f"{ox_span} -> {span}")
    print(f"    oxide from click 1 unchanged through every later click: "
          f"y=[{ox_span[0]:.3f},{ox_span[1]:.3f}]")

    # --- the etch removed the nitride ONLY inside the opening ---------
    assert _y_range(after_etch, "Si3N4", -1.0, 1.0) is None, (
        "nitride survives inside the developed opening -- the etch did not "
        "go through")
    masked_nitride = _y_range(after_etch, "Si3N4", -4.5, -3.5)
    assert masked_nitride is not None, "the resist failed to protect the nitride"
    nitride_before = _y_range(after_nitride, "Si3N4", -4.5, -3.5)
    assert all(abs(a - b) < 0.1 * GRID
               for a, b in zip(nitride_before, masked_nitride)), (
        f"nitride under the resist changed: {nitride_before} -> {masked_nitride}")
    print(f"    nitride cleared in the opening, preserved under the resist at "
          f"y=[{masked_nitride[0]:.3f},{masked_nitride[1]:.3f}]")

    # --- metal reached the opening AND the resist top (conformal) -----
    in_window = _y_range(after_metal, "W", -0.5, 0.5)
    on_resist = _y_range(after_metal, "W", -4.5, -3.5)
    assert in_window is not None, "no metal deposited into the opening"
    assert on_resist is not None, "no metal deposited over the resist"
    assert in_window[0] < on_resist[0], (
        f"metal in the opening ({in_window}) should sit lower than metal on "
        f"top of the resist ({on_resist})")
    print(f"    metal conformal: y={in_window} in the opening vs {on_resist} "
          f"on the resist")


def test_new_wafer_does_not_resume_the_old_one():
    """A run with no resume state must build a fresh wafer."""
    print("\n[B] a click with no carried state starts from bare silicon")

    deposition = {
        "_process_category": "deposition", "_process_model_key": "isotropic",
        **BASE, "mask_spans_um": [],
        "rate": 0.05, "deposition_time_s": 0.3, "material": "Si3N4",
    }
    result = _run_click(deposition, None)
    found = _materials(result["final_mesh"])
    assert set(found) == {"Si", "Si3N4"}, (
        f"a fresh run picked up materials from an earlier wafer: {sorted(found)}")
    print(f"    materials={sorted(found)} -- no leftovers from the previous test")


def test_pristine_wafer_can_be_materialized():
    """A wafer with no process run on it still has a real geometry.

    Doping used to refuse until some other process had produced a mesh,
    which is a prerequisite: a wafer exists from the moment it is
    created, and doping virgin silicon is a real step. The GUI now
    exports the current wafer instead of refusing
    (`_materialize_current_wafer` -> the worker's `_materialize_wafer`
    branch), so this pins that the export is a real, dopeable wafer and
    that it ran NO process to get there.
    """
    print("\n[C] a wafer with nothing run on it exports a real geometry")

    out = tempfile.mkdtemp(prefix="pristine_")
    config = {
        "_materialize_wafer": True, "output_dir": out,
        "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
        "silicon_depth_um": 5.0, "pr_thickness_um": 1.0,
        "mask_spans_um": [],
    }
    config_file = os.path.join(out, "wafer.json")
    result_file = os.path.join(out, "result.json")
    Path(config_file).write_text(json.dumps(config), encoding="utf-8")
    gui.worker_main(config_file, result_file)

    result = json.loads(Path(result_file).read_text(encoding="utf-8"))
    assert result.get("success"), f"worker failed: {result.get('error')}"
    assert result["step_count"] == 0, (
        f"materializing the wafer ran {result['step_count']} process step(s) -- "
        f"it must run none")

    found = _materials(result["final_mesh"])
    assert set(found) == {"Si"}, (
        f"a wafer with nothing run on it is not bare silicon: {sorted(found)}")
    silicon = found["Si"]
    assert silicon[:, 0].min() < -4.5 and silicon[:, 0].max() > 4.5, (
        "the exported wafer does not span its own width")

    # It must be a real ProcessResult that doping can attach to.
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_uniform_doping

    process_result = build_process_result(
        {"final_mesh": result["final_mesh"], "snapshots": []}
    )
    doped = apply_uniform_doping(process_result, {"Si": -1e15})
    assert doped.doping.regions[0].region == "Si"
    assert doped.doping.regions[0].net_doping_cm3 == -1e15

    # And it carries state, so the next real step resumes from it.
    assert Path(result["domain_state"]).exists()
    print(f"    materials={sorted(found)}, x=[{silicon[:,0].min():.3f},"
          f"{silicon[:,0].max():.3f}], dopeable, state written, 0 steps run")


def main():
    test_state_accumulates_across_runs()
    test_new_wafer_does_not_resume_the_old_one()
    test_pristine_wafer_can_be_materialized()

    print()
    print("PROCESS-STATE ACCUMULATION VERIFIED AGAINST REAL VIENNAPS 4.6.2")
    print("(each RUN runs ONE step on the wafer the previous RUN left,")
    print(" every earlier step's geometry preserved, no wafer rebuilt)")


if __name__ == "__main__":
    main()
