#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 P1: a state migrated from a mesh-only ProcessResult plus
a synthetic intrinsic (net_doping_cm3=0.0) uniform DopingProfile --
`advance_wafer_state(None, doping_process_result, "doping")` -- must
fail closed EXPLICITLY, never resolve to a guessed "intrinsic Si,
NetDoping=0".

History: this pinned the GUI's gate-stack DC operating point fallback
for "no accumulated self.wafer_state", which built exactly that state.
Tier 1-1 removed the fallback: `run_dc_operating_point()` now hands
`self.wafer_state` (None included) straight to the central gate inside
`apply_doping()`, and that entry point is covered by
tests/unit/test_measurement_entry_point_gate_mock.py. This file keeps
pinning the underlying contract for the legacy-migration pattern itself.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.device.devsim import doping_mapping
from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult, MaterialRegion


def _write_minimal_si_mesh(path):
    """A real, minimal single-triangle mesh meshio can read back, with
    a "Material" cell-data array tagging it as region 0 -- just enough
    for WaferState.from_process_result()'s real meshio.read() call to
    succeed (this test exercises the real legacy-migration code path,
    not a mock of it)."""
    import meshio
    import numpy as np

    mesh = meshio.Mesh(
        points=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        cells=[("triangle", np.array([[0, 1, 2]]))],
        cell_data={"Material": [np.array([0])]},
    )
    meshio.write(path, mesh, file_format="vtu")


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


def main():
    # The exact fallback shape: no prior state, a synthetic intrinsic
    # uniform DopingProfile paired with a mesh-only ProcessResult.
    with tempfile.TemporaryDirectory() as tmp:
        mesh_path = str(Path(tmp) / "fallback.vtu")
        _write_minimal_si_mesh(mesh_path)

        doping = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=0.0)])
        process_result = ProcessResult(
            volume_mesh_path=mesh_path,
            material_field="Material",
            material_regions=[MaterialRegion(name="Si", tag=0)],
            doping=doping,
        )
        state = advance_wafer_state(None, process_result, "doping")

    q = state.net_doping_at(0.0, 0.0)
    assert q.net_doping is None, "no accumulated state must never resolve to a real 0"
    assert q.physics_status is not None
    assert q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"

    fake = FakeDevsim([0.0, 1.0], [0.0, 0.0])
    orig = backend.require_devsim
    backend.require_devsim = lambda: fake
    doping_mapping.backend.require_devsim = lambda: fake
    try:
        try:
            doping_mapping.apply_doping("dev", "Si", state)
            raise AssertionError("apply_doping must raise, not silently write 0")
        except doping_mapping.UnsupportedDopingState:
            pass
    finally:
        backend.require_devsim = orig
        doping_mapping.backend.require_devsim = orig

    assert "NetDoping" not in fake.writes

    print("Legacy state from a mesh-only result + synthetic intrinsic profile: "
          "explicitly fail-closed -- net_doping_at is None/UNSUPPORTED_BY_MODEL, "
          "apply_doping raises UnsupportedDopingState, 0 writes.")


if __name__ == "__main__":
    main()
