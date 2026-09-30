# Batch 7H-E6E SUPPLEMENT 1: corrections after Codex partial approval (E6E REPORT / PLAN / raw data unchanged)

1. **P0 defect in the E6E tolerance.** The E6E contract compared |S - A| with B = E_A + E_S + E_NV and had no limit on B/A.
   - E_NV = 128 u sum A_t / sin(theta_min,t) grows without bound for a sliver triangle.
   - The one-triangle counterexample (0,0), (1,0), (2,1e-14) with S = 2A PASSED on the E6E code, with B/A = 2.842170943040401 and
     S/A - 1 = 1.0 (Batch 7H-E6E-R1, `p0_before.json`).
   - E6E's statements that the contract "certifies" a region are therefore withdrawn for inputs whose B/A is large.
   - Batch 7H-E6E-R1 adds the refusal `MESH_AREA_UNCERTAINTY_TOO_LARGE` (B/A > 1e-8) and `MESH_AREA_BUDGET_NONFINITE`.
2. **Wording of the E6E REPORT header.** The header said the refused meshes include "raw, unrefined ViennaPS meshes whose Mask region
   ... is 8-28x ... and whose Si region is up to +30 %".
   - The +30 % Si case (`test_measurement_canonical_state_gate_real.py`) is a **refined** mesh (implant-windows graded refinement), not a
     raw one.
   - Its raw mesh conserves area exactly (7H-E6E-R1 diagnosis B: raw S/A - 1 = 0.0; refined +0.30000000000004756).
   - The raw case measured in 7H-E6E-R1 is the phase5 etch mesh. There, Mask is +17.935 and Si is +0.00278, and both regions fail.
3. **Budget basis.** The 128 u per-element term is an ASSUMED_BOUND inherited from 7H-E2. It was not derived from DEVSIM source.
   Nothing in E6E proves area conservation mathematically.
