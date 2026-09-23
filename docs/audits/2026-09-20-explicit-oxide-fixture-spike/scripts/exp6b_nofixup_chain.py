# -*- coding: utf-8 -*-
"""EXP 6b -- what happens when a supported step is chained onto the wrapped
LOCOS explicit stack WITHOUT _make_locos_domain_chainable(). Isolated in its
own process (argv[1] = deposition | etch) because a native crash must not
take the other experiments with it. Return code + native stderr are the
evidence."""
import sys
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.etching  # noqa: F401
import tcad.process.deposition  # noqa: F401
from tcad.process import registry
from tcad.process.oxidation.locos import LocosOxidation
from tcad.backends.viennaps.io import save_locos_volume_mesh

which = sys.argv[1]
module = C.module_and_counters()
work = C.scratch("exp6b_")
recipe = {"grid_delta_um": 0.05, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT,
          "mask_left_um": 0.5, "mask_right_um": 1.5, "pr_thickness_um": 0.3, "mask_material": "Mask",
          "pad_oxide_thickness_um": 0.10, "silicon_depth_um": C.DEPTH}
step = LocosOxidation()
geometry, mats, flags = step._build_locos_geometry(recipe, module)
m0 = C.measure(module, save_locos_volume_mesh(geometry, mats, flags, str(Path(work) / "before"),
                                              floor_depth_um=C.DEPTH))
print("before:", list(m0["materials"]), {k: v["area"] for k, v in m0["materials"].items()}, flush=True)
if which == "deposition":
    cat, model, r = "deposition", "isotropic", {"rate": 0.1, "deposition_time_s": 1.0, "material": "Si3N4",
                                                "silicon_depth_um": C.DEPTH}
else:
    cat, model, r = "etching", "isotropic", {"material_rates": {"SiO2": -0.1, "Si": 0.0, "Mask": 0.0},
                                             "etch_time_s": 0.5, "silicon_depth_um": C.DEPTH}
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    res = registry.get(cat, model)(inherited_domain=geometry).run(r, str(Path(work) / "after"))
m1 = C.measure(module, res["final_mesh"])
print("after:", list(m1["materials"]), {k: v["area"] for k, v in m1["materials"].items()}, flush=True)
C.save_json(f"exp6b_nofixup_{which}.json", {
    "materials_before": list(m0["materials"]), "areas_before": {k: v["area"] for k, v in m0["materials"].items()},
    "materials_after": list(m1["materials"]), "areas_after": {k: v["area"] for k, v in m1["materials"].items()}})
print("EXP6b DONE")
