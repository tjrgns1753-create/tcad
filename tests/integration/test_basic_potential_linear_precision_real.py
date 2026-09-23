#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch 7H-C1: deterministic real-DevSim linear-precision test for
tcad.device.devsim.solve.run_basic_potential_solve.

Fixture: a single rectangular Si region, 2 um x 1 um, built directly with
DevSim's public create_gmsh_mesh/add_gmsh_region/add_gmsh_contact API (no
ViennaPS, no mesh_import -- isolates the solve skeleton's own equation
assembly from geometry/import concerns). The grid has 3 unequal-width
columns (x = 0, 0.6, 1.5, 2.0 um) and 2 unequal-height rows (y = 0, 0.4,
1.0 um); each rectangular cell is split by its own bottom-left-to-top-right
diagonal into two triangles. Splitting a rectangle by one diagonal always
gives two triangles with exactly one right angle and two acute angles
(never obtuse), regardless of the rectangle's aspect ratio -- so this grid
is non-obtuse by construction while still being non-uniform (unequal
column widths and row heights) and carrying 2 interior nodes
((0.6,0.4) and (1.5,0.4) um).

Left contact = the x=0 boundary edge; right contact = the x=2 boundary
edge; top/bottom carry no explicit boundary condition (natural
zero-normal-flux). With left=0V, right=1V the analytic solution of
Laplace's equation on this domain is the linear ramp
Potential(x,y) = x/2 (V), independent of y.

Why this is the right discriminator between the DOUBLE-EDGECOUPLE bug and
the fix (established in
docs/audits/2026-09-23-batch7h-c-flux-discretization/REPORT.md, sections 6
and 8-9, read for context only -- not imported or depended on here):
DevSim's own equation-assembly integrates a bulk edge_model against
EdgeCouple ("the length of the perpendicular bisector", devsim.net's own
Equation-and-models manual page). The correct edge model for a diffusive
flux is therefore (V@n0-V@n1)*EdgeInverseLength, whose assembled matrix
coefficient becomes EdgeCouple/EdgeLength -- the real Laplacian weight,
which reproduces ANY linear potential exactly on a non-obtuse mesh (every
signed cotangent weight is >= 0 there, so DevSim's own internal absolute
weighting coincides with it; confirmed by direct measurement on this exact
mesh family in the audit above). The pre-fix code instead used
(V@n0-V@n1)*EdgeCouple as the edge model, which assembly integrates AGAIN
by EdgeCouple, giving a matrix coefficient of EdgeCouple**2 -- physically
the wrong units and wrong magnitude -- which was measured to produce an
L-infinity potential error of ~2.22e-2 V on this project's own equivalent
non-obtuse control mesh (audit REPORT.md section 8, mesh "M1"). This test
reproduces that discriminator directly against the real assembled matrix,
not just the node potentials, so a future accidental reintroduction of
"*EdgeCouple" in the edge_model string cannot silently pass by coincidence.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.solve import run_basic_potential_solve

assert devsim_backend.is_available(), "DevSim must be installed for this test"

# Fixed BEFORE the first run of this test (against the pre-fix production
# code) -- never loosened afterward to make a result pass.
EXACT_V = 1.0e-9         # analytic-solution match tolerance (item B)
MATRIX_REL_TOL = 1.0e-9  # matrix-coefficient match tolerance (items C/D)

L_UM, H_UM = 2.0, 1.0
X_COLS = [0.0, 0.6, 1.5, 2.0]
Y_ROWS = [0.0, 0.4, 1.0]


def _build_device(module, device, mesh, region):
    """Public create_gmsh_mesh/add_gmsh_region/add_gmsh_contact path --
    the SAME public API family import_process_result() uses, never a
    private/internal one."""
    points = [(x, y) for y in Y_ROWS for x in X_COLS]
    idx = {(x, y): i for i, (x, y) in enumerate(points)}

    triangles = []
    for ry in range(len(Y_ROWS) - 1):
        y0, y1 = Y_ROWS[ry], Y_ROWS[ry + 1]
        for cx in range(len(X_COLS) - 1):
            x0, x1 = X_COLS[cx], X_COLS[cx + 1]
            bl, br, tl, tr = idx[(x0, y0)], idx[(x1, y0)], idx[(x0, y1)], idx[(x1, y1)]
            # split by the bottom-left -> top-right diagonal: two triangles,
            # each with exactly one right angle (never obtuse)
            triangles.append((bl, br, tr))
            triangles.append((bl, tr, tl))

    coordinates = []
    for x, y in points:
        coordinates += [x, y, 0.0]

    elements = []
    for a, b, c in triangles:
        elements += [2, 0, a, b, c]  # 2 = triangle, region index 0

    left_edges = [(idx[(0.0, Y_ROWS[k])], idx[(0.0, Y_ROWS[k + 1])]) for k in range(len(Y_ROWS) - 1)]
    right_edges = [(idx[(L_UM, Y_ROWS[k])], idx[(L_UM, Y_ROWS[k + 1])]) for k in range(len(Y_ROWS) - 1)]
    for a, b in left_edges:
        elements += [1, 1, a, b]   # 1 = line, region index 1 ("left")
    for a, b in right_edges:
        elements += [1, 2, a, b]   # region index 2 ("right")

    module.create_gmsh_mesh(mesh=mesh, coordinates=coordinates, elements=elements,
                            physical_names=[region, "left", "right"])
    module.add_gmsh_region(gmsh_name=region, mesh=mesh, region=region, material="Si")
    module.add_gmsh_contact(gmsh_name="left", mesh=mesh, name="left", material="metal", region=region)
    module.add_gmsh_contact(gmsh_name="right", mesh=mesh, name="right", material="metal", region=region)
    module.finalize_mesh(mesh=mesh)
    module.create_device(mesh=mesh, device=device)
    return points


def main():
    module = devsim_backend.require_devsim()
    device, mesh, region = "d_7hc1_linear", "m_7hc1_linear", "Si"
    points = _build_device(module, device, mesh, region)

    # Two distinct node counts -- do not conflate them:
    #   strict geometric interior: excludes ALL boundary nodes (left/right
    #     contacts AND the top/bottom natural-boundary rows).
    #   free bulk-equation nodes: excludes only the left/right Dirichlet
    #     contact nodes (top/bottom rows carry no explicit BC, so they are
    #     "free" unknowns solved by the bulk equation, not interior in the
    #     geometric sense). This is the set the matrix check below (items
    #     C/D) actually exercises, since it only excludes contact nodes.
    n_strict_interior = sum(1 for x, y in points if 0.0 < x < L_UM and 0.0 < y < H_UM)
    n_free_bulk = sum(1 for x, y in points if 0.0 < x < L_UM)
    assert n_strict_interior >= 1, "fixture must have at least one strict geometric interior node"

    solve_result = run_basic_potential_solve(
        device=device, region=region, contact_bias={"left": 0.0, "right": 1.0},
    )
    print(f"[fixture] {len(points)} nodes, {n_strict_interior} strict interior, "
          f"{n_free_bulk} free bulk-equation -- {solve_result}")

    x = module.get_node_model_values(device=device, region=region, name="x")
    phi = module.get_node_model_values(device=device, region=region, name="Potential")
    analytic = [xv / L_UM for xv in x]  # V = x/L, L in the same coordinate units as x

    err = [abs(p - a) for p, a in zip(phi, analytic)]
    linf = max(err)
    l2 = (sum(e * e for e in err) / len(err)) ** 0.5
    print(f"[A] Linf={linf:.6e} V  L2={l2:.6e} V  (tolerance {EXACT_V:.1e} V)")

    # A + B: EVERY node (not just min/max) matches the analytic ramp
    for i, (p, a, e) in enumerate(zip(phi, analytic, err)):
        assert e <= EXACT_V, (
            f"node {i} at x={x[i]:.6f} um: Potential={p!r} V, analytic={a!r} V, "
            f"error={e:.6e} V exceeds tolerance {EXACT_V:.1e} V -- this is the "
            f"linear-precision failure mode of the double-EdgeCouple bug"
        )

    # C + D: read the REAL assembled matrix (never assume from the node
    # values alone -- a coincidentally-small potential error would not by
    # itself distinguish "correct assembly" from "a different wrong one")
    eqn = module.get_equation_numbers(device=device, region=region, equation="PotentialEquation")
    matrix = module.get_matrix_and_rhs(format="csr")["static"]
    ap, ai, av = matrix["ap"], matrix["ai"], matrix["av"]

    module.edge_from_node_model(device=device, region=region, node_model="node_index")
    n0 = module.get_edge_model_values(device=device, region=region, name="node_index@n0")
    n1 = module.get_edge_model_values(device=device, region=region, name="node_index@n1")
    couple = module.get_edge_model_values(device=device, region=region, name="EdgeCouple")
    length = module.get_edge_model_values(device=device, region=region, name="EdgeLength")

    def matrix_entry(row_node, col_node):
        row = eqn[row_node]
        for k in range(ap[row], ap[row + 1]):
            if ai[k] == eqn[col_node]:
                return av[k]
        return 0.0

    checked = 0
    for k in range(len(n0)):
        a, b = int(n0[k]), int(n1[k])
        c, ln = couple[k], length[k]
        if c == 0.0:
            continue
        expected_col = c / ln
        expected_c2 = c * c
        for i, j in ((a, b), (b, a)):
            if x[i] in (0.0, L_UM):
                continue  # contact node -- its own row is the boundary-condition row, not the bulk flux row
            w = -matrix_entry(i, j)  # off-diagonal Jacobian sign convention: contribution INTO row i FROM node j
            rel_col = abs(w - expected_col) / expected_col
            rel_c2 = abs(w - expected_c2) / abs(expected_c2) if expected_c2 else float("inf")
            checked += 1
            assert rel_col <= MATRIX_REL_TOL, (
                f"edge ({i},{j}): matrix coefficient {w!r} does not match EdgeCouple/EdgeLength "
                f"{expected_col!r} (rel diff {rel_col:.3e}) -- edge_model is not assembling as "
                f"the correct diffusive flux"
            )
            assert rel_c2 > MATRIX_REL_TOL, (
                f"edge ({i},{j}): matrix coefficient {w!r} matches EdgeCouple**2 {expected_c2!r} "
                f"-- the double-EdgeCouple bug is back"
            )
    assert checked > 0, "no interior bulk edge rows were actually checked -- test would be a false green"
    print(f"[C/D] {checked} interior directed-edge matrix rows checked: all match EdgeCouple/EdgeLength, "
          f"none match EdgeCouple**2 (tolerance {MATRIX_REL_TOL:.1e} rel)")

    module.delete_device(device=device)
    module.delete_mesh(mesh=mesh)
    assert device not in module.get_device_list()

    print()
    print("BASIC POTENTIAL LINEAR-PRECISION TEST PASSED (real DevSim, real assembled matrix)")


if __name__ == "__main__":
    main()
