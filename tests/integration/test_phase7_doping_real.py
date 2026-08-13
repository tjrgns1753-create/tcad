#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7 real-backend verification: run a real ViennaPS Etching
ProcessStep, attach uniform doping to its ProcessResult via
tcad.physics.doping (separate from the process model), map that
doping into DevSim, and solve DevSim's official doping-aware
Poisson-only equation — for both n-type and p-type doping, checking
the result against the analytic built-in-potential prediction.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_uniform_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
from tcad.device.devsim.resistor_equation import set_bias

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}

# DevSim's own n_i default (silicon intrinsic carrier concentration,
# cm^-3) and V_t at 300K, used only to sanity-check the *real* solved
# potential against the analytic built-in-potential formula
# CreateSiliconPotentialOnlyContact itself implements (read from its
# source, not guessed) -- this is a physics check on real solver
# output, not a fabricated expected value.
import devsim
from devsim.python_packages import simple_physics as sp


def run_one(device_name, mesh_name, net_doping_cm3):
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        process_result = build_process_result(step_result)

        # doping applied as a separate step, not by the process model
        doped_result = apply_uniform_doping(process_result, {"Si": net_doping_cm3})
        assert doped_result.doping is not None
        assert doped_result.doping.kind == "uniform"
        assert process_result.doping is None, "original ProcessResult must stay untouched"

        imported = import_process_result(
            doped_result, mesh_name=mesh_name, device_name=device_name,
            contact_regions=["Si"], contact_axis="x",
        )

        apply_doping(imported.device, doped_result.doping)
        setup_semiconductor_potential_equation(
            imported.device, "Si", imported.contacts, temperature_k=300.0,
        )
        for c in imported.contacts:
            set_bias(imported.device, c, 0.0)

        devsim.solve(type="dc", solver_type="direct",
                     absolute_error=1e10, relative_error=1e-10, maximum_iterations=30)

        values = devsim.get_node_model_values(device=imported.device, region="Si", name="Potential")
        return imported, values


def main():
    print("[1/3] Running n-type (Nd=1e17 cm^-3) real ViennaPS + DevSim solve...")
    imported_n, values_n = run_one("phase7_device_n", "phase7_mesh_n", 1.0e17)
    pmin_n, pmax_n = min(values_n), max(values_n)
    print(f"      regions={imported_n.regions} contacts={imported_n.contacts}")
    print(f"      n-type potential min/max = {pmin_n:.6f} / {pmax_n:.6f} V")

    print("[2/3] Running p-type (Na=1e17 cm^-3) real ViennaPS + DevSim solve...")
    imported_p, values_p = run_one("phase7_device_p", "phase7_mesh_p", -1.0e17)
    pmin_p, pmax_p = min(values_p), max(values_p)
    print(f"      p-type potential min/max = {pmin_p:.6f} / {pmax_p:.6f} V")

    # Real physics check: uniform doping at 0V bias -> the whole region
    # sits at the Ohmic contact's built-in potential, V_t*ln(|Nd|/n_i),
    # with sign following doping type. Read n_i/V_t from DevSim's own
    # parameter values (not hardcoded), matching CreateSiliconPotentialOnlyContact's
    # own formula (read from its source).
    n_i = devsim.get_parameter(device=imported_n.device, region="Si", name="n_i")
    v_t = devsim.get_parameter(device=imported_n.device, region="Si", name="V_t")
    expected = v_t * math.log(1.0e17 / n_i)
    print(f"[3/3] Analytic built-in potential check: n_i={n_i:.3e}, V_t={v_t:.6f}, "
          f"expected |V_bi|={expected:.6f}")

    assert abs(pmax_n - pmin_n) < 1e-9, "uniform doping should give uniform potential"
    assert abs(pmax_p - pmin_p) < 1e-9
    assert abs(pmax_n - expected) < 1e-6, f"n-type mismatch: {pmax_n} vs {expected}"
    assert abs(pmax_p + expected) < 1e-6, f"p-type mismatch: {pmax_p} vs {-expected}"
    assert pmax_n > 0 and pmax_p < 0, "n-type/p-type potential sign must be opposite"

    print()
    print("PHASE 7 FULL PIPELINE (ViennaPS -> ProcessResult -> physics.doping -> "
          "DevSim NetDoping -> official semiconductor Poisson solve) "
          "RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 SUCCESSFULLY, "
          "MATCHING THE ANALYTIC BUILT-IN POTENTIAL FOR BOTH DOPING SIGNS")


if __name__ == "__main__":
    main()
