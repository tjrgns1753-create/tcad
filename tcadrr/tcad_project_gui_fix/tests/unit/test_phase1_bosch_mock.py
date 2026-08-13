#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 verification: run the extracted run_viennaps_bosch() against a
mock viennaps module that mimics the real API surface used by the
original run_viennaps_bosch(). Confirms that the session/io extraction
did not change call sequence, argument values, or output structure.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class FakeMaterial:
    Mask = "Mask"
    Si = "Si"
    Polymer = "Polymer"


class FakeUnitSingleton:
    """Mimics vps.Length / vps.Time: class-level setUnit()/toString()."""

    _value = ""

    @classmethod
    def setUnit(cls, value):
        cls._value = value

    @classmethod
    def toString(cls):
        return cls._value


class FakeLength(FakeUnitSingleton):
    pass


class FakeTime(FakeUnitSingleton):
    pass


class FakeDomain:
    """Mimics vps.Domain's API surface actually called by production code.

    tcad.backends.viennaps.io.save_volume_mesh() now builds a floored
    COPY of the domain before export (see io.py's _floored_copy_for_export),
    which needs: the deep-copy constructor `Domain(domain)`, getGridDelta(),
    getBoundingBox(), and getLevelSets() -- each level set then goes
    through *real* viennals calls (vls.Domain(ls), vls.MakeGeometry,
    vls.BooleanOperation), since those are pybind11-typed and cannot
    accept a plain Python stand-in. So getLevelSets() here returns real,
    empty viennals.Domain objects, not fakes -- everything else about
    this test (ViennaPS itself: MakeTrench, Process, SingleParticleProcess,
    etc.) stays fully mocked, matching what this file already tests.
    The floor's geometric CORRECTNESS is not this test's concern (that is
    covered elsewhere, against the real backend); this only has to give
    save_volume_mesh() a valid API surface to call.
    """

    def __init__(self, gridDelta, xExtent=None, yExtent=None):
        import viennals as vls

        if isinstance(gridDelta, FakeDomain):
            # Deep-copy constructor path: `domain.__class__(domain)`.
            other = gridDelta
            self.gridDelta = other.gridDelta
            self.xExtent = other.xExtent
            self.yExtent = other.yExtent
            self.top_level_sets = list(other.top_level_sets)
            self._level_sets = [vls.Domain(ls) for ls in other._level_sets]
        else:
            self.gridDelta = gridDelta
            self.xExtent = xExtent
            self.yExtent = yExtent
            self.top_level_sets = []
            self._level_sets = [vls.Domain(gridDelta)]
        self.surface_saves = []
        self.volume_saves = []

    def getGridDelta(self):
        return self.gridDelta

    def getBoundingBox(self):
        half_x = self.xExtent / 2.0
        return [[-half_x, 0.0, 0.0], [half_x, self.yExtent, 0.0]]

    def getLevelSets(self):
        return self._level_sets

    def duplicateTopLevelSet(self, material):
        self.top_level_sets.append(material)

    def removeTopLevelSet(self):
        assert self.top_level_sets, "removeTopLevelSet called with empty stack"
        self.top_level_sets.pop()

    def removeStrayPoints(self):
        pass

    def saveSurfaceMesh(self, path, add_material_ids):
        Path(path).write_text("fake vtp")
        self.surface_saves.append((path, add_material_ids))

    def saveVolumeMesh(self, path):
        # Mirrors real ViennaPS 4.6.2 behavior (verified with the actual
        # installed package in Phase 2): saveVolumeMesh appends
        # "_volume.vtu" to the given base name rather than writing the
        # literal path.
        actual_path = f"{path}_volume.vtu"
        Path(actual_path).write_text("fake volume mesh")
        self.volume_saves.append(actual_path)


class FakeMakeTrenchHandle:
    def __init__(self, calls, kwargs):
        self.calls = calls
        self.kwargs = kwargs

    def apply(self):
        self.calls.append(self.kwargs)


class FakeSingleParticleProcess:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeMultiParticleProcess:
    def __init__(self):
        self.neutral = None
        self.ion = None
        self.rate_fn = None

    def addNeutralParticle(self, sticking):
        self.neutral = sticking

    def addIonParticle(self, sourcePower, thetaRMin):
        self.ion = (sourcePower, thetaRMin)

    def setRateFunction(self, fn):
        self.rate_fn = fn


class FakeProcessHandle:
    def __init__(self, calls, domain, model, duration):
        self.calls = calls
        self.domain = domain
        self.model = model
        self.duration = duration

    def apply(self):
        self.calls.append((self.model, self.duration))


class FakeViennaPS:
    def __init__(self):
        self.dimension = None
        self.trench_calls = []
        self.process_calls = []
        self.Material = FakeMaterial
        self.Length = FakeLength
        self.Time = FakeTime

    def setDimension(self, dim):
        self.dimension = dim

    def Domain(self, gridDelta, xExtent, yExtent):
        return FakeDomain(gridDelta, xExtent, yExtent)

    def MakeTrench(self, domain, trenchWidth, trenchDepth, maskHeight):
        return FakeMakeTrenchHandle(
            self.trench_calls,
            {
                "domain": domain,
                "trenchWidth": trenchWidth,
                "trenchDepth": trenchDepth,
                "maskHeight": maskHeight,
            },
        )

    def SingleParticleProcess(self, **kwargs):
        return FakeSingleParticleProcess(**kwargs)

    def MultiParticleProcess(self):
        return FakeMultiParticleProcess()

    def Process(self, domain, model, duration):
        return FakeProcessHandle(self.process_calls, domain, model, duration)


def main():
    import tcad.backends.viennaps.session as session_mod
    import tcad.process.etching.bosch_drie as bosch_mod

    fake = FakeViennaPS()
    session_mod.vps = fake  # monkeypatch: pretend ViennaPS is installed

    assert session_mod.is_available() is True, "is_available() should report True"

    recipe = {
        "mask_left_um": 3.5,
        "mask_right_um": 6.5,
        "pr_thickness_um": 1.0,
        "cycles": 2,
        "grid_delta_um": 0.05,
        "x_extent_um": 10.0,
        "y_extent_um": 8.0,
        "etch_time_s": 1.0,
        "polymer_rate": 0.03,
        "polymer_sticking": 1.0,
        "ion_source_exponent": 500.0,
        "ion_rate": -0.02,
        "neutral_rate": -0.01,
        "neutral_sticking": 0.10,
    }

    with tempfile.TemporaryDirectory() as tmp:
        result = bosch_mod.run_viennaps_bosch(recipe, tmp)

        # --- structural checks (same shape as the original function) ---
        assert set(result.keys()) == {"final_mesh", "snapshots", "cycles"}
        assert result["cycles"] == 2
        assert result["final_mesh"].endswith("bosch_final_volume.vtu")
        assert Path(result["final_mesh"]).exists()

        # 000_initial, 001_initial_etch, then 4 snapshots per cycle x 2 cycles
        expected_snapshot_count = 2 + 4 * 2
        assert len(result["snapshots"]) == expected_snapshot_count, (
            f"expected {expected_snapshot_count} snapshots, "
            f"got {len(result['snapshots'])}"
        )
        for path in result["snapshots"]:
            assert Path(path).exists(), f"missing snapshot file: {path}"

        # --- call-sequence / argument checks ---
        assert fake.dimension == 2, "setDimension(2) must be called (matches original)"

        assert len(fake.trench_calls) == 1
        trench_kwargs = fake.trench_calls[0]
        # round(..., 9) matches ProcessStep.prepare_domain()'s own
        # computation exactly (tcad/process/base.py) -- it strips
        # float64 subtraction noise before passing trenchWidth to
        # MakeTrench (see CLAUDE.md, "MakeTrench floating-point
        # sensitivity"). Comparing against the raw subtraction here
        # would silently pass for this test's specific values (3.5,
        # 6.5 -> exactly 3.0, no noise to strip) while checking the
        # wrong thing.
        assert trench_kwargs["trenchWidth"] == round(
            recipe["mask_right_um"] - recipe["mask_left_um"], 9
        )
        assert trench_kwargs["trenchDepth"] == 0.0
        assert trench_kwargs["maskHeight"] == max(recipe["pr_thickness_um"], 0.1)

        # Process() called: 1 initial etch + (passivation, breakthrough, etch) x cycles
        assert len(fake.process_calls) == 1 + 3 * recipe["cycles"]

        # duplicateTopLevelSet/removeTopLevelSet balance after all cycles
        domain = fake.trench_calls[0]["domain"]
        assert domain.top_level_sets == [], "polymer top-level-set stack must be balanced"

        # rate function behaves like the original etch_rate()
        mp = fake.process_calls[1][0]  # first cycle's silicon_etch MultiParticleProcess
        # find the MultiParticleProcess instance actually used for etching
        etch_models = [m for m, _ in fake.process_calls if isinstance(m, FakeMultiParticleProcess)]
        rate_fn = etch_models[0].rate_fn
        assert rate_fn((1.0, 1.0), FakeMaterial.Mask) == 0.0
        expected_si_rate = 1.0 * recipe["ion_rate"] + 1.0 * recipe["neutral_rate"]
        assert abs(rate_fn((1.0, 1.0), FakeMaterial.Si) - expected_si_rate) < 1e-12

    print("ALL PHASE 1 MOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
