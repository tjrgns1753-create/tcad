#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-material etch selectivity — real ViennaPS 4.6.2, through the actual
production entry points (registry -> DirectionalEtch/IsotropicEtch
.run()), on a real oxide-on-silicon stack.

Guards the optional `material_rates` recipe key added to
tcad/process/etching/directional.py and isotropic.py. Without it, those
models apply ONE rate to every non-mask material, i.e. no selectivity at
all — which is easy to mistake for selectivity when a masking layer
merely happens to be in the way (measured: etching a window covered by
0.2um of oxide removes "only oxide" while the etch stays shallower than
the oxide, then eats into Si at the identical rate the moment it punches
through; see LOCOS_CHAINING_TEST_LOG.txt item 19).

The two ViennaPS overloads DISAGREE on sign, which is the real trap this
test locks down: DirectionalProcess's materialRates removes material for
POSITIVE rates (so the wrapper flips the recipe's sign),
IsotropicProcess's removes for NEGATIVE (so the wrapper must not). A
wrong sign is silently a no-op rather than an error, so a regression
here would look like "the etch did nothing," not like a crash.

Checks, for BOTH models:
  1. With selectivity, an etch deep enough to clear the oxide leaves
     substantially more Si than the same etch without selectivity.
  2. The measured Si:oxide etch-depth ratio matches the requested one.
  3. The sign convention is right — i.e. the selective recipe removes
     material at all, rather than silently doing nothing.

Expected values are derived from the recipe's own geometry and rates.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.etching  # noqa: F401 -- registers the models
import tcad.process.oxidation  # noqa: F401 -- builds the oxide-on-Si stack
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

GRID_DELTA_UM = 0.05
X_EXTENT_UM = 4.0
WINDOW_UM = 1.0
OXIDE_UM = 0.2

#: Etch deep enough to clear the oxide and bite into Si, so the
#: unselective and selective cases actually differ.
TOTAL_ETCH_UM = 0.4
SELECTIVITY = 10.0

BASE_RECIPE = {
    "grid_delta_um": GRID_DELTA_UM,
    "x_extent_um": X_EXTENT_UM,
    "y_extent_um": 3.0,
    "mask_left_um": (X_EXTENT_UM - WINDOW_UM) / 2.0,
    "mask_right_um": (X_EXTENT_UM + WINDOW_UM) / 2.0,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.02,
    "mask_material": "Mask",
    "pad_oxide_thickness_um": OXIDE_UM,
}


def areas_by_material(mesh_path):
    mesh = meshio.read(str(mesh_path))
    block = next((c for c in mesh.cells if c.type == "triangle"), None)
    assert block is not None, f"{mesh_path} has no triangles"
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    areas = {}
    for tri, tag in zip(block.data, tags):
        p = mesh.points[tri]
        a = abs((p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1])
                - (p[2, 0] - p[0, 0]) * (p[1, 1] - p[0, 1])) / 2.0
        areas[int(tag)] = areas.get(int(tag), 0.0) + a
    return areas


def oxidize(tmp, label):
    """A real oxide-on-Si stack with a masked window, via the real
    production entry point. Its own `last_domain` is what the etch
    steps below chain from."""
    step = registry.get("oxidation", "thermal")()
    result = step.run(dict(BASE_RECIPE), str(Path(tmp) / label))
    return step, areas_by_material(result["final_mesh"])


def etch(tmp, label, inherited, model_name, recipe):
    step = registry.get("etching", model_name)(inherited_domain=inherited)
    result = step.run(dict(recipe), str(Path(tmp) / label))
    return areas_by_material(result["final_mesh"])


def check(model_name, plain_recipe, selective_recipe, si_tag, oxide_tag):
    with tempfile.TemporaryDirectory() as tmp:
        step_a, before = oxidize(tmp, f"{model_name}_ox_a")
        plain = etch(tmp, f"{model_name}_plain", step_a.last_domain,
                     model_name, plain_recipe)

        step_b, before_b = oxidize(tmp, f"{model_name}_ox_b")
        selective = etch(tmp, f"{model_name}_selective", step_b.last_domain,
                         model_name, selective_recipe)

    # Both oxidation runs are the same recipe, so their "before" states
    # must match -- otherwise the comparison below is meaningless.
    assert abs(before[si_tag] - before_b[si_tag]) < 1e-6, (
        f"[{model_name}] the two baseline oxidations disagree on Si area "
        f"({before[si_tag]} vs {before_b[si_tag]}); comparison invalid"
    )

    plain_si_removed = before[si_tag] - plain[si_tag]
    selective_si_removed = before_b[si_tag] - selective[si_tag]
    plain_ox_removed = before[oxide_tag] - plain[oxide_tag]
    selective_ox_removed = before_b[oxide_tag] - selective[oxide_tag]

    # 3. sign convention: the selective recipe must actually etch.
    assert selective_ox_removed > 0.5 * OXIDE_UM * WINDOW_UM, (
        f"[{model_name}] the selective recipe removed almost no oxide "
        f"({selective_ox_removed:.5f}) -- a wrong materialRates sign is a "
        f"SILENT no-op, which is exactly what this looks like"
    )

    # 1. selectivity protects Si.
    assert plain_si_removed > 0.0, (
        f"[{model_name}] the unselective control removed no Si "
        f"({plain_si_removed:.5f}), so there is nothing for selectivity to "
        f"improve on -- the etch is not deep enough to test anything"
    )
    assert selective_si_removed < plain_si_removed, (
        f"[{model_name}] selectivity did not protect Si: removed "
        f"{selective_si_removed:.5f} vs {plain_si_removed:.5f} unselective"
    )

    # 2. the ratio matches what was asked for. Compared in Si etch DEPTH
    # (area / window width) against the grid, since the absolute numbers
    # are only resolvable to about a cell.
    plain_depth = plain_si_removed / WINDOW_UM
    selective_depth = selective_si_removed / WINDOW_UM
    predicted_selective_depth = plain_depth / SELECTIVITY
    assert abs(selective_depth - predicted_selective_depth) < GRID_DELTA_UM, (
        f"[{model_name}] Si etch depth with {SELECTIVITY:.0f}:1 selectivity was "
        f"{selective_depth:.5f}um, expected ~{predicted_selective_depth:.5f}um "
        f"(1/{SELECTIVITY:.0f} of the unselective {plain_depth:.5f}um), "
        f"off by more than one grid cell ({GRID_DELTA_UM}um)"
    )

    print(f"  [{model_name}] oxide removed {selective_ox_removed:.5f}; Si depth "
          f"{plain_depth:.5f}um unselective -> {selective_depth:.5f}um at "
          f"{SELECTIVITY:.0f}:1 (predicted {predicted_selective_depth:.5f}um)")


def main():
    module = viennaps_session.require_viennaps()
    si_tag = int(module.Material.Si)
    oxide_tag = int(module.Material.SiO2)

    print("directional etch:")
    check(
        "directional",
        plain_recipe={
            "direction": [0, -1, 0],
            "directional_velocity": -TOTAL_ETCH_UM,
            "etch_time_s": 1.0,
            "mask_material": "Mask",
            "calculate_visibility": False,
        },
        selective_recipe={
            "direction": [0, -1, 0],
            # Negative removes, this project's own etching convention --
            # the wrapper flips it for ViennaPS's inverted overload.
            "material_rates": {
                "SiO2": (-TOTAL_ETCH_UM, 0.0),
                "Si": (-TOTAL_ETCH_UM / SELECTIVITY, 0.0),
                "Mask": (0.0, 0.0),
            },
            "etch_time_s": 1.0,
        },
        si_tag=si_tag,
        oxide_tag=oxide_tag,
    )

    print("isotropic etch:")
    check(
        "isotropic",
        plain_recipe={
            "rate": -TOTAL_ETCH_UM,
            "etch_time_s": 1.0,
            "mask_material": "Mask",
        },
        selective_recipe={
            # Same recipe-level convention (negative removes); this
            # wrapper passes it through unflipped, because
            # IsotropicProcess's overload already agrees with it.
            "material_rates": {
                "SiO2": -TOTAL_ETCH_UM,
                "Si": -TOTAL_ETCH_UM / SELECTIVITY,
                "Mask": 0.0,
            },
            "etch_time_s": 1.0,
        },
        si_tag=si_tag,
        oxide_tag=oxide_tag,
    )

    print("ETCH SELECTIVITY TEST PASSED")


if __name__ == "__main__":
    main()
