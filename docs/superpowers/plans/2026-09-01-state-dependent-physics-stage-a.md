# State-Dependent Physics — Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `WaferState` a species-preserving doping query surface
(`DopantProfile`, `donor_concentration_at`, `acceptor_concentration_at`,
`net_doping_at`) without changing a single existing test's behavior or
expected value — pure plumbing, the smallest and lowest-risk stage of
the state-dependent-physics design.

**Architecture:** A new module, `tcad/physics/dopant_profile.py`,
converts the EXISTING `DopingProfile`/`DopingRegion` shape (unchanged)
into a new, position-queryable `DopantProfile` per species/polarity.
`WaferState` gains an optional `dopant_profiles` field and three query
methods that read it. **Nothing in `tcad/device/devsim/doping_mapping.py`
or `tcad/device/devsim/mesh_import.py` changes** — investigation during
planning found `DopingRegion` already preserves donor/acceptor/species
separately (shipped by the prior "litho/doping/renderer" plan) and
`doping_mapping.py` already builds DevSim's NetDoping directly from
that, so there is no existing behavior to migrate and nothing to touch
there. This is narrower than the design doc's own §8 migration-table
wording implied at spec-writing time ("device-layer NetDoping
conversion moved to read from it") — that sentence is superseded by
this finding; the actual Stage A deliverable is additive-only.

**Tech Stack:** Python dataclasses (no new dependency). Task 3 uses
the project's existing real ViennaPS 4.6.2 + DevSim integration-test
pattern (`tests/integration/test_implant_windows_doping_real.py` is
the closest existing example and this plan's Task 3 follows its shape
directly).

**Spec:** `docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md`
(§2 "Doping state: process layer keeps species and polarity" — this
plan implements exactly and only that section, nothing from §1/§3/§4).
Base design: `docs/superpowers/specs/2026-08-25-wafer-state-physics-design.md`.

## Global Constraints

- **Zero physics-behavior change.** Every existing test's numeric
  assertions must remain byte-identical. This stage adds a new,
  currently-uncalled query surface; it does not change what any
  existing code path computes.
- **No changes to `tcad/device/devsim/doping_mapping.py`,
  `tcad/device/devsim/mesh_import.py`, or any `apply_*_doping()`
  function in `tcad/physics/doping.py`.** Confirmed unnecessary by
  investigation (see Architecture above); touching them would violate
  CLAUDE.md's Development Rules ("do not refactor unrelated code",
  "never change code just to make a test pass").
- **`WaferState` stays a frozen, immutable query** (per the base
  design's own §1) — the new field is added with a default so the one
  existing caller (`tcad/process/etching/isotropic.py:72`,
  `WaferState.query(geometry)`) is completely unaffected.
- Process-layer/device-layer separation (spec §2): `DopantProfile`
  never computes or stores a signed net value as primary state —
  `net_doping_at` is always a derived, on-demand combination of
  separately-tracked donor and acceptor magnitudes.
- Test convention: `def main(): ... assert ...` +
  `if __name__ == "__main__": main()`, not pytest. `tests/unit/` for
  pure-Python (no backend) tests, `tests/integration/` (suffix
  `_real.py`) for real ViennaPS+DevSim tests. Both directories are
  auto-discovered by `tests/run_regression.py` via `glob("test_*.py")`
  — no registration needed.
- Real backends: `PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE`
  env vars, project venv at `../.venv/Scripts/python.exe` (one level
  above the repo root).

---

### Task 1: `DopantProfile` + conversion from the existing `DopingProfile`

**Files:**
- Create: `tcad/physics/dopant_profile.py`
- Test: `tests/unit/test_dopant_profile_mock.py`

**Interfaces:**
- Consumes: `tcad.mesh.interface.DopingProfile`, `DopingRegion` (existing,
  unchanged — see field list in that file); `tcad.physics.values.Source`
  (existing, unchanged).
- Produces (for Task 2 and Task 3):
  - `DopantProfile` frozen dataclass: `species: Optional[str]`,
    `polarity: str` (`"donor"` or `"acceptor"`), `concentration_at:
    Callable[[float, float], float]` (signature `(x_um, depth_um) ->
    cm^-3`, always >= 0), `thermal_budget: float = 0.0`,
    `source: Optional[Source] = None`.
  - `dopant_profiles_from_doping_profile(doping: DopingProfile) ->
    Tuple[DopantProfile, ...]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dopant_profile_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DopantProfile: a lossless, species-preserving adapter over the
existing DopingProfile/DopingRegion shape -- no ViennaPS/DevSim needed,
pure Python math, checked against hand-computed expected values."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import DopingProfile, DopingRegion
from tcad.physics.dopant_profile import (
    DopantProfile,
    dopant_profiles_from_doping_profile,
)


def test_uniform_net_only_splits_by_sign():
    """No donor/acceptor split known -> the project's own documented
    convention (positive net = donor, negative net = acceptor) applies,
    and only ONE polarity's profile is produced -- never an invented
    opposite-polarity value that was never there."""
    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=1.0e17),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    assert profiles[0].polarity == "donor"
    assert profiles[0].species is None
    assert profiles[0].concentration_at(0.0, 0.0) == 1.0e17
    assert profiles[0].thermal_budget == 0.0

    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=-2.0e16),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    assert profiles[0].polarity == "acceptor"
    assert profiles[0].concentration_at(5.0, 0.0) == 2.0e16


def test_uniform_donor_acceptor_split_preserves_both():
    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=5.0e15,
                     donor_conc_cm3=1.0e16, acceptor_conc_cm3=5.0e15,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    assert len(profiles) == 2
    assert by_polarity["donor"].species == "P"
    assert by_polarity["donor"].concentration_at(0.0, 0.0) == 1.0e16
    assert by_polarity["acceptor"].species == "B"
    assert by_polarity["acceptor"].concentration_at(0.0, 0.0) == 5.0e15


def test_step_junction_matches_devsim_step_function():
    """Reproduces doping_mapping.py's real DevSim equations exactly,
    INCLUDING the boundary quirk: at x == junction_position_um, both
    step() calls fire (DevSim's step(z) is 1.0 for z >= 0), so both
    donor and acceptor profiles are non-zero there. This is existing,
    already-shipped DevSim behavior -- not something this module may
    round away."""
    doping = DopingProfile(kind="step_junction", regions=[
        DopingRegion(region="Si", junction_axis="x", junction_position_um=1.0,
                     donor_conc_cm3=1.0e18, acceptor_conc_cm3=2.0e18,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    donor, acceptor = by_polarity["donor"], by_polarity["acceptor"]

    assert donor.concentration_at(2.0, 0.0) == 1.0e18   # right of junction: donor side
    assert donor.concentration_at(0.0, 0.0) == 0.0       # left of junction: no donor
    assert acceptor.concentration_at(0.0, 0.0) == 2.0e18
    assert acceptor.concentration_at(2.0, 0.0) == 0.0
    # boundary quirk, exactly matching DevSim's own step():
    assert donor.concentration_at(1.0, 0.0) == 1.0e18
    assert acceptor.concentration_at(1.0, 0.0) == 2.0e18


def test_gaussian_implant_donor_acceptor_share_shape():
    doping = DopingProfile(kind="gaussian_implant", regions=[
        DopingRegion(region="Si", junction_axis="x",
                     peak_position_um=0.0, straggle_um=0.5,
                     donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=3.0e17,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    import math
    expected_shape = math.exp(-((1.0 - 0.0) ** 2) / (2.0 * 0.5 ** 2))
    assert abs(by_polarity["donor"].concentration_at(1.0, 0.0)
               - 2.0e18 * expected_shape) < 1.0
    assert abs(by_polarity["acceptor"].concentration_at(1.0, 0.0)
               - 3.0e17 * expected_shape) < 1.0
    # peak value at the peak position
    assert abs(by_polarity["donor"].concentration_at(0.0, 0.0) - 2.0e18) < 1.0


def test_implant_windows_background_plus_windows():
    doping = DopingProfile(kind="implant_windows", regions=[
        DopingRegion(region="Si", junction_axis="x",
                     donor_conc_cm3=1.0e15, acceptor_conc_cm3=1.0e16,
                     net_doping_cm3=1.0e15 - 1.0e16,
                     implant_windows=[
                         {"min_um": -1.6, "max_um": -0.6,
                          "donor_conc_cm3": 1.0e20, "acceptor_conc_cm3": 0.0,
                          "conc_cm3": 1.0e20},
                     ]),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    # inside the window: background + window contribution
    assert by_polarity["donor"].concentration_at(-1.1, 0.0) == 1.0e15 + 1.0e20
    # outside the window: background only
    assert by_polarity["donor"].concentration_at(2.0, 0.0) == 1.0e15
    assert by_polarity["acceptor"].concentration_at(-1.1, 0.0) == 1.0e16


def test_unknown_kind_raises():
    doping = DopingProfile(kind="not_a_real_kind", regions=[
        DopingRegion(region="Si", net_doping_cm3=1.0),
    ])
    try:
        dopant_profiles_from_doping_profile(doping)
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def main():
    test_uniform_net_only_splits_by_sign()
    test_uniform_donor_acceptor_split_preserves_both()
    test_step_junction_matches_devsim_step_function()
    test_gaussian_implant_donor_acceptor_share_shape()
    test_implant_windows_background_plus_windows()
    test_unknown_kind_raises()
    print("DopantProfile conversion matches doping_mapping.py's real "
          "DevSim equations for all 4 doping kinds, in both net-only "
          "and donor/acceptor-split input forms.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py`
Expected: `ModuleNotFoundError: No module named 'tcad.physics.dopant_profile'`

- [ ] **Step 3: Write the implementation**

Create `tcad/physics/dopant_profile.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DopantProfile -- the process-layer, species-preserving doping
representation WaferState reads.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md,
section 2: DevSim's NetDoping is a device-layer concept, built exactly
once, only inside tcad/device/devsim/doping_mapping.py -- unchanged by
this module. Nothing upstream of that boundary computes or stores a
plain signed net value as ITS primary representation; a DopantProfile
keeps species and polarity (donor vs acceptor) separate for as long as
possible. A combined net value is always a DERIVED query
(WaferState.net_doping_at, added in a later task), never stored here.

dopant_profiles_from_doping_profile() is a pure, lossless adapter over
the EXISTING tcad.mesh.interface.DopingProfile/DopingRegion shape --
it does not replace that shape. doping_mapping.py, the GUI, and every
existing doping kind keep using DopingRegion exactly as they do today;
this module exists only so WaferState (which has never carried doping
information at all, deliberately, per the base wafer-state design) can
gain a doping query surface without touching the already-verified
DevSim NetDoping construction path.

Two things this module deliberately does NOT model, both belonging to
the DEVICE layer rather than the declared process-layer profile:
window_scale (doping_mapping.apply_doping's continuation-ramp
multiplier -- a solve-strategy detail, not part of what the process
declares) and barrier-covered-window exclusion (derived from the real
mesh at DevSim import time, not from the DopingProfile alone).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from tcad.mesh.interface import DopingProfile, DopingRegion
from tcad.physics.values import Source


@dataclass(frozen=True)
class DopantProfile:
    """One species' concentration magnitude, as a real function of
    position -- always >= 0; sign/polarity is a separate field, never
    folded into the returned value.

    species : chemical identity ("P", "B", "As", ...) when the
        originating DopingRegion carried a donor_species/acceptor_species
        label; None otherwise. Never invented.
    polarity : "donor" or "acceptor".
    concentration_at : (x_um, depth_um) -> cm^-3, magnitude only.
        depth_um is accepted for interface symmetry with the base
        design's thickness_of(material, x) shape, but every doping kind
        this module converts is defined along one lateral axis only --
        depth_um is unused by every concentration_at built here today.
    thermal_budget : cumulative D*t (cm^2) this profile has experienced.
        Always 0.0 out of this module; no process in this project's
        registry contributes to it yet (Stage B, not this stage).
    source : provenance, when known. None for every existing caller.
    """

    species: Optional[str]
    polarity: str
    concentration_at: Callable[[float, float], float]
    thermal_budget: float = 0.0
    source: Optional[Source] = None


def _step(z: float) -> float:
    """DevSim's own step(): 1.0 for z >= 0, else 0.0 -- reproduced
    here (not imported; DevSim's step() is a symbolic equation-string
    function evaluated by DevSim's own solver, not a Python callable)
    so this matches tcad.device.devsim.doping_mapping.apply_doping()'s
    real DevSim equations node-for-node, including the boundary case."""
    return 1.0 if z >= 0.0 else 0.0


def _gaussian_shape(x_um: float, position_um: float, straggle_um: float) -> float:
    return math.exp(-((x_um - position_um) ** 2) / (2.0 * straggle_um ** 2))


def _split_net(net: Optional[float]) -> Tuple[float, float]:
    """This project's own documented sign convention (positive net =
    donor, negative net = acceptor) applied to recover a single
    polarity's magnitude when no explicit donor/acceptor split exists.
    Never produces a non-zero value for BOTH polarities from one net
    number -- that would invent data that was never supplied."""
    value = net or 0.0
    return (max(value, 0.0), max(-value, 0.0))


def dopant_profiles_from_doping_profile(
    doping: DopingProfile,
) -> Tuple[DopantProfile, ...]:
    """Convert an EXISTING DopingProfile into DopantProfiles.

    Lossless wherever a DopingRegion carries a real donor/acceptor
    split (every existing doping kind supports this). Falls back to
    _split_net() only where a caller used the original net-only input
    form.
    """
    profiles: List[DopantProfile] = []
    for region in doping.regions:
        if doping.kind == "uniform":
            profiles.extend(_uniform_profiles(region))
        elif doping.kind == "step_junction":
            profiles.extend(_step_junction_profiles(region))
        elif doping.kind == "gaussian_implant":
            profiles.extend(_gaussian_implant_profiles(region))
        elif doping.kind == "implant_windows":
            profiles.extend(_implant_windows_profiles(region))
        else:
            raise NotImplementedError(
                f"dopant_profiles_from_doping_profile supports kind in "
                f"('uniform', 'step_junction', 'gaussian_implant', "
                f"'implant_windows') so far, got {doping.kind!r}"
            )
    return tuple(profiles)


def _uniform_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.donor_conc_cm3 is not None or region.acceptor_conc_cm3 is not None:
        donor_mag = region.donor_conc_cm3 or 0.0
        acceptor_mag = region.acceptor_conc_cm3 or 0.0
    else:
        donor_mag, acceptor_mag = _split_net(region.net_doping_cm3)
    out: List[DopantProfile] = []
    if donor_mag:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor_mag: v,
        ))
    if acceptor_mag:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor_mag: v,
        ))
    return out


def _step_junction_profiles(region: DopingRegion) -> List[DopantProfile]:
    position = region.junction_position_um
    donor = region.donor_conc_cm3 or 0.0
    acceptor = region.acceptor_conc_cm3 or 0.0
    out: List[DopantProfile] = []
    if donor:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=lambda x, d, v=donor, p=position: v * _step(x - p),
        ))
    if acceptor:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor, p=position: v * _step(p - x),
        ))
    return out


def _gaussian_implant_profiles(region: DopingRegion) -> List[DopantProfile]:
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
        ))
    if acceptor_peak:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=lambda x, d, v=acceptor_peak, p=position, s=straggle:
                v * _gaussian_shape(x, p, s),
        ))
    return out


def _implant_windows_profiles(region: DopingRegion) -> List[DopantProfile]:
    if region.donor_conc_cm3 is not None or region.acceptor_conc_cm3 is not None:
        bg_donor = region.donor_conc_cm3 or 0.0
        bg_acceptor = region.acceptor_conc_cm3 or 0.0
    else:
        bg_donor, bg_acceptor = _split_net(region.net_doping_cm3)

    donor_windows: List[Tuple[float, float, float]] = []
    acceptor_windows: List[Tuple[float, float, float]] = []
    for window in region.implant_windows or []:
        if "donor_conc_cm3" in window or "acceptor_conc_cm3" in window:
            d = window.get("donor_conc_cm3", 0.0)
            a = window.get("acceptor_conc_cm3", 0.0)
        else:
            d, a = _split_net(window.get("conc_cm3"))
        if d:
            donor_windows.append((window["min_um"], window["max_um"], d))
        if a:
            acceptor_windows.append((window["min_um"], window["max_um"], a))

    out: List[DopantProfile] = []
    if bg_donor or donor_windows:
        out.append(DopantProfile(
            species=region.donor_species, polarity="donor",
            concentration_at=_windowed_sum(bg_donor, donor_windows),
        ))
    if bg_acceptor or acceptor_windows:
        out.append(DopantProfile(
            species=region.acceptor_species, polarity="acceptor",
            concentration_at=_windowed_sum(bg_acceptor, acceptor_windows),
        ))
    return out


def _windowed_sum(
    background: float,
    windows: List[Tuple[float, float, float]],
) -> Callable[[float, float], float]:
    def f(x_um: float, depth_um: float) -> float:
        total = background
        for lo, hi, mag in windows:
            total += mag * _step(x_um - lo) * _step(hi - x_um)
        return total
    return f
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_dopant_profile_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 5: Commit**

```bash
git add tcad/physics/dopant_profile.py tests/unit/test_dopant_profile_mock.py
git commit -m "feat: DopantProfile -- species-preserving doping adapter (Stage A, state-dependent physics)"
```

---

### Task 2: `WaferState` doping query surface

**Files:**
- Modify: `tcad/physics/wafer_state.py`
- Test: `tests/unit/test_wafer_state_doping_mock.py`

**Interfaces:**
- Consumes: `DopantProfile` from Task 1 (`tcad.physics.dopant_profile`).
- Produces (for Task 3 and any future Stage B/C caller):
  - `WaferState.dopant_profiles: Tuple[DopantProfile, ...] = ()` (new
    field, default empty — every existing `WaferState.query(geometry)`
    call, currently only `tcad/process/etching/isotropic.py:72`, is
    unaffected).
  - `WaferState.query(domain, dopant_profiles: Tuple[DopantProfile,
    ...] = ())` — new optional keyword parameter, plumbed straight into
    the constructed `WaferState`.
  - `WaferState.donor_concentration_at(x_um, depth_um=0.0) -> float`
  - `WaferState.acceptor_concentration_at(x_um, depth_um=0.0) -> float`
  - `WaferState.net_doping_at(x_um, depth_um=0.0) -> float` (derived:
    `donor_concentration_at - acceptor_concentration_at`, never stored)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_wafer_state_doping_mock.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState's doping query surface -- built by hand (no ViennaPS
domain needed), so this exercises the aggregation logic alone."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.wafer_state import WaferState


def _bare_state(dopant_profiles=()):
    return WaferState(
        materials=("Si",), stack=(), grid_delta_um=0.1,
        _cells=(), _thin_x=(), dopant_profiles=dopant_profiles,
    )


def test_no_profiles_is_zero_everywhere():
    state = _bare_state()
    assert state.donor_concentration_at(0.0, 0.0) == 0.0
    assert state.acceptor_concentration_at(0.0, 0.0) == 0.0
    assert state.net_doping_at(0.0, 0.0) == 0.0


def test_multiple_profiles_of_the_same_polarity_sum():
    """Two donor profiles superposed (e.g. a background plus an
    implant window, or two species) must ADD, matching the real
    physical relationship apply_implant_windows_doping already
    documents (superposition, not replacement)."""
    profiles = (
        DopantProfile(species="P", polarity="donor",
                      concentration_at=lambda x, d: 1.0e17),
        DopantProfile(species="As", polarity="donor",
                      concentration_at=lambda x, d: 2.0e16),
        DopantProfile(species="B", polarity="acceptor",
                      concentration_at=lambda x, d: 5.0e15),
    )
    state = _bare_state(profiles)
    assert state.donor_concentration_at(0.0, 0.0) == 1.0e17 + 2.0e16
    assert state.acceptor_concentration_at(0.0, 0.0) == 5.0e15
    assert state.net_doping_at(0.0, 0.0) == (1.0e17 + 2.0e16) - 5.0e15


def test_query_accepts_optional_dopant_profiles_kwarg():
    """WaferState.query() must accept dopant_profiles= as an optional
    kwarg without touching the domain-reading code path -- checked via
    signature inspection, no real ViennaPS domain needed for this unit
    test."""
    import inspect
    parameters = inspect.signature(WaferState.query).parameters
    assert "dopant_profiles" in parameters
    assert parameters["dopant_profiles"].default == ()


def main():
    test_no_profiles_is_zero_everywhere()
    test_multiple_profiles_of_the_same_polarity_sum()
    test_query_accepts_optional_dopant_profiles_kwarg()
    print("WaferState's doping query surface sums same-polarity "
          "profiles correctly and net_doping_at is a derived value.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/Scripts/python.exe tests/unit/test_wafer_state_doping_mock.py`
Expected: `TypeError: __init__() got an unexpected keyword argument
'dopant_profiles'`

- [ ] **Step 3: Write the implementation**

In `tcad/physics/wafer_state.py`:

1. Add the import near the top (after the existing `from typing import ...` line):

```python
from tcad.physics.dopant_profile import DopantProfile
```

2. Add the new field to the `WaferState` dataclass, after `_thin_x`
   (must be last, since it is the only field with a default):

```python
@dataclass(frozen=True)
class WaferState:
    materials: Tuple[str, ...]
    stack: Tuple[LayerInfo, ...]
    grid_delta_um: float
    _cells: Tuple[_Cell, ...]
    _thin_x: Tuple[float, ...]
    dopant_profiles: Tuple[DopantProfile, ...] = ()
```

3. Change `query`'s signature and its final `return WaferState(...)` call:

```python
    @staticmethod
    def query(domain: Any, dopant_profiles: Tuple[DopantProfile, ...] = ()) -> "WaferState":
        import viennals as vls
```

   (only the signature line changes; the body is unchanged down to the
   `return WaferState(` call, which gains one more keyword argument:)

```python
        return WaferState(
            materials=names,
            stack=stack,
            grid_delta_um=grid,
            _cells=tuple(cells),
            _thin_x=WaferState._thin_layer_positions(domain, grid),
            dopant_profiles=dopant_profiles,
        )
```

4. Add the three new query methods at the end of the class, after
   `under_resolved_x`:

```python
    def donor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> float:
        return sum(
            p.concentration_at(x_um, depth_um)
            for p in self.dopant_profiles if p.polarity == "donor"
        )

    def acceptor_concentration_at(self, x_um: float, depth_um: float = 0.0) -> float:
        return sum(
            p.concentration_at(x_um, depth_um)
            for p in self.dopant_profiles if p.polarity == "acceptor"
        )

    def net_doping_at(self, x_um: float, depth_um: float = 0.0) -> float:
        """Derived, always -- never a stored field (spec 2026-09-01,
        section 2: process-layer state stays donor/acceptor-separated;
        only a query like this one collapses it to a signed net)."""
        return self.donor_concentration_at(x_um, depth_um) - self.acceptor_concentration_at(x_um, depth_um)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.venv/Scripts/python.exe tests/unit/test_wafer_state_doping_mock.py`
Expected: prints the summary line, exit 0.

- [ ] **Step 5: Run the existing WaferState/resolver unit and real tests unchanged**

Run:
```bash
../.venv/Scripts/python.exe tests/unit/test_resolver_mock.py
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_wafer_state_real.py
```
Expected: both pass unchanged (they never pass `dopant_profiles=`, so
they exercise the new default `()` path).

- [ ] **Step 6: Commit**

```bash
git add tcad/physics/wafer_state.py tests/unit/test_wafer_state_doping_mock.py
git commit -m "feat: WaferState doping query surface (donor/acceptor/net, Stage A)"
```

---

### Task 3: Real cross-check against DevSim's own solved NetDoping

**Files:**
- Test: `tests/integration/test_dopant_profile_matches_devsim_real.py`

**Interfaces:**
- Consumes: `dopant_profiles_from_doping_profile` (Task 1),
  `WaferState.net_doping_at` (Task 2), and the EXISTING, unmodified
  `apply_uniform_doping` / `apply_step_junction_doping` /
  `apply_gaussian_implant_doping` / `apply_implant_windows_doping`
  (`tcad/physics/doping.py`), `import_process_result` / `apply_doping`
  (`tcad/device/devsim/mesh_import.py` / `doping_mapping.py`).
- Produces: nothing consumed by a later task — this is Stage A's
  closing verification, proving the new Task 1/2 code computes the
  SAME numbers DevSim's real solved NetDoping does, not merely
  numbers that look plausible on paper.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_dopant_profile_matches_devsim_real.py`,
following the exact pattern of
`tests/integration/test_implant_windows_doping_real.py` (build once
via a real ViennaPS etch, then apply each doping kind, import into
DevSim, read back real `NetDoping`/`x` node values, and compare):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage A closing verification: WaferState.net_doping_at (built from
DopantProfile, Task 1/2 of the state-dependent-physics plan) must
reproduce DevSim's own REAL solved NetDoping node values, for every
doping kind, at the real node coordinates DevSim itself reports --
not a second, independently-plausible formula, but the exact same
number the already-verified doping_mapping.py path produces.

Per docs/superpowers/specs/2026-09-01-state-dependent-process-physics-design.md
section 2, this is the proof that the new process-layer query surface
and the existing device-layer NetDoping construction agree, without
requiring doping_mapping.py to change at all.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

RECIPE = {
    "grid_delta_um": 0.1,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.3,
    "etch_time_s": 0.5,
    "rate": -0.05,
    "mask_material": "Mask",
}


def _fresh_process_result():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        return build_process_result(step_result)


def _check_one_kind(label, doped_result, boundaries=()):
    """Import into a fresh DevSim device, read real NetDoping, compare
    node-by-node against WaferState.net_doping_at built from the SAME
    DopingProfile via Task 1/2's new code. Boundary-adjacent nodes
    (step() ambiguity, not the thing under test) are skipped, same
    convention as test_implant_windows_doping_real.py."""
    imported = import_process_result(
        doped_result, mesh_name=f"{label}_mesh", device_name=f"{label}_device",
        contact_regions=["Si"], contact_axis="x",
    )
    try:
        apply_doping(imported.device, doped_result.doping)

        x_values = devsim.get_node_model_values(device=imported.device, region="Si", name="x")
        actual = devsim.get_node_model_values(device=imported.device, region="Si", name="NetDoping")

        profiles = dopant_profiles_from_doping_profile(doped_result.doping)
        state = WaferState(materials=("Si",), stack=(), grid_delta_um=0.1,
                            _cells=(), _thin_x=(), dopant_profiles=profiles)

        max_rel_error = 0.0
        n_checked = 0
        for x, dev_value in zip(x_values, actual):
            if boundaries and min(abs(x - b) for b in boundaries) < 1e-6:
                continue
            predicted = state.net_doping_at(x, 0.0)
            denom = max(abs(dev_value), 1.0)
            rel_error = abs(predicted - dev_value) / denom
            max_rel_error = max(max_rel_error, rel_error)
            n_checked += 1

        print(f"[{label}] checked {n_checked} nodes, "
              f"max relative error vs real DevSim NetDoping: {max_rel_error:.3e}")
        assert n_checked > 0, f"{label}: no nodes checked"
        assert max_rel_error < 1e-9, (
            f"{label}: WaferState.net_doping_at does not match real "
            f"DevSim NetDoping (max rel error {max_rel_error})"
        )
    finally:
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)


def main():
    # uniform, donor/acceptor split
    result = _fresh_process_result()
    doped = apply_uniform_doping(
        result, donor_by_region_cm3={"Si": 1.0e16},
        acceptor_by_region_cm3={"Si": 3.0e15},
    )
    _check_one_kind("uniform", doped)

    # step_junction
    result = _fresh_process_result()
    doped = apply_step_junction_doping(
        result, region="Si", junction_axis="x", junction_position_um=0.0,
        donor_conc_cm3=1.0e18, acceptor_conc_cm3=1.0e18,
    )
    _check_one_kind("step_junction", doped, boundaries=[0.0])

    # gaussian_implant, donor/acceptor split
    result = _fresh_process_result()
    doped = apply_gaussian_implant_doping(
        result, region="Si", junction_axis="x",
        peak_position_um=0.0, straggle_um=0.5,
        donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=1.0e17,
    )
    _check_one_kind("gaussian_implant", doped)

    # implant_windows, background + one window
    result = _fresh_process_result()
    doped = apply_implant_windows_doping(
        result, region="Si", axis="x",
        background_doping_cm3=-1.0e17,
        windows=[{"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1.0e20}],
    )
    _check_one_kind("implant_windows", doped, boundaries=[-1.6, -0.6])

    assert devsim.get_device_list() == (), (
        "a device leaked past cleanup -- would poison a later, "
        "unrelated solve (see CLAUDE.md's documented DevSim-lifecycle trap)"
    )
    print("WaferState.net_doping_at matches real, solved DevSim "
          "NetDoping for all 4 doping kinds.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against real ViennaPS + DevSim**

```bash
cd C:/Users/박석훈/PycharmProjects/tcad/tcad
PYTHONIOENCODING=utf-8 KMP_DUPLICATE_LIB_OK=TRUE ../.venv/Scripts/python.exe tests/integration/test_dopant_profile_matches_devsim_real.py
```

Expected: all four `[kind] checked N nodes, max relative error ...`
lines print with error below `1e-9`, then the summary line, exit 0.
If any kind's max relative error is NOT below `1e-9`, that is a real
mismatch between Task 1/2's evaluator and `doping_mapping.py`'s actual
DevSim equation for that kind — re-derive that kind's
`concentration_at` from `doping_mapping.py`'s real equation string
(quoted in that file's own module docstring) rather than adjusting the
tolerance.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_dopant_profile_matches_devsim_real.py
git commit -m "test: DopantProfile/WaferState doping surface matches real solved DevSim NetDoping (Stage A closing verification)"
```

---

## Stage A completion criteria

Before this stage is considered done and Stage B can be planned:

1. All three tasks above committed.
2. Full project regression (`tests/run_regression.py`, controller-run
   with a bounded timeout, per this project's established pattern) —
   same pass/fail counts as the pre-Stage-A baseline (67 passed / 3
   pre-existing failures / 0 skipped as of the last recorded baseline
   in CLAUDE.md, plus the 2 new mock tests and 1 new real test this
   plan adds, all passing) — **zero new failures, zero changed
   existing-test values.**
3. A brief note added to CLAUDE.md's Completed section (mirroring
   this project's existing convention for a finished SDD plan) once
   the whole-branch review for this stage is clean.

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-09-01-state-dependent-physics-stage-a.md`.
Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per
task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using
executing-plans, batch execution with checkpoints

**Which approach?**
