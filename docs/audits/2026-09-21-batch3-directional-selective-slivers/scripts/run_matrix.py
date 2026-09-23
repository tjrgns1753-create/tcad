"""Batch 3A: 13-run matrix. grid in (0.10, 0.05, 0.025) x {directional, isotropic} x {plain, selective}
(+ one repeat of directional/selective at grid 0.05 on a separate copy of the same baseline).

The physical inputs are those of tests/integration/test_etch_selectivity_real.py, unchanged (recipes come
from its own `recipes()`); only the grid varies, as fixed in advance. Nothing is added or removed after seeing
results. For each run, from the SAME post-etch domain, three stages are measured separately:

  A  native level sets                      (viennals ToSurfaceMesh, real line connectivity)
  B  level sets of the floored export copy  (vio._floored_copy_for_export: Expand + Box INTERSECT per level set)
  C  volume mesh of the UNfloored copy      (domain copy .saveVolumeMesh)
  D  volume mesh of the floored copy        (what vio.save_volume_mesh() writes) -- also compared to the step's own
     final_mesh
"""
import copy
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_common as ac
from audit_common import T, fx, vio, session, ed, np

import tcad.process.etching  # noqa: F401  (registers the etch models)
from tcad.process import registry

RAW = ac.AUDIT / "raw"
MESHES = RAW / "meshes"
GRIDS = (0.10, 0.05, 0.025)
CASES = [("directional", "plain"), ("directional", "selective"), ("isotropic", "plain"), ("isotropic", "selective")]
REPEAT = (0.05, "directional", "selective")
FLOOR_UM = T.SILICON_DEPTH_UM


def stage_native(domain, g, core):
    return ac.native_metrics(domain, ac.WINDOW, g, core)


def run_case(baseline, g, model, tag, outdir, label):
    assert ac.sha256_file(baseline.vpsd_path) == baseline.vpsd_sha256, "baseline .vpsd changed on disk"
    pre_domain = session.load_domain_state(baseline.vpsd_path)
    run_domain = session.load_domain_state(baseline.vpsd_path)           # independent copy that gets etched
    recipe = T.recipes()[model][tag]
    core = baseline.regions.core_um
    t0 = time.time()
    with fx.forbid_oxidation(ac.MODULE) as counts:
        step = registry.get("etching", model)(inherited_domain=run_domain)
        result = step.run(dict(recipe), str(Path(outdir) / label))
    elapsed = time.time() - t0
    post = step.last_domain

    pre_native = stage_native(pre_domain, g, core)
    post_native = stage_native(post, g, core)
    sha_before_exports = post_native["surface_sha256"]
    rec = {"grid_um": g, "model": model, "recipe_kind": tag, "label": label, "recipe": recipe,
           "etch_elapsed_s": round(elapsed, 2), "oxidation_calls": counts["Oxidation"],
           "material_map_pre": ac.material_map_record(pre_domain), "material_map_post": ac.material_map_record(post),
           "native_pre": pre_native, "native_post": post_native,
           # NOTE: this first metric is CONFOUNDED by an undercut beneath the mask (isotropic lowers the SiO2/Si
           # level sets, which raises 'Mask thickness' although the mask did not move). Kept in the raw output for
           # transparency; the wall-position metric below is the one that answers "did the rate-0 mask move?".
           "mask_body_movement_pre_vs_post__CONFOUNDED": ac.mask_body_movement(pre_native["_surf"], post_native["_surf"], g),
           "wall_positions_pre": ac.wall_positions(pre_native["_surf"], g),
           "wall_positions_post": ac.wall_positions(post_native["_surf"], g)}

    # B: level sets of the floored export copy
    floored = vio._floored_copy_for_export(post, FLOOR_UM)
    rec["native_floored_copy"] = stage_native(floored, g, core)
    # C: volume mesh of the UNfloored copy of the same post domain
    unfloored = post.__class__(post)
    base_c = str(Path(outdir) / f"{label}_unfloored")
    unfloored.saveVolumeMesh(base_c)
    path_c = f"{base_c}_volume.vtu"
    # D: volume mesh of the floored copy (== vio.save_volume_mesh); compare with the step's own export
    base_d = str(Path(outdir) / f"{label}_floored")
    floored.saveVolumeMesh(base_d)
    path_d = f"{base_d}_volume.vtu"
    final = result["final_mesh"]
    rec["files"] = {"final_mesh_sha256": ac.sha256_file(final), "floored_export_sha256": ac.sha256_file(path_d),
                    "unfloored_export_sha256": ac.sha256_file(path_c),
                    "final_mesh_identical_to_floored_export_bytes": ac.sha256_file(final) == ac.sha256_file(path_d)}
    # exporting must not have altered the post domain
    rec["post_domain_unchanged_by_exports"] = ac.domain_surfaces(post) is not None and \
        ac.native_metrics(post, ac.WINDOW, g, core)["surface_sha256"] == sha_before_exports

    pre_mesh = ac.load_tagged(baseline.baseline_mesh_path)
    rec["volume_baseline"] = ac.volume_metrics(pre_mesh, ac.WINDOW, core)
    rec["foot_native_pre"] = ac.foot_native(pre_native["_surf"])
    rec["foot_native_post"] = ac.foot_native(post_native["_surf"])
    final_tagged = ac.load_tagged(final)
    rec["foot_volume_pre"] = ac.foot_triangles(pre_mesh)
    rec["foot_volume_final"] = ac.foot_triangles(final_tagged)
    rec["volume_final"] = ac.volume_metrics(final_tagged, ac.WINDOW, core, pre_mesh)
    rec["volume_floored_export"] = ac.volume_metrics(ac.load_tagged(path_d), ac.WINDOW, core, pre_mesh)
    rec["volume_unfloored_export"] = ac.volume_metrics(ac.load_tagged(path_c), ac.WINDOW, core, pre_mesh)

    cls = {}
    for mat in ("SiO2", "Mask"):
        nat = post_native["materials"].get(mat, {}).get("present_in_window_native")
        exp = rec["volume_final"]["materials"].get(mat, {}).get("n_crossing_triangles_positive_area", 0) > 0
        cls[mat] = ac.classify(nat, exp)
    rec["classification_native_vs_export"] = cls

    MESHES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, MESHES / f"g{g}_{label}_final_floored.vtu")
    shutil.copy2(path_c, MESHES / f"g{g}_{label}_unfloored.vtu")
    return rec


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    env = {"python": sys.version, "platform": platform.platform(),
           "numpy": np.__version__, "viennals": getattr(ac.vls, "__version__", "?"),
           "viennaps": getattr(ac.MODULE, "__version__", "?"),
           "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ac.REPO, capture_output=True, text=True).stdout.strip(),
           "physical_inputs": {"oxide_um": T.OXIDE_UM, "window_half_um": T.WINDOW_HALF_UM, "mask_height_um": T.MASK_HEIGHT_UM,
                               "R_ETCH_um_per_s": T.R_ETCH, "R_SI_SELECTIVE_um_per_s": T.R_SI_SELECTIVE,
                               "T_TOTAL_S": T.T_TOTAL_S, "x_extent_um": T.X_EXTENT_UM, "y_extent_um": T.Y_EXTENT_UM,
                               "silicon_depth_um": T.SILICON_DEPTH_UM, "mask_material": T.MASK_MATERIAL},
           "grids": list(GRIDS), "cases": CASES, "repeat": list(REPEAT)}
    results = {"environment": env, "runs": []}
    n = 0
    for g in GRIDS:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = fx.build_masked_explicit_stack(
                tmp, x_extent_um=T.X_EXTENT_UM, y_extent_um=T.Y_EXTENT_UM, silicon_depth_um=T.SILICON_DEPTH_UM,
                oxide_top_um=T.OXIDE_UM, grid_delta_um=g, mask_spans_um=T.MASK_SPANS_UM,
                mask_height_um=T.MASK_HEIGHT_UM, mask_material=T.MASK_MATERIAL, reach_um=T.REACH_UM)
            MESHES.mkdir(parents=True, exist_ok=True)
            shutil.copy2(baseline.baseline_mesh_path, MESHES / f"g{g}_baseline_post_mask_pre_etch.vtu")
            todo = [(m, k, f"{m}_{k}") for m, k in CASES]
            if g == REPEAT[0]:
                todo.append((REPEAT[1], REPEAT[2], f"{REPEAT[1]}_{REPEAT[2]}_REPEAT"))
            for model, tag, label in todo:
                n += 1
                print(f"[{n}/13] grid {g} {label} ...", flush=True)
                rec = run_case(baseline, g, model, tag, tmp, label)
                rec["run_number"] = n
                rec["baseline_sha256"] = baseline.vpsd_sha256
                results["runs"].append(rec)
                ac.dump_json(results, RAW / "matrix_results.json")
                print(f"      done in {rec['etch_elapsed_s']} s; classification {rec['classification_native_vs_export']}", flush=True)
    results["derive_regions_fallbacks"] = ac.FALLBACKS
    ac.dump_json(results, RAW / "matrix_results.json")
    print("runs:", n, "| fallbacks:", ac.FALLBACKS)


if __name__ == "__main__":
    main()
