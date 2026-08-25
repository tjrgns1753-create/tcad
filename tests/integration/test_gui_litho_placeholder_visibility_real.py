#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The litho placeholder (Mask Alignment / Exposure) must not disappear
just because an EARLIER, unrelated real process step already ran --
see docs/investigation_log.md, "Mask Alignment/Exposure placeholder
disappears once any real mesh exists". Drives the real TCADApplication
(window withdrawn) through a real Oxidation, then Litho, checking the
STATE FLAG that drives the rendering decision (the same technique
tests/unit/test_gui_litho_lifecycle_mock.py already uses for the
resist-spans state, extended here to the render-gate state).
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

        assert app._litho_pending_since_last_mesh is False, (
            "a fresh wafer must not start with litho marked pending")

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"
        assert app._litho_pending_since_last_mesh is False
        assert app.wafer.processed is True

        # Litho actions AFTER a real mesh already exists -- this is
        # exactly the reported scenario (Oxidation, then PR Coat /
        # Mask Alignment / Exposure).
        app.process_pr_coat()
        assert app._litho_pending_since_last_mesh is True, (
            "PR COAT after an earlier real mesh must mark litho pending "
            "so the placeholder draws instead of the stale real mesh")

        app.process_mask_alignment()
        assert app._litho_pending_since_last_mesh is True

        # The gate itself: real_mesh_available must now be False even
        # though wafer.processed is True and last_final_mesh exists.
        real_mesh_available = bool(
            app.wafer.processed
            and app.last_final_mesh
            and Path(app.last_final_mesh).exists()
            and not app._litho_pending_since_last_mesh
        )
        assert real_mesh_available is False, (
            "real_mesh_available must be False while litho is pending, "
            "so the placeholder actually draws")

        # Not just the flag -- process_mask_alignment() already called
        # its own redraw(); confirm the mask placeholder ACTUALLY drew,
        # matching the user's literal complaint ("Mask Alignment를 하면
        # 마스크가 화면에 나타나야 하는데 나타나지 않음").
        texts = _canvas_texts(app.canvas)
        assert any("MASK OPENING" in t for t in texts), (
            f"Mask Alignment after an earlier real process must draw the "
            f"mask on screen, got canvas texts: {texts}")

        app.process_exposure()
        assert app._litho_pending_since_last_mesh is True

        # Same check for Exposure: the user must be able to see WHICH
        # area was exposed ("Exposure를 하면... 노광된 부분이 시각적으로
        # 구분되어야 함").
        texts = _canvas_texts(app.canvas)
        assert any("UV EXPOSURE" in t for t in texts), (
            f"Exposure must show which area was exposed, got: {texts}")
        assert any("EXPOSED PR" in t for t in texts), (
            f"Exposure must highlight the exposed PR region distinctly, "
            f"got: {texts}")

        app.process_develop()
        assert app._litho_pending_since_last_mesh is True

        # A REAL step (Etch) consumes the pending litho state.
        app.etch_model.set("Isotropic etch")
        app.grid_var.set(0.2)
        app.isotropic_rate_var.set(0.05)
        app.etch_time_var.set(1.0)
        ok = app.run_etch()
        assert app._litho_pending_since_last_mesh is False, (
            "a real Etch must clear the pending flag -- it consumed "
            "the current litho state into a new real mesh")

        # PR STRIP must not regress into the SAME bug this task fixes:
        # it is deliberately excluded from ever setting pending=True
        # (see Step 2's own note), so its own real geometry mutation
        # (_strip_resist_from_geometry(), verified separately by
        # test_pr_strip_real.py) must still leave the mesh visibly
        # up to date afterward, not hidden behind a stale placeholder.
        app.process_pr_coat()
        assert app.wafer.pr_present
        mesh_before_strip = app.last_final_mesh
        app.process_pr_strip()
        assert app._litho_pending_since_last_mesh is False, (
            "PR STRIP must never leave litho marked pending -- its own "
            "real geometry mutation already produces an up-to-date mesh "
            "(or, if no real mesh existed, there is nothing to be "
            "pending against)")
        real_mesh_available_after_strip = bool(
            app.wafer.processed
            and app.last_final_mesh
            and Path(app.last_final_mesh).exists()
            and not app._litho_pending_since_last_mesh
        )
        assert real_mesh_available_after_strip is True, (
            "after a real PR STRIP, the real (stripped) mesh must render "
            "normally, not fall back to the placeholder")
        assert app.last_final_mesh != mesh_before_strip, (
            "PR STRIP must have produced a genuinely new mesh (the "
            "stripped one), not left the pre-strip mesh in place")

        print("Litho placeholder gate: pending after PR Coat/Align/"
              "Expose/Develop even with an earlier real mesh present; "
              "cleared by the next real process step; PR STRIP never "
              "incorrectly marked pending, real mesh renders after it.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
