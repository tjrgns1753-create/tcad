# TCAD 2D Project

## Goal
Build a reliable 2D TCAD process → mesh → DevSim device simulation pipeline.

- 2D only. Do not expand to 3D.
- Prioritize physical correctness over feature count.
- Use actual ViennaPS 4.6.2 / DevSim execution for validation.

## Claude Code environment notes (tooling, not TCAD physics)

Not about this project's physics — carried here only because Claude
has no memory between sessions and this came up once already.

- This runs as a **remote/web Claude Code session** (managed cloud
  container), not a local CLI. Terminal-only slash commands —
  confirmed for `/plugin` and `/reload-plugins` — return "isn't
  available in this environment" here. Not a permissions issue; those
  commands simply aren't supported outside the local CLI.
- Plugin management in this environment goes through the **web UI's
  own plugin browser screen** (the one with a "폴더 선택"/folder-select
  button — it's folder/project-scoped), not slash commands.
- Being LISTED in that browser does not mean a plugin is enabled/active
  for the session — e.g. "Ponytail" (3rd-party, Dietrich Gebert) and
  "Frontend design" (Anthropic) showed up in the list but their skills
  were not available in-session until actually opened and toggled
  on/installed from that screen.
- There is no in-session reload command to pick up a change made in the
  web UI afterward (`/reload-plugins` doesn't exist here) — a browser
  refresh or a new session is the practical way to pick it up.
- A background command's stdout is fully buffered until it exits when
  redirected to a file — a real ViennaPS run can show 0 lines for
  minutes and look hung. Wait for the exit notification, don't kill it.
- A subagent cannot resume itself when its own background job
  completes. Have the controller run expensive commands (full
  regression, real ViennaPS flows) itself and relay the result.

## THE INVARIANT (read before changing anything in the GUI or process layer)

    the user picks a process -> only that process runs
      -> the current wafer is updated -> the user picks the next one

Process order is **never** hardcoded, enforced, or suggested. Any
category — oxidation, lithography, etching, deposition, doping,
metallization — must be selectable and runnable at any moment, on
whatever the wafer currently is.

Concretely, all of these are violations, not just the first:

- a disabled/greyed-out process button;
- a message like "run X first" or "a previous step is required";
- a modal confirm dialog that must be answered before the step will
  run (a confirm is still a block);
- a warning that tells the user which step to run instead — advice
  about sequence is still a prescribed sequence;
- creating a process, mask, resist, material or geometry the user did
  not ask for, or producing a later step's result early;
- a specialized variant reaching into the general path (LOCOS is the
  worked example: it is a sibling option of thermal oxidation, never a
  prerequisite for it, never a default, and its logic must not touch
  the plain path).

When a step has nothing to act on, that is a RESULT, not a refusal:
run it, change nothing, and say so in the log. When something is
physically questionable, note it in the log and run what was asked.

Pinned by `tests/unit/test_gui_no_forced_order_mock.py`, which traps
every blocking messagebox call and fails if one fires.

Do not write example process sequences — in code, in comments, or in
prose. Describe what a step does to the wafer it is given instead.

## Development Rules

- Investigate before modifying production code.
- For suspected problems, first make the smallest experiment that distinguishes hypotheses.
- Never change code just to make a test pass.
- Preserve existing regression tests.
- Do not refactor unrelated code.
- Report uncertainty honestly.
- Work slowly and one subsystem at a time.
- When adding a new DevSim characterization/sweep (a new contact, a new
  measured quantity, a new device region), size any local mesh
  refinement near it from the CONCENTRATION/REGION ACTUALLY BEING
  MEASURED there — not from whatever doping happens to be most
  convenient or already-refined nearby. Concretely: refining an
  interface or contact from the BULK/background doping's Debye length
  is not a safe default merely because it "seems related" — a
  minority-carrier layer that forms there (e.g. a MOS inversion
  channel) reaches carrier densities near the OPPOSITE (peak/implant)
  doping, and sizing the mesh for the wrong concentration can leave the
  very region being measured spanned by a single node. Confirmed to
  produce a 3.8e7x wrong terminal current, silently — no crash, no
  convergence warning, a real-looking device with a plausible-looking
  (monotonic, charge-conserving) I-V curve, and it passed the shipped
  regression test for the same reason. Full case study: search
  `docs/investigation_log.md` for "MOSFET drain current was wrong by
  3.8e7x". Prefer deriving refinement scale from the doping profile
  programmatically (`derive_implant_windows_refinement()` in
  `tcad/device/devsim/mesh_import.py`) over a caller hand-picking one.

Order in which these were BUILT AND VERIFIED by this project. This is
development sequencing only — it is not a process flow, and nothing in
the tool may enforce, assume, or suggest it (see the invariant above):

1. Initial wafer geometry
2. Mask representation
3. Oxidation
4. Etching
5. Isotropic etch
6. Bosch / scalloping
7. Physical benchmarks
8. DevSim electrical validation

## Architecture

Process flow:

Process → ViennaPS → ProcessResult → DevSim → device simulation

Inside ProcessStep.run(): WaferState.query(domain) → resolve(intent,
state) → ResolvedRecipe, between prepare_domain() and the model call.

Process continuity uses explicit instance state:
`ProcessStep(inherited_domain=...)`

Do NOT introduce global/module-level process state.

## Project memory: read `docs/investigation_log.md`

Claude has no memory between sessions. This file (CLAUDE.md) is kept
short on purpose; `docs/investigation_log.md` holds the full,
session-by-session "what was tested / result / what it proves / next
experiment" writeup for every investigation this project has ever run
— root causes, rejected hypotheses, exact numbers. **Before
re-investigating anything that sounds even slightly familiar, grep
that file for it — a past session has very likely already found and
fixed it, and re-discovering it wastes a session.** This CLAUDE.md
only carries: the rules above, a one-line-per-item summary of what's
resolved (below), and full detail on what's still genuinely OPEN
(further below) — since that's what a new session needs to act on
immediately.

## Completed

### Phase 13 / Phase 14
Process flow continuity verified with real ViennaPS 4.6.2 (multi-step
flows correctly inherit previous geometry); ProcessResult → DevSim
verified (oxidation → mesh, oxidation → doping → DevSim, oxidation →
MOS C-V, oxidation → etch → doping → DevSim).

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

### Resolved investigations (summary — full detail in `docs/investigation_log.md`)

Current regression: `tests/run_regression.py` → **57 passed, 3 failed,
0 skipped**, measured on Windows with real ViennaPS 4.6.2 + DevSim.

The 3 failures are pre-existing and were confirmed to fail at a clean
HEAD in a separate git worktree, so they are not caused by any recent
change. All three are DevSim-side, none are geometry/process-flow:
`test_device_lifecycle_repeat_real` (asserts two runs produce byte-equal
I-V points; they differ in the 3rd significant digit at ~1e-27 A, i.e.
solver noise around zero, so the assertion is stricter than the solver
is deterministic), `test_robust_iv_sweep_real` and
`test_gui_measurement_doping_kinds_real` (real `Convergence failure!`,
OPEN item 2 territory).

**Do not quote an earlier "33 passed, 0 failed" from this file as
evidence that the suite is green** — that number was written from a
different environment and was already wrong here before this session
started (it measured 32/5 on first run). Run the suite and read the
number. Note also that `run_regression.py` itself crashes with a
`UnicodeEncodeError` while PRINTING a failing test's traceback under
the Windows cp949 console, which truncates the whole run — use
`PYTHONIOENCODING=utf-8` when running it there.

- **Si floor / mesh export**: raw ViennaPS `saveVolumeMesh()` clips a
  semi-infinite Si region to ~2×gridDelta (narrow-band artifact, not a
  real substrate-depth limit). Fixed with a boolean-intersect "floor"
  applied to a deep-copied domain at export time
  (`save_volume_mesh()`, `tcad/backends/viennaps/io.py`), wired to
  `Wafer.silicon_depth_um` end to end (recipe key, GUI field). Verified
  at gridDelta 0.01–0.2.
- **MakeTrench float sensitivity**: a single float64 ULP in
  `trenchWidth` can silently fail to cut the mask window. Fixed by
  rounding the computed width to 9 decimals in `prepare_domain()`.
- **Oxidation seed thickness**: `vps.Oxidation()`'s default 0.002um
  native-oxide seed stalls below gridDelta. Fixed:
  `setInitialOxideThickness(max(0.002, grid_delta_um))`.
- **DevSim/OpenMP crash**: two OpenMP runtimes double-initializing.
  Fixed with `KMP_DUPLICATE_LIB_OK=TRUE` before `import devsim`.
- **DevSim device/mesh lifecycle**: `delete_device()` alone leaks the
  mesh and corrupts later solves; must also call `delete_mesh()`.
- **LOCOS (Phase 4) segfault**: `OxidationMaskParameters` default
  `contactMode=1` diverges for this project's geometry. Fixed:
  `contactMode=2`, matching the official ViennaPS example.
- **LOCOS mask erosion (~97-99% area loss)**: root cause was mask
  sitting directly on bare Si with no pad-oxide buffer (real LOCOS
  physics requires one). Fixed with pad-oxide-first geometry +
  a custom per-material export (`save_locos_volume_mesh()`) that
  works around a ViennaLS "topmost wins" export limitation which
  otherwise drops the `Si` material entirely for this topology.
- **LOCOS process-flow chaining**: LOCOS geometry didn't satisfy
  ViennaLS `Advect`'s "last level set contains all others"
  precondition (every other geometry in the project does, via
  `MakeTrench`'s own convention). Fixed by re-wrapping the domain
  right after LOCOS's own export, plus a weakref-keyed export-hint
  registry so downstream steps export correctly with zero changes to
  any `ProcessStep.run()` file.
- **LOCOS-on-LOCOS — RESOLVED (was blocked).** A second LOCOS
  oxidation used to hang, then was refused outright. Root cause: a
  LOCOS domain must satisfy two conflicting requirements — Advect
  needs the last level set to contain all others (so the re-wrap
  unions mask into oxide), while `vps.Oxidation()`'s oxide-band
  detection needs a DISTINCT band, which that union destroys. Both are
  satisfiable at once: keep the re-wrap for chaining, and rebuild a
  separate unwrapped-mask domain for the oxidation from copies stashed
  just before the union (`register_locos_unwrapped()` in
  `tcad/backends/viennaps/io.py`). Verified at 10hr, where growth
  clears the grid noise floor: SiO2 +0.175 vs the first step's +0.106,
  Si consumed, all 3 materials preserved, 3-step chains work. A
  staleness fingerprint refuses the case where an intervening step
  modified the domain (it would otherwise silently oxidize stale
  geometry). **Measurement caveat worth reusing:** the chaining test's
  own 0.02hr recipe is below the 0.2um grid's noise floor — at that
  time BOTH oxidations move oxide area by ~0, so it cannot judge
  whether a process step did anything. Full writeup: search
  `docs/investigation_log.md` for "LOCOS-on-LOCOS — ROOT-CAUSED".
- **KOH/TMAH crystallographic wet etching**: added using real, cited
  rate constants (30% KOH, 70°C). Later found the 3D-example direction
  vectors made `rate111`/`rate311` algebraically inert in this
  project's 2D cross-section (wrong depth axis) — fixed additively
  with a derived 2D crystal frame (`KOH_30PCT_70C_2D`). Self-limiting
  V-groove behavior is still NOT achieved (see OPEN items).
  Per-material etch selectivity (`material_rates`) added to
  directional/isotropic etch along the way.
  Directional deposition: fixed a sign-convention bug
  (`directionalVelocity` sign was inverted vs. ViennaPS's own
  convention) and a shape bug (`calculateVisibility=True`, ViennaPS's
  own default, silently under-grows non-monotonically — now defaults
  to `False`).
- **MOSFET buildout**: `implant_windows` doping (laterally-windowed,
  superposed doping via DevSim's own equation parser), `mask_spans_um`
  (arbitrary multi-span masks, generalizing `MakeTrench`), gate/contact
  placement verified via the existing `contact_sides`/`contact_axes`
  API, `geometry`/`gate_stack` (Si + oxide + electrode + S/D pads, its
  own zero-duration category — could not safely be folded into the
  shared `prepare_domain()`), a working gate C-V sweep, and a working
  Id-Vgs sweep with real gate-controlled drain current. Along the way:
  graded/telescoping mesh refinement (`graded_refine_mesh_near`)
  replaced single-window refinement to make high-doping devices
  (up to 1e20 cm^-3) converge affordably; and a 3.8e7x-wrong terminal
  current was root-caused to an under-resolved inversion layer (see
  the Development Rules entry above) and fixed with
  `derive_implant_windows_refinement()`.
- **GUI**: real ViennaPS mesh rendering (was a placeholder rectangle),
  per-model etch-panel field visibility, and — most recently —
  boundary-tracing solid-silhouette rendering (traces each material's
  true outline from the real mesh instead of decimated triangles over
  a stale placeholder, so etch undercuts/voids render correctly). All
  visually verified on-screen via a secondary `.venv312` + Xvfb +
  `xdotool` setup (the main venv's Python has no installable tkinter
  in this container). GUI etch panel wires 4 models (Bosch DRIE,
  Directional RIE, Isotropic, SF6/O2); an oxidation/LOCOS panel, a
  deposition panel (7 models), a MOSFET gate-stack panel, and a doping
  panel (4 kinds) are now also wired (see GUI section below) — every
  registry and non-registry category is now wired. A 2-terminal
  device-measurement panel (real DevSim solve, user-chosen voltage-
  source/multimeter contact roles) was added on top of that — the
  first GUI code path to import `devsim` directly.
- **Registry growth**: etching 11 models, deposition 6 models, doping
  3 kinds (uniform, step_junction, gaussian_implant, implant_windows),
  plus `geometry`/`gate_stack`.
- **MOSFET Ohm's-law cross-check ~800x gap — RESOLVED, no real
  resistive anomaly.** Reading DevSim's own converged edge-current
  models directly (not reconstructing current from density) at real
  graph cuts across the channel — validated first against the known
  terminal Id/Is at contact-adjacent cuts (matched to 4 decimals) —
  showed current is smooth, fully conserved, and ~100% electron
  current (hole current negligible, ruling out a body-current
  explanation) at every x tested, including the exact point where an
  earlier density-based reconstruction had shown a mathematical
  singularity. The ~800x figure (and the later, harder-to-explain
  edge-zone breakdown) both trace to the same root cause: the density
  -reconstruction proxy ("excess electron density over a pre-bias
  snapshot") stops correlating with real local current near a doping
  -window edge, not any actual device defect. Full writeup: search
  `docs/investigation_log.md` for "RESOLVED: no real resistive anomaly
  exists".
- **`derive_implant_windows_refinement()` mesh-composition bug fixed
  (union, not accumulation) — does NOT by itself fix the implant_windows
  GEOMETRY-DEPENDENT convergence gap, still OPEN, see below.** Lateral
  refinement rings are now built as one predicate PER RING WIDTH
  (matching ANY window edge at that depth) instead of one full
  telescope PER EDGE — so two nearby refinement sources share ring
  passes instead of stacking. No change to the shared
  `graded_refine_mesh_near`/`refine_mesh_near` machinery; full 31-test
  regression suite still passes. A decisive follow-up experiment then
  showed refining harder at a known-exact sidewall position — even with
  this fixed composition — still fails to converge up to practically
  affordable mesh sizes, which redirects the remaining problem toward
  the equilibrium SOLVE STRATEGY rather than mesh resolution.
  **Confirmed the redirect was right: doping-LEVEL continuation
  (ramping NetDoping's magnitude 1e17->1e20 in a few steps, reusing
  each step's converged solution as the next step's initial guess —
  the same mechanism already used for BIAS ramping, applied to doping
  instead) fully and reproducibly solves the EQUILIBRIUM failure.**
  Full writeup below (OPEN item 2) and in `docs/investigation_log.md`.
- **Heavily-doped 2-terminal solves fixed and shipped:
  `tcad/characterization/robust_iv_sweep.py`.** 1e20 cm^-3 is the real
  production source/drain level (substrate 1e14-1e17, well/channel
  1e16-1e18, S/D 1e19-1e21), so it has to work. Three pieces, each
  separately measured, none of them a tolerance fudge: doping-level
  continuation for equilibrium (via `apply_doping`'s new additive
  `window_scale`); DevSim's OWN official `gmsh_mos2d.py` transport
  tolerances (`absolute_error=1e30`, `relative_error=1e-5`) instead of
  `pn_junction_iv_sweep.py`'s `absolute_error=1e10` — already validated
  inside this project by the passing MOSFET Id-Vgs test at the same
  1e20 doping, and blocking because **DevSim requires BOTH its absolute
  and relative criteria** (a logged solve with RelError 9.08e-06
  against a 1e-5 tolerance kept iterating solely because AbsError
  2.86e10 > 1e10); and a bias ramp that RESTORES the node solutions on
  a failed step, which DevSim's own `rampbias` does not do. Verified
  not to change answers: on the known-passing 4x3um recipe it returns
  the same current as the old path to 5.7e-08 relative. `pn_junction_
  iv_sweep.py` deliberately untouched. Pinned by
  `tests/integration/test_robust_iv_sweep_real.py`.
- **GUI's "DevSim is not installed" error was misleading — fixed.** A
  bare `except Exception: devsim = None` in `backend.py` discarded the
  real import error, so a genuinely-installed DevSim that failed to
  import (missing unversioned BLAS `.so` symlink — Debian/Ubuntu ships
  only the versioned `libblas.so.3`) reported the same message as
  "never installed". Fixed with `_default_devsim_math_libs()`
  auto-detection (searches for `libblas.so.3`/`libopenblas.so.0`, only
  acts when `DEVSIM_MATH_LIBS` isn't already set and a candidate
  exists) plus an error message that distinguishes the two cases.
  Verified: 33/33 regression in a clean env, a forced-broken-BLAS unit
  test confirming the correct message, and a live headless GUI MEASURE
  click producing a real converged solve with no error dialog. Search
  `docs/investigation_log.md` for "DevSim is not installed" error was
  misleading" for the full writeup.
- **GUI order-free single-step runs, deposition chaining, deposition
  material selection, p/n doping color — fixed.** The earlier "order is
  the user's choice" Process Flow work only changed the explicit ADD TO
  FLOW/RUN PROCESS FLOW path; the plain RUN ETCH/RUN OXIDATION/RUN
  DEPOSITION buttons still each ran standalone (no `inherited_domain`,
  so a click after a previous click silently rebuilt a fresh wafer
  instead of continuing) and oxidation/deposition still carried a
  leftover "Run lithography and develop first" gate neither genuinely
  needed (`prepare_domain()` only ever reads `self.wafer` fields that
  are always defaulted). Fixed with `self.completed_steps` (every real
  step already run this session) + `_chained_flow_config()`, which
  wraps a single RUN click as `completed_steps + [recipe]` and executes
  it through the SAME `run_flow`/`ProcessStep(inherited_domain=...)`
  mechanism the flow panel already used — so a standalone click now
  chains too. All three litho-first gates removed (etch's included, for
  consistency — leaving just one would relocate the same complaint).
  Also added: deposition material selection (5 of 7 deposition models
  had no way to choose WHAT was deposited — they silently merge into
  whatever material sits on top unless `geometry.duplicateTopLevelSet()`
  is called first, a mechanism `geometric_trench.py`/`bosch_drie.py`
  already used; now wired as an opt-in `material` recipe key + GUI
  combobox on all 6 material-relevant models); and a p/n doping color
  overlay (blue = n / red = p, reproducing `doping_mapping.py`'s own
  NetDoping sign convention exactly, not a separate approximation) on
  the real-mesh canvas render. Verified live through real ViennaPS
  (order-free oxidation, standalone-click chaining producing a mesh
  with both the prior step's and new step's materials, material
  tagging producing a genuinely distinct SiO2 region, and a real doping
  run producing both a blue and a red overlay rectangle) plus the full
  33-test regression suite. Search `docs/investigation_log.md` for
  "order-free single-step runs, deposition chaining, deposition
  material selection, p/n doping color" for the full writeup.
- **Lithography became real STATE; a process step no longer invents a
  photomask.** Architecture audit, driven by four user-reported
  symptoms, found ONE root cause behind all of them: there was no
  resist state anywhere. Mask/PR were GUI *parameters* that always
  carry a value (`Wafer.mask_openings_um` defaults to `[[3.5, 6.5]]`,
  `pr_thickness_um` to 1.0), and each process panel independently
  decided whether to turn them into geometry. Measured against real
  ViennaPS before the fix, not assumed: (a) a plain isotropic
  deposition on a FRESH wafer, user having run no lithography at all,
  produced materials `['Mask','Si','SiO2']` — a 1.0um Mask solid — and
  patterned the film to x=[-1.5,1.5] instead of depositing it across
  the wafer; (b) oxidation → **PR COAT alone** → deposition put Mask
  only OUTSIDE the openings and Si3N4 only INSIDE them, i.e. a bare
  coat behaved as coat+align+expose+develop. Note (a) is the SAME
  defect already fixed for oxidation only (oxide floating on top of a
  mask) — that fix was a per-panel special case, so etch and
  deposition kept the bug. Fixed structurally with one resist-state
  table, `_resist_spans_um()`, read by BOTH the recipe builder and the
  canvas overlay (they derived resist shape independently before, and
  disagreed): no resist → no mask at all (fresh OR chained); coated,
  not developed → ONE full-width span; developed → the opaque
  complement. A blanket coat needed no new geometry code —
  `mask_spans_from_openings([])` already returns exactly one
  full-width span. Also fixed alongside: `wafer.developed` was set once
  and cleared only by NEW WAFER, so coat→develop→strip→coat left the
  fresh coat already patterned (PR COAT now clears the cycle); the
  SESSION STATE markers lit stages 0..6 for a single oxidation,
  claiming PR coat/alignment/exposure/develop/**etch** the user never
  ran (`_mark_stage_done` now accumulates only what ran); PR STRIP's
  silent `return` became a warning; and `run_process_flow` set
  `wafer.etched` for any flow, including flows containing no etch.
  Pinned by `tests/unit/test_gui_litho_lifecycle_mock.py` (drives the
  REAL TCADApplication with the window withdrawn) and
  `tests/integration/test_litho_lifecycle_state_real.py` (the same
  recipes through real ViennaPS, plus the full
  Si→oxidation→litho→etch→strip→deposition→doping sequence).
  **Still true, deliberately:** PR STRIP is a state transition only —
  resist already built into an earlier step's exported geometry stays
  in that mesh. `domain.removeMaterial()` exists in ViennaPS 4.6.2
  (verified) so a real strip step is implementable; not done yet, and
  the integration test asserts the current behavior so the gap stays
  visible.
- **One wafer now accumulates state: each RUN runs ONE step on the
  geometry the previous RUN left.** The GUI runs every step in its own
  subprocess, so it cannot hold a live ViennaPS Domain between clicks.
  It used to solve that by REPLAYING — `_chained_flow_config()` sent
  `completed_steps + [recipe]` to a fresh `run_flow()`, so the Nth
  click re-ran all N steps from a bare wafer. The geometry that
  produced was correct, but it was O(N²) and re-paid for the slowest
  step forever (a ~25s oxidation was re-run on every later click), and
  it is literally the user-reported "each process builds a new wafer".
  Fixed by carrying the `.vpsd` that `run_flow` was *already writing
  and nobody read back*: `run_flow` gained an additive
  `initial_domain=` parameter, the worker takes `_resume_state` and
  returns `domain_state`, and the GUI keeps it in
  `self.last_domain_state` (cleared by NEW WAFER).
  `completed_steps` survives as history/timeline only. Measured: clicks
  2-4 of a 4-step flow each report `step_count == 1` and take 0.3s
  instead of re-running the oxidation. Pinned by
  `tests/integration/test_process_state_resume_real.py`.
  **LOCOS deliberately still replays.** `io.register_locos_export()` /
  `register_locos_unwrapped()` are keyed by `id(domain)` and the latter
  holds live ViennaLS level sets, so a `.vpsd` round-trip loses them
  and a following LOCOS-on-LOCOS would refuse outright. Measured first
  rather than assumed: a round-tripped LOCOS domain still EXPORTS all
  three materials correctly with the same extents, so only
  LOCOS-after-LOCOS is affected — `_locos_in_history()` falls back to
  replay for that case rather than trading the feature away for speed.
- **Metallization is its own GUI category, and the category list is now
  the CAD one.** Categories are Oxidation / Lithography / Etching /
  Deposition / Metallization / Doping / Geometry / Device measurement,
  each selecting exactly one panel (category -> method -> that method's
  parameters -> RUN), with no order enforced. Metallization is a thin
  layer over the deposition registry — `run_metallization()` emits
  `_process_category: "deposition"` — so masking, chaining and state
  carry are the same verified code path, with no second implementation.
  Its method list is the physically meaningful subset (sputter/PVD,
  conformal CVD, isotropic plating; TEOS and epitaxy do not deposit
  metal) and its material list was checked entry-by-entry against
  ViennaPS 4.6.2's own `Material` enum — note there is **no Al**, which
  is why the default is W. `_run_single_step()` was added as a NEW
  helper for it rather than refactoring run_etch/run_oxidation/
  run_deposition, deliberately: those three are individually verified
  and rewriting them to share it would risk three working behaviors to
  remove duplication that is not causing a bug.
- **Selective Epitaxy can finally name what it grows.** It was the one
  deposition model with no `duplicateTopLevelSet()` call, so an
  epitaxial layer could only merge into whatever material was on top —
  correct for HOMOepitaxy (Si on Si is the same crystal) but making
  HETEROepitaxy (SiGe on Si) inexpressible. Added with the same
  opt-in/default-off shape the other six models use, so a recipe
  without the key behaves exactly as before. `Si`/`SiGe`/`aSi` joined
  the GUI's material list. Note the recipe now has two different
  material meanings: `material_rates` names the SEED surfaces growth is
  selective to, `material` names what is grown.
- **The physical rules are pinned as one readable spec**,
  `tests/integration/test_physics_rules_real.py`: PR coating is really
  blanket; no mask pattern reaches geometry before develop; selective
  etch AND selective deposition are possible only after develop; every
  one of the 7 deposition models can name its material (asserted by
  inspecting each registered model, so a new model cannot be added
  without it); doping leaves the Si geometry and material set
  bit-identical and carries P/N as a signed concentration with the
  overlay colors P = #e0393e (red) / N = #2f6fed (blue); and a
  Si -> +SiO2 -> +Si3N4 -> +W flow preserves every earlier layer.
- **ViennaPS cannot open a non-ASCII path — silently.** Root cause of
  5 pre-existing regression failures on this machine (user name is
  `박석훈`, so `tempfile.gettempdir()` is non-ASCII). `vps.Writer(...)
  .apply()` wrote NO file and raised NOTHING, so `save_domain_state()`
  returned normally and the caller only found out one step later when
  `Reader` failed with "Could not open file"; `Reader` failed the same
  way on a file that demonstrably existed (copied there, 1206 bytes),
  proving it is the path string and not the content. The usual Windows
  workaround — an 8.3 short path via `GetShortPathNameW` — was tried
  first and does NOT work here: 8.3 generation is disabled on this
  volume, so the call returns the long path unchanged. Fixed with
  `_ascii_io_path()` in `session.py`: do the I/O in an ASCII scratch
  directory and move the result to where the caller asked, plus an
  explicit post-write existence check so a failed save can never again
  masquerade as a failed load. An ASCII-named machine takes the
  unchanged path and pays nothing. This fixed `test_phase13_process_flow_real`
  and `test_phase14_flow_devsim_real` outright.
- **PN diode I-V verified end to end (V_th = 0.720 V, ideality factor
  1.01) — and two CALLER-SIDE traps found doing it.** A textbook
  process flow (oxidation → lithography → doping → metallization →
  lithography) through `run_flow` + `run_pn_junction_iv_sweep` first
  produced a curve with NO diode knee. Neither cause was in library
  code. **(1) Wafer vs. domain coordinates:** deriving the junction
  position from a litho mask window's center in WAFER coords (0..width)
  puts it in the wrong place — the domain is CENTERED (a 4.0um
  `x_extent_um` meshes as x = -2.1..+2.1), so `0.5*(1.5+2.5)` = 2.0
  landed 0.1um from the edge, making a 98%-one-type slab that still
  solved, still conserved charge, and still drew a smooth monotonic
  curve. Subtract `0.5*x_extent_um`, or derive it from the mesh the way
  `test_phase8_pn_junction_real.py` does. **(2) Bias polarity:**
  `apply_step_junction_doping` puts donors where axis > junction, so
  `Si_xmax` is the n-side and sweeping IT positive REVERSE-biases the
  diode; forward bias drives the p-side (`Si_xmin`). Once both were
  fixed the same device gave 10 decades of exponential forward current,
  flat 3.7e-11 A reverse saturation, and the classic n≈1.9 →
  n≈1.01 → n>1.1 (recombination → diffusion → high-injection)
  progression. **Carries an open flag:** `test_phase8_pn_junction_real.py`
  uses the same inverted labels and its branch assertions pass either
  way, so it would not catch a polarity inversion — left unchanged,
  see the log entry. Search `docs/investigation_log.md` for "PN diode
  I-V looked broken".
- **WaferState-driven physics resolution** (`tcad/physics/`:
  values.py/wafer_state.py/intent.py/tables.py/resolve.py).
  `resolve(intent, state, user_supplied=None)` has NO history parameter
  — order can never affect a result. Physics reads
  `state.exposed_materials()` (spatially present now), never
  `state.materials` (merely declared — e.g. a fully-etched layer stays
  declared at zero thickness). `Resolution`/`Provenance` are separate
  axes; `INTERACTION_COEFFICIENTS` ships **empty on purpose** — UNKNOWN
  never blocks execution, only gets reported. Wired onto the real path
  for isotropic etching only; oxidation/deposition/metallization/doping
  are not yet wired, and **doping is not in WaferState at all**
  (deliberate, not an oversight). Design:
  `docs/superpowers/specs/2026-08-25-wafer-state-physics-design.md`.

## OPEN issues (active — read before starting new work)

1. **KOH/TMAH self-limiting V-groove — ROOT-CAUSED, and NOT fixable at
   this project's layer.** No longer an open question, but left here
   because it bounds what the shipped KOH model may be claimed to do.
   The velocity field is *correct*: evaluating `psWetEtching.hpp`'s own
   formula with this project's `KOH_30PCT_70C_2D` frame gives exactly
   `rate111` at the (111) facet, and its velocity minimum sits at
   54.7400° vs the real magic angle 54.7356° — the 2D frame is right to
   0.005°. The failure is at the CORNER: **a V-groove apex has outward
   normal (0,1,0) by symmetry at any resolution, and that normal
   evaluates to exactly `rate100` = 159x `rate111`.** So the one point
   that must stop for the groove to close is the fastest-moving point
   on the whole profile. Measured directly, starting from a V-notch
   pre-carved at the exact magic angle: apex advances at ~100x
   `rate111` (~0.7x `rate100`) from the first timestep, while the
   sidewall angle still reads 54.50° at R²=0.9998 — and it is
   **grid-independent** (0.68/0.78/0.75x `rate100` at gd 0.2/0.1/0.05),
   ruling out apex rounding. Root cause: v(tilt) is strongly
   NON-CONVEX, and plain normal-velocity level-set advection moves each
   point by its own local normal, so a concave corner between two slow
   facets is not governed by those facets. Correct behaviour needs a
   Wulff/Frank convexification inside the advection library — i.e. a
   ViennaLS-level numerical-methods change, unreachable from any
   recipe, frame, grid, scheme or geometry choice here. This one
   mechanism also explains why none of the 12 spatial schemes helped,
   why grid refinement never helped, and why the facet angle wanders
   from a flat start. **Consequence:** `wet_etching.py`'s existing
   docstring scope limit ("anisotropic, genuinely (111)-aware — NOT
   validated self-limiting KOH/TMAH physics") is correct and must stay;
   what changed is that the reason is now exact rather than suspected.
   TMAH stays moot for the same reason, and real TMAH rate constants
   were never obtained (paywalled paper, blocked mirror, no ViennaPS
   data). Two measurement traps worth reusing are recorded with it: an
   under-sized `floor_depth_um` faked a 90-second "self-limited
   plateau" (export floor clipping a still-growing front), and a
   straight-line angle fit needs its R² reported or a curved profile
   yields a confident, meaningless angle. Full writeup: search
   `docs/investigation_log.md` for "the apex normal evaluates to
   rate100".

2. **`implant_windows` convergence is GEOMETRY-DEPENDENT, not solved in
   general — OPEN.** Framing this correctly matters: the requirement is
   NOT "wafer size 4x3 works, 10x8 doesn't" — a user arbitrarily etches
   a device and dopes it, and the solve must converge for WHATEVER
   geometry+doping combination that produces, not for a fixed list of
   verified configurations. `refine_process_result_for_implant_windows()`
   fixed one configuration (4x3um wafer, mask 1.5-2.5) robustly under
   perturbation of THAT configuration's own mask — but a different
   configuration (the GUI's own 10x8um default) still raises
   "Convergence failure!" with the identical doping-derived refinement
   applied. The fix is real but narrower than "implant_windows
   converges" — treat it as "one geometry class now converges", not as
   the general case being solved. It fails in the **EQUILIBRIUM** solve
   (RelError 1.0 -> 1.52, rising) before any bias is applied — so no
   bias-ramping strategy can help, and refinement as currently derived
   does not rescue it either (fails both with and without).

   **ROOT CAUSE (confirmed by direct experiment):** a doping junction
   placed roughly HALF A MESH CELL from an etched sidewall, with the
   heavily-doped side forming a full-thickness strip narrower than one
   cell. The GUI's defaults do exactly that: mask 3.5-6.5 puts the
   trench sidewall at x=+-1.5, and the implant window's outer edge is
   at +-1.6 — a 0.1um full-thickness n+ sliver against a 0.2um grid.
   Same wafer, same mask, same trench, same doping levels, same
   refinement, moving ONLY the windows:

   | implant windows | edges vs the sidewall at +-1.5 | result |
   |---|---|---|
   | 0.6-1.6 (GUI default) | outer edge 0.1um from it | **FAIL** |
   | 0.6-1.2 | both well inside the trench | OK, +2.9267e-11 A |
   | 2.0-3.0 | both well outside the trench | OK, +2.9273e-11 A |

   Note the junction-to-sidewall distance alone is not the trigger: the
   passing 4x3 case also has a window edge 0.1um from its sidewall, but
   there the etched step falls in the lightly-doped BODY, so no
   sub-cell strip of 1e20 silicon is formed. Workaround for a user
   today: keep implant-window edges at least ~1 grid cell away from
   etched sidewalls (or put them fully inside/outside the trench).
   Neither a finer base grid nor more refinement rescues the default
   layout — grid 0.10 (26374 nodes) still fails, and so does the
   unrefined mesh.

   What makes it look mysterious from the outside: the failure is
   **marginal in every measurable mesh property**.
   Measured directly, `mask 3.5-6.5` (the GUI default, FAILS) vs
   `mask 4.5-5.5` (PASSES) on the same 10x8 wafer produce meshes that
   are identical in every property checked — 1330 nodes each, same
   x/y extents, same two contacts with 25 elements each, same NetDoping
   range — differing only in which side of the junction 4 nodes land on.
   A 4-node difference flips convergence. Ruled out by bisection, each
   its own run: domain size alone (10x8 with a narrow mask converges),
   the implant-window edges coinciding with etched trench sidewalls
   (4x3 with a wide mask converges), and the doping level (dropping the
   body to -1e15 still fails).

   Reproducer: `mask_left_um=3.5, mask_right_um=6.5, x_extent_um=10,
   y_extent_um=8, silicon_depth_um=5, grid_delta_um=0.2`, implant
   windows [-1.6,-0.6] and [0.6,1.6] at 1e20 on a -1e17 body.

   Why this is a GENERAL robustness gap, not a one-off case to patch:
   `derive_implant_windows_refinement()` derives refinement rings from
   the DOPING profile alone (window edges, peak concentration) — it has
   no visibility into where the process step put an etched sidewall.
   Any user who etches a trench and then places an implant window edge
   near that sidewall (not just at x=+-1.6 on a 10x8 wafer — this is a
   RELATIONSHIP between two independently-chosen inputs, so it recurs
   at other coordinates for other geometries too) can reproduce this
   class of failure. Fixing "the 10x8 default" specifically would just
   move the undiscovered failure to the next untested combination.
   A real fix needs the refinement (or the solve strategy) to be aware
   of GEOMETRIC features (etched edges / material boundaries) in
   addition to doping features, or the solver needs to handle a
   sub-cell high-doping sliver without diverging in equilibrium.

   **TRIED "add refinement at the sidewall too" — confirmed it does NOT
   work with the current mesh-refinement machinery, and confirmed WHY.**
   Mesh-only checks (no solve, cheap): the RAW mesh already has sub-cell
   triangles at the etched sidewall x=+-1.5, independent of any doping
   (ViennaPS's own geometric meshing of the trench corner — areas down
   to 6.9e-05 vs a normal 0.02, confirmed by direct triangle-area dump).
   Adding a SEPARATE telescoping ring set at that sidewall, on top of
   the doping-derived rings already centered at the window edge 0.1um
   away, does not converge either — worse, it doesn't even reach a
   solve attempt: at the SAME ring depth the doping-only path uses (4
   rings, matching `_IMPLANT_WINDOWS_MAX_RINGS`), mesh size went from
   12049 Si nodes to 156832 — even a SINGLE extra 0.2um-half-width ring
   alone tripled it (12049 -> 36407). Re-ordering the combined predicate
   list to interleave by ring width (globally-widest-first across BOTH
   sources, instead of one source's full telescope then the other's)
   barely helped (156832 -> 142070, ~9%) — ruling out ORDER as the
   cause.

   Root cause, confirmed by reading `refine_mesh_near()`
   (`tcad/device/devsim/mesh_refine.py`): it unconditionally subdivides
   any triangle whose centroid matches the predicate, with NO check for
   "already smaller than what this predicate needs" — so two
   independent full ring telescopes (doping's 4 + a second, separate 4
   for the sidewall) that overlap spatially don't take the union of
   what's needed there, they ACCUMULATE: a triangle already refined
   down to the doping telescope's finest ring gets the sidewall
   telescope's full 4-level halving applied on top, unconditionally,
   in either order. `graded_refine_mesh_near`'s own docstring says
   plainly it is designed for ONE nested telescope per call, widest to
   narrowest; it was never designed to compose TWO independent
   telescopes with overlapping footprints, and that is exactly the
   geometry this failure mode requires (a doping edge close enough to a
   sidewall to need both).

   **FIXED (partially) — `derive_implant_windows_refinement()` now
   composes lateral rings as a UNION, not an accumulation.** Rather than
   looping per-edge with each edge's own full widest-to-narrowest
   telescope, it now builds ONE predicate PER RING WIDTH, each matching
   ANY window edge at that depth — so two nearby edges share ring
   passes instead of each getting the other's full depth stacked on
   top. No change was needed to `graded_refine_mesh_near`/
   `refine_mesh_near` themselves (both stayed exactly as-is, so every
   other caller — MOSFET Id-Vgs, gate stack C-V, step_junction,
   gaussian_implant — is unaffected; confirmed by the full 31-test
   regression suite passing after this change, same as before).
   Verified directly against the OLD code on the identical known-
   passing recipe (project's own `test_gui_measurement_doping_kinds_
   real.py` recipe): OLD gives 11269 Si nodes / +3.475285e-11 A, NEW
   gives 13955-19421 Si nodes (depending on search radius tried during
   development) / +3.909162e-11 A to +3.932010e-11 A — both converge,
   both satisfy KCL (equal-and-opposite terminal currents) to 6+
   figures; the ~13% current difference reflects the NEW mesh's
   somewhat finer local resolution, not a regression.

   **DECISIVE FINDING (this session): mesh refinement AT THE SIDEWALL —
   even done perfectly — is NOT the fix for the GUI-default 10x8 case.**
   A geometric-anomaly auto-detector was built and tried first (scans
   the raw mesh for triangles that are both small AND touch a different
   material tag, feeds their positions into the same union composition
   as the doping edges) — it correctly located points right at the real
   sidewall, but the case still failed to converge, so a cleaner
   decisive test was run: feed the union composition the EXACT,
   hand-confirmed sidewall position (x=+-1.5um, no detector, no
   ambiguity) directly. Findings, mesh-size-only checks BEFORE each
   solve attempt (this project nearly OOM'd twice earlier chasing this
   same question with the OLD accumulating composition, so every step
   here was checked cheaply first):

   | ring depth | Si nodes | result |
   |---|---|---|
   | 4 rings (0.025um half-width) | ~16550 | Convergence failure! |
   | 6 rings (0.00625um half-width) | 69274 | Convergence failure! |
   | 8 rings (0.0016um half-width) | 303530 | did not finish in 300s |

   This rules out "the mesh isn't fine enough at the sidewall" as the
   (complete) explanation — even PERFECT knowledge of where to refine,
   composed correctly (no accumulation), pushed to 12.5nm-scale local
   resolution, still fails in the EQUILIBRIUM solve, and going finer
   becomes computationally impractical before it has a chance to
   resolve anyway. The geometric-anomaly auto-detector was therefore
   REMOVED again (it added real complexity/fragility — an early version
   false-positived on an unrelated real material boundary, this
   project's own documented Si-floor artifact — for a mechanism now
   shown insufficient on its own), leaving only the validated,
   unambiguously-safe union-composition restructuring in production.

   **CONFIRMED: doping-LEVEL continuation (not mesh) is the correct
   lever — EQUILIBRIUM fully solved by it; DRIFT-DIFFUSION helped a lot
   but not fully solved yet.** On the exact 69274-node (6-ring,
   exact-sidewall) mesh that failed above, ramping the window
   concentration itself (1e17 -> 1e20 in 5 geometric steps, reusing
   each step's converged Potential as the next step's initial guess —
   the same mechanism `run_pn_junction_iv_sweep` already uses for BIAS,
   applied to a NetDoping node-model constant instead) makes the
   EQUILIBRIUM (Poisson-only) solve converge cleanly and reproducibly.
   Confirmed multiple times, always succeeds.

   Extending the identical idea one stage later — enable drift-diffusion
   at a LOW doping level first (trivial there), then ramp doping UP
   again with transport equations already active — also works, but only
   PARTIALLY: it converges up to some point in the 1e18-1e19 cm^-3
   range, then fails, and where exactly it fails depends on how finely
   the ramp is stepped:

   | ramp step ratio | steps to 1.0 | got as far as | then failed at |
   |---|---|---|---|
   | ~3x (7 coarse steps) | 7 | 3.0e18 | 1.0e19 |
   | 1.3x (28 steps) | 28 | 6.62e18 (best run) / 5.76e18 (another run) | ~7.6e18-1.0e19 |
   | 1.15x (51 steps) | 51 | 6.62e18 | 7.61e18 |

   Each finer step schedule pushed the failure point further (3.0e18 ->
   5.76e18 -> 6.62e18) but with clearly DIMINISHING returns — doubling
   the step count from 28 to 51 gained nothing further (both topped out
   at 6.62e18). This is NOT "just needs even finer steps": it looks like
   a real numerical wall somewhere in the 7e18-1e19 cm^-3 range for
   drift-diffusion on this specific ultra-fine (12.5nm) mesh, distinct
   in character from the equilibrium failure (which doping continuation
   solved outright, not just pushed back).

   ALSO CONFIRMED (a real trap, costly to rediscover): loosening
   INTERMEDIATE ramp-step tolerance (1e-4 instead of 1e-6, reasoning
   that an intermediate step only needs to seed the next step's initial
   guess, not full precision) made things WORSE, not better — a step
   that "converged" at only 1e-4 precision was a bad enough initial
   guess that the VERY NEXT step diverged outright (RelError -> 2e4,
   unbounded, not oscillating). Keep tight tolerance (1e-6) at every
   ramp step, not just the final target — use smaller STEPS instead of
   looser precision to control cost.

   **RESOLVED, and shipped — the drift-diffusion half was a TOLERANCE
   problem, not a doping-ramp problem.** The DD wall above disappears
   entirely once the transport solve uses DevSim's OWN official
   `gmsh_mos2d.py` tolerances (`absolute_error=1e30`,
   `relative_error=1e-5`) instead of `pn_junction_iv_sweep.py`'s
   `absolute_error=1e10`. That is not a new guess: this project's own
   PASSING MOSFET Id-Vgs test already uses those values at the same
   1e20 doping, and `mosfet_sweep.py`'s own docstring already records
   that 1e10 "plateaus at a residual oscillation around 2-6e-5 rather
   than settling, even at 100+ iterations" — the exact symptom logged
   here. **Why 1e10 blocks it: DevSim requires BOTH its absolute and
   relative criteria** (confirmed directly from this project's solver
   logs — a solve reporting RelError 9.08e-06 against a 1e-5 tolerance
   kept iterating because AbsError 2.86e10 exceeded 1e10), and an
   absolute tolerance of 1e10 is simply unreachable once carrier
   densities are ~1e20. With continuation for equilibrium + those
   tolerances for transport, the GUI-default 10x8um wafer now reaches a
   VERIFIED-PHYSICAL V=0 drift-diffusion state: terminal currents
   ~1e-28 A, Electrons 1e3..9.99e19, Holes 1.001..1e17 (exactly the
   analytic n_i^2/N values), no NaN.

   All three pieces are now in production as
   `tcad/characterization/robust_iv_sweep.py`
   (`run_robust_pn_junction_iv_sweep`), with
   `pn_junction_iv_sweep.py` deliberately left untouched:
   (1) doping-level continuation for equilibrium (via `apply_doping`'s
   new, additive `window_scale`), (2) DevSim's own DD tolerances,
   (3) a bias ramp that RESTORES the node solutions on a failed step —
   DevSim's own `rampbias` restores only the bias parameter, so a
   diverged attempt otherwise leaves the device corrupted and every
   subsequent halved step starts from there.

   **What still fails, precisely characterized.** The failure needs BOTH
   conditions, and neither alone is enough:
   (a) an implant-window edge within about half a grid cell of an
   ETCHED SIDEWALL (the sub-cell full-thickness strip), and
   (b) window doping at 1e20 cm^-3.
   Controlled proof, identical geometry / identical 12049-node mesh /
   identical solve strategy, varying ONLY the concentration:
   1e18 -> converges (+7.414179e-11 A), 1e19 -> converges
   (+7.341554e-11 A), 1e20 -> fails. And varying only the window
   POSITION at a fixed 1e20: windows clear of the sidewall converge
   (measured here at a 0.6um contact gap, and already documented above
   at 3.8um and 2.0um gaps), so it is the sidewall crossing, not the
   distance to the contacts (a floating-region explanation was proposed
   and REFUTED by exactly that comparison).

   The residual failure mode is Newton DIVERGENCE, not a stall: at a
   1e-06 V bias step the solve starts close (rel ~8.6e-05 against a
   1e-05 target), improves for two iterations, then blows up to
   DevSim's clamped 9.99e+02 / 3.00e+03 relative errors. Ring depth
   shifts it but does not cure it — 4 rings stall at 4e-06 V, 5 rings
   (23711 nodes) crawl to ~6e-04 V in ~34 attempts with an effective
   max step of ~3e-05 V, far too slow to reach 0.3 V.

   Ruled out by direct measurement this session, so a future session
   need not re-test them: mesh RESOLUTION (4/5/6/8 rings, with and
   without exact sidewall targeting); mesh QUALITY (DevSim's own
   EdgeCouple has ZERO negative entries and the edge-length ratio is
   3.050e3 on the failing mesh vs 3.048e3 on the passing one —
   indistinguishable); solution-state corruption during ramping (a
   ramp with explicit save/restore fails identically); and
   `variable_update="log_damp"` on the continuity equations (DevSim
   already uses `"positive"`; log_damp made the V=0 state measurably
   WORSE — terminal currents 1e-14 and same-signed, i.e. KCL-violating,
   versus 1e-28 and opposite without it).

   Next smallest experiment: since the failure is Newton divergence
   from a near-converged state, try a damped/limited update — e.g.
   solve the failing step with a much smaller `maximum_iterations` and
   repeated re-entry (crude damping), or examine which NODES carry the
   diverging update (`get_node_model_values` on the update between
   iterations) to see whether it is localized to the sliver or global.

3. **PR Strip / Doping / Deposition — three user-reported GUI issues,
   ROOT-CAUSED, NOT YET FIXED.** Reproduced against real ViennaPS 4.6.2,
   no code changed yet. Full writeups: search `docs/investigation_log.md`
   for "PR Strip removes nothing", "Doping: five confirmed gaps", and
   "Deposition: renderer y-scale artifact".

   **PR Strip:** not "Etching converts PR to Mask" (litho never produces
   real geometry — confirmed neither `process_pr_coat()` nor
   `process_develop()` calls `subprocess.run`; ViennaPS 4.6.2's own
   `Material` enum has no PR/photoresist entry at all). The real bug is
   `process_pr_strip()` only clearing GUI flags, never calling
   `domain.removeMaterial()` on the live domain — blocked on having no
   way to tell resist-derived `Mask` apart from LOCOS's own hard mask,
   which uses the identical material tag.

   **Doping**, five items: (1) no independent donor+acceptor in the same
   region for any of the 4 doping kinds — DONE, see Completed, "litho/
   doping/renderer plan"; (2) no dopant-species field anywhere — a
   `donor_species`/`acceptor_species` field now exists on `DopingRegion`
   and is logged, but is label-only metadata, not yet consumed by the
   DevSim NetDoping equation; (3) **likely root cause of the "DevSim did
   not run" report**
   — `run_measurement()`'s stale-doping re-attachment calls
   `run_doping()` internally, which pops up "No DevSim solve was run"
   in the middle of a MEASURE click, right before DevSim actually runs;
   (4) the P/N color overlay is already correctly implemented but
   invisible by default (`viewer_layer_var` defaults to `"geometry"`,
   not `"doping"`); (5) `WaferState` carries no doping field at all —
   known, deliberately deferred by the physics-resolver plan to a
   "stage 4+" this project's 11-task plan never reached.

   **Deposition**, two items, opposite causes: long deposition making
   the lower structure look eroded is a **renderer artifact, not real
   geometry** — raw mesh measurement showed SiO2 thickness unchanged
   (0.111um) across a 40x deposition-time range while the renderer's
   `y_scale` shrinks uniformly as the top grows
   (`available_above / depth_above` in `_draw_real_mesh_result`).
   Masked regions getting no deposition IS real, correct ViennaPS
   physics (`maskMaterial=` blocks positive rate too, confirmed by
   direct execution) applied **unconditionally** by the GUI to 3 of 7
   models with no user choice — and it directly contradicts this
   project's own Metallization panel text ("lands ... on top of the
   resist (lift-off geometry)"), since `run_metallization()` sets the
   same unconditional `mask_material` that excludes the resist entirely.

Minor/uncertain threads (not blocking, see investigation_log.md for
each item's own "what remains uncertain" section if you need it):
`pad_oxide_thickness_um`'s default only verified at one grid
resolution; `_AUTO_REFINE_MAX_RINGS=20` not stress-tested past 1e20
cm^-3; `dedupe_materials`/`filter_mesh_materials` only exercised for
one geometry/doping combination; `mask_spans_um` doesn't validate
spans against the domain extent; chained LOCOS reuses the inherited
(deformed) mask and silently ignores the recipe's own mask-window keys,
and its staleness fingerprint is point-counts only (a heuristic); every
RUN still writes into a fresh `tempfile.mkdtemp()` that nothing cleans
up, and those directories now hold the `.vpsd` the NEXT click resumes
from, so they cannot simply be deleted when a step ends; and PR STRIP
removes resist from the process STATE but not from geometry an earlier
step already exported (`domain.removeMaterial()` exists in ViennaPS
4.6.2 — verified — so a real strip step is implementable;
`test_litho_lifecycle_state_real.py` asserts the current behavior so
the gap stays visible).

Every process category the GUI names is now wired — see the GUI section
for the current category list.

## GUI

**Current shape (read this first; the history below predates it).**
The GUI is a Process CAD: pick a category, pick that category's method,
fill in only that method's parameters, press RUN. No order is enforced
anywhere — a step that genuinely needs something says so when pressed
(and warns rather than blocking, e.g. a blanket-resist etch, or resist
present during a furnace oxidation).

Categories, in the order they appear: **Oxidation, Lithography,
Etching, Deposition, Metallization, Doping, Geometry (MOSFET gate
stack), Device measurement**. Exactly one panel is visible at a time
(`_PANEL_ORDER` / `_PANEL_LABELS` / `_show_panel_category`).

Two invariants worth not breaking:

* **Lithography is state, not parameters.** `Wafer.pr_present` +
  `Wafer.developed` are the resist; `mask_openings_um` and
  `pr_thickness_um` are only inputs. Everything that needs to know
  "what is the resist doing" — the recipe builder AND the canvas
  overlay — reads `_resist_spans_um()`, never the fields directly.
  Adding a second reader that derives resist shape on its own is how
  the drawn state and the simulated state diverged before.
* **Each RUN resumes the accumulated wafer** from
  `self.last_domain_state` (a `.vpsd`), running one step. It falls back
  to replaying the whole history only when there is no state file yet
  or the history contains LOCOS (`_locos_in_history`).

GUI visualization is not authoritative for process geometry — always
judge physical correctness from the actual ViennaPS mesh/output, never
from what's drawn on screen. The etch panel renders the real, floored,
per-material mesh (boundary-traced solid silhouettes, not a
placeholder), for whichever of the 4 wired etch models is selected.

An oxidation panel (thermal / LOCOS, `tcad/process/oxidation/thermal.py`'s
one registered model) was added alongside it — `worker_main()` was
generalized from a hardcoded `"etching"` category to reading
`_process_category`/`_process_model_key` from the recipe, so it now
serves any registry category, not etch-only. LOCOS vs fin-style is one
checkbox (mirrors the recipe's own `mask_material`-presence switch).
Verified through real ViennaPS 4.6.2 end-to-end via Xvfb + xdotool (no
tkinter in the main `.venv`; a `.venv312 --system-site-packages` +
`apt install python3-tk xdotool` matches the project's established
GUI-testing workaround): both LOCOS and fin-style runs complete and
render the real mesh, and the existing etch panel is unaffected
(regression-tested live, not just via `tests/run_regression.py`).
`Wafer.etched` (etch-only, still gates the trench-opening placeholder
fallback) and a new `Wafer.processed` (any real process step) are now
distinct — the real-mesh render gate uses `processed`. Along the way,
found and fixed a real latent bug this surfaced: `process_pr_strip()`
guarded on `process_stage != "etched"` literally, which would have
silently no-opped after a real oxidation run (`process_stage ==
"oxidized"`) once that stage's button state is ever refreshed — not
etch-specific once "PR strip after oxidation" is a reachable action,
so it now accepts either terminal stage. That refresh gap itself
(`run_etch`/`run_oxidation` never called `_update_process_buttons()`,
so PR strip never visibly enabled after either) is now also fixed and
live-verified: both etch->strip and LOCOS->strip click-tested
end-to-end through real ViennaPS via the same Xvfb+xdotool setup, not
just confirmed by reading the diff. Deposition, doping, and
gate_stack remain unwired (see OPEN-adjacent minor threads); doping
in particular is not a registry category at all and needs different
plumbing than the panel/worker pattern the other three share.

A deposition panel (7 registered models: isotropic, directional,
single_particle_cvd, teos, teos_pecvd, selective_epitaxy,
geometric_trench) was added next, same combobox +
show/hide-per-model-frame pattern as the oxidation panel, field
defaults taken from the real, already-passing
`tests/integration/test_phase3_deposition_real.py` rather than
invented. `geometric_trench` is architecturally distinct from the
other 6 (a zero-duration geometric stamp, no `deposition_time_s`
field) and got its own frame with a pitfall-warning label. Live-
verified via the same Xvfb+xdotool setup: geometric_trench and
Isotropic Deposition both ran through real ViennaPS to a completed
mesh; PR strip's three-way terminal-stage guard (`"etched"`,
`"oxidized"`, `"deposited"`) is now confirmed live for all three
stages, not just the first two. The other 5 deposition models are
wired with real-verified defaults but were not individually click-run
this session — see `docs/investigation_log.md`'s own "what remains
uncertain" for the deposition-panel entry.

A MOSFET gate-stack panel (registry category `"geometry"`, model
`gate_stack`) was added last. It does not fit the etch/oxidation/
deposition panel pattern: `GateStack.__init__` refuses
`inherited_domain` outright, there is no lithography step before it,
and it is explicitly TERMINAL (chaining any further process step onto
its export is documented, in `gate_stack.py`'s own module docstring,
to silently corrupt 4 of its 5 materials). So its "BUILD GATE STACK"
button is always enabled (mirrors NEW WAFER, not gated by
`process_stage`), and a successful build sets `process_stage` to a new
value, `"gate_stack"`, that `_update_process_buttons()` has no button
list for — every litho/etch/oxidation/deposition/strip button is left
disabled, enforcing "do not chain a further step" at the GUI layer
too; the 01-08 sequence markers are deliberately left untouched since
this build never goes through that sequence. Field defaults match
`tests/integration/test_gate_stack_geometry_real.py`'s own verified
values. Live-verified via the same Xvfb+xdotool setup: a real build
from a fresh wafer (no litho run first) produced the correct 5-material
topology (Si body, W source pad left, TiN gate centered over the
channel, Cu drain pad right), all litho buttons confirmed grayed out
afterward, and NEW WAFER confirmed to correctly escape the terminal
state. `material_colors` gained TiN/W/Cu entries (previously unlisted,
would have rendered as indistinguishable gray) since telling the 3 new
materials apart is the entire point of viewing this geometry.

A doping panel (4 kinds: uniform, step_junction, gaussian_implant,
implant_windows) was added last, closing out every category the GUI's
own inventory named. `tcad/physics/doping.py` is NOT a registry
category — no `ProcessStep`, no `vps.Process()` call, pure Python that
attaches a `DopingProfile` to a `ProcessResult` built (via
`build_process_result`) from whatever real mesh
(`self.last_final_mesh`) etch/oxidation/deposition/gate_stack most
recently produced. Because it is cheap (a meshio read, no ViennaPS
simulation), it runs directly on the Tk main thread rather than through
`worker_main()`'s subprocess pattern every other panel uses, and its
"APPLY DOPING" button is gated on "a real mesh exists"
(`self.wafer.processed`/`self.last_final_mesh`) inside
`_update_process_buttons()`, not on `process_stage` — so it stays
correct after any of the four process panels' success paths, or NEW
WAFER, with no changes to those methods. The panel states its own
scope limit up front: it only attaches a `DopingProfile` and logs it —
no DevSim solve, no contacts, no I-V/C-V curve (that would be a
separate, larger feature). Live-verified via the same Xvfb+xdotool
setup: "APPLY DOPING" starts disabled on a fresh wafer, a real
Isotropic etch enables it immediately, Implant Windows (background +
2 superposed windows, the structurally most complex kind) and Uniform
both applied successfully against the real etched mesh with the log
confirming `build_process_result` read the real materials
(`['Mask', 'Si']`) — not a stub — and NEW WAFER correctly disables the
button again afterward.

A 2-terminal device-measurement panel was added last, going beyond the
GUI's own original inventory into actual DevSim device simulation for
the first time. Scoped explicitly with the user first: 2-terminal
etch+doping (not the 4-terminal gate_stack MOSFET), and "set pin
position" means picking a role (voltage source vs. multimeter/GND) for
each of the 2 EXISTING auto-derived contacts, not clicking an arbitrary
point on the mesh (contacts are only ever auto-derived at a region's
own axis extremes — `<region>_<axis>min/max` — today; free-form contact
placement would need new `mesh_import.py` machinery). Reuses
`self.last_doped_result` from the doping panel; runs the real
`import_process_result` -> `apply_doping` ->
`run_pn_junction_iv_sweep` pipeline `test_phase8_pn_junction_real.py`
already verifies. Because `run_pn_junction_iv_sweep` reproducibly fails
to reconverge if called twice on the same device, every MEASURE click
imports a fresh DevSim device and cleans it up in `finally`
(`delete_device`+`delete_mesh`, mirroring
`tcad/cli/run_pipeline.py`'s own pattern) rather than keeping one
device alive across clicks. All 4 doping kinds converge through this
panel's own code path
(`tests/integration/test_gui_measurement_doping_kinds_real.py`), each
with its own refinement strategy: Step Junction uses
`refine_near_um`/`refine_axis` from the profile; Gaussian Implant uses
the existing `auto_refine_from_doping=True`; Implant Windows uses
`refine_process_result_for_implant_windows()` (see below); Uniform
needs none, having no junction to resolve.

**Implant Windows additionally routes through the ROBUST solve path**
(`run_robust_pn_junction_iv_sweep`, see the Completed summary) rather
than `run_pn_junction_iv_sweep`, because it is the kind that carries
real production source/drain levels (1e20 cm^-3), which the simple
path's single-jump strategy cannot reach — it fails in the EQUILIBRIUM
solve before any bias is applied. That branch owns NetDoping
registration itself (it ramps the doping level), so `apply_doping` is
deliberately NOT called first for this kind; the other three kinds keep
exactly their previous code path. Live-verified through the real GUI
end to end (litho -> Isotropic etch -> Implant Windows doping ->
MEASURE) under Xvfb: "Voltage source (Si_xmax): +0.3000 V,
I = 3.471737e-11 A / Multimeter (Si_xmin): 0.0000 V,
I = -3.471681e-11 A" — equal and opposite, and NetDoping was observed
re-registered 5 times, matching the continuation's 5 ramp steps, so the
robust path is confirmed to be the one that ran. Still subject to
OPEN item 2's one remaining pathological combination (window edge
within ~half a grid cell of an etched sidewall AND 1e20 doping).

Live-verified via the same Xvfb+xdotool setup (after `pip install
devsim==2.11.0` into `.venv312`, previously tkinter-only): a real
solve at V=+0.3 on Step Junction doping produced Voltage source
(Si_xmax) I=+4.855292 A / Multimeter (Si_xmin) I=-4.855292 A — equal
and opposite, a real KCL check on a real solved device — and swapping
which pin is the source reproduced the same magnitude with the sign
following the new assignment. Along the way, found (not guessed) that
the GUI's own default domain size (width_um=10, y_extent_um=8,
grid_delta_um=0.05) combined with Step Junction's local refinement
produces ~218k DevSim equations — 60x more than Phase 8's verified
~10-15k combination — and the panel's un-ramped single-jump bias solve
sat unfinished for 5+ minutes on that mesh before being killed;
raising `grid_delta_um` to 0.2 (an existing GUI field, no code change)
brought it to ~15k equations and a few-second solve. This is
recorded as a performance finding, not a correctness one — see
`docs/investigation_log.md`'s own "what remains uncertain" for
whether the large-mesh case would have eventually converged.

**Implant Windows was the one kind that genuinely did NOT converge**
through this panel (real, reproducible "Convergence failure!" at the
panel's own defaults: -1e17 body with 1e20 source/drain, whose ~1.2nm
Debye length is ~170x finer than a 0.2um process grid). It is the one
kind `import_process_result`'s `auto_refine_from_doping` cannot serve,
because its `DopingRegion` carries neither `junction_position_um` nor
`peak_position_um`. Fixed with
`refine_process_result_for_implant_windows()`
(`tcad/device/devsim/mesh_import.py`) — derives predicates from the
existing `derive_implant_windows_refinement()`, graded-refines, and
returns a ProcessResult on the refined mesh carrying the same
DopingProfile. The GUI panel and the regression test both call that
one function rather than each holding a copy. Measured **on a 4x3um
wafer**: fails outright -> 622->13543 mesh points, 11269 Si nodes,
I=+3.4753e-11 A, ~10.5s per click including the ViennaPS etch. Robust
there rather than lucky — perturbing the mask (1.3-2.7 / 1.4-2.6 /
1.5-2.5 / 1.6-2.4) keeps all four converging at a consistent ~3.5e-11 A.
**It does NOT fix the GUI's own default 10x8um wafer — see OPEN item 2.**

**Reusable trap found while chasing this (cost a whole prior
conclusion):** a LEAKED DevSim device makes the NEXT, unrelated solve
fail — and it does not matter whether the leaked device is
pathological. Leaking a perfectly healthy `uniform` device was enough
to turn a converging `implant_windows` solve into "Convergence
failure!", while a device whose own solve had just FAILED did no harm
once properly deleted. `devsim.solve()` takes no device filter, so it
iterates every registered device. A scratch harness whose cleanup was
`delete_device(device=..., region="")` inside a bare `except: pass`
(that call raises `region is an invalid option`) therefore reported
TWO doping kinds as non-convergent when only one had a real problem,
and blamed the wrong subsystem for it. The new regression test asserts
`devsim.get_device_list()` is empty after every kind so this can never
silently recur. Full writeup: search `docs/investigation_log.md` for
"GUI measurement: which doping kinds actually converge".

**Mouse-drawn mask** was added to the Lithography panel's 2D
cross-section canvas: click-drag now sets `mask_left_um`/`mask_right_um`
directly (previously text-field-only). Implemented as a thin input
layer on TOP of the existing text-field state — `_on_mask_drag_end()`
writes into the SAME `self.wafer.mask_left_um`/`mask_right_um` and the
SAME `self.left_var`/`self.right_var` StringVars `_read_lithography_
fields()` already reads at process-run time, so nothing downstream
(the recipe, ViennaPS, every process step) needed to change. A shared
`_wafer_canvas_x_transform()` helper factors out the pixel<->um mapping
`redraw()` already computes inline for the mask-opening rectangle, so
the drag handler can never drift out of sync with what's drawn.
Handles a reversed (right-to-left) drag by sorting min/max, ignores
sub-0.05um accidental clicks (leaves the existing mask untouched rather
than collapsing it), and is disabled once `wafer.processed` (a real
mesh exists, so the canvas shows the real ViennaPS render instead of
the mask placeholder — editing the mask then would silently disagree
with the geometry already on screen). Only a single opening is
supported (matches the GUI's own existing scope — `mask_spans_um`, the
backend's multi-span feature, has no GUI field at all today, drawn or
typed). Live-verified via the same Xvfb+xdotool setup: a real mouse
drag from x=2.0um to x=5.0um set both text fields to `2.000`/`5.000`
and, after MASK ALIGNMENT, the rendered "MASK OPENING" appeared at
exactly that position on screen — a genuine pixel-level round-trip, not
just a state-variable check. **Found, not fixed (pre-existing, unrelated
to this change):** `reset()` (NEW WAFER) creates a fresh `Wafer()` but
never clears `self.left_var`/`self.right_var` (or any other
Lithography-panel StringVar — `pr_var`, `depth_var`, `dose_var`,
`develop_var`) — so after NEW WAFER, the text fields keep showing the
PREVIOUS wafer's values, and the next `_read_lithography_fields()` call
(first litho button press) overwrites the freshly-reset `self.wafer`
right back to those stale numbers, silently undoing part of NEW WAFER.
Confirmed live (mask dragged to 2.000/5.000, NEW WAFER clicked, fields
still read 2.000/5.000). Out of scope for this change — same class of
bug would affect a typed edit just as much as a dragged one — left
here for whoever picks it up next.

**GUI restructured into a real CAD tool (three changes, all
live-verified through real ViennaPS):**

1. **Process order is now the user's choice.** The GUI used to enforce
   one hard-wired sequence by greying out every other button, which
   made whole classes of real device impossible to express: real
   devices need categories in orders that sequence could not reach at
   all. A **Process flow**
   panel now lets steps be queued in any order (ADD TO FLOW), reordered
   (up/down), removed, and run as one chained flow. It runs through
   `tcad.process.flow.run_flow`, which chains steps via
   `ProcessStep(inherited_domain=...)` so each continues from the
   previous step's REAL geometry — the Phase 13/14 machinery this
   project already verified, which simply had no way in from the GUI.
   `worker_main()` grew a `_flow_steps` branch for this; the
   single-step branch is unchanged. `_update_process_buttons()` no
   longer gates on `process_stage` — steps that genuinely need a
   predecessor still say so when pressed (`run_etch` checks
   `wafer.developed`), which reports the real reason instead of
   silently greying a button out. Verified live: oxidation queued
   BEFORE etch, reordered, run — final mesh carries `['Mask', 'Si',
   'SiO2']`, i.e. the etch really did continue from the oxide.

2. **Category -> model -> parameters.** All seven panels used to be
   stacked at once, several screens long, most of it irrelevant to the
   task at hand. A **Process category** combobox now shows exactly one
   panel at a time (`_show_panel_category`, `self._panel_frames`); each
   panel already picked its own MODEL and showed only that model's
   fields, so this just adds the missing outer level. Verified live:
   exactly one panel is mapped at any time.

3. **Multi-window masks.** `Wafer.mask_openings_um` holds EVERY opening
   (mask_left_um/mask_right_um remain the selected one, so every
   existing reader keeps working), edited through a listbox with
   add/remove/update, and the canvas drag edits the selected opening.
   Recipes now carry `mask_spans_um` built by the new pure helper
   `tcad.process.base.mask_spans_from_openings()` (unit-tested in
   `tests/unit/test_mask_spans_from_openings_mock.py`). **Side effect
   worth knowing: mask POSITION is now real.** The old
   mask_left/mask_right path goes through `MakeTrench`, which uses only
   the WIDTH and always centres the window — a mask drawn off to one
   side was silently processed as a centred one. For a single centred
   opening both paths agree exactly (the GUI's own 3.5–6.5 default on a
   10um wafer gives sidewalls at ±1.5 either way). Verified live: two
   openings (1.0–2.5 and 7.0–8.5) produced a real ViennaPS mesh with
   exactly TWO mask windows, at the drawn positions.

## Current Task

Do not try to solve everything at once. One item at a time; regression
before moving to the next. All three are root-caused already — see OPEN
issue 3 and the cited `docs/investigation_log.md` entries for the full
evidence before touching any code.

1. **PR Strip.** Make it actually remove resist-derived `Mask` geometry
   from the live domain (`domain.removeMaterial()`), gated on a way to
   tell resist-derived `Mask` apart from LOCOS's own hard mask — see
   `docs/investigation_log.md`, "PR Strip removes nothing".

2. **Doping ↔ WaferState.** Independent donor+acceptor input for all 4
   doping kinds is DONE (see Completed, "litho/doping/renderer plan").
   Still open: wire doping into `WaferState` so a later process step's
   physics resolution can see it, the "No DevSim solve was run" popup
   firing mid-MEASURE, and the invisible-by-default P/N color overlay —
   see `docs/investigation_log.md`, "Doping: five confirmed gaps".

3. **Deposition renderer + mask policy.** Fix the renderer's `y_scale`
   so unchanged lower layers stop looking eroded as the top grows, and
   make the masked-vs-blanket choice explicit and consistent across all
   7 deposition models (including Metallization, whose own "lift-off"
   claim the current unconditional mask exclusion contradicts) — see
   `docs/investigation_log.md`, "Deposition: renderer y-scale artifact".

For each investigation report:
1. What was tested
2. Result
3. What it proves
4. What remains uncertain
5. Next smallest experiment
