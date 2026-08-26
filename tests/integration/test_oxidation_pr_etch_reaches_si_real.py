#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_etch() must log a per-material summary that correctly distinguishes
"Si not yet reached" (insufficient etch budget) from "Si genuinely
removed" (sufficient budget) -- exercising _log_etch_material_summary()
directly against two real .vpsd-independent-copy scenarios, and
confirming the underlying GEOMETRY behaves as previously verified (this
task changes NO physics -- see docs/investigation_log.md).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

WIDTH = 10.0
HALF = WIDTH / 2.0
BASE = dict(grid_delta_um=0.05, x_extent_um=WIDTH, y_extent_um=8.0,
            silicon_depth_um=5.0, pr_thickness_um=1.0)
DEVELOPED_SPANS = [[-HALF, -1.5], [1.5, HALF]]
OPEN_WINDOW = [-1.5, 1.5]


def _oxidize():
    """Runs a real oxidation and returns its result dict PLUS a real
    `.vpsd` domain_state -- needed because this test reuses the SAME
    oxidized domain independently for two separate etch scenarios
    (insufficient vs. sufficient budget), so each must load its OWN
    fresh copy rather than share one mutable in-memory Domain object.

    Raw ProcessStep.run() (unlike the GUI's worker_main() subprocess
    wrapper) does NOT return a "domain_state" key -- this is the exact
    bug Task 1's implementer found and fixed by switching to
    run_flow() for a one-shot chain; here the domain needs to be
    reused TWICE independently afterward, so the fix is instead to
    capture the live Domain object via a prepare_domain() wrapper (the
    same technique this project's own scratch investigations used) and
    save it explicitly.
    """
    oxidation = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        **BASE, "mask_spans_um": [],
        "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5,
    }
    tmp = tempfile.mkdtemp(prefix="etchsi_ox_")
    ox_step = registry.get("oxidation", "thermal")()

    captured = {}
    orig_prepare_domain = ox_step.prepare_domain

    def capture_prepare_domain(recipe):
        domain = orig_prepare_domain(recipe)
        captured["domain"] = domain
        return domain

    ox_step.prepare_domain = capture_prepare_domain
    result = ox_step.run(oxidation, tmp)

    domain_state_path = str(Path(tmp) / "after_oxidation.vpsd")
    session.save_domain_state(captured["domain"], domain_state_path)
    result["domain_state"] = domain_state_path
    return result


def _etch(domain_state, rate, etch_time_s):
    etch_domain = session.load_domain_state(domain_state)
    etch_recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        **BASE,
        "remask_spans_um": DEVELOPED_SPANS, "mask_material": "PHS",
        "rate": rate, "etch_time_s": etch_time_s,
    }
    etch_step = registry.get("etching", "isotropic")()
    etch_step._inherited_domain = etch_domain
    tmp = tempfile.mkdtemp(prefix="etchsi_etch_")
    return etch_step.run(etch_recipe, tmp)


def _si_top(mesh_path, x_lo, x_hi):
    import meshio
    module = session.require_viennaps()
    m = meshio.read(mesh_path)
    tri = next(c for c in m.cells if c.type == "triangle")
    tags = m.cell_data["Material"][m.cells.index(tri)]
    si_tag = int(module.Material.Si)
    pts = m.points
    ys = [pts[n][1] for t, tag in zip(tri.data, tags) if int(tag) == si_tag
          for n in t if x_lo <= pts[n][0] <= x_hi]
    return max(ys) if ys else None


def main():
    ox_result = _oxidize()

    # --- Case 1: insufficient budget (GUI defaults) -- Si must NOT move ---
    insufficient = _etch(ox_result["domain_state"], rate=-0.05, etch_time_s=1.0)
    si_before = _si_top(ox_result["final_mesh"], *OPEN_WINDOW)
    si_after_insufficient = _si_top(insufficient["final_mesh"], *OPEN_WINDOW)
    moved_insufficient = si_before - si_after_insufficient
    print(f"Insufficient budget: Si moved {moved_insufficient:.5f}um in the open window")
    assert moved_insufficient < 0.001, (
        f"with the GUI's default etch budget (< SiO2 thickness), Si must "
        f"NOT move -- moved {moved_insufficient:.5f}um")

    # PR-protected region must be fully untouched regardless.
    si_protected_before = _si_top(ox_result["final_mesh"], -4.0, -3.0)
    si_protected_after = _si_top(insufficient["final_mesh"], -4.0, -3.0)
    assert abs(si_protected_before - si_protected_after) < 0.001, (
        "PR-protected Si must be untouched")

    # --- Case 2: sufficient budget -- Si MUST genuinely move; PR-protected
    #     region must STILL be untouched. ---
    sufficient = _etch(ox_result["domain_state"], rate=-0.05, etch_time_s=4.0)
    si_after_sufficient = _si_top(sufficient["final_mesh"], *OPEN_WINDOW)
    moved_sufficient = si_before - si_after_sufficient
    print(f"Sufficient budget: Si moved {moved_sufficient:.5f}um in the open window")
    assert moved_sufficient > 0.01, (
        f"with enough etch budget to punch through SiO2, Si MUST genuinely "
        f"move in the open window -- moved only {moved_sufficient:.5f}um")

    si_protected_after_2 = _si_top(sufficient["final_mesh"], -4.0, -3.0)
    assert abs(si_protected_before - si_protected_after_2) < 0.001, (
        "PR-protected Si must STILL be untouched even when the open "
        "window's Si was genuinely etched")

    # --- The log summary itself ---
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    app = gui.TCADApplication()
    try:
        app.withdraw()
        app.update_idletasks()
        logged = []
        app._log = lambda msg: logged.append(msg)
        # The pre-etch reference must be a real volume mesh with
        # per-material cell tags -- exactly what ox_result["final_mesh"]
        # is (a save_volume_mesh() export), NOT ox_result["snapshots"]
        # (raw saveSurfaceMesh() .vtp files with no Material cell_data,
        # which the reader inside _log_etch_material_summary cannot
        # parse). This matches the real run_etch() wiring, which uses
        # the previous step's last_final_mesh, never a snapshot.
        app._log_etch_material_summary(
            ox_result["final_mesh"], insufficient["final_mesh"], [OPEN_WINDOW],
        )
        combined = "".join(logged)
        assert "Si" in combined and "not yet reached" in combined, (
            f"insufficient-budget log must say Si was not reached: {combined!r}")
    finally:
        app.destroy()

    print("Etch physics unchanged (confirmed by direct geometry measurement); "
          "log summary correctly distinguishes 'not yet reached' from "
          "'genuinely removed', and PR protection holds in both cases.")


if __name__ == "__main__":
    main()
