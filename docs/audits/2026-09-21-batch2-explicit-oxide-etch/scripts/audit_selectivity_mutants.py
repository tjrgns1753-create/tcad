# -*- coding: utf-8 -*-
"""Sensitivity check for tests/integration/test_etch_selectivity_real.py: three mutated selective
recipes are run on independent copies of the SAME saved baseline and judged with the test's own
predicates. Each mutant must be caught (at least one predicate false). No production code is changed;
the mutants are RECIPES only.

  wrong_sign      : selective rates given with the opposite sign (Directional's wrapper flips the sign,
                    Isotropic's does not; a wrong sign is a silent no-op / deposition)
  no_selectivity  : Si rate == oxide rate (selectivity silently absent)
  oxide_untouched : oxide rate 0 (oxide never punched through)

Writes raw/selectivity_mutants.json.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
INTEGRATION = REPO / "tests" / "integration"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(INTEGRATION))

import _explicit_etch_fixture as fx
import test_etch_selectivity_real as t1
from tcad.backends.viennaps import session

common = {"etch_time_s": t1.T_TOTAL_S, "silicon_depth_um": t1.SILICON_DEPTH_UM}


def selective(model, ox, si):
    if model == "isotropic":
        return {"material_rates": {"SiO2": ox, "Si": si, t1.MASK_MATERIAL: 0.0}, **common}
    return {"direction": [0, -1, 0],
            "material_rates": {"SiO2": (ox, 0.0), "Si": (si, 0.0), t1.MASK_MATERIAL: (0.0, 0.0)}, **common}


MUTANTS = {
    "wrong_sign": (+t1.R_ETCH, +t1.R_SI_SELECTIVE),
    "no_selectivity": (-t1.R_ETCH, -t1.R_ETCH),
    "oxide_untouched": (0.0, -t1.R_SI_SELECTIVE),
}

tmp = tempfile.mkdtemp(prefix="mutants_", dir=session._ascii_scratch_dir())
baseline = fx.build_masked_explicit_stack(
    tmp, x_extent_um=t1.X_EXTENT_UM, y_extent_um=t1.Y_EXTENT_UM, silicon_depth_um=t1.SILICON_DEPTH_UM,
    oxide_top_um=t1.OXIDE_UM, grid_delta_um=t1.GRID_UM, mask_spans_um=t1.MASK_SPANS_UM,
    mask_height_um=t1.MASK_HEIGHT_UM, mask_material=t1.MASK_MATERIAL, reach_um=t1.REACH_UM)
out = {}
for model in ("isotropic", "directional"):
    plain = fx.run_etch_on_independent_copy(baseline, model, t1.recipes()[model]["plain"], tmp, f"{model}_plain")
    rp = fx.native_removal(plain.core_before, plain.core_after)
    for name, (ox, si) in MUTANTS.items():
        o = fx.run_etch_on_independent_copy(baseline, model, selective(model, ox, si), tmp, f"{model}_{name}")
        rs = fx.native_removal(o.core_before, o.core_after)
        ev = fx.exported_view(o.core_before, o.core_after)
        predicates = {
            "oxide_punched_through_in_core": ev["sio2_columns_present_after"] == 0,
            "plain_gt_selective_gt_0": rp["si_removed_um"] > rs["si_removed_um"] > 0.0,
            "selective_depth_matches_recipe": abs(rs["si_removed_um"] - t1.EXPECTED_SI_SELECTIVE_UM) <= t1.DEPTH_TOLERANCE_UM,
        }
        out[f"{model}/{name}"] = {"si_removed_um": rs["si_removed_um"], "oxide_removed_um": rs["oxide_removed_um"],
                                  "plain_si_removed_um": rp["si_removed_um"],
                                  "sio2_columns_after": ev["sio2_columns_present_after"],
                                  "predicates": predicates, "caught": not all(predicates.values())}
        print(model, name, out[f"{model}/{name}"])
assert all(v["caught"] for v in out.values()), "a mutant slipped through the test's predicates"
(HERE.parent / "raw" / "selectivity_mutants.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print("ALL MUTANTS CAUGHT")
