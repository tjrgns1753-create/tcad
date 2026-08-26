#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All 4 doping kinds must accept independent donor/acceptor concentrations
and compute net = donor - acceptor internally, while PRESERVING the raw
donor/acceptor values on the DopingRegion (not just collapsing to net).
Every EXISTING net-only call shape must still work unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)


def _base_result():
    # ProcessResult's real constructor fields (verified directly against
    # tcad/mesh/interface.py -- an earlier draft of this test used
    # final_mesh/snapshots, which are ProcessStep.run()'s raw dict keys,
    # not ProcessResult's own fields): volume_mesh_path (required),
    # material_field="Material" (default), material_regions=[] (default).
    return ProcessResult(
        volume_mesh_path="dummy.vtu",
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def main():
    # --- Backward compatibility: old net-only call shapes unchanged ---
    r = apply_uniform_doping(_base_result(), {"Si": 1.0e17})
    assert r.doping.regions[0].net_doping_cm3 == 1.0e17
    assert r.doping.regions[0].donor_conc_cm3 is None

    r = apply_gaussian_implant_doping(_base_result(), "Si", "x", 0.0, 0.5, 1.0e17)
    assert r.doping.regions[0].peak_conc_cm3 == 1.0e17

    r = apply_implant_windows_doping(_base_result(), "Si", "x", -1.0e17, [
        {"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20},
    ])
    assert r.doping.regions[0].net_doping_cm3 == -1.0e17
    assert r.doping.regions[0].implant_windows[0]["conc_cm3"] == 1.0e20

    # --- New donor/acceptor shapes ---
    r = apply_uniform_doping(
        _base_result(),
        donor_by_region_cm3={"Si": 1.0e16}, acceptor_by_region_cm3={"Si": 5.0e15},
    )
    region = r.doping.regions[0]
    assert region.net_doping_cm3 == 5.0e15, f"net must be donor-acceptor, got {region.net_doping_cm3}"
    assert region.donor_conc_cm3 == 1.0e16, "raw donor value must be preserved"
    assert region.acceptor_conc_cm3 == 5.0e15, "raw acceptor value must be preserved"

    r = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", 0.0, 0.3,
        donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=3.0e17,
        donor_species="P", acceptor_species="B",
    )
    region = r.doping.regions[0]
    assert abs(region.peak_conc_cm3 - (2.0e18 - 3.0e17)) < 1.0, (
        f"gaussian net peak must be donor-acceptor, got {region.peak_conc_cm3}")
    assert region.donor_peak_conc_cm3 == 2.0e18
    assert region.acceptor_peak_conc_cm3 == 3.0e17
    assert region.donor_species == "P" and region.acceptor_species == "B"

    r = apply_implant_windows_doping(
        _base_result(), "Si", "x",
        donor_background_cm3=1.0e15, acceptor_background_cm3=1.0e16,
        windows=[
            {"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1.0e20, "acceptor_conc_cm3": 0.0},
        ],
    )
    region = r.doping.regions[0]
    assert region.net_doping_cm3 == 1.0e15 - 1.0e16, (
        f"background net must be donor-acceptor, got {region.net_doping_cm3}")
    window = region.implant_windows[0]
    assert window["conc_cm3"] == 1.0e20, f"window net must be donor-acceptor, got {window['conc_cm3']}"
    assert window["donor_conc_cm3"] == 1.0e20 and window["acceptor_conc_cm3"] == 0.0

    # --- step_junction unchanged (already correct) ---
    r = apply_step_junction_doping(_base_result(), "Si", "x", 0.0, 1.0e18, 1.0e18)
    assert r.doping.regions[0].donor_conc_cm3 == 1.0e18
    assert r.doping.regions[0].acceptor_conc_cm3 == 1.0e18

    print("All 4 doping kinds accept independent donor/acceptor input, "
          "compute net=donor-acceptor internally, preserve the raw "
          "values, and every existing net-only call shape is unchanged.")


if __name__ == "__main__":
    main()
