#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 P1: the CLI pipeline's `_apply_device_doping` now
threads a MODELLED initial `WaferStateV2` from the process step's OWN
recipe when it carries explicit virgin-substrate bounds
(`x_extent_um` + `silicon_depth_um`), instead of unconditionally
migrating the exported mesh as `LEGACY_UNRESOLVED`
(`advance_wafer_state(None, ...)`).

Branch A / Branch B, both proven here:
  - Branch A: an explicit-bounds recipe with NO real geometry-changing
    category (e.g. a doping-only config) attaches a real numeric
    doping profile to the MODELLED rectangle -- a genuine PASS.
  - Branch B: the CLI still has no representable v2 GeometryTransform
    for a real etching/deposition/oxidation category, so a real
    process step still fails closed EVEN WHEN the recipe's initial
    bounds were explicit -- an explicit initial rectangle must never
    be treated as still valid after a real, un-represented geometry
    change. This is the regression this test exists to catch: naively
    swapping `advance_wafer_state(None, ...)` for the MODELLED initial
    state would otherwise silently attach a real numeric profile to
    geometry that a real (curved) etch/oxidation/deposition had
    already invalidated.
  - Branch B (unchanged legacy path): a recipe with no explicit bounds
    still resolves to `None` and behaves exactly as before.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.cli.run_pipeline import _initial_state_for_process, _apply_device_doping
from tcad.device.devsim import doping_mapping
from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult, MaterialRegion


class FakeDevsim:
    def __init__(self, xs, ys):
        self._xs, self._ys = list(xs), list(ys)
        self.writes = {}

    def get_node_model_values(self, device, region, name):
        return list(self._xs) if name == "x" else list(self._ys)

    def node_model(self, device, region, name, equation):
        pass

    def set_node_values(self, device, region, name, values):
        self.writes[name] = list(values)

    class error(RuntimeError):
        pass


class FakeImported:
    device = "cli_dev"


def _write_minimal_si_mesh(path):
    import meshio
    import numpy as np

    mesh = meshio.Mesh(
        points=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        cells=[("triangle", np.array([[0, 1, 2]]))],
        cell_data={"Material": [np.array([0])]},
    )
    meshio.write(path, mesh, file_format="vtu")


def _process_result(tmp, net_doping_cm3=1.0e17):
    mesh_path = str(Path(tmp) / "cli.vtu")
    _write_minimal_si_mesh(mesh_path)
    doping = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=net_doping_cm3, chemical_state="ACTIVE")])
    return ProcessResult(
        volume_mesh_path=mesh_path, material_field="Material",
        material_regions=[MaterialRegion(name="Si", tag=0)], doping=doping,
    )


def test_initial_state_branch_a_explicit_bounds():
    state = _initial_state_for_process({"recipe": {
        "x_extent_um": 4.0, "silicon_depth_um": 2.0, "grid_delta_um": 0.2}})
    assert state is not None
    cell = state.active_cells()[0]
    assert cell.is_modelled
    assert cell.bounds_um == (-2.0, 2.0, -2.0, 0.0), cell.bounds_um


def test_initial_state_branch_b_missing_depth():
    assert _initial_state_for_process({"recipe": {"x_extent_um": 4.0}}) is None


def test_initial_state_branch_b_no_process_cfg():
    assert _initial_state_for_process(None) is None
    assert _initial_state_for_process({}) is None


def _run_apply(process_cfg, tmp, device_cfg=None):
    fake = FakeDevsim([0.0, 1.0], [-1.0, -1.0])
    orig = backend.require_devsim
    backend.require_devsim = lambda: fake
    doping_mapping.backend.require_devsim = lambda: fake
    try:
        _apply_device_doping(
            FakeImported(), _process_result(tmp),
            device_cfg or {"length_scale_to_cm": 1.0}, process_cfg,
        )
        return fake, None
    except doping_mapping.UnsupportedDopingState as exc:
        return fake, exc
    finally:
        backend.require_devsim = orig
        doping_mapping.backend.require_devsim = orig


def test_branch_a_doping_only_config_attaches_a_real_number():
    """No real geometry-changing category in process_cfg (e.g. a
    doping-only description) -- the MODELLED initial rectangle is used
    directly and the real doping profile attaches for real."""
    with tempfile.TemporaryDirectory() as tmp:
        process_cfg = {"recipe": {"x_extent_um": 4.0, "silicon_depth_um": 2.0}}
        fake, exc = _run_apply(process_cfg, tmp)
        assert exc is None, f"expected a real numeric write, got {exc}"
        assert fake.writes["NetDoping"] == [1.0e17, 1.0e17]


def test_branch_b_real_process_category_still_fails_closed():
    """THE regression guard: even with explicit initial bounds, a real
    (un-represented) etching/deposition/oxidation category must still
    fail closed -- the explicit rectangle is not proof the geometry is
    still valid after a real process step this model cannot verify."""
    with tempfile.TemporaryDirectory() as tmp:
        process_cfg = {
            "category": "etching",
            "recipe": {"x_extent_um": 4.0, "silicon_depth_um": 2.0},
        }
        fake, exc = _run_apply(process_cfg, tmp)
        assert exc is not None, "a real process category must still block the solve"
        assert "NetDoping" not in fake.writes


def test_branch_b_no_explicit_bounds_unchanged_legacy_path():
    """A recipe without explicit bounds behaves exactly as before --
    LEGACY migration from the mesh, fail closed."""
    with tempfile.TemporaryDirectory() as tmp:
        process_cfg = {"category": "etching", "recipe": {}}
        fake, exc = _run_apply(process_cfg, tmp)
        assert exc is not None
        assert "NetDoping" not in fake.writes


def main():
    test_initial_state_branch_a_explicit_bounds()
    test_initial_state_branch_b_missing_depth()
    test_initial_state_branch_b_no_process_cfg()
    test_branch_a_doping_only_config_attaches_a_real_number()
    test_branch_b_real_process_category_still_fails_closed()
    test_branch_b_no_explicit_bounds_unchanged_legacy_path()
    print("CLI _apply_device_doping: explicit-bounds recipes build a "
          "MODELLED initial state (Branch A); a real process category "
          "still fails closed regardless (regression guard); a recipe "
          "with no explicit bounds is unchanged legacy Branch B.")


if __name__ == "__main__":
    main()
