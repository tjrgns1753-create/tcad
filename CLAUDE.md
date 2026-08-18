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
  any `ProcessStep.run()` file. LOCOS-on-LOCOS is still blocked (see
  OPEN items).
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
  Directional RIE, Isotropic, SF6/O2); deposition/oxidation/doping
  have no GUI panel at all.
- **Registry growth**: etching 11 models, deposition 6 models, doping
  3 kinds (uniform, step_junction, gaussian_implant, implant_windows),
  plus `geometry`/`gate_stack`.

## OPEN issues (active — read before starting new work)

1. **MOSFET Ohm's-law cross-check — plateau explained, edge zones need
   a different technique (not further density reconstruction).** Three
   independently-implemented extraction methods (raw-node x-column
   grouping; scattered-point Delaunay reinterpolation; real
   `matplotlib.tri` FEM triangle-connectivity interpolation, verified
   21795/21795 vertices coordinate-matched to the actual production
   mesh) all agree: away from the two channel-junction edges, the
   properly-integrated N_sheet(x) plateau (~1.5-1.7e12 cm^-2) matches
   the old centre-point value almost exactly — **this closes, with high
   confidence, the question of where the originally-reported ~800x
   figure came from**: purely the crude "apply the centre value over
   the WHOLE channel length" assumption, not a real distributed
   physical effect.
   The two ~0.15um edge zones themselves are a DIFFERENT, harder
   problem than "needs a better interpolator" — confirmed, not just
   suspected: with real FEM connectivity, N_sheet(x) genuinely crosses
   ZERO near the drain edge under this bias, and 99% of the whole
   -channel R_total then comes from the single sample nearest that
   zero-crossing. This is the `R = dx/(q·mu·N_sheet(x))` MODEL hitting
   a real mathematical singularity, not a mesh/interpolation artifact —
   confirmed because all three structurally-different methods broke
   down at the same location the same way. A local "all current flows
   through one inversion sheet" model is simply the wrong tool at a
   point with no net local inversion charge; no finer mesh or better
   interpolant fixes that. Also confirmed NOT safe: just discarding the
   edge zones and using the plateau alone (gives 5.11e-2A, close to the
   original 874x-too-high figure) — whatever the edge zones actually
   contribute is not negligible.
   Next step (named, not started): stop reconstructing current from
   density through the edge zones — read DevSim's OWN converged
   electron current density directly (its edge-current models along a
   few vertical cuts) instead, since DevSim's real drift-diffusion
   solve was never confined to a local-inversion-sheet assumption in
   the first place. Full writeup: search `docs/investigation_log.md`
   for "lateral sheet-density" and "MODEL BREAKDOWN CONFIRMED".
2. **LOCOS-on-LOCOS is blocked, not fixed.** A second LOCOS oxidation
   on a LOCOS-produced domain raises `NotImplementedError` (confirmed
   pre-existing hang/silent-corruption otherwise, not a regression).
   No workaround built.
3. **KOH/TMAH self-limiting V-groove not achieved.** The 2D
   crystal-frame bug is fixed (rate111/rate311 are no longer inert),
   but the model still does not hold a stable (111) facet — mask
   undercut is the leading hypothesis (fast `rate110` direction is
   vertical at the mask edge, widening the window faster than the
   slow facet can anchor). Root mechanism traced to ViennaLS-internal
   territory (`Advect`'s velocity-extension handling for a
   concave-corner-forming problem); not read at the C++ source level.
   TMAH itself is moot until this is resolved — its distinguishing
   parameter (`rate111`) has no traction on the simulated shape yet.
   Real TMAH rate constants were also never obtained (paywalled paper,
   blocked mirror, no ViennaPS data).

Minor/uncertain threads (not blocking, see investigation_log.md for
each item's own "what remains uncertain" section if you need it):
`pad_oxide_thickness_um`'s default only verified at one grid
resolution; `_AUTO_REFINE_MAX_RINGS=20` not stress-tested past 1e20
cm^-3; `dedupe_materials`/`filter_mesh_materials` only exercised for
one geometry/doping combination; `mask_spans_um` doesn't validate
spans against the domain extent; no GUI wiring for doping, gate_stack,
or the newer etch/deposition models.

## GUI

GUI visualization is not authoritative for process geometry — always
judge physical correctness from the actual ViennaPS mesh/output, never
from what's drawn on screen. The etch panel now renders the real,
floored, per-material mesh (boundary-traced solid silhouettes, not a
placeholder), for whichever of the 4 wired etch models is selected.

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
