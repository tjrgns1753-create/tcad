# Batch 2: test_etch_selectivity_real + test_oxidation_pr_etch_reaches_si_real (2026-09-21)

Scope: exactly these two tests, the test-only helper `tests/integration/_explicit_etch_fixture.py` (reuses Batch 1's
`_explicit_oxide_fixture.py` unchanged), and this directory. No production `tcad/` change, no full regression, no commit.

## Status

* `test_etch_selectivity_real.py`: migrated, PASS (RC=0), sensitivity-checked with three recipe mutants (all caught).
* `test_oxidation_pr_etch_reaches_si_real.py`: migrated; every geometry verdict passes, but the test FAILS (RC=1) on a strict
  comparison of `_log_etch_material_summary()` magnitudes with the real central-core geometry. This is a **production
  diagnostic finding** (below). It is NOT relaxed, NOT worked around, NOT fixed here. Stopped for review.

## Why the originals failed

Both created their oxide with a positive-time oxidation, now UNSUPPORTED_BY_MODEL (fail-closed), so no SiO2 exists
(test 1: `KeyError: 30`, the SiO2 tag; test 2: Si moved 0.0125 um under the "insufficient" budget because nothing covered it).
Independent of that, both measured with methods that this batch replaces: test 1 divided material AREA by the window width and
called it an isotropic vertical depth; test 2 read max(y) over the whole window including the mask-edge nodes (the same
arithmetic as the logger under test).

## Design

Explicit initial Si/SiO2 (`MakePlane`) + explicit test mask (`remask_domain`), provenance DIRECT_EXPLICIT_GEOMETRY, saved once as a
`.vpsd` (sha256 recorded). Every etch loads its OWN copy; each copy is proven equal to the baseline before the etch and the saved
file/a fresh copy are proven pristine afterwards. Region rules (core, protected bands) are derived from window, grid and the
recipe's isotropic reach, never from a result. Verdicts use NATIVE level-set positions at the central core; exported-mesh values
are reported separately (the exporter puts the Si/SiO2 interface a grid-proportional distance above the native level set, and
adding the mask level set doubles it: 0.000249 -> 0.000495 um at grid 0.05, while the native Si/SiO2 level sets moved by 0.0).

## Finding: `_log_etch_material_summary()` reads the mask-edge shoulder

The logger takes max(y) of each material's nodes with `lo <= x <= hi` over the whole open window. The node that attains the
maximum is at x = -1.5, exactly the mask edge (the window boundary), where the profile rises above the flat interior.
Interior of the window: SiO2 top 0.1000 (insufficient), Si top -0.1500 (sufficient); flat to grid resolution over the whole core.

| case | logger says | central core (exported) | native core |
|---|---|---|---|
| insufficient, SiO2 | etched 0.0450 um (top 0.2002 -> 0.1552) | 0.1000 um | 0.1000 um |
| sufficient, Si | etched 0.1268 um (top 0.0005 -> -0.1263) | 0.1505 um | 0.1500 um |

The categorical verdicts happen to be right in these two cases (Si "unchanged (not yet reached)" / Si "etched", SiO2 "fully
cleared"); the reported amounts are 55% and 16% low. The same formula evaluated on the same meshes with the window narrowed to
+/-1.4 um returns the correct 0.1000 / 0.1505 (`raw/logger_shoulder.json`, `logger_formula_vs_window_half_width`), so the boundary
node is the cause. A central etch smaller than the shoulder offset would be reported as "unchanged (not yet reached)".

Evidence: `raw/logger_shoulder.json`, `raw/meshes/{baseline_post_mask_pre_etch,insufficient,sufficient}.vtu`, `raw/logger_shoulder.stdout.txt`,
`scripts/audit_logger_shoulder.py`.

## Files

`raw/BEFORE_*.log` (pre-change failures), `raw/FIRST_RUN_*.log`, `raw/STRICT_RUN_*.log`, `raw/FINAL_*.log` (single, both orders,
Batch 1, capability controls), `raw/geometry_tables.json`, `raw/selectivity_mutants.json`, `raw/logger_shoulder.json`.

## Not done

Full regression; the other 13 migration targets; any production change (logger, isotropic, directional, exporter offset); commit.
