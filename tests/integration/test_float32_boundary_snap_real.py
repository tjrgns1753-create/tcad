#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 1-1 supplement (task 2): a DevSim node whose coordinate is off
its canonical cell boundary purely from float32 mesh serialization must
be corrected (snapped), not blocked as a geometry mismatch -- while a
node genuinely outside canonical geometry (a real mismatch, however it
arose) must still block exactly as before.

Root cause: DevSim node coordinates are the mesh file's float32 vertex
points times `length_scale_to_cm`
(tcad.device.devsim.mesh_import.import_process_result). A canonical
cell edge at x=2.4um serializes to float32(2.4)=2.400000095367431640625,
so a real DevSim node there reads back as x=2.4000000848900527um -- one
float32 ULP outside the exact [-2.4, 2.4] canonical bound. Reproduced
here on the GUI's own real 4.8um-wide uniform-doped wafer: BEFORE the
snap fix (Tier 1-1-r2), 12 of 150 real DevSim nodes at that edge read
NetDoping=0.0 (a silent known-undoped 0, not a block -- the geometry-
coverage gate that shipped in r2 then blocked the whole measurement
instead, equally wrong: solved_netdoping_zero_nodes=12 pre-r2,
0-nodes-solved-at-all post-r2, evidence in
docs/audits/2026-09-17-tier1-1-r2/{pre,post}_fix_float32_boundary_evidence.log).

Scenario 1 (fixed): width=4.8um, uniform 1e16 donor. Real solve,
every DevSim node's NetDoping equal to the canonical value exactly (0
zero-doped boundary nodes), finite KCL-satisfying terminal current.

Scenario 2 (control): width=5.0um, same doping -- every node already
falls exactly inside its canonical cell (0 nodes need snapping); this
proves the fix changes nothing where there was nothing to fix, and
gives an independent current to check length-scaling against.

Scenario 3 (still blocks): the REAL 4.8um device, but queried against a
canonical WaferStateV2 built for the WRONG width (4.0um instead of
4.8um) -- a genuine ~0.4um geometry mismatch at each edge, far more
than 1 ULP. Must still block with 0 writes / 0 solve, unaffected by the
snap fix.

Real GUI (withdrawn), real ViennaPS 4.6.2, real DevSim -- nothing
mocked. Snap count / max snap distance are computed independently here
(by comparing DevSim's own returned node coordinates against the
canonical cell bounds directly), not read from any production API, so
they cross-check the fix rather than merely echo it.
"""
import json
import math
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

LENGTH_SCALE_TO_CM = 1.0e-4
DEPTH_UM = 1.0
GRID_UM = 0.2
DONOR_CM3 = 1.0e16


def _measure_uniform(app, devsim, width_um):
    """Run a real Uniform-doped MEASURE on a `width_um`-wide wafer.
    Returns (currents, final_node_snapshot, log_delta, solve_calls,
    doping_writes)."""
    app.wafer.width_um = width_um
    app.wafer.silicon_depth_um = DEPTH_UM
    app.grid_var.set(GRID_UM)
    app.meas_voltage_var.set(0.01)
    app.meas_axis_var.set("x")
    app.meas_source_pin.set("max")
    assert app._materialize_current_wafer(), f"materializing the real {width_um}um wafer failed"
    app.doping_kind.set("Uniform")
    app.dope_uniform_region_var.set("Si")
    app.dope_uniform_donor_var.set(DONOR_CM3)
    app.dope_uniform_acceptor_var.set(0.0)
    assert app.run_doping(silent=True)
    canonical_cells = [(c.material_instance_id, c.lifecycle, c.bounds_um) for c in app.wafer_state.cells]

    counts = {"solve": 0, "writes": 0}
    snap = {}
    originals = {n: getattr(devsim, n) for n in ("solve", "node_model", "set_node_values", "delete_device")}

    def solve(*a, **k):
        counts["solve"] += 1
        return originals["solve"](*a, **k)

    def node_model(*a, **k):
        counts["writes"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
        return originals["node_model"](*a, **k)

    def set_node_values(*a, **k):
        counts["writes"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
        return originals["set_node_values"](*a, **k)

    def delete_device(*a, **k):
        for model in ("x", "y", "NetDoping"):
            try:
                snap[model] = list(devsim.get_node_model_values(device=k.get("device"), region="Si", name=model))
            except Exception:
                snap[model] = None
        return originals["delete_device"](*a, **k)

    log_before = app.log.get("1.0", "end-1c")
    devsim.solve, devsim.node_model = solve, node_model
    devsim.set_node_values, devsim.delete_device = set_node_values, delete_device
    try:
        app.run_measurement()
    finally:
        for n, fn in originals.items():
            setattr(devsim, n, fn)
    log = app.log.get("1.0", "end-1c")[len(log_before):]
    currents = [float(m) for m in re.findall(r"I = ([-+0-9.eE]+) A", log)]
    return {
        "width_um": width_um, "canonical_cells": canonical_cells, "currents": currents,
        "final_nodes": snap, "log": log, "solve_calls": counts["solve"], "doping_writes": counts["writes"],
    }


def _snap_evidence(result):
    """Independently cross-check the fix: for every real DevSim node,
    compare its coordinate against the canonical cell bounds directly
    (not via any production snap function) and report how many needed
    correction and by how much, plus whether the SOLVED NetDoping
    matches the canonical value at every node and how many boundary
    (would-have-been-zero) nodes read 0.0."""
    snap = result["final_nodes"]
    assert snap.get("NetDoping"), f"DevSim never held a solved NetDoping for width={result['width_um']}"
    cell_bounds = [c[2] for c in result["canonical_cells"] if c[2] is not None]
    xs = [x / LENGTH_SCALE_TO_CM for x in snap["x"]]
    ys = [y / LENGTH_SCALE_TO_CM for y in snap["y"]]
    solved = snap["NetDoping"]
    mismatched = 0
    zero_nodes = []
    needing_correction = []
    for x, y, n in zip(xs, ys, solved):
        exact = any(b[0] <= x <= b[1] and b[2] <= y <= b[3] for b in cell_bounds)
        if not exact:
            dist = min(
                max(max(b[0] - x, 0.0, x - b[1]), max(b[2] - y, 0.0, y - b[3]))
                for b in cell_bounds
            )
            needing_correction.append((x, y, dist))
        if n != DONOR_CM3:
            mismatched += 1
        if n == 0.0:
            zero_nodes.append((x, y))
    return {
        "nodes": len(xs),
        "mismatched_vs_canonical_donor": mismatched,
        "zero_netdoping_boundary_nodes": len(zero_nodes),
        "zero_node_examples": zero_nodes[:5],
        "nodes_needing_coordinate_correction": len(needing_correction),
        "max_correction_distance_um": max((d for _, _, d in needing_correction), default=0.0),
        "correction_examples": [(round(x, 9), round(y, 9), round(d, 9)) for x, y, d in needing_correction[:5]],
    }


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    from tcad.backends.viennaps import session as viennaps_session
    from tcad.device.devsim import backend as devsim_backend

    if not viennaps_session.is_available() or not devsim_backend.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS or DevSim is not installed")
        return
    devsim = devsim_backend.require_devsim()

    originals = {n: getattr(gui.messagebox, n) for n in ("showinfo", "showerror", "showwarning")}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, **k: None)

    results = {}
    try:
        app.withdraw()
        results["4.8um_fixed"] = _measure_uniform(app, devsim, 4.8)
        app.reset()
        results["5.0um_control"] = _measure_uniform(app, devsim, 5.0)

        # Scenario 3: the REAL 4.8um device's real node coordinates,
        # queried against a canonical state built for the WRONG (4.0um)
        # width -- a genuine ~0.4um mismatch at each edge, far more than
        # 1 ULP, using the SAME real backend end to end.
        from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe

        app.reset()
        app.wafer.width_um = 4.8
        app.wafer.silicon_depth_um = DEPTH_UM
        app.grid_var.set(GRID_UM)
        assert app._materialize_current_wafer()
        wrong_state = initial_wafer_state_from_recipe(
            {"x_extent_um": 4.0, "silicon_depth_um": DEPTH_UM, "grid_delta_um": GRID_UM})
        mismatch_result = build_process_result({"final_mesh": app.last_final_mesh, "snapshots": []})
        imported = import_process_result(
            mismatch_result, mesh_name="snap_mismatch_mesh", device_name="snap_mismatch_dev",
            contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        mismatch_writes = {"count": 0}
        orig_nm, orig_snv, orig_solve = devsim.node_model, devsim.set_node_values, devsim.solve

        def count_nm(*a, **k):
            mismatch_writes["count"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
            return orig_nm(*a, **k)

        def count_snv(*a, **k):
            mismatch_writes["count"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
            return orig_snv(*a, **k)

        solve_calls = {"n": 0}

        def count_solve(*a, **k):
            solve_calls["n"] += 1
            return orig_solve(*a, **k)

        devsim.node_model, devsim.set_node_values, devsim.solve = count_nm, count_snv, count_solve
        mismatch_exc = None
        try:
            apply_doping(imported.device, "Si", wrong_state, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        except UnsupportedDopingState as exc:
            mismatch_exc = exc
        finally:
            devsim.node_model, devsim.set_node_values, devsim.solve = orig_nm, orig_snv, orig_solve
            devsim.delete_device(device=imported.device)
            devsim.delete_mesh(mesh=imported.mesh)
    finally:
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
        app.destroy()

    evidence = {k: _snap_evidence(v) for k, v in results.items()}
    printable = {k: {kk: vv for kk, vv in v.items() if kk not in ("final_nodes", "log")}
                for k, v in results.items()}
    print("RESULTS " + json.dumps(printable, default=str))
    print("EVIDENCE " + json.dumps(evidence, default=str))
    print("MISMATCH_SCENARIO " + json.dumps({
        "blocked": mismatch_exc is not None, "writes": mismatch_writes["count"],
        "solve_calls": solve_calls["n"],
        "message_head": str(mismatch_exc)[:300] if mismatch_exc else None,
    }, default=str))

    # ---- Scenario 1: fixed ----
    r48, e48 = results["4.8um_fixed"], evidence["4.8um_fixed"]
    assert r48["solve_calls"] >= 1, f"4.8um: no real solve ran ({r48['solve_calls']})"
    assert r48["doping_writes"] >= 1, "4.8um: doping was never written"
    assert e48["nodes_needing_coordinate_correction"] > 0, (
        "4.8um: fixture is broken -- this recipe must reproduce real float32-boundary nodes "
        "(it did in every prior run of this exact recipe)")
    assert e48["max_correction_distance_um"] > 0.0, e48
    print(f"[4.8um] {e48['nodes_needing_coordinate_correction']} of {e48['nodes']} nodes needed float32 "
          f"round-trip correction, max distance {e48['max_correction_distance_um']:.3e} um")
    assert e48["mismatched_vs_canonical_donor"] == 0, (
        f"4.8um: {e48['mismatched_vs_canonical_donor']} node(s) have solved NetDoping != the canonical "
        f"{DONOR_CM3:.3e}: {e48}")
    assert e48["zero_netdoping_boundary_nodes"] == 0, (
        f"4.8um: {e48['zero_netdoping_boundary_nodes']} node(s) still read NetDoping=0.0 at the boundary "
        f"(the exact pre-fix symptom): {e48['zero_node_examples']}")
    currents48 = r48["currents"][:2]
    assert len(currents48) == 2 and all(math.isfinite(i) for i in currents48), r48["currents"]
    assert abs(currents48[0] + currents48[1]) <= 1e-4 * abs(currents48[0]), (
        f"4.8um: terminal currents not equal and opposite (KCL): {currents48}")
    print(f"[4.8um] terminal currents: {currents48}")

    # ---- Scenario 2: control ----
    r50, e50 = results["5.0um_control"], evidence["5.0um_control"]
    assert r50["solve_calls"] >= 1 and r50["doping_writes"] >= 1
    assert e50["nodes_needing_coordinate_correction"] == 0, (
        f"5.0um control: expected 0 nodes needing correction, got "
        f"{e50['nodes_needing_coordinate_correction']} -- the control fixture itself is off")
    assert e50["mismatched_vs_canonical_donor"] == 0 and e50["zero_netdoping_boundary_nodes"] == 0
    currents50 = r50["currents"][:2]
    assert len(currents50) == 2 and all(math.isfinite(i) for i in currents50), r50["currents"]
    print(f"[5.0um control] 0 nodes needed correction (already exact); terminal currents: {currents50}")

    # ---- Length-scaling consistency between 4.8um and 5.0um ----
    # Same uniform doping, same depth, same grid; only the contact
    # separation (~ width) differs -- an Ohmic resistor at fixed bias,
    # so current should scale as I ~ 1/width (R = rho*L/A, L=width).
    # This IS a real physics check, not a coarse smoke test: measured
    # in development the observed ratio was ~1.8% off the predicted
    # one, so REL_TOL below (10%) is a genuine, named bound on a real
    # Ohm's-law prediction -- wide enough to absorb this project's own
    # non-ideal contact effects (see mosfet_sweep.py's own tolerance
    # notes), but tight enough that the pre-fix failure mode (~2e-7 A,
    # a ~600x-1000x error from a spuriously near-zero-doped contact
    # node) would still fail it outright.
    REL_TOL = 0.10
    i48, i50 = abs(currents48[0]), abs(currents50[0])
    predicted_ratio = 5.0 / 4.8
    observed_ratio = i48 / i50
    rel_error = abs(observed_ratio - predicted_ratio) / predicted_ratio
    print(f"[scaling] |I(4.8)|={i48:.6e} A, |I(5.0)|={i50:.6e} A, observed ratio={observed_ratio:.4f}, "
          f"predicted (5.0/4.8, fixed-cross-section Ohmic scaling)={predicted_ratio:.4f}, "
          f"relative error={rel_error:.4%} (tolerance {REL_TOL:.0%})")
    assert rel_error <= REL_TOL, (
        f"4.8um current is not consistent with 5.0um by simple length scaling: "
        f"observed ratio {observed_ratio:.4f} vs predicted {predicted_ratio:.4f}, "
        f"relative error {rel_error:.4%} exceeds {REL_TOL:.0%}")

    # ---- Scenario 3: a real mismatch (not 1-ULP) still blocks ----
    assert mismatch_exc is not None, "a genuine ~0.4um geometry mismatch must still raise UnsupportedDopingState"
    assert mismatch_writes["count"] == 0 and solve_calls["n"] == 0, (
        f"mismatch scenario: writes={mismatch_writes['count']} solve_calls={solve_calls['n']}")
    assert "UNSUPPORTED_BY_MODEL" in str(mismatch_exc) and "First blocked node" in str(mismatch_exc)

    print("\nPASS: real float32 mesh-serialization boundary nodes are snapped and solved correctly "
          "(0 mismatches vs canonical, 0 zero-doped boundary nodes, finite KCL current, scaling "
          "consistent with the 5.0um control); a genuine ~0.4um geometry mismatch on the same real "
          "device still blocks with 0 writes / 0 solve.")


if __name__ == "__main__":
    main()
