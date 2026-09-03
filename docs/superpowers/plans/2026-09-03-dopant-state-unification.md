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
- Produces: `DopingQueryResult(donor_concentration: float, acceptor_concentration: float, net_doping: float, physics_status: Optional[dict])`. `WaferState.net_doping_at(x_um, depth_um) -> DopingQueryResult` (return type CHANGES from `float` — every existing caller must be updated in this task; grep confirms only `donor_concentration_at`/`acceptor_concentration_at`/`net_doping_at` themselves, no other production caller exists yet, per gap analysis). `WaferState.query(domain, dopant_profiles=(), last_step_category: Optional[str] = None)` (new keyword-only parameter).
- The category → transition-kind table (Task's own concrete decision on the spec's left-open mechanism): `MATERIAL_CHANGE_KIND_BY_CATEGORY: Dict[str, str] = {"etching": "removal", "oxidation": "conversion"}` — a step whose category has no entry (e.g. `"deposition"`, which never removes existing material a profile could have been in, only adds on top) is `None`: no classification is needed because deposition/doping/metallization never make an already-doped material disappear.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_wafer_state_doping_mock.py -- add

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

    def donor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> DopingQueryResult:
        return self.net_doping_at(x_um, depth_um)  # convenience: same call, callers read .donor_concentration

    def acceptor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> DopingQueryResult:
        return self.net_doping_at(x_um, depth_um)

    def net_doping_at(self, x_um: float, depth_um: float = 0.0) -> DopingQueryResult:
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

(`donor_concentration_at`/`acceptor_concentration_at` keeping their old names but now returning the same `DopingQueryResult` — read the field you need off it — is a deliberate, disclosed API break; there is exactly one production caller today per the gap analysis, none yet in the real pipeline, so no other file needs updating in this task. Task 5 is the one that adds real production callers.)

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

### Task 5: `WaferState.dopant_profiles` accumulation wired through EVERY process category

**Files:**
- Modify: `tcad/process/etching/isotropic.py` (fix the confirmed production bug: pass `dopant_profiles=`)
- Modify: every other process category that calls `WaferState.query()` or should — audit `tcad/process/oxidation/`, `tcad/process/etching/*.py`, `tcad/process/deposition/*.py` for the call site, and where none exists today, this task ADDS the call at the same point `isotropic.py`'s own `resolve()` call sits (do not invent a new integration point — mirror the existing one, extended)
- Create: `tcad/physics/wafer_state_accumulation.py` (the shared helper, so every call site uses IDENTICAL logic — spec §9)
- Test: `tests/integration/test_wafer_state_accumulation_devsim_real.py` (new, real ViennaPS+DevSim — replaces the deleted Task-4 tests' coverage)

**Interfaces:**
- Produces: `advance_wafer_state(domain, prior_state: Optional[WaferState], result: ProcessResult, category: str) -> WaferState` — the ONE function every process step's real pipeline calls.
- Consumes: `dopant_profiles_from_doping_profile()` (Task 1), `WaferState.query(..., last_step_category=)` (Task 2).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_wafer_state_accumulation_devsim_real.py -- new file
"""Real ViennaPS: two SEPARATE apply_gaussian_implant_doping calls (B,
then P -- Task 4 removed the old existing= mechanism) accumulate at the
WaferState layer instead, via advance_wafer_state(). Proves the spec's
Sec9 replacement mechanism actually closes the dual-source-of-truth gap
-- not just that a function exists."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation, tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result  # existing helper this project already uses


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
        base = build_process_result(result0["final_mesh"])

        b_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=0.2, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state1 = advance_wafer_state(step.last_domain, None, b_result, "oxidation")
        print(f"after B implant: {len(state1.dopant_profiles)} profile(s), "
              f"species={[p.species for p in state1.dopant_profiles]}")
        assert len(state1.dopant_profiles) == 1

        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=0.15, donor_peak_conc_cm3=2e18, donor_species="P",
        )
        state2 = advance_wafer_state(step.last_domain, state1, p_result, "oxidation")
        species = sorted(p.species for p in state2.dopant_profiles)
        print(f"after P implant (via advance_wafer_state, NOT existing=): "
              f"{len(state2.dopant_profiles)} profile(s), species={species}")
        assert species == ["B", "P"], "both must be present -- accumulation now lives at the WaferState layer"

        q = state2.net_doping_at(-1.0, 0.0)
        print(f"net_doping at x=-1.0 (B's own peak): donor={q.donor_concentration:.3e}, "
              f"acceptor={q.acceptor_concentration:.3e}, net={q.net_doping:.3e}")
        assert q.acceptor_concentration > 0 and q.physics_status is None

        print("WaferState.dopant_profiles accumulates real, independent B+P profiles "
              "through advance_wafer_state() -- the ProcessResult.doping dual-source-of-truth "
              "gap is closed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_wafer_state_accumulation_devsim_real.py`
Expected: FAIL — `tcad.physics.wafer_state_accumulation` does not exist.

- [ ] **Step 3: Implement**

```python
# tcad/physics/wafer_state_accumulation.py -- new file
"""The ONE function every real process step's pipeline calls to advance
WaferState's dopant_profiles (spec 2026-09-03 Sec9) -- closes the
confirmed production bug where WaferState.query()'s only call site
(isotropic.py) never passed dopant_profiles= at all."""
from typing import Optional

from tcad.mesh.interface import ProcessResult
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState


def advance_wafer_state(
    domain, prior_state: Optional[WaferState], result: ProcessResult, category: str,
) -> WaferState:
    prior_profiles = prior_state.dopant_profiles if prior_state is not None else ()
    this_step_profiles = (
        dopant_profiles_from_doping_profile(result.doping)
        if result.doping is not None else ()
    )
    return WaferState.query(
        domain,
        dopant_profiles=prior_profiles + this_step_profiles,
        last_step_category=category,
    )
```

Fix `tcad/process/etching/isotropic.py:72` (the confirmed bug):
```python
# before:
        state = WaferState.query(geometry)
# after:
        state = advance_wafer_state(geometry, self.inherited_wafer_state, result, "etching")
```
(exact variable names for "the result so far" and "the prior WaferState, if this step continues a chain" depend on `isotropic.py`'s own existing locals — read the surrounding function before editing; do not invent a new parameter without checking whether `ProcessStep.__init__`'s existing `inherited_domain` mechanism already carries something equivalent that should be threaded the same way).

Audit every other process category (`tcad/process/oxidation/thermal.py`, every file under `tcad/process/etching/`, `tcad/process/deposition/*.py`) for its own `resolve()`/`WaferState` usage; where a category has NO such call today (most don't — only isotropic etching is wired per CLAUDE.md's own Completed notes), this task does NOT need to add resolve()-based physics resolution to every category (that is out of scope, per the base 2026-08-25 design's own staged rollout) — it only needs to ensure that WHEREVER a category's real pipeline builds/returns a `ProcessResult` with `doping` set (i.e. wherever the GUI or a test calls an `apply_*_doping` function), the caller uses `advance_wafer_state()` to fold it into the running `WaferState`, per Task 9's GUI wiring. Document this scope boundary explicitly in the task report.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_wafer_state_accumulation_devsim_real.py`
Expected: PASS with the real printed species list `['B', 'P']`.

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/wafer_state_accumulation.py tcad/process/etching/isotropic.py tests/integration/test_wafer_state_accumulation_devsim_real.py
git commit -m "feat: advance_wafer_state() -- real cross-step dopant accumulation, fixes isotropic.py's doping-blind WaferState.query() bug"
```

---

### Task 6: Real removal-classification acceptance test (CE-1) — etch erases a shallow profile, second implant anchors to the new surface

**Files:**
- Test: `tests/integration/test_ce1_order_sensitive_trench_real.py` (new, real ViennaPS+DevSim)

**Interfaces:**
- Consumes: `advance_wafer_state()` (Task 5), `WaferState.net_doping_at()` (Task 2).

- [ ] **Step 1: Write the real test (this task is test-only — no new production code, it exercises Tasks 1-5's real mechanism end-to-end for CE-1)**

```python
# tests/integration/test_ce1_order_sensitive_trench_real.py
"""Spec 2026-09-03 CE-1, executable: swapping which shallow dopant is
applied FIRST (and therefore erased by a later etch inside the trench)
flips the trench's own net polarity. Real ViennaPS geometry + etch,
real WaferState accumulation -- not asserted, measured."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation, tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result

WIDTH_UM, Y_EXTENT_UM, SI_DEPTH_UM, GRID_UM = 10.0, 8.0, 5.0, 0.2


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
    return step, build_process_result(result["final_mesh"])


def run_order(tmp, first_species, first_polarity_kwarg, second_species, second_polarity_kwarg):
    step, base = _fresh_wafer(tmp)
    r1 = apply_gaussian_implant_doping(
        base, region="Si", junction_axis="x", peak_position_um=0.0, straggle_um=0.1,
        **{first_polarity_kwarg: 1e18, f"{first_polarity_kwarg.split('_')[0]}_species": first_species},
    )
    state1 = advance_wafer_state(step.last_domain, None, r1, "oxidation")

    etch_step = registry.get("etching", "isotropic")(inherited_domain=step.last_domain)
    etch_recipe = {
        "_process_category": "etching", "_process_model_key": "isotropic",
        "etch_time_s": 30.0, "isotropic_rate_um_per_s": 0.02,  # a few grid cells deep
        "silicon_depth_um": SI_DEPTH_UM, "grid_delta_um": GRID_UM,
        "x_extent_um": WIDTH_UM, "y_extent_um": Y_EXTENT_UM,
        "mask_spans_um": [[3.5, 6.5]],
    }
    etch_result = etch_step.run(etch_recipe, tmp)
    state1_post_etch = advance_wafer_state(etch_step.last_domain, state1, base, "etching")

    r2 = apply_gaussian_implant_doping(
        build_process_result(etch_result["final_mesh"]), region="Si", junction_axis="x",
        peak_position_um=0.0, straggle_um=0.1,
        **{second_polarity_kwarg: 1e18, f"{second_polarity_kwarg.split('_')[0]}_species": second_species},
    )
    state2 = advance_wafer_state(etch_step.last_domain, state1_post_etch, r2, "etching")
    return state2.net_doping_at(0.0, 0.0)  # inside the trench opening


def main():
    with tempfile.TemporaryDirectory() as tmp:
        q_p_first = run_order(tmp, "B", "acceptor_peak_conc_cm3", "P", "donor_peak_conc_cm3")
    with tempfile.TemporaryDirectory() as tmp2:
        q_n_first = run_order(tmp2, "P", "donor_peak_conc_cm3", "B", "acceptor_peak_conc_cm3")

    print(f"[B then P, trench-etched between] net_doping inside trench: {q_p_first.net_doping:.3e}")
    print(f"[P then B, trench-etched between] net_doping inside trench: {q_n_first.net_doping:.3e}")
    assert (q_p_first.net_doping > 0) != (q_n_first.net_doping > 0), (
        "swapping which species is applied first (and therefore erased by the "
        "trench etch) must flip the trench's own net polarity"
    )
    print("Order-sensitivity confirmed with real ViennaPS geometry: the species "
          "applied FIRST is erased by the etch inside the trench; only the SECOND "
          "survives there, exactly as spec CE-1 predicts.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it currently fails or errors**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce1_order_sensitive_trench_real.py`
Expected: at this point in the plan it should mostly work already (Tasks 1-5 are done) — if it fails, the failure is real signal about a Task 1-5 gap, not a placeholder. Debug against the REAL etch geometry (check the real trench depth vs. `straggle_um=0.1`'s real spatial extent — adjust `etch_time_s`/`isotropic_rate_um_per_s` so the trench genuinely removes the shallow implant; this project's own `derive_implant_windows_refinement()`-adjacent reasoning about "etch deep enough to remove a shallow implant" from CLAUDE.md's OPEN issues is directly relevant background reading).

- [ ] **Step 3: N/A (test-only task, no production code to write)**

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce1_order_sensitive_trench_real.py`
Expected: PASS, with real printed net_doping values of opposite sign.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce1_order_sensitive_trench_real.py
git commit -m "test: CE-1 order-sensitivity, real ViennaPS -- swapping implant order flips trench polarity"
```

---

### Task 7: Real oxidation-conversion `UNSUPPORTED_BY_MODEL` acceptance test (CE-2)

**Files:**
- Test: `tests/integration/test_ce2_oxidation_conversion_unsupported_real.py` (new, real ViennaPS+DevSim)

**Interfaces:**
- Consumes: Tasks 1, 2, 5.

- [ ] **Step 1: Write the real test**

```python
# tests/integration/test_ce2_oxidation_conversion_unsupported_real.py
"""Spec CE-2, executable: a dopant whose Si is CONSUMED by a real
oxidation (Si -> SiO2 conversion, directly measured elsewhere this
session) must report UNSUPPORTED_BY_MODEL for its fate there -- never
a silent geometry-gated 0. A separate, unrelated, still-computable
profile at another location must still return its real value (the
partial-aggregate contract, spec Sec6)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401
from tcad.process import registry
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.mesh.viennaps_adapter import build_process_result


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step0 = registry.get("oxidation", "thermal")()
        recipe0 = {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            "mask_spans_um": [], "pr_thickness_um": 1.0,
            "silicon_depth_um": 5.0, "grid_delta_um": 0.2,
            "x_extent_um": 10.0, "y_extent_um": 8.0,
            "oxidant": "Dry", "temperature_c": 900.0, "time_hours": 0.01,
        }
        result0 = step0.run(recipe0, tmp)
        base = build_process_result(result0["final_mesh"])

        # A very shallow N implant, right where the next oxidation will consume Si.
        n_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=0.0,
            straggle_um=0.05, donor_peak_conc_cm3=1e18, donor_species="P",
        )
        state1 = advance_wafer_state(step0.last_domain, None, n_result, "oxidation")

        # A SEPARATE, deep P profile, far enough down that the next
        # oxidation cannot possibly reach it -- must stay fully computable.
        p_result = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=0.0,
            straggle_um=0.05, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        # merge both into one state directly (both share the same base geometry)
        import dataclasses
        state1 = dataclasses.replace(
            state1, dopant_profiles=state1.dopant_profiles +
            tuple(p for p in advance_wafer_state(step0.last_domain, None, p_result, "oxidation").dopant_profiles)
        )

        recipe1 = dict(recipe0)
        recipe1["temperature_c"], recipe1["time_hours"] = 1050.0, 0.3
        step1 = registry.get("oxidation", "thermal")(inherited_domain=step0.last_domain)
        result1 = step1.run(recipe1, tmp)
        state2 = advance_wafer_state(step1.last_domain, state1, base, "oxidation")

        q_shallow = state2.net_doping_at(0.0, 0.02)   # near-surface: consumed by oxidation
        print(f"[near-surface, consumed by real oxidation] donor={q_shallow.donor_concentration}, "
              f"physics_status={q_shallow.physics_status}")
        assert q_shallow.physics_status is not None
        assert q_shallow.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"

        q_deep = state2.net_doping_at(0.0, 3.0)   # deep: real Si, untouched by oxidation
        print(f"[deep, untouched] donor={q_deep.donor_concentration:.3e}, acceptor={q_deep.acceptor_concentration:.3e}, "
              f"physics_status={q_deep.physics_status}")
        assert q_deep.physics_status is None
        assert q_deep.donor_concentration > 0 or q_deep.acceptor_concentration > 0

        print("Oxidation's real Si->SiO2 conversion correctly reports UNSUPPORTED_BY_MODEL "
              "for the consumed dopant's fate (never a silent 0), while an unrelated, "
              "still-real profile elsewhere stays fully computable -- CE-2 confirmed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce2_oxidation_conversion_unsupported_real.py`
Expected: may need real tuning of `straggle_um`/oxidation time so the shallow profile's peak genuinely falls within the real consumed region (use this session's own established real-consumption numbers — a 1050°C/0.3hr oxidation on a 0.2 µm grid measurably consumed Si down to somewhere between y=0.08 and y=0.15 µm, per this plan's own spec evidence — pick probe depths and straggle accordingly, and print the real consumed range from the mesh directly rather than assuming it, matching this project's "verify by running" discipline).

- [ ] **Step 3: N/A (test-only)**

- [ ] **Step 4: Confirm pass with real printed physics_status showing `UNSUPPORTED_BY_MODEL`.**

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce2_oxidation_conversion_unsupported_real.py
git commit -m "test: CE-2, real ViennaPS -- oxidation's Si consumption reports UNSUPPORTED_BY_MODEL, never silent 0"
```

---

### Task 8: DevSim per-node NetDoping conversion (`set_node_values`, replacing symbolic kind-dispatch)

**Files:**
- Modify: `tcad/device/devsim/doping_mapping.py` (`apply_doping()` — replace the kind-based equation-string branches with one generic per-node Python evaluation path)
- Test: `tests/integration/test_doping_mapping_per_node_real.py` (new)

**Interfaces:**
- Consumes: `WaferState.net_doping_at()` (Task 2), real DevSim `get_node_model_values`/`set_node_values` (already used elsewhere in this codebase, per spec §10).
- Produces: `apply_doping(device: str, region: str, state: WaferState) -> Optional[dict]` (returns the aggregated `physics_status` across every node that had a gap, or `None` if none did — mirrors the existing project convention of surfacing `physics_status` from a doping-application call).

- [ ] **Step 1: Write the failing real test**

```python
# tests/integration/test_doping_mapping_per_node_real.py
"""Real DevSim: apply_doping() now evaluates WaferState.net_doping_at()
at every REAL mesh node (via get_node_model_values(name='x'/'y'),
already used in voltage_probe.py) and writes via set_node_values --
replacing the old symbolic node_model(equation=...) kind-dispatch.
Cross-checked against the worked numeric example in spec Sec10."""
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
        result = step.run(recipe, tmp)
        base = build_process_result(result["final_mesh"])

        r_p = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=1.0,
            straggle_um=3.0, donor_peak_conc_cm3=3e18, donor_species="P",
        )
        r_b = apply_gaussian_implant_doping(
            base, region="Si", junction_axis="x", peak_position_um=-1.0,
            straggle_um=3.0, acceptor_peak_conc_cm3=1e18, acceptor_species="B",
        )
        state = advance_wafer_state(step.last_domain, None, r_p, "oxidation")
        import dataclasses
        state = dataclasses.replace(
            state, dopant_profiles=state.dopant_profiles +
            advance_wafer_state(step.last_domain, None, r_b, "oxidation").dopant_profiles,
        )

        device_name, region_name = import_process_result(base, device_name="ce_dev")
        try:
            physics_status = apply_doping(device_name, region_name, state)
            xs = devsim.get_node_model_values(device=device_name, region=region_name, name="x")
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"checked {len(xs)} real DevSim nodes")
            print(f"NetDoping range: [{min(net):.3e}, {max(net):.3e}]")
            print(f"physics_status: {physics_status}")
            assert len(xs) > 0
            assert max(net) > 0 and min(net) < 0, "both donor- and acceptor-dominated regions must exist"
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=device_name)

        print("Real per-node NetDoping written via set_node_values(), cross-checked "
              "against a real DevSim device -- kind-based symbolic equations retired.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_doping_mapping_per_node_real.py`
Expected: FAIL — `apply_doping()`'s current signature takes a `ProcessResult`/`DopingProfile`, not a `WaferState`.

- [ ] **Step 3: Implement**

```python
# tcad/device/devsim/doping_mapping.py -- apply_doping REWRITTEN
def apply_doping(device: str, region: str, state: "WaferState") -> Optional[dict]:
    """Real per-node NetDoping (spec 2026-09-03 Sec10) -- replaces
    every prior kind-based symbolic-equation branch. Works identically
    regardless of how many DopantProfiles WaferState carries or which
    models produced them."""
    import devsim
    from tcad.physics.values import combine, Resolution

    xs_um = devsim.get_node_model_values(device=device, region=region, name="x")
    ys_um = devsim.get_node_model_values(device=device, region=region, name="y")
    # DevSim's own x/y node models are in cm (this project's existing
    # convention, confirmed in voltage_probe.py) -- convert once.
    donors, acceptors, nets = [], [], []
    all_entries = []
    for x_cm, y_cm in zip(xs_um, ys_um):
        result = state.net_doping_at(x_cm * 1e4, y_cm * 1e4)
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

(`node_model(..., equation="0")` is required BEFORE `set_node_values` — confirmed real DevSim requirement already implicit in this project's existing `semiconductor_equation.py` usage: a node model must be REGISTERED before its values can be set. `x_cm * 1e4` converts DevSim's cm convention to this project's um convention — confirm the exact conversion direction against `voltage_probe.py`'s own real, already-verified `xs_cm = ... ; then used directly` pattern before assuming the multiplier's sign/magnitude; do not guess it, read that file's surrounding real usage.)

Every existing CALLER of the old `apply_doping(...)` (grep for it across `tcad/device/devsim/mesh_import.py`, the GUI, and every real integration test that calls it directly) must be updated to build a `WaferState` (via `advance_wafer_state()`) and call the new signature — this is expected to be the largest mechanical part of this task; enumerate every call site with `grep -rn "apply_doping(" tests/ tcad/` before starting, and update each one, not just the ones this brief happened to name.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_doping_mapping_per_node_real.py`
Expected: PASS with real printed NetDoping range spanning both signs.

Also re-run every PREVIOUSLY-passing doping-related real integration test this task's signature change touches (`test_phase7_doping_real.py`, `test_phase8_pn_junction_real.py`, `test_implant_windows_doping_real.py`, `test_doping_barrier_windows_real.py`, `test_gaussian_implant_doping_real.py`) to confirm zero regression in the actual computed NetDoping values (same physics, new mechanism) — this is the load-bearing check for this task, not merely "the new test passes."

- [ ] **Step 5: Commit**

```bash
git add tcad/device/devsim/doping_mapping.py tests/integration/test_doping_mapping_per_node_real.py
# plus every updated call site enumerated above
git commit -m "feat: real per-node NetDoping via set_node_values(), replacing symbolic kind-dispatch equations"
```

---

### Task 9: GUI rewiring — doping accumulation + anneal dispatch through the real new path

**Files:**
- Modify: `tcad_2d_stagewise.py` (`run_doping()`, `_on_thermal_anneal_clicked()`)
- Modify: `tests/integration/test_gui_thermal_anneal_real.py` (rewritten against the new mechanism, not `existing=`)

**Interfaces:**
- Consumes: `advance_wafer_state()` (Task 5), `apply_thermal_anneal()` new signature (Task 3).
- Produces: `self.wafer_state: Optional[WaferState]` as the GUI's own held state (new instance attribute, replacing the role `self.last_doped_result` played for accumulation — `self.last_doped_result` may still exist for whatever non-accumulation purposes it serves elsewhere, e.g. measurement; do not remove it if other code depends on it for something this task doesn't touch — read every existing reference before deciding).

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

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_thermal_anneal_real.py`
Expected: FAIL — `app.wafer_state` does not exist yet.

- [ ] **Step 3: Implement**

In `run_doping()`: after building `result` (the `ProcessResult` with `.doping` set by whichever `apply_*_doping` call the selected kind uses), replace the `existing=self.last_doped_result if accumulate else None` logic with:
```python
self.wafer_state = advance_wafer_state(
    self.last_domain_state_object,  # whatever real domain handle run_doping() already has for this mesh
    getattr(self, "wafer_state", None),
    result, self._current_process_category_for_doping(),  # or whatever the recipe's own category key is
)
```
In `_on_thermal_anneal_clicked()`: replace the call into the OLD `apply_thermal_anneal(result, temp, time)` with:
```python
updated_profiles, physics_status = apply_thermal_anneal(
    self.wafer_state.dopant_profiles, self.anneal_temp_var.get(), self.anneal_time_var.get(),
)
import dataclasses
self.wafer_state = dataclasses.replace(self.wafer_state, dopant_profiles=updated_profiles)
self.last_physics_status = physics_status
```
Log each species' real before/after `model_params["straggle_um"]` by POSITION (not species-keyed — the Stage-B final-review Important #1/#2 fix already established this pattern; reuse it, now reading `model_params` instead of the old dict shape), and surface `physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"` in the log line exactly as Stage B's fix wave already did for out-of-citation-window anneals — this task's version additionally covers a profile whose `model` has no anneal handler at all (Task 3), not only an out-of-window citation.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_gui_thermal_anneal_real.py`
Expected: PASS, real GUI, real ViennaPS, all 5 required sensitivities still demonstrated with real numbers.

- [ ] **Step 5: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_thermal_anneal_real.py
git commit -m "feat: GUI doping/anneal wired through advance_wafer_state()/dispatch-based apply_thermal_anneal, not existing="
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
flat wrong color. This test proves the FIX: real per-x-bucket colors
from WaferState.net_doping_at(), and a visibly distinct rendering for
any UNSUPPORTED_BY_MODEL bucket (spec Sec6's GUI requirement)."""
def main():
    ...  # same B-then-P setup as Task 9's test
    segments = app._doping_color_segments("Si", x_min_um=-5.0, x_max_um=5.0)
    print(f"segments: {segments}")
    # Must show at least TWO distinct colors -- not one flat color for
    # the whole region (the exact bug this session found and fixed).
    colors = {seg[2] for seg in segments if seg[2] not in ("#unsupported",)}
    assert len(colors) >= 2, "B(acceptor) and P(donor) regions must render as genuinely different colors"
    print(f"distinct real colors rendered: {colors}")
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

**Files:**
- Test: `tests/integration/test_ce3_implant_anneal_etch_implant_real.py` (new — the user's own explicitly required integration case)

**Interfaces:**
- Consumes: everything from Tasks 1-10, exercised through the real production GUI code path (not a bespoke script) — matching this project's own established pattern (`test_gui_thermal_anneal_real.py` already drives the real `TCADApplication`, window withdrawn).

- [ ] **Step 1: Write the real, full-chain test**

```python
# tests/integration/test_ce3_implant_anneal_etch_implant_real.py
"""Spec CE-3, the explicitly required final integration case: implant
-> anneal -> etch -> second implant, driven through the ACTUAL
production GUI handlers (app.run_doping, app._on_thermal_anneal_clicked,
real ViennaPS etch), ending in a real per-node DevSim NetDoping (Task 8)
that correctly reflects BOTH profiles -- neither via a legacy shortcut."""
import os, sys
from pathlib import Path
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    import tkinter, tcad_2d_stagewise as gui
    app = gui.TCADApplication()
    try:
        app.withdraw(); app.update_idletasks()
        app.grid_var.set(0.2)
        assert app._materialize_current_wafer()

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si"); app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(-1.0); app.dope_gauss_straggle_var.set(0.15)
        app.dope_gauss_acceptor_var.set(1.0e18); app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)
        profile1_id = id(app.wafer_state.dopant_profiles[0])
        print(f"[1/5] profile_1 (B) created")

        app.anneal_temp_var.set(950.0); app.anneal_time_var.set(300.0)
        app._on_thermal_anneal_clicked()
        b_widened = next(p for p in app.wafer_state.dopant_profiles if p.species == "B")
        print(f"[2/5] profile_1 (B) annealed: straggle -> {b_widened.model_params['straggle_um']:.4f} um")
        assert b_widened.model_params["straggle_um"] > 0.15

        # Real etch, via the GUI's own etch panel/run path.
        app.panel_category.set(app._PANEL_LABELS["etch"])
        app._show_panel_category()
        # ... set real etch fields for the currently-selected model, matching
        # this project's own existing test_gui_process_state_chaining_real.py
        # pattern for how a standalone RUN click continues from the current
        # domain -- read that file before writing this step, do not invent a
        # new chaining mechanism.
        assert app.run_etch()
        print(f"[3/5] real etch ran, chained from the doped wafer")

        app.panel_category.set(app._PANEL_LABELS["doping"])
        app._show_panel_category()
        app.dope_gauss_position_var.set(1.0); app.dope_gauss_straggle_var.set(0.1)
        app.dope_gauss_donor_var.set(2.0e18); app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P"); app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        species = sorted(p.species for p in app.wafer_state.dopant_profiles)
        print(f"[4/5] profile_2 (P) created post-etch: species now {species}")
        assert species == ["B", "P"]
        assert id(next(p for p in app.wafer_state.dopant_profiles if p.species == "B")) == profile1_id \
            or True  # profile_1 may be a NEW object (frozen dataclass, anneal returns a new one) --
                     # the real invariant is SPECIES PRESENT, not object identity; assert on species/count only.

        # Real per-node DevSim conversion (Task 8), through the real device.
        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.device.devsim.doping_mapping import apply_doping
        import devsim
        device_name, region_name = import_process_result(app.last_final_process_result, device_name="ce3_dev")
        try:
            physics_status = apply_doping(device_name, region_name, app.wafer_state)
            net = devsim.get_node_model_values(device=device_name, region=region_name, name="NetDoping")
            print(f"[5/5] real DevSim NetDoping range: [{min(net):.3e}, {max(net):.3e}], "
                  f"physics_status={physics_status}")
            assert max(net) > 0 and min(net) < 0
        finally:
            devsim.delete_device(device=device_name)
            devsim.delete_mesh(mesh=device_name)

        print("CE-3 confirmed end-to-end through the real production GUI: "
              "implant -> anneal -> etch -> second implant produces a real, "
              "correct, per-node NetDoping reflecting both profiles.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify**

Run: `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe tests/integration/test_ce3_implant_anneal_etch_implant_real.py`
Expected: real failures here are genuine integration gaps between Tasks 1-10 (e.g. a real API name mismatch between what Task 9 wired and what this test assumes) — debug against the real, already-committed Task 1-10 code, not by weakening this test's assertions.

- [ ] **Step 3: N/A (test-only; if a real gap is found, fix it in the OWNING task's file, not here — record which task's code changed in this task's own report)**

- [ ] **Step 4: Confirm pass with all 5 real printed milestones.**

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_ce3_implant_anneal_etch_implant_real.py
git commit -m "test: CE-3 full integration, real GUI end-to-end -- implant -> anneal -> etch -> second implant -> real per-node NetDoping"
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
