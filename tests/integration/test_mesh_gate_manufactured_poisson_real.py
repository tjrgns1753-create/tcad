#!/usr/bin/env python3
"""Manufactured-source Poisson control for the importer's area-conservation gate (Batch 7H-E6G). A NUMERICAL-EQUATION check with a
manufactured source -- not a PN / device-physics validation.

Mesh: the 7H-C1 non-uniform, non-obtuse structured geometry (single Si rectangle 2 um x 1 um, x lines 0, 0.6, 1.5, 2.0 um, y lines 0,
0.4, 1.0 um, right triangles), imported through import_process_result (area gate included), length scale 1e-4 cm/um.
Equation (DEVSIM public API only): -eps psi'' = rho with eps and rho set by set_parameter; edge flux eps*(psi@n0 - psi@n1)*
EdgeInverseLength (integrated with EdgeCouple); node model "-rho" (integrated with NodeVolume, DEVSIM's own convention -- the same sign
simple_physics uses for PotentialIntrinsicCharge = -q * charge density); Dirichlet psi = 0 on Si_xmin and Si_xmax; top / bottom natural
(zero flux). Exact solution psi(x) = rho x (L - x) / (2 eps), x from x_min, L = x_max - x_min. The finite-volume scheme reproduces a
quadratic exactly at the nodes when the dual volumes are exact, so the tolerance is fixed here before any run:
max |psi - exact| <= 1e-9 * max |exact|."""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REL_TOL = 1.0e-9
EPS = 1.0
L_CM = 2.0e-4
RHO = 8.0 * EPS / (L_CM ** 2)        # max exact psi = rho L^2 / (8 eps) = 1 V


def main():
    import meshio
    from tcad.backends.viennaps import session
    from tcad.device.devsim import backend
    from tcad.device.devsim.mesh_import import import_process_result
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
    path = Path(tempfile.mkdtemp(prefix="gate_poisson_")) / "poisson_control.vtu"
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
        imported = import_process_result(pr, mesh_name="gate_poisson_mesh", device_name="gate_poisson_device",
                                         contact_regions=["Si"], contact_axis="x", length_scale_to_cm=1.0e-4)
        rep = imported.area_conservation["Si"]
        assert rep["pass"], rep
        dev, reg = imported.device, "Si"
        dv.set_parameter(device=dev, region=reg, name="eps_mms", value=EPS)
        dv.set_parameter(device=dev, region=reg, name="rho_mms", value=RHO)
        dv.node_solution(device=dev, region=reg, name="Potential")
        dv.edge_from_node_model(device=dev, region=reg, node_model="Potential")
        dv.edge_model(device=dev, region=reg, name="Flux", equation="eps_mms*(Potential@n0-Potential@n1)*EdgeInverseLength")
        dv.edge_model(device=dev, region=reg, name="Flux:Potential@n0", equation="eps_mms*EdgeInverseLength")
        dv.edge_model(device=dev, region=reg, name="Flux:Potential@n1", equation="-eps_mms*EdgeInverseLength")
        dv.node_model(device=dev, region=reg, name="Source", equation="-rho_mms")
        dv.node_model(device=dev, region=reg, name="Source:Potential", equation="0")
        dv.equation(device=dev, region=reg, name="PotentialEquation", variable_name="Potential", edge_model="Flux", node_model="Source")
        for contact in ("Si_xmin", "Si_xmax"):
            dv.contact_node_model(device=dev, contact=contact, name=f"{contact}_bc", equation="Potential")
            dv.contact_node_model(device=dev, contact=contact, name=f"{contact}_bc:Potential", equation="1")
            dv.contact_equation(device=dev, contact=contact, name="PotentialEquation", node_model=f"{contact}_bc")
        dv.solve(type="dc", absolute_error=1.0e-12, relative_error=1.0e-12, maximum_iterations=30)
        x = np.array(dv.get_node_model_values(device=dev, region=reg, name="x"))
        v = np.array(dv.get_node_model_values(device=dev, region=reg, name="Potential"))
        xr = x - x.min()
        L = x.max() - x.min()
        exact = RHO * xr * (L - xr) / (2 * EPS)
        err = float(np.max(np.abs(v - exact)))
        rel = err / float(np.max(np.abs(exact)))
        print(f"area report: A {rep['A']!r} S {rep['S']!r} B/A {rep['relative_uncertainty']!r}")
        print(f"solve calls {calls['solve']}, nodes {len(v)}, max|exact| {np.max(np.abs(exact)):.6f} V, max |psi - exact| = {err:.3e} V, "
              f"relative {rel:.3e} (tolerance {REL_TOL:.1e})")
        assert calls["solve"] >= 1, "no real solve ran"
        assert rel <= REL_TOL, f"manufactured Poisson error {rel:.3e} exceeds {REL_TOL:.1e}"
    finally:
        dv.solve = real_solve
        if imported is not None:
            dv.delete_device(device=imported.device)
            dv.delete_mesh(mesh=imported.mesh)
    assert list(dv.get_device_list()) == []
    print("MESH GATE MANUFACTURED POISSON CONTROL PASSED")


if __name__ == "__main__":
    main()
