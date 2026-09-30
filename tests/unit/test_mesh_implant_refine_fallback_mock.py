#!/usr/bin/env python3
"""refine_process_result_for_implant_windows: StructuredRemeshUnsupported keeps the graded path (with a logged reason) while
StructuredRemeshAborted propagates and writes nothing (Batch 7H-E6H criteria D). Pure mesh + numpy; no DEVSIM / ViennaPS."""
import logging
import os
import sys
import tempfile
from pathlib import Path

import meshio
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mesh_structured_remesh_mock import grid  # noqa: E402
from tcad.device.devsim.mesh_import import refine_process_result_for_implant_windows  # noqa: E402
from tcad.device.devsim.mesh_refine import StructuredRemeshAborted, structured_lateral_refine  # noqa: E402
from tcad.mesh.interface import MaterialRegion, ProcessResult  # noqa: E402
from tcad.physics.doping import apply_implant_windows_doping  # noqa: E402


def doped_result(P, T, G, names, windows, path):
    meshio.write(path, meshio.Mesh(P, [("triangle", T)], cell_data={"Material": [G]}))
    pr = ProcessResult(volume_mesh_path=path, material_field="Material", material_regions=[MaterialRegion(name=n, tag=t) for t, n in names.items()])
    return apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=0.0, acceptor_background_cm3=1e17,
                                        windows=[{"min_um": a, "max_um": b, "donor_conc_cm3": 1e20, "acceptor_conc_cm3": 0.0} for a, b in windows],
                                        chemical_state="ACTIVE")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def main():
    tmp = tempfile.mkdtemp(prefix="fallback_mock_")
    capture = Capture()
    logging.getLogger("tcad.device.devsim.mesh_import").addHandler(capture)

    # supported: structured path, identical to a direct builder call, no fallback message
    P, T, G = grid([0.5 * i for i in range(9)], [0.5 * j for j in range(3)])
    res = refine_process_result_for_implant_windows(doped_result(P, T, G, {10: "Si"}, [(1.0, 2.0)], os.path.join(tmp, "a.vtu")),
                                                    refined_mesh_path=os.path.join(tmp, "a_ref.vtu"))
    m = meshio.read(res.volume_mesh_path)
    assert not capture.records, capture.records
    from tcad.device.devsim.mesh_import import implant_windows_lateral_request
    doped = doped_result(P, T, G, {10: "Si"}, [(1.0, 2.0)], os.path.join(tmp, "a2.vtu"))
    req = implant_windows_lateral_request(doped.doping, P, T)
    Pd, Td, _, _ = structured_lateral_refine(P, T, G, req["centers"], req["rings"])
    assert np.array_equal(m.points, Pd) and np.array_equal(m.cells[0].data, Td)

    # StructuredRemeshUnsupported (a missing triangle): graded path, reason logged, output written
    res = refine_process_result_for_implant_windows(doped_result(P, T[1:], G[1:], {10: "Si"}, [(1.0, 2.0)], os.path.join(tmp, "b.vtu")),
                                                    refined_mesh_path=os.path.join(tmp, "b_ref.vtu"))
    assert os.path.exists(res.volume_mesh_path) and len(meshio.read(res.volume_mesh_path).cells[0].data) > len(T) - 1
    assert any("NOT_TWO_TRIANGLES_PER_CELL" in r for r in capture.records), capture.records

    # StructuredRemeshAborted (aspect condition): propagates, no output, no graded substitute
    P, T, G = grid([0.1 * i for i in range(41)], [0.0, 1.0, 2.0])
    before = len(capture.records)
    out = os.path.join(tmp, "c_ref.vtu")
    try:
        refine_process_result_for_implant_windows(doped_result(P, T, G, {10: "Si"}, [(1.5, 2.5)], os.path.join(tmp, "c.vtu")), refined_mesh_path=out)
    except StructuredRemeshAborted as exc:
        assert exc.reason == "TRANSITION_ASPECT", exc.reason
    else:
        raise AssertionError("expected StructuredRemeshAborted")
    assert not os.path.exists(out) and len(capture.records) == before
    print("FALLBACK MOCK CHECKS PASSED: supported -> structured (equal to a direct call); Unsupported -> graded + logged reason; "
          "Aborted -> propagated, nothing written")


if __name__ == "__main__":
    main()
