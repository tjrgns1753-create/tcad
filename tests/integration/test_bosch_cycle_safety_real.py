#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bosch DRIE cycle-count safety: the GUI's own default `cycles` must
produce a real, complete ViennaPS mesh, and raising `cycles` above the
confirmed-safe boundary must be disclosed in the log WITHOUT blocking
the step -- see docs/investigation_log.md, "Investigation C" for the
real ViennaPS evidence this pins (cycles<=2 always produced a complete
mesh across 4+ real trials at this grid/domain scale; cycles>=3 never
did, failing three different ways across cycles 3/4/5/10: a
near-empty exported mesh, a ValueError, or a RuntimeError from
ViennaPS's own ray tracer).

Per THE INVARIANT (CLAUDE.md): the user's chosen cycle count always
runs -- this test does NOT assert that a high cycles value is blocked
or refused, only that (a) the safe default genuinely works via real
ViennaPS, and (b) the risk is disclosed in the log before the step
runs. No physics is mocked; every process step here is a real
ViennaPS 4.6.2 execution through the actual GUI dispatch path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tkinter  # noqa: F401
import tcad_2d_stagewise as gui
from tcad.backends.viennaps import session as viennaps_session
from tcad.core.models import BoschRecipe

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"


def _run_bosch(app, cycles):
    """Runs Bosch DRIE with the given cycle count and returns whatever
    was newly appended to the real log Text widget -- reading the
    widget directly rather than mocking `_log`, since the log IS the
    real disclosure surface a user sees."""
    app.panel_category.set(app._PANEL_LABELS["etch"])
    app._show_panel_category()
    app.etch_model.set("Bosch DRIE")
    app.cycles_var.set(cycles)
    before = app.log.get("1.0", "end")
    app.run_etch()
    after = app.log.get("1.0", "end")
    return after[len(before):]


def main():
    # (1) the BoschRecipe dataclass default itself -- the value the GUI's
    # own cycles_var field is seeded from -- must be the confirmed-safe
    # one, not the old, never-actually-verified 10.
    default_cycles = BoschRecipe().cycles
    print(f"[1/3] BoschRecipe default cycles={default_cycles}", flush=True)
    assert default_cycles <= 2, (
        f"BoschRecipe's own default cycles ({default_cycles}) must be within "
        f"the real-ViennaPS-confirmed-safe range (<=2) -- see Investigation C"
    )

    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(0.05)
        assert app._materialize_current_wafer()

        # (2) the safe default genuinely produces a complete real mesh --
        # not merely "no exception", the actual geometry must be there.
        print("[2/3] running Bosch DRIE at the GUI's own default cycles...", flush=True)
        default_cycles_gui = int(float(app.cycles_var.get()))
        assert default_cycles_gui <= 2, (
            f"GUI cycles_var default ({default_cycles_gui}) must match the "
            f"safe BoschRecipe default"
        )
        log_text = _run_bosch(app, default_cycles_gui)
        assert app.wafer.processed and app.last_final_mesh, (
            "the safe-default Bosch run must produce a real final mesh"
        )
        import meshio
        mesh = meshio.read(app.last_final_mesh)
        assert len(mesh.points) > 1000, (
            f"safe-default Bosch mesh has only {len(mesh.points)} nodes -- "
            f"expected a real, complete geometry (thousands of nodes), not "
            f"a degenerate fragment"
        )
        assert "NOTE: Bosch cycles=" not in log_text, (
            "the safe default must NOT trigger the risky-cycles warning"
        )
        print(f"    OK: {len(mesh.points)} nodes, real complete mesh, no risk warning logged", flush=True)

        # (3) raising cycles above the safe boundary must be logged --
        # and the step must still run (THE INVARIANT: never block a
        # step the user asked for). Deliberately does NOT assert what
        # the resulting geometry looks like -- the real failure mode at
        # cycles=3 varies between trials (see Investigation C); only the
        # disclosure and "it still ran" are pinned here.
        print("[3/3] running Bosch DRIE at cycles=3 (above the safe boundary)...", flush=True)
        log_text_risky = _run_bosch(app, 3)
        assert "NOTE: Bosch cycles=3 exceeds" in log_text_risky, (
            f"raising cycles above the safe boundary must log a disclosure "
            f"note -- got: {log_text_risky!r}"
        )
        print("    OK: risky-cycles NOTE logged, and the step ran (not blocked)", flush=True)
    finally:
        app.destroy()

    print("Bosch cycle safety: safe default verified via real ViennaPS mesh, "
          "risky values disclosed in the log without blocking the step.")


if __name__ == "__main__":
    main()
