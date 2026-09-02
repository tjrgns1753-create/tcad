# State-Dependent Physics — Stage B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real, literature-grounded thermal annealing of dopant profiles
already in the wafer — every existing `DopantProfile` (not just the
newest one) broadens under its own species-specific Arrhenius `D(T)`,
dose is conserved, a new implant never erases an earlier one, and the
whole chain is observable end-to-end through the real GUI.

**Architecture:** Generalizes `gaussian_implant` from "one profile per
region" to "a list of independent terms per region" — the same
generalization `implant_windows` already made for laterally-windowed
implants, applied here to temporally-separate implants instead.
`WaferState.dopant_profiles` (already a tuple, from Stage A) becomes
the real multi-profile carrier; `apply_thermal_anneal()` is the one
function that reads every term, looks up that term's own species'
`D(T)` from a literature-cited table, and rewrites it — never a
special case for which two species happen to be present.
`DiffusionModel`-shaped physics (a single, reusable `anneal_profile()`
kernel) stays separate from `apply_thermal_diffusion_doping()` (new
dopant introduced from an external source, e.g. POCl3) — that function
is explicitly NOT built in this stage; see "Deferred to Stage B2" below.

**Tech Stack:** Pure Python (`math.exp`, no new dependency) for the
Arrhenius physics; real DevSim `exp()` node-model equations (already
verified supported, same mechanism `gaussian_implant`'s existing single
-term case already uses) for the device-layer NetDoping expression;
real ViennaPS + DevSim for every `_real.py` test.

**Spec:** `docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md`
(§1 "Diffusion physics as a pluggable model layer" — this plan
implements the cumulative-thermal-budget mechanism that section
describes, scoped to annealing EXISTING implant profiles only; the
`DiffusionModel` protocol's other consumer, external-source diffusion
doping, is Stage B2, not this plan). Base design:
`docs/superpowers/specs/2026-08-25-wafer-state-physics-design.md`.
Stage A (already shipped): `docs/superpowers/plans/2026-09-01-state-dependent-physics-stage-a.md`.

## Global Constraints

- **Zero behavior change for every existing caller that does not pass
  the new, additive parameters this plan introduces.** Every new
  field/parameter defaults to `None`/absent and reproduces today's
  single-implant, single-term path byte-for-byte. Confirmed per task
  via the pre-existing tests named in that task.
- **No new empirical constant or physics formula without a real
  citation.** Every `D(T)` value comes from a specific, identified
  paper with its own measured temperature window; a value used outside
  that window is `UNVERIFIED`, never silently promoted. No dopant-pair
  "interaction" physics is invented — each profile's own species alone
  determines its own `D(T)`; profiles never affect each other beyond
  independently sharing the same anneal's temperature/time.
- **Dose conservation is a real, tested invariant, not an assumption.**
  For a Gaussian term, dose `Q = peak_conc_cm3 * straggle_um * sqrt(2*pi)`
  (this project's own 1D convention: the profile is defined along one
  lateral axis only, uniform in the other two dimensions, so `Q` here
  is a linear density along that axis — self-consistent before/after
  the SAME formula, not a claim about a real 3D areal dose). Thermal
  broadening must leave `Q` numerically unchanged (within floating
  tolerance) for every term, independently.
- **`thermal_budget` is `sum(D(species, host, T_i) * t_i)` over every
  anneal step that profile has lived through — never raw elapsed time.**
  A 900 C / 10 min anneal and a 1000 C / 10 min anneal on the identical
  starting profile MUST produce different broadening; this is a
  required, directly-tested assertion in this plan, not an incidental
  property.
- **Depth/junction-depth evolution is `UNSUPPORTED_BY_MODEL`, not
  silently absent.** Every profile in this project (before and after
  this plan) is defined along one lateral axis only; a real anneal also
  moves the junction DEPTH, and this plan does not implement that. The
  limitation must be a real, importable, testable constant — not only a
  comment.
- **Oxide-related physics is out of scope for this plan entirely.**
  `apply_thermal_anneal()` only redistributes dopant already inside
  silicon; it reads no oxide thickness and applies no barrier check.
  (The future `apply_thermal_diffusion_doping()`'s oxide-masking
  mechanism, and any future ion-implant-through-oxide stopping-power
  model, are two SEPARATE physical mechanisms — noted here so a later
  session does not merge them.)
- **The one place DevSim's NetDoping gets built stays
  `tcad/device/devsim/doping_mapping.py`.** `WaferState`,
  `DopantProfile`, and every new function in `tcad/physics/doping.py`
  stay device-layer-independent (no `devsim` import), per Stage A's
  own established boundary.
- Test convention: `def main(): ... assert ...` + `if __name__ ==
  "__main__": main()`, not pytest. `tests/unit/` for pure-Python tests,
  `tests/integration/` (`_real.py` suffix) for real ViennaPS+DevSim.
  Both auto-discovered by `tests/run_regression.py`.
- Real backends: `PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE` env
  vars, project venv at `../.venv/Scripts/python.exe`.

## Literature sources for this plan (cited once here; every task below
references these by short name)

- **[Christensen2003]** — J. S. Christensen, H. H. Radamson,
  A. Yu. Kuznetsov, B. G. Svensson, "Phosphorus and boron diffusion in
  silicon under equilibrium conditions", *Applied Physics Letters*
  82(14), 2254–2256 (2003). DOI 10.1063/1.1566464. Real, intrinsic
  diffusivity measurements in high-purity epitaxial Si:
  - Phosphorus: `D0 = 8e-4 cm^2/s` (±5e-4), `Ea = 2.74 eV` (±0.07),
    measured over **810–1100 C**.
  - Boron: `D0 = 0.06 cm^2/s` (±0.02), `Ea = 3.12 eV` (±0.04), measured
    over **810–1050 C**.
  - This plan uses the reported central values; the reported
    uncertainties are not separately propagated (a real, stated
    simplification — this project's `Resolution`/`Provenance` axes
    already distinguish "cited, in-window" from every weaker case, and
    error-bar propagation is a further refinement, not required for
    this plan's own acceptance tests).

No SiO2-diffusivity citation is used in this plan (oxide physics is
explicitly out of scope here, see Global Constraints).

---

### Task 1: Literature D(T) data + the Arrhenius physics kernel

**Files:**
- Modify: `tcad/physics/tables.py`
- Create: `tcad/physics/diffusion_model.py`
- Test: `tests/unit/test_diffusion_model_mock.py`

**Interfaces:**
- Consumes: `tcad.physics.values.{Conditions, Coverage, PhysicalValue,
  Provenance, Range, Resolution, Source}` (existing, unchanged).
- Produces (for Task 2 and Task 4):
  - `tables.INTERACTION_COEFFICIENTS` gains 4 real entries (see Step 3).
  - `diffusion_model.arrhenius_diffusivity(species: str, host_material:
    str, temperature_c: float) -> PhysicalValue` — `.value` is `D` in
    `cm^2/s` (or `None` if no table entry), `.resolution` is `VERIFIED`
    only when `temperature_c` falls inside the citation's own measured
    window.
  - `diffusion_model.thermal_budget_contribution(species: str,
    host_material: str, temperature_c: float, time_s: float) ->
    PhysicalValue` — `.value` is `D * time_s` in `cm^2` (the real
    physical unit of a diffusion length squared), or `None` if `D` is
    unknown. Same `.resolution` propagation as above.
  - `diffusion_model.K_BOLTZMANN_EV_PER_K = 8.617333262e-5` (CODATA
    2018 value, `eV/K` — a physical constant, not a citation-derived
    parameter, so it lives as a module constant rather than a table
    entry).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_diffusion_model_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arrhenius D(T) kernel: matches the literature formula exactly, and
downgrades to UNVERIFIED outside the citation's own measured window --
no ViennaPS/DevSim needed, pure math."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.diffusion_model import (
    K_BOLTZMANN_EV_PER_K,
    arrhenius_diffusivity,
    thermal_budget_contribution,
)
from tcad.physics.values import Resolution


def _expected_D(D0, Ea, temperature_c):
    T_kelvin = temperature_c + 273.15
    return D0 * math.exp(-Ea / (K_BOLTZMANN_EV_PER_K * T_kelvin))


def test_phosphorus_matches_christensen_2003_in_window():
    """[Christensen2003]: P, D0=8e-4 cm^2/s, Ea=2.74 eV, 810-1100 C."""
    result = arrhenius_diffusivity("P", "Si", 900.0)
    expected = _expected_D(8e-4, 2.74, 900.0)
    assert result.value is not None
    assert abs(result.value - expected) / expected < 1e-9
    assert result.resolution is Resolution.VERIFIED, (
        f"900 C is inside [Christensen2003]'s 810-1100 C P window -- "
        f"expected VERIFIED, got {result.resolution}"
    )


def test_boron_matches_christensen_2003_in_window():
    """[Christensen2003]: B, D0=0.06 cm^2/s, Ea=3.12 eV, 810-1050 C."""
    result = arrhenius_diffusivity("B", "Si", 900.0)
    expected = _expected_D(0.06, 3.12, 900.0)
    assert result.value is not None
    assert abs(result.value - expected) / expected < 1e-9
    assert result.resolution is Resolution.VERIFIED


def test_outside_measured_window_is_downgraded():
    """1200 C is above [Christensen2003]'s 1100 C P ceiling -- the
    formula still computes a number (Arrhenius extrapolation is
    physically continuous), but this project's own rule is that a
    citation used outside its stated window is UNVERIFIED, never
    silently treated as equally trustworthy."""
    result = arrhenius_diffusivity("P", "Si", 1200.0)
    assert result.value is not None
    assert result.resolution is Resolution.UNVERIFIED, (
        f"1200 C is outside [Christensen2003]'s 810-1100 C P window -- "
        f"expected UNVERIFIED, got {result.resolution}"
    )


def test_unknown_species_or_host_returns_unknown():
    result = arrhenius_diffusivity("As", "Si", 900.0)
    assert result.value is None
    assert result.resolution is Resolution.UNKNOWN

    result = arrhenius_diffusivity("P", "SiO2", 900.0)
    assert result.value is None
    assert result.resolution is Resolution.UNKNOWN


def test_thermal_budget_is_D_times_t_not_raw_time():
    """The whole point of this function: two anneals with the SAME
    duration but DIFFERENT temperatures must give DIFFERENT budgets,
    because D(T) itself differs -- this is the assertion the base
    design's own migration-table language ("900 C 10 min and 1000 C
    10 min must not have the same diffusion effect") requires."""
    low = thermal_budget_contribution("P", "Si", 900.0, 600.0)
    high = thermal_budget_contribution("P", "Si", 1000.0, 600.0)
    assert low.value is not None and high.value is not None
    assert high.value > low.value, (
        f"1000 C/600s budget ({high.value}) must exceed 900 C/600s "
        f"budget ({low.value}) -- higher T means larger D(T), same t"
    )
    # exact value, not just direction:
    expected_low = _expected_D(8e-4, 2.74, 900.0) * 600.0
    assert abs(low.value - expected_low) / expected_low < 1e-9


def main():
    test_phosphorus_matches_christensen_2003_in_window()
    test_boron_matches_christensen_2003_in_window()
    test_outside_measured_window_is_downgraded()
    test_unknown_species_or_host_returns_unknown()
    test_thermal_budget_is_D_times_t_not_raw_time()
    print("Arrhenius D(T) matches [Christensen2003] exactly inside its "
          "measured window, downgrades outside it, and thermal budget "
          "genuinely depends on temperature, not just elapsed time.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_diffusion_model_mock.py`
Expected: `ModuleNotFoundError: No module named 'tcad.physics.diffusion_model'`

- [ ] **Step 3: Add the real, cited table entries**

In `tcad/physics/tables.py`, add to `INTERACTION_COEFFICIENTS` (after
the existing empty-dict declaration, replacing the bare `{}` literal
with the populated dict below — keep the surrounding module docstring
and `MATERIAL_PROPERTIES` untouched):

```python
#: (material, chemistry, parameter) -> PhysicalValue.
#: Populated only with real citations -- see each Source string for
#: the exact paper. Everything else still resolves to UNKNOWN.
INTERACTION_COEFFICIENTS: Dict[Tuple[str, str, str], PhysicalValue] = {
    ("Si", "P", "diffusivity_D0_cm2_s"): PhysicalValue(
        value=8e-4, unit="cm^2/s", material="Si", chemistry="P",
        conditions=Conditions(temperature_c=Range(810.0, 1100.0),
                               notes="intrinsic diffusivity, high-purity epitaxial Si"),
        source=Source(
            "Christensen, Radamson, Kuznetsov, Svensson, \"Phosphorus and "
            "boron diffusion in silicon under equilibrium conditions\", "
            "Appl. Phys. Lett. 82(14), 2254-2256 (2003), "
            "DOI 10.1063/1.1566464",
            Provenance.LITERATURE,
        ),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
    ("Si", "P", "diffusivity_Ea_eV"): PhysicalValue(
        value=2.74, unit="eV", material="Si", chemistry="P",
        conditions=Conditions(temperature_c=Range(810.0, 1100.0),
                               notes="intrinsic diffusivity, high-purity epitaxial Si"),
        source=Source(
            "Christensen, Radamson, Kuznetsov, Svensson, \"Phosphorus and "
            "boron diffusion in silicon under equilibrium conditions\", "
            "Appl. Phys. Lett. 82(14), 2254-2256 (2003), "
            "DOI 10.1063/1.1566464",
            Provenance.LITERATURE,
        ),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
    ("Si", "B", "diffusivity_D0_cm2_s"): PhysicalValue(
        value=0.06, unit="cm^2/s", material="Si", chemistry="B",
        conditions=Conditions(temperature_c=Range(810.0, 1050.0),
                               notes="intrinsic diffusivity, high-purity epitaxial Si"),
        source=Source(
            "Christensen, Radamson, Kuznetsov, Svensson, \"Phosphorus and "
            "boron diffusion in silicon under equilibrium conditions\", "
            "Appl. Phys. Lett. 82(14), 2254-2256 (2003), "
            "DOI 10.1063/1.1566464",
            Provenance.LITERATURE,
        ),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
    ("Si", "B", "diffusivity_Ea_eV"): PhysicalValue(
        value=3.12, unit="eV", material="Si", chemistry="B",
        conditions=Conditions(temperature_c=Range(810.0, 1050.0),
                               notes="intrinsic diffusivity, high-purity epitaxial Si"),
        source=Source(
            "Christensen, Radamson, Kuznetsov, Svensson, \"Phosphorus and "
            "boron diffusion in silicon under equilibrium conditions\", "
            "Appl. Phys. Lett. 82(14), 2254-2256 (2003), "
            "DOI 10.1063/1.1566464",
            Provenance.LITERATURE,
        ),
        resolution=Resolution.VERIFIED, provenance=Provenance.LITERATURE,
    ),
}
```

Also add `Range` to the existing `from tcad.physics.values import (...)`
line at the top of `tables.py` (it currently imports `Conditions,
Coverage, PhysicalValue, Provenance, Resolution, Source` — add `Range`
to that same import line, alphabetically).

- [ ] **Step 4: Write the Arrhenius kernel**

Create `tcad/physics/diffusion_model.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arrhenius D(T) and cumulative thermal-budget physics, sourced only
from tcad.physics.tables.INTERACTION_COEFFICIENTS -- every number this
module returns traces back to a real citation there, or is UNKNOWN.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md
section 1: this is the model boundary a future NumericalDiffusionModel
(a real PDE time-integration) can be substituted behind, without
changing anything that calls arrhenius_diffusivity()/
thermal_budget_contribution() or anneal_profile() (added in a later
task of this same plan).

thermal_budget_contribution() computes ONE isothermal step's own D*t
contribution -- the v1 scope this plan implements. A profile's running
thermal_budget (see DopantProfile, extended in a later task) is the
SUM of these contributions across every anneal it has lived through:
sum(D(T_i) * t_i) approximates the real integral ∫D(T(t))dt as a
piecewise-constant (one temperature per step) integral. This is an
explicit v1 simplification, not an architectural limit: a future
caller with a continuous T(t) history could integrate that directly
and still only ever needs to update the same single accumulated
thermal_budget scalar this module already produces -- nothing here
assumes temperature is constant for a profile's WHOLE lifetime, only
that each individual anneal STEP is isothermal (true of every real
furnace/RTA anneal this project's reference case describes).
"""

from __future__ import annotations

import math

from tcad.physics.tables import INTERACTION_COEFFICIENTS
from tcad.physics.values import (
    Conditions, Coverage, PhysicalValue, Provenance, Resolution,
)

#: CODATA 2018 value, eV/K -- a physical constant, not a citation.
K_BOLTZMANN_EV_PER_K = 8.617333262e-5

_NO_CONDITIONS = Conditions(notes="not applicable")


def arrhenius_diffusivity(
    species: str, host_material: str, temperature_c: float,
) -> PhysicalValue:
    """D(T) = D0 * exp(-Ea / (k_B * T_kelvin)), both D0 and Ea read
    from real cited table entries. UNKNOWN if either constant has no
    table entry for (host_material, species). VERIFIED only when
    temperature_c falls inside BOTH constants' own measured window;
    a value computed outside that window is UNVERIFIED -- the formula
    still evaluates (Arrhenius behavior is physically continuous), but
    this project never treats an extrapolation as equally trustworthy
    as an in-window citation.
    """
    d0_entry = INTERACTION_COEFFICIENTS.get(
        (host_material, species, "diffusivity_D0_cm2_s"))
    ea_entry = INTERACTION_COEFFICIENTS.get(
        (host_material, species, "diffusivity_Ea_eV"))
    if d0_entry is None or ea_entry is None:
        return PhysicalValue(
            value=None, unit="cm^2/s", material=host_material,
            chemistry=species, conditions=d0_entry.conditions if d0_entry
            else ea_entry.conditions if ea_entry else _NO_CONDITIONS,
            source=None, resolution=Resolution.UNKNOWN,
            provenance=Provenance.DERIVED,
        )

    temperature_kelvin = temperature_c + 273.15
    value = d0_entry.value * math.exp(
        -ea_entry.value / (K_BOLTZMANN_EV_PER_K * temperature_kelvin)
    )

    requested = {"temperature_c": temperature_c}
    d0_inside = d0_entry.conditions.covers(requested) is Coverage.INSIDE
    ea_inside = ea_entry.conditions.covers(requested) is Coverage.INSIDE
    resolution = (
        Resolution.VERIFIED if (d0_inside and ea_inside) else Resolution.UNVERIFIED
    )

    return PhysicalValue(
        value=value, unit="cm^2/s", material=host_material,
        chemistry=species, conditions=d0_entry.conditions,
        source=d0_entry.source, resolution=resolution,
        provenance=Provenance.LITERATURE,
    )


def thermal_budget_contribution(
    species: str, host_material: str, temperature_c: float, time_s: float,
) -> PhysicalValue:
    """D(T) * t for ONE isothermal anneal step -- see this module's own
    docstring for why summing these across steps approximates
    integral D(T(t)) dt, and why that is a stated v1 scope limit, not
    an architectural one."""
    diffusivity = arrhenius_diffusivity(species, host_material, temperature_c)
    if diffusivity.value is None:
        return diffusivity
    return PhysicalValue(
        value=diffusivity.value * time_s, unit="cm^2",
        material=diffusivity.material, chemistry=diffusivity.chemistry,
        conditions=diffusivity.conditions, source=diffusivity.source,
        resolution=diffusivity.resolution, provenance=diffusivity.provenance,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_diffusion_model_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 6: Commit**

```bash
git add tcad/physics/tables.py tcad/physics/diffusion_model.py tests/unit/test_diffusion_model_mock.py
git commit -m "feat: literature-cited Arrhenius D(T) for P/B in Si (Stage B, state-dependent physics)"
```

---

### Task 2: Dose-conserving Gaussian broadening kernel

**Files:**
- Modify: `tcad/physics/dopant_profile.py` (`DopantProfile` gains
  shape fields)
- Modify: `tcad/physics/diffusion_model.py` (add `anneal_profile()`)
- Test: `tests/unit/test_anneal_profile_mock.py`

**Interfaces:**
- Consumes: `DopantProfile` (Stage A), `thermal_budget_contribution`
  (Task 1).
- Produces (for Task 4):
  - `DopantProfile` gains three new, all-optional fields:
    `peak_conc_cm3: Optional[float] = None`,
    `peak_position_um: Optional[float] = None`,
    `straggle_um: Optional[float] = None` — `None` for every profile
    kind that has no defined shape (uniform/step_junction/
    implant_windows-derived profiles; Stage A never sets these, so
    every existing profile stays exactly as it was). Set together (all
    three or none) for a Gaussian-shaped profile.
  - `diffusion_model.anneal_profile(profile: DopantProfile,
    temperature_c: float, time_s: float) -> DopantProfile` — returns
    a NEW `DopantProfile` (frozen, so never mutates the input). If
    `profile.straggle_um is None` (no defined shape) or
    `profile.species is None` (no citation-backed D(T) available),
    returns the SAME profile unchanged (documented, not silent —
    caller decides whether to log this). Otherwise: broadens
    `straggle_um` by this step's own `D(T)*t` contribution, rescales
    `peak_conc_cm3` to conserve dose, rebuilds `concentration_at`
    from the new peak/position/straggle, and adds this step's
    contribution to `thermal_budget`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_anneal_profile_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anneal_profile(): real dose-conserving Gaussian broadening -- no
ViennaPS/DevSim needed."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.diffusion_model import anneal_profile, thermal_budget_contribution


def _gaussian_profile(species, polarity, peak, position, straggle):
    def shape(x, d, p=peak, pos=position, s=straggle):
        return p * math.exp(-((x - pos) ** 2) / (2.0 * s ** 2))
    return DopantProfile(
        species=species, polarity=polarity, concentration_at=shape,
        peak_conc_cm3=peak, peak_position_um=position, straggle_um=straggle,
    )


def _dose(profile):
    """Q = peak * straggle * sqrt(2*pi) -- this plan's own defined
    dose convention (a self-consistent 1D linear density, not a
    claimed real-world 3D areal dose -- see the plan's Global
    Constraints for why)."""
    return profile.peak_conc_cm3 * profile.straggle_um * math.sqrt(2.0 * math.pi)


def test_broadens_and_conserves_dose():
    profile = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    dose_before = _dose(profile)

    annealed = anneal_profile(profile, temperature_c=900.0, time_s=600.0)

    assert annealed.straggle_um > profile.straggle_um, "must broaden, not stay fixed"
    assert annealed.peak_conc_cm3 < profile.peak_conc_cm3, (
        "peak must drop as the profile widens -- otherwise dose is invented"
    )
    dose_after = _dose(annealed)
    assert abs(dose_after - dose_before) / dose_before < 1e-9, (
        f"dose not conserved: {dose_before} -> {dose_after}"
    )


def test_exact_broadening_matches_the_real_formula():
    """sigma_new^2 = sigma_old^2 + 2*Dt -- the exact Gaussian-diffusion
    Green's-function result, checked against thermal_budget_contribution's
    own real D(T)*t (Task 1), not re-derived independently here."""
    profile = _gaussian_profile("B", "acceptor", peak=5e18, position=1.0, straggle=0.2)
    contribution = thermal_budget_contribution("B", "Si", 950.0, 300.0)
    assert contribution.value is not None

    annealed = anneal_profile(profile, temperature_c=950.0, time_s=300.0)

    # Dt is in cm^2; straggle_um is in um -- 1 cm^2 = 1e8 um^2.
    expected_straggle_um2 = (0.2 ** 2) + 2.0 * contribution.value * 1e8
    assert abs(annealed.straggle_um ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9

    assert abs(annealed.thermal_budget - contribution.value) / contribution.value < 1e-9


def test_higher_temperature_broadens_more():
    profile_a = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    profile_b = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)

    low = anneal_profile(profile_a, temperature_c=900.0, time_s=600.0)
    high = anneal_profile(profile_b, temperature_c=1000.0, time_s=600.0)

    assert high.straggle_um > low.straggle_um, (
        "1000 C must broaden more than 900 C at the identical duration"
    )


def test_no_shape_or_no_species_is_unchanged():
    """A profile with no defined Gaussian shape (straggle_um is None --
    e.g. Stage A's uniform/step_junction/implant_windows-derived
    profiles) or no species label has nothing anneal_profile() can
    compute a citation-backed D(T) for -- returned unchanged, not
    guessed."""
    no_shape = DopantProfile(species="P", polarity="donor",
                              concentration_at=lambda x, d: 1e17)
    result = anneal_profile(no_shape, temperature_c=900.0, time_s=600.0)
    assert result is no_shape or result == no_shape

    no_species = DopantProfile(species=None, polarity="donor",
                                concentration_at=lambda x, d: 1e19,
                                peak_conc_cm3=1e19, peak_position_um=0.0,
                                straggle_um=0.1)
    result = anneal_profile(no_species, temperature_c=900.0, time_s=600.0)
    assert result.straggle_um == no_species.straggle_um, (
        "no species label -- no citation-backed D(T) exists -- must not guess one"
    )


def test_cumulative_across_two_anneal_calls():
    """The core worked example this whole stage exists for: annealing
    TWICE must widen the profile MORE than annealing once, and by the
    exact sum of both steps' own D(T)*t (each step's OWN temperature)."""
    profile = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)

    once = anneal_profile(profile, temperature_c=900.0, time_s=600.0)
    twice = anneal_profile(once, temperature_c=1000.0, time_s=300.0)

    c1 = thermal_budget_contribution("P", "Si", 900.0, 600.0)
    c2 = thermal_budget_contribution("P", "Si", 1000.0, 300.0)
    expected_straggle_um2 = (0.1 ** 2) + 2.0 * (c1.value + c2.value) * 1e8

    assert twice.straggle_um > once.straggle_um
    assert abs(twice.straggle_um ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9
    assert abs(twice.thermal_budget - (c1.value + c2.value)) / (c1.value + c2.value) < 1e-9


def main():
    test_broadens_and_conserves_dose()
    test_exact_broadening_matches_the_real_formula()
    test_higher_temperature_broadens_more()
    test_no_shape_or_no_species_is_unchanged()
    test_cumulative_across_two_anneal_calls()
    print("anneal_profile() conserves dose exactly, matches the real "
          "Gaussian-diffusion broadening formula, is genuinely "
          "temperature-dependent (not just elapsed time), and "
          "accumulates correctly across repeated anneal calls.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_anneal_profile_mock.py`
Expected: `TypeError: __init__() got an unexpected keyword argument 'peak_conc_cm3'`

- [ ] **Step 3: Extend `DopantProfile`**

In `tcad/physics/dopant_profile.py`, add three fields to the
`DopantProfile` dataclass (after `source`, all defaulting to `None`):

```python
    peak_conc_cm3: Optional[float] = None
    peak_position_um: Optional[float] = None
    straggle_um: Optional[float] = None
```

Update the class docstring to document them (one short paragraph:
"peak_conc_cm3 / peak_position_um / straggle_um : set together for a
Gaussian-shaped profile -- the extra structure `anneal_profile()`
(tcad.physics.diffusion_model) needs to re-broaden this profile under
further thermal budget. None for every profile with no defined shape
(this module's uniform/step_junction/implant_windows conversions never
set these).").

- [ ] **Step 4: Write `anneal_profile()`**

In `tcad/physics/diffusion_model.py`: add
`from tcad.physics.dopant_profile import DopantProfile` to the file's
existing top-of-file import block (`math` is already imported there
from Task 1 — no second import needed). Then add this function after
`thermal_budget_contribution`:

```python
def anneal_profile(
    profile: DopantProfile, temperature_c: float, time_s: float,
) -> DopantProfile:
    """Real, dose-conserving Gaussian broadening under one isothermal
    anneal step. See this module's own docstring for the thermal-budget
    accumulation model.

    Dose Q = peak_conc_cm3 * straggle_um * sqrt(2*pi) (this plan's own
    1D convention) is conserved EXACTLY: sigma_new^2 = sigma_old^2 +
    2*Dt (the real Green's-function result for Gaussian diffusion),
    and peak_new = peak_old * (sigma_old / sigma_new) -- the unique
    rescaling that keeps Q unchanged while sigma grows.

    Returns the SAME profile, unchanged, when there is no defined shape
    (straggle_um is None) or no species label (no citation-backed D(T)
    is possible) -- never guesses.
    """
    if profile.straggle_um is None or profile.species is None:
        return profile

    contribution = thermal_budget_contribution(
        profile.species, "Si", temperature_c, time_s,
    )
    if contribution.value is None:
        return profile

    dt_um2 = contribution.value * 1e8  # cm^2 -> um^2 (1 cm = 1e4 um)
    new_straggle = math.sqrt(profile.straggle_um ** 2 + 2.0 * dt_um2)
    new_peak = profile.peak_conc_cm3 * (profile.straggle_um / new_straggle)
    new_thermal_budget = profile.thermal_budget + contribution.value

    position = profile.peak_position_um

    def new_shape(x_um: float, depth_um: float,
                  peak=new_peak, pos=position, straggle=new_straggle) -> float:
        return peak * math.exp(-((x_um - pos) ** 2) / (2.0 * straggle ** 2))

    return DopantProfile(
        species=profile.species, polarity=profile.polarity,
        concentration_at=new_shape, thermal_budget=new_thermal_budget,
        source=profile.source, peak_conc_cm3=new_peak,
        peak_position_um=position, straggle_um=new_straggle,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_anneal_profile_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 6: Run Task 1's test unchanged**

Run: `../.venv/Scripts/python.exe tests/unit/test_diffusion_model_mock.py`
Expected: still passes, identical output (this task only added a new
function and new dataclass fields, changed nothing existing).

- [ ] **Step 7: Commit**

```bash
git add tcad/physics/dopant_profile.py tcad/physics/diffusion_model.py tests/unit/test_anneal_profile_mock.py
git commit -m "feat: dose-conserving Gaussian anneal kernel (Stage B, state-dependent physics)"
```

---

### Task 3: Multiple independent Gaussian implant terms per region

**Files:**
- Modify: `tcad/mesh/interface.py` (`DopingRegion` gains
  `gaussian_terms`)
- Modify: `tcad/physics/doping.py` (`apply_gaussian_implant_doping`
  gains `existing=`)
- Test: `tests/unit/test_gaussian_implant_terms_mock.py`

**Interfaces:**
- Consumes: existing `DopingRegion`/`DopingProfile`/`ProcessResult`
  (`tcad.mesh.interface`, unchanged shapes otherwise).
- Produces (for Task 5 and Task 6):
  - `DopingRegion.gaussian_terms: Optional[List[Dict]] = None` — each
    dict: `{"species": Optional[str], "polarity": "donor"|"acceptor",
    "peak_conc_cm3": float, "peak_position_um": float, "straggle_um":
    float, "thermal_budget_cm2": float}`. `None` for every existing
    caller (backward compatible); when set, this is the FULL list of
    independent terms for this region — the region's own
    `peak_conc_cm3`/`peak_position_um`/`straggle_um`/
    `donor_peak_conc_cm3`/`acceptor_peak_conc_cm3` legacy fields are
    left at whatever `apply_gaussian_implant_doping` last set them to
    (kept for any caller reading them directly) but a consumer that
    understands `gaussian_terms` (Task 5, Task 6) reads THAT list, not
    the legacy scalar fields, whenever it is present.
  - `apply_gaussian_implant_doping(..., existing: Optional[ProcessResult]
    = None)` — when `existing` is `None` (the default, every current
    caller), behavior is BYTE-IDENTICAL to today. When `existing` is
    given and `existing.doping` is `None` or already `kind ==
    "gaussian_implant"`, the new implant is APPENDED as one more term
    to whatever terms `existing.doping` already carried (converting
    its legacy single-profile shape into a one-item term list first,
    if it had no `gaussian_terms` yet), and the returned
    `ProcessResult.doping.regions[0].gaussian_terms` holds ALL terms
    (old and new). Raises `ValueError` if `existing.doping.kind` is
    set to anything other than `"gaussian_implant"` — mixing implant
    terms on top of a different doping kind's representation is
    explicitly out of this plan's scope (see the plan's Global
    Constraints: no new dopant-kind interaction physics).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gaussian_implant_terms_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_gaussian_implant_doping's existing= parameter: a second call
ADDS a term, never erases the first -- no ViennaPS/DevSim needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import apply_gaussian_implant_doping


def _base_result():
    return ProcessResult(
        volume_mesh_path="dummy.vtu",
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def test_existing_none_is_byte_identical_to_today():
    """Zero behavior change for every caller that doesn't pass existing=."""
    result = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.3,
        peak_conc_cm3=1.0e17,
    )
    region = result.doping.regions[0]
    assert region.peak_conc_cm3 == 1.0e17
    assert region.peak_position_um == 0.0
    assert region.straggle_um == 0.3
    assert region.gaussian_terms is None


def test_second_call_adds_a_term_does_not_erase_the_first():
    """B implant, then P implant on top -- both must exist afterward."""
    first = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        donor_peak_conc_cm3=0.0, acceptor_peak_conc_cm3=1.0e18,
        acceptor_species="B",
    )
    second = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.15,
        donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=0.0,
        donor_species="P",
        existing=first,
    )
    terms = second.doping.regions[0].gaussian_terms
    assert terms is not None
    assert len(terms) == 2, f"expected 2 terms (B then P), got {len(terms)}"

    species_seen = {t["species"] for t in terms}
    assert species_seen == {"B", "P"}, f"expected both B and P present, got {species_seen}"

    b_term = next(t for t in terms if t["species"] == "B")
    p_term = next(t for t in terms if t["species"] == "P")
    assert b_term["polarity"] == "acceptor"
    assert b_term["peak_conc_cm3"] == 1.0e18
    assert b_term["peak_position_um"] == -1.0
    assert p_term["polarity"] == "donor"
    assert p_term["peak_conc_cm3"] == 2.0e18
    assert p_term["peak_position_um"] == 1.0

    # ORIGINAL result object must be untouched (this project's own
    # convention: every apply_*_doping returns a NEW ProcessResult).
    assert first.doping.regions[0].gaussian_terms is None or \
        len(first.doping.regions[0].gaussian_terms) == 1


def test_existing_with_incompatible_kind_raises():
    from tcad.physics.doping import apply_uniform_doping
    uniform_result = apply_uniform_doping(_base_result(), {"Si": 1.0e16})
    try:
        apply_gaussian_implant_doping(
            _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
            peak_conc_cm3=1.0e18, existing=uniform_result,
        )
        assert False, "expected ValueError for incompatible existing doping kind"
    except ValueError:
        pass


def main():
    test_existing_none_is_byte_identical_to_today()
    test_second_call_adds_a_term_does_not_erase_the_first()
    test_existing_with_incompatible_kind_raises()
    print("apply_gaussian_implant_doping's existing= parameter adds "
          "terms without erasing earlier ones, and every caller that "
          "doesn't use it is completely unaffected.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_gaussian_implant_terms_mock.py`
Expected: `TypeError: apply_gaussian_implant_doping() got an unexpected keyword argument 'existing'`

- [ ] **Step 3: Add `gaussian_terms` to `DopingRegion`**

In `tcad/mesh/interface.py`, add ONE field to the `DopingRegion`
dataclass, after `acceptor_species` (the last existing field):

```python
    gaussian_terms: Optional[List[Dict[str, Any]]] = None
```

Add one paragraph to `DopingRegion`'s docstring: "`gaussian_terms` :
`gaussian_implant` case, MULTIPLE-implant variant -- a list of
independent term dicts (`species`, `polarity`, `peak_conc_cm3`,
`peak_position_um`, `straggle_um`, `thermal_budget_cm2`), each
representing one implant call that was ADDED rather than replacing
what came before (see `tcad.physics.doping.apply_gaussian_implant_
doping`'s `existing=` parameter). `None` for every region built from a
single implant call with no `existing=` — the plain
`peak_conc_cm3`/`peak_position_um`/`straggle_um` fields above still
carry that one profile, unchanged. When both this and the plain fields
are set, `gaussian_terms` is authoritative (device-layer and
process-layer readers that understand it use it INSTEAD of the plain
fields, which then describe only the region's original single-implant
form for any caller not yet updated to read `gaussian_terms`)."

`Dict`/`Any` are already imported at the top of `tcad/mesh/interface.py`
(`from typing import Any, Dict, List, Optional`) — no new import needed.

- [ ] **Step 4: Implement `existing=` in `apply_gaussian_implant_doping`**

In `tcad/physics/doping.py`, modify `apply_gaussian_implant_doping`'s
signature and body. Current signature (do not change the existing
parameters or their order/defaults — only ADD the new one at the end):

```python
def apply_gaussian_implant_doping(
    result: ProcessResult,
    region: str,
    junction_axis: str,
    peak_position_um: float,
    straggle_um: float,
    peak_conc_cm3: Optional[float] = None,
    *,
    donor_peak_conc_cm3: Optional[float] = None,
    acceptor_peak_conc_cm3: Optional[float] = None,
    donor_species: Optional[str] = None,
    acceptor_species: Optional[str] = None,
    existing: Optional[ProcessResult] = None,
) -> ProcessResult:
```

Replace the function body's final section (from `doping_region =
DopingRegion(` to the `return replace(result, doping=doping)` at the
end) with:

```python
    new_terms = []
    if donor_peak_conc_cm3:
        new_terms.append({
            "species": donor_species, "polarity": "donor",
            "peak_conc_cm3": donor_peak_conc_cm3,
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })
    if acceptor_peak_conc_cm3:
        new_terms.append({
            "species": acceptor_species, "polarity": "acceptor",
            "peak_conc_cm3": acceptor_peak_conc_cm3,
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })
    if not new_terms and peak_conc_cm3 is not None:
        # net-only input form -- this project's own documented sign
        # convention (positive net = donor, negative = acceptor),
        # same as every other doping kind's net-only fallback.
        polarity = "donor" if peak_conc_cm3 >= 0 else "acceptor"
        new_terms.append({
            "species": None, "polarity": polarity,
            "peak_conc_cm3": abs(peak_conc_cm3),
            "peak_position_um": peak_position_um, "straggle_um": straggle_um,
            "thermal_budget_cm2": 0.0,
        })

    all_terms = list(new_terms)
    if existing is not None:
        prior_doping = existing.doping
        if prior_doping is not None and prior_doping.kind != "gaussian_implant":
            raise ValueError(
                f"apply_gaussian_implant_doping's existing= only accepts a "
                f"prior gaussian_implant result (or none yet); got kind="
                f"{prior_doping.kind!r}. Superposing implant terms onto a "
                f"different doping kind's representation is out of scope -- "
                f"see this plan's Global Constraints."
            )
        if prior_doping is not None:
            prior_region = prior_doping.regions[0]
            if prior_region.gaussian_terms:
                all_terms = list(prior_region.gaussian_terms) + new_terms
            elif prior_region.peak_conc_cm3 is not None or \
                    prior_region.donor_peak_conc_cm3 is not None or \
                    prior_region.acceptor_peak_conc_cm3 is not None:
                # legacy single-implant region -- normalize it into one
                # or two terms (donor/acceptor) before appending the new one.
                prior_terms = []
                if prior_region.donor_peak_conc_cm3:
                    prior_terms.append({
                        "species": prior_region.donor_species, "polarity": "donor",
                        "peak_conc_cm3": prior_region.donor_peak_conc_cm3,
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                if prior_region.acceptor_peak_conc_cm3:
                    prior_terms.append({
                        "species": prior_region.acceptor_species, "polarity": "acceptor",
                        "peak_conc_cm3": prior_region.acceptor_peak_conc_cm3,
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                if not prior_terms and prior_region.peak_conc_cm3 is not None:
                    polarity = "donor" if prior_region.peak_conc_cm3 >= 0 else "acceptor"
                    prior_terms.append({
                        "species": None, "polarity": polarity,
                        "peak_conc_cm3": abs(prior_region.peak_conc_cm3),
                        "peak_position_um": prior_region.peak_position_um,
                        "straggle_um": prior_region.straggle_um,
                        "thermal_budget_cm2": 0.0,
                    })
                all_terms = prior_terms + new_terms

    if donor_peak_conc_cm3 is not None or acceptor_peak_conc_cm3 is not None:
        donor = donor_peak_conc_cm3 or 0.0
        acceptor = acceptor_peak_conc_cm3 or 0.0
        peak_conc_cm3 = donor - acceptor

    doping_region = DopingRegion(
        region=region,
        junction_axis=junction_axis,
        peak_position_um=peak_position_um,
        straggle_um=straggle_um,
        peak_conc_cm3=peak_conc_cm3,
        donor_peak_conc_cm3=donor_peak_conc_cm3,
        acceptor_peak_conc_cm3=acceptor_peak_conc_cm3,
        donor_species=donor_species,
        acceptor_species=acceptor_species,
        gaussian_terms=all_terms if (existing is not None and all_terms) else None,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[doping_region])
    return replace(result, doping=doping)
```

This keeps every existing call (no `existing=`) producing
`gaussian_terms=None` exactly as before (the `if (existing is not
None and all_terms)` guard), and only builds the multi-term list when
a caller actually opts in.

- [ ] **Step 5: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_gaussian_implant_terms_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 6: Run the existing donor/acceptor regression test unchanged**

Run: `PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_doping_donor_acceptor_all_kinds_real.py`
Expected: passes unchanged (it never passes `existing=`, so it takes
the byte-identical path).

- [ ] **Step 7: Commit**

```bash
git add tcad/mesh/interface.py tcad/physics/doping.py tests/unit/test_gaussian_implant_terms_mock.py
git commit -m "feat: apply_gaussian_implant_doping's existing= adds a term, never erases one (Stage B)"
```

---

### Task 4: `apply_thermal_anneal()` — every existing profile, its own D(T)

**Files:**
- Modify: `tcad/physics/doping.py`
- Test: `tests/unit/test_thermal_anneal_mock.py`

**Interfaces:**
- Consumes: `apply_gaussian_implant_doping`'s `gaussian_terms` shape
  (Task 3), `anneal_profile`/`thermal_budget_contribution` (Task 1/2).
- Produces (for Task 5, Task 6, Task 7):
  - `apply_thermal_anneal(result: ProcessResult, temperature_c: float,
    time_s: float) -> ProcessResult` — reads `result.doping`; if its
    `kind` is not `"gaussian_implant"` OR it has no defined terms
    (nothing to anneal), returns `result` UNCHANGED (a real result, not
    a silent no-op that pretends to have run — the caller can compare
    `result.doping is returned.doping` to detect this). Otherwise:
    normalizes the region's terms exactly like Task 3's `existing=`
    path does, calls `anneal_profile`-equivalent math (via a small
    per-term helper reusing `thermal_budget_contribution` +
    the same broadening formula) on EVERY term independently, and
    returns a NEW `ProcessResult` whose `doping.regions[0].
    gaussian_terms` holds every term updated.
  - `DEPTH_EVOLUTION_RESOLUTION: Resolution = Resolution.UNSUPPORTED_BY_MODEL`
    — a real, importable, testable module-level constant.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_thermal_anneal_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_thermal_anneal(): every existing term gets its OWN species'
D(T), independently -- no ViennaPS/DevSim needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import ProcessResult, MaterialRegion
from tcad.physics.doping import (
    DEPTH_EVOLUTION_RESOLUTION,
    apply_gaussian_implant_doping,
    apply_thermal_anneal,
    apply_uniform_doping,
)
from tcad.physics.values import Resolution


def _base_result():
    return ProcessResult(
        volume_mesh_path="dummy.vtu",
        material_regions=[MaterialRegion(name="Si", tag=1)],
    )


def test_depth_evolution_is_a_real_importable_constant():
    assert DEPTH_EVOLUTION_RESOLUTION is Resolution.UNSUPPORTED_BY_MODEL


def test_anneal_widens_every_term_by_its_own_species_D():
    b_implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    both = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
        existing=b_implant,
    )
    annealed = apply_thermal_anneal(both, temperature_c=900.0, time_s=600.0)

    terms = annealed.doping.regions[0].gaussian_terms
    b_term = next(t for t in terms if t["species"] == "B")
    p_term = next(t for t in terms if t["species"] == "P")

    assert b_term["straggle_um"] > 0.2, "B must broaden"
    assert p_term["straggle_um"] > 0.2, "P must broaden"
    # B and P have DIFFERENT Ea/D0 [Christensen2003] -- at the SAME
    # T/t they must broaden by DIFFERENT amounts, not identically.
    assert abs(b_term["straggle_um"] - p_term["straggle_um"]) > 1e-6, (
        f"B ({b_term['straggle_um']}) and P ({p_term['straggle_um']}) "
        f"broadened identically -- species-independent D(T) is wrong"
    )


def test_original_result_untouched():
    implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    )
    original_straggle = implant.doping.regions[0].peak_conc_cm3
    apply_thermal_anneal(implant, temperature_c=900.0, time_s=600.0)
    assert implant.doping.regions[0].peak_conc_cm3 == original_straggle


def test_non_gaussian_kind_is_a_real_no_op():
    uniform = apply_uniform_doping(_base_result(), {"Si": 1.0e17})
    result = apply_thermal_anneal(uniform, temperature_c=900.0, time_s=600.0)
    assert result is uniform, (
        "no defined shape to anneal -- must return the SAME object, "
        "not a copy pretending something happened"
    )


def test_900c_and_1000c_give_different_results():
    implant = apply_gaussian_implant_doping(
        _base_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    )
    low = apply_thermal_anneal(implant, temperature_c=900.0, time_s=600.0)
    high = apply_thermal_anneal(implant, temperature_c=1000.0, time_s=600.0)
    low_straggle = low.doping.regions[0].gaussian_terms[0]["straggle_um"]
    high_straggle = high.doping.regions[0].gaussian_terms[0]["straggle_um"]
    assert high_straggle > low_straggle


def main():
    test_depth_evolution_is_a_real_importable_constant()
    test_anneal_widens_every_term_by_its_own_species_D()
    test_original_result_untouched()
    test_non_gaussian_kind_is_a_real_no_op()
    test_900c_and_1000c_give_different_results()
    print("apply_thermal_anneal() widens every existing term by its "
          "own species' real D(T), independently, leaves non-Gaussian "
          "kinds as a real no-op, and 900C != 1000C.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_thermal_anneal_mock.py`
Expected: `ImportError: cannot import name 'apply_thermal_anneal' from 'tcad.physics.doping'`

- [ ] **Step 3: Write `apply_thermal_anneal()`**

In `tcad/physics/doping.py`, add near the top (after the existing
imports, before `apply_uniform_doping`):

```python
from tcad.physics.diffusion_model import thermal_budget_contribution
from tcad.physics.values import Resolution

#: This project's own doping representation is defined along ONE
#: lateral axis only (every existing kind -- uniform, step_junction,
#: gaussian_implant, implant_windows -- has no depth/y variation at
#: all). A real anneal also moves the junction DEPTH; this module does
#: not compute that. Real, importable, testable -- not only a comment.
DEPTH_EVOLUTION_RESOLUTION = Resolution.UNSUPPORTED_BY_MODEL
```

Then, at the end of the file (after `apply_implant_windows_doping`),
add:

```python
def _normalize_gaussian_terms(region: DopingRegion) -> List[Dict]:
    """A DopingRegion's implant content as a flat term list, regardless
    of whether it already used gaussian_terms (Task 3) or only the
    legacy single-profile fields. Shared by apply_thermal_anneal() here
    and apply_gaussian_implant_doping's existing= path (Task 3) --
    kept as ONE function so the two paths cannot drift apart."""
    if region.gaussian_terms:
        return list(region.gaussian_terms)
    terms = []
    if region.donor_peak_conc_cm3:
        terms.append({
            "species": region.donor_species, "polarity": "donor",
            "peak_conc_cm3": region.donor_peak_conc_cm3,
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    if region.acceptor_peak_conc_cm3:
        terms.append({
            "species": region.acceptor_species, "polarity": "acceptor",
            "peak_conc_cm3": region.acceptor_peak_conc_cm3,
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    if not terms and region.peak_conc_cm3 is not None:
        polarity = "donor" if region.peak_conc_cm3 >= 0 else "acceptor"
        terms.append({
            "species": None, "polarity": polarity,
            "peak_conc_cm3": abs(region.peak_conc_cm3),
            "peak_position_um": region.peak_position_um,
            "straggle_um": region.straggle_um, "thermal_budget_cm2": 0.0,
        })
    return terms


def apply_thermal_anneal(
    result: ProcessResult, temperature_c: float, time_s: float,
) -> ProcessResult:
    """Widen every EXISTING Gaussian implant term by its own species'
    real, cited D(T) (tcad.physics.diffusion_model) -- independently,
    never a species-pair interaction. Dose is conserved per term (see
    tcad.physics.diffusion_model.anneal_profile's docstring for the
    exact formula this reuses).

    Real, honest no-op (returns `result` UNCHANGED, same object) when
    result.doping has no defined Gaussian shape to widen -- this
    function never invents a shape for uniform/step_junction/
    implant_windows doping, which this project has no anneal physics
    for.

    Depth/junction-depth evolution is NOT computed -- see this module's
    own DEPTH_EVOLUTION_RESOLUTION constant.
    """
    if result.doping is None or result.doping.kind != "gaussian_implant":
        return result

    region = result.doping.regions[0]
    terms = _normalize_gaussian_terms(region)
    if not terms:
        return result

    updated_terms = []
    for term in terms:
        if term["species"] is None:
            updated_terms.append(term)
            continue
        contribution = thermal_budget_contribution(
            term["species"], "Si", temperature_c, time_s,
        )
        if contribution.value is None:
            updated_terms.append(term)
            continue
        dt_um2 = contribution.value * 1e8
        old_straggle = term["straggle_um"]
        new_straggle = (old_straggle ** 2 + 2.0 * dt_um2) ** 0.5
        new_peak = term["peak_conc_cm3"] * (old_straggle / new_straggle)
        updated_terms.append({
            "species": term["species"], "polarity": term["polarity"],
            "peak_conc_cm3": new_peak, "peak_position_um": term["peak_position_um"],
            "straggle_um": new_straggle,
            "thermal_budget_cm2": term["thermal_budget_cm2"] + contribution.value,
        })

    new_region = replace(region, gaussian_terms=updated_terms)
    new_doping = DopingProfile(kind="gaussian_implant", regions=[new_region])
    return replace(result, doping=new_doping)
```

Add `List, Dict` to the existing `from typing import Dict, List,
Optional` import line at the top of the file (already imports `Dict`,
confirm `List` is present too — add it if not).

- [ ] **Step 4: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_thermal_anneal_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 5: Run every earlier task's test unchanged**

```bash
../.venv/Scripts/python.exe tests/unit/test_diffusion_model_mock.py
../.venv/Scripts/python.exe tests/unit/test_anneal_profile_mock.py
../.venv/Scripts/python.exe tests/unit/test_gaussian_implant_terms_mock.py
```
Expected: all three pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add tcad/physics/doping.py tests/unit/test_thermal_anneal_mock.py
git commit -m "feat: apply_thermal_anneal -- every existing profile widens by its own species D(T) (Stage B)"
```

---

### Task 5: `WaferState.dopant_profiles` sees every term independently

**Files:**
- Modify: `tcad/physics/dopant_profile.py`
- Test: extend `tests/unit/test_dopant_profile_mock.py` (Stage A's file)

**Interfaces:**
- Consumes: `DopingRegion.gaussian_terms` (Task 3).
- Produces (for Task 7, Task 8): `dopant_profiles_from_doping_profile()`
  (Stage A) gains a branch inside `_gaussian_implant_profiles` — when
  `region.gaussian_terms` is set, returns ONE `DopantProfile` per term
  (each carrying that term's own `peak_conc_cm3`/`peak_position_um`/
  `straggle_um`/`thermal_budget` — the exact fields Task 2 added),
  instead of the legacy single-pair path. When `gaussian_terms` is
  `None`, behavior is BYTE-IDENTICAL to Stage A (the existing legacy
  path, untouched).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_dopant_profile_mock.py` (add this function
and call it from `main()`, alongside the existing Stage A tests —
do not remove or modify any existing test in that file):

```python
def test_gaussian_terms_produce_one_dopant_profile_each():
    """Stage B: multiple implant terms in one region -> multiple
    DopantProfiles, each carrying its OWN species/peak/straggle/
    thermal_budget -- not collapsed into one."""
    doping = DopingProfile(kind="gaussian_implant", regions=[
        DopingRegion(
            region="Si", junction_axis="x",
            peak_position_um=0.0, straggle_um=0.2,  # legacy fields, unused when gaussian_terms is set
            gaussian_terms=[
                {"species": "B", "polarity": "acceptor", "peak_conc_cm3": 1.0e18,
                 "peak_position_um": -1.0, "straggle_um": 0.2, "thermal_budget_cm2": 1.5e-11},
                {"species": "P", "polarity": "donor", "peak_conc_cm3": 2.0e18,
                 "peak_position_um": 1.0, "straggle_um": 0.15, "thermal_budget_cm2": 3.0e-12},
            ],
        ),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 2

    by_species = {p.species: p for p in profiles}
    assert by_species["B"].polarity == "acceptor"
    assert by_species["B"].peak_conc_cm3 == 1.0e18
    assert by_species["B"].peak_position_um == -1.0
    assert by_species["B"].straggle_um == 0.2
    assert by_species["B"].thermal_budget == 1.5e-11
    assert by_species["P"].polarity == "donor"
    assert by_species["P"].thermal_budget == 3.0e-12

    import math
    assert abs(by_species["B"].concentration_at(-1.0, 0.0) - 1.0e18) < 1.0
    assert by_species["B"].concentration_at(-1.0 + 10.0, 0.0) < 1.0e-10  # far from peak
```

Update `main()` in that same file to also call
`test_gaussian_terms_produce_one_dopant_profile_each()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py`
Expected: `AttributeError` or a shape mismatch (the current
`_gaussian_implant_profiles` ignores `gaussian_terms` and falls
through to the legacy peak/position/straggle path, producing profiles
with the WRONG species/values).

- [ ] **Step 3: Update `_gaussian_implant_profiles`**

In `tcad/physics/dopant_profile.py`, replace the existing
`_gaussian_implant_profiles` function body with:

```python
def _gaussian_implant_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.gaussian_terms:
        out: List[DopantProfile] = []
        for term in region.gaussian_terms:
            peak, position, straggle = (
                term["peak_conc_cm3"], term["peak_position_um"], term["straggle_um"],
            )
            out.append(DopantProfile(
                species=term["species"], polarity=term["polarity"],
                concentration_at=lambda x, d, v=peak, p=position, s=straggle:
                    v * _gaussian_shape(x, p, s),
                thermal_budget=term.get("thermal_budget_cm2", 0.0),
                peak_conc_cm3=peak, peak_position_um=position, straggle_um=straggle,
            ))
        return out

    position = region.peak_position_um
    straggle = region.straggle_um
    if region.donor_peak_conc_cm3 is not None or region.acceptor_peak_conc_cm3 is not None:
        donor_peak = region.donor_peak_conc_cm3 or 0.0
        acceptor_peak = region.acceptor_peak_conc_cm3 or 0.0
    else:
        donor_peak, acceptor_peak = _split_net(region.peak_conc_cm3)
    out: List[DopantProfile] = []
    if donor_peak:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor_peak, p=position, s=straggle:
                v * _gaussian_shape(x, p, s),
            peak_conc_cm3=donor_peak, peak_position_um=position, straggle_um=straggle,
        ))
    if acceptor_peak:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor_peak, p=position, s=straggle:
                v * _gaussian_shape(x, p, s),
            peak_conc_cm3=acceptor_peak, peak_position_um=position, straggle_um=straggle,
        ))
    return out
```

(The legacy branch is Stage A's original function body, unchanged —
only the `if region.gaussian_terms:` branch at the top is new, and it
now also sets the Task 2 shape fields on the legacy path's returned
profiles too, so a legacy-path profile can ALSO be re-annealed via
`anneal_profile()` directly against `WaferState.dopant_profiles`
uniformly — this is purely additive and does not change any existing
assertion.)

- [ ] **Step 4: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py`
Expected: all tests (Stage A's five plus this new one) pass.

- [ ] **Step 5: Run Task 4/5/6's WaferState doping test unchanged**

Run: `../.venv/Scripts/python.exe tests/unit/test_wafer_state_doping_mock.py`
Expected: passes unchanged (this task only touched
`_gaussian_implant_profiles`'s internals; `WaferState`'s own
aggregation methods are untouched).

- [ ] **Step 6: Commit**

```bash
git add tcad/physics/dopant_profile.py tests/unit/test_dopant_profile_mock.py
git commit -m "feat: multiple gaussian_implant terms each become their own DopantProfile (Stage B)"
```

---

### Task 6: Real DevSim NetDoping from multiple summed terms

**Files:**
- Modify: `tcad/device/devsim/doping_mapping.py`
- Test: `tests/integration/test_gaussian_implant_terms_devsim_real.py`

**Interfaces:**
- Consumes: `DopingRegion.gaussian_terms` (Task 3).
- Produces: `apply_doping()`'s `"gaussian_implant"` branch, when
  `region_doping.gaussian_terms` is set, builds `Donors` as the SUM of
  every donor-polarity term's own Gaussian expression and `Acceptors`
  as the sum of every acceptor-polarity term's, then `NetDoping =
  Donors - Acceptors` — the SAME Donors/Acceptors/NetDoping pattern
  `"step_junction"` already uses, generalized to N Gaussian terms
  instead of 2 step() terms. When `gaussian_terms` is `None`, the
  existing single-expression branch runs UNCHANGED.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_gaussian_implant_terms_devsim_real.py`,
modeled directly on
`tests/integration/test_dopant_profile_matches_devsim_real.py`
(Stage A's own closing-verification pattern — reuse its
`_fresh_process_result()` shape):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real DevSim proof: two independent Gaussian implant terms (added via
apply_gaussian_implant_doping's existing=, Task 3) sum into ONE real,
solved NetDoping expression -- Donors + Acceptors built from ALL
terms, not just the last one registered.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_gaussian_implant_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask",
}


def _fresh_process_result():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        return build_process_result(step_result)


def main():
    b_implant = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x",
        peak_position_um=-0.8, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    both = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x",
        peak_position_um=0.8, straggle_um=0.15,
        donor_peak_conc_cm3=2.0e18, donor_species="P",
        existing=b_implant,
    )
    assert both.doping.regions[0].gaussian_terms is not None
    assert len(both.doping.regions[0].gaussian_terms) == 2

    imported = import_process_result(
        both, mesh_name="terms_mesh", device_name="terms_device",
        contact_regions=["Si"], contact_axis="x",
    )
    try:
        apply_doping(imported.device, both.doping)

        x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        net_doping = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

        import math
        def expected(x):
            b_term = -1.0e18 * math.exp(-((x - (-0.8)) ** 2) / (2.0 * 0.2 ** 2))
            p_term = 2.0e18 * math.exp(-((x - 0.8) ** 2) / (2.0 * 0.15 ** 2))
            return b_term + p_term

        max_rel_error = 0.0
        n_checked = 0
        for x, actual in zip(x_values, net_doping):
            exp = expected(x)
            denom = max(abs(exp), 1.0)
            max_rel_error = max(max_rel_error, abs(actual - exp) / denom)
            n_checked += 1

        print(f"[1/2] checked {n_checked} nodes, max relative error vs "
              f"independently-summed formula: {max_rel_error:.3e}")
        assert max_rel_error < 1e-6, (
            f"real DevSim NetDoping does not match the sum of both "
            f"implant terms: {max_rel_error}"
        )

        # sign sanity at each peak
        near_b = min(range(len(x_values)), key=lambda i: abs(x_values[i] - (-0.8)))
        near_p = min(range(len(x_values)), key=lambda i: abs(x_values[i] - 0.8))
        assert net_doping[near_b] < 0, "B (acceptor) peak must read net-negative"
        assert net_doping[near_p] > 0, "P (donor) peak must read net-positive"
        print(f"[2/2] B peak reads {net_doping[near_b]:.3e} (acceptor), "
              f"P peak reads {net_doping[near_p]:.3e} (donor)")
    finally:
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    assert devsim.get_device_list() == ()
    print("Two independently-added Gaussian implant terms sum into one "
          "real, solved DevSim NetDoping -- both terms present, neither "
          "overwrote the other.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify it fails**

Run:
```
cd C:/Users/박석훈/PycharmProjects/tcad/tcad
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_gaussian_implant_terms_devsim_real.py
```
Expected: fails the relative-error assertion (today's `apply_doping`
ignores `gaussian_terms` entirely and instead reads whatever the
region's single legacy `peak_conc_cm3`/`peak_position_um`/
`straggle_um` last held, producing only the SECOND (P) implant's own
expression, not the sum of both).

- [ ] **Step 3: Generalize the `gaussian_implant` branch**

In `tcad/device/devsim/doping_mapping.py`, replace the existing
`elif doping.kind == "gaussian_implant":` branch's body with:

```python
    elif doping.kind == "gaussian_implant":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            exclusion_for_region = exclusion
            if region_doping.gaussian_terms:
                donor_terms = []
                acceptor_terms = []
                for term in region_doping.gaussian_terms:
                    position_native = term["peak_position_um"] * length_scale_to_cm
                    straggle_native = term["straggle_um"] * length_scale_to_cm
                    expr = (
                        f"{term['peak_conc_cm3']}*exp(-(({axis}-({position_native}))^2)"
                        f"/(2*({straggle_native})^2))"
                    )
                    if term["polarity"] == "donor":
                        donor_terms.append(expr)
                    else:
                        acceptor_terms.append(expr)
                donors_expr = " + ".join(donor_terms) if donor_terms else "0"
                acceptors_expr = " + ".join(acceptor_terms) if acceptor_terms else "0"
                module.node_model(
                    device=device, region=region_doping.region, name="Donors",
                    equation=f"({donors_expr})",
                )
                module.node_model(
                    device=device, region=region_doping.region, name="Acceptors",
                    equation=f"({acceptors_expr})",
                )
                module.node_model(
                    device=device, region=region_doping.region, name="NetDoping",
                    equation=f"(Donors-Acceptors)*{exclusion_for_region}",
                )
                continue

            position_native = region_doping.peak_position_um * length_scale_to_cm
            straggle_native = region_doping.straggle_um * length_scale_to_cm
            gaussian_expr = (
                f"{region_doping.peak_conc_cm3}*exp(-(({axis}-({position_native}))^2)"
                f"/(2*({straggle_native})^2))"
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({gaussian_expr})*{exclusion_for_region}",
            )
```

(This keeps the ORIGINAL single-expression path completely intact as
the `continue`-free tail of the loop, only reached when
`gaussian_terms` is falsy — byte-identical for every existing caller.)

Update the module's own docstring (the "Real API used here" comment
block) to add one short paragraph describing the new multi-term
Donors/Acceptors path, next to the existing `"gaussian_implant"`
paragraph — mirroring how the docstring already documents
`step_junction`'s Donors/Acceptors pattern.

- [ ] **Step 4: Run the test to verify it passes**

Run the same command as Step 2. Expected: prints both summary lines,
exit 0.

- [ ] **Step 5: Run the existing single-term real regression tests unchanged**

```bash
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_gaussian_implant_doping_real.py
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_dopant_profile_matches_devsim_real.py
```
Expected: both pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add tcad/device/devsim/doping_mapping.py tests/integration/test_gaussian_implant_terms_devsim_real.py
git commit -m "feat: real DevSim NetDoping sums ALL gaussian_implant terms, not just the last (Stage B)"
```

---

### Task 7: Acceptance tests A/B/C — the scenarios this whole stage exists for

**Files:**
- Create: `tests/integration/test_thermal_anneal_acceptance_real.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: nothing consumed by a later task — this is Stage B's
  closing, real-execution proof.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_thermal_anneal_acceptance_real.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage B acceptance tests, exactly as specified during design review:

A: B implant -> anneal
B: B implant -> P implant -> anneal
C: B implant -> anneal -> P implant -> anneal

For each: no profile is destroyed, B and P use independently-different
D(T), anneal reaches every currently-existing profile, dose is
conserved, and changing temperature/time produces a different real
result. C's own final anneal must move BOTH the original B profile
(already annealed once) and the newly-added P profile.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_gaussian_implant_doping, apply_thermal_anneal
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask",
}


def _fresh_process_result():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        return build_process_result(step_result)


def _dose(term):
    return term["peak_conc_cm3"] * term["straggle_um"] * math.sqrt(2.0 * math.pi)


def _by_species(result):
    return {t["species"]: t for t in result.doping.regions[0].gaussian_terms}


def scenario_A():
    b_implant = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    b_dose_before = b_implant.doping.regions[0].acceptor_peak_conc_cm3 * 0.2 * math.sqrt(2.0 * math.pi)

    annealed = apply_thermal_anneal(b_implant, temperature_c=900.0, time_s=600.0)
    b = _by_species(annealed)["B"]

    assert b["straggle_um"] > 0.2, "[A] B must broaden"
    assert abs(_dose(b) - b_dose_before) / b_dose_before < 1e-6, "[A] dose must be conserved"
    print(f"[A] B implant -> anneal: straggle 0.200 -> {b['straggle_um']:.4f} um, "
          f"dose conserved to {abs(_dose(b) - b_dose_before) / b_dose_before:.2e}")


def scenario_B():
    b_implant = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    both = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
        existing=b_implant,
    )
    annealed = apply_thermal_anneal(both, temperature_c=900.0, time_s=600.0)
    terms = _by_species(annealed)

    assert "B" in terms and "P" in terms, "[B] neither profile may be destroyed"
    assert terms["B"]["straggle_um"] > 0.2, "[B] B must broaden"
    assert terms["P"]["straggle_um"] > 0.2, "[B] P must broaden"
    assert abs(terms["B"]["straggle_um"] - terms["P"]["straggle_um"]) > 1e-6, (
        "[B] B and P must broaden by DIFFERENT amounts (different D(T))"
    )
    print(f"[B] B implant -> P implant -> anneal: both present, "
          f"B={terms['B']['straggle_um']:.4f}um P={terms['P']['straggle_um']:.4f}um")


def scenario_C():
    b_implant = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    )
    b_annealed_once = apply_thermal_anneal(b_implant, temperature_c=900.0, time_s=600.0)
    b_straggle_after_first_anneal = _by_species(b_annealed_once)["B"]["straggle_um"]

    both = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
        existing=b_annealed_once,
    )
    final = apply_thermal_anneal(both, temperature_c=900.0, time_s=600.0)
    terms = _by_species(final)

    assert "B" in terms and "P" in terms, "[C] neither profile may be destroyed"
    assert terms["B"]["straggle_um"] > b_straggle_after_first_anneal, (
        "[C] the FINAL anneal must widen B FURTHER, beyond its own first anneal -- "
        f"got {terms['B']['straggle_um']} vs {b_straggle_after_first_anneal} after anneal 1 alone"
    )
    assert terms["P"]["straggle_um"] > 0.2, "[C] P (introduced after B's first anneal) must also broaden"
    print(f"[C] B implant -> anneal -> P implant -> anneal: B widened across "
          f"BOTH anneals ({0.2:.4f} -> {b_straggle_after_first_anneal:.4f} -> "
          f"{terms['B']['straggle_um']:.4f} um), P widened by the final anneal alone "
          f"({0.2:.4f} -> {terms['P']['straggle_um']:.4f} um)")


def scenario_temperature_dependence():
    implant = apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    )
    low = apply_thermal_anneal(implant, temperature_c=900.0, time_s=600.0)
    high = apply_thermal_anneal(implant, temperature_c=1000.0, time_s=600.0)
    low_s = _by_species(low)["P"]["straggle_um"]
    high_s = _by_species(high)["P"]["straggle_um"]
    assert high_s != low_s
    assert high_s > low_s
    print(f"[T] 900C/10min -> {low_s:.4f}um, 1000C/10min -> {high_s:.4f}um "
          f"(same duration, different T -- genuinely different results)")


def main():
    scenario_A()
    scenario_B()
    scenario_C()
    scenario_temperature_dependence()
    print("\nAll Stage B acceptance scenarios (A/B/C + temperature "
          "dependence) verified against real physics: no profile "
          "destroyed, independent species D(T), every existing "
          "profile reached by anneal, dose conserved, and a later "
          "anneal continues to affect an earlier profile.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against real ViennaPS + DevSim**

```bash
cd C:/Users/박석훈/PycharmProjects/tcad/tcad
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_thermal_anneal_acceptance_real.py
```

Expected: all four scenario print lines, then the summary line, exit 0.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_thermal_anneal_acceptance_real.py
git commit -m "test: Stage B acceptance scenarios A/B/C + temperature dependence, real ViennaPS+DevSim"
```

---

### Task 8: GUI — implant accumulates, a real Anneal control, an observable effect

**Files:**
- Modify: `tcad_2d_stagewise.py`
- Test: `tests/integration/test_gui_thermal_anneal_real.py` (real
  ViennaPS is needed to materialize a real mesh before `run_doping()`
  will build a `ProcessResult` — this cannot be a `tests/unit/` mock
  test; `devsim` is not needed by anything this task touches, but the
  test still checks for it, matching
  `test_gui_doping_donor_acceptor_real.py`'s own established
  convention for this exact panel).

**Interfaces:**
- Consumes: `apply_gaussian_implant_doping`'s `existing=` (Task 3),
  `apply_thermal_anneal` (Task 4).
- Produces: `run_doping()`'s existing `elif kind == "Gaussian Implant":`
  branch (`tcad_2d_stagewise.py:4050-4072`) now passes `existing=`,
  so a second Gaussian Implant click adds a term instead of replacing
  the wafer's doping state. A new "ANNEAL" control (temperature/time
  fields + button), placed in `_make_doping_panel()` alongside the
  existing SiO2-barrier field and the APPLY DOPING button (i.e.
  outside every per-kind frame, since anneal is not itself a doping
  kind — it acts on whatever doping already exists), calls
  `apply_thermal_anneal(self.last_doped_result, T, t)`, updates
  `self.last_doped_result`, and logs the real before/after
  `peak_conc_cm3`/`straggle_um` for every term.

- [ ] **Step 1: Wire `existing=` into the Gaussian Implant branch**

In `tcad_2d_stagewise.py`, `run_doping()`, replace the
`elif kind == "Gaussian Implant":` block's call (currently
`tcad_2d_stagewise.py:4060-4065`) with:

```python
            elif kind == "Gaussian Implant":

                region = self.dope_gauss_region_var.get()
                axis = self.dope_gauss_axis_var.get()
                position = float(self.dope_gauss_position_var.get())
                straggle = float(self.dope_gauss_straggle_var.get())
                donor = float(self.dope_gauss_donor_var.get())
                acceptor = float(self.dope_gauss_acceptor_var.get())
                donor_species = self.dope_gauss_donor_species_var.get()
                acceptor_species = self.dope_gauss_acceptor_species_var.get()
                accumulate = (
                    self.last_doped_result is not None
                    and (self.last_doped_result.doping is None
                         or self.last_doped_result.doping.kind == "gaussian_implant")
                )
                if self.last_doped_result is not None and not accumulate:
                    self._log(
                        "GAUSSIAN IMPLANT: the wafer's current doping is a "
                        f"different kind ({self.last_doped_result.doping.kind!r}) "
                        "-- this implant replaces it rather than superposing "
                        "(adding a term on top of a different doping kind's "
                        "representation is not supported)."
                    )
                doped_result = apply_gaussian_implant_doping(
                    process_result, region=region, junction_axis=axis,
                    peak_position_um=position, straggle_um=straggle,
                    donor_peak_conc_cm3=donor, acceptor_peak_conc_cm3=acceptor,
                    donor_species=donor_species, acceptor_species=acceptor_species,
                    existing=self.last_doped_result if accumulate else None,
                )
                n_terms = len(doped_result.doping.regions[0].gaussian_terms or [1])
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"peak@{position}um straggle={straggle}um "
                    f"donor={donor:.3e}({donor_species}) "
                    f"acceptor={acceptor:.3e}({acceptor_species}) -> "
                    f"peak_net_cm3={donor - acceptor:.3e} "
                    f"({n_terms} implant term(s) now on this wafer)"
                )
```

(Only the `accumulate` computation, the `existing=` argument, the
pre-implant log note, and the `n_terms` addition to `summary` are new;
every other line is unchanged from the current block.)

- [ ] **Step 2: Add the ANNEAL fields and button**

In `_make_doping_panel()`, immediately after the existing
`self.dope_barrier_threshold_var = self._field(frame, "SiO2 barrier
min thickness (µm)", 0.0)` block (`tcad_2d_stagewise.py:3945-3947`)
and before the `self.doping_button = ttk.Button(...)` block, add:

```python
        ttk.Label(
            frame,
            text="Anneal (widens every existing Gaussian implant term "
                 "by its own species' real D(T) -- see Christensen et "
                 "al. 2003)",
            style="Caption.TLabel",
            wraplength=310,
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 1),
        )
        self.anneal_temp_var = self._field(
            frame, "Anneal temperature (°C)", 900.0,
        )
        self.anneal_time_var = self._field(
            frame, "Anneal time (s)", 600.0,
        )
        self.anneal_button = ttk.Button(
            frame,
            text="ANNEAL",
            style="Run.TButton",
            command=self._on_thermal_anneal_clicked,
        )
        self.anneal_button.pack(
            fill="x",
            padx=12,
            pady=(3, 3),
        )
```

- [ ] **Step 3: Write the ANNEAL click handler**

In `tcad_2d_stagewise.py`, add a new method right after `run_doping()`
(i.e., immediately before `def _make_measurement_panel(`):

```python
    def _on_thermal_anneal_clicked(self):
        """Widens every existing Gaussian implant TERM (Task 4/plan
        Stage B) by its own species' real, cited D(T) -- see
        tcad.physics.diffusion_model. A real, honest no-op (logged, not
        silent) when the current doping has no defined Gaussian shape."""

        if self.last_doped_result is None or self.last_doped_result.doping is None:
            self._log("ANNEAL: no doping applied yet -- nothing to anneal.")
            return

        try:
            temperature_c = float(self.anneal_temp_var.get())
            time_s = float(self.anneal_time_var.get())
        except ValueError:
            messagebox.showerror(
                "Anneal",
                "Temperature and time must be numeric.",
            )
            return

        before = self.last_doped_result
        after = apply_thermal_anneal(before, temperature_c, time_s)

        if after is before:
            self._log(
                f"ANNEAL: {temperature_c:.0f} C / {time_s:.0f} s -- current "
                f"doping ({before.doping.kind!r}) has no defined Gaussian "
                f"shape to anneal; nothing changed."
            )
            return

        self.last_doped_result = after
        before_by_species = {
            t["species"]: t for t in (before.doping.regions[0].gaussian_terms or [])
        }
        after_terms = after.doping.regions[0].gaussian_terms

        self._log(
            f"\n================================\n"
            f"ANNEAL: {temperature_c:.0f} C / {time_s:.0f} s\n"
            f"================================\n"
            f"Applied to {len(after_terms)} existing implant term(s):"
        )
        for term in after_terms:
            before_term = before_by_species.get(term["species"])
            before_straggle = before_term["straggle_um"] if before_term else term["straggle_um"]
            before_peak = before_term["peak_conc_cm3"] if before_term else term["peak_conc_cm3"]
            self._log(
                f"  {term['species'] or '(unlabeled)'} ({term['polarity']}): "
                f"straggle {before_straggle:.4f} -> {term['straggle_um']:.4f} um, "
                f"peak {before_peak:.3e} -> {term['peak_conc_cm3']:.3e} cm^-3"
            )

        self._update_process_buttons()
```

Add `apply_thermal_anneal` to the existing
`from tcad.physics.doping import (apply_uniform_doping,
apply_step_junction_doping, apply_gaussian_implant_doping,
apply_implant_windows_doping)`-style import block near the top of the
file (the exact existing import list is at `tcad_2d_stagewise.py:60-64`
— add `apply_thermal_anneal` to it, alphabetically or matching the
existing list's own order).

- [ ] **Step 4: Write the test**

Create `tests/integration/test_gui_thermal_anneal_real.py`, following
`tests/integration/test_gui_doping_donor_acceptor_real.py`'s own
established setup (same SKIPPED-on-missing-Tk/ViennaPS/DevSim pattern,
same `app.withdraw()` + `app._materialize_current_wafer()` +
`app.grid_var.set(0.2)` real-mesh setup):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI: two Gaussian Implant clicks accumulate into two independent
DopantProfile terms on the real wafer state, and ANNEAL widens both --
by their own, DIFFERENT species' real D(T) -- with the change directly
observable in the log. Real TCADApplication (window withdrawn), real
ViennaPS.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    try:
        import tkinter  # noqa: F401
        import tcad_2d_stagewise as gui

        app = gui.TCADApplication()
    except Exception as exc:
        print(f"SKIPPED: no usable Tk display ({exc!r})")
        return

    from tcad.backends.viennaps import session as viennaps_session
    if not viennaps_session.is_available():
        app.destroy()
        print("SKIPPED: ViennaPS is not installed")
        return

    try:
        app.withdraw()
        app.update_idletasks()
        app.grid_var.set(0.2)

        ok = app._materialize_current_wafer()
        assert ok, "materializing a real ViennaPS wafer failed"

        # First implant: B (acceptor)
        app.doping_kind.set("Gaussian Implant")
        app.dope_gauss_region_var.set("Si")
        app.dope_gauss_axis_var.set("x")
        app.dope_gauss_position_var.set(-1.0)
        app.dope_gauss_straggle_var.set(0.2)
        app.dope_gauss_donor_var.set(0.0)
        app.dope_gauss_acceptor_var.set(1.0e18)
        app.dope_gauss_donor_species_var.set("")
        app.dope_gauss_acceptor_species_var.set("B")
        assert app.run_doping(silent=True)
        after_first = app.last_doped_result.doping.regions[0].gaussian_terms
        assert len(after_first) == 1
        print(f"[1/4] first implant (B) applied: {len(after_first)} term")

        # Second implant: P (donor) -- must ADD, not replace
        app.dope_gauss_position_var.set(1.0)
        app.dope_gauss_straggle_var.set(0.15)
        app.dope_gauss_donor_var.set(2.0e18)
        app.dope_gauss_acceptor_var.set(0.0)
        app.dope_gauss_donor_species_var.set("P")
        app.dope_gauss_acceptor_species_var.set("")
        assert app.run_doping(silent=True)
        terms = app.last_doped_result.doping.regions[0].gaussian_terms
        species_present = {t["species"] for t in terms}
        assert species_present == {"B", "P"}, (
            f"second implant must ADD a term, not replace -- got species "
            f"{species_present}"
        )
        print(f"[2/4] second implant (P) added: both B and P present, "
              f"{len(terms)} terms total")

        straggle_before = {t["species"]: t["straggle_um"] for t in terms}

        # Anneal -- must widen BOTH, by DIFFERENT amounts (real, different D(T))
        app.anneal_temp_var.set(900.0)
        app.anneal_time_var.set(600.0)
        app._on_thermal_anneal_clicked()

        terms_after = app.last_doped_result.doping.regions[0].gaussian_terms
        straggle_after = {t["species"]: t["straggle_um"] for t in terms_after}

        assert straggle_after["B"] > straggle_before["B"], "B must broaden"
        assert straggle_after["P"] > straggle_before["P"], "P must broaden"
        assert abs(straggle_after["B"] - straggle_after["P"]) > 1e-6, (
            "B and P must broaden by DIFFERENT amounts (different real D(T))"
        )
        print(f"[3/4] ANNEAL widened both: "
              f"B {straggle_before['B']:.4f}->{straggle_after['B']:.4f} um, "
              f"P {straggle_before['P']:.4f}->{straggle_after['P']:.4f} um")

        # The change must be OBSERVABLE in the log -- both species' real numbers.
        log_text = app.log.get("1.0", "end")
        assert "B (acceptor)" in log_text and "P (donor)" in log_text
        assert f"{straggle_after['B']:.4f}" in log_text
        assert f"{straggle_after['P']:.4f}" in log_text
        print("[4/4] both species' before/after straggle values are in the real log")

        print("\nGUI: Gaussian Implant clicks accumulate real DopantProfile "
              "terms on the wafer, and ANNEAL produces a real, "
              "species-dependent, log-observable physical change.")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run it against real ViennaPS**

```bash
cd C:/Users/박석훈/PycharmProjects/tcad/tcad
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_gui_thermal_anneal_real.py
```
Expected: all four `[n/4]` lines print, then the summary, exit 0 (or a
`SKIPPED:` line if this environment has no usable Tk display — treat
that the same way this project's other `_real.py` GUI tests already
do, per that convention).

- [ ] **Step 6: Run the existing GUI regression tests unchanged**

```bash
../.venv/Scripts/python.exe tests/unit/test_gui_no_forced_order_mock.py
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_gui_doping_donor_acceptor_real.py
```
Expected: both pass unchanged. `test_gui_doping_donor_acceptor_real.py`
DOES exercise Gaussian Implant (its own lines ~144-174), but it runs
Uniform doping FIRST — so `self.last_doped_result.doping.kind ==
"uniform"` when the Gaussian Implant click happens, `accumulate`
evaluates `False`, and `existing=None` is passed, taking the exact
byte-identical legacy path Step 1 preserves. That test's own
assertions all read the legacy `peak_conc_cm3`/`donor_peak_conc_cm3`/
`acceptor_peak_conc_cm3`/`donor_species`/`acceptor_species` fields
directly, none of which this task's changes touch.

- [ ] **Step 7: Commit**

```bash
git add tcad_2d_stagewise.py tests/integration/test_gui_thermal_anneal_real.py
git commit -m "feat: GUI implant accumulates via existing=, real ANNEAL control with observable per-species effect (Stage B)"
```

---

## Deferred to Stage B2 (not this plan)

- `apply_thermal_diffusion_doping()` — a NEW dopant introduced from an
  external constant/limited source (POCl3-style predep), erfc-shaped,
  masked by real oxide thickness (`WaferState.thickness_of`, which
  does not exist yet either — `WaferState` currently has no
  `thickness_of(material, x)` method, only `exposed_material_at`/
  `exposed_materials`/`under_resolved_x`; adding it is Stage B2's own
  first task, not silently assumed here).
- Oxide-diffusion-barrier physics and ion-implant-through-oxide
  stopping/straggle — two separate mechanisms, neither touched by this
  plan (see Global Constraints).
- Depth/junction-depth evolution — `DEPTH_EVOLUTION_RESOLUTION =
  Resolution.UNSUPPORTED_BY_MODEL` (Task 4) records this honestly;
  actually computing it is future work.
- Superposing `gaussian_implant` terms on top of a DIFFERENT existing
  doping kind (`uniform`/`step_junction`/`implant_windows`) — Task 3's
  `existing=` deliberately raises rather than guessing at a cross-kind
  interaction.

## Stage B completion criteria

1. All eight tasks above committed.
2. Full project regression (`tests/run_regression.py`, controller-run,
   bounded timeout) — same pass/fail counts as the pre-Stage-B baseline
   (72 passed / 3 pre-existing failures / 0 skipped as of Stage A's own
   close, plus this plan's new tests, all passing) — zero new failures,
   zero changed existing-test values.
3. A CLAUDE.md Completed-section note, mirroring Stage A's own entry,
   once the whole-branch review for this stage is clean.

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-09-02-state-dependent-physics-stage-b.md`.
Two execution options:

**1. Subagent-Driven (recommended)** - fresh subagent per task, review
between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session, batch
execution with checkpoints

**Which approach?**
