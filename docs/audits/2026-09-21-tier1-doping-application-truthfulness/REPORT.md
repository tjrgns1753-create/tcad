# Tier 1 -- a refused doping application must never be reported as applied

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged; nothing staged, nothing committed).

## Defect (reproduced before the change: `raw/BEFORE_repro.out.txt`)
`TCADApplication.run_doping()` treated "the recipe helper built a temporary `DopingProfile`" as success. On an UNRESOLVED or
LEGACY_UNRESOLVED canonical state (after a refused positive-time LOCOS) `advance_wafer_state` attached nothing (one
`UNSUPPORTED_BY_MODEL` doping event + one unresolved-inventory entry, 0 active attachments), yet `run_doping()` logged
`DOPING APPLIED`, printed the requested number as `net_doping_cm3=...`, replaced `last_doped_result`, appended a success history
entry, switched the viewer to the doping overlay and returned `True`. A reattach with a stale result and no canonical attachment did
the same, and an all-zero request was reported as applied.

## Change (production: `tcad_2d_stagewise.py`, `TCADApplication.run_doping()` only)
`raw`-free summary; the complete unified patch is `BATCH_production_tcad_2d_stagewise.patch`.
* success  = >= 1 NEW active attachment and no new UNSUPPORTED_BY_MODEL event and no new unresolved-inventory entry;
  only then `last_doped_result`, history, `DOPING APPLIED`, doping overlay, notification and `True`;
* refused  = the new state (refusal provenance + ledger) is kept; `last_doped_result`/history/viewer layer untouched;
  `DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL)` log with the inputs labelled `REQUESTED, NOT APPLIED`; `False`;
* reattach = succeeds only when the canonical state holds an active attachment;
* all-zero request = known no-op (`NO DOPING ADDED: all requested concentrations are zero`), state untouched, `False`.

## Evidence
* `raw/BEFORE_repro.out.txt` / `raw/AFTER_repro.out.txt` -- real GUI + real ViennaPS/DevSim, scenarios A/B/C/C2/D/F1/F2.
* `raw/PROBE_partial_application.out.txt` -- every doping kind with donor+acceptor on MODELLED and UNRESOLVED states: no partial
  application (stop condition not triggered).
* `raw/AFTER_TARGET_*`, `raw/AFTER_CONTROL_*`, `raw/AFTER_control_summary.txt`, `raw/IMPACT_*`, `raw/BASELINE_old_production_*`.
* `raw/MUTATION_old_production_vs_new_test.out.txt` -- the new test run against the pre-change `tcad_2d_stagewise.py` fails
  (`refused doping must return False, got True`).
* `scripts/` -- reproduction and probe scripts (read-only with respect to the repository).
* `raw/PREEXISTING_diff_*.patch` -- the dirty diff of the allowed files before this batch (kept separate from this batch's patches).
