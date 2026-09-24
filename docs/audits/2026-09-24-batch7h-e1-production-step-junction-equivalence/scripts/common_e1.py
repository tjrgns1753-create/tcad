"""Batch 7H-E1 shared constants and helpers (no ViennaPS/DEVSIM import at module level).

GUI default arguments reproduced by the production build (source lines in PLAN.md section 1):
Wafer width 10 um, silicon depth 5 um (tcad/core/models.py:22-23), grid 0.05 um (:100), y extent 8 um and
mask height max(pr_thickness 1.0, 0.1) (tcad_2d_stagewise.py materialize branch), step junction Si / x / 0 um /
1e18 / 1e18 ACTIVE (:4823-4837), barrier threshold 0.0 (:4938-4940), measurement: source pin max, 0.3 V (:5595-5624),
length scale 1e-4, refine near the junction position on the junction axis (:5779-5786)."""
import hashlib
import json
import math
import os
import re

GUI = {
    "grid_delta_um": 0.05, "x_extent_um": 10.0, "y_extent_um": 8.0, "silicon_depth_um": 5.0,
    "pr_thickness_um": 1.0, "mask_spans_um": [],
    "doping": {"region": "Si", "junction_axis": "x", "junction_position_um": 0.0,
               "donor_conc_cm3": 1.0e18, "acceptor_conc_cm3": 1.0e18, "chemical_state": "ACTIVE"},
    "barrier": {"barrier_material": "SiO2", "axis": "x", "min_barrier_thickness_um": 0.0},
    "import": {"mesh_name": "gui_measure_mesh", "device_name": "gui_measure_device", "contact_regions": ["Si"],
               "contact_axis": "x", "length_scale_to_cm": 1.0e-4, "refine_near_um": 0.0, "refine_axis": "x"},
    "measure": {"source_pin": "max", "voltage": 0.3, "gnd_voltage": 0.0},
}
REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    return sha(open(p, "rb").read())


def finite_or_status(v):
    """Strict-JSON value: finite float as is; non-finite -> {'value': None, 'status': 'NONFINITE_<kind>'}."""
    if isinstance(v, float) and not math.isfinite(v):
        return {"value": None, "status": "NONFINITE_" + ("NAN" if math.isnan(v) else ("POS_INF" if v > 0 else "NEG_INF"))}
    return v


def strict(o):
    if isinstance(o, dict):
        return {k: strict(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [strict(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(o, float):
        return finite_or_status(o)
    return o


def dump_strict(obj, path):
    text = json.dumps(strict(obj), indent=1, allow_nan=False, default=str)
    text = USER_PATH.sub("<USERPROFILE>", text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    load_strict(path)


def load_strict(path):
    def bad(c):
        raise ValueError(f"non-strict JSON constant {c} in {os.path.basename(path)}")
    return json.loads(open(path, encoding="utf-8").read(), parse_constant=bad)
