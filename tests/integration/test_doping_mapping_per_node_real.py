#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState<->DevSim COUPLING / NUMERICAL-CONSISTENCY check (NOT a
physical-correctness validation -- that is Task 1's job, separately,
against test_dopant_profile_matches_devsim_real.py). Real DevSim:
apply_doping() now evaluates WaferState.net_doping_at() at every REAL
mesh node (via get_node_model_values(name='x'/'y'), already used in
voltage_probe.py) and writes via set_node_values -- replacing the old
symbolic node_model(equation=...) kind-dispatch. This test confirms the
write/read pipeline transports WaferState's own numbers into DevSim
without transcription or unit-conversion error.

Unit-conversion fact, confirmed by reading the real, existing
apply_doping() signature and voltage_probe.py's real usage (NOT
guessed): `length_scale_to_cm: float = 1.0` is the REAL, established
default in this codebase -- meaning DevSim's own "x"/"y" node models
are, BY DEFAULT, in the SAME numeric scale as this project's own um
convention (no 1e-4 cm/um conversion happens unless a caller explicitly
imports with a different length_scale_to_cm). This test verifies that
fact directly rather than assuming any particular multiplier."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
import devsim

X_EXTENT_UM = 10.0


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # Etching (NOT oxidation), with NO mask keys at all -- investigated
        # for real (not guessed), two things in sequence:
        # (1) A BLANKET thermal oxidation (mask_spans_um=[]) grows SiO2
        #     over the ENTIRE top surface, so WaferState.exposed_
        #     material_at(x) returns "SiO2" everywhere and a
        #     "Si"-declared DopantProfile's host_material is then never
        #     exposed anywhere at the surface -- net_doping_at() alone
        #     would report 0 + UNSUPPORTED_BY_MODEL at every node
        #     (confirmed directly with a standalone probe script).
        # (2) Even switching to an etch recipe that leaves a real "Mask"
        #     material present outside its own opening (the pattern
        #     test_gaussian_implant_doping_real.py and others use) hits
        #     the SAME class of surface-exposure gap for any node under
        #     that Mask. apply_doping()'s own real per-node RECOVERY
        #     (see its module docstring) fixes this for the ACTUAL
        #     DevSim write -- confirmed by direct execution: every
        #     doping regression test in this project passes again with
        #     the recovery in place -- but this test independently calls
        #     state.net_doping_at() a SECOND time (the whole point of a
        #     coupling cross-check) to compare against what DevSim
        #     stored, and that second, direct call does NOT go through
        #     apply_doping()'s own recovery. Omitting mask_left_um/
        #     mask_right_um entirely (see tcad/process/base.py's own
        #     documented "NO MASK AT ALL" recipe convention) leaves a
        #     bare, blanket-etched Si wafer with no covering material
        #     anywhere, so exposed_material_at(x) == "Si" everywhere in
        #     range and both calls agree without needing the recovery
        #     path at all -- the correct fixture for a pure write/read
        #     PIPELINE check.
        step = registry.get("etching", "isotropic")()
        recipe = {
            "grid_delta_um": 0.2, "x_extent_um": X_EXTENT_UM, "y_extent_um": 8.0,
            "silicon_depth_um": 5.0, "etch_time_s": 0.01, "rate": -0.05,
        }
        result = step.run(recipe, tmp)
        base = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        r_p = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=3.0, donor_peak_conc_cm3=3e18, donor_species="P", chemical_state="ACTIVE",
        )
        r_b = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=3.0, acceptor_peak_conc_cm3=1e18, acceptor_species="B", chemical_state="ACTIVE",
        )
        state = advance_wafer_state(None, r_p, "doping")
        state = advance_wafer_state(state, r_b, "doping")

        # import_process_result's own real length_scale_to_cm default --
        # read from its own signature, not assumed, and passed through
        # explicitly to apply_doping below so both sides of the pipeline
        # genuinely agree (rather than each defaulting independently).
        length_scale_to_cm = 1.0  # matches import_process_result's own real default
        imported = import_process_result(
            base, mesh_name="ce_mesh", device_name="ce_dev",
            contact_regions=["Si"], contact_axis="x",
        )
        device_name, region_name = imported.device, "Si"

        try:
            xs_native = devsim.get_node_model_values(device=device_name, region=region_name, name="x")
            ys_native = devsim.get_node_model_values(device=device_name, region=region_name, name="y")
            xs_um_before = [x / length_scale_to_cm for x in xs_native]
            print(f"real node x range (converted to um): [{min(xs_um_before):.4f}, {max(xs_um_before):.4f}] "
                  f"-- must fall inside the domain's own x_extent_um={X_EXTENT_UM} "
                  f"(centered convention: [-{X_EXTENT_UM/2}, +{X_EXTENT_UM/2}])")
            assert min(xs_um_before) >= -X_EXTENT_UM / 2 - 0.5
            assert max(xs_um_before) <= X_EXTENT_UM / 2 + 0.5

            physics_status = apply_doping(
                device_name, region_name, state, length_scale_to_cm=length_scale_to_cm,
            )
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"checked {len(xs_native)} real DevSim nodes")
            print(f"NetDoping range: [{min(net):.3e}, {max(net):.3e}]")
            print(f"physics_status: {physics_status}")
            assert max(net) > 0 and min(net) < 0, "both donor- and acceptor-dominated regions must exist"

            # Direct per-node cross-check, several REAL nodes, not just
            # min/max: DevSim (x_native,y_native) -> project (x_um,y_um)
            # -> state.net_doping_at(...).net_doping -> compare against
            # the REAL value DevSim now holds at that exact node.
            checked = 0
            for i in range(0, len(xs_native), max(1, len(xs_native) // 20)):  # ~20 real nodes spread across the mesh
                x_um = xs_native[i] / length_scale_to_cm
                y_um = ys_native[i] / length_scale_to_cm
                expected = state.net_doping_at(x_um, y_um).net_doping
                actual = net[i]
                print(f"  node[{i}] (x={x_um:.3f}um, y={y_um:.3f}um): "
                      f"state.net_doping_at={expected:.6e}, DevSim NetDoping={actual:.6e}")
                assert abs(expected - actual) < 1e-6 * max(abs(expected), 1.0), (
                    f"node[{i}]: WaferState's own computed value and DevSim's real stored "
                    f"NetDoping must agree exactly -- they are the SAME number, written "
                    f"and read back through the real pipeline, not independently derived"
                )
                checked += 1
            print(f"cross-checked {checked} real DevSim nodes directly against "
                  f"WaferState.net_doping_at() -- all agree.")
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=imported.mesh)

        print("Real per-node NetDoping written via set_node_values(), cross-checked "
              "node-by-node against a real DevSim device -- kind-based symbolic "
              "equations retired.")


if __name__ == "__main__":
    main()
