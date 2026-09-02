#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arrhenius D(T) kernel: matches the literature formula exactly, and
downgrades to UNVERIFIED outside the citation's own measured window --
no ViennaPS/DevSim needed, pure math."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.diffusion_model import (
    K_BOLTZMANN_EV_PER_K,
    arrhenius_diffusivity,
    thermal_budget_contribution,
)
from tcad.physics.values import Resolution


def _expected_D(D0, Ea, temperature_c):
    T_kelvin = temperature_c + 273.15
    return D0 * math.exp(-Ea / (K_BOLTZMANN_EV_PER_K * T_kelvin))


def test_phosphorus_matches_christensen_2003_in_window():
    """[Christensen2003]: P, D0=8e-4 cm^2/s, Ea=2.74 eV, 810-1100 C."""
    result = arrhenius_diffusivity("P", "Si", 900.0)
    expected = _expected_D(8e-4, 2.74, 900.0)
    assert result.value is not None
    assert abs(result.value - expected) / expected < 1e-9
    assert result.resolution is Resolution.VERIFIED, (
        f"900 C is inside [Christensen2003]'s 810-1100 C P window -- "
        f"expected VERIFIED, got {result.resolution}"
    )


def test_boron_matches_christensen_2003_in_window():
    """[Christensen2003]: B, D0=0.06 cm^2/s, Ea=3.12 eV, 810-1050 C."""
    result = arrhenius_diffusivity("B", "Si", 900.0)
    expected = _expected_D(0.06, 3.12, 900.0)
    assert result.value is not None
    assert abs(result.value - expected) / expected < 1e-9
    assert result.resolution is Resolution.VERIFIED


def test_outside_measured_window_is_downgraded():
    """1200 C is above [Christensen2003]'s 1100 C P ceiling -- the
    formula still computes a number (Arrhenius extrapolation is
    physically continuous), but this project's own rule is that a
    citation used outside its stated window is UNVERIFIED, never
    silently treated as equally trustworthy."""
    result = arrhenius_diffusivity("P", "Si", 1200.0)
    assert result.value is not None
    assert result.resolution is Resolution.UNVERIFIED, (
        f"1200 C is outside [Christensen2003]'s 810-1100 C P window -- "
        f"expected UNVERIFIED, got {result.resolution}"
    )


def test_unknown_species_or_host_returns_unknown():
    result = arrhenius_diffusivity("As", "Si", 900.0)
    assert result.value is None
    assert result.resolution is Resolution.UNKNOWN

    result = arrhenius_diffusivity("P", "SiO2", 900.0)
    assert result.value is None
    assert result.resolution is Resolution.UNKNOWN


def test_thermal_budget_is_D_times_t_not_raw_time():
    """The whole point of this function: two anneals with the SAME
    duration but DIFFERENT temperatures must give DIFFERENT budgets,
    because D(T) itself differs -- this is the assertion the base
    design's own migration-table language ("900 C 10 min and 1000 C
    10 min must not have the same diffusion effect") requires."""
    low = thermal_budget_contribution("P", "Si", 900.0, 600.0)
    high = thermal_budget_contribution("P", "Si", 1000.0, 600.0)
    assert low.value is not None and high.value is not None
    assert high.value > low.value, (
        f"1000 C/600s budget ({high.value}) must exceed 900 C/600s "
        f"budget ({low.value}) -- higher T means larger D(T), same t"
    )
    # exact value, not just direction:
    expected_low = _expected_D(8e-4, 2.74, 900.0) * 600.0
    assert abs(low.value - expected_low) / expected_low < 1e-9


def main():
    test_phosphorus_matches_christensen_2003_in_window()
    test_boron_matches_christensen_2003_in_window()
    test_outside_measured_window_is_downgraded()
    test_unknown_species_or_host_returns_unknown()
    test_thermal_budget_is_D_times_t_not_raw_time()
    print("Arrhenius D(T) matches [Christensen2003] exactly inside its "
          "measured window, downgrades outside it, and thermal budget "
          "genuinely depends on temperature, not just elapsed time.")


if __name__ == "__main__":
    main()
