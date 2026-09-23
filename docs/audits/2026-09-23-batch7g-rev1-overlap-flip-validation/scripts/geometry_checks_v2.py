"""Batch 7G Rev.1 Phase B: corrected audit geometry checker. A NEW file --
does not modify docs/audits/2026-09-23-batch7g-delaunay-refinement-spike/
scripts/geometry_checks.py, which stays byte-identical (verified at the end
of this batch's own run).

Fixes required by the bounded prompt over the Phase 1 checker:
  1. Triangles are handled as VERTEX-INDEX tuples throughout the pairwise
     classification (never `id()` of a coordinate slice -- see
     phase_a_reproduce_p0_bug.py / phase_a_l3_full_scan.py for the proof
     that Phase 1's `_would_overlap_any_other()` used an inert `id()`-vs-int
     comparison that never actually excluded shared-vertex/edge neighbors).
  2. Shared topology is classified into exactly one of:
       "duplicate"          -- same 3 vertex indices (any order)
       "shared_edge"         -- exactly 2 shared vertex indices
       "shared_vertex"        -- exactly 1 shared vertex index
       "disjoint"             -- 0 shared vertex indices
     -- never a blanket "any shared vertex -> skip".
  3. For "shared_edge": the two non-shared (opposite) vertices are checked
     for being on OPPOSITE sides of the shared edge's line (proper
     adjacency, zero true overlap) vs the SAME side (an invalid bow-tie/
     fold, genuine overlap) -- not assumed safe.
  4. For "shared_vertex" and "disjoint": full independent geometric
     intersection is always computed (never skipped outright).
  5. TWO independent positive-area-intersection methods:
       Method A: corrected Sutherland-Hodgman polygon clipping (index-based,
                 CCW-normalized, tolerance derived below).
       Method B: separating-axis theorem (SAT) over the 6 candidate edge-
                 normal axes of the two triangles -- a genuinely different
                 algorithm from polygon clipping, not a restatement of it.
     A pair is CONFIRMED_OVERLAP only when both methods agree it is
     positive-area; CONFIRMED_NO_OVERLAP only when both agree it is not;
     otherwise UNKNOWN (excluded from the overlap COUNT, reported
     separately -- never silently included as an overlap or excluded as a
     clean pair, per the bounded prompt's instruction 8).
  6. Overlap-area tolerance is DERIVED from this specific mesh's own
     coordinate dtype/precision and its own median edge length -- see
     `derive_overlap_area_tolerance()` -- fixed once, before ANY real-mesh
     result is inspected, never adjusted after seeing one.
  7. Duplicate triangles, non-manifold edges (owner count > 2), zero-area
     triangles, and inverted-orientation triangles are counted separately
     from "overlap".
  8. Hole check adds boundary-vertex degree (every boundary vertex must
     have degree exactly 2 within the boundary-edge graph for a simple
     closed loop) and connected-component counting on top of Phase 1's
     own outer_area-minus-triangle_area_sum scalar.
"""
import numpy as np

COORD_TOL_REL = 1e-9  # kept identical to Phase 1's own constant, for coincidence/collinearity only


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def triangle_signed_area(p0, p1, p2):
    return 0.5 * ((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]))


def build_topology(triangles):
    edge_owners = {}
    for ti, tri in enumerate(triangles):
        v0, v1, v2 = int(tri[0]), int(tri[1]), int(tri[2])
        for (a, b), opp in (((v0, v1), 2), ((v1, v2), 0), ((v2, v0), 1)):
            edge_owners.setdefault(_edge_key(a, b), []).append((ti, opp))
    return edge_owners


def derive_overlap_area_tolerance(points, triangles):
    """Derived ONCE from this mesh's own coordinate precision and scale --
    never tuned to a specific result. Returns (length_tol, area_tol, detail).

    length_tol: the coordinate round-trip/representation noise floor.
      - if `points` is a float32 array (as the real ViennaPS-imported mesh
        arrays are -- confirmed by direct inspection, see this batch's own
        Phase A diagnosis output, coordinates print as np.float32), use ONE
        float32 ULP at the mesh's own max-magnitude coordinate (mirrors this
        project's own established `_float32_roundtrip_ulp_um()` reasoning in
        tcad/device/devsim/doping_mapping.py: the noise floor scales with
        the coordinate's own magnitude, never a fixed constant).
      - if float64, use COORD_TOL_REL * mesh coordinate span (this project's
        own established relative-coincidence tolerance).
    area_tol: SAFETY_FACTOR * length_tol * median_edge_length -- bounds the
      area of a thin sliver polygon that clipping can spuriously produce
      along a touching (non-overlapping) shared boundary, given the
      triangle-triangle intersection polygon has at most 6 vertices (2
      triangles x 3 edges each, Sutherland-Hodgman worst case), so a
      SAFETY_FACTOR of 10 gives comfortable headroom over a single-edge
      sliver estimate without being tuned to any observed real value.
    """
    SAFETY_FACTOR = 10.0
    pts2 = np.asarray(points)[:, :2]
    span = float(max((pts2.max(axis=0) - pts2.min(axis=0)).max(), 1e-300))
    max_abs_coord = float(max(np.abs(pts2).max(), 1e-300))
    is_float32 = np.asarray(points).dtype == np.float32
    if is_float32:
        length_tol = float(np.spacing(np.float32(max_abs_coord)))
        basis = "float32_ulp_at_max_abs_coord"
    else:
        length_tol = COORD_TOL_REL * span
        basis = "COORD_TOL_REL_times_span"

    edge_owners = build_topology(triangles)
    lens = []
    for (a, b) in list(edge_owners.keys())[:5000]:
        lens.append(float(np.linalg.norm(pts2[a] - pts2[b])))
    median_edge_len = float(np.median(lens)) if lens else span * 0.01

    area_tol = SAFETY_FACTOR * length_tol * median_edge_len
    detail = {
        "dtype": str(np.asarray(points).dtype), "basis": basis, "max_abs_coord": max_abs_coord,
        "span": span, "length_tol": length_tol, "median_edge_len": median_edge_len,
        "safety_factor": SAFETY_FACTOR, "area_tol": area_tol,
    }
    return length_tol, area_tol, detail


def classify_pair_topology(tri_i, tri_j):
    """tri_i, tri_j: 3-index tuples. Returns one of
    'duplicate'/'shared_edge'/'shared_vertex'/'disjoint' plus the shared
    index set."""
    si, sj = set(int(v) for v in tri_i), set(int(v) for v in tri_j)
    shared = si & sj
    if len(shared) == 3:
        return "duplicate", shared
    if len(shared) == 2:
        return "shared_edge", shared
    if len(shared) == 1:
        return "shared_vertex", shared
    return "disjoint", shared


def _clip_polygon(subject, clip):
    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= -1e-15

    def intersect(p1, p2, a, b):
        A1, B1 = b[1] - a[1], a[0] - b[0]
        C1 = A1 * a[0] + B1 * a[1]
        A2, B2 = p2[1] - p1[1], p1[0] - p2[0]
        C2 = A2 * p1[0] + B2 * p1[1]
        det = A1 * B2 - A2 * B1
        if abs(det) < 1e-300:
            return p2
        x = (B2 * C1 - B1 * C2) / det
        y = (A1 * C2 - A2 * C1) / det
        return np.array([x, y])

    output = list(subject)
    for i in range(len(clip)):
        if not output:
            break
        a, b = clip[i], clip[(i + 1) % len(clip)]
        input_list = output
        output = []
        s = input_list[-1]
        for e in input_list:
            if inside(e, a, b):
                if not inside(s, a, b):
                    output.append(intersect(s, e, a, b))
                output.append(e)
            elif inside(s, a, b):
                output.append(intersect(s, e, a, b))
            s = e
    return output


def _polygon_area(poly):
    if len(poly) < 3:
        return 0.0
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def method_a_clip_area(p_i, p_j):
    """Sutherland-Hodgman, CCW-normalized. p_i/p_j: 3x2 arrays."""
    p_i = list(p_i)
    p_j = list(p_j)
    if triangle_signed_area(*p_i) < 0:
        p_i = p_i[::-1]
    if triangle_signed_area(*p_j) < 0:
        p_j = p_j[::-1]
    clipped = _clip_polygon(p_i, p_j)
    return _polygon_area(clipped), clipped


def method_b_sat_overlap_length(p_i, p_j):
    """Separating-axis theorem: returns the MINIMUM projected-overlap
    length across all 6 candidate axes (edge normals of both triangles).
    A value <= 0 means a genuine separating axis exists (no overlap,
    exact up to floating point). A value > 0 on EVERY axis means the two
    convex shapes have positive-area intersection (SAT is exact for
    convex polygons). This is algorithmically independent of clipping --
    no polygon is ever constructed."""
    p_i = np.asarray(p_i, dtype=float)
    p_j = np.asarray(p_j, dtype=float)
    min_overlap = None
    for pts in (p_i, p_j):
        for k in range(3):
            p1, p2 = pts[k], pts[(k + 1) % 3]
            edge = p2 - p1
            axis = np.array([-edge[1], edge[0]])
            norm = np.linalg.norm(axis)
            if norm < 1e-300:
                continue
            axis = axis / norm
            proj_i = p_i @ axis
            proj_j = p_j @ axis
            overlap = min(proj_i.max(), proj_j.max()) - max(proj_i.min(), proj_j.min())
            if min_overlap is None or overlap < min_overlap:
                min_overlap = overlap
    return float(min_overlap) if min_overlap is not None else 0.0


def shared_edge_is_proper_adjacency(points, tri_i, tri_j, shared_idx, length_tol):
    """For a shared_edge pair: are the two non-shared (opposite) vertices
    on OPPOSITE sides of the shared edge's line (proper mesh adjacency,
    zero true overlap by construction) or the SAME side (an invalid
    bow-tie/fold, genuine overlap)? Returns (is_proper, side_i, side_j)."""
    ea, eb = sorted(shared_idx)
    opp_i = [v for v in tri_i if int(v) not in shared_idx][0]
    opp_j = [v for v in tri_j if int(v) not in shared_idx][0]
    pa, pb = points[ea][:2], points[eb][:2]
    edge = pb - pa

    def side(p):
        v = np.asarray(p[:2]) - pa
        cross = edge[0] * v[1] - edge[1] * v[0]
        return cross

    si = side(points[opp_i])
    sj = side(points[opp_j])
    tol = length_tol * max(np.linalg.norm(edge), 1e-300)
    if abs(si) < tol or abs(sj) < tol:
        return None, si, sj  # degenerate/near-collinear -- can't classify confidently
    return (si * sj < 0), si, sj


def corrected_triangle_overlap_check(points, triangles, tags, exclude_pairs=None):
    """Full corrected pairwise overlap classification. `exclude_pairs`: a
    set of triangle indices to fully exclude from being checked AGAINST
    (e.g. the two old triangles a flip is about to replace) -- Phase C's
    own requirement 9 that the replaced pair itself must not be compared.
    Returns a dict with confirmed overlaps, unknowns, topology tallies,
    and mesh-quality counts (duplicate/non-manifold/zero-area/inverted)."""
    exclude_pairs = exclude_pairs or set()
    n = len(triangles)
    length_tol, area_tol, tol_detail = derive_overlap_area_tolerance(points, triangles)

    areas_signed = np.array([triangle_signed_area(*points[triangles[ti]][:, :2]) for ti in range(n)])
    zero_area = [ti for ti in range(n) if abs(areas_signed[ti]) < 1e-300]
    inverted = [ti for ti in range(n) if areas_signed[ti] < 0]

    edge_owners = build_topology(triangles)
    non_manifold_edges = [k for k, v in edge_owners.items() if len(v) > 2]

    tri_key = [tuple(sorted(int(v) for v in tri)) for tri in triangles]
    seen_keys = {}
    duplicates = []
    for ti, k in enumerate(tri_key):
        if k in seen_keys:
            duplicates.append((seen_keys[k], ti))
        else:
            seen_keys[k] = ti

    areas_abs = np.abs(areas_signed)
    tri_bboxes = []
    for ti in range(n):
        pts = points[triangles[ti]][:, :2]
        tri_bboxes.append((pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()))
    cell_size = max(float(np.median(np.sqrt(areas_abs[areas_abs > 0]))) * 3.0, 1e-300) if (areas_abs > 0).any() else 1.0

    grid = _SpatialGridV2(cell_size)  # defined later in this module; resolved at call time
    for ti in range(n):
        if ti in exclude_pairs:
            continue
        grid.insert(ti, tri_bboxes[ti])

    confirmed_overlaps = []
    unknowns = []
    topology_tally = {"duplicate": 0, "shared_edge": 0, "shared_vertex": 0, "disjoint": 0}
    boundary_contact_count = 0
    checked = set()
    for ti in range(n):
        if ti in exclude_pairs:
            continue
        for tj in grid.candidates(tri_bboxes[ti]):
            if tj <= ti or tj in exclude_pairs:
                continue
            pair = (ti, tj)
            if pair in checked:
                continue
            checked.add(pair)
            topo, shared_idx = classify_pair_topology(triangles[ti], triangles[tj])
            topology_tally[topo] += 1
            if topo == "duplicate":
                continue

            p_i = points[triangles[ti]][:, :2]
            p_j = points[triangles[tj]][:, :2]

            if topo == "shared_edge":
                is_proper, si, sj = shared_edge_is_proper_adjacency(points, triangles[ti], triangles[tj], shared_idx, length_tol)
                if is_proper is True:
                    boundary_contact_count += 1
                    continue  # proper adjacency -- zero true overlap by construction, not even clip-checked
                # is_proper is False (bow-tie) or None (degenerate/near-collinear) -- fall through to full check

            area_a, _clipped = method_a_clip_area(p_i, p_j)
            min_overlap_b = method_b_sat_overlap_length(p_i, p_j)

            a_says_overlap = area_a > area_tol
            b_says_overlap = min_overlap_b > length_tol

            if a_says_overlap and b_says_overlap:
                confirmed_overlaps.append({
                    "triangles": (ti, tj), "topology": topo, "area_clip": float(area_a),
                    "sat_min_overlap_length": float(min_overlap_b),
                })
            elif (not a_says_overlap) and (not b_says_overlap):
                if topo != "disjoint":
                    boundary_contact_count += 1
            else:
                unknowns.append({
                    "triangles": (ti, tj), "topology": topo, "area_clip": float(area_a),
                    "sat_min_overlap_length": float(min_overlap_b),
                    "note": "methods disagree -- excluded from confirmed overlap count",
                })

    return {
        "length_tol": length_tol, "area_tol": area_tol, "tolerance_detail": tol_detail,
        "confirmed_overlaps": confirmed_overlaps, "n_confirmed_overlaps": len(confirmed_overlaps),
        "unknown_pairs": unknowns, "n_unknown_pairs": len(unknowns),
        "topology_tally": topology_tally, "boundary_contact_count": boundary_contact_count,
        "n_pairs_checked": len(checked),
        "duplicate_triangles": duplicates, "n_duplicate_triangles": len(duplicates),
        "non_manifold_edges": non_manifold_edges, "n_non_manifold_edges": len(non_manifold_edges),
        "zero_area_triangles": zero_area, "n_zero_area_triangles": len(zero_area),
        "inverted_triangles": inverted, "n_inverted_triangles": len(inverted),
    }


class _SpatialGridV2:
    def __init__(self, cell_size):
        self.cell_size = max(cell_size, 1e-300)
        self.buckets = {}

    def _cells_for_bbox(self, xmin, xmax, ymin, ymax):
        cs = self.cell_size
        ix0, ix1 = int(np.floor(xmin / cs)), int(np.floor(xmax / cs))
        iy0, iy1 = int(np.floor(ymin / cs)), int(np.floor(ymax / cs))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                yield (ix, iy)

    def insert(self, key, bbox):
        for cell in self._cells_for_bbox(*bbox):
            self.buckets.setdefault(cell, []).append(key)

    def candidates(self, bbox):
        seen = set()
        for cell in self._cells_for_bbox(*bbox):
            for k in self.buckets.get(cell, ()):
                if k not in seen:
                    seen.add(k)
                    yield k


def corrected_hole_check(points, triangles):
    """Adds boundary-vertex degree + connected-component checks on top of
    the outer_area-minus-triangle_area_sum scalar (never used alone)."""
    edge_owners = build_topology(triangles)
    boundary_edges = {key: owners for key, owners in edge_owners.items() if len(owners) == 1}
    degree = {}
    for a, b in boundary_edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    non_degree_2 = {v: d for v, d in degree.items() if d != 2}

    adj = {}
    for a, b in boundary_edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    visited_nodes = set()
    components = []
    for start in adj:
        if start in visited_nodes:
            continue
        comp = set()
        stack = [start]
        while stack:
            u = stack.pop()
            if u in comp:
                continue
            comp.add(u)
            for w in adj.get(u, []):
                if w not in comp:
                    stack.append(w)
        visited_nodes |= comp
        components.append(comp)

    visited_edges = set()
    loops = []
    for start_edge in boundary_edges:
        if start_edge in visited_edges:
            continue
        a0, b0 = start_edge
        loop = [a0, b0]
        visited_edges.add(start_edge)
        cur, prev = b0, a0
        while cur != a0:
            nxts = [x for x in adj.get(cur, []) if x != prev and _edge_key(cur, x) not in visited_edges]
            if not nxts:
                nxts = [x for x in adj.get(cur, []) if x != prev]
                if not nxts:
                    break
            nxt = nxts[0]
            key = _edge_key(cur, nxt)
            visited_edges.add(key)
            loop.append(nxt)
            prev, cur = cur, nxt
            if len(loop) > 2 * len(boundary_edges) + 10:
                break
        loops.append(loop)

    def poly_area(loop):
        if len(loop) < 3:
            return 0.0
        a = 0.0
        n = len(loop)
        for i in range(n):
            x1, y1 = points[loop[i]][:2]
            x2, y2 = points[loop[(i + 1) % n]][:2]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0

    loop_areas = [poly_area(loop) for loop in loops]
    tri_area_sum = float(sum(abs(triangle_signed_area(*points[tri][:, :2])) for tri in triangles))
    outer_idx = int(np.argmax(loop_areas)) if loop_areas else None
    outer_area = loop_areas[outer_idx] if outer_idx is not None else 0.0
    hole_area = outer_area - tri_area_sum

    return {
        "n_boundary_loops": len(loops), "loop_areas": loop_areas, "outer_loop_area": outer_area,
        "triangle_area_sum": tri_area_sum, "uncovered_hole_area": hole_area,
        "n_boundary_edges": len(boundary_edges),
        "n_boundary_vertices_with_degree_ne_2": len(non_degree_2),
        "boundary_vertex_degree_problems": non_degree_2,
        "n_boundary_connected_components": len(components),
        "is_clean_manifold_boundary": (len(non_degree_2) == 0),
    }
