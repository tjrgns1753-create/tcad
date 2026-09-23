# Tier 1-2 Rev.3.1 — LOCOS pad-oxide positive-time resolution

Date: 2026-09-18
Scope: audit only; no oxidation production change, no full regression, no commit

## Verdict

An explicit 20 nm LOCOS pad oxide is physically resolved at 10 nm and 20 nm
grid spacing for the tested 1000 C dry-oxidation, 0.5 h recipe.  The 10 nm and
20 nm results conserve oxide/consumed-Si thickness at 2.2700 and agree with the
Deal–Grove final thickness within 1.01% and 2.06%, respectively.

At 50 nm grid spacing, ViennaPS reports successful completion of one substep
and 0.5 h simulated, but the oxide does not grow and Si consumption is exactly
zero.  Its final physical oxide thickness remains 20.000 nm instead of the
37.973 nm Deal–Grove prediction.  This is a silent resolution failure, not a
supported calculation.

Consequently:

- the existing grid-dependent 50 nm pad-oxide floor is not a physical fix;
- simply replacing that floor with 20 nm while keeping a 50 nm grid would
  replace one wrong result with a silent no-growth result;
- the tested coarse condition must be fail-closed/`UNSUPPORTED_BY_MODEL`, or
  the user must select a grid that resolves the requested physical layer;
- the three cases establish a safe result for these tested values only.  They
  do not prove a universal minimum cells-per-layer threshold.

## Method

The audit script
`investigate_rev3_1_locos_positive_time.py` invokes the production
`LocosOxidation.run()` path with installed ViennaPS 4.6.2.  Each grid is run in
a separate Python process.  The only instrumentation is a context-managed
replacement of `vps.Process` which exports the domain immediately before and
after the real `Process.apply()` call, then restores the original class.

Common physical recipe:

- explicit `pad_oxide_thickness_um = 0.02`;
- dry O2, 1000 C, 0.5 h;
- identical 3 um x 2 um domain, mask, and opening;
- field measurement at x=0, the center of the exposed opening;
- LOCOS-aware `save_locos_volume_mesh()` export;
- grid spacing varied only across 0.01, 0.02, and 0.05 um.

The first attempted invocation stopped before importing the project because
the audit script initially selected the parent directory rather than the
repository root.  No ViennaPS process ran in that attempt.  The path was fixed
before any result was accepted.

## Measurement definition correction

For a LOCOS wrapped stack, the exported SiO2 tag's lower y bound is not a
reliable post-advection Si/SiO2 interface.  At grid=0.02, the oxide tag still
begins at y=0 while the exported Si top moves to y=-0.00826238 um.  Treating
the oxide tag's own y-span as physical thickness would therefore omit consumed
silicon and produce a false conservation ratio of 1.27.

All authoritative values below use same-x physical boundaries:

```
t_ox(x)       = y_oxide_top(x) - y_Si_top(x)
oxide_growth  = t_ox,after - t_ox,before
Si_consumed   = y_Si_top,before - y_Si_top,after
```

This definition satisfies the exact geometric identity
`oxide_growth = ambient_surface_displacement + Si_consumed` with zero residual
in all three runs.  The raw oxide-tag span remains in each JSON only as a
diagnostic field.

## Real ViennaPS results

Deal–Grove coefficients parsed independently from every native solver log:
`B=0.010439 um^2/hr`, `B/A=0.044911 um/hr`.  With initial oxide
`x_i=0.02 um` and `t=0.5 hr`,

```
x_f^2 + A*x_f = x_i^2 + A*x_i + B*t,
A = B/(B/A)
```

gives `x_f=0.03797284535 um`.

| grid (um) | substeps / simulated time | final physical oxide (um) | oxide growth (um) | Si consumed (um) | growth / consumed | error vs Deal–Grove | verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.01 | 3 / 0.5 h | 0.03835645039 | 0.01835645083 | 0.00808654260 | 2.26999989 | +1.0102% | physically consistent |
| 0.02 | 2 / 0.5 h | 0.03875561617 | 0.01875561662 | 0.00826238282 | 2.27000092 | +2.0614% | physically consistent |
| 0.05 | 1 / 0.5 h | 0.01999999769 | -1.86e-9 | 0.0 | undefined | -47.3308% | silent no-growth; unsupported |

The 10 nm and 20 nm final thicknesses differ by 0.00039917 um, approximately
1.04% of the 10 nm result, and both independently satisfy the physical
conservation ratio.  The 50 nm result is not on that convergent trend.

Machine-readable results and unedited native logs:

- `rev3_1_results/rev3_1_grid_0p010.json`
- `rev3_1_results/rev3_1_grid_0p020.json`
- `rev3_1_results/rev3_1_grid_0p050.json`
- `rev3_1_results/grid_0p010_native.log`
- `rev3_1_results/grid_0p020_native.log`
- `rev3_1_results/grid_0p050_native.log`

## M5-C authoritative evidence correction

`results_v3_locos.json` no longer exposes the plain-export-derived
0.549671 um value as an authoritative seed thickness:

- `seed_created_thickness_um = null`;
- `quantitative_geometry_status = "UNTRUSTED_EXPORT"`;
- the old number remains only under `raw_untrusted_measurement`;
- the trusted M5-C evidence is limited to native facts: SiO2 is absent before
  `apply()`, present afterward, and zero-time geometry identity is therefore
  false.

## Fresh LOCOS contract

- `LocosOxidation.run(inherited_domain=None)` is a composite scenario/fixture
  builder: it constructs Si, pad oxide, and mask before invoking oxidation.
  It has no input wafer, so public-step identity is not defined (N/A).
- An oxidation transition in an arbitrary user-controlled process chain acts
  on inherited geometry.  For that transition, `time_hours=0` must be strict
  geometry identity.
- A future fix must not treat implicit fresh-fixture construction and an
  inherited physical oxidation transition as the same semantic operation.

## Repository state and scope wording

The accurate statement is: **this Tier 1-2 audit did not modify
`tcad/process/oxidation/thermal.py` or `tcad/process/oxidation/locos.py`.**
Other production files already have uncommitted WaferState/Tier 1-1 changes,
so it would be inaccurate to claim that the entire production tree is clean.

No production implementation, full regression, or commit was performed in
Rev.3.1.
