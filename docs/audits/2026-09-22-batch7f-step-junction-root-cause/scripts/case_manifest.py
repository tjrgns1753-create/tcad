"""Batch 7F -- build and hash the FIXED case manifest BEFORE any case is run.
Per the bounded prompt: case/tolerance/mesh/bias are never changed after
seeing a first result. Levels L3/L4/L5 only (no L6+). No commit, no
production changes.
"""
import hashlib
import json
import os

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)

# Local spacing (cm) at the junction for L3/L4/L5, read directly from Batch 7D
# Rev.2's own already-completed raw data (docs/audits/2026-09-21-batch7d-step-
# junction-convergence/rev2/data/rev2_L0L3.json + rev2_L4L5.json, 2D R1 node
# cases) -- reused as the deterministic x-spacing target for the structured
# control mesh (section 9's own requirement), never invented.
REV2_LOCAL_SPACING_CM = {3: 1.249999968422344e-06, 4: 6.24999984211172e-07, 5: 3.12499992105586e-07}
REV2_SOURCE_FILES = {
    3: "docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2/data/rev2_L0L3.json",
    4: "docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2/data/rev2_L4L5.json",
    5: "docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2/data/rev2_L4L5.json",
}

CASE_TIMEOUT_S = 900

IMPORTED_CASES = [
    {"mode": "imported", "level": lv, "representation": rep, "shifted": sh,
     "label": f"imp_L{lv}_{rep}_{'shift' if sh else 'node'}"}
    for lv in (3, 4, 5) for rep in ("R1", "R2") for sh in (False, True)
]

# R1-shift is included once for an explicit BYTE-LEVEL doping-array proof
# (see byte_identical_proof.py) then OMITTED from the STRUCTURED matrix only
# (imported matrix keeps all 4 representations per level, matching Batch 7D's
# own precedent and giving an independent re-confirmation on real ViennaPS
# mesh, not just the structured control).
STRUCTURED_CASES = [
    {"mode": "structured", "level_equiv": lv, "representation": rep, "shifted": sh, "diagonal": "fixed",
     "band_spacing_um": REV2_LOCAL_SPACING_CM[lv] / 1.0e-4,
     "label": f"struct_L{lv}_{rep}_{'shift' if sh else 'node'}_fixed"}
    for lv in (3, 4, 5) for rep in ("R1", "R2") for sh in (False, True)
    if not (rep == "R1" and sh)  # R1-shift omitted -- see byte_identical_proof.py
]
# diagonal-orientation control at the MID level (L4)
STRUCTURED_CASES.append({
    "mode": "structured", "level_equiv": 4, "representation": "R1", "shifted": False, "diagonal": "alternating",
    "band_spacing_um": REV2_LOCAL_SPACING_CM[4] / 1.0e-4, "label": "struct_L4_R1_node_alternating",
})
# H / 2H height-scaling control, ONE structured spacing level (L4-equivalent), R1 node
STRUCTURED_CASES.append({
    "mode": "structured", "level_equiv": 4, "representation": "R1", "shifted": False, "diagonal": "fixed",
    "band_spacing_um": REV2_LOCAL_SPACING_CM[4] / 1.0e-4, "y_extent_um": 2.0, "label": "struct_L4_R1_node_H",
})
STRUCTURED_CASES.append({
    "mode": "structured", "level_equiv": 4, "representation": "R1", "shifted": False, "diagonal": "fixed",
    "band_spacing_um": REV2_LOCAL_SPACING_CM[4] / 1.0e-4, "y_extent_um": 4.0, "label": "struct_L4_R1_node_2H",
})

MANIFEST = {
    "batch": "7F", "created": "2026-09-22", "case_timeout_s": CASE_TIMEOUT_S,
    "levels": [3, 4, 5], "no_L6_or_above": True,
    "rev2_local_spacing_cm_reused": REV2_LOCAL_SPACING_CM,
    "rev2_source_files": REV2_SOURCE_FILES,
    "imported_cases": IMPORTED_CASES,
    "structured_cases": STRUCTURED_CASES,
    "n_imported": len(IMPORTED_CASES), "n_structured": len(STRUCTURED_CASES),
}

if __name__ == "__main__":
    path = os.path.join(DATA, "case_manifest.json")
    text = json.dumps(MANIFEST, indent=2, sort_keys=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(os.path.join(DATA, "case_manifest.sha256"), "w", encoding="utf-8") as f:
        f.write(f"{sha}  case_manifest.json\n")
    print(f"n_imported={len(IMPORTED_CASES)} n_structured={len(STRUCTURED_CASES)} sha256={sha}")
