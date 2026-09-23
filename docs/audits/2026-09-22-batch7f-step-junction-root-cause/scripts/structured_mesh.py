"""Batch 7F Section 9: a DETERMINISTIC structured triangular mesh, built via
the SAME public devsim.create_gmsh_mesh()/add_gmsh_region()/add_gmsh_contact()
path tcad/device/devsim/mesh_import.py::import_process_result() already uses
in production (verified, not a new/private mechanism) -- chosen instead of
add_2d_mesh_line()/add_2d_region()/add_2d_contact() because that path's
contact-boundary matching could not be gotten to register any contact in
direct testing (0 contacts found regardless of bounding-box tolerance tried),
while create_gmsh_mesh() is already proven (capability spikes A/B, and this
project's own entire real-device test suite). Both are "DEVSIM public mesh
API" -- the bounded prompt names the requirement (public mesh API only), not
a specific function.

Building the triangulation by hand also gives EXACT, auditable control over
diagonal orientation (the bounded prompt's own requirement) -- something
DEVSIM's automatic 2D structured mesher would not expose or let this audit
verify.
"""
import numpy as np


def build_x_lines_um(band_half_width_um, band_spacing_um, x_extent_um, coarse_spacing_um):
    """Deterministic, symmetric x-line positions: uniform `band_spacing_um`
    inside the junction band [-band_half_width_um, +band_half_width_um]
    (always includes x=0.0 exactly), then a geometric doubling transition out
    to `coarse_spacing_um` for the rest of the half-extent. Symmetric about 0."""
    half_extent = x_extent_um / 2.0
    n_band = max(1, round(band_half_width_um / band_spacing_um))
    band_pts = np.linspace(-band_half_width_um, band_half_width_um, 2 * n_band + 1)

    # geometric transition from band edge to coarse_spacing_um, doubling each step
    transition = []
    pos = band_half_width_um
    step = band_spacing_um
    while pos < half_extent - coarse_spacing_um:
        step = min(step * 2.0, coarse_spacing_um)
        pos = pos + step
        if pos >= half_extent - coarse_spacing_um:
            break
        transition.append(pos)

    right = list(band_pts) + transition + [half_extent]
    right = sorted(set(round(v, 12) for v in right if v <= half_extent + 1e-12))
    left = sorted(-v for v in right if v > 1e-12)
    all_x = sorted(set(left + right))
    return np.array(all_x, dtype=np.float64)


def build_structured_triangulation(x_lines_um, y_extent_um, n_y, diagonal="fixed"):
    """Rectangular grid (x_lines_um) x (n_y+1 uniform y-lines spanning
    [-y_extent_um, 0]), each cell split into 2 triangles.
      diagonal="fixed": every cell split along the SAME diagonal (bottom-left
        to top-right).
      diagonal="alternating": cells alternate diagonal direction in a
        checkerboard pattern (control for diagonal-orientation sensitivity).
    Returns (points_um [N,2], triangles [M,3] int, tags [M] all-zero (single
    material)).
    """
    y_lines_um = np.linspace(-y_extent_um, 0.0, n_y + 1)
    nx, ny = len(x_lines_um), len(y_lines_um)
    points = np.array([[x, y] for y in y_lines_um for x in x_lines_um], dtype=np.float64)

    def idx(ix, iy):
        return iy * nx + ix

    triangles = []
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            v00, v10, v01, v11 = idx(ix, iy), idx(ix + 1, iy), idx(ix, iy + 1), idx(ix + 1, iy + 1)
            use_alt = (diagonal == "alternating") and ((ix + iy) % 2 == 1)
            if use_alt:
                # split along the OTHER diagonal (bottom-right to top-left)
                triangles.append((v00, v10, v01))
                triangles.append((v10, v11, v01))
            else:
                # fixed diagonal: bottom-left to top-right
                triangles.append((v00, v10, v11))
                triangles.append((v00, v11, v01))
    triangles = np.array(triangles, dtype=np.int64)
    tags = np.zeros(len(triangles), dtype=np.int64)
    return points, triangles, tags


def import_structured_device(module, points_um, triangles, tags, device_name, mesh_name,
                              length_scale_to_cm, region_name="Si"):
    """Import via the SAME public create_gmsh_mesh()/add_gmsh_region()/
    add_gmsh_contact() path import_process_result() uses (read only that
    function's own logic reused here, production code itself untouched)."""
    points_cm = points_um * length_scale_to_cm
    coords = []
    for x, y in points_cm:
        coords += [float(x), float(y), 0.0]

    elements = []
    for v0, v1, v2 in triangles:
        elements += [2, 0, int(v0), int(v1), int(v2)]

    # boundary edges (owned by exactly one triangle), split by xmin/xmax
    edge_owner = {}
    for ti, (v0, v1, v2) in enumerate(triangles):
        for a, b in ((int(v0), int(v1)), (int(v1), int(v2)), (int(v2), int(v0))):
            key = (a, b) if a < b else (b, a)
            edge_owner.setdefault(key, []).append(ti)
    boundary_edges = [e for e, owners in edge_owner.items() if len(owners) == 1]

    x_all = points_um[:, 0]
    xmin, xmax = x_all.min(), x_all.max()
    lo_edges = [e for e in boundary_edges if abs(x_all[e[0]] - xmin) < 1e-9 and abs(x_all[e[1]] - xmin) < 1e-9]
    hi_edges = [e for e in boundary_edges if abs(x_all[e[0]] - xmax) < 1e-9 and abs(x_all[e[1]] - xmax) < 1e-9]

    physical_names = [region_name]
    contact_defs = []
    if lo_edges:
        physical_names.append(f"{region_name}_xmin")
        idx_c = len(physical_names) - 1
        for e in lo_edges:
            elements += [1, idx_c, e[0], e[1]]
        contact_defs.append(f"{region_name}_xmin")
    if hi_edges:
        physical_names.append(f"{region_name}_xmax")
        idx_c = len(physical_names) - 1
        for e in hi_edges:
            elements += [1, idx_c, e[0], e[1]]
        contact_defs.append(f"{region_name}_xmax")

    module.create_gmsh_mesh(mesh=mesh_name, coordinates=coords, elements=elements, physical_names=physical_names)
    module.add_gmsh_region(gmsh_name=region_name, mesh=mesh_name, region=region_name, material=region_name)
    for cname in contact_defs:
        module.add_gmsh_contact(gmsh_name=cname, mesh=mesh_name, name=cname, material="metal", region=region_name)
    module.finalize_mesh(mesh=mesh_name)
    module.create_device(mesh=mesh_name, device=device_name)
    return region_name, mesh_name, contact_defs
