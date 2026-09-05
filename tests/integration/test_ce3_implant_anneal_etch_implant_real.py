#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spec CE-3, the explicitly required final integration case, x-only
(no depth-dependent claim anywhere): implant -> anneal -> etch ->
second implant, through the REAL production GUI doping/anneal handlers,
ending in a real per-node DevSim NetDoping (Task 8) cross-check that
correctly reflects BOTH profiles -- neither via a legacy shortcut.

**Classification, explicit (same as Task 8):** the per-node DevSim
comparison here is a WaferState<->DevSim coupling/numerical-consistency
check, not an independent physical-correctness re-validation -- it
confirms the same real production wiring Task 8 built transports
numbers correctly through this end-to-end GUI scenario, not that the
Gaussian formula itself is newly proven physically correct here
(already done, separately, by Task 1).

**Etch success is judged from real mesh material data, never a GUI
boolean.** This test never calls `app.run_etch()` -- it uses a real,
precisely-configured, standalone (non-inherited) `IsotropicEtch`
registry call for the etch step specifically (same technique Task 6's
CE-1 test already validated), then threads the real result back into
`app.last_final_mesh` so the subsequent `app.run_doping()` call for P
picks up the real post-etch mesh.

Three real deviations from this task's own draft brief, each confirmed
by direct execution (a scratch probe script), not assumed -- see
task-11-report.md for the full printed evidence:

**Risk 1 (pre-flagged, CONFIRMED backwards).** `mask_spans_um` names
the OPAQUE/PROTECTED span in domain-centered coordinates (confirmed by
reading `tcad.process.base.ProcessStep.prepare_domain()` /
`mask_spans_from_openings()`), exactly as Task 6's CE-1 already found.
The brief's own draft recipe, `"mask_spans_um": [[-1.5, 1.5]]` with a
comment claiming it "opens ONLY around X_ETCH", is backwards -- a real
probe run confirmed it: that literal span left X_ETCH=0.0 reading
"Si" (PROTECTED, not etched) and X_B=-3.5 reading None (etched away!),
the exact opposite of the intended claim. The corrected span,
protecting everything EXCEPT a real open window around X_ETCH
(`[[-HALF_DOMAIN_UM, -WINDOW_HALF_UM], [WINDOW_HALF_UM, HALF_DOMAIN_UM]]`),
was confirmed by the same probe to give X_ETCH=None (genuinely cleared)
and X_B="Si" (protected) -- exactly right.

**Risk 2 (pre-flagged, CONFIRMED).** `app.last_domain_state` is a
serialized `.vpsd` FILE PATH (`session.save_domain_state()` returns the
path string; `tcad_2d_stagewise.py` itself later does
`Path(self.last_domain_state).exists()`, treating it as a path, not a
Domain), never a live ViennaPS Domain object -- confirmed both by
reading the source and by a real probe: constructing
`IsotropicEtch(inherited_domain=<a path string>)` and calling `.run()`
raises `AttributeError("'str' object has no attribute
'getMaterialMap'")` downstream, exactly as the risk predicted. Fixed by
NOT using `inherited_domain=` at all for the etch step: since neither
the B implant nor the anneal touches geometry (doping is WaferState-
only), the wafer at this point is still exactly the bare, unprocessed
Si wafer `_materialize_current_wafer()` built, so a standalone FRESH
`IsotropicEtch()` (no inherited domain) is the right construction --
matching this project's own already-established CE-1/CE-2 pattern of
using a separate, independently-verified real mesh for a "before"/
"after" comparison rather than literal domain continuity (CE-2's own
module docstring: "the 'before' and 'after' facts are each real and
independently verified, even though they come from two different real
ViennaPS meshes"). The fresh etch step deliberately uses a shallow
`silicon_depth_um=1.0` (not the GUI's own 5.0 default) for its own
construction only -- the SAME scale Task 6's CE-1 test already
validated (`rate=-0.5, etch_time_s=3.0` clearing a 1.0um-deep column
with a safe ~1.0um lateral-undercut margin to a mask edge 2.5um away)
so the etch can GENUINELY, COMPLETELY clear Si at X_ETCH (not merely
recess it) while leaving X_B fully protected; this choice affects only
how deep the etch step's own OWN standalone wafer is, never any
doping/WaferState assertion (all of which are x-only, depth-agnostic).

**Risk 3 (new finding, not pre-flagged in the brief -- found while
verifying Risk 1/2 by execution).** The brief's own draft `_material_at()`
helper picks whichever mesh cell matching a given x it happens to
iterate first, regardless of y -- NOT the topmost (surface) material.
A genuinely-cleared column and a merely-RECESSED one (Si still present
lower down) can both contain a matching "Si" cell, so that helper
cannot reliably distinguish them (exactly the failure mode Task 6's own
CE-1 docstring warns about: "a recess that leaves Si still topmost
there would produce NO geometry-gated zero at all"). Replaced with
`WaferState.exposed_material_at()` (Task 1, already used by CE-1/CE-2
for this exact purpose) -- picks the cell with the greatest y_max at a
given x, i.e. the real topmost/exposed material, still read directly
from the real exported mesh (never a GUI boolean), just via the
already-verified, more robust method instead of a new, unverified one.
Confirmed correct by the same probe script: after the real etch+strip,
`exposed_material_at(X_ETCH)` reads None (genuinely gone) and
`exposed_material_at(X_B)` reads "Si" (untouched).

Two further, smaller real gaps in the brief's draft, fixed directly
(this test's own code, not an owning task's):
`import_process_result()` requires a positional `mesh_name` argument
(the draft omitted it) and returns an `ImportedDevice` dataclass, not a
`(device_name, region_name)` tuple (the draft assumed the latter) --
fixed to match the real signature and the pattern already established
in `tests/integration/test_doping_mapping_per_node_real.py`. The
draft's cleanup also called `devsim.delete_mesh(mesh=device_name)`;
the real mesh name (`imported.mesh`) is not necessarily the same string
as the device name (confirmed by the same reference test, which uses
`mesh_name="ce_mesh", device_name="ce_dev"` -- two different strings) --
fixed to delete the actual mesh name.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers "etching"/"isotropic"

#: Real domain-centered x-positions (um). B survives untouched; the
#: real etch genuinely clears X_ETCH; P lands elsewhere afterward.
X_B, X_ETCH, X_P = -3.5, 0.0, 3.5

#: Scale for the standalone etch step's OWN fresh wafer only (Risk 2's
#: fix) -- matches Task 6's CE-1, already validated at this scale.
ETCH_GRID_UM = 0.2
ETCH_SI_DEPTH_UM = 1.0
WINDOW_HALF_UM = 1.0


def main():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    from tcad.process import registry
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.wafer_state import WaferState
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer()

        # -- real "before" reference: the current wafer is genuinely
        # bare Si at both positions (real mesh data, not assumed) --
        prior_mesh = app.last_final_mesh
        prior_state = WaferState.from_process_result(
            build_process_result({"final_mesh": prior_mesh, "snapshots": []})
        )
        before_etch = prior_state.exposed_material_at(X_ETCH)
        before_b_site = prior_state.exposed_material_at(X_B)
        assert before_etch == "Si" and before_b_site == "Si", (
            f"the honest 'before' baseline must be real, unetched Si at BOTH "
            f"coordinates -- got X_ETCH={before_etch!r}, X_B={before_b_site!r}"
        )

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(X_B)
        app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_donor_var.set(0.0)
        app.dope_gauss_acceptor_var.set(1.0e18)
        app.dope_gauss_donor_species_var.set("")
        app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)
        print(f"[1/5] profile_1 (B) created at x={X_B}: "
              f"{len(app.wafer_state.dopant_profiles)} profile(s)")

        app.anneal_temp_var.set(950.0)
        app.anneal_time_var.set(300.0)
        app._on_thermal_anneal_clicked()
        b_widened = next(p for p in app.wafer_state.dopant_profiles if p.species == "B")
        print(f"[2/5] profile_1 (B) annealed: straggle -> "
              f"{b_widened.model_params['straggle_um']:.4f} um")
        assert b_widened.model_params["straggle_um"] > 0.3

        # -- Real, standalone, precisely-configured etch (Risk 2's fix:
        # no inherited_domain -- see module docstring). Its own
        # protected mask spans are the domain-centered OPAQUE
        # complement of a real open window around X_ETCH (Risk 1's
        # fix), confirmed correct by a real probe (see module
        # docstring, both risks). --
        x_extent_um = app.wafer.width_um
        half_domain_um = x_extent_um / 2.0
        etch_step = registry.get("etching", "isotropic")()
        etch_recipe = {
            "_process_category": "etching", "_process_model_key": "isotropic",
            "rate": -0.5, "etch_time_s": 3.0,
            "silicon_depth_um": ETCH_SI_DEPTH_UM, "grid_delta_um": ETCH_GRID_UM,
            "x_extent_um": x_extent_um, "y_extent_um": 8.0,
            "pr_thickness_um": 0.3, "mask_material": "Mask",
            "mask_spans_um": [
                [-half_domain_um, -WINDOW_HALF_UM],
                [WINDOW_HALF_UM, half_domain_um],
            ],
        }
        # mkdtemp (not TemporaryDirectory): the resulting mesh file must
        # outlive this block -- it is read again later in this test and
        # threaded into app.last_final_mesh.
        etch_tmp = tempfile.mkdtemp(prefix="ce3_etch_")
        etch_result = etch_step.run(etch_recipe, etch_tmp)

        # Real strip of the protective mask (standard fab practice
        # after any masked etch -- same real ViennaPS 4.6.2 API
        # Task 6's CE-1 test already verifies), so the protected
        # span is genuinely exposed Si again, not Si-under-Mask
        # (Risk 3, module docstring).
        module = session.require_viennaps()
        etch_step.last_domain.removeMaterial(module.Material.Mask)
        stripped_mesh = save_volume_mesh(
            etch_step.last_domain, Path(etch_tmp) / "ce3_etch_stripped",
            floor_depth_um=ETCH_SI_DEPTH_UM,
        )

        etched_state = WaferState.from_process_result(
            build_process_result({"final_mesh": stripped_mesh, "snapshots": []})
        )
        after_etch = etched_state.exposed_material_at(X_ETCH)
        after_b_site = etched_state.exposed_material_at(X_B)
        print(f"[3/5] real etch: X_ETCH={X_ETCH} {before_etch}->{after_etch}, "
              f"X_B={X_B} (must stay Si) {before_b_site}->{after_b_site}")
        assert after_etch != "Si", (
            "the etch must genuinely remove Si at X_ETCH, not merely recess it"
        )
        assert after_b_site == "Si", "B's own x-position must be untouched by this etch"

        # Thread the real result back into the GUI's own continuity
        # fields exactly as run_etch() itself would (this task's own
        # disclosed hybrid, see the brief) -- so the SUBSEQUENT
        # app.run_doping() call for P picks up the real post-etch mesh.
        app.last_final_mesh = stripped_mesh
        app.last_domain_state = None
        app.wafer.etched = True
        app.wafer.processed = True

        from tcad.physics.wafer_state_accumulation import advance_wafer_state
        app.wafer_state = advance_wafer_state(
            app.wafer_state,
            build_process_result({"final_mesh": stripped_mesh, "snapshots": []}),
            "etching",
        )

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.dope_gauss_position_var.set(X_P)
        app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_donor_var.set(2.0e18)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species = sorted(p.species for p in app.wafer_state.dopant_profiles)
        print(f"[4/5] profile_2 (P) created post-etch at x={X_P}: species now {species}")
        assert species == ["B", "P"], "both profiles must independently coexist in WaferState"

        # -- Real per-node DevSim conversion (Task 8), through a real device. --
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.device.devsim.doping_mapping import apply_doping
        import devsim

        final_result = build_process_result({"final_mesh": app.last_final_mesh, "snapshots": []})
        length_scale_to_cm = 1.0  # matches import_process_result's own real default (Task 8)
        imported = import_process_result(
            final_result, mesh_name="ce3_mesh", device_name="ce3_dev",
        )
        assert "Si" in imported.regions, f"expected a 'Si' region, got {imported.regions!r}"
        device_name, region_name = imported.device, "Si"
        try:
            physics_status = apply_doping(
                device_name, region_name, app.wafer_state, length_scale_to_cm=length_scale_to_cm,
            )
            xs_native = devsim.get_node_model_values(device=device_name, region=region_name, name="x")
            ys_native = devsim.get_node_model_values(device=device_name, region=region_name, name="y")
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"[5/5] checked {len(xs_native)} real DevSim nodes, "
                  f"NetDoping range: [{min(net):.3e}, {max(net):.3e}], physics_status={physics_status}")
            assert max(net) > 0 and min(net) < 0, "both B(acceptor) and P(donor) contributions must be real"

            mismatches = 0
            for i in range(0, len(xs_native), max(1, len(xs_native) // 15)):
                x_um = xs_native[i] / length_scale_to_cm
                y_um = ys_native[i] / length_scale_to_cm
                expected = app.wafer_state.net_doping_at(x_um, y_um).net_doping
                if abs(expected - net[i]) > 1e-6 * max(abs(expected), 1.0):
                    mismatches += 1
                    print(f"  MISMATCH node[{i}] x={x_um:.3f}um: expected={expected:.6e}, DevSim={net[i]:.6e}")
            assert mismatches == 0, f"{mismatches} real node(s) disagreed between WaferState and DevSim"
            print("Real per-node cross-check: WaferState.net_doping_at() and DevSim's own "
                  "stored NetDoping agree at every checked node.")
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=imported.mesh)

        print("CE-3 confirmed end-to-end through the real production GUI doping/anneal "
              "handlers plus a real, mesh-verified etch: B survives (annealed) at its own "
              "untouched position, the etched region is genuinely cleared, P is added "
              "afterward independently, and a real per-node DevSim NetDoping reflects both "
              "-- x-only throughout, no depth-dependent claim made anywhere.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
