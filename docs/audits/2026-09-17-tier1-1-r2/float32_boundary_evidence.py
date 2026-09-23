"""Evidence (not a regression test): a real GUI Uniform measurement on a
4.8 x 1.0 um wafer, grid 0.2 um (width override: argv[1], e.g. 4.6 --
its +-2.3 um edges quantize INWARD, so it is the supported control).

The canonical Si cell is x in [-2.4, 2.4], y in [-1.0, 0.0] (recipe
bounds). DevSim node coordinates are the mesh's float32 points scaled
to cm, so the x = +-2.4 um edge nodes read back as +-2.4000001 um --
outside the cell by one float32 unit. Before the geometry-coverage gate,
WaferStateV2.net_doping_at() found no owning cell there and returned a
known-undoped 0.0, which apply_doping() wrote into the contact nodes of
a uniformly 1e16-doped device and solved. After it, the same nodes have
zero owning cells and the measurement is blocked.

Prints one EVIDENCE json line: solve calls, doping writes, currents,
blocked message, and -- when a solve ran -- how many solved NetDoping
values are 0.0 and where. Real GUI (withdrawn), ViennaPS, DevSim.
"""
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import tcad_2d_stagewise as gui  # noqa: E402
from tcad.device.devsim import backend  # noqa: E402

SCALE = 1.0e-4
WIDTH_UM = float(sys.argv[1]) if len(sys.argv) > 1 else 4.8


def main():
    devsim = backend.require_devsim()
    app = gui.TCADApplication()
    app.withdraw()
    counts = {"solve": 0, "doping_writes": 0}
    snap = {}
    originals = {n: getattr(devsim, n) for n in ("solve", "node_model", "set_node_values", "delete_device")}

    def solve(*a, **k):
        counts["solve"] += 1
        return originals["solve"](*a, **k)

    def node_model(*a, **k):
        counts["doping_writes"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
        return originals["node_model"](*a, **k)

    def set_node_values(*a, **k):
        counts["doping_writes"] += k.get("name") in ("Donors", "Acceptors", "NetDoping")
        return originals["set_node_values"](*a, **k)

    def delete_device(*a, **k):
        for model in ("x", "y", "NetDoping"):
            try:
                snap[model] = list(devsim.get_node_model_values(device=k.get("device"), region="Si", name=model))
            except Exception:
                snap[model] = None
        return originals["delete_device"](*a, **k)

    try:
        app.wafer.width_um = WIDTH_UM
        app.wafer.silicon_depth_um = 1.0
        app.grid_var.set(0.2)
        app.meas_voltage_var.set(0.01)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        assert app._materialize_current_wafer()
        app.doping_kind.set("Uniform")
        app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16)
        app.dope_uniform_acceptor_var.set(0.0)
        assert app.run_doping(silent=True)
        cells = [(c.material_instance_id, c.lifecycle, c.bounds_um) for c in app.wafer_state.cells]
        log_before = app.log.get("1.0", "end-1c")
        devsim.solve, devsim.node_model = solve, node_model
        devsim.set_node_values, devsim.delete_device = set_node_values, delete_device
        try:
            app.run_measurement()
        finally:
            for n, fn in originals.items():
                setattr(devsim, n, fn)
        log = app.log.get("1.0", "end-1c")[len(log_before):]
    finally:
        app.destroy()

    evidence = {
        "width_um": WIDTH_UM,
        "canonical_cells": cells,
        "solve_calls": counts["solve"],
        "doping_node_model_writes": counts["doping_writes"],
        "currents_in_log": re.findall(r"I = ([-+0-9.eE]+) A", log),
        "blocked_message": next((ln for ln in log.splitlines() if "UNSUPPORTED_BY_MODEL" in ln), None),
        "first_blocked_node_line": next((ln for ln in log.splitlines() if ln.startswith("First blocked node")), None),
        "instances_line": next((ln for ln in log.splitlines() if ln.startswith("Canonical material instance")), None),
        "blocked_because_line": next((ln for ln in log.splitlines() if ln.startswith("Blocked because")), None),
    }
    if snap.get("NetDoping") is not None:
        xs = [x / SCALE for x in snap["x"]]
        zero = [(x, y / SCALE) for x, y, n in zip(xs, snap["y"], snap["NetDoping"]) if n == 0.0]
        evidence.update({
            "solved_nodes": len(xs),
            "node_x_range_um": [min(xs), max(xs)],
            "nodes_outside_canonical_cell": sum(1 for x in xs if not -WIDTH_UM / 2 <= x <= WIDTH_UM / 2),
            "solved_netdoping_zero_nodes": len(zero),
            "zero_node_x_values_um": sorted({x for x, _ in zero}),
            "solved_netdoping_values": sorted(set(snap["NetDoping"])),
        })
    print("EVIDENCE " + json.dumps(evidence, default=str))


if __name__ == "__main__":
    main()
