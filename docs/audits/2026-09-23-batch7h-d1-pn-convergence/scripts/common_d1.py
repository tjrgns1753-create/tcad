"""Batch 7H-D1 shared helpers (DEVSIM 2.11.0 public API only).
Read-only reuse: 7H-D sg_lib (build_2d, apply_variant D1, signed_geometry,
currents, 7H-B formulas as fm) and 7H-D build_fixtures_7hd.quality. Semiconductor
equations come only from the UNMODIFIED production setup functions."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
S7HD = os.path.join(HERE, "..", "..", "2026-09-23-batch7h-d-sg-pn-mesh-validity", "scripts")
sys.path.insert(0, S7HD)
import sg_lib as _sl  # noqa: E402  (7H-D, read-only)
from build_fixtures_7hd import quality  # noqa: E402,F401  (7H-D, read-only)

fm, UM, REGION = _sl.fm, _sl.UM, _sl.REGION
ECE, HCE, PE = _sl.ECE, _sl.HCE, _sl.PE
build_2d, apply_variant, signed_geometry, currents = _sl.build_2d, _sl.apply_variant, _sl.signed_geometry, _sl.currents
NA = ND = 1e17


def fixed():
    return json.load(open(os.path.join(DATA, "fixed_d1.json"), encoding="utf-8"))


def build_1d(dv, xs_um, dev="d"):
    m = "m_" + dev
    dv.create_1d_mesh(mesh=m)
    for i, x in enumerate(xs_um):
        tag = "L" if i == 0 else ("R" if i == len(xs_um) - 1 else None)
        h = (xs_um[1] - xs_um[0]) if i == 0 else (x - xs_um[i - 1])
        if tag:
            dv.add_1d_mesh_line(mesh=m, pos=x * UM, ps=h * UM, tag=tag)
        else:
            dv.add_1d_mesh_line(mesh=m, pos=x * UM, ps=h * UM)
    dv.add_1d_contact(mesh=m, name="left", tag="L", material="metal")
    dv.add_1d_contact(mesh=m, name="right", tag="R", material="metal")
    dv.add_1d_region(mesh=m, material="Si", region=REGION, tag1="L", tag2="R")
    dv.finalize_mesh(mesh=m)
    dv.create_device(mesh=m, device=dev)


def set_doping(dv, rule, dev="d"):
    """J1: x < 0 -> -NA, x > 0 -> +ND (a node at x == 0 is an error);
    J0: additionally x == 0 -> 0 (the 7H-D rule, diagnostic only)."""
    x = dv.get_node_model_values(device=dev, region=REGION, name="x")
    if rule == "J1":
        assert all(v != 0.0 for v in x), "J1 mesh has a node on the junction"
    vals = [ND if v > 0 else (-NA if v < 0 else 0.0) for v in x]
    dv.node_model(device=dev, region=REGION, name="NetDoping", equation="0")
    dv.set_node_values(device=dev, region=REGION, name="NetDoping", values=vals)


def solve(dv, kind, tag):
    """Registered stopping rule (fixed_d1.json). A convergence failure is a result."""
    s = fixed()["solver"][kind]
    print(f"### SOLVE-BEGIN {tag}", flush=True)
    try:
        r = dv.solve(type="dc", absolute_error=s["absolute_error"], relative_error=s["relative_error"],
                     maximum_iterations=s["maximum_iterations"], info=True)
        err = None
    except Exception as e:  # noqa: BLE001
        r, err = None, repr(e)[:300]
    print(f"### SOLVE-END {tag}", flush=True)
    if not r:
        return {"ok": False, "error": err}
    last = r["iterations"][-1]["devices"][0]
    eqs = {e["name"]: {"abs": e["absolute_error"], "rel": e["relative_error"]}
           for reg in last["regions"] for e in reg["equations"]}
    return {"ok": bool(r["converged"]), "converged": bool(r["converged"]), "iterations": len(r["iterations"]),
            "final_device_rel": last["relative_error"], "final_device_abs": last["absolute_error"],
            "final_equations": eqs, "rel_threshold": s["relative_error"],
            "rel_below_threshold": last["relative_error"] < s["relative_error"], "error": err}
