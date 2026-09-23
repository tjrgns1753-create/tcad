# -*- coding: utf-8 -*-
"""Requested / native / exported geometry, BEFORE and AFTER mask creation, for both Batch 2 tests
(same parameters as the tests -- imported, not copied). Also the independent-copy evidence: sha256 of
the saved baseline, and per-copy equality with the baseline. Writes raw/geometry_tables.json."""
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
import test_oxidation_pr_etch_reaches_si_real as t2
from tcad.backends.viennaps import session

out = {}
for name, kw, recipe_model, recipe in (
    ("selectivity", dict(x_extent_um=t1.X_EXTENT_UM, y_extent_um=t1.Y_EXTENT_UM, silicon_depth_um=t1.SILICON_DEPTH_UM,
                         oxide_top_um=t1.OXIDE_UM, grid_delta_um=t1.GRID_UM, mask_spans_um=t1.MASK_SPANS_UM,
                         mask_height_um=t1.MASK_HEIGHT_UM, mask_material=t1.MASK_MATERIAL, reach_um=t1.REACH_UM),
     "isotropic", t1.recipes()["isotropic"]["plain"]),
    ("reaches_si", dict(x_extent_um=t2.WIDTH_UM, y_extent_um=t2.Y_EXTENT_UM, silicon_depth_um=t2.SILICON_DEPTH_UM,
                        oxide_top_um=t2.OXIDE_UM, grid_delta_um=t2.GRID_UM,
                        mask_spans_um=[tuple(s) for s in t2.DEVELOPED_SPANS], mask_height_um=t2.PR_THICKNESS_UM,
                        mask_material=t2.MASK_MATERIAL, reach_um=t2.REACH_UM),
     "isotropic", t2._recipe(t2.T_INSUFFICIENT_S)),
):
    tmp = tempfile.mkdtemp(prefix="geom_", dir=session._ascii_scratch_dir())
    b = fx.build_masked_explicit_stack(tmp, **kw)
    # two independent copies loaded and etched; the baseline stays pristine
    c1 = fx.run_etch_on_independent_copy(b, recipe_model, recipe, tmp, "copy1")
    c2 = fx.run_etch_on_independent_copy(b, recipe_model, recipe, tmp, "copy2")
    out[name] = {
        "requested": b.requested,
        "regions": {"window": b.regions.window_um, "core": b.regions.core_um,
                    "protected_bands": b.regions.protected_bands_um, "reach_um": b.regions.reach_um,
                    "basis": b.regions.basis},
        "native_core": {"pre_mask": b.pre_mask["native"], "post_mask": b.post_mask["native"]},
        "exported_core": {"pre_mask": b.pre_mask["exported"]["materials"], "post_mask": b.post_mask["exported"]["materials"]},
        "mask_creation_native_shift_um": b.mask_creation_native_shift_um,
        "vpsd_sha256": b.vpsd_sha256,
        "copy_pre_etch_equals_baseline": [c1.copy_matches_baseline, c2.copy_matches_baseline],
        "two_identical_recipes_two_copies_identical_result": (c1.core_after == c2.core_after),
        "pristine_after": fx.verify_baseline_pristine(b, tmp),
        "forbidden_calls_fixture": b.forbidden_call_counts,
        "oxidation_calls_in_etch_runs": [c1.oxidation_calls, c2.oxidation_calls],
    }
    print(name, json.dumps({k: out[name][k] for k in ("native_core", "exported_core", "mask_creation_native_shift_um",
                                                     "copy_pre_etch_equals_baseline", "two_identical_recipes_two_copies_identical_result",
                                                     "pristine_after", "regions")}, indent=1, default=str))
(HERE.parent / "raw" / "geometry_tables.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print("DONE")
