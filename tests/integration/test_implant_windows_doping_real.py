#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Implant-windows doping real-backend verification: run a real ViennaPS
Etching ProcessStep, attach an implant_windows DopingProfile to its
ProcessResult via tcad.physics.doping (same pattern as
test_gaussian_implant_doping_real.py), map that into DevSim's NetDoping
node model, and check the *real* solved NetDoping values against an
independently-computed formula at every node — not just "doesn't crash".

Motivating case: this is the smallest piece needed for a MOSFET-shaped
doping profile (source + drain implants superposed on a channel/body
background) that this project's DopingRegion previously could not
express at all -- every existing kind (uniform/step_junction/
gaussian_implant) is a single 1D profile per region, with no way to lay
out two laterally-separated implant windows in the same region. This
test does not build a MOSFET (no gate stack, no 4-terminal device) --
it verifies the one new primitive (windowed, superposed doping) works
against the real backend.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.1,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.3,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}

# domain x spans roughly [-2, +2]; source/drain windows sit inside it
# with a channel/body region between them.
BACKGROUND_CM3 = -1.0e17   # p-type body/channel
SOURCE = {"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20}
DRAIN = {"min_um": 0.6, "max_um": 1.6, "conc_cm3": 1.0e20}


def main():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        process_result = build_process_result(step_result)

        doped_result = apply_implant_windows_doping(
            process_result, region="Si", axis="x",
            background_doping_cm3=BACKGROUND_CM3,
            windows=[SOURCE, DRAIN],
        )
        assert doped_result.doping is not None
        assert doped_result.doping.kind == "implant_windows"
        assert process_result.doping is None, "original ProcessResult must stay untouched"

        imported = import_process_result(
            doped_result, mesh_name="implant_mesh", device_name="implant_device",
            contact_regions=["Si"], contact_axis="x",
        )

        apply_doping(imported.device, doped_result.doping)

        x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        net_doping_values = devsim.get_node_model_values(
            device=imported.device, region="Si", name="NetDoping",
        )
        print(f"[1/3] NetDoping registered on {len(net_doping_values)} nodes, "
              f"x range [{min(x_values):.3f}, {max(x_values):.3f}]")

        def expected(x):
            v = BACKGROUND_CM3
            if SOURCE["min_um"] <= x <= SOURCE["max_um"]:
                v += SOURCE["conc_cm3"]
            if DRAIN["min_um"] <= x <= DRAIN["max_um"]:
                v += DRAIN["conc_cm3"]
            return v

        # Real physics check: compare DevSim's own evaluated NetDoping at
        # each node against the windowed formula computed independently
        # in Python from that node's real x coordinate. Skip nodes within
        # one grid cell of a window boundary -- step()'s value exactly AT
        # the boundary is a convention detail (< vs <=), not the thing
        # under test.
        boundaries = [SOURCE["min_um"], SOURCE["max_um"], DRAIN["min_um"], DRAIN["max_um"]]
        max_rel_error = 0.0
        n_checked = 0
        seen_body = seen_source = seen_drain = False
        for x, actual in zip(x_values, net_doping_values):
            if min(abs(x - b) for b in boundaries) < 1e-6:
                continue
            exp = expected(x)
            rel_error = abs(actual - exp) / abs(exp)
            max_rel_error = max(max_rel_error, rel_error)
            n_checked += 1
            if SOURCE["min_um"] < x < SOURCE["max_um"]:
                seen_source = True
            elif DRAIN["min_um"] < x < DRAIN["max_um"]:
                seen_drain = True
            else:
                seen_body = True

        print(f"[2/3] checked {n_checked} nodes (body/source/drain all present: "
              f"{seen_body}/{seen_source}/{seen_drain}); "
              f"max relative error vs independently-computed formula: {max_rel_error:.3e}")
        assert seen_body and seen_source and seen_drain, (
            "expected nodes in all three lateral regions (body, source, drain)"
        )
        assert max_rel_error < 1e-9, f"NetDoping does not match the windowed formula: {max_rel_error}"

        # Sign/magnitude sanity: source/drain nodes should read strongly
        # net-donor (positive), body nodes strongly net-acceptor
        # (negative) -- the qualitative signature a MOSFET-shaped doping
        # profile needs, checked at real solved values, not assumed.
        src_idx = min(range(len(x_values)), key=lambda i: abs(x_values[i] - (-1.1)))
        drn_idx = min(range(len(x_values)), key=lambda i: abs(x_values[i] - 1.1))
        body_idx = min(range(len(x_values)), key=lambda i: abs(x_values[i] - 0.0))
        assert net_doping_values[src_idx] > 0.5 * SOURCE["conc_cm3"]
        assert net_doping_values[drn_idx] > 0.5 * DRAIN["conc_cm3"]
        assert net_doping_values[body_idx] < 0
        print(f"[3/3] source={net_doping_values[src_idx]:.3e}, "
              f"drain={net_doping_values[drn_idx]:.3e}, "
              f"body={net_doping_values[body_idx]:.3e} cm^-3 -- "
              f"correct sign/magnitude at all three")

        print()
        print("IMPLANT-WINDOWS DOPING (ViennaPS -> ProcessResult -> physics.doping -> "
              "DevSim NetDoping) RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 "
              "SUCCESSFULLY, MATCHING THE INDEPENDENTLY-COMPUTED WINDOWED PROFILE")


if __name__ == "__main__":
    main()
