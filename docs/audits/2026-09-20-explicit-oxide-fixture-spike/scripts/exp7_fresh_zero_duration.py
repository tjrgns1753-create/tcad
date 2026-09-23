# -*- coding: utf-8 -*-
"""EXP 7 -- fresh zero-duration oxidation vs inherited zero-duration identity
vs positive-time gate, for LocosOxidation and ThermalOxidation. Counters are
patched into the viennaps module the production code fetches, so
Oxidation constructions / setInitialOxideThickness / Process.apply are COUNTED."""
import warnings
from pathlib import Path

from common import *  # noqa: F401,F403
import common as C
import tcad.process.oxidation  # noqa: F401
from tcad.process import registry

module = C.module_and_counters()
work = C.scratch("exp7_")
out = {"cases": []}


def base_recipe(g, time_h, mask=True, pad=None):
    r = {"grid_delta_um": g, "x_extent_um": C.X_EXTENT, "y_extent_um": C.Y_EXTENT,
         "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": time_h, "silicon_depth_um": C.DEPTH}
    if mask:
        r.update({"mask_left_um": 0.5, "mask_right_um": 1.5, "pr_thickness_um": 0.3, "mask_material": "Mask"})
    if pad is not None:
        r["pad_oxide_thickness_um"] = pad
    return r


def run_case(label, model, recipe, inherited=None):
    C.reset_counts()
    step = registry.get("oxidation", model)(inherited_domain=inherited)
    err = None
    res = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = step.run(dict(recipe), str(Path(work) / label))
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    rec = {"label": label, "model": model, "grid": recipe["grid_delta_um"], "time_hours": recipe["time_hours"],
           "inherited": inherited is not None, "requested_pad_um": recipe.get("pad_oxide_thickness_um"),
           "counts": C.snapshot_counts(), "error": err,
           "oxidation_spy_calls": [[c[0], repr(c[1])] for s in C.SPY_OBJECTS for c in s.calls]}
    if res is not None:
        rec["state_transition"] = res.get("state_transition")
        rec["physics_status_reason"] = (res.get("physics_status") or {}).get("reason_code")
        m = C.measure(module, res["final_mesh"])
        rec["materials"] = list(m["materials"])
        rec["areas"] = {k: v["area"] for k, v in m["materials"].items()}
        cols = C.col_at(module, res["final_mesh"], [0.0, 0.8])
        rec["columns"] = cols
        ox = cols["0.0"].get("SiO2")
        rec["sio2_thickness_at_window_x0"] = (ox[1] - ox[0]) if ox else None
        rec["sio2_present"] = "SiO2" in m["materials"]
    out["cases"].append(rec)
    print(f"[{label}] mats={rec.get('materials')} SiO2@x0={rec.get('sio2_thickness_at_window_x0')} "
          f"transition={rec.get('state_transition')} counts={rec['counts']} err={err}")
    return step, res


# fresh zero-duration LOCOS, default pad (grid floor) at three grids
for g in (0.02, 0.05, 0.10):
    run_case(f"locos_fresh_t0_defaultpad_g{g}", "locos", base_recipe(g, 0.0))
# fresh zero-duration LOCOS, explicit pad
run_case("locos_fresh_t0_pad0.10_g0.05", "locos", base_recipe(0.05, 0.0, pad=0.10))
run_case("locos_fresh_t0_pad0.20_g0.05", "locos", base_recipe(0.05, 0.0, pad=0.20))
# fresh zero-duration THERMAL (no mask concept)
for g in (0.02, 0.05, 0.10):
    run_case(f"thermal_fresh_t0_g{g}", "thermal", base_recipe(g, 0.0, mask=False))
# inherited zero-duration on an explicit planar fixture
fx = C.build_explicit(module, 0.05, 0.20)
before = C.measure(module, C.export(fx, work, "fx_before", C.DEPTH))
out["inherited_fixture_before_areas"] = {k: v["area"] for k, v in before["materials"].items()}
for model in ("thermal", "locos"):
    run_case(f"{model}_inherited_t0", model, base_recipe(0.05, 0.0, mask=False), inherited=fx)
# positive-time gate, fresh and inherited
for model, mask in (("thermal", False), ("locos", True)):
    run_case(f"{model}_fresh_t0.5", model, base_recipe(0.05, 0.5, mask=mask))
    run_case(f"{model}_inherited_t0.5", model, base_recipe(0.05, 0.5, mask=mask), inherited=fx)
after = C.measure(module, C.export(fx, work, "fx_after", C.DEPTH))
out["inherited_fixture_after_areas"] = {k: v["area"] for k, v in after["materials"].items()}
out["inherited_fixture_unchanged_after_all_runs"] = (
    out["inherited_fixture_before_areas"] == out["inherited_fixture_after_areas"])
out["scratch"] = work
C.save_json("exp7_fresh_zero_duration.json", out)
print("EXP7 DONE")
