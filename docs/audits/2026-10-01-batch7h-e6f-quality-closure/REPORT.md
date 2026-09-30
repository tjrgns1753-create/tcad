# Batch 7H-E6F interim REPORT: red promotion and blue candidate, both rejected; production unchanged

**Verdict**
- The red-promotion candidate was already out of the production candidates.
- The **blue candidate is also rejected.** At the GUI default scale its closure reached 1,350,067 triangles by pass 2 and stopped at the
  400,000 cap. The old production code reaches 124,000 after all 4 passes.
- The cause is shared by both candidates. They require every child to be exactly non-obtuse. On float32 ViennaPS meshes, whose cells are
  square only to ~1e-7, the only split that satisfies that exactly is the red (similar) split. Red splits both legs, and that cascades
  through the mesh.
- `tcad/device/devsim/mesh_refine.py` is unchanged (semantic diff 0).

## 1. Modules and state
**Production state.**
- `mesh_refine.py` HEAD blob (LF) sha256 `e6b356689941bd3333813a33380de2a9e9d5bb62f0c7c98d832270cdfa52613f`.
- The working copy is CRLF (`dd959689…`) under the system `core.autocrlf=true`, as before this batch.
- `git status` shows no change.

**Audit modules** (LF sha256; all under `scripts/`):
| name | file | sha256 | origin |
|---|---|---|---|
| old | `refine_old.py` | `e6b35668…` | byte copy of production `mesh_refine.py` at `0ef6dd2` |
| red | `refine_red.py` | `92fdb268…` | old + `red_promotion_attempt.patch` (`d7f6aabc…`: exact green-child check, float64 coordinates) |
| blue prototype | `alt_rgb_e6f.py` | `cb2db6af…` | sweep closure; the reference semantics |
| blue | `refine_blue.py` | `41c2e062…` | same decision rule, with caches, a work queue and float sign screening (exact fallback) |

**Correction.** The first evaluation run (`eval_e6f_run1_INCOMPLETE.log`, sha `af709788…`) built "old" by setting the red module's
green test to always pass. That shares red's float64 coordinates, so it is **not a byte-equal production baseline**. The small baselines
were re-run with the real `refine_old` (`eval2_small.json`). Its sizes and obtuse counts equal run 1's (grid 340 / 860 / 2860 with 20 /
60 / 140 obtuse; B 1040 with 120 obtuse). Run 1 was stopped by PID during its last case (GUI wafer, prototype blue). That case is marked
INCOMPLETE, and its JSON was never flushed; the log is kept.

## 2. What the blue candidate guarantees (from the code and small counterexamples)
- **Reference edge.** It is the longest edge by exact squared length. Ties go to the first maximum in the order (v0,v1), (v1,v2),
  (v2,v0): deterministic for a given vertex order, not orientation-invariant. For right triangles the hypotenuse is strictly longest,
  so no tie arises.
- **Multiple passes.** Each pass treats every triangle as new. There is no reference-edge or newest-vertex memory across passes, so it
  is **not** the literature's RGB / newest-vertex bisection, only a quality-driven red/green/blue closure.
- **Termination.** The set of scheduled edges only grows and is finite.
- **Uniqueness: none.** The decision is not monotone. With one broken leg a triangle becomes blue (scheduling only the hypotenuse); with
  two broken non-longest edges it becomes red (scheduling all three). So the fixed point depends on processing order.
  - On B_raw at 1e16, the sweep prototype gave 743 / 2767 triangles and the queue version 735 / 2721. Both passed every geometric check.
  - Example: triangle (1.0,-1.0), (1.2,-0.8), (1.0,-0.8) became red in the sweep and blue in the queue.
  - All other small fixtures gave identical arrays in both versions.
- **Non-obtuse output.** Green and blue are accepted only if all children are exactly non-obtuse; red of a non-obtuse parent is similar
  to it. So a non-obtuse input gives a non-obtuse output, **provided the midpoints are exact** (float64 midpoints of float32 values are).
  - An obtuse input is not repaired. The mis-built "equilateral lattice" fixture turned out to be 128 of 128 obtuse at input, and its
    outputs stay obtuse (2028); this demonstrates only that limitation.
- **Locality: none in general.** On exact squares (integer grid), blue is local: a 20x20 grid with an 80-triangle seed gives red 80,
  green 40, blue 40, 1160 output triangles. With cell height 1 + 2^-20 it becomes red 782, untouched 0, 3182 output triangles.
  - The mechanism: for a right triangle, the hypotenuse midpoint N is the circumcenter, so angle ANB = 2 x angle ACB. That is 90 degrees
    only for an exactly isosceles parent. Any non-red split of a nearly isosceles right triangle therefore has a 90 +/- epsilon child.
  - B_raw has 5 distinct exact cell widths (0.19999993 to 0.20000005).
  - Accepting epsilon is not an option: DEVSIM's F3 NodeVolume over-integrates by ~epsilon, about 1e-7 relative, which the unchanged
    area gate (budget ~1e-14) refuses.

## 3. Results
**Small fixtures, full exact check** (`eval2_small.json`, sha `6bcf1ac5…`). The checks: obtuse, degenerate, orientation, duplicate
triangles and coordinates, edge owners and directions, hanging nodes (exact point-in-edge), child tag against the containing parent,
exact area per tag, outer / interface segment preservation (spatial index), existing nodes, and target resolution against the old
module.

| case | old | red | blue |
|---|---|---|---|
| 2-cell counterexample | 9 tri, **1 obtuse** | 12, 0 | 11, 0 |
| 10x10, 3 passes | 2860, 140 | 11180, 0 | 3260, 0 |
| 10x10 graded (3 windows) | 1180, 140 | 10116, 0 | 1460, 0 |
| two materials, window on the interface, 2 passes | 216, 24 | 608, 0 | 264, 0 |
| identity (all false) | 48 = input | 48 | 48 |
| B_raw 1e16 (production predicates) | 1040, 120 | 3200, 0 | 2721 (proto 2767), 0 |

- In every case: hanging nodes 0, child tag mismatches 0, duplicates 0, area per tag equal, boundary / interface segments preserved,
  existing nodes preserved, and target resolution at least the old module's.
- Timings are split per case in the JSON (generation / exact geometry / boundary / other). For example, on B_raw blue took 0.058 s to
  generate, 0.665 s for the exact geometry and 0.016 s for the boundary check. Exact geometry is the dominant cost everywhere.

**GUI default scale, blue, one remote run** (36730397379, pure geometry, exec SHA `b804f45`).
- Input: E6A `wafer_volume.vtu` (40,000 triangles, sha `cfae97d4…`) with the GUI-default 1e20 windows, giving 4 production predicates.

| pass | marked | red / green / blue / untouched | output triangles | refined outside the predicate | wall |
|---|---|---|---|---|---|
| 0 | 1,600 | 18,625 / 1,375 / 4,140 / 15,860 | 105,530 | 22,540 | 2.31 s |
| 1 | 3,200 | 73,215 / 2,782 / 18,706 / 10,827 | 365,369 | 91,503 | 9.38 s |
| 2 | 6,400 | 286,331 / 4,131 / 60,787 / 14,120 | would be 1,350,067 | 344,849 | 32.18 s -> **RESOURCE_LIMIT** (no array built) |

- The old module on the same input: 45,600 / 56,800 / 79,200 / 124,000 triangles.
- Exact geometry was NOT_VERIFIED for this case.
- Blue fails decision criterion 3 (it does not finish within budget at the default scale) and shows exactly the global spread explained
  in section 2. It is **not** retained as a production candidate.

## 4. Why local refinement cannot be kept by closure rules on these meshes, and what another construction would need
- The inputs are structured right-triangle grids whose float32 cells are only approximately square.
- DEVSIM integrates with F3, which over-counts any obtuse angle, even one of 90 + 1e-7 degrees.
- Under the unchanged area gate, a split is admissible only if it is exactly non-obtuse. For these triangles that leaves only similar
  (red) splits, and red closure is not local.

Options that keep the gate and DEVSIM unchanged, each needing its own approval:
- **(a) Transition templates on the grid lines.** Build the refined mesh from the grid lines with non-obtuse transition templates
  (the 7H-E4 / E6A family, 0 obtuse by construction on the GUI-default mesh). This needs a structured-input detector and a new builder in
  place of `refine_mesh_near` for such inputs. It is a new mesh construction, not a closure rule.
- **(b) Snap to exactly square dyadic grid lines before refining.** This moves nodes, which conflicts with the "existing nodes
  preserved" contract.
- **(c) Accept the obtuse children.** This requires a different volume rule (F2) inside DEVSIM, which is out of scope.

Nothing here claims DEVSIM import, solve or PN accuracy.
