# Corrections to Batch 7G Rev.1 (recorded here; Rev.1 files are left byte-identical)

Each item was re-verified against the stored Rev.1 files at the start of Batch 7H-A.

1. **Rev.1 chat report tolerance numbers were wrong for the L3 run.** The chat report stated
   `median_edge_length = 0.0354 um`, `area_tol = 8.43e-8 um^2`. Those values came from
   `phase_d_investigate_unknowns.py`, which runs on the 3-pass mesh (1834 triangles), not on the L3
   mesh (5760 triangles, refine_levels=4) used by `phase_e_l3_spike.py`.

2. **The stored L3 run used different values.** `data/phase_e_l3_spike.json`,
   `flip_report.tolerance`: `median_edge_len = 0.01250004768371582 um`,
   `area_tol = 2.9802436074533034e-08 um^2`, `length_tol = 2.384185791015625e-07 um`.

3. **`material_tags_preserved` in `phase_e_l3_spike.py` compares only the SET of tag values**
   (`material_tags_present = sorted(set(tags))`, line 80). It does not prove the tag multiset or
   per-triangle material ownership is preserved.

4. **`n_constrained_edges` compares only a COUNT** (line 52). It does not prove that the exact
   boundary, contact or material-interface edge set is preserved.

5. **`old_tri_multiset` / `new_tri_multiset` are computed and never used** (lines 77-78). No assertion
   depends on them.

6. **Rev.1's overlap safety check is fail-open.** Both `corrected_triangle_overlap_check`
   (`geometry_checks_v2.py:320`) and Candidate A's `_local_overlap_area_against_externals`
   (`candidate_a_edge_flip_v2.py:115`) count a pair as overlap only when BOTH methods agree. A pair on
   which the methods disagree (UNKNOWN) adds nothing to the before/after overlap total, so a flip that
   creates an UNKNOWN pair is accepted. Rev.1's "68/68 flips, 0 overlap increase" therefore does not
   prove that no overlap was created.

Consequence: Rev.1's claims "no real overlap in L3", "Candidate A created no overlap", and "all
material/contact/boundary invariants preserved" were not proven by Rev.1's own code. Batch 7H-A
re-examines each one with exact rational arithmetic and exact set comparisons.
