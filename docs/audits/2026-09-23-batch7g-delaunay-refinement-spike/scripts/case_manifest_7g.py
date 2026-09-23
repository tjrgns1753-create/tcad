"""Batch 7G Phase 1 -- fixed, pre-hashed case manifest for the geometry audit
(section 6/11). Never changed after seeing a first result. Reuses Batch 7F's
own local-spacing values (already hashed/sourced there) for the structured
control's band spacing.
"""
import hashlib
import json
import os

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)

REV2_LOCAL_SPACING_CM = {3: 1.249999968422344e-06, 4: 6.24999984211172e-07, 5: 3.12499992105586e-07}
CASE_TIMEOUT_S = 600

GEOMETRY_CASES = [
    {"mode": "raw", "label": "geo_raw"},
    {"mode": "imported", "level": 3, "label": "geo_imp_L3"},
    {"mode": "imported", "level": 4, "label": "geo_imp_L4"},
    {"mode": "imported", "level": 5, "label": "geo_imp_L5"},
    {"mode": "structured", "level_equiv": 3, "band_spacing_um": REV2_LOCAL_SPACING_CM[3] / 1.0e-4, "label": "geo_struct_L3"},
    {"mode": "structured", "level_equiv": 4, "band_spacing_um": REV2_LOCAL_SPACING_CM[4] / 1.0e-4, "label": "geo_struct_L4"},
    {"mode": "structured", "level_equiv": 5, "band_spacing_um": REV2_LOCAL_SPACING_CM[5] / 1.0e-4, "label": "geo_struct_L5"},
]

# Coordinate/tolerance constants used throughout geometry_checks.py, recorded
# here for the manifest record (see that module's own docstring for the
# rationale -- never adjusted after seeing real-mesh results).
FIXED_TOLERANCES = {
    "COORD_TOL_REL": 1e-9,
    "DELAUNAY_ANGLE_SLACK_RAD": 1e-9,
    "overlap_area_threshold_um2": 1e-20,
}

MANIFEST = {
    "batch": "7G-Phase1", "created": "2026-09-23", "case_timeout_s": CASE_TIMEOUT_S,
    "levels": [3, 4, 5], "no_L6_or_above": True,
    "fixed_tolerances": FIXED_TOLERANCES,
    "rev2_local_spacing_cm_reused": REV2_LOCAL_SPACING_CM,
    "geometry_cases": GEOMETRY_CASES,
}

if __name__ == "__main__":
    path = os.path.join(DATA, "case_manifest_7g.json")
    text = json.dumps(MANIFEST, indent=2, sort_keys=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(os.path.join(DATA, "case_manifest_7g.sha256"), "w", encoding="utf-8") as f:
        f.write(f"{sha}  case_manifest_7g.json\n")
    print(f"n_geometry_cases={len(GEOMETRY_CASES)} sha256={sha}")
