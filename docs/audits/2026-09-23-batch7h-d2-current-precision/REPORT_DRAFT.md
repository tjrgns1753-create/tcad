# Batch 7H-D2 pre-registration (fixed BEFORE the first registered run)

Status carried from 7H-D1: verdict A is **PROVISIONAL**; the contact-current float64 cause is
`HYPOTHESIS_SUPPORTED_BY_ULP_CORRELATION`, not yet confirmed by a controlled intervention.

All run matrices, observables (C0-C3), tolerances, restoration / certification / A / B rules are in
`data/fixed_d2.json`, hashed in `data/prereg_sha256.txt` together with `data/fixtures_d2.json` and every script.

Disclosed before registration (no current or potential metric was read):
* `data/devsim_info.txt`: DEVSIM 2.11.0, extended_precision true, direct_solver mkl_pardiso, math_libraries
  mkl_rt.3.dll; the three extended_* parameters are unset by default ("Cannot find parameter").
* `data/manual/` (fetched from devsim.net, `fetched_utc.txt`): solver section 9.3 (extended precision; Windows x64
  uses boost cpp_bin_float_quad; kahan3/kahan4 use Kahan summation in extended_model mode). No statement about the
  Bernoulli function under extended precision was found in the fetched pages.
* `data/smoke_pre_registration.txt`: flag readback and wall time only (P4 ~4x slower than P0 on M2 h = 0.005 um).
* `data/worker_mechanics_check_pre_registration.txt`: the worker runs end to end (step ok flags, result keys,
  flag readback at start / set / end only).
* h = 0.00125 um fixtures (`data/fixtures_d2.json`, 7H-D1 builder): 64962 nodes / 128160 triangles each; M1 0 obtuse,
  M2 all right, M3 15072 obtuse, 0 Delaunay / boundary-Gabriel violations, 0 negative signed couples or volumes,
  J2 = J1, inventory asymmetry 0.
