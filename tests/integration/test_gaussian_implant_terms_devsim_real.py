#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real DevSim proof: two independent Gaussian implant terms (added via
apply_gaussian_implant_doping's existing=, Task 3) sum into ONE real,
solved NetDoping expression -- Donors + Acceptors built from ALL
terms, not just the last one registered.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask",
}


def _fresh_process_result():
    """Run a fresh etch step in its own temp directory and build the
    ProcessResult. Returns (result, tmp). Caller must keep `tmp` alive
    until the mesh file has actually been read (e.g. via
    import_process_result), then call tmp.cleanup() -- same shape as
    test_dopant_profile_matches_devsim_real.py's own
    _fresh_process_result(). A `with ... return` idiom here would
    delete the mesh file on return, before any downstream reader gets
    to it."""
    step_cls = registry.get("etching", "isotropic")
    tmp = tempfile.TemporaryDirectory()
    try:
        step_result = step_cls().run(RECIPE, tmp.name)
        result = build_process_result(step_result)
        return result, tmp
    except Exception:
        tmp.cleanup()
        raise


def main():
    b_result, b_tmp = _fresh_process_result()
    try:
        b_implant = apply_gaussian_implant_doping(
            b_result, "Si", "x",
            peak_position_um=-0.8, straggle_um=0.2,
            acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
        )
    finally:
        b_tmp.cleanup()

    both_result, both_tmp = _fresh_process_result()
    try:
        both = apply_gaussian_implant_doping(
            both_result, "Si", "x",
            peak_position_um=0.8, straggle_um=0.15,
            donor_peak_conc_cm3=2.0e18, donor_species="P",
            existing=b_implant,
        )
        assert both.doping.regions[0].gaussian_terms is not None
        assert len(both.doping.regions[0].gaussian_terms) == 2

        imported = import_process_result(
            both, mesh_name="terms_mesh", device_name="terms_device",
            contact_regions=["Si"], contact_axis="x",
        )
        try:
            apply_doping(imported.device, both.doping)

            x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
            net_doping = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

            import math
            def expected(x):
                b_term = -1.0e18 * math.exp(-((x - (-0.8)) ** 2) / (2.0 * 0.2 ** 2))
                p_term = 2.0e18 * math.exp(-((x - 0.8) ** 2) / (2.0 * 0.15 ** 2))
                return b_term + p_term

            max_rel_error = 0.0
            n_checked = 0
            for x, actual in zip(x_values, net_doping):
                exp = expected(x)
                denom = max(abs(exp), 1.0)
                max_rel_error = max(max_rel_error, abs(actual - exp) / denom)
                n_checked += 1

            print(f"[1/2] checked {n_checked} nodes, max relative error vs "
                  f"independently-summed formula: {max_rel_error:.3e}")
            assert max_rel_error < 1e-6, (
                f"real DevSim NetDoping does not match the sum of both "
                f"implant terms: {max_rel_error}"
            )

            # sign sanity at each peak
            near_b = min(range(len(x_values)), key=lambda i: abs(x_values[i] - (-0.8)))
            near_p = min(range(len(x_values)), key=lambda i: abs(x_values[i] - 0.8))
            assert net_doping[near_b] < 0, "B (acceptor) peak must read net-negative"
            assert net_doping[near_p] > 0, "P (donor) peak must read net-positive"
            print(f"[2/2] B peak reads {net_doping[near_b]:.3e} (acceptor), "
                  f"P peak reads {net_doping[near_p]:.3e} (donor)")
        finally:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)

        assert devsim.get_device_list() == ()
        print("Two independently-added Gaussian implant terms sum into one "
              "real, solved DevSim NetDoping -- both terms present, neither "
              "overwrote the other.")
    finally:
        both_tmp.cleanup()


if __name__ == "__main__":
    main()
