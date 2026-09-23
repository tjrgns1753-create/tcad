# Batch 1: test_cad_negative_validation_real + test_pin_placement_validation_real (2026-09-21)

Scope: exactly these two tests, their shared test-only helper `tests/integration/_explicit_oxide_fixture.py`, and this audit directory.
No production `tcad/` change, no full regression, no other migration, no commit.

## Why they failed before

Both built their oxide with a fresh positive-time thermal oxidation (`registry.get("oxidation","thermal")`, `time_hours=0.5`). That is
UNSUPPORTED_BY_MODEL, so the step returns the recipe's virgin Si wafer (no SiO2). The mesh then spans y=[-5.0, 0.0]; the hard-coded
"on SiO2" pin at y=0.19 lies above it, and the classifier answers `outside_mesh` instead of `on_insulator`
(`raw/BEFORE_*.log`). Their purpose was contact/pin classification, not oxidation kinetics.

## Fixture (provenance DIRECT_EXPLICIT_GEOMETRY)

Si half-space (surface y=0, floor = explicit `silicon_depth_um`) + a SiO2 plane over the whole width, `MakePlane(..., top, SiO2, True)`.
Not grown, not deposited. `vps.Oxidation` and `vps.Process` are independently trapped/counted during construction and restored in a `finally`
(negative control: each trap fires and is restored after the exception). No thickness tolerance is asserted; native level-set values and
exported-mesh values are reported separately (`raw/audit_batch1.json`).

## Pins

All four are computed from the exported mesh with edge-ownership code independent of `contact_probe`; nothing is copied from an earlier run
(no 0.19, no -5.0, no -2.5, no x=1000). The helper raises rather than retuning a number when a stack cannot separate the boundaries at the
given tolerance (SiO2 top must be > 2 x tolerance above the interface; bulk point must be > 10 x tolerance from every external edge).

## Evidence files

`raw/BEFORE_*.log` (pre-change failures), `raw/AFTER_*.log` (single + two consecutive rounds), `raw/CONTROL_*.log` (capability controls),
`raw/audit_batch1.json` + `scripts/audit_batch1.py` (requested / native / exported blocks, pins, trap control, AST scan, oxidation-mention list).

## Not done

Full regression; the other 15 migration targets; exporter offset cause; wrapped LOCOS interface; contactMode helper; commit.
