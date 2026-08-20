#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All 4 doping kinds through the GUI measurement panel's own path — real
ViennaPS 4.6.2 + real DevSim drift-diffusion solve.

The panel (tcad_2d_stagewise.py's run_measurement) does, verbatim:
    length_scale_to_cm = 1.0e-4
    step_junction    -> refine_near_um / refine_axis from the profile
    gaussian_implant -> auto_refine_from_doping=True
    implant_windows  -> refine_process_result_for_implant_windows()
    uniform          -> no refinement (no junction to resolve)
    run_pn_junction_iv_sweep(sweep_voltages=[voltage])   # single point
and the doping values below are the doping panel's own default field
values, so a failure here is a failure a user would actually hit on
MEASURE.

SCOPE LIMIT, and it is a real one: the WAFER below is 4x3um, while the
GUI's own default wafer is 10x8um (Wafer.width_um=10, run_etch's
y_extent_um=8.0, mask 3.5-6.5). implant_windows passes here and still
FAILS at that default wafer size — in the equilibrium solve, before any
bias — so passing this test does NOT mean a default-sized GUI run
converges. See CLAUDE.md OPEN item 2. The 4x3 case is robust rather
than lucky (perturbing the mask to 1.3-2.7 / 1.4-2.6 / 1.6-2.4 keeps
all of them converging at a consistent ~3.5e-11 A), but it is a
smaller device than the GUI ships with.

Why this test exists (measured, not assumed — see docs/investigation_log.md
"GUI measurement: which doping kinds actually converge"):

  * implant_windows at the panel's own defaults (-1e17 body, 1e20
    source/drain) USED TO FAIL OUTRIGHT with "Convergence failure!",
    because implant_windows is the one kind import_process_result's
    auto_refine_from_doping cannot serve (its DopingRegion carries
    neither junction_position_um nor peak_position_um). Its Debye
    length at 1e20 is ~1.2nm against a 0.2um process grid.

  * A LEAKED DevSim device makes an unrelated later solve fail. Proven
    three ways in one sitting: leaking a perfectly healthy uniform
    device was enough to turn a converging implant_windows solve into
    "Convergence failure!", while properly deleting even a device whose
    own solve had just FAILED left the next solve converging normally.
    devsim.solve() takes no device filter, so it iterates every
    registered device. That is why this test deletes device AND mesh
    between kinds, and why it asserts the registry is empty each time —
    an earlier scratch harness whose cleanup silently no-opped
    (delete_device(device=..., region="") raises "region is an invalid
    option", swallowed by a bare except) reported two doping kinds as
    non-convergent when only one of them had a real problem.

Checks per kind: the sweep converges, both terminals report current,
and the two terminal currents are equal and opposite (a real KCL check
on a real solved device).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import (
    import_process_result,
    refine_process_result_for_implant_windows,
)
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

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

LENGTH_SCALE_TO_CM = 1.0e-4  # the panel's own value
VOLTAGE = 0.3               # the panel's own default source voltage
REGION = "Si"


def dope_with_panel_defaults(kind, process_result):
    """The doping panel's own default field values, verbatim."""
    if kind == "uniform":
        return apply_uniform_doping(process_result, {REGION: 1.0e17})
    if kind == "step_junction":
        return apply_step_junction_doping(
            process_result, region=REGION, junction_axis="x",
            junction_position_um=0.0,
            donor_conc_cm3=1.0e18, acceptor_conc_cm3=1.0e18,
        )
    if kind == "gaussian_implant":
        return apply_gaussian_implant_doping(
            process_result, region=REGION, junction_axis="x",
            peak_position_um=0.0, straggle_um=0.5, peak_conc_cm3=1.0e17,
        )
    if kind == "implant_windows":
        return apply_implant_windows_doping(
            process_result, region=REGION, axis="x",
            background_doping_cm3=-1.0e17,
            windows=[
                {"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20},
                {"min_um": 0.6, "max_um": 1.6, "conc_cm3": 1.0e20},
            ],
        )
    raise AssertionError(f"unknown kind {kind!r}")


def measure_one_kind(kind, process_result):
    """Exactly what run_measurement() does for this kind."""
    doped_result = dope_with_panel_defaults(kind, process_result)
    assert doped_result.doping.kind == kind

    refine_kwargs = {}

    if kind == "step_junction":
        region_doping = doped_result.doping.regions[0]
        refine_kwargs = {
            "refine_near_um": region_doping.junction_position_um,
            "refine_axis": region_doping.junction_axis,
        }
    elif kind == "gaussian_implant":
        refine_kwargs = {"auto_refine_from_doping": True}
    elif kind == "implant_windows":
        # The panel calls this same function; implant_windows is the one
        # kind auto_refine_from_doping cannot derive anything for.
        refined = refine_process_result_for_implant_windows(doped_result)
        assert refined is not None, (
            "no refinement derived for implant_windows -- this kind is "
            "measured NOT to converge unrefined at these concentrations"
        )
        assert refined.doping is doped_result.doping, (
            "refined ProcessResult must carry the same DopingProfile"
        )
        assert (
            {r.name for r in refined.material_regions}
            == {r.name for r in doped_result.material_regions}
        ), "graded refinement must not add or drop a material region"
        doped_result = refined

    imported = None
    try:
        imported = import_process_result(
            doped_result, mesh_name="gui_measure_mesh",
            device_name="gui_measure_device",
            contact_regions=[REGION], contact_axis="x",
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
            **refine_kwargs,
        )
        assert len(imported.contacts) == 2, imported.contacts

        apply_doping(
            imported.device, doped_result.doping,
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )

        gnd_contact, source_contact = imported.contacts[0], imported.contacts[1]
        result = run_pn_junction_iv_sweep(
            device=imported.device, region=REGION,
            all_contacts=imported.contacts,
            sweep_contact=source_contact, sweep_voltages=[VOLTAGE],
            fixed_contacts={gnd_contact: 0.0},
        )

        node_count = len(devsim.get_node_model_values(
            device=imported.device, region=REGION, name="x"))

        point = result.points[-1]
        i_source = point.currents[source_contact]
        i_gnd = point.currents[gnd_contact]
        return node_count, source_contact, i_source, gnd_contact, i_gnd

    finally:
        # BOTH calls, and not inside a bare except: a leaked device (even
        # a healthy one) makes the NEXT kind's solve fail, because
        # devsim.solve() has no device filter. See this module's docstring.
        if imported is not None:
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)


def main():
    kinds = ["uniform", "step_junction", "gaussian_implant", "implant_windows"]

    with tempfile.TemporaryDirectory() as tmp:
        step_result = registry.get("etching", "isotropic")().run(RECIPE, tmp)
        process_result = build_process_result(step_result)
        print(f"[1/{len(kinds) + 1}] real ViennaPS etch OK -> "
              f"{[r.name for r in process_result.material_regions]}")

        for index, kind in enumerate(kinds, start=2):
            nodes, src, i_src, gnd, i_gnd = measure_one_kind(kind, process_result)

            assert abs(i_src) > 0.0, f"{kind}: source terminal reported zero current"
            denominator = max(abs(i_src), abs(i_gnd))
            kcl_error = abs(i_src + i_gnd) / denominator
            # Threshold set from measurement, not taste. The loosest of
            # the four is step_junction's blocking junction: I = 4.93e-11 A
            # with the two terminals differing by 1.0e-15 A absolute, i.e.
            # 2.0e-5 relative -- solver noise amplified by taking a
            # relative error of a near-zero current, not lost charge. A
            # device that genuinely failed to conserve charge would differ
            # by a FACTOR, so 1e-3 still separates the two cases by orders
            # of magnitude. (The other three kinds land at 1e-13..1e-18.)
            assert kcl_error < 1.0e-3, (
                f"{kind}: terminal currents not equal and opposite: "
                f"{src}={i_src:.6e} {gnd}={i_gnd:.6e} (rel err {kcl_error:.2e})"
            )

            # A leaked device would silently break the NEXT kind, so make
            # that failure mode loud and immediate instead.
            assert devsim.get_device_list() == (), (
                f"{kind}: devices still registered after cleanup: "
                f"{devsim.get_device_list()}"
            )

            print(f"[{index}/{len(kinds) + 1}] {kind:17s} converged at "
                  f"V={VOLTAGE}: {nodes:6d} nodes  {src}={i_src:+.6e} A  "
                  f"{gnd}={i_gnd:+.6e} A  (KCL rel err {kcl_error:.1e})")

    print()
    print("ALL 4 DOPING KINDS CONVERGE THROUGH THE GUI MEASUREMENT PANEL'S "
          "OWN PATH, at the doping panel's own default field values")
    print("NOTE: on a 4x3um wafer. implant_windows still FAILS on the GUI's "
          "default 10x8um wafer -- see CLAUDE.md OPEN item 2.")


if __name__ == "__main__":
    main()
