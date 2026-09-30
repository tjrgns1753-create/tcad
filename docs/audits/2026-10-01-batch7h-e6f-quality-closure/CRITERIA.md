# Batch 7H-E6F working memo: acceptance criteria, fixed before implementation and before any run

Base HEAD `0ef6dd29aaeba7a2109c8454c50e046cead0fb5a` (tracked dirty 0). Serena MCP was not connected (earlier CONNECT_TIMEOUT); the
callers were checked by `rg` and direct reading:
- `import_process_result` calls `refine_mesh_near` (explicit window) and `graded_refine_mesh_near` (auto from doping).
- `refine_process_result_for_implant_windows` calls `graded_refine_mesh_near` (the E6E-R1 B path).
- `tests/unit/test_mesh_refine_mock.py` and audit scripts also call it.

## Rule (quality-aware red-green closure in `_refine_once`)
A. Seed triangles are red, as before.
B. The conformity closure is unchanged: a triangle with >= 2 broken edges becomes red.
C. A triangle with exactly one broken edge is split virtually. The midpoint is computed exactly as the final split computes it: the
   same `(points[a] + points[b]) / 2.0` on the same dtype. The two green children are tested.
D. The parent is promoted to red if a child has an obtuse or right-degenerate angle or zero area. The test uses **exact rational
   arithmetic** on the float values: `Fraction(float(v))` dot and cross products. Obtuse means dot < 0; degenerate means cross == 0. A
   right angle (dot == 0) is allowed. There is no rounding to 90 degrees and no tolerance.
E. Steps B-D are iterated to a fixed point.
F. The final split uses the same midpoint coordinates the test used, cached once per edge.

**Stated before implementation.**
- The red (midpoint) split of a non-obtuse parent gives four children similar to the parent in exact arithmetic. With rounded
  midpoints they can deviate; every output is checked exactly, and any obtuse output is reported, not hidden.
- An input triangle that is already obtuse is not repaired: its red children stay obtuse, and its green children are refused (the
  parent becomes red). No repair of raw ViennaPS slivers (representative A) is claimed.
- The closure can spread beyond the requested window. The spread is measured and reported: triangles refined outside the predicate,
  and the node / triangle counts against the old algorithm.

## Acceptance (all required)
1. **Counterexample.** On the green-split counterexample (right triangle split on a leg), the old code produces an obtuse child. After
   the change, no new obtuse triangle is produced, measured exactly.
2. **Synthetic tests, pure.** Each case checks exact counts of obtuse, degenerate, duplicate and inverted triangles; conformity (every
   edge has <= 2 owners, both directions, the boundary chain is intact); the tag carried from each parent; exact per-region area;
   the geometric segment set of material and outer boundaries (every original boundary segment equals the union of its child
   segments, collinear, same endpoints); existing nodes unchanged in coordinates and order; no duplicate node coordinates; and target
   resolution (every triangle whose centroid matches the predicate in the old algorithm's final mesh has an old-algorithm-equal or
   finer max edge in the new one). The cases:
   - single pass and multi-pass;
   - graded consecutive windows;
   - two materials with the window straddling the interface;
   - an all-false predicate (identity);
   - a rotated and reflected structured input;
   - an obtuse input (limitation documented).
3. **Real B path (remote).** The B recipe goes through the production caller `refine_process_result_for_implant_windows`. Required:
   - every region passes the unchanged area gate;
   - raw / old refined / new refined compared on counts, angles, obtuse counts, area, NodeVolume sum, boundaries and target
     resolution;
   - the GUI path is shown to use the new mesh.
4. **Normal computation (remote).**
   - The existing small Laplace control, with tolerance 1e-9 V.
   - A new manufactured Poisson control on a structured non-obtuse mesh: -eps psi'' = rho with rho constant, psi(0) = psi(L) = 0,
     natural (zero-flux) top and bottom, exact psi = rho x (L - x) / (2 eps).
   - The Poisson source is assembled through a DEVSIM node model integrated with NodeVolume, and eps and rho are set with public
     parameters.
   - Pre-fixed tolerance: max |psi - exact| <= 1e-9 x max|exact|. This is not claimed as a derived bound. The FV scheme on this
     mesh is exact for a quadratic in x only if the dual cells are exact, which is exactly what the area gate checks, so a larger
     error is a failure.
   - This control is a numerical-equation check with a manufactured source. It is not PN validation.
5. **Blocking (remote).**
   - E6D G2 is still refused.
   - The P0 counterexample is still refused.
   - `MESH_AREA_UNCERTAINTY_TOO_LARGE` reaches the GUI (`last_physics_status`) and the CLI (exception) with 0 doping writes, 0 solves,
     no current, and cleanup ok.
6. **Resources.**
   - Node and triangle counts for B are computed locally first, from the committed B_raw evidence with the pure production caller.
   - Remote limits are 8 GiB and 90 min; B is ~1-10k triangles, so far below either.
   - Nothing is reduced to fit.

Not submitted as success if any of these holds: a criterion had to be relaxed; resolution was reduced; a boundary moved; the budget was
exceeded; or a failing test was assumed to be pre-existing. No full regression this round.
