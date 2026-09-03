# Dopant state unification — design

> Supersedes, for doping specifically, the state-carrier decisions in
> `2026-09-01-state-dependent-process-physics-design.md` §2 and the
> Stage A/B implementation that followed it. Does NOT touch that
> spec's §1 (`DiffusionModel` protocol), §3 (metal-contact axes), or
> §5-§8 — those stand as written. This document exists because Stage
> A/B, while individually verified, left two parallel and disconnected
> doping-state representations (`WaferState.dopant_profiles`, never
> populated by any live process step, and `ProcessResult.doping`,
> which the GUI actually threads) — discovered by gap analysis, not by
> a failing test.

## Scope

**In scope**: the STATE architecture only — how dopant information is
represented, accumulated, queried, and converted to a DevSim node
model. **Out of scope, explicitly**: any new profile-generation
physics (a real depth-aware diffusion model, ion-implant energy→range
physics). Both remain exactly the pluggable, not-yet-filled seam
`2026-09-01-...design.md` §1 already defined — this document changes
nothing about that seam's own boundary, only what sits underneath it
on the state side.

Reference validation case (state-representability only, not a physics
target): **Wu, Hamann, Ceballos, Chang, Solgaard, Howe, "Design and
fabrication of silicon-tessellated structures for monocentric
imagers", Microsystems & Nanoengineering 2, 16019 (2016), PMC6444745**
— independently fetched and confirmed against the published text
(2026-09-03). Its Figure 6 fabrication flow: 100 nm thermal SiO2 grown
+ patterned (n+ mask) → phosphorus predeposition (POCl3) + anneal
(1000°C/30 min) → second thermal oxidation + pattern (p+ window) →
B11 implant (20 kV, 5×10^15 cm^-2) → new 100 nm surface oxide → 20-min
drive-in (1000°C) → contact via etch → Ti(10 nm)/Pt(100 nm) metal,
liftoff. Used here only to check: can this architecture hold every
step's state without losing information? Not: does this architecture
reproduce this paper's numbers (no diffusion/implant physics model is
built in this pass, so it cannot).

---

## §1 THE STATE INVARIANT

```
    WaferState(t) -> Process Physics -> WaferState(t+1)
```

Every physical quantity `WaferState(t)` carries — geometry, material,
oxide thickness, PR/mask, every existing dopant profile, thermal
history — must, in `WaferState(t+1)`, be either:

- **(a) preserved**, if this step's physics does not affect it, or
- **(b) transformed according to real physics**, if this step's
  physics does affect it.

Never silently dropped; never replaced by an unrelated value for an
axis the step did not touch. "Preserved" means the PHYSICAL STATE is
preserved, not that a data structure was copied verbatim — where
geometry itself changes (etch, oxidation), what "preserved" means for
an axis anchored to that geometry must be re-derived consistently, not
assumed unchanged. **Pruning (actively deleting/clipping stored data)
is one possible implementation of this — never the invariant itself.**
A future model may instead remap/reinterpret state under a moved
surface; the invariant only requires the RESULT be physically
consistent, not that any specific algorithm be used.

## §2 `DopantProfile` — model-agnostic representation

```python
@dataclass(frozen=True)
class ThermalEvent:
    temperature_c: float
    time_s: float

@dataclass(frozen=True)
class DopantProfile:
    species: str
    polarity: Literal["donor", "acceptor"]
    concentration_at: Callable[[float, float], float]   # (x_um, y_um) -> cm^-3, ABSOLUTE domain coordinates, always
    host_material: str            # e.g. "Si" -- a gating HINT, not a provenance guarantee (see §4)
    model: str                    # which DopantSourceModel produced this profile
    model_params: Dict[str, Any]  # opaque to everything except that model's own re-processing function
    thermal_history: Tuple[ThermalEvent, ...] = ()   # RAW ledger — the primary stored fact
    source: Optional[Source] = None
```

`thermal_budget` (a scalar `ΣD(T)t`) is **removed as a stored field**.
It is a model-specific DERIVED convenience, computed from
`thermal_history` only by whichever model needs it (today: the V1
Gaussian broadening model's own D(T) lookup). This is a correction
from Stage B, where `thermal_budget` was stored directly — a real
finding from this session's own review: collapsing raw T(t) history
into one integral is provably sufficient for the V1 Gaussian model
alone, never claimed sufficient for any future model in general.

`model_params` is **not an unbounded metadata bag**. Contract: only
the `model`-tagged function that PRODUCED a profile (or its own
registered re-processing function, e.g. an anneal handler) may read or
interpret its `model_params`. No other code — not `doping_mapping.py`,
not the GUI, not another model's handler — may reach into
`model_params` directly. This is the fix for a real, identified gap:
Stage B's `peak_conc_cm3`/`peak_position_um`/`straggle_um` were
top-level `DopantProfile` fields, meaning every future model would
either misuse those Gaussian-specific names or grow the dataclass
forever (the same failure mode `DopingRegion` already exhibits).

**Never Gaussian-specific at the schema level.** Today's only
producing model (`model="gaussian_v1"`) happens to use a Gaussian
shape; the schema does not know or assume this. A future
`model="diffusion_erfc_v1"` or `model="lss_implant_v1"` profile is
representable with zero schema change — required acceptance criterion
for this document.

(Naming note for the implementer: `host_material` here plays the role
`DopingRegion.region` plays today, e.g. `"Si"` — not a new concept,
just renamed for clarity now that it is a gating field on
`DopantProfile` rather than a region label on `DopingRegion`.)

**`concentration_at` is a runtime evaluation interface, not the
canonical persistent representation.** The canonical, persistent facts
about a profile are `species`, `polarity`, `host_material`, `model`,
`model_params`, `thermal_history`, `source` — everything needed to
RECONSTRUCT an equivalent `concentration_at` closure at any later time,
by asking the `model`-tagged producing function to rebuild it from
`model_params` (which must therefore carry whatever anchoring
information the closure needs, e.g. an absolute position, per §5). A
bare Python closure is never the sole source of truth for a profile —
it must always be re-derivable from the persistent fields alone. (This
is a design contract only; no serialization mechanism is implemented
in this pass — it exists so one becomes possible later without a
schema change.)

## §3 Geometry-gated evaluation

**This is a three-way test, not a two-way one — `material != host_material`
does NOT by itself mean zero.** For a profile whose `host_material` is
`M`, evaluated at `(x, y)`:

1. **`exposed_material_at(x, y) == M`** — the profile genuinely
   applies here. Return `profile.concentration_at(x, y)` (a real
   calculation — itself possibly near-zero, §6 state B, but a real
   computed value either way).
2. **`exposed_material_at(x, y) != M`, and the change is a REMOVAL**
   (the process category responsible only ever takes material away —
   today, every registered etching model) → **Geometry-gated zero**
   (§6 state A). `M` genuinely no longer exists there.
3. **`exposed_material_at(x, y) != M`, and the change is a
   CONVERSION** (the process category responsible turns `M` into a
   DIFFERENT solid material in place — today, only oxidation's real
   Si→SiO2 mechanism, directly confirmed by ViennaPS measurement,
   evidence #2 below) → **`UNSUPPORTED_BY_MODEL`** (§6 state C),
   **never returned as 0** — unless a real dopant-fate/segregation
   model is registered for that specific `(M, new_material)`
   conversion pair (none exists in this project today).

**This is not computable from geometry alone.** `exposed_material_at`
by itself cannot distinguish case 2 from case 3 — this is exactly
§4's disclosed provenance limitation, restated at the query level.
The removal-vs-conversion classification must come from which PROCESS
CATEGORY most recently changed that location's material identity, not
from a bare before/after material-tag comparison. The precise
mechanism (e.g. a small, explicit per-category table —
`{"etching": "removal", "oxidation": "conversion"}` — recorded onto
`WaferState` by whichever code wires §9's
`WaferState.query(domain, dopant_profiles=...)` call, so a later query
can look it up without re-deriving it) is an implementation-plan
decision. What this document fixes is that the three-way distinction
is real and load-bearing: **no implementation may collapse case 3 into
case 2's zero just because they look identical from raw geometry
alone.**

(`acceptor_concentration_at` analogous; `net_doping_at` = donor −
acceptor, always DERIVED, never stored — see the partial-aggregate
contract at the end of §6 for what "derived" means when some
contributing profile is `UNSUPPORTED_BY_MODEL`.)

**Real evidence, kept separate by kind (do not conflate)**:
1. *Directly measured, real ViennaPS*: absolute domain-coordinate range
   is byte-identical before/after a chained oxidation step
   (`[-5.0000, 5.0000]` both times).
2. *Directly measured, real ViennaPS*: a fixed absolute coordinate
   `(x=0, y=0.15)` flips from `Si` to `SiO2` after oxidation consumes
   silicon there — proof that material CONVERSION shows up as a
   material-tag change at a fixed coordinate, which geometry gating
   detects for free, with zero new code in the oxidation step.
3. *Code/calculation verified, not a physical measurement*: a
   process-relative-depth placement function, given two different real
   mesh snapshots (different current-surface positions), computes two
   different absolute anchors for an identical "depth below current
   surface" specification — confirming the conversion responsibility
   split in §5 actually produces different results when the surface
   differs, and that an already-created profile's own anchor is never
   recomputed. (A specific surface-movement magnitude from one run,
   ~0.07 µm+, is cited only as a real, independently-observed reference
   number from evidence #2's own experiment — it is NOT the size the
   two anchors in THIS check differed by, and must not be presented as
   such. A separate run showing only ~0.0026 µm of movement under
   nominally the same recipe is recorded as a real-solver
   reproducibility/numerical-sensitivity observation, not a
   representative validation magnitude — real oxidation's CFL-retry
   dynamics are evidently sensitive run-to-run, consistent with this
   project's own already-documented "DevSim cross-solve sensitivity.")

**Acceptance criterion (invariant, not tied to any specific number)**:
identical process-relative specifications, created at different
current-surface positions, anchor to different absolute coordinates;
an existing profile's absolute anchor is never retroactively changed
by a later surface move.

## §4 Limitation — material identity ≠ material provenance

`host_material == currently-exposed material at (x, y)` is a NECESSARY
gating condition, never a provenance guarantee. **This schema does
not, in general, distinguish "this material has been here since before
the profile existed" from "this is NEW material of the same name,
later placed at a coordinate a REMOVED, differently-doped material
used to occupy."**

Concretely: geometry gating is correct for material REMOVAL (etch —
real ViennaPS confirmed) and for material ADDED ON TOP (deposition,
oxide growth — nothing already there needs to change). It is **not**
proven correct for: `P diffusion → Si etch → same-location Si
refill/epitaxy`. A refill of the same host_material into a
previously-vacated footprint can incorrectly resurrect the old,
already-removed profile there, since gating alone cannot tell the two
apart. **Refill/epitaxy and the dopant provenance question it raises
are UNSUPPORTED in this model.** The reference paper (Scope section
above) never exercises this path, so it does not block this
document's acceptance criteria — but this is a disclosed, real gap,
not a solved case. A
general fix (an active per-profile invalidation event, tied to
verified material removal, orthogonal to query-time gating) is
deferred as separate follow-up scope.

## §5 Absolute vs. process-relative coordinates — conversion responsibility

`DopantProfile.concentration_at` is **always** defined in absolute
domain coordinates (§3, evidence #1) — never "distance from the
current surface" or any other process-relative quantity.

**Responsibility split**: a `DopantSourceModel` (today's placeholder
Gaussian model; a future depth-aware diffusion or LSS-implant model)
is the ONLY place a process-relative quantity (depth below the current
surface, projected range from an implant's entry point) is ever
computed. It does so by querying the LIVE `WaferState`/geometry AT THE
MOMENT it creates a new profile, converting its own process-relative
physics into an absolute-coordinate closure exactly once. Once created,
a profile's absolute anchoring is immutable and is never retroactively
recomputed by a later process step, even one that moves the surface
elsewhere. (An anneal-family dispatch, §7, MAY update a profile's
`model_params` — e.g. widen a Gaussian's straggle — but that is an
explicit, separate operation, never an automatic side effect of a
later surface move.)

## §6 `UNSUPPORTED_BY_MODEL` ≠ `C(x, y) = 0`

Three states, never conflated:

- **(A) Geometry-gated zero** — real material genuinely absent at
  `(x, y)` right now (§3). A real, physically meaningful zero, based
  on real geometry.
- **(B) Model-computed zero** — the producing model's own
  `concentration_at(x, y)` genuinely evaluates near zero there (e.g.
  the tail of a Gaussian). A real, physically meaningful (if
  approximate) zero, from a real calculation.
- **(C) `UNSUPPORTED_BY_MODEL`** — no registered model/formula exists
  to compute a value at all for this profile in this situation (e.g. a
  dopant's fate through a material-conversion event with no
  segregation model, §4; a species with no D(T) citation). **Never
  returned or rendered as 0.**

Doping queries must expose, alongside any returned value, whether any
contributing profile is in state (C) at that point — reusing this
project's existing `physics_status`/`Resolution` accumulation pattern
rather than inventing a new one. **The GUI must render (C) visually
and textually distinct from both (A)/(B) and from "computation
complete"** — never blend an unsupported physics result into the
normal 0-concentration or done-state rendering. This follows directly
from CLAUDE.md's Core Physics Requirement.

**Partial-unsupported aggregate contract.** A doping query at `(x, y)`
never returns a bare float. Conceptually it returns:

```
donor_concentration: float     # sum over only the profiles actually computable here (states A/B)
acceptor_concentration: float  # same
net_doping: float              # donor - acceptor, from the above
physics_status: ...            # whether ANY contributing profile at this point was UNSUPPORTED_BY_MODEL (state C), and which
```

Example: at some `(x, y)`, a `P` profile is fully computable
(`+3e18`) while a `B` profile at the same point is `UNSUPPORTED_BY_MODEL`
(e.g. it sits in a region that underwent an unmodeled material
conversion). The query MAY still report `donor_concentration = 3e18`
as a real, computed partial sum — but `net_doping` at that point MUST
NOT be presented, logged, or rendered as a complete answer: the
`physics_status` for that point must say a contribution was skipped,
and every consumer (GUI, §10's per-node DevSim conversion) must check
`physics_status` before treating `net_doping` as ground truth there.
A GUI showing a "completed" NetDoping map, or §10 silently writing
`net_doping` into the DevSim node model, at a point with an
unsupported contribution — without surfacing the gap — is exactly the
"calculated as if computed" failure CLAUDE.md's Core Physics
Requirement forbids.

## §7 Anneal/redistribution is per-model dispatch, not a single function

`anneal_profile()` (Stage B) is reclassified: **model-specific
reuse/modify**, not general-purpose reuse. It is the dose-conserving
broadening formula for `model="gaussian_v1"` profiles ONLY. It must
never be invoked on a profile whose `model` tag it does not recognize.

`apply_thermal_anneal()` becomes a **dispatch function** with two
responsibilities:
1. Append this step's `(temperature_c, time_s)` as a `ThermalEvent` to
   EVERY existing profile's `thermal_history` — always, regardless of
   model (the raw fact that a profile lived through this thermal event
   is preserved even when nothing is done with it yet).
2. For each profile, look up a handler registered for its `model` tag
   and apply it (`anneal_profile()` for `"gaussian_v1"`; a future
   model's own handler for its own tag). A profile whose `model` has no
   registered handler keeps its `model_params` unchanged and is
   reported `UNSUPPORTED_BY_MODEL` for redistribution under this
   thermal event — never silently skipped without a record, never
   processed by the wrong model's formula.

A single anneal call may dispatch different profiles to different
handlers in the same pass (mixed-model anneal is not all-or-nothing).

The exact registration mechanism (a dict keyed by `model`, a decorator,
a `Protocol`) is an implementation-plan decision, not fixed by this
design — matching the base spec's own stated practice for
`DiffusionModel`'s registration shape.

## §8 GUI reuse — widgets only, never computed values

Reusable: widget layout, input fields, buttons, panel structure.
**Never reusable as-is: any displayed VALUE** — concentration, junction
position, profile depth, doping color. Every displayed value must
route through:

```
GUI input -> real DopantSourceModel -> WaferState -> real computed result -> GUI
```

A value a GUI element showed correctly against the OLD (Stage A/B)
compute path is not assumed still correct once the backend changes —
it requires re-validation against the NEW path specifically; "it used
to look right" is not evidence.

**Physics-parameter exposure gate**: a physics parameter (e.g. implant
energy) is not added to the GUI until a real, consuming compute model
is confirmed to read it and its value is confirmed to change the
computed result. A GUI field with no real model behind it is exactly
the "GUI graphic disconnected from the actual computed result"
CLAUDE.md's Core Physics Requirement forbids.

## §9 Eliminating the dual source of truth

`ProcessResult.doping` is reduced to **this step's raw declared
input only** — no longer a long-lived state carrier. The one
canonical, cross-step-threaded state is `WaferState.dopant_profiles`.
Every process step must, going forward:

```
prior_profiles = previous WaferState.dopant_profiles
this_step_profiles = dopant_profiles_from_doping_profile(result.doping)   # existing adapter, modified per §2
new_state = WaferState.query(domain, dopant_profiles = prior_profiles + this_step_profiles)
```

This closes a real, confirmed production bug found during gap
analysis: `tcad/process/etching/isotropic.py`'s own live call to
`WaferState.query(domain)` never passes `dopant_profiles=` at all —
the only production call site of `WaferState.query()` has been
doping-blind since Stage A shipped. Fixing this (extended to every
process category, not just isotropic etching) is itself part of this
document's scope, not a separate follow-up.

## §10 DevSim conversion — real per-node evaluation, not symbolic equations

Every existing NetDoping construction in this project builds a
symbolic `devsim.node_model(..., equation=...)` string. A masked,
multi-model, geometry-gated `net_doping_at(x, y)` cannot practically
be expressed as one such string. The replacement, confirmed to be
composed entirely of APIs already real and already used elsewhere in
this exact codebase:

```
xs_cm = get_node_model_values(device=, region=, name="x")   # already used, tcad/device/devsim/voltage_probe.py
ys_cm = get_node_model_values(device=, region=, name="y")   # already used, same file
values = [ WaferState.net_doping_at(x_um, y_um) for x, y in zip(xs_cm, ys_cm) ]  # real per-node Python evaluation
set_node_values(device=, region=, name="NetDoping", values=values)   # already used, semiconductor_equation.py / robust_iv_sweep.py
```

**Worked numeric example** (§10 requirement): two profiles — donor
(`P`, `concentration_at≡3e18` for `x∈[-1,1]`), acceptor (`B`,
`concentration_at≡1e18` for `x∈[-2,0]`), both `host_material="Si"`.
Three real mesh nodes:

| node (x, y) | exposed material | donor(P) | acceptor(B) | NetDoping |
|---|---|---|---|---|
| (−1.5, 0.1) | Si | 0 | 1e18 | **−1e18** |
| (−0.5, 0.1) | Si | 3e18 | 1e18 | **+2e18** (overlap) |
| (0.5, 0.1) | SiO2 (etched away) | 0 (gated, state A) | 0 | **0** |

---

## §11 Component classification (Stage A/B), with three independent validation axes

`Implementation status ≠ Physical validation status ≠ GUI validation
status` — never conflate them, and never record "tests pass" as
physical validation.

| Component | Classification | Implementation | Physical validation | GUI validation |
|---|---|---|---|---|
| `WaferState` geometry query (`exposed_material_at`, `_cells`) | Reuse | Implemented | Real ViennaPS (Stage A + this doc's own §3 experiments) | Doping-specific queries never wired to GUI at all (geometry-only rendering uses it today) |
| `dopant_profiles_from_doping_profile()` | Modify | Implemented (old shape) | Old shape: real DevSim cross-check exists; new (§2) shape: unverified | Not wired to GUI (test-only today) |
| `anneal_profile()` | **Model-specific reuse/modify** (§7) | Implemented, Gaussian-only | Real ViennaPS+DevSim (Stage B) | Live-verified — **scoped to `model="gaussian_v1"` only** |
| `apply_thermal_anneal()` | Modify → dispatch (§7) | Implemented as Gaussian-only dispatch | Gaussian-only case verified; multi-model dispatch unverified (design only) | Gaussian-only case live-verified |
| `DopingRegion.gaussian_terms` | Discard, concept absorbed | Implemented | Real DevSim (5.139e-14 rel. error) | Live-verified |
| `DopingProfile.kind: str` | Discard | Implemented (current production) | Each kind individually verified; **the cross-kind failure motivating discard was found by code reading, not a failing real test** | N/A |
| `doping_mapping.py` kind-branch equations | Discard → §10's algorithm | Not yet implemented | Unverified as assembled; **both underlying real APIs independently already verified in this codebase** | Not wired |
| new model-dispatch registry (§7) | New | Not yet implemented (design only) | Unverified | Unverified |
| GUI doping/anneal panel widgets | Reuse (widgets only, §8) | Implemented | N/A (UI layer) | Live-verified widgets; **displayed values require re-validation post-backend-swap** |
| GUI `_doping_color_segments` overlay | Discard, rewrite | Implemented | N/A | **Live-verified WRONG** — confirmed this session (multi-term case paints one flat incorrect color) |
| Regression infra / SDD workflow | Reuse | Implemented | N/A (infrastructure) | N/A |

### Counter-examples checked before finalizing (required gate, all traced)

1. **P diffusion → etch → N implant**: N is placed relative to the
   CURRENT (post-etch) surface (§5); P remains in the list, reading
   geometry-gated zero wherever etched. Real numeric demonstration:
   with a shallow first dopant and a trench deep enough to remove it
   entirely, the FIRST-applied species is fully erased inside the
   trench while the SECOND-applied species alone occupies it —
   swapping which species goes first flips the trench's net polarity
   entirely (a concrete, order-sensitive result, verified by
   construction against §3's mechanism).
2. **N implant → oxidation → P diffusion**: oxidation converts the Si
   that N's profile lives in into SiO2 (§3, evidence #2 — a real,
   directly-measured material-tag flip at a fixed coordinate). This is
   a CONVERSION (§3 case 3), not a removal — N's dopant fate there is
   `UNSUPPORTED_BY_MODEL`, never geometry-gated zero and never
   silently presented as a resolved "0." (P, diffused afterward on the
   current post-oxidation surface, is a separate, fully computable
   profile — its own contribution is real per §3 case 1, and the
   partial-aggregate contract at the end of §6 governs how the two
   combine at any point where both would contribute.)
3. **B implant → B implant → anneal**: already real-verified live
   (Stage B GUI screenshots, this session) — two same-species profiles
   never merge; both widen independently under dispatch (§7).
4. **P diffusion → oxide growth → oxide strip → anneal**: geometry
   gating alone (no special-cased "oxide strip" doping code) correctly
   re-exposes the untouched-P Si region beneath wherever oxide is
   later stripped — the profile's own closure never needed touching
   through the whole grow/strip cycle.
5. **Overlapping different-species profiles**: already real-verified
   live (Stage B GUI, B/P overlap) — each stays independent; NetDoping
   is only ever a derived sum (§10).
6. **Surface moves, then a new diffusion is created** (Section 4 gate):
   traced under §5/§7 — new profile anchors to the NEW surface; any
   later anneal dispatches this profile to a handler for its own
   `model` tag (§7), reporting `UNSUPPORTED_BY_MODEL` per-profile if
   none exists, never applying another model's formula to it.
7. **Two implants at different energies** (Section 4 gate): both
   coexist independently (§2, never merged) — but "energy" itself is
   NOT exposed in the GUI under this document, since no consuming
   model exists yet (§8's physics-parameter exposure gate).
8. **implant → anneal → etch → second implant** (Section 4 gate):
   profile_1 broadens under dispatch, survives etch except where
   geometry-gated to zero; profile_2 is created fresh, anchored to the
   POST-etch surface, with its own empty `thermal_history`. Final
   NetDoping at any node is the real per-node sum (§10) of both,
   through the real evaluation path — never a legacy shortcut for
   either.
9. **Refill after etch** (§4's own gate): explicitly disclosed as
   UNSUPPORTED — the one counter-example this document's mechanism
   does NOT survive, recorded rather than hidden.

---

## Migration note

This document does not itself introduce a new numbered "Stage" letter
in `2026-09-01-...design.md`'s own table (§8 there) — it is a
correction to that spec's §2 or, at the implementer's discretion when
writing the plan, a plan against a small addendum to §2. Whichever
form the plan takes, the base spec's §1 (`DiffusionModel` protocol),
§3 (metal contact), and §5-§8 remain unchanged and unaffected.
