# Dopant State Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two parallel, disconnected doping-state representations (`WaferState.dopant_profiles`, never populated in production, and `ProcessResult.doping`, which the GUI actually threads) with one canonical, model-agnostic, geometry-gated state, wired through every process category and into a real per-node DevSim conversion.

**Architecture:** `DopantProfile` becomes model-agnostic (`model` + opaque `model_params`, no Gaussian-specific top-level fields). `WaferState.dopant_profiles` becomes the single accumulating state, threaded through every process step via a shared helper. `apply_thermal_anneal()` becomes a per-model dispatch function. `doping_mapping.py`'s symbolic-equation kind-dispatch is replaced by real per-node Python evaluation written via `devsim.set_node_values()`.

**Tech Stack:** Python, real ViennaPS 4.6.2, real DevSim, existing project SDD/regression infrastructure — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-dopant-state-unification-design.md` (also read `2026-09-01-state-dependent-process-physics-design.md` §1 for the unchanged `DiffusionModel` seam this plan's model-dispatch mechanism must stay compatible with).

## Global Constraints

- **2D only. Physical correctness over feature count.** (CLAUDE.md)
- **Core Physics Requirement** (CLAUDE.md): no task is complete on data structures alone, mock values, arbitrary constants/colors, GUI graphics disconnected from real computation, or "architecture that could support X later." Every physics-bearing task must trace literature/equation → real calculation → `WaferState` change → next step → DevSim → GUI.
- **THE INVARIANT** (CLAUDE.md): process order is never hardcoded or enforced. No task may special-case a process sequence.
- Never write "architecture wired successfully" as an acceptance criterion by itself — every task's acceptance criteria must show real input → real physics calculation → real `WaferState` → real DevSim node value (where applicable) → real GUI display (where applicable).
- Spec §2: `DopantProfile.concentration_at` is a runtime interface only; `model`/`model_params`/`thermal_history`/`source` are the persistent canonical facts.
- Spec §3: geometry-gated evaluation is a **three-way** test (apply / geometry-gated zero / `UNSUPPORTED_BY_MODEL`) — never a two-way `material != host_material → 0`.
- Spec §6: a partial sum (some profiles computable, others `UNSUPPORTED_BY_MODEL`) must never be presented as a complete `net_doping` without `physics_status` disclosing the gap.
- Spec §8: no new GUI parameter (e.g. implant energy) until a real consuming model reads it and is confirmed to change the computed result.
- Spec §9: `ProcessResult.doping` is reduced to "this step's raw declared input only" — `WaferState.dopant_profiles` is the one canonical, cross-step state.
- Preserve existing regression tests where the underlying behavior is unchanged; where this plan's own spec requires behavior to change (e.g. `DopingRegion.gaussian_terms` removal), update the tests that exercised the OLD behavior explicitly, in the same task, and say so in the commit message — never leave a stale test silently describing removed behavior.

---

### Task 1: `DopantProfile` schema migration — model-agnostic representation

**Files:**
- Modify: `tcad/physics/dopant_profile.py` (the `DopantProfile` dataclass and all four `_*_profiles()` helpers)
- Modify: `tcad/physics/diffusion_model.py` (`anneal_profile()` — reads the OLD top-level fields directly; breaks the moment this task's schema change lands, so it is fixed in THIS task, not left dangling for Task 3)
- Modify: `tests/unit/test_dopant_profile_mock.py` (fields renamed/removed)
- Modify: `tests/unit/test_anneal_profile_mock.py` (reads old top-level fields — update to `model_params`)
- Modify: `tests/integration/test_dopant_profile_matches_devsim_real.py` (reads old top-level Gaussian fields directly — must read `model_params` instead)

**Interfaces:**
- Produces: `ThermalEvent(temperature_c: float, time_s: float)`, `DopantProfile(species, polarity, concentration_at, host_material: str, model: str, model_params: Dict[str, Any], thermal_history: Tuple[ThermalEvent, ...] = (), source: Optional[Source] = None)`. `dopant_profiles_from_doping_profile(doping: DopingProfile) -> Tuple[DopantProfile, ...]` — same public signature, new return shape.
- Consumes: existing `tcad.mesh.interface.DopingProfile`/`DopingRegion` (unchanged in this task — Task 4 changes `DopingRegion` itself).

- [ ] **Step 1: Write the failing test for the new schema**

```python
# tests/unit/test_dopant_profile_mock.py -- add
def test_dopant_profile_has_no_gaussian_specific_top_level_fields():
    import dataclasses
    from tcad.physics.dopant_profile import DopantProfile
    field_names = {f.name for f in dataclasses.fields(DopantProfile)}
    assert "peak_conc_cm3" not in field_names
    assert "peak_position_um" not in field_names
    assert "straggle_um" not in field_names
    assert "thermal_budget" not in field_names
    assert field_names == {
        "species", "polarity", "concentration_at", "host_material",
        "model", "model_params", "thermal_history", "source",
    }
    print(f"DopantProfile fields (model-agnostic): {sorted(field_names)}")

def test_gaussian_implant_profile_carries_model_tag_and_params():
    from tcad.mesh.interface import DopingProfile, DopingRegion
    from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile

    region = DopingRegion(
        region="Si", junction_axis="x", peak_position_um=1.0,
        straggle_um=0.2, peak_conc_cm3=1e18,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[region])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.model == "gaussian_v1"
    assert p.host_material == "Si"
    assert p.model_params["peak_conc_cm3"] == 1e18
    assert p.model_params["peak_position_um"] == 1.0
    assert p.model_params["straggle_um"] == 0.2
    assert p.thermal_history == ()
    print(f"model={p.model!r}, model_params={p.model_params}, "
          f"concentration_at(1.0, 0.0)={p.concentration_at(1.0, 0.0):.3e}")
    assert abs(p.concentration_at(1.0, 0.0) - 1e18) < 1.0
```

```python
# tests/unit/test_anneal_profile_mock.py -- add
def test_anneal_profile_reads_model_params_and_uses_real_host_material():
    """Real bug this task's schema change surfaces and fixes: the OLD
    anneal_profile() hardcoded "Si" as the D(T) host material instead
    of reading the profile's own host_material -- harmless while every
    profile WAS Si, but wrong the moment host_material is a real,
    meaningful field (this task adds it). A SiGe-tagged profile must
    get SiGe's own D(T), not silently reuse Si's."""
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.diffusion_model import anneal_profile

    profile = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    widened = anneal_profile(profile, 900.0, 600.0)
    print(f"straggle {profile.model_params['straggle_um']:.4f} -> "
          f"{widened.model_params['straggle_um']:.4f} um (host_material=Si)")
    assert widened.model_params["straggle_um"] > profile.model_params["straggle_um"]

    unknown_host = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="SiGe",  # no B-in-SiGe citation exists in this project
        model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    unchanged = anneal_profile(unknown_host, 900.0, 600.0)
    print(f"host_material=SiGe (no citation): straggle unchanged = "
          f"{unchanged.model_params['straggle_um'] == unknown_host.model_params['straggle_um']}")
    assert unchanged.model_params["straggle_um"] == unknown_host.model_params["straggle_um"], (
        "must NOT silently reuse Si's D(T) for a different host_material -- UNKNOWN, not guessed"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py`
Expected: FAIL — `DopantProfile` still has `peak_conc_cm3` etc. as top-level fields, no `host_material`/`model`/`model_params`.

- [ ] **Step 3: Redefine `DopantProfile` and update the four `_*_profiles()` helpers**

```python
# tcad/physics/dopant_profile.py

@dataclass(frozen=True)
class ThermalEvent:
    """One real thermal exposure a profile has lived through -- the RAW
    fact. thermal_budget (a derived Sigma D(T)t scalar) is computed FROM
    this by whichever model needs it (today: gaussian_v1's own D(T)
    lookup) -- never stored directly (spec 2026-09-03 Sec2)."""
    temperature_c: float
    time_s: float


@dataclass(frozen=True)
class DopantProfile:
    """Model-agnostic. See spec 2026-09-03 Sec2 for the full contract:
    concentration_at is a RUNTIME evaluation interface only -- the
    persistent canonical facts are species/polarity/host_material/model/
    model_params/thermal_history/source, and any model_params shape must
    be sufficient to rebuild an equivalent concentration_at closure
    later. model_params is opaque to everyone except the model tagged
    by `model` -- no other code (doping_mapping.py, the GUI, another
    model's own handler) may read its keys directly."""
    species: Optional[str]
    polarity: str
    concentration_at: Callable[[float, float], float]
    host_material: str
    model: str
    model_params: Dict[str, Any] = field(default_factory=dict)
    thermal_history: Tuple[ThermalEvent, ...] = ()
    source: Optional[Source] = None
```

Update every helper to emit this shape. `_gaussian_implant_profiles()` (the one with real shape parameters) is the reference case:

```python
def _gaussian_implant_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.junction_axis not in (None, "x"):
        raise NotImplementedError(
            f"dopant_profiles_from_doping_profile evaluates along x only; "
            f"got junction_axis={region.junction_axis!r}"
        )
    peak, position, straggle = (
        region.peak_conc_cm3, region.peak_position_um, region.straggle_um,
    )
    if peak is None:
        return []
    polarity = "donor" if peak >= 0 else "acceptor"
    magnitude = abs(peak)
    params = {
        "peak_conc_cm3": magnitude,
        "peak_position_um": position,
        "straggle_um": straggle,
    }
    return [DopantProfile(
        species=region.donor_species if polarity == "donor" else region.acceptor_species,
        polarity=polarity,
        concentration_at=lambda x, d, m=magnitude, p=position, s=straggle: (
            m * _gaussian_shape(x, p, s)
        ),
        host_material=region.region,
        model="gaussian_v1",
        model_params=params,
    )]
```

(`_uniform_profiles`, `_step_junction_profiles`, `_implant_windows_profiles` follow the same pattern: `host_material=region.region`, `model="uniform_v1"`/`"step_junction_v1"`/`"implant_windows_v1"` respectively, `model_params` holding whatever raw numbers each kind needs for potential future re-processing — e.g. `{"net_doping_cm3": ...}` for uniform. None of these three get an anneal handler registered in Task 3 — they never had real anneal physics before this plan either, so `UNSUPPORTED_BY_MODEL` under anneal is the honest, unchanged behavior.)

**`anneal_profile()` (`tcad/physics/diffusion_model.py`) must be fixed in THIS task**, not deferred — it reads `profile.peak_conc_cm3`/`.peak_position_um`/`.straggle_um`/`.thermal_budget` directly today, all of which this task's schema change removes; leaving it unfixed breaks it immediately, before Task 3 ever runs. Read the function's real current body before editing (reproduced here so the diff is unambiguous):

```python
# tcad/physics/diffusion_model.py -- anneal_profile() REWRITTEN
def anneal_profile(
    profile: DopantProfile, temperature_c: float, time_s: float,
) -> DopantProfile:
    """Real, dose-conserving Gaussian broadening under one isothermal
    anneal step (unchanged formula from Stage B). Reads/writes
    model_params now instead of top-level fields; does NOT touch
    thermal_history -- appending this step's ThermalEvent is
    apply_thermal_anneal()'s own job (Task 3), done identically for
    EVERY profile regardless of whether a handler exists, so it must
    not also happen here (that would double-append the same event).
    """
    straggle_um = profile.model_params.get("straggle_um")
    if straggle_um is None or profile.species is None:
        return profile

    # Real bug fixed here, enabled by this task's own schema change:
    # the OLD version hardcoded "Si" instead of reading the profile's
    # own host_material -- harmless while every profile WAS Si, wrong
    # the instant host_material is a real, meaningful field.
    contribution = thermal_budget_contribution(
        profile.species, profile.host_material, temperature_c, time_s,
    )
    if contribution.value is None:
        return profile

    dt_um2 = contribution.value * 1e8  # cm^2 -> um^2 (1 cm = 1e4 um)
    new_straggle = math.sqrt(straggle_um ** 2 + 2.0 * dt_um2)
    peak_conc_cm3 = profile.model_params["peak_conc_cm3"]
    new_peak = peak_conc_cm3 * (straggle_um / new_straggle)
    position = profile.model_params["peak_position_um"]

    def new_shape(x_um: float, depth_um: float,
                  peak=new_peak, pos=position, straggle=new_straggle) -> float:
        return peak * math.exp(-((x_um - pos) ** 2) / (2.0 * straggle ** 2))

    new_params = dict(profile.model_params)
    new_params["peak_conc_cm3"] = new_peak
    new_params["straggle_um"] = new_straggle

    from dataclasses import replace
    return replace(
        profile, concentration_at=new_shape, model_params=new_params,
        # The citation that just produced new_straggle/new_peak, not
        # profile.source (unchanged from Stage B final-review Minor #4).
        source=contribution.source,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py tests/unit/test_anneal_profile_mock.py`
Expected: PASS — including the real host_material D(T) fix confirmed by the new test above. Also update `tests/integration/test_dopant_profile_matches_devsim_real.py`'s direct field reads (`profile.peak_conc_cm3` → `profile.model_params["peak_conc_cm3"]`) and re-run it for real:

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_dopant_profile_matches_devsim_real.py`
Expected: PASS, same real DevSim cross-check numbers as before (this task changes representation, not the computed values).

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/dopant_profile.py tcad/physics/diffusion_model.py tests/unit/test_dopant_profile_mock.py tests/unit/test_anneal_profile_mock.py tests/integration/test_dopant_profile_matches_devsim_real.py
git commit -m "refactor: DopantProfile becomes model-agnostic (host_material/model/model_params/thermal_history), fix anneal_profile's hardcoded Si host_material"
```

---

### Task 2: `WaferState` geometry-gated evaluation + partial-aggregate query result

**Files:**
- Modify: `tcad/physics/wafer_state.py`
- Test: `tests/unit/test_wafer_state_doping_mock.py`

**Interfaces:**
- Consumes: `DopantProfile` (Task 1).
- Produces: `DopingQueryResult(donor_concentration: float, acceptor_concentration: float, net_doping: float, physics_status: Optional[dict])`. **`WaferState.net_doping_at(x_um, depth_um) -> DopingQueryResult` is the ONLY public doping query method.** `donor_concentration_at`/`acceptor_concentration_at` are REMOVED (not kept as float-returning wrappers): today's code had two methods whose NAMES promise a scalar concentration but whose real job is a full three-way evaluation — keeping them alongside `net_doping_at` either duplicates the whole computation twice per query or forces them to secretly return the same compound result their name doesn't describe. Grep confirms zero real production callers of either today (per gap analysis) — nothing is served by keeping them. A caller wanting just the donor or acceptor number reads `.donor_concentration`/`.acceptor_concentration` off the ONE `DopingQueryResult` `net_doping_at` already returns. `WaferState.query(domain, dopant_profiles=(), last_step_category: Optional[str] = None)` (new keyword-only parameter, unchanged from the original draft).
- The category → transition-kind table (Task's own concrete decision on the spec's left-open mechanism): `MATERIAL_CHANGE_KIND_BY_CATEGORY: Dict[str, str] = {"etching": "removal", "oxidation": "conversion"}` — a step whose category has no entry (e.g. `"deposition"`, `"doping"`, or anything not yet in the table) defaults to `UNSUPPORTED_BY_MODEL`, NOT to a silent zero — see Step 3's `_polarity_sum` for why this default direction matters (CLAUDE.md's own "never silently decide" discipline).

**Scope note, read before writing tests:** this task's tests are MECHANISM/logic tests only — they construct synthetic `WaferState`/`DopantProfile` fixtures by hand (including one using a `host_material` this project has no such material at all, purely to exercise the "host_material never matches" branch in isolation) to prove the THREE-WAY DISPATCH LOGIC itself is correct. **None of these tests claim to validate real oxidation Si→SiO2 conversion physics** — that real, physical claim is Task 7's job, with real ViennaPS. Do not blur this: a mock test proving the branch-selection code is correct is not "physical validation" of anything, and must never be described as such in a report or commit message.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_wafer_state_doping_mock.py -- add
# NOTE: every fixture below is SYNTHETIC (hand-built WaferState/DopantProfile
# objects), testing the dispatch LOGIC in isolation. It proves the branch
# selection is correct; it does not and cannot validate that real oxidation
# genuinely converts Si to SiO2 in a physically correct way -- that is Task 7's
# job, with real ViennaPS execution.

def test_geometry_gated_zero_for_removal_category():
    """A profile whose host_material is genuinely gone after an
    ETCHING step (removal) reads DopingQueryResult.net_doping == 0
    with NO physics_status gap -- this is a real, physically
    meaningful zero (spec Sec3 case 2 / Sec6 state A)."""
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.wafer_state import WaferState, LayerInfo, _Cell

    profile = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1", model_params={},
    )
    # No Si cell at all at this x -- simulates etch having removed it.
    state = WaferState(
        materials=("SiO2",), stack=(LayerInfo("SiO2", 0),),
        grid_delta_um=0.1, _cells=(_Cell(0.0, 1.0, 0.5, "SiO2"),),
        _thin_x=(), dopant_profiles=(profile,),
        last_step_category="etching",
    )
    result = state.net_doping_at(0.5, 0.0)
    print(f"[removal] net_doping={result.net_doping}, physics_status={result.physics_status}")
    assert result.net_doping == 0.0
    assert result.physics_status is None

def test_unsupported_by_model_for_conversion_category_never_zero():
    """The SAME missing-material situation, but the responsible
    category is OXIDATION (conversion) -- must report
    UNSUPPORTED_BY_MODEL, never a bare 0 (spec Sec3 case 3 / Sec6
    state C)."""
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.wafer_state import WaferState, LayerInfo, _Cell

    profile = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1", model_params={},
    )
    state = WaferState(
        materials=("SiO2",), stack=(LayerInfo("SiO2", 0),),
        grid_delta_um=0.1, _cells=(_Cell(0.0, 1.0, 0.5, "SiO2"),),
        _thin_x=(), dopant_profiles=(profile,),
        last_step_category="oxidation",
    )
    result = state.net_doping_at(0.5, 0.0)
    print(f"[conversion] donor_concentration={result.donor_concentration}, "
          f"physics_status={result.physics_status}")
    assert result.donor_concentration == 0.0   # the numeric FIELD is 0 (nothing computable)
    assert result.physics_status is not None
    assert result.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    entry = result.physics_status["entries"][0]
    assert entry["material"] == "P"
    assert "conversion" in entry["note"]

def test_partial_aggregate_never_hides_the_gap():
    """One profile computable, one UNSUPPORTED -- net_doping is the
    real partial sum, but physics_status MUST disclose the gap
    (spec Sec6 partial-unsupported aggregate contract)."""
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.wafer_state import WaferState, LayerInfo, _Cell

    computable = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 3e18,
        host_material="Si", model="gaussian_v1", model_params={},
    )
    unsupported = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="SiGe",  # a material this WaferState doesn't have at all
        model="gaussian_v1", model_params={},
    )
    state = WaferState(
        materials=("Si",), stack=(LayerInfo("Si", 0),),
        grid_delta_um=0.1, _cells=(_Cell(0.0, 1.0, 0.5, "Si"),),
        _thin_x=(), dopant_profiles=(computable, unsupported),
        last_step_category="oxidation",
    )
    result = state.net_doping_at(0.5, 0.0)
    print(f"donor={result.donor_concentration}, acceptor={result.acceptor_concentration}, "
          f"net={result.net_doping}, physics_status={result.physics_status}")
    assert result.donor_concentration == 3e18
    assert result.acceptor_concentration == 0.0   # unsupported contribution NOT silently substituted as 0-and-safe
    assert result.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert any(e["material"] == "B" for e in result.physics_status["entries"])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_wafer_state_doping_mock.py`
Expected: FAIL — `net_doping_at` returns a bare float today, `WaferState` has no `last_step_category` field.

- [ ] **Step 3: Implement**

```python
# tcad/physics/wafer_state.py

MATERIAL_CHANGE_KIND_BY_CATEGORY: Dict[str, str] = {
    "etching": "removal",
    "oxidation": "conversion",
}


@dataclass(frozen=True)
class DopingQueryResult:
    donor_concentration: float
    acceptor_concentration: float
    net_doping: float
    physics_status: Optional[dict]


# WaferState dataclass gains:
    last_step_category: Optional[str] = None

# WaferState.query() signature gains:
    @staticmethod
    def query(domain: Any, dopant_profiles: Tuple[DopantProfile, ...] = (),
               last_step_category: Optional[str] = None) -> "WaferState":
        ...  # unchanged body, just also sets last_step_category=last_step_category
             # on the returned WaferState

    def _polarity_sum(self, x_um: float, depth_um: float, polarity: str) -> Tuple[float, List[dict]]:
        total = 0.0
        entries: List[dict] = []
        change_kind = MATERIAL_CHANGE_KIND_BY_CATEGORY.get(self.last_step_category or "")
        for p in self.dopant_profiles:
            if p.polarity != polarity:
                continue
            if self.exposed_material_at(x_um) == p.host_material:
                total += p.concentration_at(x_um, depth_um)
                continue
            # host_material absent here -- three-way test, spec Sec3.
            if change_kind == "removal":
                # A real, physically meaningful geometry-gated zero
                # (spec Sec6 state A) -- ONLY for a category explicitly
                # known to only ever take material away.
                continue
            # Default is UNSUPPORTED_BY_MODEL, not zero -- covers both
            # "conversion" (oxidation) AND any category with no table
            # entry at all. Never silently assume an unclassified
            # category means removal; that would be exactly the kind
            # of undisclosed guess CLAUDE.md's Core Physics Requirement
            # forbids. A future category genuinely needing "removal"
            # semantics gets added to MATERIAL_CHANGE_KIND_BY_CATEGORY
            # explicitly, not by falling through a default.
            entries.append({
                "parameter": "dopant_fate_at_material_change",
                "material": p.species, "resolution": "UNSUPPORTED_BY_MODEL",
                "provenance": "DERIVED",
                "note": f"{p.host_material} no longer exposed at this point "
                        f"(category={self.last_step_category!r}) and no dopant "
                        f"segregation/fate model is registered -- contribution "
                        f"excluded, NOT zero",
            })
        return total, entries

    def net_doping_at(self, x_um: float, depth_um: float = 0.0) -> DopingQueryResult:
        """The ONE public doping query. Read .donor_concentration /
        .acceptor_concentration / .net_doping / .physics_status off the
        result -- there is no separate donor-only or acceptor-only
        method (removed: their names promised a scalar float, but the
        real computation and the UNSUPPORTED_BY_MODEL disclosure
        requirement (spec Sec6) apply identically to every one of
        those values, so splitting them apart either duplicates the
        work or hides the same status three different callers would
        otherwise have to remember to check separately)."""
        donor, donor_gaps = self._polarity_sum(x_um, depth_um, "donor")
        acceptor, acceptor_gaps = self._polarity_sum(x_um, depth_um, "acceptor")
        entries = donor_gaps + acceptor_gaps
        physics_status = None
        if entries:
            physics_status = {"resolution": "UNSUPPORTED_BY_MODEL", "entries": entries, "notes": []}
        return DopingQueryResult(
            donor_concentration=donor, acceptor_concentration=acceptor,
            net_doping=donor - acceptor, physics_status=physics_status,
        )
```

(Removing `donor_concentration_at`/`acceptor_concentration_at` entirely, rather than keeping them as thin wrappers, is a deliberate, disclosed API break; grep confirms zero production callers of either today, so no other file needs updating in this task. Task 5 is the one that adds the first real production callers, against the single `net_doping_at` method.)

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_wafer_state_doping_mock.py`
Expected: PASS, with the three real printed cases above showing the actual 3-way distinction.

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/wafer_state.py tests/unit/test_wafer_state_doping_mock.py
git commit -m "feat: WaferState doping queries become a real 3-way test (apply/removal-zero/UNSUPPORTED_BY_MODEL)"
```

---

### Task 3: Model-dispatch registry + `apply_thermal_anneal()` as dispatch (not a single formula)

**Files:**
- Create: `tcad/physics/dopant_models.py`
- Modify: `tcad/physics/doping.py` (`apply_thermal_anneal()`)
- Test: `tests/unit/test_dopant_models_mock.py` (new), `tests/unit/test_thermal_anneal_mock.py` (updated for new signature)

**Interfaces:**
- Consumes: `DopantProfile` (Task 1), `anneal_profile()`/`thermal_budget_contribution()` (existing, `tcad/physics/diffusion_model.py`, UNCHANGED).
- Produces: `ANNEAL_HANDLERS: Dict[str, Callable[[DopantProfile, float, float], DopantProfile]]`, `register_anneal_handler(model_tag: str, handler)`. `apply_thermal_anneal(profiles: Tuple[DopantProfile, ...], temperature_c: float, time_s: float) -> Tuple[Tuple[DopantProfile, ...], Optional[dict]]` (returns updated profiles + physics_status; **signature changes from `(result: ProcessResult, ...) -> ProcessResult`** — this task operates on the profile tuple directly, since profiles now live on `WaferState`, not `ProcessResult.doping`, per spec §9; Task 5 wires this into the real per-step pipeline).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dopant_models_mock.py -- new file
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

def test_gaussian_v1_is_the_only_registered_handler():
    from tcad.physics.dopant_models import ANNEAL_HANDLERS
    print(f"registered anneal handlers: {sorted(ANNEAL_HANDLERS)}")
    assert set(ANNEAL_HANDLERS) == {"gaussian_v1"}

def test_dispatch_widens_gaussian_and_flags_unregistered_model():
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.doping import apply_thermal_anneal

    gaussian = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    no_model = DopantProfile(
        species="As", polarity="donor",
        concentration_at=lambda x, d: 5e17,
        host_material="Si", model="uniform_v1", model_params={"net_doping_cm3": 5e17},
    )
    updated, physics_status = apply_thermal_anneal((gaussian, no_model), 900.0, 600.0)

    g2 = next(p for p in updated if p.species == "B")
    u2 = next(p for p in updated if p.species == "As")
    print(f"B (gaussian_v1) straggle {gaussian.model_params['straggle_um']:.4f} -> "
          f"{g2.model_params['straggle_um']:.4f} um")
    print(f"As (uniform_v1) model_params unchanged: {u2.model_params == no_model.model_params}")
    print(f"physics_status: {physics_status}")

    assert g2.model_params["straggle_um"] > gaussian.model_params["straggle_um"], (
        "gaussian_v1 profile must actually widen"
    )
    assert len(g2.thermal_history) == 1 and g2.thermal_history[0].temperature_c == 900.0
    assert u2.model_params == no_model.model_params, "unregistered model must NOT be modified"
    assert len(u2.thermal_history) == 1, "raw thermal fact recorded even with no handler"
    assert physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert any(e["material"] == "As" for e in physics_status["entries"])
    assert not any(e["material"] == "B" for e in physics_status["entries"])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_dopant_models_mock.py`
Expected: FAIL — `tcad.physics.dopant_models` does not exist yet.

- [ ] **Step 3: Implement**

```python
# tcad/physics/dopant_models.py -- new file
"""Per-model anneal/redistribution dispatch registry (spec 2026-09-03
Sec7). Registration mechanism is a plain dict, decided at implementation
time -- the spec left the exact mechanism open, matching how the base
design (2026-08-25) also left DiffusionModel's own registration shape
undecided until implementation."""
from typing import Callable, Dict

from tcad.physics.diffusion_model import anneal_profile
from tcad.physics.dopant_profile import DopantProfile

ANNEAL_HANDLERS: Dict[str, Callable[[DopantProfile, float, float], DopantProfile]] = {}


def register_anneal_handler(model_tag: str, handler) -> None:
    ANNEAL_HANDLERS[model_tag] = handler


# anneal_profile() (Task 1 already migrated it to read model_params and
# use profile.host_material) is registered DIRECTLY -- no adapter
# needed. It must NOT append its own ThermalEvent (see its docstring,
# Task 1): apply_thermal_anneal() below does that once, uniformly, for
# every profile regardless of whether a handler exists, so a handler
# double-appending it would corrupt thermal_history.
register_anneal_handler("gaussian_v1", anneal_profile)
```

```python
# tcad/physics/doping.py -- apply_thermal_anneal REWRITTEN as dispatch
def apply_thermal_anneal(
    profiles: Tuple[DopantProfile, ...], temperature_c: float, time_s: float,
) -> Tuple[Tuple[DopantProfile, ...], Optional[dict]]:
    from tcad.physics.dopant_models import ANNEAL_HANDLERS
    from tcad.physics.dopant_profile import ThermalEvent

    updated = []
    entries = []
    for profile in profiles:
        with_event = replace(
            profile, thermal_history=profile.thermal_history + (
                ThermalEvent(temperature_c=temperature_c, time_s=time_s),
            ),
        )
        handler = ANNEAL_HANDLERS.get(profile.model)
        if handler is None:
            entries.append({
                "parameter": "anneal_redistribution", "material": profile.species,
                "resolution": "UNSUPPORTED_BY_MODEL", "provenance": "DERIVED",
                "note": f"no anneal/redistribution handler registered for model={profile.model!r}",
            })
            updated.append(with_event)
            continue
        updated.append(handler(with_event, temperature_c, time_s))
    physics_status = (
        {"resolution": "UNSUPPORTED_BY_MODEL", "entries": entries, "notes": []}
        if entries else None
    )
    return tuple(updated), physics_status
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_dopant_models_mock.py tests/unit/test_thermal_anneal_mock.py`
Expected: PASS. Also re-run the real acceptance test to confirm the Gaussian numbers are unchanged after moving to `model_params`:

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_thermal_anneal_acceptance_real.py`
Expected: PASS, same real straggle/peak numbers Stage B already established (this task changes plumbing, not the formula).

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/dopant_models.py tcad/physics/doping.py tests/unit/test_dopant_models_mock.py tests/unit/test_thermal_anneal_mock.py
git commit -m "refactor: apply_thermal_anneal becomes per-model dispatch, gaussian_v1 registered as the only handler"
```

---

### Task 4: Remove `DopingRegion.gaussian_terms` / `existing=` accumulation (single source of accumulation moves to WaferState)

**Files:**
- Modify: `tcad/mesh/interface.py` (remove `gaussian_terms` field from `DopingRegion`)
- Modify: `tcad/physics/doping.py` (`apply_gaussian_implant_doping` drops `existing=`, back to one term per call; `_normalize_gaussian_terms` helper removed)
- Modify: `tcad/device/devsim/doping_mapping.py` (gaussian_implant branch: remove the multi-term Donors/Acceptors-sum code path, keep only the single-expression NetDoping equation)
- Modify: `tcad/physics/dopant_profile.py` (`_gaussian_implant_profiles` drops the `gaussian_terms` branch — Task 1 already wrote the single-term-only version, this task just deletes the now-dead branch if Task 1 left it for compatibility)
- Retire/replace: `tests/unit/test_gaussian_implant_terms_mock.py`, `tests/integration/test_gaussian_implant_terms_devsim_real.py` (this exact multi-term-within-one-DopingRegion coverage is superseded by Task 5's WaferState-level accumulation test — delete these two files in this task, note the replacement test name in the commit message)

**Interfaces:**
- Produces: `apply_gaussian_implant_doping(result, region, junction_axis, peak_position_um, straggle_um, peak_conc_cm3=None, *, donor_peak_conc_cm3=None, acceptor_peak_conc_cm3=None, donor_species=None, acceptor_species=None) -> ProcessResult` (identical to the ORIGINAL Stage-A-era signature — `existing=` parameter removed).

- [ ] **Step 1: Write the failing test (asserting the OLD accumulation mechanism is gone)**

```python
# tests/unit/test_gaussian_implant_no_existing_param_mock.py -- new file
import inspect

def test_apply_gaussian_implant_doping_has_no_existing_param():
    from tcad.physics.doping import apply_gaussian_implant_doping
    sig = inspect.signature(apply_gaussian_implant_doping)
    print(f"apply_gaussian_implant_doping params: {list(sig.parameters)}")
    assert "existing" not in sig.parameters

def test_doping_region_has_no_gaussian_terms_field():
    import dataclasses
    from tcad.mesh.interface import DopingRegion
    field_names = {f.name for f in dataclasses.fields(DopingRegion)}
    print(f"DopingRegion fields: {sorted(field_names)}")
    assert "gaussian_terms" not in field_names
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_gaussian_implant_no_existing_param_mock.py`
Expected: FAIL — both fields/params still present.

- [ ] **Step 3: Implement (delete, don't add)**

Remove `gaussian_terms: Optional[List[Dict[str, Any]]] = None` from `DopingRegion` (`tcad/mesh/interface.py`). Remove the `existing=` parameter and its entire accumulation branch (roughly lines 206-252 of the current `apply_gaussian_implant_doping`, per this session's own earlier reading of the file) from `apply_gaussian_implant_doping`, restoring the plain single-term construction at the end of that function. In `doping_mapping.py`'s `gaussian_implant` branch, delete the `region_doping.gaussian_terms:` conditional entirely, keeping only the single-expression `NetDoping = peak*exp(...)` path that existed before Stage B. Delete `tests/unit/test_gaussian_implant_terms_mock.py` and `tests/integration/test_gaussian_implant_terms_devsim_real.py` (superseded by Task 5's `test_wafer_state_accumulation_devsim_real.py`).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/unit/test_gaussian_implant_no_existing_param_mock.py`
Expected: PASS.

Run the full mock+real suites once here to confirm nothing else references the removed field/param:

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/run_regression.py`
Expected: any remaining references to `gaussian_terms`/`existing=` fail loudly — fix them (they should only be in the two deleted test files and `tcad_2d_stagewise.py`, which Task 9 fixes).

- [ ] **Step 5: Commit**

```bash
git add tcad/mesh/interface.py tcad/physics/doping.py tcad/device/devsim/doping_mapping.py tcad/physics/dopant_profile.py
git rm tests/unit/test_gaussian_implant_terms_mock.py tests/integration/test_gaussian_implant_terms_devsim_real.py
git add tests/unit/test_gaussian_implant_no_existing_param_mock.py
git commit -m "refactor: remove DopingRegion.gaussian_terms/existing= -- multi-term accumulation moves to WaferState (Task 5)"
```

---

### Task 5: `WaferState.dopant_profiles` accumulation wired through the REAL production path (mesh-file-based, not live-domain)

**Critical real-architecture finding, confirmed by reading `tcad_2d_stagewise.py` directly before writing this task (do not skip this reading again in the implementer's own pass):** the GUI's real doping code path (`run_doping()`) NEVER holds a live ViennaPS `Domain` object. Every process step runs in its own subprocess (CLAUDE.md's own documented reason: "the GUI runs every step in its own subprocess, so it cannot hold a live ViennaPS Domain between clicks"); `run_doping()` itself runs on the Tk main thread and only ever has `self.last_final_mesh` (a MESH FILE path) — it builds `process_result = build_process_result({"final_mesh": self.last_final_mesh, "snapshots": []})`, never a live domain. But `WaferState.query(domain)` (Task 2) requires a live domain (`domain.getMaterialMap()`, `domain.getLevelSets()`) — it CANNOT be called from `run_doping()`'s real code path as written. `isotropic.py`'s own internal `WaferState.query()` call (the one confirmed-buggy site from gap analysis) is a DIFFERENT, narrower thing: it runs INSIDE a subprocess worker, mid-step, where a live domain genuinely exists, for `resolve()`-based ETCH-RATE physics resolution — not for doping bookkeeping. **This task therefore needs a mesh-file-based `WaferState` constructor as the PRIMARY mechanism** (since that's what the real GUI/pipeline actually has), with the existing live-domain constructor kept for its own, separate, narrower purpose.

**Files:**
- Modify: `tcad/physics/wafer_state.py` (add the mesh-file-based constructor)
- Modify: `tcad/process/etching/isotropic.py` (fix the confirmed, narrower bug: its OWN internal resolve()-context `WaferState.query()` call never passes `dopant_profiles=` — fixed here as its own small, separate change, NOT as the primary accumulation mechanism)
- Create: `tcad/physics/wafer_state_accumulation.py` (the shared helper — spec §9)
- Test: `tests/integration/test_wafer_state_accumulation_devsim_real.py` (new, real ViennaPS+DevSim — replaces the deleted Task-4 tests' coverage)

**Interfaces:**
- Produces: `WaferState.from_process_result(result: ProcessResult, dopant_profiles: Tuple[DopantProfile, ...] = (), last_step_category: Optional[str] = None) -> WaferState` (Task 2's `WaferState` gains this SECOND constructor, alongside the existing live-domain `.query()`; takes a `ProcessResult`, not a bare path string, so it can resolve real material tag->name the same way `derive_barrier_covered_windows()` already does — via `result.material_regions`). `advance_wafer_state(prior_state: Optional[WaferState], result: ProcessResult, category: str) -> WaferState` — the function the REAL production/GUI path calls (mesh-file-based, via `result.volume_mesh_path`); a separate, narrower live-domain path stays internal to `isotropic.py`'s own resolve() call, unchanged in shape from before this task except for the one-line `dopant_profiles=` fix.
- Consumes: `dopant_profiles_from_doping_profile()` (Task 1), real triangle-mesh scanning technique already used elsewhere in this project (`tcad/device/devsim/mesh_import.py`'s `derive_barrier_covered_windows()`, reproduced verbatim below — not a new mechanism).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_wafer_state_accumulation_devsim_real.py -- new file
"""Real ViennaPS, real mesh FILE (matching the actual GUI/production
path -- no live domain object anywhere in this test, per this task's
own architecture finding). Two SEPARATE apply_gaussian_implant_doping
calls (B, then P -- Task 4 removed the old existing= mechanism)
accumulate at the WaferState layer instead, via advance_wafer_state().
category='doping' for both calls -- neither is a geometry-changing
step."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result  # same helper run_doping() itself uses


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step = registry.get("oxidation", "thermal")()
        recipe = {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            "mask_spans_um": [], "pr_thickness_um": 1.0,
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
        }
        result0 = step.run(recipe, tmp)
        base = build_process_result({"final_mesh": result0["final_mesh"], "snapshots": []})

        b_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=0.2, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state1 = advance_wafer_state(None, b_result, "doping")
        print(f"after B implant: {len(state1.dopant_profiles)} profile(s), "
              f"species={[p.species for p in state1.dopant_profiles]}")
        assert len(state1.dopant_profiles) == 1

        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=0.15, donor_peak_conc_cm3=2e18, donor_species="P",
        )
        state2 = advance_wafer_state(state1, p_result, "doping")
        species = sorted(p.species for p in state2.dopant_profiles)
        print(f"after P implant (via advance_wafer_state, NOT existing=): "
              f"{len(state2.dopant_profiles)} profile(s), species={species}")
        assert species == ["B", "P"], "both must be present -- accumulation now lives at the WaferState layer"

        q = state2.net_doping_at(-1.0, 0.0)
        print(f"net_doping at x=-1.0 (B's own peak): donor={q.donor_concentration:.3e}, "
              f"acceptor={q.acceptor_concentration:.3e}, net={q.net_doping:.3e}")
        assert q.acceptor_concentration > 0 and q.physics_status is None

        # Required acceptance assertion (user's own final review, point 2):
        # a GEOMETRY-CHANGING step in between two doping calls must NOT
        # drop either existing profile. Real etch, positioned away from
        # both B and P so neither is geometry-gated by it -- this phase
        # is purely about whether advance_wafer_state() PRESERVES the
        # accumulated list across a non-doping step, not about erasure
        # (Task 6 owns the erasure claim).
        from tcad.process.etching import isotropic  # noqa: F401
        etch_step = registry.get("etching", "isotropic")(inherited_domain=step.last_domain)
        etch_recipe = {
            "_process_category": "etching", "_process_model_key": "isotropic",
            "rate": -0.02, "etch_time_s": 5.0,  # brief, real, but nowhere near B(-1.0)/P(+1.0)
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "mask_spans_um": [[-4.5, -3.5]],  # opens far from both B and P
        }
        etch_result = etch_step.run(etch_recipe, tmp)
        state3 = advance_wafer_state(
            state2, build_process_result({"final_mesh": etch_result["final_mesh"], "snapshots": []}),
            "etching",
        )
        species_after_etch = sorted(p.species for p in state3.dopant_profiles)
        print(f"after a real, unrelated etch (category='etching', no doping in this step): "
              f"species={species_after_etch}")
        assert species_after_etch == ["B", "P"], (
            "a geometry-changing step with NO doping of its own must still preserve "
            "every previously-accumulated profile -- P doping -> etch -> (implicitly) N "
            "doping must end with BOTH present, not just whichever was implanted last"
        )

        # thermal_history is untouched by advance_wafer_state() -- it only
        # concatenates profile objects, never rewrites any profile's own
        # fields. True by construction (no anneal ran in this test), verified
        # directly rather than merely asserted from the implementation:
        b_profile = next(p for p in state3.dopant_profiles if p.species == "B")
        print(f"B's thermal_history after accumulate+etch: {b_profile.thermal_history} (must be empty -- no anneal ran)")
        assert b_profile.thermal_history == ()

        print("WaferState.dopant_profiles accumulates real, independent B+P profiles "
              "through advance_wafer_state(), from a real mesh FILE -- matching the actual "
              "GUI production path, not a live-domain shortcut -- survives an intervening "
              "geometry-changing step with no doping of its own, and closes the "
              "ProcessResult.doping dual-source-of-truth gap.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_wafer_state_accumulation_devsim_real.py`
Expected: FAIL — `tcad.physics.wafer_state_accumulation` does not exist; `WaferState.from_process_result` does not exist.

- [ ] **Step 3: Implement**

```python
# tcad/physics/wafer_state.py -- ADD a second constructor (Task 2's
# WaferState/DopingQueryResult/net_doping_at are otherwise unchanged)

    @staticmethod
    def from_process_result(
        result: "ProcessResult", dopant_profiles: Tuple[DopantProfile, ...] = (),
        last_step_category: Optional[str] = None,
    ) -> "WaferState":
        """Build WaferState geometry from a real exported mesh FILE via
        ProcessResult (volume_mesh_path/material_field/material_regions)
        instead of a live ViennaPS Domain -- the real construction path
        for the GUI's doping flow (run_doping() never holds a live
        domain; it only ever has a mesh file path, per this task's own
        read of the real production code). Reuses the EXACT real
        triangle-tag-to-name-resolution pattern
        tcad/device/devsim/mesh_import.py's
        derive_barrier_covered_windows() already uses.

        SAFETY CONTRACT (user's own final review, point 1): this
        constructor is GEOMETRY-ONLY -- it has no memory of any prior
        WaferState and does NOT know about "the accumulated dopant
        list" by itself. Calling it directly with the default
        `dopant_profiles=()` silently produces a state with NO dopant
        profiles at all, even if a real prior state existed. This is
        safe ONLY for throwaway, geometry-only diagnostics (e.g.
        checking exposed_material_at at some x) whose result is NEVER
        assigned back to the real accumulating state variable
        (`app.wafer_state`, or any `stateN` a test keeps building on).
        The ONLY sanctioned way to build/advance the real accumulating
        state is `advance_wafer_state()` (below), which explicitly
        threads `prior_state.dopant_profiles + this_step_profiles`
        through this constructor -- never call this constructor
        directly for that purpose. (The tag->name resolution itself is
        `tag_to_name = {region.tag: region.name for region in
        result.material_regions}`, verbatim from that function.)
        """
        import meshio

        tag_to_name = {region.tag: region.name for region in result.material_regions}
        mesh = meshio.read(result.volume_mesh_path)
        triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)

        cells = []
        if triangle_block is not None and result.material_field in mesh.cell_data:
            block_index = mesh.cells.index(triangle_block)
            tags = mesh.cell_data[result.material_field][block_index]
            points = mesh.points
            for triangle, tag in zip(triangle_block.data, tags):
                corners = points[triangle]
                name = tag_to_name.get(int(tag), f"?{int(tag)}")
                cells.append(_Cell(
                    x_min=corners[:, 0].min(), x_max=corners[:, 0].max(),
                    y_max=corners[:, 1].max(), material=name,
                ))

        materials = tuple(sorted({c.material for c in cells}))
        return WaferState(
            materials=materials,
            stack=tuple(LayerInfo(m, i) for i, m in enumerate(materials)),
            # grid_delta_um is not derivable from a bare exported mesh
            # file (no recipe/domain object to read it from here) --
            # confirmed by reading net_doping_at()/exposed_material_at()
            # (Task 2): neither reads grid_delta_um at all, only
            # _cells/dopant_profiles. 0.0 is a real, inert value for
            # this construction path, not a guess standing in for
            # missing logic -- _thin_layer_positions (the ONLY consumer
            # of grid_delta_um) is a live-domain-only diagnostic and is
            # never computed here (_thin_x=() below, matching that this
            # constructor has no level-set access to derive it from).
            grid_delta_um=0.0,
            _cells=tuple(cells), _thin_x=(),
            dopant_profiles=dopant_profiles, last_step_category=last_step_category,
        )
```

```python
# tcad/physics/wafer_state_accumulation.py -- new file
"""The function the REAL production/GUI doping path calls to advance
WaferState (spec 2026-09-03 Sec9) -- mesh-file-based, matching what
run_doping() actually has (no live domain, per this task's own finding).
A SEPARATE, narrower fix applies inside isotropic.py's own resolve()
context, which DOES have a live domain -- see below, not this function."""
from typing import Optional

from tcad.mesh.interface import ProcessResult
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState


def advance_wafer_state(
    prior_state: Optional[WaferState], result: ProcessResult, category: str,
) -> WaferState:
    prior_profiles = prior_state.dopant_profiles if prior_state is not None else ()
    this_step_profiles = (
        dopant_profiles_from_doping_profile(result.doping)
        if result.doping is not None else ()
    )
    return WaferState.from_process_result(
        result,
        dopant_profiles=prior_profiles + this_step_profiles,
        last_step_category=category,
    )
```

**Separate, narrower fix**: `tcad/process/etching/isotropic.py`'s OWN internal `resolve()`-context call (a genuinely live-domain context, since it runs inside the subprocess worker mid-step) is fixed in place, NOT routed through `advance_wafer_state()` above (that function is mesh-file-based; this call site has a live domain and a different purpose — etch-rate physics resolution, not doping bookkeeping):
```python
# before (tcad/process/etching/isotropic.py:72):
        state = WaferState.query(geometry)
# after:
        state = WaferState.query(geometry, dopant_profiles=(), last_step_category="etching")
```
(Read the exact surrounding code before editing — confirm the real local variable name for "the domain object at this point" is `geometry` as CLAUDE.md's own gap-analysis quote states, not assumed; `dopant_profiles=()` is correct here — this call site resolves etch-RATE physics, which today's model does not condition on doping at all, so there is no real prior-profile list to thread through this SPECIFIC call even after this fix; it exists only so this WaferState's OWN `last_step_category` is correctly set to `"etching"` for whatever it's used for internally.)

**Scope boundary, explicit**: this task does NOT add `resolve()`-based physics resolution to any category that doesn't already have it (oxidation, deposition, other etch models) — that is out of scope, unchanged from the base 2026-08-25 design's own staged rollout, and doing so here would be exactly the kind of unrelated refactor CLAUDE.md's Development Rules forbid ("Do not refactor unrelated code"). The ONLY two things this task wires are: (1) `advance_wafer_state()`/`WaferState.from_process_result()` as the real, mesh-file-based doping-accumulation mechanism Task 9 calls from the GUI, and (2) the one-line `dopant_profiles=()`/`last_step_category="etching"` fix to `isotropic.py`'s own pre-existing, unrelated `resolve()` call.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_wafer_state_accumulation_devsim_real.py`
Expected: PASS with the real printed species list `['B', 'P']`, built entirely from a real mesh FILE path, no live domain.

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/wafer_state.py tcad/physics/wafer_state_accumulation.py tcad/process/etching/isotropic.py tests/integration/test_wafer_state_accumulation_devsim_real.py
git commit -m "feat: advance_wafer_state()/WaferState.from_process_result() -- real mesh-file-based cross-step dopant accumulation matching the actual GUI production path"
```

---

### Task 6: Real geometry/state order-sensitivity acceptance test (CE-1) — NOT a depth-dependent-removal claim

**Critical scope correction (read before writing this test):** the current Gaussian model's `concentration_at(x, depth)` interface accepts `depth` but every real implementation IGNORES it (confirmed, Task 1). **This test must never claim or rely on "a shallow implant was removed because it was shallow while a deep one would have survived"** — that is an UNSUPPORTED, depth-dependent physics claim this model cannot make. What the model CAN honestly demonstrate, with real ViennaPS geometry, is purely x-only: a real etch makes Si genuinely absent (not merely recessed — recessed Si is STILL the topmost material at that x per `exposed_material_at`'s real, existing by-x-column logic, so a MERE recess produces NO geometry-gated zero at all; this task's own Step 1 verification below confirms with real numbers that the chosen etch removes Si completely, not partially, at the target x-range) at a given x-range; a profile whose `host_material="Si"` there reads geometry-gated zero afterward regardless of its own `straggle_um`; and swapping WHICH species existed at that x-range BEFORE the etch (and is therefore erased) versus which one is placed at a DIFFERENT, untouched x-range AFTER the etch determines the final `WaferState`'s species composition and net polarity. This is a real, x-only, model-honest demonstration of geometry/state order-sensitivity — not evidence of depth-selective implant/etch physics.

**Files:**
- Test: `tests/integration/test_ce1_order_sensitive_geometry_real.py` (new, real ViennaPS+DevSim)

**Interfaces:**
- Consumes: `advance_wafer_state()` (Task 5, mesh-file-based signature: `advance_wafer_state(prior_state, result, category)`), `WaferState.net_doping_at()` (Task 2).

- [ ] **Step 1: Write the real test, INCLUDING a real pre-check that the etch removes Si completely (not a recess) at the target x-range**

```python
# tests/integration/test_ce1_order_sensitive_geometry_real.py
"""Spec 2026-09-03 CE-1 (corrected scope): geometry/state order-
sensitivity, X-ONLY -- no depth-dependent claim anywhere in this file.
Two disjoint x-regions: R_ETCH (real ViennaPS etch removes Si there
COMPLETELY -- verified below, not assumed) and R_SAFE (never touched).
Whichever species existed at R_ETCH before the etch is erased there
(geometry-gated zero); a DIFFERENT species is placed at R_SAFE after
the etch. Swapping which species plays which role flips the wafer's
final species composition and net polarity -- this is the real,
model-honest form of "process order changes the final WaferState."
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation, tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result

WIDTH_UM, Y_EXTENT_UM, SI_DEPTH_UM, GRID_UM = 10.0, 8.0, 5.0, 0.2
R_ETCH_X, R_SAFE_X = 0.0, 3.5   # disjoint x positions; R_SAFE is far outside the etch mask window


def _fresh_wafer(tmp):
    step = registry.get("oxidation", "thermal")()
    recipe = {
        "_process_category": "oxidation", "_process_model_key": "thermal",
        "mask_spans_um": [], "pr_thickness_um": 1.0,
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": WIDTH_UM, "y_extent_um": Y_EXTENT_UM,
        "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
    }
    result = step.run(recipe, tmp)
    return step, build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})


def _real_etch(tmp, inherited_domain):
    """A real, through-Si trench at R_ETCH_X -- deep/long enough to
    remove Si COMPLETELY there (verified by the caller, not assumed
    from the recipe numbers alone)."""
    etch_step = registry.get("etching", "isotropic")(inherited_domain=inherited_domain)
    etch_recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        "etch_time_s": 600.0, "isotropic_rate_um_per_s": 0.02,  # real, through-depth removal
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": WIDTH_UM, "y_extent_um": Y_EXTENT_UM,
        "mask_spans_um": [[3.5, 6.5]],  # opens a window centered near R_ETCH_X=0? -- see Step 2 note
    }
    result = etch_step.run(etch_recipe, tmp)
    return build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})


def run_order(tmp, region_species):
    """region_species: {"etch": (kwarg, species), "safe": (kwarg, species)} --
    which species targets R_ETCH_X (implanted BEFORE the etch) vs R_SAFE_X
    (implanted AFTER the etch)."""
    step, base = _fresh_wafer(tmp)
    etch_kwarg, etch_species = region_species["etch"]
    safe_kwarg, safe_species = region_species["safe"]

    r1 = apply_gaussian_implant_doping(
        base, region="Si", junction_axis="x", peak_position_um=R_ETCH_X, straggle_um=0.3,
        **{etch_kwarg: 1e18, f"{etch_kwarg.split('_')[0]}_species": etch_species},
    )
    state1 = advance_wafer_state(None, r1, "doping")

    from tcad.physics.wafer_state import WaferState
    pre_etch_state = WaferState.from_process_result(base, last_step_category=None)
    print(f"[pre-etch] exposed material at R_ETCH_X={R_ETCH_X}: "
          f"{pre_etch_state.exposed_material_at(R_ETCH_X)}")

    etched_result = _real_etch(tmp, step.last_domain)
    post_etch_state_for_check = WaferState.from_process_result(etched_result, last_step_category=None)
    exposed_after = post_etch_state_for_check.exposed_material_at(R_ETCH_X)
    print(f"[post-etch] exposed material at R_ETCH_X={R_ETCH_X}: {exposed_after}")
    assert exposed_after != "Si", (
        f"the etch must remove Si COMPLETELY at R_ETCH_X (a recess that leaves Si "
        f"still topmost there would produce NO geometry-gated zero at all) -- "
        f"got exposed_material_at={exposed_after!r}, tune etch_time_s/mask_spans_um "
        f"and re-run this check before trusting the rest of this test"
    )

    state1_post_etch = advance_wafer_state(state1, etched_result, "etching")

    r2 = apply_gaussian_implant_doping(
        etched_result, region="Si", junction_axis="x", peak_position_um=R_SAFE_X, straggle_um=0.3,
        **{safe_kwarg: 1e18, f"{safe_kwarg.split('_')[0]}_species": safe_species},
    )
    state2 = advance_wafer_state(state1_post_etch, r2, "doping")

    q_etch = state2.net_doping_at(R_ETCH_X, 0.0)
    q_safe = state2.net_doping_at(R_SAFE_X, 0.0)
    print(f"  R_ETCH_X net_doping: {q_etch.net_doping:.3e} (physics_status={q_etch.physics_status})")
    print(f"  R_SAFE_X net_doping: {q_safe.net_doping:.3e}")
    return q_etch, q_safe


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("=== Order 1: B at R_ETCH (erased), P at R_SAFE (survives) ===")
        q_etch_1, q_safe_1 = run_order(tmp, {
            "etch": ("acceptor_peak_conc_cm3", "B"),
            "safe": ("donor_peak_conc_cm3", "P"),
        })
    with tempfile.TemporaryDirectory() as tmp2:
        print("\n=== Order 2 (swapped): P at R_ETCH (erased), B at R_SAFE (survives) ===")
        q_etch_2, q_safe_2 = run_order(tmp2, {
            "etch": ("donor_peak_conc_cm3", "P"),
            "safe": ("acceptor_peak_conc_cm3", "B"),
        })

    # R_ETCH_X: whichever species was placed there before the etch is
    # erased either way -- both orders must read (near) zero there.
    assert q_etch_1.physics_status is None and abs(q_etch_1.net_doping) < 1.0
    assert q_etch_2.physics_status is None and abs(q_etch_2.net_doping) < 1.0

    # R_SAFE_X: the SIGN must flip -- Order 1 ends with P (donor, positive)
    # surviving there; Order 2 ends with B (acceptor, negative) instead.
    print(f"\nR_SAFE_X net_doping: Order 1={q_safe_1.net_doping:.3e}, Order 2={q_safe_2.net_doping:.3e}")
    assert (q_safe_1.net_doping > 0) and (q_safe_2.net_doping < 0), (
        "swapping which species is assigned to the doomed (R_ETCH) vs safe (R_SAFE) "
        "role must flip R_SAFE's final polarity -- this is real geometry/state "
        "order-sensitivity, x-only, no depth claim involved"
    )
    print("\nOrder-sensitivity confirmed with real ViennaPS geometry: whichever species "
          "existed at the etched location is erased there regardless of order; the "
          "OTHER location's final species (and therefore polarity) depends entirely "
          "on which role each species was assigned -- a real, x-only, model-honest "
          "demonstration, not a claim about depth-selective physics.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it currently fails or errors**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce1_order_sensitive_geometry_real.py`
Expected: the FIRST real thing to check is the printed `[pre-etch]`/`[post-etch]` `exposed_material_at(R_ETCH_X)` lines and the assertion right after them. **Do not proceed past this check by assumption** — if `exposed_after == "Si"` (a mere recess, not a complete removal), the test's own assertion catches this immediately with a clear message; fix it by adjusting `mask_spans_um`/`R_ETCH_X`/`etch_time_s` (the mask window `[3.5, 6.5]` and `R_ETCH_X=0.0` as drafted here do NOT obviously line up — this is a real gap deliberately left for the implementer to resolve by reading `mask_spans_from_openings`'s real coordinate convention and this project's own established centered-domain convention (`x in [-width/2, +width/2]`, per CLAUDE.md's own documented PN-diode investigation) before picking real, verified numbers — do not guess coordinates, print and check them).

- [ ] **Step 3: N/A (test-only task, no production code to write)**

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce1_order_sensitive_geometry_real.py`
Expected: PASS, with real printed net_doping values showing R_SAFE_X's sign flipping between the two orders and R_ETCH_X reading ~zero in both.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce1_order_sensitive_geometry_real.py
git commit -m "test: CE-1 geometry/state order-sensitivity, real ViennaPS -- x-only, no depth-dependent physics claim"
```

---

### Task 7: Real oxidation-conversion `UNSUPPORTED_BY_MODEL` acceptance test (CE-2)

**Critical scope correction (same as Task 6): no depth-based probing anywhere in this test.** The earlier draft compared a "shallow" probe (`net_doping_at(x, 0.02)`) against a "deep" one (`net_doping_at(x, 3.0)`) to claim oxidation "penetrated" to some depth — **deleted**. `depth_um` is accepted by every current `concentration_at` but ignored (Task 1), and `exposed_material_at(x)` (the real gating check) does not take a depth argument at all — it already only depends on x. CE-2's real content is therefore: (1) confirm via a REAL mesh probe that a FIXED absolute coordinate is `Si` before oxidation and `SiO2` after (mirroring this session's own already-run `arch_validate_q1q2.py` experiment exactly — reuse its real numbers/approach, do not re-derive from scratch); (2) confirm the SAME fixed x-position, queried through `WaferState.net_doping_at`, reports `UNSUPPORTED_BY_MODEL` post-oxidation; (3) confirm a SEPARATE x-position, protected by a real oxidation mask so it remains real Si, stays fully computable (the partial-aggregate contract, spec Sec6) — with NO claim anywhere about "how deep" oxidation reached.

**Files:**
- Test: `tests/integration/test_ce2_oxidation_conversion_unsupported_real.py` (new, real ViennaPS+DevSim)

**Interfaces:**
- Consumes: Tasks 1, 2, 5.

- [ ] **Step 1: Write the real test**

```python
# tests/integration/test_ce2_oxidation_conversion_unsupported_real.py
"""Spec CE-2, executable, x-only (no depth claim): a dopant whose Si is
CONSUMED by a real oxidation (Si -> SiO2 conversion AT A FIXED ABSOLUTE
COORDINATE, directly re-verified here the same way this session's own
arch_validate_q1q2.py experiment already confirmed it) must report
UNSUPPORTED_BY_MODEL for its fate there -- never a silent geometry-
gated 0. A SEPARATE profile, protected by a real oxidation mask so its
own x-position stays real Si, must still return its real value (the
partial-aggregate contract, spec Sec6)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result

X_CONVERTED, X_PROTECTED = 0.0, -3.5   # X_PROTECTED must sit under the oxidation mask -- verified below, not assumed


def _material_at(mesh_path, x_um, y_um, tol=0.15):
    import viennaps as vps
    mesh = meshio.read(mesh_path)
    names = {}
    for attr in dir(vps.Material):
        if attr.startswith("_"):
            continue
        v = getattr(vps.Material, attr)
        if isinstance(v, vps.Material):
            names.setdefault(int(v), attr)
    best = None
    for key, blocks in mesh.cell_data.items():
        if "material" not in key.lower():
            continue
        for cells, values in zip(mesh.cells, blocks):
            for cell, tag in zip(cells.data, np.asarray(values).ravel()):
                corners = mesh.points[cell]
                if abs(corners[:, 0].mean() - x_um) >= tol or abs(corners[:, 1].mean() - y_um) >= tol:
                    continue
                name = names.get(int(tag), f"?{int(tag)}")
                if best is None:
                    best = name
    return best


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step0 = registry.get("oxidation", "thermal")()
        recipe0 = {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            # A non-empty mask protects X_PROTECTED from THIS oxidation --
            # confirm the real span semantics (does mask_spans_um name the
            # OPENING or the PROTECTED span for this model?) by reading
            # tcad/process/oxidation/thermal.py's own prepare_domain()
            # before trusting this literal value; do not guess.
            "mask_spans_um": [[-5.0, -2.0]], "pr_thickness_um": 1.0,
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
        }
        result0 = step0.run(recipe0, tmp)
        base = build_process_result({"final_mesh": result0["final_mesh"], "snapshots": []})

        before_converted = _material_at(result0["final_mesh"], X_CONVERTED, 0.1)
        before_protected = _material_at(result0["final_mesh"], X_PROTECTED, 0.1)
        print(f"[before oxidation] X_CONVERTED={X_CONVERTED}: {before_converted}, "
              f"X_PROTECTED={X_PROTECTED}: {before_protected}")
        assert before_converted == "Si" and before_protected == "Si"

        n_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=X_CONVERTED,
            straggle_um=0.3, donor_peak_conc_cm3=1e18, donor_species="P",
        )
        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=X_PROTECTED,
            straggle_um=0.3, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state1 = advance_wafer_state(None, n_result, "doping")
        state1 = advance_wafer_state(state1, p_result, "doping")

        recipe1 = dict(recipe0)
        recipe1["temperature_c"], recipe1["time_hours"] = 1050.0, 0.3
        step1 = registry.get("oxidation", "thermal")(inherited_domain=step0.last_domain)
        result1 = step1.run(recipe1, tmp)

        after_converted = _material_at(result1["final_mesh"], X_CONVERTED, 0.1)
        after_protected = _material_at(result1["final_mesh"], X_PROTECTED, 0.1)
        print(f"[after oxidation]  X_CONVERTED={X_CONVERTED}: {after_converted}, "
              f"X_PROTECTED={X_PROTECTED}: {after_protected}")
        assert after_converted != "Si", (
            f"X_CONVERTED must genuinely flip material (mirroring this session's own "
            f"real Si->SiO2 measurement) -- got {after_converted!r}; if this fails, "
            f"the recipe's temperature_c/time_hours need real tuning, same as this "
            f"session's own arch_validate_q1q2.py experiment needed"
        )
        assert after_protected == "Si", (
            f"X_PROTECTED must stay real Si (proves the mask genuinely protects it) -- "
            f"got {after_protected!r}; if this fails, mask_spans_um's real span "
            f"semantics were guessed wrong above -- read prepare_domain() for real"
        )

        state2 = advance_wafer_state(
            state1, build_process_result({"final_mesh": result1["final_mesh"], "snapshots": []}),
            "oxidation",
        )

        q_converted = state2.net_doping_at(X_CONVERTED, 0.0)
        print(f"[X_CONVERTED] donor={q_converted.donor_concentration}, "
              f"physics_status={q_converted.physics_status}")
        assert q_converted.physics_status is not None
        assert q_converted.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"

        q_protected = state2.net_doping_at(X_PROTECTED, 0.0)
        print(f"[X_PROTECTED] donor={q_protected.donor_concentration:.3e}, "
              f"acceptor={q_protected.acceptor_concentration:.3e}, "
              f"physics_status={q_protected.physics_status}")
        assert q_protected.physics_status is None
        assert q_protected.acceptor_concentration > 0

        print("Oxidation's real Si->SiO2 conversion (at a fixed absolute x, mask-verified) "
              "correctly reports UNSUPPORTED_BY_MODEL for the consumed dopant's fate (never "
              "a silent 0), while a mask-protected profile elsewhere stays fully computable "
              "-- CE-2 confirmed, x-only, no depth-penetration claim made anywhere.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce2_oxidation_conversion_unsupported_real.py`
Expected: the real mesh-probe assertions (`before_converted`/`before_protected`/`after_converted`/`after_protected`) are the first real signal — do not proceed past them by assumption. If `mask_spans_um`'s real semantics differ from what's drafted here (opening vs. protected span), the `after_protected == "Si"` assertion catches it immediately with a clear message; fix by reading `tcad/process/oxidation/thermal.py`'s `prepare_domain()` for the real convention, then re-run.

- [ ] **Step 3: N/A (test-only)**

- [ ] **Step 4: Confirm pass with real printed physics_status showing `UNSUPPORTED_BY_MODEL` at X_CONVERTED and `None` (fully computable) at X_PROTECTED.**

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce2_oxidation_conversion_unsupported_real.py
git commit -m "test: CE-2, real ViennaPS -- oxidation's Si conversion reports UNSUPPORTED_BY_MODEL at a fixed coordinate, never silent 0; x-only, no depth claim"
```

---

### Task 8: DevSim per-node NetDoping conversion (`set_node_values`, replacing symbolic kind-dispatch)

**Classification, explicit (user's own final review, point 3): this task's per-node checks are a WaferState↔DevSim COUPLING / NUMERICAL-CONSISTENCY check, NOT a physical-correctness validation.** The values written into DevSim are computed BY `WaferState.net_doping_at()` and then read back — confirming the write/read pipeline and unit conversion transport a number without transcription error, not independently re-proving the underlying Gaussian formula is physically correct (that was already done, separately, by Task 1's real DevSim cross-check against `test_dopant_profile_matches_devsim_real.py`, and by Stage A/B's own prior work). Every docstring, print statement, and Step 4 description in this task says "coupling"/"numerical consistency", never "physical validation" — do not blur the two.

**Also required (user's own final review, standing invariant): no bypass that lets `ProcessResult.doping` act as cross-step canonical state again.** Grep for every existing caller of the OLD `apply_doping(...)` before starting — this MUST include `run_measurement()` in `tcad_2d_stagewise.py` by name (its own docstring, read directly this session, states it calls `run_doping()` internally "to re-attach stale doping to the current mesh"). Two real risks to resolve while updating it, not to silently assume away:
1. If `run_measurement()` currently solves DevSim directly from `self.last_doped_result.doping` (bypassing `WaferState` entirely), it must be changed to use `self.wafer_state` instead — otherwise it is exactly the "`ProcessResult.doping` reused as canonical state" bypass this whole plan exists to close.
2. If `run_measurement()`'s "re-attach" flow works by calling `run_doping()` again (Task 9's own real code path, which now unconditionally APPENDS to `self.wafer_state.dopant_profiles` every call), a naive re-attach could silently DUPLICATE the same profile in the accumulated list. Read `run_measurement()`'s real body before finalizing this task; if this risk is real, fix it (e.g. re-attachment should refresh geometry without re-appending an unchanged profile) rather than shipping a silent double-count. Report the real finding either way — do not guess that it is fine.

**Files:**
- Modify: `tcad/device/devsim/doping_mapping.py` (`apply_doping()` — replace the kind-based equation-string branches with one generic per-node Python evaluation path)
- Test: `tests/integration/test_doping_mapping_per_node_real.py` (new)

**Interfaces:**
- Consumes: `WaferState.net_doping_at()` (Task 2), real DevSim `get_node_model_values`/`set_node_values` (already used elsewhere in this codebase, per spec §10).
- Produces: `apply_doping(device: str, region: str, state: WaferState) -> Optional[dict]` (returns the aggregated `physics_status` across every node that had a gap, or `None` if none did — mirrors the existing project convention of surfacing `physics_status` from a doping-application call).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_doping_mapping_per_node_real.py
"""WaferState<->DevSim COUPLING / NUMERICAL-CONSISTENCY check (NOT a
physical-correctness validation -- that is Task 1's job, separately,
against test_dopant_profile_matches_devsim_real.py). Real DevSim:
apply_doping() now evaluates WaferState.net_doping_at() at every REAL
mesh node (via get_node_model_values(name='x'/'y'), already used in
voltage_probe.py) and writes via set_node_values -- replacing the old
symbolic node_model(equation=...) kind-dispatch. This test confirms the
write/read pipeline transports WaferState's own numbers into DevSim
without transcription or unit-conversion error.

Unit-conversion fact, confirmed by reading the real, existing
apply_doping() signature and voltage_probe.py's real usage (NOT
guessed): `length_scale_to_cm: float = 1.0` is the REAL, established
default in this codebase -- meaning DevSim's own "x"/"y" node models
are, BY DEFAULT, in the SAME numeric scale as this project's own um
convention (no 1e-4 cm/um conversion happens unless a caller explicitly
imports with a different length_scale_to_cm). This test verifies that
fact directly rather than assuming any particular multiplier."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import tcad.process.oxidation  # noqa: F401
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
import devsim

X_EXTENT_UM = 10.0


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step = registry.get("oxidation", "thermal")()
        recipe = {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            "mask_spans_um": [], "pr_thickness_um": 1.0,
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": X_EXTENT_UM, "y_extent_um": 8.0,
            "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
        }
        result = step.run(recipe, tmp)
        base = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        r_p = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=3.0, donor_peak_conc_cm3=3e18, donor_species="P",
        )
        r_b = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=3.0, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state = advance_wafer_state(None, r_p, "doping")
        state = advance_wafer_state(state, r_b, "doping")

        # import_process_result's own real length_scale_to_cm default --
        # read from its own signature, not assumed, and passed through
        # explicitly to apply_doping below so both sides of the pipeline
        # genuinely agree (rather than each defaulting independently).
        device_name, region_name = import_process_result(base, device_name="ce_dev")
        length_scale_to_cm = 1.0  # matches import_process_result's own real default; see Step 3 note

        try:
            xs_native = devsim.get_node_model_values(device=device_name, region=region_name, name="x")
            ys_native = devsim.get_node_model_values(device=device_name, region=region_name, name="y")
            xs_um_before = [x / length_scale_to_cm for x in xs_native]
            print(f"real node x range (converted to um): [{min(xs_um_before):.4f}, {max(xs_um_before):.4f}] "
                  f"-- must fall inside the domain's own x_extent_um={X_EXTENT_UM} "
                  f"(centered convention: [-{X_EXTENT_UM/2}, +{X_EXTENT_UM/2}])")
            assert min(xs_um_before) >= -X_EXTENT_UM / 2 - 0.5
            assert max(xs_um_before) <= X_EXTENT_UM / 2 + 0.5

            physics_status = apply_doping(
                device_name, region_name, state, length_scale_to_cm=length_scale_to_cm,
            )
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"checked {len(xs_native)} real DevSim nodes")
            print(f"NetDoping range: [{min(net):.3e}, {max(net):.3e}]")
            print(f"physics_status: {physics_status}")
            assert max(net) > 0 and min(net) < 0, "both donor- and acceptor-dominated regions must exist"

            # Direct per-node cross-check, several REAL nodes, not just
            # min/max: DevSim (x_native,y_native) -> project (x_um,y_um)
            # -> state.net_doping_at(...).net_doping -> compare against
            # the REAL value DevSim now holds at that exact node.
            checked = 0
            for i in range(0, len(xs_native), max(1, len(xs_native) // 20)):  # ~20 real nodes spread across the mesh
                x_um = xs_native[i] / length_scale_to_cm
                y_um = ys_native[i] / length_scale_to_cm
                expected = state.net_doping_at(x_um, y_um).net_doping
                actual = net[i]
                print(f"  node[{i}] (x={x_um:.3f}um, y={y_um:.3f}um): "
                      f"state.net_doping_at={expected:.6e}, DevSim NetDoping={actual:.6e}")
                assert abs(expected - actual) < 1e-6 * max(abs(expected), 1.0), (
                    f"node[{i}]: WaferState's own computed value and DevSim's real stored "
                    f"NetDoping must agree exactly -- they are the SAME number, written "
                    f"and read back through the real pipeline, not independently derived"
                )
                checked += 1
            print(f"cross-checked {checked} real DevSim nodes directly against "
                  f"WaferState.net_doping_at() -- all agree.")
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=device_name)

        print("Real per-node NetDoping written via set_node_values(), cross-checked "
              "node-by-node against a real DevSim device -- kind-based symbolic "
              "equations retired.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_doping_mapping_per_node_real.py`
Expected: FAIL — `apply_doping()`'s current signature takes a `ProcessResult`/`DopingProfile`, not a `WaferState`.

- [ ] **Step 3: Implement**

**Read `tcad/device/devsim/doping_mapping.py`'s and `tcad/device/devsim/mesh_import.py`'s real, EXISTING `length_scale_to_cm: float = 1.0` parameter before writing this** (grep confirms it: both files already default it to `1.0`, and `mesh_import.py`'s own docstring states "multiplies every mesh coordinate before import" — meaning DevSim's stored node "x"/"y" values are ALREADY in this project's own um-equivalent scale whenever the default is used, contrary to an easy but wrong assumption that DevSim always stores physical cm). The new `apply_doping()` keeps this SAME real parameter, rather than hardcoding any conversion literal:

```python
# tcad/device/devsim/doping_mapping.py -- apply_doping REWRITTEN
def apply_doping(
    device: str, region: str, state: "WaferState", length_scale_to_cm: float = 1.0,
) -> Optional[dict]:
    """Real per-node NetDoping (spec 2026-09-03 Sec10) -- replaces
    every prior kind-based symbolic-equation branch. Works identically
    regardless of how many DopantProfiles WaferState carries or which
    models produced them. length_scale_to_cm MUST match whatever value
    the device's own import_process_result() call used (this project's
    existing convention, already documented on the pre-existing
    apply_doping()'s own length_scale_to_cm parameter -- preserved
    here, not reinvented)."""
    import devsim
    from tcad.physics.values import combine, Resolution

    xs_native = devsim.get_node_model_values(device=device, region=region, name="x")
    ys_native = devsim.get_node_model_values(device=device, region=region, name="y")
    donors, acceptors, nets = [], [], []
    all_entries = []
    for x_native, y_native in zip(xs_native, ys_native):
        x_um = x_native / length_scale_to_cm
        y_um = y_native / length_scale_to_cm
        result = state.net_doping_at(x_um, y_um)
        donors.append(result.donor_concentration)
        acceptors.append(result.acceptor_concentration)
        nets.append(result.net_doping)
        if result.physics_status is not None:
            all_entries.extend(result.physics_status["entries"])

    devsim.node_model(device=device, region=region, name="Donors", equation="0")
    devsim.set_node_values(device=device, region=region, name="Donors", values=donors)
    devsim.node_model(device=device, region=region, name="Acceptors", equation="0")
    devsim.set_node_values(device=device, region=region, name="Acceptors", values=acceptors)
    devsim.node_model(device=device, region=region, name="NetDoping", equation="0")
    devsim.set_node_values(device=device, region=region, name="NetDoping", values=nets)

    if not all_entries:
        return None
    resolutions = [Resolution(e["resolution"]) for e in all_entries]
    return {"resolution": combine(resolutions).value, "entries": all_entries, "notes": []}
```

(`node_model(..., equation="0")` is required BEFORE `set_node_values` — confirmed real DevSim requirement already implicit in this project's existing `semiconductor_equation.py` usage: a node model must be REGISTERED before its values can be set.)

Every existing CALLER of the old `apply_doping(...)` (grep for it across `tcad/device/devsim/mesh_import.py`, the GUI, and every real integration test that calls it directly) must be updated to build a `WaferState` (via `advance_wafer_state()`) and call the new signature, passing the SAME `length_scale_to_cm` the corresponding `import_process_result()` call used — this is expected to be the largest mechanical part of this task; enumerate every call site with `grep -rn "apply_doping(" tests/ tcad/` before starting, and update each one, not just the ones this brief happened to name.

**Real, confirmed caller (read directly this session, not guessed): `tcad_2d_stagewise.py`'s `run_measurement()` calls the OLD signature exactly as**
```python
apply_doping(
    imported.device, doped_result.doping,
    length_scale_to_cm=length_scale_to_cm,
    exclude_windows=exclude_windows, exclude_axis="x",
)
```
**This exposes a real feature-parity gap this task must resolve, not silently drop:** the OLD signature accepts `exclude_windows`/`exclude_axis` — the real, already-shipped SiO2-barrier-exclusion mechanism ("SiO2 no longer silently fails to block doping", `derive_barrier_covered_windows()`). The NEW signature drafted above (`apply_doping(device, region, state, length_scale_to_cm)`) has no equivalent parameter. Before finalizing this task, read `derive_barrier_covered_windows()`'s full body and the OLD `apply_doping()`'s own equation-construction code (specifically how `exclude_windows`/`exclude_axis` shape the NetDoping equation string) to determine: does this exclusion concern belong at PROFILE-CREATION time (an `apply_gaussian_implant_doping()`-family argument, shaping which windows a NEW profile even applies to) or does it need its own parameter on the NEW `apply_doping()` too? Do not assume WaferState's own geometry-gating (§3) already subsumes it without checking — geometry-gating only knows "is `profile.host_material` exposed at `(x, y)` RIGHT NOW"; barrier exclusion may be a distinct, independent masking concept (which windows a doping call was even SPECIFIED to affect, decided using geometry at CREATION time, not query time) that this project currently implements at the DEVICE layer specifically because the OLD equation-string approach had no other way to express it. Resolve this for real, then update `run_measurement()`'s own call accordingly and re-run `test_doping_barrier_windows_real.py` (already in this task's own regression list below) to confirm the real barrier-exclusion behavior survives unchanged.

**Also confirmed in `run_measurement()`: the `implant_windows` kind bypasses `apply_doping()` entirely**, calling `run_robust_pn_junction_iv_sweep(..., doping=doped_result.doping, ...)` directly (`tcad/characterization/robust_iv_sweep.py`, which registers its own NetDoping via a doping-level continuation ramp). This function is NOT part of this task's scope to rewrite for multi-profile `WaferState` awareness — it is real, working, separately-verified code (`test_robust_iv_sweep_real.py`) built around a single `DopingProfile`'s own implant_windows shape specifically for the 1e20 cm^-3 convergence problem it solves. Document explicitly, in this task's own report, that an `implant_windows`-kind measurement through `run_measurement()` still reflects only its OWN profile, not any OTHER accumulated profile in `self.wafer_state` — a disclosed, real limitation, not a silent gap.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_doping_mapping_per_node_real.py`
Expected: PASS with real printed NetDoping range spanning both signs, AND ~20 real per-node cross-checks all agreeing between `WaferState.net_doping_at()` and DevSim's own stored `NetDoping`.

Also re-run every PREVIOUSLY-passing doping-related real integration test this task's signature change touches (`test_phase7_doping_real.py`, `test_phase8_pn_junction_real.py`, `test_implant_windows_doping_real.py`, `test_doping_barrier_windows_real.py`, `test_gaussian_implant_doping_real.py`) to confirm zero regression in the actual computed NetDoping values (same physics, new mechanism) — this is the load-bearing check for this task, not merely "the new test passes."

- [ ] **Step 5: Commit**

```bash
git add tcad/device/devsim/doping_mapping.py tests/integration/test_doping_mapping_per_node_real.py
# plus every updated call site enumerated above
git commit -m "feat: real per-node NetDoping via set_node_values(), replacing symbolic kind-dispatch equations"
```

---

### Task 9: GUI rewiring — doping accumulation + anneal dispatch through the real new path

**Real production code, read directly before writing this task (do not re-derive from memory — quoted here verbatim from `tcad_2d_stagewise.py` as it exists today):**

`run_doping()` (lines ~4019-4218) builds `process_result = build_process_result({"final_mesh": self.last_final_mesh, "snapshots": []})` — a MESH-FILE-based `ProcessResult`, never a live domain (confirmed, Task 5's own architecture finding) — dispatches on `kind = self.doping_kind.get()`, and for `"Gaussian Implant"` specifically has the accumulation block Task 4 removes entirely:
```python
accumulate = (
    self.last_doped_result is not None
    and (self.last_doped_result.doping is None
         or self.last_doped_result.doping.kind == "gaussian_implant")
)
...
doped_result = apply_gaussian_implant_doping(
    process_result, ..., existing=self.last_doped_result if accumulate else None,
)
n_terms = len(doped_result.doping.regions[0].gaussian_terms or [1])
```
After the `if/elif` kind dispatch, EVERY kind converges on:
```python
self.last_doped_result = doped_result
...
self._update_process_buttons()
self.viewer_layer_var.set("doping")
self.redraw()
```

`_on_thermal_anneal_clicked()` (lines ~4220-4294) today:
```python
if self.last_doped_result is None or self.last_doped_result.doping is None:
    self._log("ANNEAL: no doping applied yet -- nothing to anneal.")
    return
...
before = self.last_doped_result
after = apply_thermal_anneal(before, temperature_c, time_s)
if after is before:
    ...  # logged no-op
    return
self.last_doped_result = after
before_terms = _normalize_gaussian_terms(before.doping.regions[0])
after_terms = _normalize_gaussian_terms(after.doping.regions[0])
unverified_species = {...}  # from after.physics_status
for before_term, term in zip(before_terms, after_terms):
    ...  # logs straggle/peak before->after, positionally paired (Stage B final-review Important #1/#2)
self.last_physics_status = after.physics_status
self._update_process_buttons()
```

**CONFIRMED, real finding (user's own final-review condition 1 — resolved here, not deferred): `run_measurement()`'s stale-doping re-attachment double-appends without this fix.** Read directly this session, `run_measurement()` (line ~4501) contains:
```python
if self._doping_is_stale():
    self._log("\nNOTE: the doping profile was attached to an earlier mesh. "
               "Re-applying the same doping to the current geometry before measuring.\n")
    if not self.run_doping(silent=True):
        return
    doped_result = self.last_doped_result
```
Under this task's own design (every `run_doping()` call unconditionally appends to `self.wafer_state.dopant_profiles`), this internal re-attach call WOULD append a SECOND, duplicate copy of the same profile every time a measurement re-attaches stale doping.

**Real resolution, grounded in the new architecture (not a guess): re-attachment does not need to touch `self.wafer_state.dopant_profiles` at all.** `_doping_is_stale()`'s whole reason for existing is that `doped_result.volume_mesh_path` (needed by `import_process_result()`/`derive_barrier_covered_windows()` for MESH READING) no longer matches `self.last_final_mesh`. But `self.wafer_state.dopant_profiles` are `DopantProfile`s with ABSOLUTE-coordinate closures (Task 1/§5) — they are evaluated against WHATEVER geometry `self.wafer_state` currently represents, via geometry-gating (§3), automatically, on every query. The ALREADY-recorded profile does not need to be recreated just because the mesh file changed; it is already being correctly gated against the CURRENT geometry (which the new geometry-sync wiring below keeps `self.wafer_state` in sync with, independent of doping). Re-attachment's real job is only to refresh the LOCAL `doped_result`/`self.last_doped_result` object (for `import_process_result`'s mesh-reading needs), never to add a new entry to the canonical accumulated list.

Fix: add `reattach: bool = False` to `run_doping()`'s signature. The line that appends to `self.wafer_state` becomes:
```python
if not reattach:
    self.wafer_state = advance_wafer_state(self.wafer_state, doped_result, "doping")
```
`run_measurement()`'s own internal call becomes `self.run_doping(silent=True, reattach=True)`.

**CONFIRMED, real finding (user's own final-review condition 2 — resolved here): doping is NOT the only category that must keep `self.wafer_state` in sync.** Grep confirms the real pattern `self.last_final_mesh = result.get("final_mesh")` appears at 8 real sites across this file (lines ~1313, 2350, 2899, 2962, 3024, 3322, 3670, 6146 — covering `run_oxidation`, `run_etch`, `_materialize_current_wafer`, and every other single-step/flow-step runner). If ONLY `run_doping()` ever touches `self.wafer_state`, then after any geometry-changing step (etch, oxidation, deposition, ...) with no doping of its own, `self.wafer_state`'s own `_cells`/`materials` (its geometry) goes STALE — reflecting whatever mesh existed at the time of the LAST doping call, not the wafer's real current geometry — meaning every SUBSEQUENT geometry-gated query (§3) would silently evaluate against the WRONG, outdated geometry.

Fix: add one shared private helper, called at EVERY one of the 8 real sites, immediately after each one's own `self.last_final_mesh = result.get("final_mesh")` line:
```python
def _sync_wafer_state_geometry(self, recipe, result):
    """Keep self.wafer_state's GEOMETRY current after any real process
    step, doping or not -- preserving every already-accumulated
    DopantProfile unchanged (this ProcessResult carries no .doping, so
    advance_wafer_state's this_step_profiles is empty; prior_profiles
    passes through untouched)."""
    final_mesh = result.get("final_mesh")
    if not final_mesh:
        return
    process_result = build_process_result({"final_mesh": final_mesh, "snapshots": []})
    category = recipe.get("_process_category")
    self.wafer_state = advance_wafer_state(self.wafer_state, process_result, category)
```
Call `self._sync_wafer_state_geometry(recipe, result)` at each of the 8 sites (each already has its own `recipe` dict with `"_process_category"` set, and its own `result` dict — confirmed by reading `run_etch()`'s real code, which has exactly this shape). This is the SAME `advance_wafer_state()` Task 5 built, used here for the geometry-only-refresh case rather than the doping-append case.

**Files:**
- Modify: `tcad_2d_stagewise.py` (`run_doping()` — including the new `reattach=` parameter, `_on_thermal_anneal_clicked()`, `run_measurement()` — its internal re-attach call, `run_oxidation()`/`run_etch()`/every other of the 8 real `self.last_final_mesh = result.get("final_mesh")` sites — add the `_sync_wafer_state_geometry()` call, `__init__`/`reset()` — add `self.wafer_state = None` alongside the existing `self.last_doped_result = None` initialization in BOTH places, mirroring that exact pattern)
- Modify: `tests/integration/test_gui_thermal_anneal_real.py` (rewritten against the new mechanism, not `existing=`)
- Test: `tests/integration/test_gui_doping_survives_geometry_steps_real.py` (new — the user's own required condition-2 acceptance case: doping → etch → oxidation → doping preserves both mesh and all accumulated profiles)

**Interfaces:**
- Consumes: `advance_wafer_state()` (Task 5, real signature `advance_wafer_state(prior_state, result, category)` — mesh-file-based, no domain argument), `apply_thermal_anneal()` new signature (Task 3, operates on a profile tuple, not a `ProcessResult`).
- Produces: `self.wafer_state: Optional[WaferState]` — new instance attribute, the GUI's own held accumulating state, kept current by EVERY real process step (not just doping). `self.last_doped_result` is KEPT UNCHANGED (still set identically, for whatever other code — e.g. `run_measurement()`'s mesh-reading needs — depends on it; this task only ADDS `self.wafer_state` alongside it, never removes the older attribute or its existing assignments, and never lets it substitute for `self.wafer_state` as the canonical cross-step doping state).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_gui_thermal_anneal_real.py -- REWRITTEN (existing= no longer exists, Task 4)
def main():
    ...  # same setup as before through app._materialize_current_wafer()
    app.doping_kind.set("Gaussian Implant")
    app.dope_gauss_region_var.set("Si"); app.dope_gauss_axis_var.set("x")
    app.dope_gauss_position_var.set(-1.0); app.dope_gauss_straggle_var.set(0.2)
    app.dope_gauss_acceptor_var.set(1.0e18); app.dope_gauss_acceptor_species_var.set("B")
    assert app.run_doping(silent=True)

    assert app.wafer_state is not None
    assert len(app.wafer_state.dopant_profiles) == 1
    print(f"[1/N] first implant (B) applied via advance_wafer_state: "
          f"{len(app.wafer_state.dopant_profiles)} profile(s)")

    app.dope_gauss_position_var.set(1.0); app.dope_gauss_straggle_var.set(0.15)
    app.dope_gauss_donor_var.set(2.0e18); app.dope_gauss_acceptor_var.set(0.0)
    app.dope_gauss_donor_species_var.set("P"); app.dope_gauss_acceptor_species_var.set("")
    assert app.run_doping(silent=True)
    species = sorted(p.species for p in app.wafer_state.dopant_profiles)
    print(f"[2/N] second implant (P) added: {species}")
    assert species == ["B", "P"], "accumulation must now flow through WaferState, not existing="

    app.anneal_temp_var.set(900.0); app.anneal_time_var.set(600.0)
    app._on_thermal_anneal_clicked()
    b_after = next(p for p in app.wafer_state.dopant_profiles if p.species == "B")
    print(f"B straggle after real GUI anneal: {b_after.model_params['straggle_um']:.4f} um")
    assert b_after.model_params["straggle_um"] > 0.2
    ...
```

(Full rewrite of every remaining assertion in this file follows the same pattern already established in the pre-existing version — read it before rewriting, keep every one of the 5 user-required GUI-observable sensitivities from Stage B's own acceptance criteria, just re-pointed at `app.wafer_state` instead of `app.last_doped_result.doping.regions[0].gaussian_terms`.)

```python
# tests/integration/test_gui_doping_survives_geometry_steps_real.py -- new file
"""User's own final-review condition 2, executable: doping -> etch ->
oxidation -> doping must preserve BOTH the current real mesh AND every
previously-accumulated DopantProfile -- not just whichever doping call
happened last. Real GUI, real ViennaPS throughout."""
import os, sys
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.parent.parent.as_posix())


def main():
    import tcad_2d_stagewise as gui
    app = gui.TCADApplication()
    try:
        app.withdraw(); app.update_idletasks()
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer()
        mesh_after_materialize = app.last_final_mesh

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si"); app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(-3.0); app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_acceptor_var.set(1.0e18); app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)
        print(f"[1/4] B implant: {[p.species for p in app.wafer_state.dopant_profiles]}")
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"]

        # Real etch -- geometry changes, NO doping of its own.
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        app.etch_model.set("Isotropic etch")
        app.isotropic_rate_var.set(0.02); app.etch_time_var.set(2.0)
        app.run_etch()
        mesh_after_etch = app.last_final_mesh
        print(f"[2/4] after real etch: mesh changed={mesh_after_etch != mesh_after_materialize}, "
              f"species still present={[p.species for p in app.wafer_state.dopant_profiles]}")
        assert mesh_after_etch != mesh_after_materialize, "the etch must genuinely produce a new mesh"
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"], (
            "a geometry-only etch (no doping of its own) must NOT drop the existing B profile"
        )

        # Real oxidation -- ANOTHER geometry change, still no doping.
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.ox_temp_var.set(900.0); app.ox_time_var.set(0.01)
        app.run_oxidation()
        mesh_after_oxidation = app.last_final_mesh
        print(f"[3/4] after real oxidation: mesh changed={mesh_after_oxidation != mesh_after_etch}, "
              f"species still present={[p.species for p in app.wafer_state.dopant_profiles]}")
        assert mesh_after_oxidation != mesh_after_etch
        assert [p.species for p in app.wafer_state.dopant_profiles] == ["B"], (
            "a second geometry-only step must ALSO preserve the existing B profile"
        )

        # Second doping call -- must ADD to, not replace, what survived.
        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.dope_gauss_position_var.set(3.0); app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(2.0e18); app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P"); app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species = sorted(p.species for p in app.wafer_state.dopant_profiles)
        print(f"[4/4] after second doping (P) post-etch-post-oxidation: species={species}")
        assert species == ["B", "P"], (
            "doping -> etch -> oxidation -> doping must end with BOTH B and P present -- "
            "geometry-only steps in between must never silently drop an accumulated profile"
        )

        # Condition 1's own acceptance check: a silent re-attach (the
        # exact path run_measurement() takes when _doping_is_stale())
        # must NOT duplicate the just-added P profile.
        count_before_reattach = len(app.wafer_state.dopant_profiles)
        assert app.run_doping(silent=True, reattach=True)
        count_after_reattach = len(app.wafer_state.dopant_profiles)
        print(f"reattach=True: profile count {count_before_reattach} -> {count_after_reattach} "
              f"(must be unchanged, never duplicated)")
        assert count_after_reattach == count_before_reattach, (
            "a silent re-attach (run_measurement()'s own real code path) must never "
            "append a duplicate copy of the profile it is only refreshing"
        )

        print("Condition 2 confirmed: WaferState's geometry stays current through etch AND "
              "oxidation (neither of which carries its own doping), while every previously-"
              "accumulated DopantProfile survives both, and a later doping call correctly adds "
              "to that surviving state rather than replacing it.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_thermal_anneal_real.py tests/integration/test_gui_doping_survives_geometry_steps_real.py`
Expected: FAIL — `app.wafer_state` does not exist yet; `run_doping()` has no `reattach=` parameter; the 8 geometry-producing methods have no `_sync_wafer_state_geometry()` call yet.

- [ ] **Step 3: Implement**

In `run_doping()`: add `reattach: bool = False` to the signature. Right after the real, existing `self.last_doped_result = doped_result` line (kept as-is), ADD:
```python
if not reattach:
    self.wafer_state = advance_wafer_state(self.wafer_state, doped_result, "doping")
```
(`doped_result` already carries `volume_mesh_path` inherited from `process_result` — Task 5's `advance_wafer_state`/`WaferState.from_process_result` need nothing else. Category is `"doping"`, per the corrected classification: a doping call never changes geometry, so it can never be the thing that causes a profile's `host_material` to disappear. The `reattach` guard is this task's resolution to condition 1, described in full above — `run_measurement()`'s own re-attach call must pass `reattach=True`.)

Implement `_sync_wafer_state_geometry(self, recipe, result)` exactly as specified above, and call it at EVERY one of the 8 real `self.last_final_mesh = result.get("final_mesh")` sites (this task's resolution to condition 2) — immediately after each site's own mesh assignment, passing that SAME method's own `recipe`/`result` locals.

Delete the ENTIRE `accumulate`/`existing=`/`n_terms = len(doped_result.doping.regions[0].gaussian_terms or [1])` block from the `"Gaussian Implant"` branch (Task 4 already removed the underlying mechanism; this is where the GUI's own now-dead reference to it is cleaned up) — replace the `summary` string's `n_terms` reference with `len(self.wafer_state.dopant_profiles)` (the real, new accumulation count) instead.

In `_on_thermal_anneal_clicked()`, replace the body from `before = self.last_doped_result` onward:
```python
if self.wafer_state is None or not self.wafer_state.dopant_profiles:
    self._log("ANNEAL: no doping applied yet -- nothing to anneal.")
    return

before_profiles = self.wafer_state.dopant_profiles
updated_profiles, physics_status = apply_thermal_anneal(
    before_profiles, temperature_c, time_s,
)
self.wafer_state = dataclasses.replace(self.wafer_state, dopant_profiles=updated_profiles)

# Positional pairing (same principle as the Stage B final-review
# Important #1/#2 fix, now at the WaferState.dopant_profiles level
# instead of DopingRegion.gaussian_terms -- apply_thermal_anneal
# (Task 3) preserves order, never reorders/drops, so zip is correct).
unsupported_species = {
    entry["material"] for entry in (physics_status or {}).get("entries", [])
    if entry["resolution"] == "UNSUPPORTED_BY_MODEL"
}
self._log(
    f"\n================================\n"
    f"ANNEAL: {temperature_c:.0f} C / {time_s:.0f} s\n"
    f"================================\n"
    f"Applied to {len(updated_profiles)} existing profile(s):"
)
for before_p, after_p in zip(before_profiles, updated_profiles):
    flag = (
        " (UNSUPPORTED_BY_MODEL -- no anneal handler registered, or out of citation range)"
        if before_p.species in unsupported_species else ""
    )
    before_straggle = before_p.model_params.get("straggle_um")
    after_straggle = after_p.model_params.get("straggle_um")
    if before_straggle is not None and after_straggle is not None:
        self._log(
            f"  {before_p.species or '(unlabeled)'} ({before_p.polarity}): "
            f"straggle {before_straggle:.4f} -> {after_straggle:.4f} um{flag}"
        )
    else:
        self._log(
            f"  {before_p.species or '(unlabeled)'} ({before_p.polarity}): "
            f"no defined shape to anneal{flag}"
        )

self.last_physics_status = physics_status
self._update_process_buttons()
```
(The old `if after is before: ... return` no-op check is removed — `apply_thermal_anneal` (Task 3) always returns a NEW tuple, even when every profile is `UNSUPPORTED_BY_MODEL`, so there is no longer a single object-identity check that means "nothing happened"; the per-profile log loop above already reports each profile's real outcome individually, which is a more precise disclosure than the old all-or-nothing check gave.)

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_thermal_anneal_real.py tests/integration/test_gui_doping_survives_geometry_steps_real.py`
Expected: PASS, real GUI, real ViennaPS — the first file demonstrates all 5 required sensitivities with real numbers; the second (conditions 1+2) confirms geometry-only steps (etch, oxidation) never drop an accumulated profile, AND confirms `reattach=True` never duplicates the canonical profile list.

- [ ] **Step 5: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_thermal_anneal_real.py tests/integration/test_gui_doping_survives_geometry_steps_real.py
git commit -m "feat: GUI doping/anneal wired through advance_wafer_state()/dispatch-based apply_thermal_anneal, not existing= -- every geometry step keeps WaferState current, reattach never double-appends"
```

---

### Task 10: GUI P/N color overlay rewrite — reads real `WaferState`, distinguishes `UNSUPPORTED_BY_MODEL`

**Files:**
- Modify: `tcad_2d_stagewise.py` (`_doping_color_segments`)
- Test: `tests/integration/test_gui_doping_color_overlay_real.py` (new — this session confirmed the OLD version is live-verified WRONG; this test is the regression pin for the fix)

**Interfaces:**
- Consumes: `app.wafer_state` (Task 9), `WaferState.net_doping_at()` (Task 2).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_gui_doping_color_overlay_real.py
"""Confirmed bug this session: the OLD _doping_color_segments read
region.peak_conc_cm3 (a legacy single-value field reflecting only the
MOST RECENT implant call), painting an entire multi-term region ONE
flat wrong color. This test proves the FIX with a per-bucket
cross-check -- not just 'at least two colors appear' -- confirming
EVERY real bucket's rendered color matches the SIGN of
WaferState.net_doping_at() at that exact bucket's own center, and that
an UNSUPPORTED_BY_MODEL bucket renders as a visibly distinct marker,
never blended into the normal blue/red rendering (spec Sec6)."""
N_COLOR, P_COLOR, UNSUPPORTED_MARKER = "#2f6fed", "#e0393e", "#unsupported"


def main():
    ...  # same B-then-P setup as Task 9's test
    segments = app._doping_color_segments("Si", x_min_um=-5.0, x_max_um=5.0)
    print(f"{len(segments)} real segments returned")

    mismatches = []
    unsupported_seen = supported_seen = 0
    for x_lo, x_hi, color in segments:
        bucket_center = (x_lo + x_hi) / 2.0
        result = app.wafer_state.net_doping_at(bucket_center, 0.0)
        if result.physics_status is not None:
            unsupported_seen += 1
            if color != UNSUPPORTED_MARKER:
                mismatches.append(
                    f"bucket@{bucket_center:.2f}um: physics_status shows a gap but "
                    f"rendered color={color!r} (expected {UNSUPPORTED_MARKER!r})"
                )
            continue
        supported_seen += 1
        expected = N_COLOR if result.net_doping >= 0 else P_COLOR
        if color != expected:
            mismatches.append(
                f"bucket@{bucket_center:.2f}um: net_doping={result.net_doping:.3e} "
                f"(sign expects {expected!r}) but rendered color={color!r}"
            )

    print(f"buckets checked: {len(segments)} (supported={supported_seen}, unsupported={unsupported_seen})")
    for m in mismatches:
        print(f"  MISMATCH: {m}")
    assert not mismatches, f"{len(mismatches)} bucket(s) rendered a color that disagrees with the real computed sign/status"

    colors = {c for _, _, c in segments if c != UNSUPPORTED_MARKER}
    assert len(colors) >= 2, "B(acceptor) and P(donor) regions must render as genuinely different colors"
    print(f"distinct real colors rendered: {colors}; every bucket's color matches its real "
          f"WaferState.net_doping_at() sign/status, none inferred or assumed.")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_doping_color_overlay_real.py`
Expected: FAIL against the OLD implementation (one flat color, confirmed this session) — or an AttributeError if `_doping_color_segments`'s signature hasn't been updated yet.

- [ ] **Step 3: Implement**

Rewrite `_doping_color_segments(self, region_name, x_min_um, x_max_um, n_buckets=60)` to bucket `[x_min_um, x_max_um]` into `n_buckets` real intervals, call `self.wafer_state.net_doping_at(bucket_center_x, 0.0)` per bucket (0.0 depth is this model's own x-only scope, unchanged from Stage B), and pick the segment color from the REAL sign of `result.net_doping` when `result.physics_status is None`, or a visibly distinct marker (e.g. `"#unsupported"` mapped to a hatched/gray fill in the caller, or whatever this project's existing Tk stipple convention supports) when `result.physics_status is not None` — never blending an unsupported bucket into the normal blue/red rendering (spec §6's explicit GUI requirement).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_doping_color_overlay_real.py`
Expected: PASS, with real, distinct colors for B and P's regions (and, if the test extends to exercise CE-2's scenario, a visibly distinct rendering for the unsupported bucket).

- [ ] **Step 5: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_doping_color_overlay_real.py
git commit -m "fix: GUI P/N overlay reads real per-bucket WaferState.net_doping_at(), fixes confirmed one-flat-color bug"
```

---

### Task 11: Full integration acceptance — CE-3 `implant → anneal → etch → second implant`, real end-to-end, through the actual GUI

**Critical scope correction, same as Tasks 6/7: no depth-dependent physics claim anywhere in this test.** This test does NOT claim "B's shallow depth was physically removed by the etch" or "P was implanted at a new surface depth" — both are UNSUPPORTED, depth-based claims this x-only model cannot make. What this test DOES claim, all real and model-honest: (1) B is implanted and really widened by a real anneal dispatch (Task 3); (2) a real ViennaPS etch genuinely changes geometry at a KNOWN, mesh-verified x-range (reusing Task 6's now-established "verify Si is genuinely gone, not just recessed" pattern) while B survives at its OWN, untouched x-position; (3) P is implanted afterward, independently; (4) both profiles coexist in `WaferState.dopant_profiles`; (5) a real per-node DevSim `NetDoping` cross-check (Task 8's mechanism) confirms the final device reflects both, at several real nodes, not just a min/max sign check.

**Classification, explicit (same as Task 8, user's own final review, point 3): the per-node DevSim comparison in this test is a WaferState↔DevSim coupling/numerical-consistency check, not an independent physical-correctness re-validation** — it confirms the same real production wiring Task 8 built transports numbers correctly through this specific end-to-end GUI scenario, not that the Gaussian formula itself is newly proven physically correct here (already done, separately, by Task 1).

**Etch success is judged from real mesh material data, never a GUI boolean (user's own final review, point 4).** This test never calls `app.run_etch()` at all (see the hybrid approach below) and never reads any success flag as its primary signal — `after_etch != "Si"` / `after_b_site == "Si"`, both read directly from the real exported mesh via `_material_at()`, are the ONLY signals this test trusts for whether the etch did what it claims. `app.wafer.etched = True` is set afterward purely so the GUI's OWN internal state stays consistent for any later code that reads it — it is never itself an assertion target.

**Real production facts this task's own code was checked against before writing (do not re-derive):** `app.run_etch()` (line ~5872) has **NO return value on success** (falls through, implicit `None` — unlike `run_doping(silent=)`, which explicitly returns `True`/`False`) — success is signaled by real side effects: `self.wafer.etched` becomes `True` and `self.last_final_mesh` is updated (confirmed at line ~6134/6146). `run_etch()` reads `self.etch_model.get()` (a label, e.g. `"Isotropic etch"` -> internally mapped to model key `"isotropic"`), `self.etch_time_var.get()`, `self.isotropic_rate_var.get()` (magnitude only — the real code applies `-abs(...)` itself), and mask config via `self._mask_recipe_keys_for_current_step()` (litho-driven; a fresh/undeveloped wafer's own default there is a blanket, unmasked etch).

**Deliberate hybrid approach, disclosed, not a placeholder:** getting a PRECISELY-targeted etch (a specific, mesh-verified x-range, matching Task 6's established real-removal pattern) through the full litho-panel GUI flow is a larger, separate concern than this test's own core claim (accumulation + anneal dispatch + real per-node DevSim cross-check, exercised through the real GUI). This test therefore uses the REAL GUI for doping/anneal (`app.run_doping`, `app._on_thermal_anneal_clicked` — Task 9's own real wiring) and a DIRECT, precisely-configured registry call (same technique already validated in Task 6) for the etch step specifically, then manually threads the etch's real result back into `app.last_final_mesh`/`app.wafer.etched`/`app.last_domain_state` (the same fields `run_etch()` itself would set) so the SUBSEQUENT `app.run_doping()` call for P correctly picks up the real post-etch mesh — this is a deliberate simplification of ONE step's own path, not a placeholder standing in for missing logic, and is stated here explicitly rather than silently.

**Files:**
- Test: `tests/integration/test_ce3_implant_anneal_etch_implant_real.py` (new — the user's own explicitly required integration case)

**Interfaces:**
- Consumes: everything from Tasks 1-10, exercised through the real production GUI's doping/anneal handlers (`test_gui_thermal_anneal_real.py`'s own established pattern: real `TCADApplication`, window withdrawn).

- [ ] **Step 1: Write the real, full-chain test**

```python
# tests/integration/test_ce3_implant_anneal_etch_implant_real.py
"""Spec CE-3, the explicitly required final integration case, x-only
(no depth-dependent claim anywhere): implant -> anneal -> etch ->
second implant, through the REAL production GUI doping/anneal handlers,
ending in a real per-node DevSim NetDoping (Task 8) cross-check that
correctly reflects BOTH profiles -- neither via a legacy shortcut."""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

X_B, X_ETCH, X_P = -3.5, 0.0, 3.5   # B survives untouched; the etch clears X_ETCH; P lands elsewhere


def main():
    import tkinter, tcad_2d_stagewise as gui
    from tcad.process import registry
    from tcad.mesh.viennaps_adapter import build_process_result

    app = gui.TCADApplication()
    try:
        app.withdraw(); app.update_idletasks()
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer()

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si"); app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(X_B); app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_acceptor_var.set(1.0e18); app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)
        print(f"[1/5] profile_1 (B) created at x={X_B}: "
              f"{len(app.wafer_state.dopant_profiles)} profile(s)")

        app.anneal_temp_var.set(950.0); app.anneal_time_var.set(300.0)
        app._on_thermal_anneal_clicked()
        b_widened = next(p for p in app.wafer_state.dopant_profiles if p.species == "B")
        print(f"[2/5] profile_1 (B) annealed: straggle -> {b_widened.model_params['straggle_um']:.4f} um")
        assert b_widened.model_params["straggle_um"] > 0.3

        # Real, precisely-configured etch (direct registry call, same
        # technique Task 6 already validated) -- verified via real mesh
        # probe, not assumed, then threaded back into the GUI's own
        # real continuity fields exactly as run_etch() itself would set
        # them (see this task's own header note on why this is a
        # disclosed hybrid, not a placeholder).
        import meshio, numpy as np
        prior_mesh = app.last_final_mesh
        etch_step = registry.get("etching", "isotropic")(inherited_domain=app.last_domain_state)
        etch_recipe = {
            "_process_category": "etching", "_process_model_key": "isotropic",
            "rate": -0.02, "etch_time_s": 600.0,
            "silicon_depth_um": app.wafer.silicon_depth_um, "grid_delta_um": float(app.grid_var.get()),
            "x_extent_um": app.wafer.width_um, "y_extent_um": 8.0,
            "mask_spans_um": [[-1.5, 1.5]],  # opens ONLY around X_ETCH -- verify below, not assumed
        }
        etch_result = etch_step.run(etch_recipe, tempfile.mkdtemp(prefix="ce3_etch_"))

        def _material_at(mesh_path, x_um, tol=0.15):
            import viennaps as vps
            mesh = meshio.read(mesh_path)
            names = {int(v): a for a in dir(vps.Material) if not a.startswith("_")
                     for v in [getattr(vps.Material, a)] if isinstance(v, vps.Material)}
            best = None
            for key, blocks in mesh.cell_data.items():
                if "material" not in key.lower():
                    continue
                for cells, values in zip(mesh.cells, blocks):
                    for cell, tag in zip(cells.data, np.asarray(values).ravel()):
                        corners = mesh.points[cell]
                        if abs(corners[:, 0].mean() - x_um) >= tol:
                            continue
                        name = names.get(int(tag), f"?{int(tag)}")
                        if best is None:
                            best = name
            return best

        before_etch = _material_at(prior_mesh, X_ETCH)
        after_etch = _material_at(etch_result["final_mesh"], X_ETCH)
        before_b_site = _material_at(prior_mesh, X_B)
        after_b_site = _material_at(etch_result["final_mesh"], X_B)
        print(f"[3/5] real etch: X_ETCH={X_ETCH} {before_etch}->{after_etch}, "
              f"X_B={X_B} (must stay Si) {before_b_site}->{after_b_site}")
        assert after_etch != "Si", "the etch must genuinely remove Si at X_ETCH, not merely recess it"
        assert after_b_site == "Si", "B's own x-position must be untouched by this etch"

        app.last_final_mesh = etch_result["final_mesh"]
        app.last_domain_state = etch_result.get("domain_state")
        app.wafer.etched = True
        app.wafer.processed = True
        app.wafer_state = advance_wafer_state = __import__(
            "tcad.physics.wafer_state_accumulation", fromlist=["advance_wafer_state"]
        ).advance_wafer_state(
            app.wafer_state,
            build_process_result({"final_mesh": etch_result["final_mesh"], "snapshots": []}),
            "etching",
        )

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.dope_gauss_position_var.set(X_P); app.dope_gauss_straggle_var.set(0.3)
        app.dope_gauss_donor_var.set(2.0e18); app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P"); app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species = sorted(p.species for p in app.wafer_state.dopant_profiles)
        print(f"[4/5] profile_2 (P) created post-etch at x={X_P}: species now {species}")
        assert species == ["B", "P"], "both profiles must independently coexist in WaferState"

        # Real per-node DevSim conversion (Task 8), through a real device.
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.device.devsim.doping_mapping import apply_doping
        import devsim
        final_result = build_process_result({"final_mesh": app.last_final_mesh, "snapshots": []})
        device_name, region_name = import_process_result(final_result, device_name="ce3_dev")
        length_scale_to_cm = 1.0  # matches import_process_result's own real default (Task 8)
        try:
            physics_status = apply_doping(
                device_name, region_name, app.wafer_state, length_scale_to_cm=length_scale_to_cm,
            )
            xs_native = devsim.get_node_model_values(device=device_name, region=region_name, name="x")
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"[5/5] checked {len(xs_native)} real DevSim nodes, "
                  f"NetDoping range: [{min(net):.3e}, {max(net):.3e}], physics_status={physics_status}")
            assert max(net) > 0 and min(net) < 0, "both B(acceptor) and P(donor) contributions must be real"

            mismatches = 0
            for i in range(0, len(xs_native), max(1, len(xs_native) // 15)):
                x_um = xs_native[i] / length_scale_to_cm
                expected = app.wafer_state.net_doping_at(x_um, 0.0).net_doping
                if abs(expected - net[i]) > 1e-6 * max(abs(expected), 1.0):
                    mismatches += 1
                    print(f"  MISMATCH node[{i}] x={x_um:.3f}um: expected={expected:.6e}, DevSim={net[i]:.6e}")
            assert mismatches == 0, f"{mismatches} real node(s) disagreed between WaferState and DevSim"
            print("Real per-node cross-check: WaferState.net_doping_at() and DevSim's own "
                  "stored NetDoping agree at every checked node.")
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=device_name)

        print("CE-3 confirmed end-to-end through the real production GUI doping/anneal "
              "handlers plus a real, mesh-verified etch: B survives (annealed) at its own "
              "untouched position, the etched region is genuinely cleared, P is added "
              "afterward independently, and a real per-node DevSim NetDoping reflects both "
              "-- x-only throughout, no depth-dependent claim made anywhere.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce3_implant_anneal_etch_implant_real.py`
Expected: real failures here are genuine integration gaps between Tasks 1-10 (e.g. a real API name mismatch between what Task 9 wired and what this test assumes, or the `mask_spans_um`/`X_ETCH` alignment needing real tuning, same as Task 6/7's own established pattern) — debug against the real, already-committed Task 1-10 code and real mesh probes, never by weakening this test's assertions (in particular: never delete the `after_etch != "Si"`/`after_b_site == "Si"` checks to "make it pass").

- [ ] **Step 3: N/A (test-only; if a real gap is found, fix it in the OWNING task's file, not here — record which task's code changed in this task's own report)**

- [ ] **Step 4: Confirm pass with all 5 real printed milestones and zero real per-node mismatches.**

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce3_implant_anneal_etch_implant_real.py
git commit -m "test: CE-3 full integration, real GUI end-to-end -- implant -> anneal -> etch -> second implant -> real per-node NetDoping, x-only, no depth claim"
```

---

## Plan completion criteria

- Full regression (`tests/run_regression.py`) passes with the SAME 3 pre-existing DevSim-convergence failures as every prior run this session, zero new failures.
- Every one of the 10 items from the user's own plan-review checklist has a task that addresses it:
  1. real physics per task → Tasks 1, 3, 6, 7 (real formulas/dispatch, not just structures)
  2. `WaferState.dopant_profiles` wired in production → Task 5
  3. `ProcessResult.doping` old accumulation path actually removed → Task 4
  4. `set_node_values()` real DevSim wiring → Task 8
  5. GUI stops reusing legacy `_doping_color_segments` → Task 10
  6. no path converts `UNSUPPORTED_BY_MODEL` to 0 → Tasks 2, 7 (tested explicitly)
  7. CE-1/CE-2 as real executable acceptance tests → Tasks 6, 7
  8. CE-3 in the final integration test → Task 11
  9. Gaussian model never silently generalized → Task 3's `ANNEAL_HANDLERS` registry keeps `"gaussian_v1"` explicit and singular; no task in this plan adds a second model
  10. no new GUI parameter without a real model → no task in this plan adds one (explicitly, e.g. no "implant energy" field appears anywhere above)
- No task's acceptance criteria reads "architecture wired successfully" alone — every task's Step 4 names a real printed number or real DevSim/GUI observation.
- The user's own final-approval conditions (all resolved, not deferred, before Task 9 implementation begins):
  1. `run_measurement()`'s stale-doping re-attachment never double-appends — resolved via `run_doping(reattach=True)` skipping the accumulation call entirely (Task 9), grounded in the real architectural fact that geometry-gating already keeps an existing profile correctly evaluated against current geometry without needing to be recreated.
  2. Every geometry-mutating process (not just doping) keeps `self.wafer_state` current — resolved via `_sync_wafer_state_geometry()` called at all 8 real `self.last_final_mesh = ...` sites (Task 9), with a real GUI acceptance test proving doping → etch → oxidation → doping preserves both mesh and every accumulated profile.
  3. `UNSUPPORTED_BY_MODEL` is never conflated with a real zero — enforced by the three-way test itself (§3/Task 2) and directly asserted in CE-2 (Task 7) and CE-3 (Task 11).
- Real, disclosed (not silently dropped) feature-parity gap for the implementer to resolve during Task 8: the OLD `apply_doping()`'s `exclude_windows`/`exclude_axis` (SiO2 barrier exclusion) has no equivalent in the new signature yet — investigate and resolve before considering Task 8 done, per that task's own expanded brief.
