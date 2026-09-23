"""Paired pre/post etch diagnostics on tagged 2D triangle meshes.

This is a DIAGNOSTIC, not a physics model. It never changes what an etch did; it reports only what the two
EXPORTED VOLUME MESHES prove, and it refuses to produce a number whenever the pre/post correspondence is not
unambiguous. Every result carries ``evidence_source = "exported_volume_mesh"``: the GUI path holds no native
level-set domain, so nothing here says anything about native geometry, about how much material "really" remains,
about exporter artifacts, or about numerical noise.

Vocabulary (one contract state per material per window, see ``MaterialResult.contract_state``):

``FULLY_CLEARED_IN_WINDOW``          pre has a positive-area intersection with the window, post has none anywhere in it.
``CENTER_CLEARED_RESIDUAL_REMAINS``  the material is gone from the paired window-centre span AND positive-area
                                     residual remains elsewhere in the window; both facts are kept, with metadata.
``POST_ONLY_RESIDUAL``               pre has no window intersection, post has one. Physical creation, exposure or
                                     motion is NOT inferred.
``PAIRED_VERTICAL_DISPLACEMENT``     the centre-connected paired flat run (vertical displacement only); the detailed
                                     status is ``ETCHED`` / ``UNCHANGED`` (with a reach) / ``ROSE_OR_INDETERMINATE``.
``AMBIGUOUS``                        the pairing is not proven; no number.

Topology, not tolerances, decides what is one body: material triangles are connected only through a COMPLETE shared
edge (same two point indices, same material). Sharing a single vertex, or touching along a T-junction, is not
connectivity, and no geometry epsilon ever merges two bodies. Every vertical section keeps the component id that
produced it; a paired run whose pre or post component id changes is ``AMBIGUOUS``.

What is deliberately NOT here (each was a measured failure of the earlier node-``max(y)`` diagnostic, see
docs/audits/2026-09-21-batch3-logger-shoulder/): material presence read from mesh vertices; a window-wide maximum;
independent pre/post feature selection; "displacement is small => the etch has not reached this material"; and any
size cutoff that would drop or ignore a residual.

Two epsilons are kept strictly apart:

``geometry epsilon``
    Derived from float32 coordinate spacing (the exported meshes are float32): 4 ulps of the largest coordinate.
    It only decides whether two coordinates are the same point and whether a clipped polygon has numerically
    positive area (a triangle that merely touches the slab boundary clips to zero area up to rounding). It is not a
    size cutoff for residuals: at 1.9e-6 um it is far below every residual measured so far (>= 5.5e-5 um wide).
``DIAGNOSTIC_TOLERANCE_UM``
    The project's existing diagnostic COMPARISON tolerance (the old logger's noise floor, ``UNCHANGED_UM`` in
    tests/integration/_explicit_etch_fixture.py). It decides whether two top heights count as "the same" for this
    diagnostic. It is NOT a physical or vertical resolution of the level-set / mesh.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

DIAGNOSTIC_TOLERANCE_UM = 0.001
_FLOAT32_ULP_REL = 2.0 ** -23

#: where every statement of this module comes from (structured key / human text)
EVIDENCE_SOURCE = "exported_volume_mesh"
EVIDENCE_SOURCE_TEXT = "exported volume mesh"

# contract states
FULLY_CLEARED_IN_WINDOW = "fully_cleared_in_window"
CENTER_CLEARED_RESIDUAL_REMAINS = "center_cleared_residual_remains"
POST_ONLY_RESIDUAL = "post_only_residual"
PAIRED_VERTICAL_DISPLACEMENT = "paired_vertical_displacement"
AMBIGUOUS = "ambiguous"

# detailed statuses of the paired-displacement family (contract_state == PAIRED_VERTICAL_DISPLACEMENT for the first two)
ETCHED = "etched"
UNCHANGED = "unchanged"
ROSE_OR_INDETERMINATE = "rose_or_indeterminate"          # no number; contract_state == AMBIGUOUS

# reach of an UNCHANGED material, judged on the post mesh over the whole measured run
REACH_EXPOSED = "exposed"
REACH_OVERLAIN = "overlain"
REACH_UNKNOWN = "cannot_be_inferred"

_SINGLE, _ABSENT, _OTHER = "single", "absent", "other"


@dataclass(frozen=True)
class TaggedMesh:
    """A 2D triangle mesh with one material name per triangle (only x, y are used). ``triangles`` holds POINT
    INDICES; two triangles are connected only if they share the same two point indices of an edge."""
    points: np.ndarray
    triangles: np.ndarray
    materials: Tuple[str, ...]

    def __post_init__(self):
        if len(self.materials) != len(self.triangles):
            raise ValueError("one material name per triangle is required")


@dataclass(frozen=True)
class ResidualComponent:
    """One material component (shared-edge connected) that has positive-area intersection with the window."""
    clipped_area_um2: float
    clipped_x_extent_um: Tuple[float, float]
    clipped_y_extent_um: Tuple[float, float]
    touches_left_window_edge: bool
    touches_right_window_edge: bool
    whole_mesh_triangle_count: int
    triangles_intersecting_window: int
    #: True iff EVERY triangle of the whole material component lies inside or on the boundary of the window, i.e.
    #: no triangle of the component has positive area outside the window.
    isolated_island: bool


@dataclass(frozen=True)
class Residual:
    """All positive-area window intersection of one material in the post mesh (no size cutoff)."""
    total_clipped_area_um2: float
    x_extent_um: Tuple[float, float]
    y_extent_um: Tuple[float, float]
    touches_left_window_edge: bool
    touches_right_window_edge: bool
    component_count: int
    components: Tuple[ResidualComponent, ...]
    evidence_source: str = EVIDENCE_SOURCE


@dataclass(frozen=True)
class MaterialResult:
    material: str
    status: str
    window_um: Tuple[float, float]
    displacement_um: Optional[float] = None      # vertical flat-interior displacement, > 0 = top went down
    run_x_um: Optional[Tuple[float, float]] = None
    n_intervals: int = 0
    reach: Optional[str] = None                  # only for UNCHANGED
    reason: Optional[str] = None                 # why no number, when there is none
    post_top_range_um: Optional[Tuple[float, float]] = None
    center_clear_x_um: Optional[Tuple[float, float]] = None      # CENTER_CLEARED_RESIDUAL_REMAINS only
    n_center_clear_intervals: int = 0
    residual: Optional[Residual] = None          # CENTER_CLEARED_RESIDUAL_REMAINS and POST_ONLY_RESIDUAL
    evidence_source: str = EVIDENCE_SOURCE

    @property
    def contract_state(self) -> str:
        if self.status in (ETCHED, UNCHANGED):
            return PAIRED_VERTICAL_DISPLACEMENT
        if self.status == ROSE_OR_INDETERMINATE:
            return AMBIGUOUS
        return self.status


# --------------------------------------------------------------------------- topology
def triangle_components(mesh: TaggedMesh) -> np.ndarray:
    """Component id per triangle. Two triangles are in one component iff they are of the SAME material and share a
    COMPLETE edge (identical, sorted point-index pair). One shared vertex, or a T-junction, is not connectivity;
    no coordinate tolerance is applied."""
    tri = np.asarray(mesh.triangles, dtype=np.int64)
    n = len(tri)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    owner: Dict[Tuple[str, int, int], int] = {}
    for t in range(n):
        a, b, c = (int(v) for v in tri[t])
        for u, v in ((a, b), (b, c), (c, a)):
            if u == v:
                continue
            key = (mesh.materials[t], min(u, v), max(u, v))
            if key in owner:
                ra, rb = find(t), find(owner[key])
                if ra != rb:
                    parent[ra] = rb
            else:
                owner[key] = t
    roots = np.array([find(t) for t in range(n)], dtype=np.int64)
    return roots


# ------------------------------------------------------------------------ geometry helpers
class _Ctx:
    """One mesh restricted to the triangles that genuinely overlap the window slab, with component ids."""

    def __init__(self, mesh: TaggedMesh, lo: float, hi: float, eps: float):
        tri = np.asarray(mesh.triangles, dtype=np.int64)
        pts = np.asarray(mesh.points, dtype=np.float64)[:, :2]
        p = pts[tri]                                           # (M, 3, 2)
        minx, maxx = p[:, :, 0].min(axis=1), p[:, :, 0].max(axis=1)
        cid = triangle_components(mesh)
        # whole-component facts, over the FULL mesh (needed for the isolated-island definition)
        self.comp_size: Dict[int, int] = {}
        self.comp_minx: Dict[int, float] = {}
        self.comp_maxx: Dict[int, float] = {}
        for k in range(len(tri)):
            c = int(cid[k])
            self.comp_size[c] = self.comp_size.get(c, 0) + 1
            self.comp_minx[c] = min(self.comp_minx.get(c, np.inf), float(minx[k]))
            self.comp_maxx[c] = max(self.comp_maxx.get(c, -np.inf), float(maxx[k]))
        keep = (minx < hi - eps) & (maxx > lo + eps)
        self.p = p[keep]
        self.minx, self.maxx = minx[keep], maxx[keep]
        self.mat = np.asarray(mesh.materials, dtype=object)[keep]
        self.cid = cid[keep]
        self.eps = eps

    def crossings(self, lo: float, hi: float) -> Dict[str, List[tuple]]:
        """{material: [(local index, clipped area, clipped polygon), ...]} for triangles with positive-area
        intersection with the slab [lo, hi] (numerically positive: area > eps^2 and x-extent > eps)."""
        out: Dict[str, List[tuple]] = {}
        for k in range(len(self.p)):
            poly = _clipped_polygon(self.p[k], lo, hi)
            if len(poly) < 3:
                continue
            area = _polygon_area(poly)
            width = max(q[0] for q in poly) - min(q[0] for q in poly)
            if area > self.eps * self.eps and width > self.eps:
                out.setdefault(self.mat[k], []).append((k, area, poly))
        return out

    def sections(self, a: float, b: float) -> Dict[str, Dict[str, List[Tuple[float, float, int]]]]:
        """{material: {'a'|'m'|'b': [(ylo, yhi, component id), ...]}} for the interval (a, b).

        No triangle vertex lies strictly inside (a, b) (the caller's partition contains every vertex x), so every
        triangle that spans the interval has straight, non-crossing edges over it: three scanlines (both ends and
        the middle) characterise the top exactly. Vertical ranges are merged only WITHIN one component; ranges of
        different components are never merged, even when they touch."""
        eps = self.eps
        span = (self.minx <= a + eps) & (self.maxx >= b - eps)
        xs = {"a": a, "m": 0.5 * (a + b), "b": b}
        raw: Dict[str, Dict[str, List[Tuple[float, float, int]]]] = {}
        for k in np.nonzero(span)[0]:
            m = self.mat[k]
            for tag, x in xs.items():
                yr = _tri_yrange(self.p[k], x, eps)
                if yr is not None:
                    raw.setdefault(m, {"a": [], "m": [], "b": []})[tag].append((yr[0], yr[1], int(self.cid[k])))
        return {m: {tag: _merge_within_component(v, eps) for tag, v in d.items()} for m, d in raw.items()}


def _clip(poly, bound, keep_greater):
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        pin = p[0] >= bound if keep_greater else p[0] <= bound
        qin = q[0] >= bound if keep_greater else q[0] <= bound
        if pin:
            out.append(p)
        if pin != qin:
            t = (bound - p[0]) / (q[0] - p[0])
            out.append((bound, p[1] + t * (q[1] - p[1])))
    return out


def _clipped_polygon(tri, lo, hi):
    poly = [(float(tri[i][0]), float(tri[i][1])) for i in range(3)]
    poly = _clip(poly, lo, True)
    if poly:
        poly = _clip(poly, hi, False)
    return poly


def _polygon_area(poly) -> float:
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def _tri_yrange(tri, x, eps) -> Optional[Tuple[float, float]]:
    ys = []
    for i in range(3):
        x1, y1 = float(tri[i][0]), float(tri[i][1])
        x2, y2 = float(tri[(i + 1) % 3][0]), float(tri[(i + 1) % 3][1])
        lo_, hi_ = min(x1, x2), max(x1, x2)
        if x < lo_ - eps or x > hi_ + eps:
            continue
        if hi_ - lo_ <= eps:
            ys += [y1, y2]
        else:
            t = min(1.0, max(0.0, (x - x1) / (x2 - x1)))
            ys.append(y1 + t * (y2 - y1))
    return (min(ys), max(ys)) if ys else None


def _merge_within_component(ranges, eps):
    by: Dict[int, List[List[float]]] = {}
    for lo, hi, c in sorted(ranges, key=lambda r: (r[2], r[0])):
        seg = by.setdefault(c, [])
        if seg and lo <= seg[-1][1] + eps:
            seg[-1][1] = max(seg[-1][1], hi)
        else:
            seg.append([lo, hi])
    return sorted(((a, b, c) for c, segs in by.items() for a, b in segs), key=lambda r: (r[0], r[1], r[2]))


def _geometry_eps(meshes: Sequence[TaggedMesh], window: Tuple[float, float]) -> float:
    scale = max(abs(window[0]), abs(window[1]), 1e-30)
    for m in meshes:
        if len(m.points):
            scale = max(scale, float(np.abs(np.asarray(m.points)[:, :2]).max()))
    return 4.0 * _FLOAT32_ULP_REL * scale


# ---------------------------------------------------------------------------- residual metadata
def _residual(ctx: _Ctx, crossing: List[tuple], lo: float, hi: float, eps: float) -> Residual:
    """Metadata for EVERY positive-area window intersection of one material (no cutoff on width or area)."""
    by: Dict[int, List[tuple]] = {}
    for k, area, poly in crossing:
        by.setdefault(int(ctx.cid[k]), []).append((area, poly))
    comps = []
    for cid, items in by.items():
        xs = [q[0] for _, poly in items for q in poly]
        ys = [q[1] for _, poly in items for q in poly]
        comps.append(ResidualComponent(
            clipped_area_um2=sum(a for a, _ in items),
            clipped_x_extent_um=(min(xs), max(xs)), clipped_y_extent_um=(min(ys), max(ys)),
            touches_left_window_edge=any(abs(q[0] - lo) <= eps for _, poly in items for q in poly),
            touches_right_window_edge=any(abs(q[0] - hi) <= eps for _, poly in items for q in poly),
            whole_mesh_triangle_count=ctx.comp_size[cid], triangles_intersecting_window=len(items),
            isolated_island=bool(ctx.comp_minx[cid] >= lo - eps and ctx.comp_maxx[cid] <= hi + eps)))
    comps.sort(key=lambda c: (-c.clipped_area_um2, c.clipped_x_extent_um))
    ax = [v for c in comps for v in c.clipped_x_extent_um]
    ay = [v for c in comps for v in c.clipped_y_extent_um]
    return Residual(
        total_clipped_area_um2=sum(c.clipped_area_um2 for c in comps), x_extent_um=(min(ax), max(ax)),
        y_extent_um=(min(ay), max(ay)),
        touches_left_window_edge=any(c.touches_left_window_edge for c in comps),
        touches_right_window_edge=any(c.touches_right_window_edge for c in comps),
        component_count=len(comps), components=tuple(comps))


# --------------------------------------------------------------------------------- analysis
def _partition(ctxs: Sequence[_Ctx], lo: float, hi: float, eps: float) -> List[float]:
    xs = [lo, hi]
    for c in ctxs:
        v = c.p[:, :, 0].ravel()
        xs.extend(float(x) for x in v[(v > lo + eps) & (v < hi - eps)])
    xs.sort()
    out = [xs[0]]
    for x in xs[1:]:
        if x - out[-1] > eps:
            out.append(x)
    return out          # every interior vertex is < hi - eps, so `hi` is always the last entry


def analyze_window(pre: TaggedMesh, post: TaggedMesh, window: Tuple[float, float], *,
                   tolerance_um: float = DIAGNOSTIC_TOLERANCE_UM) -> List[MaterialResult]:
    lo, hi = float(window[0]), float(window[1])
    if not lo < hi:
        raise ValueError(f"empty window {window!r}")
    eps = _geometry_eps((pre, post), (lo, hi))
    cpre, cpost = _Ctx(pre, lo, hi, eps), _Ctx(post, lo, hi, eps)
    x_pre, x_post = cpre.crossings(lo, hi), cpost.crossings(lo, hi)
    in_pre, in_post = set(x_pre), set(x_post)
    results: List[MaterialResult] = []
    for m in sorted(in_pre - in_post):
        results.append(MaterialResult(m, FULLY_CLEARED_IN_WINDOW, (lo, hi)))
    for m in sorted(in_post - in_pre):
        results.append(MaterialResult(m, POST_ONLY_RESIDUAL, (lo, hi),
                                      residual=_residual(cpost, x_post[m], lo, hi, eps)))
    paired = sorted(in_pre & in_post)
    if paired:
        xs = _partition((cpre, cpost), lo, hi, eps)
        secs = [(cpre.sections(a, b), cpost.sections(a, b)) for a, b in zip(xs[:-1], xs[1:])]
        for m in paired:
            results.append(_paired(m, xs, secs, lo, hi, eps, tolerance_um, cpost, x_post[m]))
    return sorted(results, key=lambda r: r.material)


class _Side:
    """What one mesh shows for one material on one common interval, over the three scanlines."""
    __slots__ = ("kind", "tops", "cid", "note")

    def __init__(self, kind, tops=None, cid=None, note=None):
        self.kind, self.tops, self.cid, self.note = kind, tops, cid, note


def _side(sec, m) -> _Side:
    d = sec.get(m)
    lens = [len(d[t]) for t in ("a", "m", "b")] if d else [0, 0, 0]
    if not any(lens):
        return _Side(_ABSENT)
    if all(n == 1 for n in lens):
        cids = {d[t][0][2] for t in ("a", "m", "b")}
        if len(cids) == 1:
            return _Side(_SINGLE, [d[t][0][1] for t in ("a", "m", "b")], cids.pop())
        return _Side(_OTHER, note="the component id changes within one interval")
    return _Side(_OTHER, note="more than one vertical component (or a partial section) on a scanline")


def _paired(m, xs, secs, lo, hi, eps, tol, cpost, x_post_m) -> MaterialResult:
    n = len(secs)
    win = (lo, hi)
    pre_side = [_side(s[0], m) for s in secs]
    post_side = [_side(s[1], m) for s in secs]
    post_mid_tops = [s[1][m]["m"][0][1] for s in secs if m in s[1] and len(s[1][m]["m"]) == 1]
    top_range = (min(post_mid_tops), max(post_mid_tops)) if post_mid_tops else None

    def refuse(reason):
        return MaterialResult(m, AMBIGUOUS, win, reason=reason, post_top_range_um=top_range)

    xc = 0.5 * (lo + hi)
    centre = [i for i in range(n) if xs[i] - eps <= xc <= xs[i + 1] + eps]
    if not centre:
        return refuse("window midpoint is not covered by any common interval")
    if any(pre_side[i].kind != _SINGLE for i in centre):
        return refuse("in the pre mesh the material is absent or has more than one vertical component / component "
                      "at the window midpoint")
    post_kinds = {post_side[i].kind for i in centre}
    if post_kinds == {_SINGLE}:
        return _paired_displacement(m, xs, secs, pre_side, post_side, centre, lo, hi, eps, tol, top_range)
    if post_kinds == {_ABSENT}:
        return _center_clear(m, xs, pre_side, post_side, centre, lo, hi, eps, top_range, cpost, x_post_m)
    return refuse("in the post mesh the material is absent, has more than one vertical component, or the two sides "
                  "of a midpoint node disagree at the window midpoint")


def _paired_displacement(m, xs, secs, pre_side, post_side, centre, lo, hi, eps, tol, top_range) -> MaterialResult:
    n, win = len(pre_side), (lo, hi)

    def refuse(reason):
        return MaterialResult(m, AMBIGUOUS, win, reason=reason, post_top_range_um=top_range)

    c0 = centre[0]
    pre_ref, post_ref = pre_side[c0].tops[1], post_side[c0].tops[1]
    pre_cid, post_cid = pre_side[c0].cid, post_side[c0].cid
    if any(abs(pre_side[i].tops[1] - pre_ref) > tol or abs(post_side[i].tops[1] - post_ref) > tol
           or pre_side[i].cid != pre_cid or post_side[i].cid != post_cid for i in centre):
        return refuse("the window midpoint sits on a node whose two sides disagree")

    def flat(i):
        p, q = pre_side[i], post_side[i]
        if p.kind != _SINGLE or q.kind != _SINGLE:
            return False
        return all(abs(v - pre_ref) <= tol for v in p.tops) and all(abs(v - post_ref) <= tol for v in q.tops)

    if not all(flat(i) for i in centre):
        return refuse("no flat surface (pre and post) at the window midpoint")
    i0, i1 = min(centre), max(centre)
    for step in (-1, +1):
        i = i0 if step < 0 else i1
        while 0 <= i + step < n and flat(i + step):
            j = i + step
            if pre_side[j].cid != pre_cid or post_side[j].cid != post_cid:
                return refuse("the paired flat run passes from one material component to another "
                              "(pre or post component id changes; shared-edge topology)")
            i = j
        if step < 0:
            i0 = i
        else:
            i1 = i
    count = i1 - i0 + 1
    x0, x1 = xs[i0], xs[i1 + 1]
    if count < 2 or not x1 - x0 > eps:
        return refuse("fewer than two adjacent flat common intervals connected to the window midpoint")
    d = pre_ref - post_ref
    common = dict(window_um=win, run_x_um=(x0, x1), n_intervals=count, post_top_range_um=top_range)
    if d > tol:
        return MaterialResult(m, ETCHED, displacement_um=d, **common)
    if d < -tol:
        return MaterialResult(m, ROSE_OR_INDETERMINATE, displacement_um=d,
                              reason="post top is above the pre top in the paired flat interior", **common)
    return MaterialResult(m, UNCHANGED, displacement_um=d, reach=_reach(m, secs, i0, i1, eps), **common)


def _reach(m, secs, i0, i1, eps) -> str:
    """Reach of material `m` on the POST mesh over the WHOLE measured run: every common interval is inspected on
    all three scanlines (start, midpoint, end). The material's top is `exposed` when no other material lies above
    it, `overlain` when exactly one other component touches it from above (a further layer stacked on that
    overlayer does not matter), and anything else -- a gap above the top, several touching components, or a
    relation that differs between scanlines or intervals -- makes the whole run `cannot_be_inferred`."""
    kinds = set()
    for i in range(i0, i1 + 1):
        post = secs[i][1]
        for tag in ("a", "m", "b"):
            top = post[m][tag][0][1]
            touching = above_without_contact = 0
            for other, d in post.items():
                if other == m:
                    continue
                for ylo, yhi, _ in d[tag]:
                    if yhi > top + eps:
                        if ylo <= top + eps:
                            touching += 1
                        else:
                            above_without_contact += 1
            if touching == 0 and above_without_contact == 0:
                kinds.add(REACH_EXPOSED)
            elif touching == 1:
                kinds.add(REACH_OVERLAIN)
            else:
                kinds.add(REACH_UNKNOWN)
    return kinds.pop() if len(kinds) == 1 else REACH_UNKNOWN


def _center_clear(m, xs, pre_side, post_side, centre, lo, hi, eps, top_range, cpost, x_post_m) -> MaterialResult:
    n, win = len(pre_side), (lo, hi)

    def refuse(reason):
        return MaterialResult(m, AMBIGUOUS, win, reason=reason, post_top_range_um=top_range)

    pre_cid = pre_side[centre[0]].cid
    if any(pre_side[i].cid != pre_cid for i in centre):
        return refuse("the pre component changes at the window midpoint")

    def cleared(i):
        return pre_side[i].kind == _SINGLE and post_side[i].kind == _ABSENT

    i0, i1 = min(centre), max(centre)
    for step in (-1, +1):
        i = i0 if step < 0 else i1
        while 0 <= i + step < n and cleared(i + step):
            j = i + step
            if pre_side[j].cid != pre_cid:
                return refuse("the centre-clear span passes from one pre component to another "
                              "(shared-edge topology)")
            i = j
        if step < 0:
            i0 = i
        else:
            i1 = i
    count = i1 - i0 + 1
    x0, x1 = xs[i0], xs[i1 + 1]
    if count < 2 or not x1 - x0 > eps:
        return refuse("the centre-clear span is fewer than two common intervals wide")
    return MaterialResult(m, CENTER_CLEARED_RESIDUAL_REMAINS, win, center_clear_x_um=(x0, x1),
                          n_center_clear_intervals=count, post_top_range_um=top_range,
                          residual=_residual(cpost, x_post_m, lo, hi, eps))


def analyze_etch_windows(pre: TaggedMesh, post: TaggedMesh, windows: Sequence[Sequence[float]], *,
                         tolerance_um: float = DIAGNOSTIC_TOLERANCE_UM):
    """Each open window is analysed independently (nothing is shared between windows, including residual metadata).
    Returns [((lo, hi), [MaterialResult, ...]), ...]."""
    return [((float(w[0]), float(w[1])),
             analyze_window(pre, post, (float(w[0]), float(w[1])), tolerance_um=tolerance_um))
            for w in windows]
