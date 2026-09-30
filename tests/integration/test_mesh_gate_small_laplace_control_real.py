#!/usr/bin/env python3
"""Normal electrical control for the importer's area-conservation gate
(Batch 7H-E6E-R1 PLAN section 4): a small, non-obtuse, non-uniform planar
mesh goes through import_process_result() -- gate included -- and a real
DevSim Laplace solve whose answer is known in closed form.

Mesh: the 7H-C1 fixture geometry (single Si rectangle 2 um x 1 um, x lines
0, 0.6, 1.5, 2.0 um, y lines 0, 0.4, 1.0 um, each cell split by its
bottom-left-to-top-right diagonal: right triangles only), written as a .vtu
with the ViennaPS Si tag. Contacts Si_xmin = 0 V, Si_xmax = 1 V; the exact
solution of Laplace's equation is Potential = (x - x_min) / (x_max - x_min).
Tolerance 1e-9 V is inherited unchanged from
tests/integration/test_basic_potential_linear_precision_real.py (EXACT_V).
Passing shows that a certified mesh still reaches a correct solve; it says
nothing about mesh convergence or device physics beyond this Laplace case."""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EXACT_V = 1.0e-9


def main():
    import meshio
    from tcad.backends.viennaps import session
    from tcad.device.devsim import backend
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.solve import run_basic_potential_solve
    from tcad.mesh.viennaps_adapter import build_process_result

    dv = backend.require_devsim()
    si = int(session.require_viennaps().Material.Si)
    xs, ys = [0.0, 0.6, 1.5, 2.0], [0.0, 0.4, 1.0]
    pts = np.array([[x, y, 0.0] for y in ys for x in xs])
    nx = len(xs)
    tris = []
    for j in range(len(ys) - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i
            tris += [(a, b, c), (a, c, d)]
    tmp = Path(tempfile.mkdtemp(prefix="gate_laplace_"))
    path = tmp / "laplace_control.vtu"
    meshio.write(str(path), meshio.Mesh(pts, [("triangle", np.array(tris))], cell_data={"Material": [np.full(len(tris), si, dtype=np.int32)]}))

    calls = {"solve": 0}
    real_solve = dv.solve

    def counted(*a, **kw):
        calls["solve"] += 1
        return real_solve(*a, **kw)
    dv.solve = counted
    imported = None
    try:
        pr = build_process_result({"final_mesh": str(path), "snapshots": []})
        imported = import_process_result(pr, mesh_name="gate_laplace_mesh", device_name="gate_laplace_device",
                                         contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1.0e-4)
        rep = imported.area_conservation["Si"]
        assert rep["pass"] and rep["relative_uncertainty"] <= rep["certification_limit"], rep
        assert sorted(imported.contacts) == ["Si_xmax", "Si_xmin"], imported.contacts
        run_basic_potential_solve(device=imported.device, region="Si", contact_bias={"Si_xmin": 0.0, "Si_xmax": 1.0})
        x = np.array(dv.get_node_model_values(device=imported.device, region="Si", name="x"))
        v = np.array(dv.get_node_model_values(device=imported.device, region="Si", name="Potential"))
        exact = (x - x.min()) / (x.max() - x.min())
        err = float(np.max(np.abs(v - exact)))
        print(f"area report: {rep}")
        print(f"solve calls {calls['solve']}, nodes {len(v)}, max |Potential - exact| = {err:.3e} V (tolerance {EXACT_V:.1e} V)")
        assert calls["solve"] >= 1, "no real solve ran"
        assert err <= EXACT_V, f"Laplace error {err:.3e} V exceeds {EXACT_V:.1e} V"
    finally:
        dv.solve = real_solve
        if imported is not None:
            dv.delete_device(device=imported.device)
            dv.delete_mesh(mesh=imported.mesh)
    assert list(dv.get_device_list()) == []
    print("MESH GATE SMALL LAPLACE CONTROL PASSED")


if __name__ == "__main__":
    main()
