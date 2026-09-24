# Batch 7H-D4 interpretation ERRATUM

Written after Codex's interim review, before the D4 remote results were read. `PLAN.md`, `PLAN.sha256`, the analyzer
(`analyze_d4.py`), its pinned thresholds and the raw data are NOT changed. The registered verdicts are computed and
reported exactly as registered; this erratum only corrects how they may be interpreted.

## 1. The 2e-10 node-state threshold is a comparison criterion, not an error bound
PLAN section 5 argued: "each accepted state lies within one final update of the discrete root (quadratic Newton
convergence), so two runs differ by at most 2 x 1e-10 relative per node". This argument does not hold:
* DEVSIM's reported RelError / `relative_error_node` is an update / convergence diagnostic of the last Newton step.
  It is not a bound on the distance between the accepted state and the true discrete solution.
* Local quadratic convergence of Newton was assumed, not demonstrated in this experiment.
Correct reading: `NODE_TOL_REL = 2e-10` (potential scaled by max |psi|, carriers as |ln ratio|) is an experimental
comparison threshold fixed before the results. A MATCHES / DIFFERS / INCONCLUSIVE node verdict states only whether the two
runs agree within that threshold. It gives no guarantee on the physical or discrete-solution error of either run.

## 2. What differs between P12 and P4
PLAN section 5 wrote that P12 and P4 "differ only in the precision of the Newton linear solve". That is wrong.
Per the DEVSIM manual (section 9.3.2) `extended_solver` concerns the extended-precision matrix for the Newton and linear
solver; Codex's reading of the official description is that it applies to matrix / right-hand-side assembly and error
evaluation while the linear solver itself runs in double precision. D4 does not test which internal stage differs.
Correct statement: P12 (`extended_model` + `extended_equation`) and P4 (additionally `extended_solver`) differ only in the
`extended_solver` flag; its exact internal effect is not established here.

## 3. Global max |psi| normalisation can hide junction-local differences
The registered potential criterion |psi_P12 - psi_P4| <= 2e-10 x max |psi_P4| uses a global scale (~0.42-0.52 V), so a
difference concentrated near the junction, where |psi| is small, is judged against the global scale. The report therefore
adds, as descriptive statistics only (they do not change any registered verdict): the maximum absolute potential difference
and its node coordinates, the same maximum restricted to |x| <= 0.10 um (the region between the inner cuts, which contains the
depletion region of about +-0.07 um), and the maxima / locations of |ln(n_P12/n_P4)| and |ln(p_P12/p_P4)|.

## 4. Scope of any "P12 == P4" result
Agreement between P12 and P4 does not exclude that both runs converged to the same inaccurate discrete solution. The mesh
convergence gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`, the production precision defaults and all PN physical
validity judgements remain unchanged. No new threshold and no additional experiment follow from the D4 results.
