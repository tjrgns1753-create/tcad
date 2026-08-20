# TCAD 2D Project

## Goal
Build a reliable 2D TCAD process → mesh → DevSim device simulation pipeline.

- 2D only. Do not expand to 3D.
- Prioritize physical correctness over feature count.
- Use actual ViennaPS 4.6.2 / DevSim execution for validation.

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

Preferred order:
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

### Resolved investigations (summary — full detail in `docs/investigation_log.md`)

Current regression: `tests/run_regression.py` → **30 passed, 0 failed,
0 skipped**.

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
  deposition panel (7 models), and a MOSFET gate-stack panel are now
  also wired (see GUI section below); doping is the only remaining
  unwired category.
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

Minor/uncertain threads (not blocking, see investigation_log.md for
each item's own "what remains uncertain" section if you need it):
`pad_oxide_thickness_um`'s default only verified at one grid
resolution; `_AUTO_REFINE_MAX_RINGS=20` not stress-tested past 1e20
cm^-3; `dedupe_materials`/`filter_mesh_materials` only exercised for
one geometry/doping combination; `mask_spans_um` doesn't validate
spans against the domain extent; no GUI wiring for doping, gate_stack,
deposition, or the newer etch models (oxidation/LOCOS is now wired —
see GUI section); chained LOCOS reuses the inherited
(deformed) mask and silently ignores the recipe's own mask-window keys,
and its staleness fingerprint is point-counts only (a heuristic).

## GUI

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
materials apart is the entire point of viewing this geometry. Doping —
not a registry category at all, needs different plumbing — is now the
only unwired category.

## Current Task

Do not try to solve everything at once.

First establish a physically correct flat 2D Si wafer / mask representation.

Then verify oxidation.

Then etch/isotropic etch.

Then Bosch scalloping.

Only after geometry is trustworthy should physical device benchmarks be performed.

For each investigation report:
1. What was tested
2. Result
3. What it proves
4. What remains uncertain
5. Next smallest experiment
