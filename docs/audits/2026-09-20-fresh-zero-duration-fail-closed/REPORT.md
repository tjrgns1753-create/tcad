# Fresh zero-duration / unsupported oxidation must not invent geometry (2026-09-20)

Scope: only the fresh-domain zero-duration and unsupported oxidation paths and what WaferState/GUI do with them. No test
migration, no wrapped-LOCOS/DevSim interface change, no full regression, no commit.

Two rounds:
1. Round 1: a fresh zero-duration step no longer builds a pad oxide/mask, and a fresh UNSUPPORTED step no longer builds a Mask.
2. Round 2 (this file's contract, after Codex review): a fresh zero-duration step is a **materialization**, not an **identity**.

## 1. Physical finding (round 1)

Measured in `../2026-09-20-explicit-oxide-fixture-spike/raw/exp7_fresh_zero_duration.json` (PRE-FIX):

| path (grid 0.05) | materials before fix | `state_transition` before | Oxidation() / seed setter / Process.apply / `_build_locos_geometry` before |
|---|---|---|---|
| LOCOS fresh t=0 | Mask, Si, **SiO2** | None | 1 / 0 / 0 / 1 |
| THERMAL fresh t=0 | Si | None | **1 / 1** / 0 / 0 |
| LOCOS fresh t=0.5 (UNSUPPORTED) | Si, **Mask** | unsupported | 0 / 0 / 0 / 0 |
| THERMAL fresh t=0.5 (UNSUPPORTED) | Si | unsupported | 0 / 0 / 0 / 0 |

## 2. Why the round-1 "fresh identity" was wrong (round 2)

Round 1 reported a fresh zero-duration result as `{"kind":"identity", ..., "inherited": False}` and `advance_wafer_state` returned
`prior_state` for it. But `inherited=False` means the backend was NOT handed the prior domain: it built a new virgin-Si domain from
the recipe. Nothing proves the prior WaferState (its bounds, its material instances and lineage, its dopant, its grid) describes that
new mesh. A prior state with a different substrate, an added SiN/SiO2 layer, an etch/deposition history, or a dopant on an instance
that the fresh mesh does not contain was preserved verbatim (`active_attachments_after: 1`, `dopant_query_after: 1e17`) -- a state
that no longer matched its mesh. The round-1 audit script recorded exactly that as the correct answer because it forced an arbitrary
doped prior into every path. Those data are kept, marked `SUPERSEDED_CONTRACT_BUG`, and re-measured.

## 3. Contract implemented

| step | backend result | transition | WaferState |
|---|---|---|---|
| inherited, t=0 | input domain object returned | `{"kind":"identity","reason":"zero_duration_oxidation","category":"oxidation","inherited":True}` | `out is prior_state` (attachments, queries, grid all intact) |
| fresh, t=0 | virgin Si only (no SiO2/Mask/pad/seed) | `{"kind":"materialization", ..., "inherited":False, "initial_geometry":{"material":"Si","bounds_um":[-x/2,x/2,-depth,0],"material_instance_id":"si#substrate","grid_delta_um":g}}` | no prior -> MODELLED initial state (1 Si cell, 0 attachments, undoped query 0.0, only initial-geometry provenance); prior -> **fail-closed** (never `is prior`, even for equal bounds) |
| fresh, t>0 | virgin Si only | `unsupported` | fail-closed |
| inherited, t>0 | input domain untouched | `unsupported` | fail-closed |

- Bounds come from `x_extent_um` and `silicon_depth_um` only (never a mesh, never `y_extent_um`, never the exporter floor). A recipe that cannot
  state `x_extent_um`, `silicon_depth_um`, `grid_delta_um` makes a fresh zero-duration step raise `ValueError` before any geometry is built.
- The schema is strict (`parse_fresh_zero_duration_materialization`): exact key sets, kind/reason/category, `inherited is False`, material exactly
  "Si", exact substrate instance id, four finite real bounds with positive area, finite positive grid. `inherited_identity` and
  `fresh materialization` predicates are separate and mutually exclusive (`is_canonical_inherited_zero_duration_identity`,
  `is_canonical_fresh_zero_duration_materialization`); the old both-True `is_canonical_zero_duration_identity` is removed.
- GUI: the same two predicates decide wording and state; a fresh step with a prior WaferState logs `CONTINUITY NOT PROVEN ... nothing was preserved`.
- RUN PROCESS FLOW: counts physical changes vs zero-duration materializations/identities from each step's own transition;
  `wafer.processed` / `process_stage = flow_done` are earned only by physical changes; a zero-duration-only flow prints
  `FLOW FINISHED: 0 physical process change(s), N zero-duration materialization(s), M zero-duration identity step(s)`; an all-real flow keeps
  `PROCESS FLOW COMPLETE`; the unsupported flow-stop contract is unchanged.

Everything after the `duration > 0` gate in `ThermalOxidation.run` / `LocosOxidation.run` is unreachable and left untouched.

## 4. Evidence

- `scripts/eight_paths.py` -> `raw/eight_paths_v2.json`, `raw/eight_paths_v2.stdout.txt`: 8 fresh zero-duration paths (2 models x 4 prior variants),
  2 inherited zero-duration, 4 positive-time; counted (not trapped) calls; cells/bounds/lifecycle, attachments, ledger, queries.
- `raw/eight_paths.json.SUPERSEDED_CONTRACT_BUG.md` marks the round-1 data (`raw/eight_paths.json`, `.stdout.txt`, `scripts/eight_paths_SUPERSEDED_CONTRACT_BUG.py`),
  which are unchanged.
- Mutation check: re-introducing the old "any zero-duration dict preserves prior_state" semantics makes tests C, D, E, G fail.
- `raw/spike_REPORT_correction.diff`: corrections to the explicit-oxide spike REPORT.

## 5. Not done / open

- Full regression, the 17-test migration, the wrapped-LOCOS DevSim interface, `import_process_result` silently dropping interface pairs, the contactMode helper, exporter offset.
- `test_gui_headless_no_modal_hang_real.py` (#4) still fails as before (positive-time oxidation dependency); it is a migration target.
- After a fresh-materialization fail-closed, the prior cells stay in the state as UNRESOLVED and the new Si is NOT added to it, so a device
  measurement needs a new explicit `initialize`/doping on a known wafer -- deliberate (no invented continuity), but a user-visible consequence.
