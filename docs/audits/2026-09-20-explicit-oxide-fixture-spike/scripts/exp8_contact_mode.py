# -*- coding: utf-8 -*-
"""EXP 8 -- contactMode safety-regression feasibility WITHOUT running the
unsupported solver. Oxidation models here are spies around the real object;
Process.apply is counted and must stay 0."""
import re
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.oxidation  # noqa: F401
from tcad.process import registry
import viennals as vls

module = C.module_and_counters()
work = C.scratch("exp8_")
out = {}

# (a) positive-time production gate: model construction count
for model, mask in (("locos", True), ("thermal", False)):
    C.reset_counts()
    r = {"grid_delta_um": 0.05, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT, "oxidant": "Dry",
         "temperature_c": 1000.0, "time_hours": 0.5, "silicon_depth_um": C.DEPTH}
    if mask:
        r.update({"mask_left_um": 0.5, "mask_right_um": 1.5, "pr_thickness_um": 0.3, "mask_material": "Mask"})
    res = registry.get("oxidation", model)().run(r, str(Path(work) / f"gate_{model}"))
    out[f"a_positive_time_gate_{model}"] = {"counts": C.snapshot_counts(),
                                            "state_transition": res.get("state_transition")}

# (b) the only currently reachable configuration segment: fresh zero-duration LOCOS
C.reset_counts()
r = {"grid_delta_um": 0.05, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT, "oxidant": "Dry",
     "temperature_c": 1000.0, "time_hours": 0.0, "silicon_depth_um": C.DEPTH,
     "mask_left_um": 0.5, "mask_right_um": 1.5, "pr_thickness_um": 0.3, "mask_material": "Mask",
     "pad_oxide_thickness_um": 0.10}
res = registry.get("oxidation", "locos")().run(r, str(Path(work) / "cfg_zero"))
spy = C.SPY_OBJECTS[0]
out["b_fresh_zero_duration_locos"] = {
    "counts": C.snapshot_counts(),
    "state_transition": res.get("state_transition"),
    "mask_params_contactMode_seen": spy.mask_params_seen,
    "calls": [[c[0], repr(c[1])] for c in spy.calls],
}

# (c) default of OxidationMaskParameters (so that '2' is a real override)
out["c_default_OxidationMaskParameters_contactMode"] = int(vls.OxidationMaskParameters().contactMode)

# (d) static scan of production sources for any contactMode line
scan = {}
for f in ("tcad/process/oxidation/locos.py", "tcad/process/oxidation/thermal.py"):
    src = (C.REPO / f).read_text(encoding="utf-8")
    scan[f] = [f"{i}: {ln.strip()}" for i, ln in enumerate(src.splitlines(), 1)
               if re.search(r"contactMode", ln)]
out["d_static_contactMode_lines"] = scan

# (e) negative control: does the spy actually detect a wrong value?
C.reset_counts()
spy_ox = module.Oxidation()
spy_ox.setMaskParameters(vls.OxidationMaskParameters())      # library default, not 2
out["e_negative_control_spy_sees_default"] = spy_ox.mask_params_seen
out["scratch"] = work
C.save_json("exp8_contact_mode.json", out)
for k, v in out.items():
    print(k, "=>", v)
print("EXP8 DONE")
