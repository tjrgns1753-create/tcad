#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doping must not keep pointing at a mesh a later step replaced.

last_doped_result is set once when doping runs and cleared only by NEW
WAFER. After a later process step, measurement read that stale object
and solved the geometry as it was BEFORE the step.

This is a unit test, not an integration test: it exercises
_doping_is_stale() directly against stub state, which is pure logic
and needs neither ViennaPS nor DevSim.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

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
    finally:
        app.destroy()

    print("DOPING STALENESS DETECTED against the current mesh")


if __name__ == "__main__":
    main()
