# Batch 7H-E2 ERRATUM — Supplement 1 (corrects ERRATUM.md section 4)

`ERRATUM.md` is left unchanged. This supplement records which of its sentences are withdrawn, the counter-example numbers,
and the corrected reading. All numbers below are MEASURED from existing arrays by
`docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/scripts/recheck_e2_e3.py` (numpy only, read-only; output
`.../data/recheck_e2_e3.json`) unless a line says FORMULA or RULE-APPLIED. Raised by the Codex lead's review of 7H-E3.

## 1. Withdrawn sentences (ERRATUM.md section 4)

| # | Original sentence (ERRATUM.md s. 4) | Status | Counter-example (measured) |
|---|---|---|---|
| a | "a real, exactly-quantified 1.5625e8 / 2.5e11 = 0.0625 % contribution to the donor-side `exact_dual_F2` ... that exists purely because of this ... convention" | **withdrawn** | S4 donor F2 total - continuum = **7.809053e7 cm^-1 = 0.031236 %**, not 1.5625e8. 1.5625e8 is the x = 0 column's own F2 x N, but the x > 0 side then covers only 25 um^2 minus a half-column strip, so the net gap is half of it. |
| b | "wholly independent of any refinement-stage defect (it is present, unchanged, at S0 before any refinement is applied)" | **withdrawn** | The x = 0 column's F2 area halves at every pass: S0 **2.499999765e-9**, S1 1.249999882e-9, S2 6.249999411e-10, S3 3.124999706e-10, S4 **1.562499853e-10 cm^2** (16x smaller). The donor F2 gap follows it: S0 **1.249965e9 (0.499986 %)**, S1 6.249655e8, S2 3.124655e8, S3 1.562155e8, S4 7.809053e7 (0.031236 %). Not present unchanged; it depends on the refinement. |
| c | "The same computation on the flip-candidate mesh gives a smaller observed gap (7.809e7 cm^-1, about half of the S0-based figure); ... this smaller number reflects some additional, currently uncharacterized interaction between the flip and the x = 0 column's own F2 partition. That residual difference ... is left UNKNOWN" | **withdrawn** | The flip changed nothing here: donor F2 total is **2.5007809053e11 cm^-1** on S4, on the E2 exact-flip candidate, and on the E3 graded candidate (identical to 10 significant figures). x = 0 column F2 area is 1.562499853e-10 cm^2 on all three. The "about half" came from comparing a full-column figure with a net gap (item a), not from the flip. |
| d | "at ~0.06 %, is an order of magnitude smaller than the candidate's own remaining 2.02 % excess and two orders of magnitude smaller than S4's original 5.83 %" | **corrected** | At S4 / flip / E3 the rule-driven gap is 0.031 %; the comparison with the shape-driven NodeVolume excess (2.02 %, 5.83 %, 0.94 %) still holds qualitatively, but the number was wrong and the gap is not a fixed quantity (it is 0.5 % at S0). |

The facts ERRATUM.md section 4 stated correctly are kept: every x = 0 node carries the full donor AND the full acceptor
concentration (RULE `wafer_state_v2.py:743-744`, DEVSIM `step()` convention `doping_mapping.py:864,868`); `exact_dual_F2`
and the continuum `N x 25 um^2` are different references and neither is the physical truth.

## 2. Corrected reading — two separate mechanisms

**(i) Area partition (geometry, MEASURED + FORMULA).** In the signed dual F2 (which partitions the exact area), the x = 0
column's dual strip has width (h_left + h_right)/2, where h_left, h_right are the distances to the first node column on each
side, and height H = 5e-4 cm. The nodes with x > 0 therefore cover the area 25 um^2 minus a strip of width h_right/2.
FORMULA (derived here, not a literature result): with donor = N on x >= 0 and 0 on x < 0,

    donor F2 integral - N x 25 um^2 = N x H x h_left / 2      (acceptor: N x H x h_right / 2)

The formula matches the measured gap at every stage (formula vs measured, cm^-1): S0 1.25e9 vs 1.249965e9; S1 6.25e8 vs
6.249655e8; S2 3.125e8 vs 3.124655e8; S3 1.5625e8 vs 1.562155e8; S4, flip, E3 7.8125e7 vs 7.809053e7. The residual of
about 3.4e5 cm^-1 is consistent with the float32 coordinates (total F2 area 4.999999311e-7 cm^2 rather than exactly
5e-7); that attribution is an inference, not separately isolated.

**(ii) Junction-line double assignment (rule, not geometry).** The gap exists at all only because the x = 0 node gets both
species at full strength (step(0) = 1 on both sides). A mesh with no node exactly on x = 0 (the J1 representation of the
7H-D fixtures) would not have this term. With a J0 node column, the term is N x H x h / 2 and shrinks linearly with the
first-column spacing h. It is set by the local spacing at the junction line, not by the triangle shapes elsewhere.

**Where the change happens (MEASURED):** every refinement pass S0->S1->...->S4 halves h (5.0e-6 -> 2.5e-6 -> 1.25e-6 ->
6.25e-7 -> 3.125e-7 cm) and halves the gap. The x = 0 column's NodeVolume equals its F2 at every stage (no obtuse triangle
touches x = 0), so the DEVSIM NodeVolume integral has the same x = 0 part. Its much larger total excess at S1-S4 (donor
NodeVolume total 2.5187e11 at S1 up to 2.6464e11 at S4) is the separate shape mechanism at |x| = 0.10-0.15 um, 7H-E2's
main finding, and is unaffected by this supplement.

## 3. Status of the continuum reference
N x 25 um^2 = 2.5e11 cm^-1 is the integral of the idealized step profile with a zero-width junction. It is a mathematical
comparison point for the profile this project defines. It is not evidence about the active doping of a real wafer.
