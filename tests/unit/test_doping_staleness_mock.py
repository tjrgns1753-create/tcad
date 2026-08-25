#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doping must not keep pointing at a mesh a later step replaced.

last_doped_result is set once when doping runs and cleared only by NEW
WAFER. After a later process step, measurement read that stale object
and solved the geometry as it was BEFORE the step.

This is a unit test, not an integration test: it exercises
_doping_is_stale() directly against stub state, which is pure logic
and needs neither ViennaPS nor DevSim.

Also covers (review finding on the original fix): the first block
above only drives _doping_is_stale() against a stub, so it would still
pass even if run_doping()'s trailing `return True` were lost (falling
back to an implicit, falsy `None`) or if run_measurement()'s whole
re-attachment block were deleted -- the dangerous case being a SILENT
abort of every measurement whenever doping is stale, with no error
dialog. The second block below exercises the REAL run_doping() and
run_measurement() methods against that, still with no ViennaPS/DevSim:
only the DevSim import boundary (tcad.device.devsim.backend,
tcad.device.devsim.mesh_import.import_process_result) is stubbed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui
        from tcad.device.devsim import backend as devsim_backend
        import tcad.device.devsim.mesh_import as mesh_import_mod

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    try:
        app.withdraw()
        app.update_idletasks()

        class _Stub:
            pass

        doped = _Stub()
        doped.volume_mesh_path = "C:/meshes/step_A.vtu"

        app.last_doped_result = doped
        app.last_final_mesh = "C:/meshes/step_A.vtu"
        assert app._doping_is_stale() is False, (
            "doping on the current mesh must not read as stale")

        # A later process step produced a new mesh.
        app.last_final_mesh = "C:/meshes/step_B.vtu"
        assert app._doping_is_stale() is True, (
            "doping still points at the mesh from before the last step, so "
            "a measurement would solve the wrong geometry")

        app.last_doped_result = None
        assert app._doping_is_stale() is False, "no doping cannot be stale"

        # ------------------------------------------------------------
        # Wiring coverage below drives the REAL run_doping() and
        # run_measurement() methods -- not stand-ins for them -- so a
        # deleted `return True` or a deleted re-attachment block would
        # actually be caught. Only the genuine ViennaPS/DevSim boundary
        # is stubbed:
        #   - build_process_result / apply_uniform_doping (module-
        #     level names in tcad_2d_stagewise, so run_doping() never
        #     needs a real ViennaPS mesh)
        #   - devsim_backend.is_available/require_devsim and
        #     mesh_import.import_process_result (so run_measurement()
        #     never needs a real DevSim solve)
        #   - messagebox, silenced so a caught exception can't pop a
        #     real dialog and hang the test
        # last_final_mesh is pointed at two real, always-present files
        # on disk (this script, and the Python interpreter binary) to
        # stand in for "mesh before" / "mesh after a later step" --
        # run_doping()'s own guard only checks the path exists, and the
        # faked build_process_result never reads it.
        # ------------------------------------------------------------
        real_build_process_result = gui.build_process_result
        real_apply_uniform_doping = gui.apply_uniform_doping
        mesh_a = str(Path(__file__).resolve())
        mesh_b = sys.executable

        created = []

        def _fake_apply_uniform_doping(process_result, regions):
            result = _Stub()
            result.volume_mesh_path = app.last_final_mesh
            result.material_regions = []
            result.doping = _Stub()
            result.doping.kind = "uniform"
            region_stub = _Stub()
            region_stub.region = "Si"
            result.doping.regions = [region_stub]
            created.append(result)
            return result

        gui.build_process_result = lambda step_result: _Stub()
        gui.apply_uniform_doping = _fake_apply_uniform_doping

        devsim_backend.is_available = lambda: True
        devsim_backend.require_devsim = lambda: object()

        real_messagebox = gui.messagebox

        class _QuietMessagebox:
            def showinfo(self, *a, **k):
                pass

            def showerror(self, *a, **k):
                pass

        gui.messagebox = _QuietMessagebox()

        real_import_process_result = mesh_import_mod.import_process_result
        reached = {"called": False, "process_result": None}

        def _fake_import_process_result(process_result, **kwargs):
            # Stands in for the real mesh-import/DevSim boundary: just
            # far enough into run_measurement() to prove which
            # doped_result it carried, then stop before any real solve.
            reached["called"] = True
            reached["process_result"] = process_result
            raise RuntimeError("test boundary -- stop before any real solve")

        mesh_import_mod.import_process_result = _fake_import_process_result

        try:
            app.dope_uniform_region_var.set("Si")
            # Donor/acceptor replaced the single net-concentration field
            # this session (see CLAUDE.md's Doping fix) -- net = 1e17,
            # same value this test always used; only the field names
            # that carry it changed.
            app.dope_uniform_donor_var.set("1e17")
            app.dope_uniform_acceptor_var.set("0")

            # (1) run_doping()'s bool-return contract -- the one site
            # the finding calls out by name: a lost trailing
            # `return True` would collapse this to a falsy `None`,
            # which is exactly what would make run_measurement's
            # `if not self.run_doping(): return` silently treat a
            # SUCCESSFUL re-attachment as a failure.
            app.doping_kind.set("Uniform")
            app.last_final_mesh = mesh_a
            app.last_doped_result = None
            assert app.run_doping() is True, (
                "run_doping() must return True, not just something "
                "truthy, on success")
            assert app.last_doped_result is created[-1]

            # A second of the four `return False` sites (the first,
            # `_materialize_current_wafer()` failing, is cheaper still
            # and checked separately below) -- not the dangerous case
            # itself, but confirms the shape holds elsewhere too.
            stale = app.last_doped_result
            app.doping_kind.set("Not A Real Kind")
            assert app.run_doping() is False, (
                "run_doping() must return False for an unrecognized "
                "doping kind")
            assert app.last_doped_result is stale, (
                "a failed run_doping() must not touch last_doped_result")

            app._materialize_current_wafer = lambda: False
            app.last_final_mesh = None
            assert app.run_doping() is False, (
                "run_doping() must return False when it can't "
                "materialize a wafer to dope")
            del app._materialize_current_wafer

            # (2) run_measurement()'s re-attachment wiring, driven by
            # the REAL run_doping() above (no stand-in), against a
            # "later step moved the mesh on" scenario.
            #
            # Branch A: doping is stale, and the real re-attachment
            # run_doping() call genuinely fails (unknown kind) ->
            # run_measurement must return before ever reaching the
            # mesh-import boundary.
            app.last_doped_result = stale  # attached to mesh_a
            app.last_final_mesh = mesh_b   # a later step's mesh
            app.doping_kind.set("Not A Real Kind")
            assert app._doping_is_stale() is True

            app.run_measurement()

            assert reached["called"] is False, (
                "run_measurement must not reach the mesh-import "
                "boundary when the real re-attachment run_doping() "
                "call fails")
            assert app.last_doped_result is stale, (
                "a failed re-attachment must not replace "
                "last_doped_result")

            # Branch B: doping is stale, and the real re-attachment
            # run_doping() call genuinely succeeds -> run_measurement
            # must proceed past the re-attachment block and use the
            # REFRESHED last_doped_result, not the stale one it read
            # before the check.
            app.doping_kind.set("Uniform")
            assert app._doping_is_stale() is True

            app.run_measurement()

            assert reached["called"] is True, (
                "run_measurement did not proceed past the "
                "re-attachment block after run_doping() reported "
                "success")
            assert app.last_doped_result is not stale, (
                "run_doping() should have re-attached to a fresh "
                "result")
            assert reached["process_result"] is app.last_doped_result, (
                "run_measurement used the STALE doped_result instead "
                "of re-reading self.last_doped_result after a "
                "successful re-attachment")
        finally:
            gui.build_process_result = real_build_process_result
            gui.apply_uniform_doping = real_apply_uniform_doping
            mesh_import_mod.import_process_result = real_import_process_result
            gui.messagebox = real_messagebox
    finally:
        app.destroy()

    print("DOPING STALENESS DETECTED against the current mesh")
    print("RUN_DOPING BOOL CONTRACT + RUN_MEASUREMENT RE-ATTACHMENT WIRING COVERED")


if __name__ == "__main__":
    main()
