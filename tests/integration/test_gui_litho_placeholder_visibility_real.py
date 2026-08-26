#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The litho placeholder (Mask Alignment / Exposure) must not disappear
just because an EARLIER, unrelated real process step already ran --
see docs/investigation_log.md, "Mask Alignment/Exposure placeholder
disappears once any real mesh exists". Drives the real TCADApplication
(window withdrawn) through a real Oxidation, then Litho, checking the
CANVAS TEXT the litho visuals actually draw (the same technique
tests/unit/test_gui_litho_lifecycle_mock.py already uses for the
resist-spans state, extended here to the render output).

Lithography UI state display and physical mesh rendering are
independent (see redraw()'s own comment on `real_mesh_available`):
a real mesh, once it exists, must ALWAYS render (materials, doping
overlay) regardless of litho state, and litho visuals (PR film / mask
box / UV rays) draw on top of whatever real surface is currently
there. Neither one hides the other -- see docs/investigation_log.md,
"PR COAT after real geometry hid the mesh" for the regression this
fixes (a doping+oxidation session losing its SiO2/doping from the
canvas the moment PR COAT was clicked, even though nothing was lost
from the underlying mesh/domain state).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _canvas_texts(canvas):
    """Every text string currently drawn on the canvas -- lets a test
    assert on what the USER WOULD SEE, not just an internal flag."""
    texts = []
    for item_id in canvas.find_all():
        if canvas.type(item_id) == "text":
            texts.append(canvas.itemcget(item_id, "text"))
    return texts


def main():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        print("SKIPPED: ViennaPS is not installed")
        return

    # PHS must have its own color, distinct from Mask's and from the
    # renderer's generic fallback -- checked once, statically, before
    # any process runs (see docs/investigation_log.md, "PR color falls
    # back to gray once a real mesh renders it").
    phs_color = gui.TCADApplication._MATERIAL_COLORS.get("PHS")
    assert phs_color is not None, "PHS must have its own _MATERIAL_COLORS entry"
    assert phs_color != gui.TCADApplication._MATERIAL_COLORS.get("Mask"), (
        "PR (PHS) must not render in Mask's color")
    assert phs_color != "#b0b0b0", (
        "PR (PHS) must not fall back to the renderer's generic gray")

    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"
        assert app.wafer.processed is True

        mesh_before_litho = app.last_final_mesh
        domain_before_litho = app.last_domain_state

        # Litho actions AFTER a real mesh already exists -- this is
        # exactly the reported scenario (Oxidation, then PR Coat /
        # Mask Alignment / Exposure). None of these touch the real
        # mesh/domain state -- they are pure state transitions.
        app.process_pr_coat()
        assert app.last_final_mesh == mesh_before_litho, (
            "PR COAT must not change the real mesh")
        assert app.last_domain_state == domain_before_litho, (
            "PR COAT must not change the real domain state")

        app.process_mask_alignment()

        # process_mask_alignment() already called its own redraw();
        # confirm the mask placeholder ACTUALLY drew, matching the
        # user's literal complaint ("Mask Alignment를 하면 마스크가
        # 화면에 나타나야 하는데 나타나지 않음") -- AND that the real
        # mesh is still on screen at the same time (the regression this
        # fixes: real geometry must not be hidden just because litho
        # state changed).
        texts = _canvas_texts(app.canvas)
        assert any("MASK OPENING" in t for t in texts), (
            f"Mask Alignment after an earlier real process must draw the "
            f"mask on screen, got canvas texts: {texts}")
        assert not any(t == "Si substrate" for t in texts), (
            f"Mask Alignment after an earlier real process must NOT fall "
            f"back to the flat placeholder -- the real mesh must still "
            f"render, got canvas texts: {texts}")

        app.process_exposure()

        # Same check for Exposure: the user must be able to see WHICH
        # area was exposed ("Exposure를 하면... 노광된 부분이 시각적으로
        # 구분되어야 함") -- again with the real mesh still showing.
        texts = _canvas_texts(app.canvas)
        assert any("UV EXPOSURE" in t for t in texts), (
            f"Exposure must show which area was exposed, got: {texts}")
        assert any("EXPOSED PR" in t for t in texts), (
            f"Exposure must highlight the exposed PR region distinctly, "
            f"got: {texts}")
        assert not any(t == "Si substrate" for t in texts), (
            f"Exposure must NOT fall back to the flat placeholder, "
            f"got: {texts}")

        app.process_develop()
        assert app.last_final_mesh == mesh_before_litho, (
            "PR COAT/ALIGN/EXPOSE/DEVELOP together must still not have "
            "touched the real mesh -- litho is state-only until a real "
            "process step runs")

        # A REAL step (Etch) produces a genuinely new mesh. run_etch()
        # has no explicit `return True` on its success path (every
        # `return` in it is an early-failure bare `return`, pre-existing
        # and out of this fix's scope) -- check the real signal instead:
        # last_final_mesh actually changed.
        app.etch_model.set("Isotropic etch")
        app.grid_var.set(0.2)
        app.isotropic_rate_var.set(0.05)
        app.etch_time_var.set(1.0)
        app.run_etch()
        assert app.last_final_mesh != mesh_before_litho, (
            "a real Etch must produce a new real mesh reflecting the "
            "developed litho pattern")

        # PR STRIP must not regress into the SAME bug this task fixes:
        # its own real geometry mutation (_strip_resist_from_geometry(),
        # verified separately by test_pr_strip_real.py) must leave the
        # mesh visibly up to date afterward, not hidden behind a stale
        # placeholder.
        app.process_pr_coat()
        assert app.wafer.pr_present
        mesh_before_strip = app.last_final_mesh
        app.process_pr_strip()
        texts = _canvas_texts(app.canvas)
        assert not any(t == "Si substrate" for t in texts), (
            f"after a real PR STRIP, the real (stripped) mesh must "
            f"render normally, not fall back to the placeholder, "
            f"got: {texts}")
        assert app.last_final_mesh != mesh_before_strip, (
            "PR STRIP must have produced a genuinely new mesh (the "
            "stripped one), not left the pre-strip mesh in place")

        print("Litho placeholder: PR Coat/Align/Expose/Develop draw "
              "their visuals on top of the real mesh, which stays "
              "visible throughout (never hidden by a litho UI state "
              "change); a real process step still produces a genuinely "
              "new mesh; PR STRIP's real mesh renders normally "
              "afterward.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
