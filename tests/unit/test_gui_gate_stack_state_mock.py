#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A gate-stack build must not leave the previous wafer resumable.

run_gate_stack() clears completed_steps because a gate stack is
terminal, but last_domain_state and last_physics_status were both
added later and were not cleared with it -- so the next RUN click
resumed the pre-gate-stack wafer, and a status log/read afterward
could still show the pre-gate-stack step's physics/numerical status.
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

        # Pretend a previous step left an accumulated wafer behind.
        app.completed_steps = [{"_process_category": "oxidation"}]
        app.last_domain_state = "C:/nonexistent/previous_wafer.vpsd"
        app.flow_step_meshes = ["C:/nonexistent/previous.vtu"]
        app.last_physics_status = {"resolution": "UNKNOWN", "entries": []}

        # The success tail of run_gate_stack, isolated from the worker.
        gui.TCADApplication._clear_state_for_gate_stack(app)

        assert app.completed_steps == [], "gate stack left completed_steps behind"
        assert app.flow_step_meshes == [], "gate stack left step meshes behind"
        assert app.last_domain_state is None, (
            "gate stack left last_domain_state set, so the next RUN would "
            "resume the PRE-gate-stack wafer")
        assert app.last_physics_status is None, (
            "gate stack left last_physics_status set, so a status log/read "
            "afterward could still show the pre-gate-stack step's status")
    finally:
        app.destroy()

    print("GATE STACK STATE CLEARED: completed_steps, step meshes, "
          "domain state, physics status")


if __name__ == "__main__":
    main()
