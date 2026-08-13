#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8 real-backend verification: build a real PN junction from a
real ViennaPS-etched structure, solve DevSim's official doping-aware
Poisson equilibrium (checked against the analytic built-in potential),
turn on real electron/hole drift-diffusion, and run a single real
continuous bias ramp (reverse -> equilibrium -> forward), extracting
real terminal current at every point.

Important real finding (not documented anywhere, found by hitting it):
devsim.solve() takes NO `device=` argument — it solves every currently
registered device together as one combined system. Leaving multiple
devices registered (e.g. a throwaway probe used only to read geometry)
made a later, unrelated device's solve fail to reconverge. The fix:
devsim.delete_device() any probe device right after reading what's
needed from it, and do the real sweep as ONE continuous voltage ramp
on ONE device (matching realistic TCAD practice anyway) rather than
two separate forward/reverse calls on the same device.
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
from tcad.physics.doping import apply_step_junction_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from tcad.characterization.io import save_csv, save_json
from tcad.characterization.plotting import save_iv_plot

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.15,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}

LENGTH_SCALE_TO_CM = 1.0e-4  # um -> cm; see mesh_import.py's docstring
DONOR_CM3 = 1.0e18
ACCEPTOR_CM3 = 1.0e18


def main():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        print(f"[1/6] ViennaPS process step OK -> {step_result['final_mesh']}")

        process_result = build_process_result(step_result)
        print(f"[2/6] ProcessResult OK -> regions: {[r.name for r in process_result.material_regions]}")

        probe = import_process_result(process_result, mesh_name="phase8_probe_mesh", device_name="phase8_probe_device")
        x_native = devsim.get_node_model_values(device=probe.device, region="Si", name="x")
        junction_position_um = 0.5 * (min(x_native) + max(x_native))
        # delete_device() alone leaves the underlying mesh (from
        # create_gmsh_mesh()) registered in DevSim's global state; a
        # later solve() in this same process picks up ALL registered
        # devices (no device= filter), so leftover mesh/device state
        # from a failed OR merely-finished earlier import can make an
        # unrelated later solve fail to reconverge too. Mirrors the
        # already-verified _cleanup_device() pattern in
        # tcad/cli/run_pipeline.py.
        devsim.delete_device(device=probe.device)
        devsim.delete_mesh(mesh=probe.mesh)

        doped_result = apply_step_junction_doping(
            process_result, region="Si", junction_axis="x",
            junction_position_um=junction_position_um,
            donor_conc_cm3=DONOR_CM3, acceptor_conc_cm3=ACCEPTOR_CM3,
        )
        assert doped_result.doping.kind == "step_junction"
        assert process_result.doping is None, "original ProcessResult must stay untouched"
        print(f"[3/6] Step-junction ProcessResult built OK -> junction at x={junction_position_um:.3f} um")

        imported = import_process_result(
            doped_result, mesh_name="phase8_mesh", device_name="phase8_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert len(imported.contacts) == 2
        p_contact, n_contact = imported.contacts[0], imported.contacts[1]
        print(f"[4/6] DevSim import OK (um->cm) -> regions={imported.regions} contacts={imported.contacts}")

        apply_doping(imported.device, doped_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

        sweep_voltages = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4]
        result = run_pn_junction_iv_sweep(
            device=imported.device, region="Si", all_contacts=imported.contacts,
            sweep_contact=n_contact, sweep_voltages=sweep_voltages,
            fixed_contacts={p_contact: 0.0},
        )

        print("[5/6] Full bias ramp (real drift-diffusion currents):")
        currents_by_v = {}
        for p in result.points:
            v = p.voltages[n_contact]
            i = p.currents[n_contact]
            currents_by_v[round(v, 6)] = i
            print(f"      V={v:+.2f}  I_total={i:.6e} A")

        fwd_voltages_sorted = sorted(v for v in currents_by_v if v >= 0.0)
        fwd_currents = [currents_by_v[v] for v in fwd_voltages_sorted]
        assert all(
            fwd_currents[i + 1] >= fwd_currents[i] - 1e-15
            for i in range(len(fwd_currents) - 1)
        ), f"forward current must not decrease with forward bias: {fwd_currents}"
        assert fwd_currents[-1] > fwd_currents[0], "forward current must increase overall"

        rev_voltages_sorted = sorted((v for v in currents_by_v if v < 0.0), reverse=True)
        rev_currents = [currents_by_v[v] for v in rev_voltages_sorted]
        assert all(i <= 1e-12 for i in rev_currents), (
            f"reverse-biased current should be near-zero or negative (blocking), got {rev_currents}"
        )
        print(f"      Forward current increases with bias: {fwd_currents}")
        print(f"      Reverse current stays near-zero/negative (blocking): {rev_currents}")

        # devsim.solve() has no device= argument -- it solves every
        # registered device together (see module docstring). Delete the
        # now-finished main device (AND its mesh -- delete_device() alone
        # leaves the mesh registered) before creating a fresh one for the
        # equilibrium check, or that solve fails to reconverge too.
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        eq_probe = import_process_result(
            doped_result, mesh_name="phase8_eq_mesh", device_name="phase8_eq_device",
            contact_regions=["Si"], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        apply_doping(eq_probe.device, doped_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation
        setup_semiconductor_potential_equation(eq_probe.device, "Si", eq_probe.contacts, temperature_k=300.0)
        devsim.solve(type="dc", absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)
        eq_pot = devsim.get_node_model_values(device=eq_probe.device, region="Si", name="Potential")
        eq_spread = max(eq_pot) - min(eq_pot)
        n_i = devsim.get_parameter(device=eq_probe.device, region="Si", name="n_i")
        v_t = devsim.get_parameter(device=eq_probe.device, region="Si", name="V_t")
        v_bi_analytic = v_t * math.log(DONOR_CM3 * ACCEPTOR_CM3 / (n_i * n_i))
        devsim.delete_device(device=eq_probe.device)
        devsim.delete_mesh(mesh=eq_probe.mesh)

        print(f"[6/6] Equilibrium (Poisson-only, dedicated device) spread = {eq_spread:.9f} V, "
              f"analytic V_bi = {v_bi_analytic:.9f} V")
        assert abs(eq_spread - v_bi_analytic) < 1e-6, "equilibrium potential must match analytic V_bi"

        csv_path = Path(tmp) / "pn_junction_iv.csv"
        json_path = Path(tmp) / "pn_junction_iv.json"
        plot_path = Path(tmp) / "pn_junction_iv.png"
        save_csv(result, str(csv_path))
        save_json(result, str(json_path))
        save_iv_plot(result, str(plot_path))
        assert csv_path.exists() and csv_path.stat().st_size > 0
        assert json_path.exists() and json_path.stat().st_size > 0
        assert plot_path.exists() and plot_path.stat().st_size > 0
        print(f"      Output files OK -> {csv_path.name}, {json_path.name}, {plot_path.name}")

    print()
    print("PHASE 8 FULL PIPELINE (ViennaPS -> ProcessResult -> step-junction doping -> "
          "DevSim Poisson equilibrium [matches analytic V_bi] -> drift-diffusion -> "
          "continuous forward/reverse bias ramp) RAN AGAINST REAL VIENNAPS 4.6.2 + "
          "DEVSIM 2.10.1 SUCCESSFULLY")


if __name__ == "__main__":
    main()
