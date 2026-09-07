# TCAD SDD Completions Log (full history)

This file is the archived, full-detail record of every plan completed
through `superpowers:subagent-driven-development` (SDD) in this
project — task-by-task review verdicts, commit ranges, final
whole-branch review findings and fix waves, and the exact regression
numbers measured after each. It exists because the SDD skill's own
per-plan ledger (`.superpowers/sdd/<plan>/progress.md`) is git-ignored
scratch and is deleted once a plan's final review comes back clean —
so, unlike an investigation (which is recorded in
`docs/investigation_log.md`), **this file is often the only surviving
record of what actually happened during an SDD plan's execution.**
Never treat `docs/superpowers/plans/*.md` as a substitute for this
file: a plan file records pre-execution intent (tasks, specs,
constraints) written *before* the work started, not the review
findings, fix commits, or final verification numbers produced while
carrying it out.

**`CLAUDE.md` (project root) is the file read at the start of every
session.** Its own "Completed" section carries only a one-line-per-plan
summary of each SDD plan below, with a pointer here for the full task
list, review findings, fix commits, and verification numbers. Search
this file (e.g. grep for a section heading, matching the plan name
CLAUDE.md's own pointer names) when you need that detail.

Entries below are preserved verbatim from CLAUDE.md at the point each
was migrated out (2026-09-07) — nothing was summarized or trimmed in
the move.

---

### Litho/doping/renderer fixes (SDD, 8 tasks / 4 task groups)
Four fixes shipped via subagent-driven-development, each independently
task-reviewed plus a final whole-branch review (3 Important + 4 Minor
findings, all fixed in one wave): (1) SiO2 no longer silently fails to
block doping — `derive_barrier_covered_windows()` reads the real mesh
and excludes covered windows from `apply_doping()`'s NetDoping
equation; (2) Mask Alignment/Exposure/PR display no longer vanishes
after an unrelated earlier real process — `_litho_pending_since_last_
mesh` tracks whether a real mesh actually reflects the current resist
state; (3) Oxidation→PR→Etch "Si doesn't get etched" is no longer
mis-diagnosed as a physics bug — `_log_etch_material_summary()` logs
real per-material before/after progress in the open window (diagnostic
only, no physics change); (4) all 4 doping kinds now take independent
donor+acceptor input (`DopingRegion` gained donor/acceptor peak-conc
and label-only species fields; `apply_step_junction_doping` untouched
by design). Commits `06720c4..1e043e2` (17 commits). Verified via a
live-monitored full regression run at HEAD: 57 passed / 3 failed, same
3 pre-existing DevSim-convergence failures as before this plan, zero
new failures.

### Electrode/pin + DC sweep (SDD, 12 tasks)
CAD-style electrode/pin placement + coordinate-to-mesh-boundary contact
mapping + voltage probe + DC operating point + DC sweep (Id-Vgs, Id-Vds),
extending the existing DevSim characterization infrastructure rather than
replacing it. Plan: `docs/superpowers/plans/2026-08-27-electrode-pin-dc-sweep.md`.
Each task independently task-reviewed, plus a final whole-branch review (1
Critical + 7 Important findings, one consolidating fix round of 7 commits,
verified by a scoped re-review, 4 residual Minor findings fixed directly).
Commits `d66fff4..383889d` (24 commits total).

Key pieces: `Pin`/`PinPlacementError` data model and coordinate-to-mesh-
boundary resolution (`tcad/mesh/pin.py`, `tcad/device/devsim/contact_probe.py`);
`point_contacts` (free-form pin placement) and `extra_contacts` (a second
axis-extreme contact on one region, enabling a Body contact) added to
`import_process_result` as purely additive, default-off parameters — every
pre-existing caller's behavior is unchanged, confirmed under whole-branch
review; `resolve_pins_to_point_contacts()` as the SINGLE wafer→domain pin
conversion (duplicate check, mesh-derived `x_domain = mesh_min_x + pin.x_um`,
per-pin boundary validation, radius check) shared by the GUI electrode panel
and every test — earlier in the branch the GUI and the tests each had their
own copy, and disagreed on how to compute wafer width when the mesh isn't
symmetrically padded; a real DevSim device leak/lifecycle trap and an
unramped-body-bias bug (`set_bias()` alone never solves — a non-zero
`body_voltage` was silently NEVER applied whenever the swept contact's first
voltage equaled its current bias, the common Vgs[0]=0/Vds[0]=0 case) were
both found and fixed during review, not by design.

**Known limitation, stated explicitly:** the body-effect-on-Vth is NOT
verified anywhere in this project — `test_mosfet_body_bias_real.py`'s check
had to fall back to an Ohm's-law current-ratio prediction because a -0.3V
body bias makes this device's own gate ramp to Vgs=4V fail to converge (this
recipe's implant windows are full-depth, so the body/drain share a resistive
substrate path rather than isolating a threshold-shift regime). Also found,
not yet independently investigated: an identical DevSim solve converges as
the first device built in a process and diverges as the second, despite
correct `delete_device()`+`delete_mesh()` cleanup — see
`docs/investigation_log.md`, "DevSim cross-solve sensitivity".

The end-to-end capstone (`test_device_fabrication_to_dc_sweep_real.py`) uses
TWO separately-built devices, not one: real coordinate-placed contacts
(including Body) need an exposed channel/pad gap that strong gate turn-on
does not tolerate on this device family — confirmed by a real control
comparison, not tuned. Device B (zero gap) reproduces the project's own
already-verified `test_mosfet_id_vgs_real.py` turn-on ratio (2.58e7x vs.
control 2.56e7x, 0.92% apart).

Full regression after the fix round: 69 passed / 3 failed / 0 skipped, same
3 pre-existing DevSim-convergence failures as every prior run this session,
zero new failures.

### State-dependent process physics — Stage A (SDD, 3 tasks)
First stage of a new architectural direction, user-initiated and user-scoped
(not a Claude proposal): make each process step's physics genuinely depend on
the CURRENT wafer state — materials, geometry, doping, thermal history — as
that step's real initial/boundary condition, rather than an interaction-
coefficient lookup keyed by process pairs. Design:
`docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md`
(extends the base `2026-08-25-wafer-state-physics-design.md`). Reference
validation case: a real, cited PN-diode fabrication paper
(arXiv:2407.13705), decomposed step-by-step with an explicit causal
explanation of WHY each prior step's result changes the next step's physics
— used only as physical validation, never as a fixed recipe (THE INVARIANT
still applies in full: no code introduced by this design may special-case
that paper's step order, count, or values).

Stage A itself is pure plumbing, zero physics-behavior change anywhere:
`DopantProfile` (`tcad/physics/dopant_profile.py`) is a lossless,
species/polarity-preserving adapter over the EXISTING `DopingProfile`/
`DopingRegion` shape (already carries independent donor/acceptor/species
per the earlier litho/doping/renderer plan — this stage did not need to
touch `doping_mapping.py`, `mesh_import.py`, or any `apply_*_doping()`
function at all, a real finding from investigation that narrowed the
plan's own original scope before implementation). `WaferState` gained a
`dopant_profiles` field plus `donor_concentration_at`/
`acceptor_concentration_at`/`net_doping_at` (the last always DERIVED, never
stored — process-layer state stays donor/acceptor-separated, DevSim's
NetDoping stays a device-layer concept built exactly once, at import time,
same as before). Verified against real, solved DevSim `NetDoping` node
values for all 4 existing doping kinds at machine-epsilon agreement
(`tests/integration/test_dopant_profile_matches_devsim_real.py`). A final
whole-plan review (Opus) independently cross-checked all 4
`concentration_at` formulas against `doping_mapping.py`'s real DevSim
equation strings line by line and confirmed the zero-behavior-change
guarantee by diff (exactly 5 files touched, none of the protected ones);
its 1 Important finding (`junction_axis` silently assumed to be `"x"` —
harmless today since every in-repo caller passes `"x"`, but a future
`"y"`/`"z"` caller would get a silently wrong number) plus 4 bundled Minor
findings were fixed in one wave and re-reviewed clean. Commits
`ec023f2..586e79e` (9 commits: 2 spec-writing + 3 task + 1 task-level fix
round + 1 final-review fix wave, plus 2 doc-clarification commits from
user review of the spec itself). Full regression: 72 passed / 3 failed /
0 skipped, same 3 pre-existing DevSim-convergence failures as every prior
run this session, zero new failures.

**Explicitly NOT done in this stage** (each stage's own boundary, not an
oversight — see the design doc's §8 migration table): no `DiffusionModel`,
no new doping kind, no metal-contact 3-axis work, no oxidation/etching-
other-models/deposition/metallization wiring into `resolve()` (Stage A
touched only the doping-state half of the design, §2; the base design's
`resolve()`/`INTERACTION_COEFFICIENTS` machinery — already wired for
isotropic etching only, per the earlier Completed entry — is unchanged by
this stage). `thermal_budget` exists on `DopantProfile` but nothing sets it
non-zero yet at the time — Stage B (below) fills this in.

### State-dependent process physics — Stage B (SDD, 8 tasks)

Second stage of the same architectural direction: a literature-cited,
Arrhenius-based thermal-anneal model plus a genuine multi-profile
`DopantProfile[]` state, so a new implant ADDS to whatever already
exists on the wafer instead of overwriting it, and an anneal widens
EVERY existing profile independently through its own species' D(T).
Plan: `docs/superpowers/plans/2026-09-02-state-dependent-physics-stage-b.md`.
Grounded in **Christensen, Radamson, Kuznetsov, Svensson, "Phosphorus
and boron diffusion in silicon under equilibrium conditions", Appl.
Phys. Lett. 82(14), 2254-2256 (2003), DOI 10.1063/1.1566464** — P:
D0=8e-4 cm²/s, Ea=2.74±0.07eV, valid 810-1100°C; B: D0=0.06 cm²/s,
Ea=3.12±0.04eV, valid 810-1050°C — the only new entries in
`INTERACTION_COEFFICIENTS`.

Each of the 8 tasks was independently task-reviewed (baseline behavior,
multi-profile state extension, existing-behavior regression, real
Arrhenius D(T) anneal, dose-conservation proof, independent per-species
anneal proof, multi-profile DevSim NetDoping summation, real GUI
integration), plus a final whole-branch review (Opus: 5 Important + 5
Minor findings, ALL fixed in one consolidated wave — commit `c6e7f40`
— followed by exactly one scoped re-review that independently
re-derived the pre-fix bugs by hand and bit-compared the deduplicated
broadening formula against the old inline math: verdict CLEAN, all 10
findings confirmed ADDRESSED, zero regressions, zero new blocking
issues). One trivial docstring/code mismatch the re-review turned up
was fixed directly (commit `d76fc82`); two non-blocking residual
observations were parked in the plan's own ledger (a term-list-length
invariant that holds by construction but isn't asserted; a
theoretical, practically-unreachable false-positive on the anneal's
UNVERIFIED-citation-window flag).

Key pieces: `tcad/physics/diffusion_model.py` — real per-step D(T) via
`arrhenius_diffusivity()`, cumulative `thermal_budget_contribution()`
(∫D(T)dt, not raw elapsed time — 900°C/10min and 1000°C/10min produce
measurably different broadening), and `anneal_profile()`, the SINGLE
dose-conserving Gaussian-broadening kernel (`sigma_new^2 = sigma_old^2
+ 2*Dt`, `peak_new = peak_old * sigma_old/sigma_new`) — `doping.py`'s
`apply_thermal_anneal()` calls this once per term rather than keeping
its own copy, specifically so the two can never diverge (a final-
review finding, fixed by direct substitution rather than merely
pinning the duplication with a test). `DopingRegion.gaussian_terms`
(`tcad/mesh/interface.py`) holds an ordered list of independent implant
terms; `apply_gaussian_implant_doping(..., existing=...)` appends a new
term rather than overwriting, proven by a real regression test (B
implant → P implant leaves both present, `test_gaussian_implant_terms_
devsim_real.py`, max relative error vs an independently-summed formula
5.139e-14 through REAL solved DevSim nodes — a real bug, second term
silently discarded, was caught and fixed here: pre-fix error was
14.64). NetDoping is summed from ALL terms only at the device layer
(`doping_mapping.py`), never at the process layer. `Resolution.
UNVERIFIED` is surfaced (never silently absorbed) whenever a
user-chosen anneal temperature falls outside a species' own citation
window — both in `ProcessResult.physics_status` and in the GUI's
ANNEAL log line. `DEPTH_EVOLUTION_RESOLUTION = Resolution.
UNSUPPORTED_BY_MODEL` (this model is lateral/x-only) is enforced by a
single hoisted guard covering BOTH the legacy and the new
`gaussian_terms` code paths in `dopant_profile.py` (a final-review
finding: the new path used to skip the guard entirely). The GUI's
Gaussian Implant control now accumulates via `existing=` and a new
ANNEAL panel drives the real chain end-to-end — its own caption states
the x-only scope limit explicitly, and the acceptance test
(`test_gui_thermal_anneal_real.py`, driving the actual production
`_on_thermal_anneal_clicked` handler) proves all 5 required
GUI-observable sensitivities with real numbers: higher anneal
temperature → more broadening, longer anneal time → more broadening,
higher implant dose → higher concentration, B-then-P sequential
implant → both present, and a second anneal → both B AND P widen
again. No new empirical constants, no dopant-dopant interaction
physics, no depth/junction-depth computation was added anywhere.

**Explicitly NOT done in this stage, flagged for separate follow-up**:
`mesh_import.py`'s `_derive_refine_from_doping` (auto mesh refinement)
is still single-term-blind — with `gaussian_terms` set, it derives
refinement rings from only the LAST implant call's peak/position, so
an earlier implant's junction can go under-resolved (including a real
"terms cancel to ≤0, zero refinement at all" failure mode) — exactly
this project's own documented silent-wrong-current failure class (see
Development Rules above). Explicitly ruled out of this plan's scope
during final review; tracked as a standalone follow-up task, not fixed
here. **Still not fixed** after the dopant-state-unification plan below
(explicitly out of that plan's scope too) — and now reachable through
ALL FOUR doping kinds via real cross-step accumulation, not just
Gaussian Implant, since accumulation is no longer Gaussian-specific.

**Superseded by the dopant-state-unification plan (see below):
`gaussian_terms`/`existing=` were retired entirely.** Multi-
profile accumulation moved from a Gaussian-Implant-only,
`DopingRegion`-level list to `WaferState.dopant_profiles`, a real,
cross-step state threaded through every process step (any doping kind,
not just Gaussian) via `advance_wafer_state()`. The `UNVERIFIED`-
citation-window disclosure this stage established was migrated forward
(not dropped) into the new architecture's own `physics_status`
mechanism — see below for the real, load-bearing gap this migration
briefly introduced and how it was found and fixed.

### Dopant-state-unification (SDD, 11 tasks + one final-review fix wave)

User-initiated architectural replacement of Stage A/B's own doping
mechanism, triggered by a real, live-GUI observation ("doping renders as
vertical stripes, not a depth gradient") that led to a much bigger
finding: `ProcessResult.doping` was a per-step declaration, never a real
cross-step state, so process ORDER couldn't genuinely affect a final
device the way it does in a real fab. Design:
`docs/superpowers/specs/2026-09-03-dopant-state-unification-design.md`
(supersedes only §2 of the 2026-08-25 base design). Plan:
`docs/superpowers/plans/2026-09-03-dopant-state-unification.md`. Adds
**THE STATE INVARIANT** as a project-level rule alongside THE INVARIANT
above: `WaferState(t) -> Process Physics -> WaferState(t+1)` — every
physical quantity is either preserved (physical-state preservation, not
verbatim data copy) or transformed by real physics when a step touches
it. Also the direct origin of this file's own "Core Physics Requirement"
section near the top (added during this plan's own brainstorming,
applies project-wide, not just to doping).

Central mechanism: `WaferState.net_doping_at(x, y)` is a real THREE-WAY
dispatch, never a two-way `material != host_material -> 0`: (1) apply
the profile's real `concentration_at()` if `host_material` is currently
EXPOSED at that x (`exposed_material_at()`, a column-max-at-x surface
check); (2) a real, physically-meaningful geometry-gated ZERO if the
responsible category is classified `"removal"` (etching — a fully-
removed column has no exposed material there at all); (3)
`UNSUPPORTED_BY_MODEL` — never a silent zero — for a `"conversion"`
category (oxidation, Si->SiO2) or any UNCLASSIFIED category (the
default, deliberately, per this project's own "never silently decide"
rule). `DopantProfile` became model-agnostic
(species/polarity/concentration_at/host_material/model/model_params/
thermal_history/source); `apply_thermal_anneal()` became a per-model
dispatch registry (`ANNEAL_HANDLERS`, `gaussian_v1` the only registered
model); `advance_wafer_state(prior_state, result, category)` +
`WaferState.from_process_result()` is the real, MESH-FILE-based (not
live-domain — the GUI never holds one across clicks) accumulator; the
device layer's `apply_doping()` writes real per-node DevSim `NetDoping`
via `get_node_model_values`/`set_node_values`, replacing symbolic
per-kind equation strings entirely; the GUI's `self.wafer_state` is now
the real, persistent, cross-step-accumulating attribute every real
process step keeps current
(`_sync_wafer_state_geometry()`, all 8 real geometry-producing sites).

**Three real ViennaPS/DevSim acceptance tests prove the architecture,
strictly x-only (this Gaussian model still ignores `depth_um`
everywhere — no depth/junction-depth claim anywhere in any of them):**
CE-1 (`test_ce1_order_sensitive_geometry_real.py`) — whichever species
existed at a REAL, mesh-verified etched location is erased there
regardless of order, while a different species placed elsewhere
afterward determines that location's final polarity. CE-2
(`test_ce2_oxidation_conversion_unsupported_real.py`) — a real LOCOS
oxidation's Si->SiO2 conversion reports `UNSUPPORTED_BY_MODEL` at a
fixed, mesh-verified coordinate, never a silent 0, while a mask-
protected coordinate elsewhere stays fully computable (the partial-
aggregate contract). CE-3
(`test_ce3_implant_anneal_etch_implant_real.py`) — the full capstone:
implant -> anneal -> etch -> second implant, through the REAL production
GUI's own doping/anneal handlers (not stand-ins), ending in a real
per-node DevSim cross-check (132 real nodes, zero mismatches) confirming
the final device reflects both profiles.

Each of the 11 tasks was independently task-reviewed; 2 needed a fix
round (CE-2's own first draft used a boolean geometry cut with ZERO
detection power for a failed mask — fixed with a real, registered,
fixed-depth etch, verified by a decisive negative-control run that
widened the mask and confirmed the fixed check now genuinely fails
there; Task 8's device-layer rewrite needed 3 fixes: `physics_status`
falsely flagging a profile its own RECOVERY mechanism had just
resolved, zero committed test coverage for that RECOVERY mechanism, and
a real, measured O(nodes×cells×profiles) performance cost). A final
whole-branch review (Opus, 4 passes over the full 14-commit range) found
the deeper, cross-cutting pattern no single task's own review could see:
**the real `UNSUPPORTED_BY_MODEL` disclosure contract was enforced
rigorously INSIDE `WaferState`, then quietly eroded at every boundary it
crossed on the way to a user** — 9 Important findings, one consolidated
fix wave (commit `7854c85`), one scoped re-review (verdict: all findings
addressed; found 2 more Minor issues, one fixed directly — commit
`56c492f` — one parked as genuinely-inert-today debt). Concretely fixed
in the wave: Stage B's own `UNVERIFIED` disclosure had been silently
lost in the schema migration (restored, kept genuinely distinct from
`UNSUPPORTED_BY_MODEL`, never conflated); `apply_doping()`'s RECOVERY
mechanism was silently converting a real oxidation CONVERSION into a
full, unflagged apply (narrowed to only suppress the disclosure for a
genuine REMOVAL, never a conversion); `apply_doping()`'s returned
`physics_status` was discarded by every GUI caller (now captured into
`self.last_physics_status`); the GUI's Implant Windows measurement
(which deliberately still bypasses `WaferState` for its own, separately-
verified 1e20 cm⁻³ convergence solution) now logs which OTHER
accumulated profiles the canvas overlay shows but this specific solve
does not include; the color overlay was painting a genuine geometry-
gated zero (CE-1's own proven real erasure) as n-type blue (now a third,
distinct marker); `net_doping_at()`'s real O(n_profiles) redundancy was
hoisted (11x-77x measured speedup, byte-identical real DevSim values).

Full regression after the fix wave + re-review fix: 89 passed, 4 failed.
3 are the long-documented pre-existing failures below. The 4th,
`test_mosfet_body_bias_real.py`, is NEW to that list but was
independently investigated by BOTH the controller and the fix-wave's own
implementer, in isolation and against the pre-fix-wave commit — passed
cleanly every time except once, embedded in the full sequential suite —
concluded a recurrence of this project's own already-open "DevSim
cross-solve sensitivity" item below, not a regression this plan
introduced. Add it to that same watch list.

**Real, disclosed limitations this plan does NOT solve, carried forward
as OPEN items in CLAUDE.md rather than silently left only in a task's own
SDD report:** `WaferState.exposed_material_at()`'s column-max-at-x surface
check has no y-awareness at all, and — unlike `apply_doping()`, which
has a DevSim-node-membership rescue available for free — the GUI's own
color overlay (Task 10) has NO such rescue, so a leftover, never-
stripped litho Mask (a separate, pre-existing gap) can
make the ENTIRE overlay render as "unsupported" gray-hatch even though
the real device would solve correctly. `WaferState.last_step_category`
is a single FLAT field (the most-recently-run step's category only, not
per-location provenance) — CE-1's own test found this, and the final
review confirmed real GUI usage (etch, then dope elsewhere, then view)
makes it materially more significant than a test-scoping question: a
user gets a real, safe, but information-losing `UNSUPPORTED_BY_MODEL`
for an etched location once ANY later unclassified-category step (e.g.
another doping call) runs, with no way to query the intermediate state
the way CE-1's own test could. Both now carry a real docstring at their
own definition site (`tcad/physics/wafer_state.py`) in addition to this
entry.

Full regression after the fix wave + docstring correction: **80
passed / 3 failed / 0 skipped**, identical 3 pre-existing DevSim-
convergence failures as every prior run this session, zero new
failures.
