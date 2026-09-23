"""Batch 7G Phase 1: pure-numpy geometry checks over raw (points, triangles, tags)
arrays -- no DevSim needed for anything in this file. Distinguishes, and never
conflates, the following terms (per this batch's own instruction 2):

  thin/sliver triangle           -- a triangle with a very small min angle
  obtuse triangle                -- a triangle with one angle > 90 deg
  circumcenter outside triangle  -- exactly what it says; obtuse triangles
                                     always have this, but so can some non-obtuse
                                     ones near degeneracy
  locally non-Delaunay interior edge
                                  -- an INTERIOR (2-triangle-owned), UNCONSTRAINED
                                     edge whose opposite angles sum to > pi
                                     (equivalently, the incircle test flags it)
  hanging node / T-junction      -- a node that lies on the OPEN interior of an
                                     edge of a triangle it is not a vertex of
  overlapping triangles          -- two NON-adjacent triangles whose interiors
                                     share positive area
  mesh hole                      -- boundary-loop-enclosed area not covered by
                                     any triangle

Fixed, pre-declared tolerances (never adjusted after seeing real-mesh results --
see this module's own CONSTANTS section and case_manifest_7g.py, which records
them for the record):
  COORD_TOL_REL   = 1e-9   -- relative to the mesh's own coordinate scale, for
                              coincidence / collinearity tests (float64 has ~1e-15
                              relative precision; this project's own established
                              float32-mesh-roundtrip tolerance work, referenced in
                              doping_mapping.py's _float32_roundtrip_ulp_um(), is
                              ~1e-7 relative for float32-origin coordinates -- 1e-9
                              is comfortably tighter than that source of noise
                              while remaining far looser than float64 machine eps)
  DELAUNAY_ANGLE_SLACK_RAD = 1e-9  -- an edge is flagged only when alpha+beta
                              EXCEEDS pi by more than this many radians, so
                              exact-Delaunay (alpha+beta==pi, e.g. two right
                              triangles from a rectangle split either way) is
                              never a false positive.
"""
import numpy as np

COORD_TOL_REL = 1e-9
DELAUNAY_ANGLE_SLACK_RAD = 1e-9


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _scale(points):
    if len(points) == 0:
        return 1.0
    span = points[:, :2].max(axis=0) - points[:, :2].min(axis=0)
    return float(max(span.max(), 1e-300))


def build_topology(triangles):
    """edge_key -> list of (triangle_index, opposite_vertex_local_index)."""
    edge_owners = {}
    for ti, tri in enumerate(triangles):
        v0, v1, v2 = int(tri[0]), int(tri[1]), int(tri[2])
        for (a, b), opp in (((v0, v1), 2), ((v1, v2), 0), ((v2, v0), 1)):
            edge_owners.setdefault(_edge_key(a, b), []).append((ti, opp))
    return edge_owners


def triangle_angles_deg(p0, p1, p2):
    def angle_at(a, b, c):
        v1, v2 = b - a, c - a
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-300)
        cosang = max(-1.0, min(1.0, cosang))
        return np.degrees(np.arccos(cosang))
    return angle_at(p0, p1, p2), angle_at(p1, p2, p0), angle_at(p2, p0, p1)


def triangle_signed_area(p0, p1, p2):
    return 0.5 * ((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]))


def circumcenter_and_radius(p0, p1, p2):
    ax, ay = p0
    bx, by = p1
    cx, cy = p2
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-300:
        return None, None
    ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d
    uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    r = np.hypot(ux - ax, uy - ay)
    return np.array([ux, uy]), r


def point_in_triangle(pt, p0, p1, p2):
    """Barycentric-sign test, orientation-agnostic."""
    def sign(a, b, c):
        return (a[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (a[1] - c[1])
    d1 = sign(pt, p0, p1)
    d2 = sign(pt, p1, p2)
    d3 = sign(pt, p2, p0)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def incircle_test(pa, pb, pc, pd):
    """Classic orientation-aware incircle determinant (Shewchuk-style, not
    exact-arithmetic, but numerically fine at this project's coordinate
    scale): pa,pb,pc must be CCW. Returns >0 if pd is strictly INSIDE the
    circumcircle of pa,pb,pc (i.e. the (pa,pb,pc)/(pb,pa? no) diagonal
    a-c is NOT locally Delaunay w.r.t. pd -- used as a cross-check against
    the angle-sum test, never the sole criterion."""
    ax, ay = pa[0] - pd[0], pa[1] - pd[1]
    bx, by = pb[0] - pd[0], pb[1] - pd[1]
    cx, cy = pc[0] - pd[0], pc[1] - pd[1]
    det = (
        (ax * ax + ay * ay) * (bx * cy - by * cx)
        - (bx * bx + by * by) * (ax * cy - ay * cx)
        + (cx * cx + cy * cy) * (ax * by - ay * bx)
    )
    return det


def local_delaunay_check(points, triangles, tags):
    """For every INTERIOR, UNCONSTRAINED (same-material, 2-owner) edge,
    compute alpha+beta (opposite angles) and the incircle cross-check.
    Constrained edges (boundary, material-interface) are returned
    SEPARATELY, never classified as violations or flip candidates."""
    edge_owners = build_topology(triangles)
    interior_unconstrained = []
    constrained = []
    for key, owners in edge_owners.items():
        if len(owners) != 2:
            constrained.append({"edge": key, "kind": "boundary", "n_owners": len(owners)})
            continue
        (t1, opp1), (t2, opp2) = owners
        if tags[t1] != tags[t2]:
            constrained.append({"edge": key, "kind": "material_interface", "n_owners": 2, "tags": (int(tags[t1]), int(tags[t2]))})
            continue
        a, b = key
        v1 = [v for v in triangles[t1] if v not in key][0] if opp1 is not None else None
        # opposite vertex is exactly triangles[t][opp]
        opp_v1 = int(triangles[t1][opp1])
        opp_v2 = int(triangles[t2][opp2])
        p_a, p_b = points[a][:2], points[b][:2]
        p_opp1, p_opp2 = points[opp_v1][:2], points[opp_v2][:2]
        # opposite angle at opp1 (angle a-opp1-b), and at opp2 (angle a-opp2-b)
        def angle_at(apex, x, y):
            v1_, v2_ = x - apex, y - apex
            cosang = np.dot(v1_, v2_) / (np.linalg.norm(v1_) * np.linalg.norm(v2_) + 1e-300)
            cosang = max(-1.0, min(1.0, cosang))
            return np.arccos(cosang)
        alpha = angle_at(p_opp1, p_a, p_b)
        beta = angle_at(p_opp2, p_a, p_b)
        severity = (alpha + beta) - np.pi
        violation = severity > DELAUNAY_ANGLE_SLACK_RAD
        # cross-check via incircle determinant (orientation-normalized on the
        # SPECIFIC triple (p_a, p_b, p_opp1) itself -- not inferred from t1's
        # raw stored vertex order, which need not match the (a,b) edge
        # traversal direction even when t1 itself is CCW).
        pa, pb, pc = p_a, p_b, p_opp1
        if triangle_signed_area(pa, pb, pc) < 0:
            pa, pb = pb, pa
        det = incircle_test(pa, pb, pc, p_opp2)
        incircle_violation = det > 0
        interior_unconstrained.append({
            "edge": key, "owners": (t1, t2), "opp_vertices": (opp_v1, opp_v2),
            "alpha_deg": float(np.degrees(alpha)), "beta_deg": float(np.degrees(beta)),
            "severity_rad": float(severity), "angle_sum_violation": bool(violation),
            "incircle_violation": bool(incircle_violation),
            "midpoint": [(p_a[0] + p_b[0]) / 2.0, (p_a[1] + p_b[1]) / 2.0],
        })
    return interior_unconstrained, constrained


def triangle_geometry_table(points, triangles):
    out = []
    for ti, tri in enumerate(triangles):
        p0, p1, p2 = points[tri[0]][:2], points[tri[1]][:2], points[tri[2]][:2]
        angles = triangle_angles_deg(p0, p1, p2)
        cc, r = circumcenter_and_radius(p0, p1, p2)
        inside = point_in_triangle(cc, p0, p1, p2) if cc is not None else False
        max_angle = max(angles)
        classification = "obtuse" if max_angle > 90.0 + 1e-9 else ("right" if abs(max_angle - 90.0) <= 1e-6 else "acute")
        edges = [np.linalg.norm(p1 - p0), np.linalg.norm(p2 - p1), np.linalg.norm(p0 - p2)]
        shortest_edge = min(edges)
        out.append({
            "triangle": ti, "angles_deg": list(angles), "min_angle_deg": float(min(angles)),
            "classification": classification, "circumcenter": (cc.tolist() if cc is not None else None),
            "circumradius": (float(r) if r is not None else None), "circumcenter_inside": bool(inside),
            "circumradius_over_shortest_edge": (float(r / shortest_edge) if (r is not None and shortest_edge > 0) else None),
        })
    return out


def edge_cotangent_weights(points, triangles, tags):
    """cot(alpha)+cot(beta) per interior UNCONSTRAINED edge -- a standard
    FEM cotangent-Laplacian weight, reported here as a geometric indicator
    correlated with (never asserted to BE) DevSim's own internal dual-volume
    algorithm, which is private/internal and not accessed."""
    interior, _ = local_delaunay_check(points, triangles, tags)
    out = []
    for e in interior:
        cot_a = 1.0 / np.tan(np.radians(e["alpha_deg"])) if abs(np.radians(e["alpha_deg"])) > 1e-12 else float("inf")
        cot_b = 1.0 / np.tan(np.radians(e["beta_deg"])) if abs(np.radians(e["beta_deg"])) > 1e-12 else float("inf")
        w = cot_a + cot_b
        out.append({"edge": e["edge"], "cot_alpha": cot_a, "cot_beta": cot_b, "weight": w, "negative_candidate": bool(w < 0)})
    return out


class _SpatialGrid:
    """Deterministic uniform spatial bin index over 2D bounding boxes --
    used for BOTH the T-junction search and the triangle-overlap search so
    neither becomes an unbounded O(N^2)/O(N*E) scan on L5 (tens of
    thousands of nodes/triangles)."""

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


def hanging_node_check(points, triangles, tags, cell_size=None):
    """Every node checked against every OTHER edge it is not an endpoint of,
    for lying on that edge's OPEN interior (collinear + inside the bounding
    interval), via a deterministic spatial grid -- not O(N*E)."""
    edge_owners = build_topology(triangles)
    scale = _scale(points)
    tol = COORD_TOL_REL * scale
    if cell_size is None:
        lens = []
        for key in list(edge_owners.keys())[:2000]:
            a, b = key
            lens.append(np.linalg.norm(points[a][:2] - points[b][:2]))
        cell_size = (np.median(lens) if lens else scale * 0.01) * 4.0

    grid = _SpatialGrid(cell_size)
    edge_list = list(edge_owners.items())
    for idx, (key, owners) in enumerate(edge_list):
        a, b = key
        pa, pb = points[a][:2], points[b][:2]
        bbox = (min(pa[0], pb[0]) - tol, max(pa[0], pb[0]) + tol, min(pa[1], pb[1]) - tol, max(pa[1], pb[1]) + tol)
        grid.insert(idx, bbox)

    hanging = []
    node_bbox_pad = tol
    for node_id in range(len(points)):
        p = points[node_id][:2]
        bbox = (p[0] - node_bbox_pad, p[0] + node_bbox_pad, p[1] - node_bbox_pad, p[1] + node_bbox_pad)
        for idx in grid.candidates(bbox):
            key, owners = edge_list[idx]
            a, b = key
            if node_id == a or node_id == b:
                continue
            pa, pb = points[a][:2], points[b][:2]
            edge_vec = pb - pa
            edge_len = np.linalg.norm(edge_vec)
            if edge_len < 1e-300:
                continue
            t = np.dot(p - pa, edge_vec) / (edge_len * edge_len)
            if t <= 1e-9 or t >= 1.0 - 1e-9:
                continue  # not strictly interior to the segment (endpoints excluded)
            closest = pa + t * edge_vec
            dist = np.linalg.norm(p - closest)
            if dist < tol:
                # confirm the T-junction shape: this whole edge (a,b) has
                # only its own owners; check whether the OTHER side has
                # (a,node_id) and (node_id,b) as real mesh edges (the
                # classic split-one-side-only signature)
                split_present = _edge_key(a, node_id) in edge_owners and _edge_key(node_id, b) in edge_owners
                hanging.append({
                    "node": node_id, "node_xy": p.tolist(), "unsplit_edge": key,
                    "unsplit_edge_owners": owners, "t_param": float(t), "distance": float(dist),
                    "split_present_on_other_side": bool(split_present),
                })
    return hanging


def _clip_polygon(subject, clip):
    """Sutherland-Hodgman polygon clipping; clip must be CONVEX (a triangle
    always is). Returns the clipped polygon (list of 2D points), possibly
    empty."""
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
        if not input_list:
            continue
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


def triangle_overlap_check(points, triangles, tags):
    """Positive-area overlap between NON-adjacent (no shared vertex)
    triangle pairs, via a deterministic spatial grid (never O(N^2))."""
    n = len(triangles)
    centroids = points[triangles][:, :, :2].mean(axis=1)
    tri_bboxes = []
    for ti in range(n):
        pts = points[triangles[ti]][:, :2]
        tri_bboxes.append((pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()))
    areas = np.array([abs(triangle_signed_area(*points[triangles[ti]][:, :2])) for ti in range(n)])
    cell_size = max(np.median(np.sqrt(areas[areas > 0])) * 3.0, 1e-300) if (areas > 0).any() else 1.0

    grid = _SpatialGrid(cell_size)
    for ti in range(n):
        grid.insert(ti, tri_bboxes[ti])

    vertex_sets = [set(int(v) for v in tri) for tri in triangles]
    overlaps = []
    checked = set()
    for ti in range(n):
        for tj in grid.candidates(tri_bboxes[ti]):
            if tj <= ti:
                continue
            pair = (ti, tj)
            if pair in checked:
                continue
            checked.add(pair)
            if vertex_sets[ti] & vertex_sets[tj]:
                continue  # share a vertex/edge -- adjacency, not overlap
            p_i = [points[v][:2] for v in triangles[ti]]
            p_j = [points[v][:2] for v in triangles[tj]]
            if not (triangle_signed_area(*p_i) > 0):
                p_i = p_i[::-1]
            if not (triangle_signed_area(*p_j) > 0):
                p_j = p_j[::-1]
            clipped = _clip_polygon(p_i, p_j)
            area = _polygon_area(clipped)
            if area > 1e-20:
                overlaps.append({"triangles": (ti, tj), "overlap_area": float(area), "centroid_i": centroids[ti].tolist(), "centroid_j": centroids[tj].tolist()})
    return overlaps, len(checked)


def boundary_loops_and_hole_check(points, triangles):
    edge_owners = build_topology(triangles)
    boundary_edges = {key: owners for key, owners in edge_owners.items() if len(owners) == 1}
    adj = {}
    for a, b in boundary_edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    visited_edges = set()
    loops = []
    for start_edge in boundary_edges:
        if start_edge in visited_edges:
            continue
        a0, b0 = start_edge
        loop = [a0, b0]
        visited_edges.add(start_edge)
        cur = b0
        prev = a0
        while cur != a0:
            nxts = [x for x in adj.get(cur, []) if x != prev]
            if not nxts:
                break
            nxt = nxts[0]
            key = _edge_key(cur, nxt)
            if key in visited_edges:
                nxts2 = [x for x in adj.get(cur, []) if x != prev and _edge_key(cur, x) not in visited_edges]
                if not nxts2:
                    break
                nxt = nxts2[0]
                key = _edge_key(cur, nxt)
            visited_edges.add(key)
            loop.append(nxt)
            prev, cur = cur, nxt
            if len(loop) > 2 * len(boundary_edges) + 10:
                break
        loops.append(loop)
    loop_areas = [_polygon_area([points[v][:2] for v in loop]) for loop in loops]
    tri_area_sum = float(sum(abs(triangle_signed_area(*points[tri][:, :2])) for tri in triangles))
    outer_idx = int(np.argmax(loop_areas)) if loop_areas else None
    outer_area = loop_areas[outer_idx] if outer_idx is not None else 0.0
    hole_area = outer_area - tri_area_sum
    return {
        "n_boundary_loops": len(loops), "loop_areas": loop_areas, "outer_loop_area": outer_area,
        "triangle_area_sum": tri_area_sum, "uncovered_hole_area": hole_area,
        "n_boundary_edges": len(boundary_edges),
    }
