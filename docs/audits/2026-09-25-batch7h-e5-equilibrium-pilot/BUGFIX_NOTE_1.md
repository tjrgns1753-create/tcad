# Batch 7H-E5 bugfix note 1 (script bug, not a PLAN/design change)

First remote run (`data/remote_run_36149228558`, request `e5-equilibrium-pilot-001`, commit `3084a3dd99f4b18f982570ce077e53cb49dd164f`)
found two implementation bugs in `scripts/stage_e5.py`, not physics findings. `PLAN.md`/`PLAN.sha256` are unchanged; the
device definitions, doping rule, solver tolerances and observation list are all unchanged. Kept as historical evidence
(not deleted); a second run follows with the fix, same PLAN, same request id pattern.

## Bug 1: `se1.measure()` return value was mis-unpacked
`shadow_e1.py:91` returns `(metrics_dict, raw_state_arrays)`. `stage_e5.py` did `m = se1.measure(...)` and then treated
`m` as the dict directly (`m.get(...)`, `m["psi_contact_V"]`), crashing with `AttributeError: 'tuple' object has no
attribute 'get'` at the very end of `D2D_S0` — AFTER both solve calls had already succeeded
(`e5_D2D_S0.json`: `poisson_converged: true`, `dd_converged: true`, 2 solve calls). The Poisson-only measurement taken
just before the crash is real and worth keeping as a preview: `psi_contact_V` +-0.4768597199126637 V (matches V_bi/2 to
10+ digits against every prior 7H-E batch's own V_bi = 0.95372 V figure), `y_symmetry_max_spread_V` 3.9e-16 (real,
near-machine-precision y-independence), `max_abs_ElectricField_V_per_cm` 358113.0 (matches 7H-E1's own S12 0 V figure
3.581130e5 V/cm to 6 digits). This is evidence the device construction, doping rule and equation setup are correct; the
crash is purely in the post-solve Python bookkeeping. Fix: `m, states = se1.measure(dv, device, contacts)`.

## Bug 2: cleanup only ran on the success path
`stage_e5.py`'s `dv.delete_device()`/`dv.delete_mesh()` calls sat at the end of the `try` block, not in a `finally`. Bug
1's crash skipped them, leaving `e5_d2d_device` (and its mesh) registered. The next run, `D2D_S12`, tried to create a
mesh with the same name and failed outright
(`devsim_py3.error: A mesh already exists with name "e5_d2d_mesh"`), leaving `e5_d2d_device` registered for the
remaining 4 runs too (`e5_result.json`: `"devices_left": ["e5_d2d_device"]` at the very end). `devsim.solve()` has no
device filter — it solves every registered device — so this is the exact leaked-device failure mode CLAUDE.md's own
"Completed" section already documents from an earlier investigation ("Leaking a perfectly healthy uniform device was
enough to turn a converging implant_windows solve into Convergence failure!"). The subsequent 1D runs' reported
`POISSON_NOT_CONVERGED` (D1D_J0 at both precision variants, and — unexpectedly, since D1's own J1 comparison group
always converged in that project's history — D1D_J1 at both variants too) are `psi_range_V: [0.0, 0.0]` at EVERY node:
the Newton iteration made literally zero progress from its zero initial guess, for 100 iterations (D1D_J0) or until an
early stop (D1D_J1, 10 iterations). This is not the oscillating-but-nonzero pattern 7H-D1's own real J0 finding showed
(`REPORT.md`: "absolute update 3.5e-17 V, relative oscillating 5.8e-9 / 6.2e-9"); a flat zero solution most plausibly
means the equation the solver actually assembled was corrupted by the second, unrelated leaked device — not a genuine
result about J0 or J1 convergence at production doping/domain scale. This is recorded as a real but INCONCLUSIVE
observation, not attributed to either device's own physics, and the whole batch is rerun clean to get an answer that is
not confounded this way.

Fix: device/mesh cleanup moved into a `finally` block, keyed off what was actually created (tracked explicitly, not
assumed), so a crash mid-run can never skip cleanup again. A new pre-flight check (`dv.get_device_list()` must be empty
before a run starts) now stops immediately with `STOP_LEAKED_DEVICE_FROM_PRIOR_RUN` if this ever recurs, rather than
letting a leak silently propagate through the remaining runs the way it did here.

## What is NOT changed
Device definitions (D2D/D1D_J0/D1D_J1), the J0/J1 doping rule, solver tolerances (Poisson 1.0/1e-6/100,
DD 1e10/1e-6/100), the precision-variant pair (S0/S12), the observation list, the analytic-reference formula, and every
number in `PLAN.md` (sha256 unchanged, `924395fb86a72658853a9b8ffd7827cdb0ddf6c1473d55609af09764ce8802fa`). This is a
straightforward Python bugfix (an unpacking error and a missing `finally`), not a reinterpretation of any physics or a
change to any pre-registered threshold.
