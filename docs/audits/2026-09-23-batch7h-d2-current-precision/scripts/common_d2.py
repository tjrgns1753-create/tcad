"""Batch 7H-D2 shared helpers. DEVSIM 2.11.0 public API only. Read-only reuse of
7H-D1 (meshes_d1, build_fixtures_d1, common_d1 -> 7H-D sg_lib) for the identical
J1 physical setup. Semiconductor equations only from the UNMODIFIED production
setup functions. Precision flags: global set_parameter, as documented in the
DEVSIM manual section 9.3.2 (data/manual/solver.txt)."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
D1S = os.path.join(HERE, "..", "..", "2026-09-23-batch7h-d1-pn-convergence", "scripts")
D1DATA = os.path.join(D1S, "..", "data")
sys.path.insert(0, D1S)
import meshes_d1 as md  # noqa: E402,F401  (7H-D1, read-only)
import build_fixtures_d1 as bf  # noqa: E402,F401  (7H-D1, read-only)
import common_d1 as cd  # noqa: E402  (7H-D1, read-only)

FLAGS = ("extended_model", "extended_equation", "extended_solver")
VARIANTS = {"P0": (False, False, False), "P1": (True, False, False), "P2": (False, True, False),
            "P3": (False, False, True), "P4": (True, True, True)}
CUTS_UM = (-0.25, -0.10, 0.0, 0.10, 0.25)
Q = 1.6e-19


def fixed():
    return json.load(open(os.path.join(DATA, "fixed_d2.json"), encoding="utf-8"))


def read_flags(dv):
    out = {}
    for n in FLAGS:
        try:
            out[n] = dv.get_parameter(name=n)
        except Exception as e:  # noqa: BLE001
            out[n] = "UNSET: " + str(e).strip()[:60]
    return out


def set_precision(dv, P):
    for n, v in zip(FLAGS, VARIANTS[P]):
        dv.set_parameter(name=n, value=v)
    got = read_flags(dv)
    assert all(got[n] is v for n, v in zip(FLAGS, VARIANTS[P])), got
    return got


def fixture(fam, h):
    key = f"{fam}_h{h}"
    for p in (os.path.join(DATA, "fixtures_d2.json"), os.path.join(D1DATA, "fixtures_d1.json")):
        if os.path.exists(p):
            f = json.load(open(p, encoding="utf-8"))
            if key in f:
                return np.array(f[key]["points_um"]), f[key]["triangles"], f[key]["quality"]
    raise KeyError(key)


def set_doping(dv, mirror):
    """J1; mirror=True puts the donors on x < 0 (device mirrored)."""
    x = dv.get_node_model_values(device="d", region=cd.REGION, name="x")
    assert all(v != 0.0 for v in x)
    s = -1.0 if mirror else 1.0
    vals = [cd.ND if s * v > 0 else -cd.NA for v in x]
    dv.node_model(device="d", region=cd.REGION, name="NetDoping", equation="0")
    dv.set_node_values(device="d", region=cd.REGION, name="NetDoping", values=vals)


def solve(dv, kind, tag):
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
    ok = bool(r["converged"]) and last["relative_error"] < s["relative_error"]
    return {"ok": ok, "converged": bool(r["converged"]), "iterations": len(r["iterations"]),
            "final_device_rel": last["relative_error"], "final_device_abs": last["absolute_error"]}
