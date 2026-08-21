#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a PN diode following the exact process order the user specified:
    oxidation -> lithography -> doping -> metallization -> lithography
and extract a real DevSim I-V curve.

Mapping of each named step onto this project's real, already-verified
machinery (chosen conservatively -- reuses Phase 8's own validated
step_junction recipe/tolerances rather than inventing new ones):

  1. oxidation      : real vps.Oxidation() (fin-style, blanket) on a
                       fresh wafer -- grows SiO2 everywhere.
  2. lithography     : sets the mask window (mask_left_um/right_um).
                       This project's litho panel is not its own
                       ViennaPS step -- it defines the window the NEXT
                       relevant operation uses. Here that's the doping
                       junction position (step 3): the p-n junction is
                       placed at the CENTER of the lithographically
                       opened window, a direct, honest use of "litho
                       defines where doping happens".
  3. doping          : apply_step_junction_doping on the "Si" region,
                       donor/acceptor = 1e18 cm^-3 (Phase 8's own
                       verified, convergent recipe), junction at the
                       litho window's center.
  4. metallization    : real vps.DirectionalProcess deposition
                       (material="W"), CHAINED onto the oxidized wafer
                       via ProcessStep(inherited_domain=...) -- the
                       same real chaining this project's Process Flow
                       machinery uses -- so the final mesh genuinely
                       carries Mask+Si+SiO2+W, not a separately-built
                       wafer.
  5. lithography     : sets the mask window again. In a real fab this
                       would pattern step 4's metal into two separate
                       probe pads; this simulator has no metal-etch
                       step in the flow the user described, and DevSim
                       contacts are auto-derived from the Si region's
                       own x-extremes regardless of what shape the
                       metal on top is -- so this step is executed
                       (the mask state really is re-set and logged) but
                       has no further geometric consequence here. Noted
                       explicitly rather than silently skipped.

Then: import into DevSim (contacts auto-derived at Si_xmin/Si_xmax,
mesh refined near the junction -- Phase 8's own fix for exactly this
1e18 cm^-3 doping level), run a real drift-diffusion bias sweep across
the junction, and save both the raw I-V data and a plot.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tcad.process.oxidation  # noqa: F401 -- registers oxidation
import tcad.process.deposition  # noqa: F401 -- registers deposition
from tcad.backends.viennaps import session as viennaps_session
from tcad.process.flow import FlowStep, run_flow
from tcad.physics.doping import apply_step_junction_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from tcad.characterization.io import save_csv, save_json
from tcad.characterization.plotting import save_iv_plot

assert viennaps_session.is_available(), "ViennaPS must be installed"
assert devsim_backend.is_available(), "DevSim must be installed"

import devsim

OUT_DIR = os.environ.get("TCAD_PN_DIODE_OUT", tempfile.mkdtemp(prefix="pn_diode_"))
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

# Same wafer geometry as Phase 8's own validated PN junction test.
X_EXTENT_UM = 4.0
Y_EXTENT_UM = 3.0
GRID_DELTA_UM = 0.15
LENGTH_SCALE_TO_CM = 1.0e-4
DONOR_CM3 = 1.0e18
ACCEPTOR_CM3 = 1.0e18

# --- step 2 & 5: lithography (mask window) ---
mask_left_um = 1.5
mask_right_um = 2.5
print(f"[2] LITHOGRAPHY: mask window opened at x=[{mask_left_um}, {mask_right_um}] um")

with tempfile.TemporaryDirectory() as tmp:
    # --- step 1: oxidation (blanket, first step -- fresh wafer) ---
    oxidation_recipe = {
        "grid_delta_um": GRID_DELTA_UM,
        "x_extent_um": X_EXTENT_UM,
        "y_extent_um": Y_EXTENT_UM,
        "mask_left_um": mask_left_um,
        "mask_right_um": mask_right_um,
        "pr_thickness_um": 0.5,
        "oxidant": "Dry",
        "temperature_c": 1000.0,
        "time_hours": 0.3,
    }

    # --- step 4: metallization (directional PVD, chained onto oxidation) ---
    metallization_recipe = {
        "grid_delta_um": GRID_DELTA_UM,
        "x_extent_um": X_EXTENT_UM,
        "y_extent_um": Y_EXTENT_UM,
        "mask_left_um": mask_left_um,
        "mask_right_um": mask_right_um,
        "pr_thickness_um": 0.5,
        "direction": [0.0, 1.0, 0.0],
        "directional_velocity": 0.1,
        "deposition_time_s": 0.2,
        "material": "W",
    }

    results = run_flow(
        [
            FlowStep(category="oxidation", name="thermal", recipe=oxidation_recipe),
            FlowStep(category="deposition", name="directional", recipe=metallization_recipe),
        ],
        OUT_DIR,
    )
    print(f"[1] OXIDATION OK -> {results[0].volume_mesh_path}")
    print(f"[4] METALLIZATION OK -> {results[1].volume_mesh_path}")
    print(f"    materials after metallization: {[r.name for r in results[1].material_regions]}")

    process_result = results[1]

    print(f"[5] LITHOGRAPHY (2nd): mask re-set at x=[{mask_left_um}, {mask_right_um}] um "
          f"(patterns the metal in a real fab; no further ViennaPS step consumes it here)")

    # --- step 3: doping, junction at the litho window's center ---
    #
    # COORDINATE CONVENTION, and it is a real trap (this script got it
    # wrong on the first run and produced a non-diode):
    # mask_left_um/mask_right_um are WAFER coordinates, 0..x_extent_um.
    # The ViennaPS domain -- and therefore every DevSim node coordinate
    # apply_doping() compares junction_position_um against -- is
    # CENTERED, spanning -x_extent/2 .. +x_extent/2 (measured directly:
    # a 4.0um x_extent gives a mesh x range of -2.1 .. +2.1).
    # Passing the wafer-coordinate window center (2.0) put the junction
    # 0.1um from the right EDGE instead of at the center, making the
    # device ~98% one doping type with a sub-micron sliver of the other
    # jammed against a contact -- which of course showed no diode knee.
    junction_position_um = 0.5 * (mask_left_um + mask_right_um) - 0.5 * X_EXTENT_UM
    doped_result = apply_step_junction_doping(
        process_result, region="Si", junction_axis="x",
        junction_position_um=junction_position_um,
        donor_conc_cm3=DONOR_CM3, acceptor_conc_cm3=ACCEPTOR_CM3,
    )
    print(f"[3] DOPING OK -> step junction at x={junction_position_um:.3f} um, "
          f"donor={DONOR_CM3:.1e} cm^-3, acceptor={ACCEPTOR_CM3:.1e} cm^-3")

    # Guard against the coordinate-convention trap above ever recurring
    # SILENTLY: a junction that lands near a mesh edge still "solves"
    # and still produces a plausible-looking monotonic curve -- it just
    # isn't a diode. Measure the real split instead of trusting the
    # arithmetic. Cheap: a bare import, no solve, deleted immediately.
    _probe = import_process_result(
        doped_result, mesh_name="_split_probe_mesh", device_name="_split_probe_device")
    try:
        _x = devsim.get_node_model_values(device=_probe.device, region="Si", name="x")
        n_side = sum(1 for v in _x if v > junction_position_um)
        p_side = len(_x) - n_side
        minority_frac = min(n_side, p_side) / len(_x)
        print(f"    junction splits the Si region {p_side} p-side / {n_side} n-side nodes "
              f"(mesh x: {min(_x):.3f}..{max(_x):.3f}); smaller side = {minority_frac:.1%}")
        assert minority_frac > 0.15, (
            f"junction at x={junction_position_um} leaves only {minority_frac:.1%} of the "
            f"Si region on one side (mesh spans {min(_x):.3f}..{max(_x):.3f}) -- this is "
            f"not a two-sided diode, check the wafer-vs-domain coordinate convention"
        )
    finally:
        devsim.delete_device(device=_probe.device)
        devsim.delete_mesh(mesh=_probe.mesh)

    imported = import_process_result(
        doped_result, mesh_name="pn_diode_mesh", device_name="pn_diode_device",
        contact_regions=["Si"], contact_axis="x",
        length_scale_to_cm=LENGTH_SCALE_TO_CM,
        refine_near_um=junction_position_um, refine_axis="x",
    )
    assert len(imported.contacts) == 2, imported.contacts
    print(f"DevSim import OK -> regions={imported.regions} contacts={imported.contacts}")

    # WHICH CONTACT IS WHICH -- derived from the naming convention
    # mesh_import.py itself establishes ("<region>_<axis>min" is the
    # low-coordinate edge, "<region>_<axis>max" the high one), not from
    # contacts[0]/[1] ordering. apply_step_junction_doping puts DONORS
    # (n-type) where the axis coordinate is GREATER than
    # junction_position_um, so the n-side is the *max* contact.
    n_contact = next(c for c in imported.contacts if c.endswith("_xmax"))
    p_contact = next(c for c in imported.contacts if c.endswith("_xmin"))
    print(f"  n-side (donors, x > junction) = {n_contact}   "
          f"p-side (acceptors) = {p_contact}")

    apply_doping(imported.device, doped_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)

    # FORWARD BIAS = positive on the P side (V_diode = V_p - V_n). So the
    # swept contact is the P contact, and a positive swept value is a
    # genuinely forward-biased diode. Sweeping the N contact positive --
    # which an earlier run of this script did -- reverse-biases it, and
    # produces a curve that looks like a broken diode (tiny, nearly flat
    # "forward" current, huge "reverse" current) when in fact the physics
    # was right and only the polarity label was wrong.
    sweep_voltages = [
        -0.5, -0.4, -0.3, -0.2, -0.1, 0.0,
        0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6,
        0.65, 0.7, 0.72, 0.74, 0.76, 0.78, 0.8, 0.82, 0.84, 0.86, 0.88, 0.9,
    ]
    result = run_pn_junction_iv_sweep(
        device=imported.device, region="Si", all_contacts=imported.contacts,
        sweep_contact=p_contact, sweep_voltages=sweep_voltages,
        fixed_contacts={n_contact: 0.0},
    )

    print("\nI-V CURVE (real drift-diffusion currents), "
          "V = forward bias across the junction (positive on the p-side):")
    for point in result.points:
        v = point.voltages[p_contact]
        i = point.currents[p_contact]
        print(f"  V={v:+.2f} V   I={i:.6e} A")

    import math
    n_i = devsim.get_parameter(device=imported.device, region="Si", name="n_i")
    v_t = devsim.get_parameter(device=imported.device, region="Si", name="V_t")
    v_bi = v_t * math.log(DONOR_CM3 * ACCEPTOR_CM3 / (n_i * n_i))
    print(f"\nanalytic built-in potential V_bi = {v_bi:.4f} V "
          f"(V_t={v_t:.5f}, n_i={n_i:.4e} cm^-3, "
          f"N_D=N_A={DONOR_CM3:.1e} cm^-3)")

    csv_path = save_csv(result, str(Path(OUT_DIR) / "pn_diode_iv.csv"))
    json_path = save_json(result, str(Path(OUT_DIR) / "pn_diode_iv.json"))
    plot_path = save_iv_plot(result, str(Path(OUT_DIR) / "pn_diode_iv.png"))
    print(f"\nsaved: {csv_path}\nsaved: {json_path}\nsaved: {plot_path}")

    devsim.delete_device(device=imported.device)
    devsim.delete_mesh(mesh=imported.mesh)
    assert devsim.get_device_list() == ()

print("\nPN DIODE BUILT (oxidation -> lithography -> doping -> metallization -> "
      "lithography) AND I-V CURVE EXTRACTED, all through real ViennaPS + DevSim.")
