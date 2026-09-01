# State-dependent process simulation — design

Status: draft, pending user approval. Extends and constrains
`docs/superpowers/specs/2026-08-25-wafer-state-physics-design.md`
(hereafter "the base design") — this document does not replace or
weaken anything there; §1-§5 below are additive.

## The name of the thing this design builds

This is **not** an "interaction coefficient expansion." Framing it that
way was tried and explicitly rejected during brainstorming. The correct
name is **state-dependent process simulation**:

```
WaferState(t)  ->  Process(t)  ->  Physics model  ->  WaferState(t+1)
```

Every process step is a function of the CURRENT wafer state, not of
which processes ran before it and not of a lookup table keyed by
process pairs. A process never asks "did oxidation run before me" —
it asks "what does the wafer look like right now" (which materials
are exposed where, how thick is each layer, what dopants exist at
what concentration and species, what cumulative thermal budget has
each of those dopants already received) and computes real physics
from that. `INTERACTION_COEFFICIENTS`, as already scoped in the base
design, holds only intrinsic (material x chemistry x condition)
physical constants — e.g. "diffusivity of phosphorus in silicon at
900 C" — and is never keyed by a pair of process categories. **No
code introduced by this design may contain a table, dict, or
conditional keyed by `(prior_process, next_process)`.** That is the
one rule everything else here exists to serve.

The direct consequence: running the same processes in a different
order can, and often must, produce a different final WaferState — not
because the simulator special-cases order, but because each process
genuinely reads a different state depending on what already happened.
`A -> B -> C` and `A -> C -> B` are expected to diverge when B and C's
real physics are order-sensitive (e.g. whether metal lands on exposed
silicon or on oxide), and expected to agree when they are not (e.g.
two independent blanket depositions on disjoint regions). Neither
outcome is hardcoded; both fall out of each step reading real state.

## Scope discipline

This is not an attempt to build commercial-TCAD-grade physics from
scratch. The goal is narrower and concrete: using the real physics
engines this project already has (ViennaPS for topography/transport,
DevSim for the electrical solve), make each process step's result
become the next process step's real initial/boundary condition — for
the specific physical relationships the reference case below actually
exercises. Physics this project's engines cannot compute is reported
as `UNKNOWN` or `UNSUPPORTED_BY_MODEL` (both enum values already exist
in the base design's `Resolution` type — no new enum is introduced
here), never faked.

## Reference case: this is not a recipe

Every process sequence used as an example below comes from one real,
cited source (arXiv:2407.13705, Appendix A, "pn junction" paragraph —
quoted verbatim in §6). It is used exactly once, as a **physical
validation case**: if this design's mechanism is correct, running
these specific steps in this specific order through this project's
resolver should reproduce the qualitative physical outcomes the paper
reports (dopant confined to oxide-opened windows, no contact where
metal sits on oxide, a p-stop ring only where implanted). **No code
introduced by this design may special-case this paper's step order,
step count, or parameter values.** A test that only passes because it
recognizes "this is the PN-diode sequence" is a bug in the test, not a
validation of the design. Per CLAUDE.md's own standing rule: process
order is never hardcoded, enforced, or suggested, in any process
category, ever — this design adds no exception to that rule.

---

## §1 Diffusion physics as a pluggable model layer

### Why this needs a model boundary at all

`tcad/physics/doping.py` today has no representation of dopant
diffusion as a **physical, time/temperature-driven process** — every
existing doping kind (`uniform`, `step_junction`, `gaussian_implant`,
`implant_windows`) takes its profile shape directly from
caller-supplied numbers (peak concentration, position, width). This
design adds one new doping kind, `thermal_diffusion`, whose profile
shape is **derived** from real diffusion physics instead of specified
by the caller. Doing that correctly requires a component with a real
mathematical model behind it, which is a different kind of thing from
the other doping kinds — hence its own interface.

### Model boundary — the point the user requires

```python
class DiffusionModel(Protocol):
    def diffuse(
        self,
        existing_profiles: tuple[DopantProfile, ...],  # everything already in the wafer, ALL species
        new_dopant: DopantSource,                       # species, source concentration/dose, where introduced
        boundary: BoundaryCondition,                     # per-x barrier thickness the dopant must cross (see below)
        conditions: Conditions,                           # temperature, time — from the base design's schema
    ) -> tuple[DopantProfile, ...]:                       # every profile, new and re-diffused
        ...
```

Supporting types, sketched here so the signature above is not
ambiguous (final shape is an implementation-plan decision, not fixed
by this design):

```python
@dataclass(frozen=True)
class DopantSource:
    species: str
    polarity: Literal["donor", "acceptor"]
    surface_concentration: PhysicalValue   # constant-source predep case
    dose: PhysicalValue | None             # limited-source / implant case
    x_range_um: tuple[float, float]        # where this source is applied (e.g. window extent)

@dataclass(frozen=True)
class BoundaryCondition:
    barrier_thickness_at: Callable[[float], float]  # x_um -> WaferState.thickness_of("SiO2", x_um)
    barrier_material: str                            # "SiO2" in the reference case; not hardcoded to it
```

`Conditions` (temperature, time) is the base design's own type,
reused unchanged.

**V1 implementation — `AnalyticalDiffusionModel`.** Closed-form
solutions to Fick's second law under the two standard boundary
conditions real fabs use and this reference case exercises:

- constant-source (predeposition): complementary error function
  (`erfc`) profile, parameterized by `sqrt(D * t)`.
- limited-source (drive-in): Gaussian profile, same parameterization.

`D` (diffusivity) comes from `INTERACTION_COEFFICIENTS`, keyed by
`(species, host_material, temperature_range)` — an intrinsic physical
constant, filled only with real citations, exactly like every other
entry in the base design's tables. **Not yet filled**: this design
does not itself supply a diffusivity number for phosphorus or boron in
silicon at these temperatures — that is a literature-data task (per
the base design's own "separate physics-data research step") to
complete before `thermal_diffusion` can produce a real number instead
of `UNKNOWN`. Recorded here as an explicit open item, not guessed.

**This is explicitly not the final diffusion model.** The `Protocol`
boundary exists so a future `NumericalDiffusionModel` — a real
finite-difference/finite-volume time integration of Fick's second law,
handling arbitrary non-constant boundary conditions, multi-species
cross-interaction, and non-uniform starting profiles that no
closed-form solution covers — can be substituted with **zero change**
to `WaferState`, `resolve()`, or any `ProcessStep`. Nothing outside
`tcad/physics/diffusion/` may depend on which implementation is
active. This is the seam the user asked for; treat replacing
`AnalyticalDiffusionModel` with a PDE solver as a drop-in swap, not a
redesign, when that becomes necessary.

### Oxide as a diffusion barrier — real physics, not a flag

`BoundaryCondition` is derived from `WaferState.thickness_of("SiO2", x)`
at every x, not from a boolean "is this window open." The standard
textbook treatment (dopant diffusivity in SiO2 is orders of magnitude
lower than in Si, so a sufficiently thick oxide is an effective mask
within a given anneal's `D*t` budget) becomes a real per-x check: at
each x, compute how far the dopant would diffuse INTO the oxide given
its own (much smaller) diffusivity in SiO2 over the same time/temperature,
and compare that penetration depth against the oxide's actual measured
thickness there. Thinner oxide (a partially-etched region, per §6 step
4a below) is a real, different boundary condition from zero oxide or
full oxide — not a third hardcoded case, but the same formula
evaluated at a different measured thickness. The SiO2 diffusivity
constant is itself an `INTERACTION_COEFFICIENTS` entry, subject to the
same "cited or UNKNOWN" discipline as the Si one.

### Cumulative thermal history — scoped explicitly, not solved in full

**The requirement, restated precisely:** `P implant -> anneal -> N
implant -> anneal` — the second anneal must be able to further diffuse
the ALREADY-EXISTING phosphorus profile, not only the newly-introduced
nitrogen/arsenic one. A dopant's diffused width depends on the total
`D*t` it has ever accumulated across every thermal exposure it has
lived through, not only the step that introduced it.

**Mechanism.** Every `DopantProfile` (see §2) carries a `thermal_budget`
value — the running `sum(D(species, host, T_i) * t_i)` across every
thermal event that profile has been subjected to. A `thermal_diffusion`
step, run against a WaferState that already contains N existing
profiles, must:

1. Compute this step's own `D*t` contribution for **every** species
   already present in `existing_profiles` (each species has its own
   diffusivity — phosphorus and boron do not diffuse at the same rate
   under the same anneal), not only for the dopant it is nominally
   introducing.
2. Add that contribution to each existing profile's `thermal_budget`
   and recompute its erfc/Gaussian shape at the new, larger `D*t`.
3. Introduce the new dopant's own profile with its own fresh
   `thermal_budget` starting from this step's conditions.

**V1 scope boundary — stated explicitly, not left implicit.** Only
process steps that are explicitly a diffusion/anneal doping kind
contribute to `thermal_budget` bookkeeping in V1. **Thermal oxidation
(1025 C in the reference case) does NOT, in V1, add to any existing
dopant's `thermal_budget`**, even though it is real, significant
thermal exposure that a real fab's dopants would also diffuse under.
This is a known, real physical omission — reproducing it correctly
would mean every thermally-significant process category (oxidation
today; potentially others later) feeds the same shared budget
mechanism, which is a materially larger integration than this pass
takes on. It is recorded here as `UNSUPPORTED_BY_MODEL` for "dopant
diffusion driven by a non-anneal thermal step," not silently absent.
A future stage extending `thermal_budget` contribution to oxidation
(and any other high-temperature category) is the natural next step
once this V1 mechanism is proven on the anneal-only case.

---

## §2 Doping state: process layer keeps species and polarity; device layer converts once

### Why a single scalar is wrong

An earlier draft of this design proposed `WaferState.doping_at(x) ->
float`. Rejected: a signed net-doping scalar cannot represent "this
region already has both a donor and an acceptor species superposed"
(which the reference case's p-stop-under-cathode-adjacent-n+ geometry
is exactly an instance of), cannot preserve which species is present
(needed for diffusivity lookups — each species has its own `D(T)`),
and conflates a process-layer physical fact with DevSim's own
NetDoping representation, which the user explicitly requires be kept
separate.

### Process-layer representation

```python
@dataclass(frozen=True)
class DopantProfile:
    species: str                         # "P", "B", "As", ... — real chemical identity, never discarded
    polarity: Literal["donor", "acceptor"]
    concentration_at: Callable[[float, float], float]   # (x_um, depth_um) -> cm^-3
    thermal_budget: float                 # cumulative D*t this profile has experienced, cm^2 (see §1)
    source: Source | None                 # which process step created/modified it; provenance only
```

`WaferState` carries `dopant_profiles: tuple[DopantProfile, ...]` — a
sequence, because multiple species and multiple regions coexist and
superpose (the existing `implant_windows` superposition semantics,
generalized). New `WaferState` query methods, matching the existing
`exposed_material_at` / `thickness_of` pattern:

```python
def donor_concentration_at(self, x_um, depth_um) -> float      # sum over donor profiles
def acceptor_concentration_at(self, x_um, depth_um) -> float   # sum over acceptor profiles
def net_doping_at(self, x_um, depth_um) -> float               # derived: donors - acceptors
def dopant_profiles(self) -> tuple[DopantProfile, ...]         # raw, species-preserving access
```

`net_doping_at` is a **derived convenience**, computed on demand from
the two signed sums — never a stored field that could drift out of
sync with the underlying species data.

### Device-layer conversion happens exactly once

DevSim's `NetDoping` node-model expression is built from
`WaferState.dopant_profiles()` (or the equivalent carried on
`ProcessResult`/`DopingProfile`) **only** at DevSim import time, inside
`tcad/device/devsim/mesh_import.py` / `apply_doping()` — the same
place this already happens today. Nothing upstream of that boundary
(`WaferState`, `resolve()`, `DiffusionModel`, any `ProcessStep`) ever
computes, stores, or reasons about a plain signed net value. This is
the "process layer preserves real dopant/process information; device
layer converts to what it needs" separation the user requires, and it
costs nothing new architecturally — `apply_doping()` already builds a
NetDoping expression from a `DopingProfile`; this design changes what
feeds that function (real per-species `DopantProfile` tuples instead
of a single donor/acceptor peak-concentration pair per region), not
where the conversion happens.

---

## §3 Metal-semiconductor electrical contact — three independent axes

### The three axes, restated with the correction

**Axis 1 — Physical geometry/material.** Does metal exist at this
(x, y)? Fully answerable today from `WaferState`/the real ViennaPS
mesh — no new mechanism needed.

**Axis 2 — Electrical contact candidacy.** Determined from the
**current, final accumulated geometry** — does a metal region share a
real mesh boundary/interface with a semiconductor region, evaluated
on the state as it exists now, regardless of which step created that
adjacency. This is the corrected version of an earlier, wrong proposal
in this design's brainstorming (that axis 2 should be decided from
"was Si exposed at the exact moment metal was deposited" — a
process-history-based test). The user's correction: **history is
auxiliary diagnostic information, never the determining input.**
Concretely, for `Al / SiO2 / Si` (metal deposited over oxide, oxide
never opened there): Axis-1 says Al geometry exists; Axis-2 must say
NO electrical contact, because the CURRENT interface at that location
is `Al-SiO2`, not `Al-Si` — and this must be true however Axis-2 is
computed, from present geometry, not from a remembered deposition
history. Where an `Al-Si` interface genuinely exists in the current
mesh (a window that was open when metal landed, or one later exposed
by any other means — the mechanism must not care which), Axis-2
reports a contact candidate.

**Mechanism.** Generalizes the interface-detection machinery already
shipped in `tcad/device/devsim/mesh_import.py`
(`interface_region_pairs` / `ImportedDevice.interfaces`, added by the
electrode-pin-dc-sweep plan's final-review Fix 3, which today checks
only a hardcoded `Si_SiO2_interface` case) to **any** (metal, exposed
semiconductor) region pair present in the mesh, reporting every real
metal-semiconductor interface it finds, not just one hardcoded name.

**Axis 3 — Model capability.** Whether the ACTUAL electrical behavior
of a real Axis-2 contact — ohmic vs. Schottky, barrier height,
contact resistance, alloying from a sintering anneal (§6 step 9) — can
be computed by this project's current ViennaPS+DevSim coupling.
**Today: no.** Every DevSim contact this project creates is declared
as an ideal voltage-source or ground contact; no work-function,
barrier-height, or contact-resistance model is wired anywhere. Axis 3
must report `UNSUPPORTED_BY_MODEL` for these specific electrical
questions whenever a real Axis-2 contact is found — it must never
silently default to "ohmic" or fabricate a resistance value. This is
also where the material-representation gap belongs on record: ViennaPS
4.6.2's `Material` enum, as this project already discovered and
documented, has no `Al` entry — so a real implementation of the
reference case's aluminum metallization would need to substitute a
different metal tag for the GEOMETRY (Axis 1), while any Axis-3
electrical claim specific to aluminum's real work function is
`UNSUPPORTED_BY_MODEL` regardless of which tag stands in for it.

---

## §4 Integration point — unchanged from the base design

Resolution still lives inside `ProcessStep.run()`, exactly as the base
design's §5 specifies (`WaferState.query(geometry)` once per step,
immediately after `prepare_domain()`). This design changes **what**
`WaferState` can express (dopant species/polarity/thermal-budget, in
addition to materials/geometry) and **what `resolve()` is now
forbidden from doing** (no process-pair table, per the opening
section) — it does not move or duplicate the integration point, and it
does not add a second place where physics gets decided.

---

## §5 SUPPORTED / UNKNOWN / UNSUPPORTED_BY_MODEL discipline

No new enum. The base design's `Resolution` type already has the
values this needs (`VERIFIED`/`UNVERIFIED`/`PARTIAL`/`UNKNOWN`/
`UNSUPPORTED_BY_MODEL`). This section is a restatement of the
requirement that every NEW physics surface this design introduces
follows that same discipline without exception:

| New surface | Reports UNKNOWN when | Reports UNSUPPORTED_BY_MODEL when |
|---|---|---|
| Diffusion masking by oxide thickness | `D(species, SiO2, T)` has no citation yet | never — this is representable once data exists |
| Cumulative thermal budget | — | contribution from a non-anneal thermal step (V1: oxidation), per §1 |
| Dopant dose/energy -> profile (ion implant) | conversion constants uncited | — |
| Metal-semiconductor Axis 2 (contact exists) | — | never — this is geometric fact, always computable |
| Metal-semiconductor Axis 3 (ohmic/Schottky/resistance/alloying) | — | always, today — no model exists at all |
| Interface fixed-charge / trap density effects | — | always, today — no model exists at all |

A caller receiving `UNKNOWN` or `UNSUPPORTED_BY_MODEL` still gets a
real, completed simulation of everything that IS representable — per
CLAUDE.md's standing rule, the step still runs and the gap is recorded,
never silently substituted with an invented number.

---

## §6 Reference validation case, with causal explanation

Source: **Design, fabrication and testing of Al/p-Si Schottky and pn
junctions for radiation studies**, arXiv:2407.13705 (2024), Appendix A.
Quoted directly (HTML edition, `arxiv.org/html/2407.13705v1`, fetched
2026-09-01):

> "pn junction diode fabrication began with the growth of 150 nm of
> thermal oxide in a dry oxygen ambient at 1025 C. This oxide provides
> surface passivation and serves to mask the phosphorus diffusion used
> to form the junction. Oxidation was followed by an in-situ nitrogen
> ambient anneal for 20 minutes to reduce oxide fixed charge. Contact
> photolithography with wet etching was then used to open windows
> through the oxide for phosphorus diffusion to form large circular n+
> cathodes. Oxide was left on the wafer backsides as a diffusion mask.
> Diffusion was carried out from a POCl3 vapour source diluted in
> nitrogen at 900 C for 5 minutes. Processing then split into three
> different paths for guard ring (GR) formation. For p-stop GR samples
> photolithography with plasma etching was used to thin the oxide to
> 20 nm in annular rings surrounding the cathodes. B+ ions were
> implanted through the thinned oxide at 3x10^13 cm^-2 dose and 20 keV
> energy to form a region of enhanced p-type doping preventing surface
> inversion. Photoresist was left in place to mask the implant. The
> implant was annealed at 900 C for 10 minutes in nitrogen. For
> non-isolated GR samples oxide was completely removed in the annular
> ring, but these samples were not implanted. For isolated GR samples
> no additional processing was done at this stage. After etching 1%
> hydrofluoric acid to hydrophobia to clear oxide from contact windows.
> A 750 nm aluminum layer was then deposited on the front of all
> samples by e-beam evaporation. Photolithography with wet etching in
> hot phosphoric acid was used to pattern the aluminum. Swabbing with
> hydrofluoric acid was then used to remove oxide from the wafer backs,
> after which 500 nm of aluminum was deposited by e-beam to create a
> back contact. Contacts were sintered in pure hydrogen at 400 C for
> 10 minutes."

Note on interpretation: this document's own numbering below groups the
quoted text into discrete steps for analysis. That grouping is an
analytical convenience, not a claim that the paper enumerates steps
this way, and the resulting table is not to be read or implemented as
an ordered `list[ProcessStep]` this project executes as a unit.

### Step 1 — Thermal oxidation (150 nm, dry O2, 1025 C)

- **Initial WaferState**: bare p-type Si (epitaxial, per the paper's
  wafer description elsewhere in the same document), no oxide, no
  resist, no dopant beyond epi background.
- **Physical phenomenon**: Deal-Grove thermal oxidation.
- **Why this step's physics does not depend on any prior process**:
  there is no prior process — this is the first step in the reference
  case, but structurally the SAME resolve() call would run identically
  starting from any WaferState exposing bare Si, at any point in a
  user's chosen sequence.
- **State variables changed**: `SiO2` thickness at every x becomes
  150 nm (uniform, no mask exists yet); `Si` recedes by the
  stoichiometric ratio this project already verified (~0.44, T3a in
  the base design).
- **What becomes input to the next process**: the resulting
  `WaferState.thickness_of("SiO2", x)` map — nothing else about HOW it
  was grown (temperature, ambient) is needed downstream; only the
  resulting geometry is.
- **ViennaPS**: yes — real Deal-Grove growth, already implemented and
  verified (`tcad/process/oxidation/thermal.py`).
- **DevSim**: not yet relevant at this stage.
- **Cannot currently be modeled**: the paper's stated purpose of the
  in-situ N2 anneal ("to reduce oxide fixed charge") is an
  interface-trap/fixed-charge phenomenon; this project has no
  interface-charge model anywhere. `UNSUPPORTED_BY_MODEL`.
- **Evidence**: quoted block above, sentence 1-2.

### Step 2 — Contact lithography + wet etch (open cathode windows)

- **Initial WaferState**: Si + blanket 150 nm SiO2 (from step 1), no
  resist.
- **Why this step's physics DOES depend on step 1's result**: the etch
  removes SiO2 down to whatever is under it at each x. Reading
  `WaferState` here is not optional bookkeeping — the etch model's
  material-selectivity behavior (this project's own `material_rates`)
  only produces the right window depth because it queries what
  material is actually present, which is 150 nm of SiO2 precisely
  because step 1 put it there. Running this step against a bare-Si
  WaferState (skip step 1 entirely) is well-defined and simply etches
  bare Si instead — still not hardcoded to expect oxide, per THE
  INVARIANT.
- **State variables changed**: `Si` exposed within the developed
  window regions (cathode locations); `SiO2` unchanged everywhere
  else, **explicitly including the wafer backside** ("oxide was left
  on the wafer backsides as a diffusion mask" — the paper states this
  is deliberate, not incidental).
- **What becomes input to the next process**:
  `WaferState.exposed_material_at(x)` at every x — this is the exact
  per-x boundary condition the diffusion step (Step 3) needs, and it
  is a real geometric fact read from state, not a coefficient.
- **ViennaPS**: yes — existing litho + selective etch machinery.
- **DevSim**: n/a.
- **Cannot currently be modeled**: nothing new; litho remains
  geometric-only (a known, pre-existing simplification, not introduced
  by this design).
- **Evidence**: quoted block, sentence 3-4.

### Step 3 — POCl3 diffusion (900 C, 5 min)

- **Initial WaferState**: Si exposed at cathode windows; SiO2 (150 nm)
  everywhere else including backside.
- **Why this step's physics DOES depend on steps 1 and 2's result,
  and HOW**: this is the central case this whole design exists to
  express correctly. The dopant source is applied uniformly (a POCl3
  vapor ambient reaches the whole wafer), but where n-type doping
  actually FORMS depends entirely on the current oxide-thickness map:
  wherever `WaferState.thickness_of("SiO2", x)` is 150 nm (unopened,
  or the untouched backside), the real diffusivity of phosphorus in
  SiO2 is low enough that essentially none reaches the Si surface
  within a 5-minute, 900 C budget — the oxide masks by real physics,
  not by a flag saying "masked." Wherever Si is exposed
  (`exposed_material_at(x) == "Si"`, from step 2), the dopant diffuses
  directly into Si with its own, much larger, diffusivity. **This is
  the difference between "diffusion has an interaction coefficient
  with oxidation" (rejected framing) and "diffusion reads the real
  current oxide thickness at each x and computes its own physics from
  it" (this design)** — the SAME diffusion physics call runs at every
  x; only the boundary condition it reads differs, and that boundary
  condition comes from real prior geometry, not from knowing an
  oxidation step ran.
- **State variables changed**: a new n-type `DopantProfile` (species
  phosphorus) forms, confined to the window x-range, with a
  `thermal_budget` reflecting this step's own 900 C x 5 min.
- **What becomes input to the next process**: this profile (and its
  `thermal_budget`) is what a later thermal step (Step 4c) must be
  able to further diffuse; the (unchanged since step 2) oxide
  thickness map is what Step 4a will next modify.
- **ViennaPS**: no — ViennaPS has no diffusion-doping physics at all.
- **DevSim**: partial — DevSim can host any NetDoping expression once
  given a shape; it has no mechanism today to DERIVE that shape from
  real time/temperature/oxide-thickness, which is exactly what §1's
  `AnalyticalDiffusionModel` adds.
- **Cannot currently be modeled** (before this design lands): the
  oxide-thickness-dependent masking decision itself; the diffusivity
  constants for phosphorus in Si and in SiO2 at 900 C are not yet
  sourced (a literature-data task, see §1) — reported `UNKNOWN` until
  filled, never guessed.
- **Evidence**: quoted block, sentence 5.

### Step 4a — Guard-ring plasma etch, p-stop path (thin oxide to 20 nm)

- **Initial WaferState**: Si (n+ doped at windows, from step 3); SiO2
  150 nm elsewhere; new resist patterned for the guard-ring geometry.
- **Why this step's physics depends on the accumulated state, and
  demonstrates a THIRD kind of boundary condition**: the etch is
  time-controlled to leave 20 nm remaining, not to clear the oxide —
  this is neither the "fully open" state Step 2 produced at the
  cathode nor the "untouched 150 nm" state elsewhere; it is a THIRD,
  intermediate `thickness_of("SiO2", x)` value the exact same physics
  machinery must handle without a special case, because it is read as
  a real number, not classified into a binary "masked/unmasked" flag
  anywhere in this design.
- **State variables changed**: `SiO2` thickness at the guard-ring
  annulus becomes 20 nm (a third, distinct value alongside 0 nm at the
  cathode and 150 nm everywhere else).
- **What becomes input to the next process**: this 20 nm value is the
  real boundary condition for Step 4b's implant (through-oxide range
  attenuation) — read the same way Step 3 read the 150/0 nm values.
- **ViennaPS**: yes — a time-controlled (not etch-to-completion) dry
  etch is existing, unmodified capability.
- **DevSim**: n/a.
- **Cannot currently be modeled**: whether 20 nm of remaining oxide
  measurably attenuates the SUBSEQUENT implant's effective dose/range
  — see Step 4b.
- **Evidence**: quoted block, sentence 6-7.

### Step 4b — Boron implant through the thinned oxide (3e13 cm^-2, 20 keV)

- **Initial WaferState**: 20 nm SiO2 at the guard-ring annulus (from
  4a); resist masking everywhere else; existing n+ cathode profile
  present.
- **Why this step's physics depends on 4a's result**: the implant
  passes THROUGH the 20 nm oxide before reaching Si — real ion-range
  physics (dose/energy -> depth/straggle, e.g. LSS/Gaussian-range
  theory) is attenuated by whatever overlying material thickness
  `WaferState` reports at that x. A 0 nm or 150 nm oxide at that same
  (x, dose, energy) would give a different effective profile; this
  step's resolve() call must read the real 20 nm, not assume a fixed
  "through oxide" constant.
- **State variables changed**: a new p-type `DopantProfile` (boron),
  superposed on the existing p-type epi background at the guard-ring
  annulus (the existing `implant_windows` superposition mechanism,
  extended to carry real species identity per §2).
- **What becomes input to the next process**: this profile (with its
  own `thermal_budget` starting fresh) is what Step 4c's anneal must
  re-diffuse.
- **ViennaPS**: no.
- **DevSim**: partial, same as Step 3 — shape-hosting only.
- **Cannot currently be modeled**: dose/energy -> peak
  concentration/depth conversion (real ion-implant range theory is not
  wired anywhere in this project today — every existing implant-style
  doping kind takes peak concentration and position directly from the
  caller); the 20 nm oxide's effect on effective range/straggle.
  `UNKNOWN` pending that data/mechanism, not `UNSUPPORTED_BY_MODEL` —
  it is representable in principle, just not sourced yet.
- **Evidence**: quoted block, sentence 8-9.

### Step 4c — Implant anneal (900 C, 10 min, N2)

- **Initial WaferState**: fresh boron profile (from 4b) coexisting
  with the earlier phosphorus profile (from Step 3, already carrying
  its own `thermal_budget` from that 900 C/5 min exposure).
- **Why this step's physics MUST touch a profile it did not create —
  this is the user's own worked example, realized in the reference
  case**: a real 900 C/10 min anneal further diffuses EVERY dopant
  present, not only the boron this step nominally targets. Per §1's
  V1 mechanism: this step's `D(P, Si, 900C) * 600s` contribution is
  added to the EXISTING phosphorus profile's `thermal_budget`
  (re-widening the cathode junction slightly, a real and expected
  effect), in the same call that computes the new boron profile's own
  diffusion under the identical thermal conditions.
- **What becomes input to the next process**: both re-diffused
  profiles, feeding the eventual electrical characterization.
- **ViennaPS**: no. **DevSim**: shape-hosting only, same as above.
- **Cannot currently be modeled**: nothing beyond what §1 already
  scopes (diffusivity citations pending) — this step is fully within
  the V1 mechanism's intended scope, unlike oxidation's thermal
  contribution (explicitly out of V1 scope, §1).
- **Evidence**: quoted block, sentence 10.

### Steps 4d/4e — Non-isolated (REG-GR) / isolated (ISO-GR) branches

- **Why these demonstrate order/choice independence directly**: REG-GR
  fully removes the oxide at the annulus (a DIFFERENT etch duration
  choice than 4a's partial etch — same category, different parameter,
  genuinely different resulting `WaferState`, with no implant
  following). ISO-GR does nothing further (the annulus stays at
  whatever thickness the prior state already had). Neither branch is
  a special case in the resolver — both are the SAME etch/no-op
  physics, evaluated against different starting states / different
  user-chosen parameters, exactly the principle this design commits
  to.
- **Evidence**: quoted block, sentence 11.

### Step 5 — Contact-window HF dip (1%, clear residual oxide)

- **Why this step matters causally**: guarantees Si is genuinely
  exposed (not merely "nominally opened three steps ago, possibly with
  some regrowth") immediately before metallization — the following
  step's Axis-2 contact determination (§3) depends on the CURRENT
  state at deposition time, and this step is what makes "current" here
  actually mean bare Si.
- **ViennaPS**: yes — representable as a very short, highly
  SiO2-selective wet etch with existing machinery.
- **Evidence**: quoted block, sentence 12.

### Step 6 — Front metal deposition (Al, 750 nm, e-beam, blanket)

- **Initial WaferState**: Si exposed at cathode + HF-cleared windows;
  SiO2 elsewhere at whichever thickness the guard-ring branch (4a/4d/4e)
  left it — 0 nm (REG-GR), 20 nm (p-stop, if the anneal didn't further
  consume it), or 150 nm (ISO-GR).
- **Why this step's physics depends on ALL prior steps at once**: this
  is a blanket deposition — geometrically the SAME everywhere — but
  its ELECTRICAL consequence (§3, Axis 2) differs by x purely because
  of the accumulated oxide-thickness map beneath it, which is the
  combined result of Steps 1, 2, and whichever guard-ring branch ran.
  No single prior step determines the outcome; the CURRENT state does.
- **State variables changed**: `Al` present everywhere on the front
  (not yet patterned).
- **What becomes input to the next process**: the real, current
  Al-to-(Si or SiO2) adjacency map — which Step 7's patterning must
  preserve or remove per-region, and which ultimately determines Axis
  2 for each final metal pad.
- **ViennaPS**: yes for geometry — with the caveat already on record
  in CLAUDE.md that ViennaPS 4.6.2's `Material` enum has no `Al` entry
  for this project; a real run substitutes a different metal tag for
  geometry purposes.
- **DevSim / Axis 3**: `UNSUPPORTED_BY_MODEL` for any Al-specific
  electrical claim (work function, barrier height), regardless of
  which tag stands in for the geometry.
- **Evidence**: quoted block, sentence 13.

### Step 7 — Front metal patterning (litho + hot H3PO4 wet etch)

- **Why this step's causal role is easy to get wrong**: it is tempting
  to say "patterning determines the contacts." It does not, alone —
  Axis 2 (§3) is only knowable from the COMBINATION of step 6's
  Al/Si-vs-Al/SiO2 footprint and step 7's final pattern. A pad that
  survives patterning but sits entirely over 150 nm SiO2 (never
  touched exposed Si at any point) is real Al geometry with NO
  electrical contact — Axis 1 true, Axis 2 false. This is the
  concrete case the design's Axis-2 mechanism (current-geometry-based,
  not history-based) must get right.
- **ViennaPS**: yes — existing selective wet-etch/litho machinery.
- **Evidence**: quoted block, sentence 14.

### Step 8 — Backside HF + back metal (Al, 500 nm, e-beam)

- Same causal shape as steps 5-6 applied to the wafer back, closing
  the substrate Ohmic contact. No new mechanism.
- **Evidence**: quoted block, sentence 15.

### Step 9 — Contact sintering anneal (H2, 400 C, 10 min)

- **Why this step matters and why it is honestly out of reach**: this
  is the step that, in reality, converts a merely-touching Al/Si
  geometric interface into a genuinely low-resistance ohmic contact
  via real metallurgical intermixing at the interface. Axis 2 (§3)
  already reports "contact candidate exists" before this step runs;
  this step is what would, in a real device, change Axis 3 from
  "geometrically touching, electrically unquantified" to "known-good
  ohmic, known resistance" — and this project has no alloying/contact-
  resistance model anywhere to represent that change. `UNSUPPORTED_BY_MODEL`,
  explicitly, rather than silently treating Axis 2 = Axis 3.
- **Evidence**: quoted block, sentence 16.

### An effect this design deliberately excludes from scope

The same paper's Schottky-fabrication appendix (a separate device on
the same wafer set) states: "the second process of photoresist
deposition took place not immediately after the step of RIE oxide
etching, with the wafers left exposed in free air inside the clean
room, it is expected that a thin layer of native oxide grew over the
top surface of the wafers" — i.e., real physical state changed from
mere elapsed TIME in air, with no process step selected by the
operator at all. This is a genuine instance of "current state, not
process history, determines subsequent physics" taken to its extreme,
but it falls entirely outside this project's scope (which only models
explicit, user-run process steps) and is recorded here as an
acknowledged, intentionally excluded case — not a gap this design's
mechanism needs to close.

---

## §7 Order-independence tests

Extends the base design's T1-T5 (unchanged, still apply as-is). One
new category:

### T6 — order sensitivity where physically real

Distinct from T2 (same state reached by different routes -> same
result — a test that TWO paths CONVERGE). T6 asserts the opposite
where physically warranted: running the SAME set of process choices in
a DIFFERENT order produces a DIFFERENT, correctly-computed
`WaferState`, specifically for the Axis-2 metal-contact case:

```
metal deposited BEFORE the underlying oxide window is opened
  -> Axis 2 must report NO contact at that location, ever again,
     unless a LATER step re-exposes that specific interface
metal deposited AFTER the window is opened
  -> Axis 2 must report a contact candidate
```

Both orders are real, user-choosable sequences; neither is treated as
"the normal one." The test file must state this explicitly, mirroring
the base design's T4 permutation-sweep disclaimer ("no permutation is
a normal order").

---

## §8 Migration, relative to the base design's staging table

| Stage | Content | Verified by |
|---|---|---|
| Base 0-2 | (already covered by the base design; unaffected) | base design's own harness |
| **This design, stage A** | `DopantProfile`/species/polarity plumbing in `WaferState` (§2); device-layer NetDoping conversion moved to read from it, producing IDENTICAL results to today for every existing doping kind (compat mode — no existing test's numbers change) | full regression, byte-identical NetDoping for unchanged kinds |
| **This design, stage B** | `DiffusionModel` protocol + `AnalyticalDiffusionModel`, wired as a new `thermal_diffusion` doping kind; diffusivity table ships EMPTY (reports UNKNOWN) | T5-style UNKNOWN-propagation test; no change to any existing doping kind |
| **This design, stage C** | Metal-contact Axis 1/2/3 tagging in `mesh_import.py`, generalized interface detection | T6; existing `Si_SiO2_interface` behavior unchanged (regression) |
| **This design, stage D** | Literature diffusivity data for P and B in Si (and in SiO2, for masking) — separate data-entry task, no code change, per the base design's own philosophy | re-measurement against the reference case's qualitative claims (confined n+ region, masked backside) |
| **Deferred, explicitly out of this design's scope** | cumulative thermal budget from oxidation; PDE-level diffusion; Schottky/ohmic distinction; contact resistance/alloying; interface fixed-charge/trap density; ion-implant dose/energy->profile physics | recorded as `UNSUPPORTED_BY_MODEL`/`UNKNOWN` per §5's table, revisited only as a future, separately-scoped design |

Each stage is independently regression-checkable before the next
begins, per CLAUDE.md's Development Rules ("work slowly and one
subsystem at a time").

## Next steps

1. User review of this document.
2. `superpowers:writing-plans` for stage A (the smallest, purely
   plumbing stage — no physics result changes for any existing test).
   Stages B-D each get their own plan once the prior stage is verified
   in production, per the base design's own migration philosophy.
