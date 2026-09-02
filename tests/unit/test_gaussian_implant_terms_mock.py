#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_gaussian_implant_doping's existing= parameter: a second call
ADDS a term, never erases the first -- no ViennaPS/DevSim needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import apply_gaussian_implant_doping


def _base_result():
    return ProcessResult(
        volume_mesh_path="dummy.vtu",
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def test_existing_none_is_byte_identical_to_today():
    """Zero behavior change for every caller that doesn't pass existing=."""
    result = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.3,
        peak_conc_cm3=1.0e17,
    )
    region = result.doping.regions[0]
    print(f"existing=None: peak_conc_cm3={region.peak_conc_cm3:.3e}, "
          f"peak_position_um={region.peak_position_um}, "
          f"straggle_um={region.straggle_um}, "
          f"gaussian_terms={region.gaussian_terms}")
    assert region.peak_conc_cm3 == 1.0e17
    assert region.peak_position_um == 0.0
    assert region.straggle_um == 0.3
    assert region.gaussian_terms is None


def test_second_call_adds_a_term_does_not_erase_the_first():
    """B implant, then P implant on top -- both must exist afterward."""
    first = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        donor_peak_conc_cm3=0.0, acceptor_peak_conc_cm3=1.0e18,
        acceptor_species="B",
    )
    second = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.15,
        donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=0.0,
        donor_species="P",
        existing=first,
    )
    terms = second.doping.regions[0].gaussian_terms
    print(f"after B then P: {len(terms) if terms else 0} terms")
    for t in terms:
        print(f"  species={t['species']} polarity={t['polarity']} "
              f"peak_conc_cm3={t['peak_conc_cm3']:.3e} "
              f"peak_position_um={t['peak_position_um']} "
              f"straggle_um={t['straggle_um']}")
    assert terms is not None
    assert len(terms) == 2, f"expected 2 terms (B then P), got {len(terms)}"

    species_seen = {t["species"] for t in terms}
    assert species_seen == {"B", "P"}, f"expected both B and P present, got {species_seen}"

    b_term = next(t for t in terms if t["species"] == "B")
    p_term = next(t for t in terms if t["species"] == "P")
    assert b_term["polarity"] == "acceptor"
    assert b_term["peak_conc_cm3"] == 1.0e18
    assert b_term["peak_position_um"] == -1.0
    assert p_term["polarity"] == "donor"
    assert p_term["peak_conc_cm3"] == 2.0e18
    assert p_term["peak_position_um"] == 1.0

    # ORIGINAL result object must be untouched (this project's own
    # convention: every apply_*_doping returns a NEW ProcessResult).
    first_terms = first.doping.regions[0].gaussian_terms
    print(f"first (original) result's terms after second call: {first_terms}")
    assert first_terms is None or len(first_terms) == 1


def test_existing_with_incompatible_kind_raises():
    from tcad.physics.doping import apply_uniform_doping
    uniform_result = apply_uniform_doping(_base_result(), {"Si": 1.0e16})
    try:
        apply_gaussian_implant_doping(
            _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
            peak_conc_cm3=1.0e18, existing=uniform_result,
        )
        assert False, "expected ValueError for incompatible existing doping kind"
    except ValueError as exc:
        print(f"correctly raised ValueError: {exc}")


def main():
    test_existing_none_is_byte_identical_to_today()
    test_second_call_adds_a_term_does_not_erase_the_first()
    test_existing_with_incompatible_kind_raises()
    print("apply_gaussian_implant_doping's existing= parameter adds "
          "terms without erasing earlier ones, and every caller that "
          "doesn't use it is completely unaffected.")


if __name__ == "__main__":
    main()
