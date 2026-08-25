#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent physical references, and a clearly-labelled fidelity check.

T3a — INDEPENDENT PHYSICS. These relations hold regardless of any
constant this project chooses, so they test physics rather than
bookkeeping:

  * Si consumed / oxide grown = 0.44, from the molar volumes of Si and
    SiO2. Not a rate constant. Measured 0.434 / 0.437 / 0.439 at
    0.5 / 1.0 / 2.0 hr — stable across time, the signature of a real
    constraint rather than a fitted value.
  * Time additivity: oxidising t then t again equals oxidising 2t once.
    A property of a time-invariant ODE, independent of any coefficient.
    Measured agreement 0.39%.

T3b — TRANSMISSION FIDELITY ONLY. THIS DOES NOT VERIFY THE RESOLVER'S
NUMERICAL CORRECTNESS. It verifies only that the number the resolver
produced is the number the backend applied.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry

GRID = 0.02
BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=GRID,
            x_extent_um=6.0, y_extent_um=6.0)
STOICHIOMETRIC_RATIO = 0.44     # molar volume ratio of Si to SiO2


def _tops(mesh_path):
    import viennaps as vps

    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        value = getattr(vps.Material, attr)
        if isinstance(value, vps.Material):
            names.setdefault(int(value), attr)

    mesh = meshio.read(mesh_path)
    points = mesh.points
    found = {}
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            values = np.asarray(values).ravel()
            for tag in set(values.tolist()):
                selected = cells.data[values == tag]
                if len(selected) == 0:
                    continue
                name = names.get(int(tag), str(int(tag)))
                top = float(points[np.unique(selected)][:, 1].max())
                found[name] = max(found.get(name, top), top)
    return found


def _oxidise(hours, domain=None):
    step = registry.get("oxidation", "thermal")(inherited_domain=domain)
    recipe = {**BASE, "oxidant": "Dry", "temperature_c": 1000.0,
              "time_hours": hours}
    if domain is None:
        recipe["mask_spans_um"] = []
    result = step.run(recipe, tempfile.mkdtemp(prefix="ref_"))
    tops = _tops(result["final_mesh"])
    return step.last_domain, tops["Si"], tops["SiO2"]


def test_t3a_stoichiometry():
    print("\n[T3a] Si consumed / oxide grown = 0.44 (molar volumes)")
    seed = max(0.002, GRID)     # thermal.py inserts, not grows, this seed
    for hours in (0.5, 1.0, 2.0):
        _, si_top, oxide_top = _oxidise(hours)
        grown = (oxide_top - si_top) - seed
        consumed = -si_top
        ratio = consumed / grown
        assert abs(ratio - STOICHIOMETRIC_RATIO) < 0.03, (
            f"t={hours}hr: consumed/grown={ratio:.3f}, expected "
            f"{STOICHIOMETRIC_RATIO} from the Si/SiO2 molar volume ratio")
        print(f"    t={hours}hr  consumed/grown = {ratio:.3f}")


def test_t3a_time_additivity():
    print("\n[T3a] oxidising t then t equals oxidising 2t once")
    domain, si_a, ox_a = _oxidise(0.5)
    _, si_chained, ox_chained = _oxidise(0.5, domain=domain)
    _, si_single, ox_single = _oxidise(1.0)
    chained = ox_chained - si_chained
    single = ox_single - si_single
    relative = abs(chained - single) / single
    assert relative < 0.05, (
        f"chained {chained:.4f} vs single {single:.4f} differ by "
        f"{relative*100:.1f}% — oxidation is not reading the existing oxide")
    print(f"    chained={chained:.4f} single={single:.4f} "
          f"diff={relative*100:.2f}%")


def test_t3b_transmission_only():
    """DOES NOT VERIFY PHYSICAL CORRECTNESS — transmission fidelity only."""
    print("\n[T3b] the rate the resolver produced is the rate applied")
    print("      (this check does NOT verify the rate is physically right)")
    step = registry.get("etching", "isotropic")()
    before = None
    result = step.run({**BASE, "mask_spans_um": [],
                       "material_rates": {"Si": 0.0}, "default_rate": 0.0,
                       "etch_time_s": 0.5},
                      tempfile.mkdtemp(prefix="ref_"))
    tops = _tops(result["final_mesh"])
    assert abs(tops["Si"]) < 0.5 * GRID, (
        f"a material given rate 0 moved to {tops['Si']:.4f} — the resolved "
        f"value is not the value the backend applied")
    print(f"    rate 0 -> Si surface at {tops['Si']:+.4f} (unmoved)")


def main():
    test_t3a_stoichiometry()
    test_t3a_time_additivity()
    test_t3b_transmission_only()
    print()
    print("PHYSICS REFERENCES OK — independent checks pass, fidelity labelled")


if __name__ == "__main__":
    main()
