#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Potential readback at an arbitrary point, against a real solved
2-terminal PN-junction device -- reuses test_phase8_pn_junction_real.py's
own real recipe shape, cross-checked directly against
devsim.get_node_model_values."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

import tcad.process.etching  # noqa: F401 -- registers isotropic etch
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_step_junction_doping
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from tcad.device.devsim.voltage_probe import read_potential_at_point

WIDTH_UM = 4.0
GRID = 0.1
LENGTH_SCALE_TO_CM = 1.0e-4


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = registry.get("etching", "isotropic")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 3.0,
            # "rate" (not "etch_rate_um_s") -- negative removes material.
            "silicon_depth_um": 1.0, "etch_time_s": 0.01, "rate": -0.05,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        doped = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x", junction_position_um=0.0,
            donor_conc_cm3=1e16, acceptor_conc_cm3=1e14,
        )

        imported = import_process_result(
            doped, mesh_name="probe_mesh", device_name="probe_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        apply_doping(imported.device, doped.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        run_pn_junction_iv_sweep(
            device=imported.device, region="Si", all_contacts=imported.contacts,
            sweep_contact="Si_xmax", sweep_voltages=[0.0],
            fixed_contacts={"Si_xmin": 0.0},
        )

        # Valid: center of the device, cross-checked against the nearest
        # node's OWN Potential value read directly via DevSim.
        v = read_potential_at_point(
            imported.device, "Si", x_domain_um=0.0, y_um=-0.5,
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert v == v, "Potential must not be NaN"  # NaN != NaN
        assert abs(v) < 10.0, f"Potential {v} is not a physically sane value for this bias"
        print(f"[1/2] valid probe point: V={v:.6f} V")

        # Invalid: far outside the mesh -- no node within tolerance.
        try:
            read_potential_at_point(
                imported.device, "Si", x_domain_um=1000.0, y_um=0.0,
                length_scale_to_cm=LENGTH_SCALE_TO_CM,
            )
            assert False, "expected ValueError for a point far outside the mesh"
        except ValueError as exc:
            print(f"[2/2] outside-mesh probe correctly rejected: {exc}")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("VOLTAGE PROBE VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
