"""Batch 7F completeness checker -- validates imported_7f.json/structured_7f.json
+ case_manifest.json against every structural requirement sections 5-11 list.
usage: python check_completeness_7f.py <imported_7f.json> <structured_7f.json> <case_manifest.json>
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(__file__)
BATCH7D_DIR = os.path.join(HERE, "..", "..", "2026-09-21-batch7d-step-junction-convergence")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    imported_path, structured_path, manifest_path = sys.argv[1:4]
    imported = list(load(imported_path).values())[0]
    structured = list(load(structured_path).values())[0]
    manifest = load(manifest_path)
    problems = []

    # ---- required levels present (imported) ------------------------------------------------------------------
    levels_present = {c.get("level") for c in imported if "error" not in c}
    if not {3, 4, 5} <= levels_present:
        problems.append(f"missing imported levels: required {{3,4,5}}, found {levels_present}")
    if any(c.get("level", 0) > 5 for c in imported):
        problems.append("L6+ found in imported cases -- forbidden")

    # ---- required imported representations x shift ------------------------------------------------------------
    combos = {(c.get("level"), c.get("representation"), c.get("shifted")) for c in imported if "error" not in c}
    required = {(lv, rep, sh) for lv in (3, 4, 5) for rep in ("R1", "R2") for sh in (False, True)}
    missing = required - combos
    if missing:
        problems.append(f"missing imported (level,representation,shifted) combos: {sorted(missing)}")

    # ---- mesh quality / contact geometry / inventory / field / y-invariance / depletion, per converged case ----
    for c in imported:
        label = c.get("label")
        if "error" in c:
            problems.append(f"{label}: probe error: {c['error'][:150]}")
            continue
        mq = c.get("mesh_quality")
        if not mq or not all(k in mq for k in ("whole", "junction_band", "transition_ring", "coarse_outer")):
            problems.append(f"{label}: missing mesh_quality zones (band/ring/outer/whole)")
        else:
            for zone in mq.values():
                if zone.get("n_triangles", 0) > 0:
                    needed = ("n_unique_edges", "n_duplicate_coords", "n_zero_area_triangles",
                             "n_flipped_orientation_triangles", "n_non_manifold_edges", "edge_length",
                             "triangle_area", "triangle_min_angle_deg", "aspect_ratio_longest_edge_over_shortest_altitude")
                    absent = [k for k in needed if k not in zone]
                    if absent:
                        problems.append(f"{label}: mesh_quality zone missing fields {absent}")
        inv = c.get("inventory")
        if not inv or "Q_D_over_q_cm-1" not in inv or "Q_A_over_q_cm-1" not in inv:
            problems.append(f"{label}: missing NodeVolume-based inventory (Q_D/Q_A)")
        if inv and "n_nodes" == "count":  # mutation 1 target field name -- see mutation test
            pass
        if inv and "sum_NodeVolume_cm2" not in inv:
            problems.append(f"{label}: inventory does not use NodeVolume (mutation 1 -- node-count substitute)")
        col = c.get("junction_column")
        if not col or "column_NodeVolume_sum_cm2" not in col:
            problems.append(f"{label}: missing junction-column volume")
        if not c.get("equilibrium_converged"):
            continue
        field = c.get("field")
        if not field:
            problems.append(f"{label}: missing field analysis")
        else:
            for key in ("global_max", "junction_band_max", "junction_interior_max_excl_boundary"):
                fm = field.get(key)
                if fm is None:
                    continue
                if "centroid_cm" not in fm or "magnitude_Vpercm" not in fm or "Ex_Vpercm" not in fm or "Ey_Vpercm" not in fm:
                    problems.append(f"{label}: field.{key} missing location/Ex/Ey/magnitude (mutation 2/3)")
            if "n_elements" not in field:
                problems.append(f"{label}: field missing element-vector evidence (mutation 2 -- scalar mislabeled as vector)")
        yinv = c.get("y_invariance")
        if not yinv or "Potential_max_spread" not in yinv:
            problems.append(f"{label}: missing y-invariance check (mutation 4)")
        for dep_key in ("depletion_old_ycollapsed_donor_side", "depletion_center_yline_donor_side",
                       "depletion_volume_weighted_donor_side"):
            if c.get(dep_key) is None:
                problems.append(f"{label}: missing {dep_key}")

    # ---- R1 vs R2 inventory difference present (mutation 8) -----------------------------------------------------
    by_key = {(c.get("level"), c.get("representation"), c.get("shifted")): c for c in imported if "error" not in c}
    for lv in (3, 4, 5):
        for sh in (False, True):
            r1, r2 = by_key.get((lv, "R1", sh)), by_key.get((lv, "R2", sh))
            if r1 and r2 and r1.get("inventory") and r2.get("inventory"):
                pass  # presence itself is the check; the report computes the actual delta
            elif r1 or r2:
                problems.append(f"L{lv} shifted={sh}: R1/R2 inventory pair incomplete -- cannot compute R1-R2 difference")

    # ---- structured control present ------------------------------------------------------------------------------
    struct_labels = {c.get("label") for c in structured if "error" not in c}
    struct_manifest_labels = {c["label"] for c in manifest.get("structured_cases", [])}
    if len(struct_manifest_labels) < 9:
        problems.append(f"structured control missing/undersized: only {len(struct_manifest_labels)} cases in manifest (mutation 5)")
    if "struct_L4_R1_node_H" not in struct_manifest_labels or "struct_L4_R1_node_2H" not in struct_manifest_labels:
        problems.append("H/2H height-scaling control missing (mutation 6)")
    struct_levels = {c.get("level_equiv") for c in manifest.get("structured_cases", []) if "level_equiv" in c}
    if 5 not in struct_levels:
        problems.append("structured L5-equivalent case missing (mutation 7)")
    if not any(c.get("diagonal") == "alternating" for c in manifest.get("structured_cases", [])):
        problems.append("diagonal-orientation control (alternating) missing")

    # ---- Batch 7D raw files untouched (mutation 10) ---------------------------------------------------------------
    snapshot_path = os.path.join(HERE, "..", "data", "batch7d_pre_existing_hashes.txt")
    if os.path.exists(snapshot_path):
        changed = []
        with open(snapshot_path, encoding="utf-8") as f:
            for line in f:
                sha, rel = line.strip().split("  ", 1)
                full = os.path.join(HERE, "..", "..", "..", "..", rel)
                if not os.path.exists(full):
                    changed.append(f"MISSING: {rel}")
                    continue
                now = hashlib.sha256(open(full, "rb").read()).hexdigest()
                if now != sha:
                    changed.append(f"CHANGED: {rel}")
        if changed:
            problems.append(f"Batch 7D pre-existing files modified: {changed[:5]}")
    else:
        problems.append("no Batch 7D pre-existing-file hash snapshot found to verify against (run make_batch7d_snapshot.py first)")

    # ---- no fabricated iteration counts (mutation 12) --------------------------------------------------------------
    def _scan_for_actual_iterations(obj, path=""):
        if isinstance(obj, dict):
            if "actual_iterations" in obj and obj["actual_iterations"] is not None:
                problems.append(f"fabricated actual_iterations at {path}: {obj['actual_iterations']!r}")
            for k, v in obj.items():
                _scan_for_actual_iterations(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _scan_for_actual_iterations(v, f"{path}[{i}]")

    _scan_for_actual_iterations(imported, "imported")
    _scan_for_actual_iterations(structured, "structured")

    if problems:
        print("COMPLETENESS CHECK FAILED:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print("COMPLETENESS CHECK PASSED: all mesh-quality/inventory/field/y-invariance/depletion/structured/"
          "H2H/L5/diagonal/batch7d-untouched/no-fabricated-iterations requirements satisfied.")


if __name__ == "__main__":
    main()
