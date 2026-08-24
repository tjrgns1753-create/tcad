# WaferState-driven physics resolution — design

Status: approved 2026-08-25. Implementation plan follows separately.

## The invariant this design exists to serve

> Not "a simulator that allows every order", but **"a simulator where
> every order can be run, and the result differs according to the actual
> wafer state at that moment."**

Both halves are required:

- **Runnable in any order** — no disabled button, no "run X first", no
  modal confirm that gates execution, no advice steering the user to a
  different step.
- **Results genuinely differ by state** — each step reads the real
  current wafer and computes from real physics.

Two orders of the same processes may legitimately produce different
results, and often must. The difference has to *arise* from the
materials, geometry, doping and resist that actually exist when the
second process runs — never from a rule that inspects which process ran
before. Writing `if previous_step == oxidation` violates the invariant
even when it produces the "right" answer.

Process orders appearing anywhere below are illustrations or test
inputs. **None of them is a supported-order list, a default flow, or a
rule.**

## Why this is two separate problems

| Problem | Question | State before this design |
|---|---|---|
| Order freedom | Does the GUI block the user? | Largely solved |
| Physical correctness | Does the process read the wafer? | Barely started |

Order freedom was addressed in earlier work. This design addresses the
second, which the audit found almost entirely absent: **no process step
queried the domain's actual material composition.** Every physical
parameter arrived from the recipe dict.

## Evidence base

Everything below was measured against real ViennaPS 4.6.2. CLAUDE.md's
own claims were deliberately not used as evidence.

### Gaps found

- **Etching is material-blind.** The GUI never sets `material_rates`, so
  `IsotropicProcess` takes its single-`rate` branch and removes every
  material at the same speed. Measured on a Si/SiO2/Si3N4/W stack: a
  0.2 um/s x 1.0 s etch removed W and Si3N4 at identical rates, taking
  exactly 0.2 um off the top.
- **Oxidation is material-blind.** After a W deposition, a Dry 1000 C
  oxidation grew `SiO2 [0.050, 0.059]` **on top of the tungsten** —
  thermal oxide cannot grow there; the metal seals the silicon.
- **Doping is not wafer state.** `DopingProfile` is consumed only under
  `tcad/device/devsim/` and `tcad/characterization/`; it never enters
  `tcad/process/`. In the GUI `last_doped_result` is set once and
  cleared only by NEW WAFER, so doping then etching leaves measurement
  solving the pre-etch geometry.
- **A model hardcodes a fresh wafer's materials.**
  `etching/fluorocarbon.py` fixes
  `_REQUIRED_MATERIALS = ("Mask", "Si", "Polymer")`. The same recipe that
  completes in seconds on a fresh wafer did not complete within 300 s
  after an oxidation put SiO2 in the domain.

### Capabilities confirmed

- **Oxidation IS state-driven with respect to existing oxide.**
  0.5 hr = 0.065 um; 0.5+0.5 chained = 0.080 um; 1.0 hr single =
  0.081 um. Chained matches single, and neither is 2x the half-time
  result — Deal-Grove slowing is real. This is the model the rest should
  reach.
- **WaferState is fully derivable from the live domain.**
  `getMaterialsInDomain()`, `getMaterialMap().getMaterialAtIdx(i)`
  (ordered stack), and `getLevelSets()` + `ToSurfaceMesh` /
  `ToVoxelMesh`. No new ViennaPS API, no reliance on the lossy export.
- **The domain is one object mutated in place.**
  `dep._inherited_domain is ox.last_domain` -> True;
  `dep.last_domain is ox.last_domain` -> True; re-reading
  `ox.last_domain` after the deposition shows the post-deposition stack.
- **`.vpsd` round-trip preserves what WaferState reads.** Stack order
  and exposed material both preserved; a further step runs correctly on
  the reloaded domain.

### Backend shapes the resolver must serve

| Shape | Models | What it needs |
|---|---|---|
| Rate table | `IsotropicProcess`, `DirectionalProcess`, `SelectiveEpitaxy` | `{Material: rate}` |
| Role slots | `PlasmaEtchingParameters` (`.Substrate/.Mask/.Passivation/.Polymer`), `CF4O2Parameters` (`.Si/.SiGe/.Mask`) | which real material plays which role, plus a constant block per slot (`A_ie, A_sp, B_ie, B_sp, Eth_ie, Eth_sp, beta_sigma, k_sigma, rho`) |
| Extensible per-material | `FluorocarbonParameters.addMaterial(...)` | one block per material actually present |
| Role setters only | `Oxidation` (`setSiliconMaterial/setOxideMaterial/setMaskMaterial`) | no per-material or spatial rate control exists |

`CF4O2Parameters` slots are fixed by **material name**, so a wafer
exposing W has nowhere to put it. That is not a missing constant; it is
the model being unable to represent the material — a distinct state.

## Architecture

```
live domain -> WaferState -> resolve(intent, state) -> ResolvedRecipe -> ViennaPS -> mutated domain
                                     ^
                     MaterialProperty + InteractionCoefficient
```

Resolution lives **inside `ProcessStep.run()`**, not in the worker's top
level and not in the GUI. Rejected alternatives:

- *Worker top level*: `run_flow` runs several steps per worker call, so
  a single top-level resolution would resolve step 2 against the state
  from before step 1 ran. Silently wrong for flows.
- *GUI, from the exported mesh*: the export is lossy (this project has
  documented material loss for LOCOS topology and floor clipping), and
  it would leave GUI, CLI and tests each resolving separately.

Inside `run()`, every caller shares one physics path and each step in a
flow resolves against its own correct intermediate state.

## §1 WaferState

A **query, not a stored object.** Recomputed at each step from the live
domain. Never cached as an independent source of truth; only a transient
per-step value shared within that step.

```python
@dataclass(frozen=True)
class WaferState:
    materials: tuple[str, ...]
    stack: tuple[LayerInfo, ...]        # innermost first
    grid_delta_um: float
    bounds: tuple[float, float, float, float]
    doping: DopingProfile | None

    def exposed_material_at(self, x) -> str | None
    def exposed_materials(self) -> frozenset[str]
    def thickness_of(self, material, x) -> float | None
    def under_resolved_x(self) -> tuple[float, ...]
```

### `materials` vs `exposed_materials` — different concepts

Measured: after an etch removes Si3N4 completely, the level set remains
with zero thickness and the material is still declared.

- `exposed_materials()` — spatially present at the surface **now**. This
  is what physics acts on.
- `materials` — declared/registered in the domain. Used for model
  registration (`addMaterial`), because backends fail on unregistered
  materials.

**Rule: never decide a physical result from the full `materials` set.**
Use what is spatially exposed. For oxidation this must be per-x, since
the exposed material varies along the wafer.

### Implementation: voxel-based, no arbitrary tolerance

`ToVoxelMesh` gives every cell a `'Material'` scalar holding the
level-set index, mapped through `getMaterialMap()`. Cells tile space, so:

- no x-sampling window (a cell's x-span either contains x or does not)
- no layer-thickness threshold (a zero-thickness layer simply has no
  cells)

The only discretization parameter left is the grid itself, which the
user already chooses.

### Verification: 8 geometries, two resolutions

Compared against an independent ground truth read from the exported
volume mesh.

| Geometry | grid 0.1 | grid 0.02 |
|---|---|---|
| bare Si | match | match |
| Si/SiO2 | match | match |
| Si/SiO2/Si3N4 | match | match |
| patterned PR | sub-grid mismatch | match |
| etched through | sub-grid mismatch | match |
| LOCOS | match | match |
| gate stack (5 materials) | match | match |
| mixed exposure along x | match | match |

The two mismatches at grid 0.1 were layers thinner than one cell
(0.065 um oxide and 0.03 um film). At grid 0.02 everything matches.

### UNDER_RESOLVED — a numerical warning, not missing physics

WaferState detects its own limit: at each x, measure level-set surface
separations and flag any layer thinner than `gridDelta`.

Measured, and it flags exactly the mismatching location and nothing
else:

```
grid=0.1  x=-4  separations=[0.1121, 0.9932]  under=[]        -> agree
grid=0.1  x= 0  separations=[0.0121, 0.0]     under=[0.0121]  -> disagree
grid=0.02 x= 0  separations=[0.0, 0.0]        under=[]        -> agree
```

This is a resolution diagnostic, kept on a **separate axis** from
physics status. Precedent exists in the project: `thermal.py` already
floors the seed oxide at `gridDelta` because "below one grid cell the
level-set can't resolve the interface".

## §2 ProcessIntent

What the user chose — a request, not a result.

```python
@dataclass(frozen=True)
class ProcessIntent:
    category: str
    method: str
    chemistry: str | None
    target_material: str | None
    parameters: Mapping
```

Deliberately carries **no per-material rates**. The user says "SF6/O2 for
30 s", not "SiO2 at 0.02 um/s".

## §3 Physics Resolver

```python
def resolve(intent: ProcessIntent, state: WaferState) -> ResolvedRecipe
```

Pure. Stateless. Does not touch the domain, does not call
`Process().apply()`, does not write files.

**There is no history parameter.** Order cannot influence the result
because no channel exists to carry it. This is the design's central
guarantee and it is enforced at the type level.

```python
@dataclass(frozen=True)
class ResolvedRecipe:
    backend_kwargs: Mapping
    resolution: Resolution
    entries: tuple[ResolvedValue, ...]   # per parameter: value, provenance, why
    under_resolved_x: tuple[float, ...]
    notes: tuple[str, ...]
```

### Oxidation's surface-material problem

`Oxidation` has no per-material or spatial rate control, so the resolver
cannot tell the backend "do not grow on metal". Three options, each
making a different physical claim:

1. No exposed Si anywhere -> run, growth zero, reason recorded. **Adopt.**
2. Some exposed Si -> not expressible today -> record UNKNOWN, run. **Adopt.**
3. Pass a non-Si material as the mask role -> **Reject.** Measured: a
   1.0 um Mask collapsed to `[-0.002, 0.006]`, this project's documented
   mask-erosion failure. That is inventing unverified physics.

## §4 Physics / Material Matrix — schema only

Constants are **not** filled in this design. Literature research is a
separate later step. The goal here is the structure that will hold them.

### Two tables, because the values differ in kind

```
MaterialProperty        intrinsic, condition-free
                        density, is_metal, oxidizable, crystal_structure

InteractionCoefficient  (material x chemistry/model x parameter)
                        always carries conditions
                        A_ie, Eth_sp, k_sigma, etch_rate, nucleation_delay, ...
```

Merging them would make condition-dependent coefficients look like
material properties.

### Every value is a record

```python
@dataclass(frozen=True)
class PhysicalValue:
    value: float | None          # None == UNKNOWN
    unit: str
    material: str
    chemistry: str | None
    conditions: Conditions
    source: Source | None
    resolution: Resolution
    provenance: Provenance
```

### Conditions are a window, not a point

```python
@dataclass(frozen=True)
class Conditions:
    temperature_c: Range | None
    pressure_pa: Range | None
    rf_power_w: Range | None
    gas_ratio: Mapping[str, Range] | None
    notes: str

    def covers(self, requested) -> Coverage   # INSIDE | OUTSIDE | UNSTATED
```

A cited constant used **outside** its measured window is downgraded to
`UNVERIFIED` for that use. A source that states no conditions is
`UNSTATED` and is never promoted to `VERIFIED`. This is what prevents a
single number from being treated as an absolute material property.

### Two orthogonal axes

```python
class Resolution(Enum):     # how settled is this resolution
    VERIFIED
    UNVERIFIED
    PARTIAL
    UNKNOWN
    UNSUPPORTED_BY_MODEL

class Provenance(Enum):     # where did the value come from
    LITERATURE
    BACKEND_DEFAULT
    USER_SUPPLIED
    DERIVED
```

| Provenance | Resolution | Meaning |
|---|---|---|
| LITERATURE | VERIFIED | cited, used inside its window |
| LITERATURE | UNVERIFIED | cited, used **outside** its window |
| BACKEND_DEFAULT | UNVERIFIED | ViennaPS's own default — not a guarantee for this material |
| USER_SUPPLIED | UNVERIFIED | caller supplied it; this project has not verified it |
| (none) | UNKNOWN | no value exists |

`LITERATURE + UNVERIFIED` is why the axes must be separate — a single
enum cannot express it.

**`USER_SUPPLIED` is not a quality judgement.** The user may have
entered measured data. It means only: this project has not verified it.

### Combination rule

| Lookups | Result |
|---|---|
| all VERIFIED, all in-window | `VERIFIED` |
| some resolved, some UNKNOWN | `PARTIAL` |
| all UNKNOWN | `UNKNOWN` |
| any UNVERIFIED (including out-of-window) | `UNVERIFIED` |
| model cannot represent the material | `UNSUPPORTED_BY_MODEL` |

`UNDER_RESOLVED` is **not** combined. It is numerical, comes from
WaferState, and travels on its own axis.

### UnknownPolicy — declared, never disguised

```python
class UnknownPolicy(Enum):
    OMIT             # do not set; model uses whatever it has
    BACKEND_DEFAULT  # pass the backend's default explicitly
    INERT            # zero
```

**Not decided in this design.** Each is itself a physical claim (`INERT`
asserts the material does not etch), so whichever applies, the result
still carries `UNKNOWN` and records which policy was used. No path
presents an unknown as verified.

### The table ships empty

Only values with real citations go in; everything else resolves to
UNKNOWN. Side effect worth having: the UNKNOWN path becomes the
most-exercised path rather than a rare branch.

### Data needed per process

| Process | Data | Kind |
|---|---|---|
| Etching | per-material rate or yield constants, mask erosion | Interaction |
| Deposition | growth rate, nucleation per surface, conformality, selectivity | Interaction |
| Metallization | as deposition + adhesion / silicide formation | Interaction |
| Oxidation | `oxidizable`, Deal-Grove coefficients, crystal orientation | Material + Interaction |
| Doping | ion stopping power, projected range, masking thickness | Interaction |
| Lithography | none (geometric state transition) | — |
| LOCOS | oxidation + mask elastic constants | Material + Interaction |
| Device measurement | DevSim's domain, out of scope here | — |

## §5 ProcessStep integration

```python
def run(self, recipe, output_dir):
    module   = session.require_viennaps()
    geometry = self.prepare_domain(recipe)   # domain settled, remask applied
    state    = WaferState.query(geometry)    # exactly once per step
    resolved = resolve(intent_from(recipe), state)
    model    = build_model(module, resolved) # the ViennaPS boundary
    module.Process(geometry, model, duration).apply()
```

**After `prepare_domain()`** because remask inserts the resist level set;
querying earlier would hide the resist from physics, and the resist is
part of the state physics must see.

**Once per step** — this is the transient cache. It does not leave the
step. The in-place mutation measurement makes this mandatory: a
WaferState held across steps would describe a domain that has since
changed underneath it.

The **ViennaPS boundary** is model construction. Only
`resolved.backend_kwargs` crosses it.

### Compatibility with existing recipes

| Recipe carries backend values (`material_rates`, ...) | honored; `Provenance.USER_SUPPLIED`, `Resolution.UNVERIFIED` |
| Recipe does not | resolver fills from the table |

This is the migration bridge: every existing test that specifies rates
keeps passing unchanged, while the result honestly records that the
number came from the caller rather than from a citation.

### Status propagation

```
resolve() -> physics (Resolution x Provenance x per-parameter reasons)
          -> numerical (under_resolved_x)   [separate axis]
     -> ProcessStep.run() result dict
     -> build_process_result() -> ProcessResult
     -> worker JSON payload            [strings and plain dicts only]
     -> GUI log and result display
```

`ProcessResult` gains fields additively, the same way `domain_state_path`
and `structure` were added.

Minimum recorded: which (process x material x parameter) was UNKNOWN,
which `UnknownPolicy` applied, how far outside its window a value was
used, and which model cannot represent which material.

### resume / `.vpsd`

No special handling. WaferState queries whatever `prepare_domain()`
returns and never asks whether it was live or reloaded. Verified by
round-trip measurement.

### LOCOS replay

Replayed steps each query their own state at their own moment. The
resolver has no input that could distinguish replay from resume, so the
LOCOS replay exception stays a GUI execution-path concern and does not
reach physics.

## §6 Test design

### T1 — structural: no channel for order

`resolve(intent, state)` has no history parameter, and `tcad/physics/`
references no history-bearing symbol. If no channel exists, order cannot
affect the result. Zero runtime cost.

### T2 — convergence: same state, different route, same resolution

Reach the same exposed state by different routes; assert `resolve()`
output is identical. A difference means history is leaking.

### T3 — split into two kinds, deliberately

**T3a — independent physics.** Relations that hold regardless of our
constants:

| Process | Reference | Basis | Measured |
|---|---|---|---|
| Oxidation | Si consumed / oxide grown = 0.44 | molar volume ratio | 0.434 / 0.437 / 0.439 at 0.5 / 1.0 / 2.0 hr |
| Oxidation | time additivity | time-invariant ODE | 0.39 % |
| Etching (isotropic) | undercut = vertical depth | definition of isotropy | not yet measured |
| Deposition (isotropic) | horizontal = vertical thickness | definition of conformality | not yet measured |

The stoichiometric ratio comes from molar volumes, not from any rate
constant, and it is stable across times — the signature of a real
constraint rather than a fitted value.

**T3b — transmission fidelity only.** Verifies that the number
`resolve()` produced is the number ViennaPS applied. Every such test
states in the file: *this test does not verify the resolver's numerical
correctness; it verifies resolver-to-backend transmission consistency
only.* This label isolates any test that would otherwise check its own
numbers against itself.

### T4 — permutation sweep

**The permutations are a fuzz generator, not a process-order
specification. No permutation is a "normal" order.** This must be stated
in the test file itself.

```
N intents -> generate permutations -> per step record
             (exposed_materials, intent, resolved_kwargs)
          -> assert: equal (exposed_materials, intent) => equal resolved_kwargs
```

Cost control: exhaustive for small N (3-4, i.e. 6-24 flows); beyond
that, **deterministic seeded random permutations** with the seed pinned
in the test so failures reproduce. Compose sweeps from fast processes;
include oxidation sparingly.

### T5 — UNKNOWN propagation

Empty table resolves to UNKNOWN and **the step still runs**; UNKNOWN
survives the worker JSON boundary to the GUI; `UNDER_RESOLVED` arrives
on its own axis; the applied policy is recorded.

### Testing rule derived from measurement

The domain is mutated in place, so before/after comparison must **not**
hold a reference — export or persist to `.vpsd` and compare. A test
written without this rule silently reports "no change".

## §7 Migration

Risk is deferred: stages 0-2 change no results, so the risky stage lands
on already-proven plumbing and a regression is immediately attributable.

| Stage | Content | Result change | Verified by |
|---|---|---|---|
| **0** | WaferState + status types added, called by nobody. Plus the two stale-state fixes below. | none | 8-geometry harness |
| **1** | Status plumbing end to end, everything reporting empty/UNKNOWN | none | T5 — proven before physics depends on it |
| **2** | Resolver on the real path, **table empty**, compat mode honors existing values | none | T1, T2, T4, full regression |
| **3** | First real physics: etch selectivity for one chemistry with cited constants | **first change** | T3a, T3b, re-measurement |
| **4+** | Remaining processes | per stage | as above |

### Stage 0 prerequisites — existing invariant violations

| Issue | Effect |
|---|---|
| `run_gate_stack` does not clear `last_domain_state` | a later RUN resumes the **pre-gate-stack** wafer |
| `last_doped_result` is stale after a later step | measurement solves the **pre-etch** geometry |

Both directly violate "read the current state" and are fixed first.

### Updating existing tests

Physics wins. Tests that specify `material_rates` pass unchanged via the
compat path. Tests that pin numbers produced by material-blind behavior
are re-measured and updated, each with its reason recorded. No test is
"fixed" by reverting physics.

Which tests actually change cannot be known until constants exist;
listing them now would be guessing.

## Physics not supported (honest list)

| Item | Reason |
|---|---|
| doping-enhanced oxidation | `Oxidation` has no doping or spatial rate API (measured) |
| suppressing oxidation on metal | only three role setters; passing non-Si as mask collapses the mask (measured) |
| CF4/O2 on materials other than Si/SiGe/Mask | slots fixed by material name -> `UNSUPPORTED_BY_MODEL` |
| sub-grid layers | level-set resolution limit -> `UNDER_RESOLVED` |
| all physical constants | table ships empty -> separate research step |

## Still unverified

- The 13 registered models have not all been mapped onto the four
  backend shapes (`bosch_drie`, `faraday_cage`, `ion_beam`, atomic layer
  processes).
- Whether T2 holds within discretization error has not been measured.
- T4 permutation sweep cost has not been measured.
- Isotropic undercut and conformal-thickness relations (T3a) have not
  been measured.

## Next steps

1. Implementation plan (writing-plans), reviewed before any code.
2. Implementation stage by stage (executing-plans).
3. **Separate physics-data research step** — with the schema in place,
   filling constants becomes data entry with sources and conditions, and
   needs no code change. It can proceed independently.
