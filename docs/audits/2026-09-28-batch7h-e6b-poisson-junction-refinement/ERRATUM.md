# Batch 7H-E6B ERRATUM 1 (wording only; `REPORT.md`, its verdict and all raw evidence are unchanged)

Written before Batch 7H-E6C. E6B's verdict `SOLVER_CONTROL_INVALID` stands, `S3/S4/S5` remain invalid and are NOT reclassified
as 0, and the workflow status `PASS` (`summary.json`, run 36527372624) is a process status, not a physics approval.

## Corrected wording
`REPORT.md` section 2 says the control criterion "was unreachable for this system" and section 7 that the relative-error target
"is not reachable". Those phrases claim more than the evidence supports. What the raw records show is narrower:

* under E6B's settings (`absolute_error 1e-12`, `relative_error 1e-12`, `maximum_iterations 10`, started from the converged
  primary state) none of the five control solves reported `converged: true` within 10 iterations;
* in each of them the absolute error was already about 5e-17 while the device relative error stayed between about 5e-10 and 5e-7
  and oscillated, and in every 2D level the C-state arrays are bit-identical to the P-state arrays;
* whether a tighter tolerance is reachable with more iterations, another initial state, another solver setting, or never, was
  **not tested**, and the root cause of the stall is **not determined**. The resemblance to the 7H-D1 J0 relative-error
  oscillation recorded in the 7H-E5 PLAN is a resemblance, not a finding.

Nothing else in `REPORT.md` is altered: the raw numbers, the fail-closed classification and the statement that no trend is
claimed all remain as written.
