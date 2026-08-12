#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process flow continuity verification (Phase 13), against real
ViennaPS 4.6.2 — no mocks.

The point of every test here is to distinguish a REAL continued flow
from "just running each model independently in order". The decisive
evidence is a negative control run alongside each flow:

    Independent run  : step 2 alone on a fresh wafer -> materials {Mask, Si}
    Continued flow   : step 2 after thermal oxidation -> materials must
                       include SiO2, which step 2 can only have gotten
                       from step 1's geometry.

SiO2 never appears from MakeTrench, and none of the etch/deposition
models create it, so its presence in a later step is proof that the
earlier step's structure was carried forward — not reproducible by
independent execution.
"""

import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import tcad.process.etching  # noqa: F401 -- registers models
import tcad.process.deposition  # noqa: F401
import tcad.process.oxidation  # noqa: F401
from tcad.backends.viennaps import session
from tcad.process import registry
from tcad.process.flow import FlowStep, run_flow

assert session.is_available(), "ViennaPS must be installed for this test"

GRID = 0.05
EXTENT = {"grid_delta_um": GRID, "x_extent_um": 4.0, "y_extent_um": 3.0,
          "mask_left_um": 1.0, "mask_right_um": 3.0, "pr_thickness_um": 0.3}

OXIDATION_RECIPE = dict(EXTENT, oxidant="Dry", temperature_c=1000.0, time_hours=0.05)
WET_ETCH_RECIPE = {
    "etch_time_s": 0.4,
    "material_rates": [{"material": "SiO2", "rate": -0.08},
                       {"material": "Si", "rate": 0.0},
                       {"material": "Mask", "rate": 0.0}],
}
CVD_RECIPE = {"deposition_time_s": 0.3, "rate": 0.05, "sticking_probability": 1.0}
DIRECTIONAL_ETCH_RECIPE = {
    "etch_time_s": 0.3, "direction": [0.0, -1.0, 0.0],
    "directional_velocity": -0.08, "mask_material": "Mask",
}
ISOTROPIC_ETCH_RECIPE = {"etch_time_s": 0.3, "rate": -0.04, "mask_material": "Mask"}


def _print_structures(title, results):
    print(f"  {title}")
    for i, r in enumerate(results):
        s = r.structure
        print(f"    step{i}: materials={s['materials']} "
              f"level_sets={s['num_level_sets']} "
              f"bbox={[[round(v, 4) for v in p] for p in s['bounding_box']]} "
              f"grid={s['grid_delta']}")
        print(f"           mesh={Path(r.volume_mesh_path).name}")


def _independent_materials(category, name, recipe, tmp):
    """Negative control: same model, same physical recipe, run ALONE on
    a fresh wafer. Whatever materials this produces is what independent
    execution can achieve."""
    full_recipe = dict(EXTENT, **recipe)
    out = Path(tmp) / f"independent_{name}"
    out.mkdir(parents=True, exist_ok=True)
    step = registry.get(category, name)()
    step.run(full_recipe, str(out))
    return session.describe_domain(step.last_domain)


def flow_si_oxidation_etching(tmp):
    print("[Flow 1] Si -> thermal oxidation -> wet etching of the oxide")
    results = run_flow(
        [
            FlowStep("oxidation", "thermal", OXIDATION_RECIPE, label="01_oxidation"),
            FlowStep("etching", "wet_etching", WET_ETCH_RECIPE, label="02_wet_etch"),
        ],
        str(Path(tmp) / "flow1"),
        reload_between_steps=True,  # prove the persisted .vpsd alone suffices
    )
    _print_structures("structures:", results)

    control = _independent_materials("etching", "wet_etching", WET_ETCH_RECIPE, tmp)
    print(f"    NEGATIVE CONTROL (wet_etching alone on fresh wafer): "
          f"materials={control['materials']} level_sets={control['num_level_sets']}")

    step2 = results[1].structure
    assert "SiO2" in results[0].structure["materials"], "step 1 should have grown oxide"
    assert "SiO2" in step2["materials"], (
        f"CONTINUITY FAILED: step 2 lost the oxide from step 1: {step2['materials']}"
    )
    assert "SiO2" not in control["materials"], (
        "negative control unexpectedly produced SiO2; the proof is invalid"
    )
    assert step2["grid_delta"] == results[0].structure["grid_delta"]
    print("    => step 2 carries SiO2, which an independent run provably cannot produce."
          " CONTINUITY PROVEN.\n")
    return results


def flow_si_oxidation_doping(tmp):
    print("[Flow 2] Si -> thermal oxidation -> doping (on the flow's final structure)")
    from tcad.physics.doping import apply_uniform_doping

    results = run_flow(
        [FlowStep("oxidation", "thermal", OXIDATION_RECIPE, label="01_oxidation")],
        str(Path(tmp) / "flow2"),
    )
    final = results[-1]
    doped = apply_uniform_doping(final, {"Si": -1e15})

    _print_structures("structures:", results)
    print(f"    ProcessResult regions carried into doping: "
          f"{[r.name for r in doped.material_regions]}")
    print(f"    doping profile: kind={doped.doping.kind}, "
          f"regions={[(d.region, d.net_doping_cm3) for d in doped.doping.regions]}")

    assert "SiO2" in final.structure["materials"]
    assert {"Si", "SiO2"}.issubset({r.name for r in doped.material_regions}), (
        "doping step must see the oxidation-produced Si/SiO2 structure"
    )
    assert doped.domain_state_path == final.domain_state_path, (
        "doping must preserve the flow's domain state handle"
    )
    assert final.doping is None, "apply_uniform_doping must not mutate the input result"
    print("    => doping applied on the oxidation flow's real Si/SiO2 structure.\n")
    return results


def flow_si_oxidation_deposition_etching(tmp):
    print("[Flow 3] Si -> oxidation -> conformal CVD deposition -> directional etch")
    results = run_flow(
        [
            FlowStep("oxidation", "thermal", OXIDATION_RECIPE, label="01_oxidation"),
            FlowStep("deposition", "single_particle_cvd", CVD_RECIPE, label="02_cvd"),
            FlowStep("etching", "directional", DIRECTIONAL_ETCH_RECIPE, label="03_etch"),
        ],
        str(Path(tmp) / "flow3"),
        reload_between_steps=True,
    )
    _print_structures("structures:", results)

    control = _independent_materials("etching", "directional", DIRECTIONAL_ETCH_RECIPE, tmp)
    print(f"    NEGATIVE CONTROL (directional etch alone): materials={control['materials']}")

    assert "SiO2" in results[2].structure["materials"], (
        f"CONTINUITY FAILED at step 3: {results[2].structure['materials']}"
    )
    assert "SiO2" not in control["materials"]
    print("    => oxide survives through all 3 steps; independent run cannot. "
          "CONTINUITY PROVEN.\n")
    return results


def flow_extra_oxidation_etch_deposition_etch(tmp):
    print("[Flow 4] Si -> oxidation -> isotropic etch -> CVD -> directional etch (4 steps)")
    results = run_flow(
        [
            FlowStep("oxidation", "thermal", OXIDATION_RECIPE, label="01_oxidation"),
            FlowStep("etching", "isotropic", ISOTROPIC_ETCH_RECIPE, label="02_iso_etch"),
            FlowStep("deposition", "single_particle_cvd", CVD_RECIPE, label="03_cvd"),
            FlowStep("etching", "directional", DIRECTIONAL_ETCH_RECIPE, label="04_dir_etch"),
        ],
        str(Path(tmp) / "flow4"),
    )
    _print_structures("structures:", results)

    assert all("SiO2" in r.structure["materials"] for r in results), (
        "oxide must persist through every subsequent step"
    )
    grids = {r.structure["grid_delta"] for r in results}
    assert len(grids) == 1, f"grid spacing must stay that of the original wafer: {grids}"
    print("    => same wafer (identical grid) carried through 4 steps, oxide intact.\n")
    return results


def test_ignored_recipe_keys_warn(tmp):
    print("[Warning check] initial-geometry keys on an inherited step must warn")
    noisy_recipe = dict(EXTENT, **WET_ETCH_RECIPE)  # includes grid_delta_um etc.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_flow(
            [
                FlowStep("oxidation", "thermal", OXIDATION_RECIPE),
                FlowStep("etching", "wet_etching", noisy_recipe),
            ],
            str(Path(tmp) / "warn_flow"),
        )
    messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("are ignored" in m for m in messages), f"expected a warning, got {messages}"
    print(f"    warning raised: {messages[0][:160]}...")
    print("    => ignored initial-geometry keys are reported, not silently dropped.\n")


def test_single_step_still_fresh(tmp):
    print("[Backward compat] a lone step must still build its own fresh wafer")
    control = _independent_materials("etching", "wet_etching", WET_ETCH_RECIPE, tmp)
    assert "SiO2" not in control["materials"]
    assert control["materials"], "a standalone step must still produce a real wafer"
    print(f"    standalone wet_etching materials={control['materials']} "
          f"(no inherited oxide, as expected)\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        flow_si_oxidation_etching(tmp)
        flow_si_oxidation_doping(tmp)
        flow_si_oxidation_deposition_etching(tmp)
        flow_extra_oxidation_etch_deposition_etch(tmp)
        test_ignored_recipe_keys_warn(tmp)
        test_single_step_still_fresh(tmp)

    print("ALL PROCESS FLOW CONTINUITY TESTS PASSED AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
