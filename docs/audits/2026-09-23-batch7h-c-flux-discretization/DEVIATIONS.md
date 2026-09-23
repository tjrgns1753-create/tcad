# Deviations from the pre-registration (REPORT_DRAFT.md / fixtures_7hc.json)

1. **Solver stopping rule** (not a comparison tolerance). Registered: `absolute_error=1e-30, relative_error=1e-13,
   maximum_iterations=20, solver_type=direct`. The first registered solve (M2, Laplace, E1) reached
   RelError 1.6e-15 / AbsError 5.6e-16 at iteration 1 and then stalled at the rounding floor
   RelError 5.32e-17 / AbsError 4.22e-17 for every later iteration, ending in "Convergence failure!" because
   DEVSIM requires both criteria. A non-fixture 5-node probe had reached exactly 0, which is why 1e-30 was chosen.
   Changed to `absolute_error=1e-12` (relative_error 1e-13 and all comparison tolerances EXACT_V, EXACT_I_REL,
   SIGNIFICANT_REL, WEIGHT_REL unchanged). This only lets DEVSIM stop after the solution is already converged to
   the rounding floor; it cannot relax any result comparison. No registered result had been computed before the
   change (the failed solve produced no solution).
