#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_thermal_anneal(): every existing term gets its OWN species'
D(T), independently -- no ViennaPS/DevSim needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import (
    DEPTH_EVOLUTION_RESOLUTION,
    apply_gaussian_implant_doping,
    apply_thermal_anneal,
    apply_uniform_doping,
)
from tcad.physics.values import Resolution


def _base_result():
    return ProcessResult(
        volume_mesh_path="dummy.vtu",
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def test_depth_evolution_is_a_real_importable_constant():
    assert DEPTH_EVOLUTION_RESOLUTION is Resolution.UNSUPPORTED_BY_MODEL


def test_anneal_widens_every_term_by_its_own_species_D():
    b_implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    both = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
        existing=b_implant,
    )
    annealed = apply_thermal_anneal(both, temperature_c=900.0, time_s=600.0)

    terms = annealed.doping.regions[0].gaussian_terms
    b_term = next(t for t in terms if t["species"] == "B")
    p_term = next(t for t in terms if t["species"] == "P")

    print(f"B: straggle 0.2 -> {b_term['straggle_um']:.6f} um, "
          f"peak 1.0e18 -> {b_term['peak_conc_cm3']:.6e} cm^-3")
    print(f"P: straggle 0.2 -> {p_term['straggle_um']:.6f} um, "
          f"peak 1.0e18 -> {p_term['peak_conc_cm3']:.6e} cm^-3")

    assert b_term["straggle_um"] > 0.2, "B must broaden"
    assert p_term["straggle_um"] > 0.2, "P must broaden"
    # B and P have DIFFERENT Ea/D0 [Christensen2003] -- at the SAME
    # T/t they must broaden by DIFFERENT amounts, not identically.
    assert abs(b_term["straggle_um"] - p_term["straggle_um"]) > 1e-6, (
        f"B ({b_term['straggle_um']}) and P ({p_term['straggle_um']}) "
        f"broadened identically -- species-independent D(T) is wrong"
    )


def test_original_result_untouched():
    implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    )
    original_straggle = implant.doping.regions[0].peak_conc_cm3
    apply_thermal_anneal(implant, temperature_c=900.0, time_s=600.0)
    assert implant.doping.regions[0].peak_conc_cm3 == original_straggle


def test_non_gaussian_kind_is_a_real_no_op():
    uniform = apply_uniform_doping(_base_result(), {"Si": 1.0e17})
    result = apply_thermal_anneal(uniform, temperature_c=900.0, time_s=600.0)
    assert result is uniform, (
        "no defined shape to anneal -- must return the SAME object, "
        "not a copy pretending something happened"
    )
    print("non-gaussian kind: apply_thermal_anneal returned the same "
          f"object (id match: {result is uniform})")


def test_900c_and_1000c_give_different_results():
    implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    )
    low = apply_thermal_anneal(implant, temperature_c=900.0, time_s=600.0)
    high = apply_thermal_anneal(implant, temperature_c=1000.0, time_s=600.0)
    low_straggle = low.doping.regions[0].gaussian_terms[0]["straggle_um"]
    high_straggle = high.doping.regions[0].gaussian_terms[0]["straggle_um"]
    print(f"P at 900C/600s -> straggle {low_straggle:.6f} um; "
          f"1000C/600s -> straggle {high_straggle:.6f} um")
    assert high_straggle > low_straggle


def main():
    test_depth_evolution_is_a_real_importable_constant()
    test_anneal_widens_every_term_by_its_own_species_D()
    test_original_result_untouched()
    test_non_gaussian_kind_is_a_real_no_op()
    test_900c_and_1000c_give_different_results()
    print("apply_thermal_anneal() widens every existing term by its "
          "own species' real D(T), independently, leaves non-Gaussian "
          "kinds as a real no-op, and 900C != 1000C.")


if __name__ == "__main__":
    main()
