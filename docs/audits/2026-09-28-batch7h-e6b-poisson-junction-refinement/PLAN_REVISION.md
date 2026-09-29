# Batch 7H-E6B PLAN Rev.2 — revision record

* Rev.1: `PLAN.md` sha256 `50555b7d9eec55515d6183a224fd1c88a783e3249667eeeaf89e1a89ba070cdf`, committed `e2cbfae6675bb7b27c7be4b7e6a7fcb6e7670c7a`. Kept as history in this repository's git log; not deleted, not treated as if it never existed.
* Rev.2: `PLAN.md` sha256 `59abed68b30247720946a7486170e56ae97b52b1457c7da0ecd3bacc8b56357c`, committed `8cca4c518838cca967d56df7a6b2de2a9b3e8644` (literal value recorded in Rev.3 because `PLAN.sha256` now holds Rev.3's hash; Rev.2's text remains in git history).
* Rev.3: see the section "Rev.3" at the end of this file and `PLAN.sha256`.
* Neither PLAN has been executed. No `devsim.solve()` call has been made for this batch. This revision happened entirely before any execution, so it is a correction to the pre-registration itself, not a post-hoc change of criteria after seeing a result.

## Defect 1 — inconsistent pair indices (`d_23`/`d_34`, `s_L`, `t_L`)

**Before (Rev.1 section 8):** `SOLVER_NOISE_INDISTINGUISHABLE | d_34 <= s_4 + s_5 or d_23 <= s_3 + s_4`. `d_23` was used for the (L3, L4) difference and `d_34` for the (L4, L5) difference — neither subscript matched the actual level numbers being compared, and section 3 never formally defined `d_23`/`d_34` at all (only prose "Pairs: (L3, L4) and (L4, L5)"). Section 6 separately used `s_L^inf`, `s_L^2`, `t_L` for the same underlying quantity under different names.

**After (Rev.2 sections 3, 4, 7, 9):** One notation used everywhere: `D34(M)` = (L3-P, L4-P) difference, `D45(M)` = (L4-P, L5-P) difference, `S3(M)`/`S4(M)`/`S5(M)` = each level's own (P, C) `observed_solver_shift`, for M in `{psiLinf, psiL2, ExLinf, ExRMS}`. Section 4 adds a synthetic (non-DEVSIM) numeric table with four cases — (a) clear decrease, (b) large solver change at L4, (c) only `D45` small, (d) both differences equal — each showing the actual inequality substitutions and the resulting section-9 state, re-verified by a small script this session (see final chat report).

## Defect 2 — non-convergent control solve could produce a false PASS

**Before (Rev.1 section 6):** "The control is `SOLVER_CONTROL_INVALID` if it errors, gives non-finite values, or its final device relative error exceeds the primary's; converged = false alone is recorded but not invalidating." This explicitly allowed a control that DEVSIM itself reports as unconverged to still be used as a valid `s_L`/`t_L` value.

**After (Rev.2 section 7, section 8):** `converged: false` (or an error, or a missing result) on any of `L3-C`/`L4-C`/`L5-C` makes that level's `S` invalid for every use — `SOLVER_CONTROL_INVALID` is reported for that level and no `LOCAL_JUNCTION_REFINEMENT_TREND_ONLY` is declared for any metric that needed it. The same rule is applied to `R6-C`/`R7-C`: either failing makes the 1D reference `REFERENCE_1D_UNUSABLE` (no positive floor-related state), while the raw 2D results are never discarded. Section 4 case (e) is the required demonstration: an unconverged `L4-C` with a deceptively tiny reported potential change (1e-9 V) is NOT evaluated against the discriminant at all — the run reports `SOLVER_CONTROL_INVALID` regardless of the raw number. `S` is now named `observed_solver_shift` everywhere (never "error" or "bound") to keep this distinction visible in any future report.

## Defect 3 — 1D reference `u_ref` treated as an uncertainty bound; floor states overclaimed

**Before (Rev.1 section 7):** `u_ref = max |psi_R6 - psi_R7| at the 233 x values + the R7 control change`, then used as if it were an error bound on the distance between R7 and the true continuum solution: `FLOOR_NOT_DETECTED if E_L3 - E_L4 > s_3 + s_4 + 2 u_ref and E_L4 - E_L5 > s_4 + s_5 + 2 u_ref`. This let R6/R7's own (possibly shared) discretization error stand in for a real bound, and let R7-vs-L5 closeness alone assert "no floor."

**After (Rev.2 section 8):** `A67(M)` (R6 vs R7, renamed `observed_reference_refinement_change`) and `G_L(M)` (level L vs R7, renamed `observed_reference_gap`) are reported as observed numbers only, never as bounds. States renamed to match their actual evidentiary weight: `REFERENCE_1D_UNUSABLE`, `REFERENCE_AGREEMENT_OBSERVED` (L5 agrees with R7 within the reference's own observed variability — explicitly not "floor absent"), `OUTER_FLOOR_SUSPECTED` (2D-2D keeps changing but stops approaching the 1D reference — named as a candidate for EITHER the fixed outer grid OR a genuine 2D/1D model difference, never narrowed to one cause), `REFERENCE_INCONCLUSIVE`. The physical-equivalence argument (no contact equation at y = 0 / y = -5 therefore the 1D solution equals the 2D continuum solution) is now explicitly labelled `CONDITIONAL`: the fact that no contact equation is registered there, and that no mesh edge crosses those lines, is confirmed structurally, but that this numerically realizes an exact homogeneous Neumann condition is not confirmed from the DEVSIM manual or installed source read this session. The Gauss-law diagnostic (Defect 4) is explicitly noted as not proving zero normal flux either.

## Defect 4 — Gauss residual reconstructed independently instead of using DEVSIM's real assembled models; unjustified hard-gate thresholds

**Before (Rev.1 section 6):** `r_i = sum ... eps (psi_i - psi_j)/L_ij x EC_ij - q (p_i - n_i + NetDoping_i) x NV_i`, built from separately-queried Donors/Acceptors/NetDoping and re-derived carrier densities, not from DEVSIM's own `PotentialIntrinsicCharge`/`PotentialEdgeFlux` node/edge models. `max r_i/s_i <= 1e-3` (correct) and `>= 0.1` (three wrong variants) were proposed as a hard `CONSISTENCY_FAIL` gate with no independent derivation.

**After (Rev.2 section 7):** The primary residual is built directly from DEVSIM's real assembled `PotentialIntrinsicCharge` (node model) and `PotentialEdgeFlux` (edge model), reading each edge's `node_index@n0`/`node_index@n1` to assign the per-node sign explicitly (`+1` at n0, `-1` at n1) — stated as the hypothesis being tested, not a manual-confirmed fact, exactly mirrored by the existing "sign flipped" wrong-variant. The externally-reconstructed version (Donors/Acceptors/NetDoping + IntrinsicElectrons/IntrinsicHoles, this batch's own `exp()`/subtraction) is kept, but only as a SECONDARY diagnostic comparing this batch's reconstruction against DEVSIM's live, Kahan-summed values — a floating-point-consistency check, not a duplicate physics check. Node-selection bookkeeping (`n_selected`, `n_selected_on_x0`, `n_selected_on_boundary`) is added so an empty or non-representative selection cannot pass silently (`ASSEMBLY_RESIDUAL_SELECTION_DEGENERATE`). Because no result-independent derivation for the `1e-3`/`0.1` thresholds was found this session, the whole check is downgraded to `ASSEMBLY_RECONSTRUCTION_DIAGNOSTIC_ONLY`: it is reported, it never triggers `CONSISTENCY_FAIL`, and it never supports declaring `CONSISTENCY_PASS` or any physics approval. `IntrinsicCharge`, `PotentialIntrinsicCharge` and `PotentialEdgeFlux` were added to the saved raw arrays (section 6.6), which also now states explicitly that every Potential-derived quantity is queried in one batch immediately after a given solve call and the P-state and C-state batches are never mixed in one calculation.

## Assumptions still unverified, carried forward explicitly (not resolved by this revision)

1. The n0/n1 flux-direction sign convention assumed for the Gauss-law reconstruction (`+1` at n0, `-1` at n1) is a hypothesis to be tested against real per-edge data once solved — not confirmed by the DEVSIM manual text located this session.
2. Whether "no contact equation at y = 0 / y = -5" numerically realizes an exact homogeneous Neumann condition (the 1D-2D continuum-equivalence argument of section 8) is `CONDITIONAL` — confirmed only structurally (no edge crosses that boundary), not from an explicit DEVSIM documentation statement.
3. The Gauss-law reconstruction's specific numeric thresholds (`1e-3`, `0.1`) have no independent derivation and remain diagnostic-only; a future batch could derive a real bound from DEVSIM's own per-equation residual figures, but that derivation was not attempted here (it would need its own PLAN before any result).
4. R6 and R7 (the 1D references) may share common discretization error with each other; their mutual agreement (`A67`) is reported but is not evidence about their distance to the true continuum solution.

## Verification performed this session (before committing Rev.2)

* Re-read `simple_physics.py:144-186` directly to confirm `PotentialIntrinsicCharge`/`PotentialEdgeFlux` are the actual
  assembled models (unchanged from Rev.1's own citation, reused here for the residual formula itself rather than just
  cited in the evidence table).
* Re-ran the four Defect-1 synthetic cases with a standalone Python script (not committed, printed in the final chat
  report) against the exact inequalities of PLAN section 3/9; all four matched the table in section 4.
* No DEVSIM, no ViennaPS, no network calls beyond what Rev.1 already fetched (no new source reading was needed for the
  DEVSIM manual citation; Defect 4's addition reuses row 5/6 of section 1, already fetched and hashed in Rev.1).

# Rev.3 — pre-execution corrections from the conditional approval of Rev.2

Made before any E6B code, profile, request or DEVSIM execution. Rev.1 and Rev.2 hashes above are historical and kept.
Only the four items below were changed; nothing else in `PLAN.md` was altered except its header (Rev number and the two
historical hashes) and the one "Always attached" line of section 9 that named the renamed diagnostic states.

## A — Gauss residual reported as an absolute value (section 7)
**Before:** `max_i R_i / s_i` (signed), for the correct assembly and the three wrong variants.
**After:** `rho_i(v) = |R_i(v)| / s_i`, `max_i rho_i(v)` for all four variants, evaluated on one and the same eligible
set E and divided by the same (correct-assembly) `s_i`, so a large negative residual cannot be hidden by a signed maximum.

## B — contact nodes excluded; explicit invalid/degenerate states (section 7)
**Before:** eligible = every node with `s_i >= 1e-3 * max(s)`; one umbrella flag `ASSEMBLY_RESIDUAL_SELECTION_DEGENERATE`
for empty selection or no x = 0 / non-contact boundary representative.
**After:** E = non-contact nodes only (all nodes of `Si_xmin` and `Si_xmax` excluded, and `max(s)` taken over non-contact
nodes only); contact-node `R_i`, `s_i`, `rho_i(v)` saved in a separate `contact_residual_diagnostic` block, never mixed into
a bulk ratio. Separate states: `DIAG_INVALID_MAX_S_ZERO`, `DIAG_INVALID_NONFINITE`, `DIAG_INVALID_NO_ELIGIBLE_NODES`
(ratios stored as `null` + status; no division by zero, no maximum of an empty array, never `0` or a pass) and
`DIAG_DEGENERATE_NO_X0_REPRESENTATIVE`, `DIAG_DEGENERATE_NO_TOP_REPRESENTATIVE`, `DIAG_DEGENERATE_NO_BOTTOM_REPRESENTATIVE`
(ratios stored with flags). The diagnostic stays `ASSEMBLY_RECONSTRUCTION_DIAGNOSTIC_ONLY`, not a physics gate.

## C — withdrawal of "a 1D potential solves the same discretized equations" (section 8)
**Before:** "so a y-independent (1D) potential solves the same discretized equations PROVIDED the top/bottom boundaries
impose zero normal flux."
**After:** the sentence is withdrawn. Only a continuum statement is kept (x-only doping, full-height y-independent
contacts, zero normal field on top/bottom => the continuum problem reduces to 1D), still `CONDITIONAL`. The PLAN now says
explicitly that the 1D and 2D finite-volume systems are different discretizations of different meshes whose rows,
integration weights, truncation error and rounding are not asserted equal or related by a bound, and that R6/R7 are
independently built reference discretizations compared by observation, neither the exact solution nor an error bound.

## D — `OUTER_FLOOR_SUSPECTED` condition and reference-state precedence (section 8)
**Before:** "`D34` and `D45` both exceed their own noise threshold (i.e. a genuine 2D-2D refinement trend)" while
`G_L4`, `G_L5` "do NOT shrink ... by more than `S_R7`"; `REFERENCE_AGREEMENT_OBSERVED` and `REFERENCE_INCONCLUSIVE`
overlapped ("comparable to or larger than" is not a formula).
**After:** `T(M)` = the core metric M is `trend observed` in section 9 (all three section-3 inequalities, valid controls,
converged primaries). Formulas: `V(M) = A67(M) + S_R7(M)`, `Delta_G(M) = G_L4(M) - G_L5(M)`, `W(M) = S4(M) + S5(M) +
2 S_R7(M)`. Precedence, first match wins: (1) `REFERENCE_1D_UNUSABLE`; (2) `REFERENCE_INCONCLUSIVE` if not `T(M)`;
(3) `REFERENCE_AGREEMENT_OBSERVED` if `G_L5 <= V`; (4) `OUTER_FLOOR_SUSPECTED` if `T(M)`, `G_L5 > V`, `Delta_G <= W`;
(5) `REFERENCE_INCONCLUSIVE` otherwise. `OUTER_FLOOR_SUSPECTED` records only the observation and lists the candidates it
cannot separate; it never names the fixed outer mesh as the cause. No new numeric tolerance was needed (every term is a
sum of already-defined observed values), so no state was lowered on that account.

## Still unverified (unchanged by Rev.3)
The four items listed under Rev.2, plus: whether `W(M)` counting `S_R7` twice is the tightest defensible sum (it is the
conservative construction, not a derived bound).
