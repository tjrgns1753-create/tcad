# Batch 7H-E3 REPORT: one graded-refinement candidate for the step-junction mesh (audit-only)

**Verdict: `CANDIDATE_REJECTED`** — 3 of 11 pre-registered checks failed: `boundary_bit_identical`,
`resolution_not_coarser_than_S4`, `ratio_within_tau`. The mechanism hypothesis 7H-E2 raised (telescoping windows should
reduce the repeated-green-bisection defect vs. one fixed window applied 4 times) is **strongly supported quantitatively**:
the NodeVolume excess fell from S4's 5.83 % to **0.94 %** (a 6.2x reduction) at **3.1x fewer triangles** (79000 vs 247000)
and effectively the same target resolution (both mesh choices give the same nominal 0.05/16 um spacing) — but the specific
4-ring candidate fixed in `PLAN.md` does not pass the pre-registered bit-for-bit/tolerance bar, for reasons explained below,
and its maximum standing per PLAN section 6 is geometry only. **Not corrected after seeing this result**: none of PLAN's
ring widths, resolution target, or tau formula.

Execution: **remote** (GitHub-hosted Windows runner), run https://github.com/tjrgns1753-create/tcad/actions/runs/36139990927
(request `e3-junction-refinement-candidate-001`), PASS, exit 0, 55.0 s, DEVSIM 2.11.0,
`code_paths_identical_to_review_sha = true`. `devsim.solve` calls: **0** (trapped); devices left: 0. Local work: PLAN
authoring, code reading (`mesh_refine.py`, `mesh_import.py`, `doping_mapping.py`, `wafer_state_v2.py`), the corrected
power-checked control logic + its synthetic test (6/6, local only, no ViennaPS/DEVSIM), and read-only numpy analysis of
already-downloaded 7H-E1/7H-E2 arrays (including a dry-run of the new invariant functions against a *reconstructed proxy*
input, explicitly NOT authoritative — see section 5). Serena MCP: connection failed again at this session's start
("Skipping connection, recent failure cached"); rg + direct file reading used throughout, as in 7H-E1/E2.

## 1. Part one — 7H-E2 verdict correction (no new computation)
Delivered as `docs/audits/2026-09-25-batch7h-e2-nodevolume-first-bad-stage/ERRATUM.md`. Summary: `NO_ORIENTATION_EFFECT`
should be read as **`ORIENTATION_INCONCLUSIVE`** — the control (`C_ccw`) reoriented 0 of 247000 triangles (the mesh was
already 100 % CCW), so comparing an unmodified input to itself is a tautology, not an experiment. The green-split ->
obtuse -> DEVSIM-F3 mechanism itself remains independently supported (stage/lineage/formula cross-checks unaffected by
this flaw). Delaunay-violations=0 (candidate flip) is not the same claim as obtuse=0 (2800 remained). `exact_dual_F2` and
`continuum_N x 25um^2` are two different discrete/continuum references, neither authoritative; the x = 0 junction-node
convention's contribution to their gap is now quantified directly from E1's raw arrays: **0.0625 %** of the continuum
reference (1.5625e8 / 2.5e11 cm^-1), an order of magnitude below the candidate's remaining excess and two orders below
S4's — real, now measured, but not a material driver of either number. 7H-E2's `PLAN.md`, `PLAN.sha256` and every raw
remote artifact (JSON/NPZ/VTU, hash-linked `run.log`/`summary.json`) are untouched (`sha256sum -c` on
`data/start_hashes_e2_tracked.txt`, rc 0; `data/artifact_remote_run_36129959490.sha256`, rc 0, re-verified this session).

The corrected, POWER-CHECKED control logic (`docs/audits/2026-09-25-batch7h-e3-junction-refinement-candidate/scripts/controls_power.py`)
mechanically refuses a cause-exclusion verdict whenever the manipulation changed 0 elements (`CONTROL_NOT_POWERED`), and
provides a manipulation (`reverse_all_windings`) that is powered by construction (`n_changed == n_total` unconditionally,
unlike 7H-E2's `ccw_only` which only touched already-negative triangles). Synthetic test
(`scripts/synthetic_power_test.py`, `data/synthetic_power_results_pre_run.json`): 6/6 cases pass, including the literal
case the correction is about — a null (0-changed) manipulation compared to itself cannot yield `..._NO_EFFECT` regardless
of what the (meaningless) comparison itself reports. This logic was not re-applied to 7H-E2's own remote data (that would
be new computation on a closed batch); it is available for reuse.

## 2. Part two — candidate design and why it is investigated first (PLAN section 0)
Candidate: call the **unmodified, already-in-production** `graded_refine_mesh_near()` (`tcad/device/devsim/mesh_refine.py:189-222`)
with a telescoping window sequence `(0.1, 0.05, 0.025, 0.0125) um` centred on x = 0, instead of `refine_mesh_near()`
(`:157-186`) with one fixed 0.1 um window applied 4 times — exactly what its own docstring says avoids ("the ENTIRE window
gets N halvings regardless of how close to the target position it is"). This function is already used in production for
two OTHER doping kinds (`refine_process_result_for_mos_gate`, `mesh_import.py:275`; `refine_process_result_for_implant_windows`,
`:363`); the step-junction path itself does not call it today, confirmed directly:
`import_process_result()` only reaches the graded branch (`:960-969`) when `auto_refine_from_doping=True`, and the
step-junction measurement call passes `refine_near_um=0.0` with that flag left at its default `False`, taking the
single-window branch at `:979-986` instead (matches 7H-E1's own path table).
Alternatives considered and not chosen for this first experiment: a globally uniform ultra-fine mesh (excluded by PLAN
section 0/8 and by this project's own prior investigation-log finding that it fails to converge affordably); a new
smoothed refinement-density field (no prior validation anywhere in this project); hand-built local re-meshing of the
boundary band (not an already-validated mechanism, more code to audit in one batch).
**Scope, stated before any result**: investigated only for 7H-E1's exact geometry — one planar Si wafer, one axis-aligned
step junction at x = 0. Not claimed to generalize to multi-material interfaces, curved boundaries, multiple junctions, or
non-axis-aligned features.

## 3. Identity and baseline reuse (PLAN sections 1, verified, not assumed)
Regenerated wafer mesh sha256 = `cfae97d4...` = 7H-E1/E2 (equal). S4 was **not** re-imported into DEVSIM this batch — reused
directly from 7H-E2's committed `e2_result.json`/`stage_S4.npz` — and proven to be the SAME S4 with plain numpy only (no
second DEVSIM import): the in-process single-window reproduction's `x * 1e-4` / `y * 1e-4` are bit-equal to 7H-E1's
recorded S4 `x_sha256` / `y_sha256`, and its 247000-triangle list equals `stage_S4.npz`'s DEVSIM-returned element list as a
multiset of sorted vertex triples (same equivalence 7H-E2 registered) — `s4_baseline_reuse.ok: true`.

## 4. Comparison table (S0 / S4 [reused] / E2's exact-flip candidate [reused] / E3 candidate)
Areas in um^2 (E3's own script computed on unscaled micrometre coordinates, confirmed internally consistent — see section 5
note on units); S4/E2-flip areas quoted in the same cm^2 units their own reports used, both equal to the same physical 50 um^2.

| | S0 | S4 (single window, reused) | E2 exact-flip candidate (reused) | **E3 candidate (graded)** |
|---|---|---|---|---|
| nodes / triangles | 20301 / 40000 | 123861 / 247000 | 123861 / 247000 | **39817 / 79000** |
| ratio (sum NodeVolume / exact area) | 1.0 | 1.0582519546022044 | 1.0201660424825372 | **1.0093750000010542** |
| tau | 1.341e-11 | 8.279e-11 | 8.263e-11 | **2.643e-11** |
| excess over area | 0.0 | 0.058252 | 0.020166 | **0.009375** |
| min edge length near junction (um) | - | 0.003124296 (target) | (not remeasured) | **0.003124714** |
| resolution vs. S4 target | - | = | (unchanged mesh) | **coarser by 1.3e-4 relative** (FAIL) |
| acute / right / obtuse | 0/40000/0 | 0/244000/3000 | 200/244000/2800 | **0/76000/3000** |
| min / max angle (deg) | 45.0 / 90.0 | 1.85 / 133.15 | 2.94 / 113.63 | **18.43 / 116.57** |
| exact Delaunay violations | 0 | 200 | 0 | **3000** |
| signed couple / node-volume negatives | 0/0 | 200/200 | 0/0 | **3000/0** |
| DEVSIM EdgeCouple at G1<0 edges | n/a | 0 neg / 200 pos | 0 neg / 0 (none neg) | **0 neg / 3000 pos** |
| donor inventory: DEVSIM NodeVolume (cm^-1) | - | 2.646411e11 | 2.551196e11 | **2.524218e11** |
| donor inventory: same-mesh F2 (cm^-1) | - | 2.500781e11 | 2.500781e11 | **2.500781e11** |
| donor inventory: geometric continuum (cm^-1) | - | 2.5e11 | 2.5e11 | 2.5e11 |
| donor DEVSIM-vs-continuum excess | - | +5.856 % | +2.048 % | **+0.969 %** |
| mesh build + DEVSIM import wall time | - | (part of E2's 258 s S4 step) | (part of E2's 216 s) | **2.0 s + 0.7 s** |

Reading: the candidate has MORE Delaunay violations and MORE negative signed couples than S4 (3000 vs 200) — not fewer —
because the telescoping structure creates **transition bands at every ring boundary** (0.1, 0.05, 0.025, 0.0125 um) rather
than S4's single band at 0.1 um, and 79000 of the candidate's triangles sit inside the finest, most-transitioned region.
But because each individual triangle now typically survives only ONE or TWO green-split generations (vs. up to four,
compounding, at S4's fixed 0.1 um boundary) rather than being repeatedly re-split at the SAME location across all 4 passes,
the RESULTING obtuse angles are milder (max 116.57 deg vs S4's 133.15 deg) and the NodeVolume excess per defect is smaller
— net effect: 6.2x lower total excess despite a similar or larger DEFECT COUNT. DEVSIM's EdgeCouple is, once again,
positive at every one of the 3000 edges the signed prediction called negative (0 negative anywhere) — the same behaviour
7H-E2 found on S4, now confirmed on a structurally different mesh too.

## 5. Why `CANDIDATE_REJECTED` — the three failed checks, precisely
* **`ratio_within_tau`**: 1.0093750000010542 vs tau 2.643e-11 — real, not a rounding artifact; the candidate's own excess
  (0.9375 %) is far above any float-precision budget, exactly as expected from the mechanism (a real geometric shape defect,
  not a precision issue — matches 7H-E2's own finding that the excess equals `sum(F3-F2)` to within tau at every stage;
  here too, `excess_explained_by_F3_within_tau: true`).
* **`resolution_not_coarser_than_S4`**: candidate minimum edge length near the junction is 0.003124714 um vs S4's own
  0.003124296199530363 um — coarser by **4.2e-7 um, 1.3e-4 relative**. Both numbers are effectively the SAME nominal
  spacing (0.05/2^4 = 0.003125 um); the tiny difference comes from which specific edge happens to be shortest in each
  mesh's own green-split geometry (a short sliver edge unique to each mesh's particular defect pattern), not from the
  candidate systematically under-resolving the junction. The check is honest and was fixed before this result was seen;
  it fails by this margin and is reported as a fail, not waived.
* **`boundary_bit_identical`**: candidate has 632 boundary-classified points vs S0/S4's 600 — **32 extra points, 0 lost**
  (verified directly from the raw `.vtu` files: every one of S0's 600 boundary points is present in the candidate; the 32
  new ones are midpoints inserted by `refine_mesh_near`'s own algorithm exactly ON the top (y=0) or bottom (y=-5) domain
  edge near x=0, e.g. (-0.075, -5.0), (-0.075, 0.0)). **This is a genuine flaw in how PLAN section 4 specified the
  invariant, not a defect in the candidate mesh**: the refinement window has no y-restriction, so it necessarily also
  refines triangles touching the top/bottom (non-contact) boundary near the junction — S4 has the identical property (its
  own refinement window also has no y-restriction), but 7H-E2 never registered a "boundary bit-identical" check to catch
  it there, so this was never noticed as an issue before. The only boundary that must stay untouched for physical/contact
  reasons is x = +-5 (`Si_xmin`/`Si_xmax`, the actual contacts) — confirmed 0 points lost or added there in both S0 and the
  candidate. Per this batch's own stop-condition discipline, the pre-registered check is reported exactly as it computed
  (`False`, a real fail against the literal PLAN text) — it is not reinterpreted or loosened after the fact, and the
  overall verdict is `CANDIDATE_REJECTED` regardless of this one check's merits, since `ratio_within_tau` and
  `resolution_not_coarser_than_S4` independently fail on their own terms.

**Local dry-run caveat, disclosed rather than hidden**: before spending remote budget, a local sanity check used
`stage_S0.npz` (7H-E2's DEVSIM-read-back, RENUMBERED S0 arrays) as a stand-in raw input, since the true raw ViennaPS
output cannot be regenerated locally. That proxy's element list turned out to carry DEVSIM's own mixed vertex-winding
convention (20000 positive / 20000 negative, matching the `all_ccw: false` pattern 7H-E1/E2 already explained is a DEVSIM
readback artifact, not a property of the stored mesh) and produced 39500 falsely "inverted" triangles in the dry run —
resolved by re-testing with a consistently-reoriented proxy (0 inverted), and confirmed harmless: the REAL remote run
(genuine `meshio.read()` of the freshly regenerated `.vtu`, never DEVSIM-touched before this candidate's own construction)
shows `n_inverted: 0` in `geometric_invariants` (section above), matching the corrected dry run and not the flawed one. This
dry-run artifact is recorded so a future session does not mistake it for a real defect if re-examining scratch files.

**Units note**: this batch's own `exact_area_cm2` field reports `"50/1"` — computed on raw (un-length-scaled) micrometre
coordinates, giving exactly 50 (um^2, not cm^2, despite the field name inherited from 7H-B/7H-E2's convention). This is
self-consistent within this batch (S0 and the candidate are compared in the SAME units) and does not affect any check —
`exact_area_equal_S0: true` — but the field name is misleading; noted here rather than silently left for a future reader
to misinterpret as cm^2.

## 6. Doping integrals (PLAN section 6, three references kept separate)
Junction-node rule, read directly (not inferred): `doping_mapping.py:864,868` uses DEVSIM's `Donors = ND * step(x-x_j)`,
`Acceptors = NA * step(x_j-x)`; `wafer_state_v2.py:743-744` documents that its OWN independent Python implementation
deliberately mirrors this exact convention ("DEVSIM's own step() convention: at the junction line both are written").
Candidate doping was queried via the real production `WaferStateV2.net_doping_at()` (not a re-derivation) at all 39817
candidate node positions; all finite. Candidate's DEVSIM-integral excess over the geometric continuum (0.969 %, donor and
acceptor separately) closely tracks its NodeVolume ratio excess (0.9375 %), as expected for a roughly uniform-concentration
region — an internal consistency check, not an independent confirmation.

## 7. What this batch does and does not establish
Established: the telescoping-window mechanism hypothesis is directionally correct and quantitatively substantial (6.2x
excess reduction, 3.1x fewer triangles) on this exact geometry; DEVSIM's EdgeCouple is never negative on this mesh either
(0 of 3000 G1-negative-predicted edges); the doping-integral gap tracks the geometric ratio as expected. Not established:
a passing candidate (this one fails 3 pre-registered checks); whether a DIFFERENT ring schedule would pass all checks
(not tried — PLAN fixed one candidate, and retuning after seeing this result is explicitly excluded); electrical accuracy
of any mesh; 2D mesh convergence at any doping level; applicability beyond the single-Si planar-wafer, single-junction
scope. The maximum verdict this batch could have registered, even if every check had passed, was `GEOMETRY_CANDIDATE_ONLY`
— it did not pass, so that cap was never reached.

## 8. No-change confirmation
Production / tests byte-identical to the start of this batch (`data/start_hashes_prod_tests.txt`, rc 0) and to review SHA
`023bcb90` (`git diff --quiet`, rc 0); 7H-E1 and 7H-E2 tracked files unchanged (`data/start_hashes_e1_tracked.txt`,
`data/start_hashes_e2_tracked.txt`, rc 0 each); all pre-existing `docs/audits/` files unchanged
(`data/start_hashes_all_audits.txt`, rc 0); no gate code touched, no precision flag set, no `devsim.solve` call, no full
regression, no GUI run; `origin/claude/waferstate-v2` = `023bcb90...`, `origin/main` = `d60e9aed...`, both unchanged from
the start of this batch.

## Serena investigation
Serena MCP connection failed again at this session's start (`ToolSearch` returned "Skipping connection (recent failure
cached...)"), so rg + direct file reading were used throughout, as in 7H-E1/E2. Target symbols and their exact file:line
locations are cited inline in sections 1-2 and 6 above (`refine_mesh_near`/`graded_refine_mesh_near` in `mesh_refine.py`;
`import_process_result`'s graded/single-window branch selection in `mesh_import.py`; the step() equations in
`doping_mapping.py`; the mirrored convention's docstring in `wafer_state_v2.py`). Callers checked directly:
`refine_process_result_for_mos_gate`/`refine_process_result_for_implant_windows` (the two existing production callers of
`graded_refine_mesh_near`) and the step-junction measurement call chain (confirmed NOT a caller, per section 2). No
production symbol was changed by this batch (0 files under `tcad/`/`tests/` touched); the candidate calls the existing
functions from a new audit script only. Final verdict is based on the raw remote numbers in `e3_result.json`, not on
Serena output (which was unavailable).

## Change diff
New files only (no existing tracked file outside `remote/profiles.py`/`remote/request.json` was modified):
`PLAN.md`, `PLAN.sha256`, `REPORT.md`; `scripts/{run_e3,stage_e3,controls_power,synthetic_power_test}.py`; `data/start_*`,
`data/synthetic_power_results_pre_run.json`, `data/artifact_remote_run_36139990927.sha256`,
`data/remote_run_36139990927/{summary.json,run.log,outputs/e3_out/*}`; plus, in the E2 folder,
`ERRATUM.md` (new file, E2's own PLAN/results/raw artifacts untouched). `remote/profiles.py` gained one new PROFILES entry
(`e3_junction_refinement_candidate`, appended after `e2_nodevolume_first_bad_stage`, same schema as the existing entries);
`remote/request.json`'s `request_id`/`profile`/`note` fields were updated to point at it, as with every prior batch.

## git diff --check
* **Working tree** (after the commit below): clean in both a normal environment and a clean-config environment
  (`GIT_CONFIG_NOSYSTEM=1`, global config `/dev/null`, `core.autocrlf=false`) — rc 0, no output, both environments.
* **This batch's own staged range** (`90200182ec0404bc14eadf7bfb2066fb249e38f3` through the REPORT commit below),
  checked with `git diff --check --cached` before committing, in both environments: **rc 2**, one warning, identical in
  both:
  ```
  docs/audits/2026-09-25-batch7h-e3-junction-refinement-candidate/data/batch_e2_erratum_e3_code.patch:408: trailing whitespace.
  +
  ```
  Cause, checked directly (`awk 'NR==408'` + `cat -A`): line 408 is a unified-diff CONTEXT line (leading space, per the
  diff format) representing a genuinely blank line in `remote/profiles.py` between the `PROFILES` dict's closing brace
  and the `# Global limits` comment — inherent to any diff of that exact hunk, not introduced by this batch and not
  something regenerating the patch file changes. Source files, `REPORT.md` and `PLAN.md` carry no such warning; this is
  the same class of hash/format-inherent warning 7H-E2's own report disclosed rather than editing evidence to silence.

## HEAD and commits
* `55056142afeea20d498742c09d6df67ae327bff5` — E3 PLAN alone.
* `90200182ec0404bc14eadf7bfb2066fb249e38f3` — 7H-E2 ERRATUM + corrected power-checked control logic + synthetic test +
  E3 start-state hashes.
* `001bc11430bf52c1c2fb7175cce1b96d8af1a2a8` — E3 candidate script, profile `e3_junction_refinement_candidate`, request.
* This REPORT's own commit (recorded after push, see the final chat message).

Stopping here for Codex review. No full regression, no PN/DD solve, no production change, no gate release.
