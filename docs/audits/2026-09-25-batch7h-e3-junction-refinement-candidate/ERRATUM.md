# Batch 7H-E3 ERRATUM (interpretation only)

Written after the Codex lead's review. `PLAN.md`, `PLAN.sha256`, the remote raw files (`e3_result.json`, npz, vtu,
hash-linked `run.log` / `summary.json`) and the registered check values are NOT changed. `CANDIDATE_REJECTED` stands: the
candidate's `ratio_within_tau` failure (0.9375 % excess vs tau 2.64e-11) is real and alone sufficient. This erratum corrects
how the other two failed checks and one field are read. Numbers are MEASURED by
`docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/scripts/recheck_e2_e3.py` (read-only, output
`.../data/recheck_e2_e3.json`).

## 1. `resolution_not_coarser_than_S4 = False`: the metric was invalid, and a valid metric gives a different picture

REPORT.md read the failed check as "coarser by 1.3e-4 relative ... not from the candidate systematically under-resolving
the junction". Both halves of that are withdrawn.
* **The metric** (the single shortest edge within 0.1 um of x = 0) does not represent junction resolution. One sliver edge
  makes it small. It is not used again.
* **At the junction line, S4 and E3 are identical (MEASURED).** Both have 1601 x = 0 nodes with identical y-coordinate sets
  (exact array equality). The y-spacing along x = 0 is 3.1243e-7 to 3.1258e-7 cm in both. The first node column is at
  x = +-3.12499992e-7 cm in both.
* **Away from the line, E3 is genuinely coarser (MEASURED, per band of edge-midpoint |x|).** The REPORT's "not
  systematically under-resolving" is contradicted:

| band (um) | S4 max edge / max horizontal edge (um) | E3 max edge / max horizontal edge (um) | E3 / S4 horizontal |
|---|---|---|---|
| 0 - 0.025 | 0.0044199 / 0.0031250 | 0.0088393 / 0.0062500 | 2x |
| 0.025 - 0.05 | 0.0044199 / 0.0031250 | 0.0176781 / 0.0125000 | 4x |
| 0.05 - 0.1 | 0.0044200 / 0.0031250 | 0.0353555 / 0.0250000 | 8x |

  This follows from E3's design: its finest ring is |x| < 0.0125 um, so outside that ring it is 2-8x coarser than S4. With
  the depletion-approximation estimate W(0 V) = 0.0484 um (half-width about 0.024 um per side, an estimate, not a
  measurement), part of the estimated space-charge region lies in E3's 2x-coarser band. So "E3 resolves the junction as well
  as S4" is true at the junction line only, and false across the estimated depletion region. Whether S4's own resolution is
  sufficient is a separate, still-unverified question (single mesh, no convergence study).

## 2. `boundary_bit_identical = False`: over-strict specification, not a shape defect

The registered value stays `False`. Reading (MEASURED, S0 raw file vs E3 candidate file):
* 0 of 600 original boundary points were lost. 32 were added: 16 on the top line y = 0 and 16 on the bottom line y = -5,
  with x between -0.075 and +0.075 um. None were added on x = +-5.
* The bounding box and the 4 corners are unchanged. Every added point lies exactly on an existing straight boundary line.
* The left and right contact node sets are identical (101 and 101 nodes, exact set equality).

This changes how the boundary is subdivided, not the domain's shape. PLAN section 4 conflated "domain boundary" with
"contact boundary". The same effect exists in production S4, whose refinement window also has no y restriction. Future
PLANs specify separately:
* no boundary point lost;
* added points lie on the same boundary line;
* contact sets are unchanged;
* the area is exact.

## 3. Units of `exact_area_cm2`
The field holds `"50/1"`, computed on unscaled micrometre coordinates, so the unit is um^2 despite the field name. Comparisons
within E3 are self-consistent. Later audit code names the field after its actual unit (`exact_area_um2`). The E3 JSON is not
edited.

## 4. What stands
* `CANDIDATE_REJECTED`, because `ratio_within_tau` fails.
* The measured excess reduction 5.825 % -> 0.9375 % and the triangle count 247000 -> 79000 stand as measurements. They do
  not make E3 usable for doping or electrical results: its excess is about 3.5e8 times the tau budget, it has 3000 obtuse
  triangles, and it is coarser than S4 across most of the estimated depletion region.
