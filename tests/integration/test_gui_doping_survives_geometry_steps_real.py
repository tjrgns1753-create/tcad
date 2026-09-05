#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User's own final-review condition 2, executable: doping -> etch ->
oxidation -> doping must preserve BOTH the current real mesh AND every
previously-accumulated DopantProfile -- not just whichever doping call
happened last. Real GUI, real ViennaPS throughout.

Also covers condition 1: a silent re-attach (run_measurement()'s own
real code path, `run_doping(silent=True, reattach=True)`) must refresh
self.last_doped_result without appending a duplicate copy of the
profile it is only refreshing.
"""
import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.parent.parent.as_posix())


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS is not installed")
        return

    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer()
        mesh_after_materialize = app.last_final_mesh

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si"); app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(-3.0); app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(0.0)
        app.dope_gauss_acceptor_var.set(1.0e18); app.dope_gauss_acceptor_species_var.set("B")
        app.dope_gauss_donor_species_var.set("")
        assert app.run_doping(silent=True)
        print(f"[1/4] B implant: {[p.species for p in app.wafer_state.dopant_profiles]}")
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"]

        # Real etch -- geometry changes, NO doping of its own.
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02); app.etch_time_var.set(2.0)
        app.run_etch()
        mesh_after_etch = app.last_final_mesh
        print(f"[2/4] after real etch: mesh changed={mesh_after_etch != mesh_after_materialize}, "
              f"species still present={[p.species for p in app.wafer_state.dopant_profiles]}")
        assert mesh_after_etch != mesh_after_materialize, "the etch must genuinely produce a new mesh"
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"], (
            "a geometry-only etch (no doping of its own) must NOT drop the existing B profile"
        )

        # Real oxidation -- ANOTHER geometry change, still no doping.
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(900.0); app.ox_time_var.set(0.01)
        app.run_oxidation()
        mesh_after_oxidation = app.last_final_mesh
        print(f"[3/4] after real oxidation: mesh changed={mesh_after_oxidation != mesh_after_etch}, "
              f"species still present={[p.species for p in app.wafer_state.dopant_profiles]}")
        assert mesh_after_oxidation != mesh_after_etch
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"], (
            "a second geometry-only step must ALSO preserve the existing B profile"
        )

        # Second doping call -- must ADD to, not replace, what survived.
        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.dope_gauss_position_var.set(3.0); app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(2.0e18); app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P"); app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species = sorted(p.species for p in app.wafer_state.dopant_profiles)
        print(f"[4/4] after second doping (P) post-etch-post-oxidation: species={species}")
        assert species == ["B", "P"], (
            "doping -> etch -> oxidation -> doping must end with BOTH B and P present -- "
            "geometry-only steps in between must never silently drop an accumulated profile"
        )

        # Condition 1's own acceptance check: a silent re-attach (the
        # exact path run_measurement() takes when _doping_is_stale())
        # must NOT duplicate the just-added P profile.
        count_before_reattach = len(app.wafer_state.dopant_profiles)
        assert app.run_doping(silent=True, reattach=True)
        count_after_reattach = len(app.wafer_state.dopant_profiles)
        print(f"reattach=True: profile count {count_before_reattach} -> {count_after_reattach} "
              f"(must be unchanged, never duplicated)")
        assert count_after_reattach == count_before_reattach, (
            "a silent re-attach (run_measurement()'s own real code path) must never "
            "append a duplicate copy of the profile it is only refreshing"
        )

        print("Condition 2 confirmed: WaferState's geometry stays current through etch AND "
              "oxidation (neither of which carries its own doping), while every previously-"
              "accumulated DopantProfile survives both, and a later doping call correctly adds "
              "to that surviving state rather than replacing it.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
