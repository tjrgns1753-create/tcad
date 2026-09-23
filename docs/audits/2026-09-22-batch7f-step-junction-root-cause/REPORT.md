# Batch 7F -- 2D step-junction 비수렴 원인 분리 감사 (investigation-only, no production changes)

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing
committed). Zero `tcad/` or `tests/` files touched. Zero existing Batch 7D/7E audit files intentionally modified --
one incidental, disclosed, content-preserving-but-not-byte-preserving line-ending change to
`../2026-09-21-batch7d-step-junction-convergence/REPORT.md` occurred during mutation-test 10's temporary write+
restore cycle; see the chat report's own disclosure section for the full incident and root cause.

**Headline finding**: `sum(NodeVolume)` vs the mesh's own real triangulated area grows from 18.6% (L3) to 33.1%
(L4) to 62.3% (L5) relative error, ISOLATED to the transition-ring triangles `refine_mesh_near()`'s red-green
closure creates (min angle collapsing 3.8deg -> 1.8deg -> 0.9deg with level). A comparable-resolution deterministic
structured control mesh (same local spacing, same contacts, fixed OR alternating diagonal, any height) shows
~1e-14 relative error at every level. The RAW, unrefined ViennaPS mesh (before `refine_mesh_near()`) also shows
~7e-7 relative error. This isolates the defect to `refine_mesh_near()`'s own refinement mechanism specifically --
not ViennaPS's export, not DevSim's NodeVolume computation itself, not triangle thinness in general.

* `scripts/capability_A_node_volume.py`, `capability_B_vector_field.py` -- the two public-API capability spikes
  (both passed; see raw/).
* `scripts/probe_case_7f.py`, `structured_mesh.py`, `mesh_quality.py`, `byte_identical_proof.py` -- the measurement
  harness (public DEVSIM API only; `scan_public_api_only_7f.py` verifies this statically).
* `scripts/case_manifest.py`, `run_matrix_7f.py` -- the fixed, pre-hashed 24-case matrix (12 imported + 12
  structured) and its subprocess-isolated dispatcher.
* `scripts/check_completeness_7f.py`, `mutation_tests_7f.py` -- verification harness (12/12 mutations caught).
* `data/*.json`, `data/aggregate_report.txt` -- raw per-case measurements and the aggregated tables.

See the full 23-section report in chat for the complete evidence, hypothesis judgment table, and production-change
recommendation (none implemented this batch).
