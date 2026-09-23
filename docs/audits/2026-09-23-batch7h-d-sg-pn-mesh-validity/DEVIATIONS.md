# Deviations from the pre-registration (data/prereg_sha256.txt, 09:06:34 UTC)

1. **Solver stopping rule (not a comparison tolerance).** Registered: Poisson abs 1e-10 / rel 1e-10; DD abs 1e30 /
   rel 1e-10. The first registered solves (1D reference, all four dx) did not stop: the Poisson Newton iterates reached
   AbsError 5.6e-17 V (machine floor) at iteration 11 and then stayed there, while the device RelError oscillated
   between 3e-8 and 1.7e-7 for the remaining iterations (log: dx = 0.01 um). The reason is structural: the exact
   solution of the symmetric junction is psi = 0 V at the x = 0 node, so a relative update criterion there is
   (rounding noise)/(~0) and cannot reach 1e-10. DEVSIM requires both criteria, so every solve ended in
   "Convergence failure" with a converged solution.
   Changed (before any registered result was computed; the failed runs produced no accepted result):
   Poisson abs 1e-10 V (unchanged) / rel 1e-6; DD abs 1e30 (unchanged) / rel 1e-6; iterations 50 (unchanged).
   Every comparison tolerance in fixed_physics.json is unchanged. The final Device AbsError / RelError of every
   solve is recorded from DEVSIM's own log so the actual convergence level is visible.
