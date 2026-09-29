# Batch 7H-E6C ERRATUM 1 (wording only; `REPORT.md`, its verdict and all raw evidence are unchanged)

E6C's verdict `INITIALIZATION_ROBUST_LOCAL_REFINEMENT_TREND_ONLY` stands and is not promoted to 2D continuum convergence or production
step-junction support.

`REPORT.md` sections 2 and 7 call the different final "absolute error" of the P runs (~1e-17) and the Q runs (2.5e-8 to 8.9e-8) "observed but
unexplained". That statement stays true, but it must be read together with what the quantity is. The DEVSIM Manual 2.10.0 command
reference for `devsim.solve` (https://devsim.net/CommandReference.html, page sha256
`163e4dd2bb8e8012cb7dd4ad8f9ed0ce56a57b617329eb5774f624822f5dd8fd`, downloaded 2026-09-28) defines `absolute_error` as "Required update
norm in the solve" and `relative_error` as "Required relative update in the solve". The per-iteration and final `absolute_error` /
`relative_error` values in the `info` result are therefore measures of the Newton **update**, not the final Poisson (physical) residual and not
a bound on the error of the solution. The P/Q difference in the reported final absolute error is a difference in the size of the last update of
two different iteration histories; why they differ remains undetermined, and neither value is used as a residual or an error bound.
