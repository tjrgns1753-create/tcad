# Batch 7H-E2 ERRATUM

Written after Codex's partial-approval review. `PLAN.md`, `PLAN.sha256`, the raw remote JSON/NPZ/VTU and the hash-linked
`run.log` / `summary.json` are NOT changed. `e2_result.json`'s registered verdict strings (`FIRST_BAD_STAGE=1`,
`NO_ORIENTATION_EFFECT`, `SHAPE_CAUSE`) are left exactly as computed and reported; this erratum corrects how one of them
may be interpreted, and separates two things REPORT.md's prose ran together.

## 1. `NO_ORIENTATION_EFFECT` was not a valid experimental conclusion — corrected reading: `ORIENTATION_INCONCLUSIVE`

PLAN section 5 defined `NO_ORIENTATION_EFFECT` as "C_ccw equals C_rt within b_i at every node" and treated that equality as
evidence that orientation is not a cause. That inference needs the control to have actually changed something. It did not:

* `C_ccw` reoriented **0 of 247000** triangles (`n_triangles_reoriented: 0` in `e2_result.json`).
* `C_ccw.vtu` and `C_rt.vtu` are byte-identical (sha256 `82fa87b04f7fb212...` for both,
  `data/posthoc_orientation_check.txt`).
* Independently: every stored triangle in the ViennaPS-exported mesh and at every refinement stage is already
  counter-clockwise (40000/40000 at S0, 247000/247000 at S4, exact integer orientation test). The `all_ccw: false` E1 and
  E2 both reported comes from the vertex order DEVSIM's own `get_element_node_list` returns on import (123500 positive /
  123500 negative at S4), not from the mesh handed to it — confirmed by comparing the stored `.vtu` triangle list against
  DEVSIM's returned element list, which agree only as a multiset of sorted vertex triples, never in stored order.

So the C_ccw experiment applied a null intervention: comparing an unmodified input to itself and reporting "no difference"
is not evidence about orientation, it is a tautology. The registered PLAN rule (mechanical equality of two records) still
fired and still printed `NO_ORIENTATION_EFFECT`; that string is correct as a report of what the rule computed, but it is
**not** an experimental result and must not be read as "orientation was tested and ruled out". Corrected reading:
**`ORIENTATION_INCONCLUSIVE`** — the question of whether triangle winding contributes to the NodeVolume excess was not
answered by 7H-E2, because no control in that batch ever produced a mesh with different winding from the one under test.
(Separately, the analysis in section 4 below — that DEVSIM's NodeVolume equals the orientation-independent rule F3, whose
cotangent sign comes from a dot product rather than the stored winding — is real evidence bearing on the same question,
independent of the C_ccw control; it is not affected by this correction and is restated below.)

## 2. What the mechanism evidence does and does not cover

The chain **green bisection of the 200 boundary right triangles -> obtuse children -> DEVSIM's NodeVolume equals the
orientation-independent rule F3 (absolute element couples) -> volume-sum excess** is supported independently at every link,
by data not affected by the orientation-control flaw:

* Stage-by-stage: S0 ratio 1.0 exactly (0 obtuse); S1-S4 ratio rises monotonically with obtuse count (200, 600, 1400, 3000)
  and with `sum(F3-F2)/area` (0.005, 0.013, 0.028, 0.058) — matching to at least 12 significant figures at every stage.
* Lineage: the audit trace copy (proven array-equal to production `refine_mesh_near` at every stage, I1 in `e2_result.json`)
  shows every obtuse triangle at every stage descends from the same 200 S0 right triangles via green splits only, never a
  red split and never a pre-existing obtuse triangle.
* Formula cross-check: DEVSIM's own `NodeVolume` equals the independently-computed F3 rule to at most 4.0e-16 relative at
  every node of every stage (`f3_max_rel_error`), and the excess over the exact area equals `sum(F3-F2)` to within the
  pre-registered float-error budget tau at every stage (`excess_explained_by_F3_within_tau: true` throughout).

What is genuinely NOT independently demonstrated is the ABSENCE of an orientation contribution — see section 1. `SHAPE_CAUSE`
as registered should be read as "the shape/obtuse-triangle mechanism is demonstrated"; it should not be read as "and
orientation was shown to contribute nothing", since that second half rests on the flawed control.

## 3. Delaunay violations = 0 is not the same claim as obtuse = 0

The candidate `exact_flip` result (PLAN section 7) removed all 200 exact Delaunay violations and all 200 negative signed
edge-couple / node-volume entries — but **2800 obtuse triangles remained** (max angle 113.63 deg, down from 3000/133.15
deg), and the ratio was still 1.0201660424825372 (2.02% excess) against tau 8.26e-11, with donor and acceptor inventories
both 2.02% high (2.551196e11 vs an exact-dual reference of 2.500781e11 cm^-1). REPORT.md's section 7 already reported these
together with the rejection; this erratum makes explicit the general point for anyone reading only the summary line: a
Delaunay-satisfying (locally optimal) triangulation is not automatically a triangulation free of obtuse angles, and DEVSIM's
`NodeVolume = F3` rule inflates on ANY obtuse triangle, Delaunay-legal or not — flipping to restore the Delaunay property is
a different, weaker property than removing obtuse angles, and E2's candidate is a direct counter-example proving the two
are not equivalent.

## 4. F2 is a discrete-mesh integral, not a physical reference — and the x=0 node convention's effect is now measured

REPORT.md's section 7 table listed `exact_dual_F2` next to `continuum_N_x_25um2` without saying which one either quantity
is measuring or why they differ even before any refinement defect. Corrected framing:

* `continuum_N_x_25um2` = N x (25 um^2), the geometric area of one half-domain (x > 0 or x < 0) if the junction were a
  zero-width line with no node sitting exactly on it. It is a **geometric reference**, not a DEVSIM quantity.
* `exact_dual_F2` = sum over EVERY node of (per-node concentration array) x (F2, the exact signed-circumcentric dual area at
  that node on the given mesh). F2 sums to the exact triangle area at every node regardless of triangle shape (proven in
  7H-B), so this is the **exact discrete-mesh integral of the SAME per-node concentration array DEVSIM would multiply by
  NodeVolume** — orientation- and obtuse-shape-independent, but still a property of a particular finite mesh's node
  positions and cell boundaries, not an independent physical ground truth. Neither quantity is "the correct physical
  answer"; they measure different things (a continuum idealization vs. a discrete dual-mesh integral of a discrete node
  array), and this erratum stops calling either one that.

**The x=0 junction-line node contribution, quantified directly from the E1 raw per-node arrays (read-only, no new
computation)**: every one of the 1601 nodes exactly on x=0 carries the FULL donor concentration (1e18 cm^-3) AND the full
acceptor concentration (1e18 cm^-3) simultaneously (confirmed by reading `prod_arrays.npz`'s `Donors`/`Acceptors` arrays
directly at the `x == 0` mask — not inferred from a summary field), with NetDoping = 0 there by cancellation. Their combined
NodeVolume is 1.56249985e-10 cm^2 (E1 `prod.json`). This means, for the DONOR array specifically, `Donors * NodeVolume`
sums to 0 over the whole x < 0 side (Donors = 0 there, confirmed directly) and 1.5625e8 cm^-1 over the x = 0 column alone —
a real, exactly-quantified 1.5625e8 / 2.5e11 = **0.0625 %** contribution to the donor-side `exact_dual_F2` (and symmetrically
for acceptor) that exists purely because of this "both species at full strength on the junction line" convention, wholly
independent of any refinement-stage defect (it is present, unchanged, at S0 before any refinement is applied). The same
computation on the flip-candidate mesh (`data/remote_run_36129959490/outputs/e2_out/candidate.npz`) gives a smaller
observed gap (`exact_dual_F2 - continuum` = 7.809e7 cm^-1, about half of the S0-based figure); the candidate mesh's flip
pass changes triangle shapes (not positions) throughout the domain including near x = 0, so this smaller number reflects
some additional, currently uncharacterized interaction between the flip and the x = 0 column's own F2 partition. **That
residual difference (why the candidate's boundary-node contribution is not exactly the S0 value) has not been isolated and
is left `UNKNOWN`** — it was not computed by either E1 or E2. What IS established: this boundary-node effect, at ~0.06 %,
is an order of magnitude smaller than the candidate's own remaining 2.02 % excess and two orders of magnitude smaller than
S4's original 5.83 % excess, so it does not materially change either verdict; it is a real, separate, and now
quantified-at-S0 contributor that should not be added into or confused with the shape-driven refinement excess.

## 5. Summary of what changes and what does not

Changed (interpretation only): `NO_ORIENTATION_EFFECT` -> read as `ORIENTATION_INCONCLUSIVE`; `SHAPE_CAUSE` -> read as
"the shape/obtuse-triangle mechanism only, not a claim that orientation was excluded"; `exact_dual_F2` and
`continuum_N_x_25um2` -> read as two different discrete/continuum references, neither authoritative, with the x = 0 node
convention's ~0.06 % contribution to their gap now quantified from raw data (section 4) rather than left unexamined.
Unchanged: `FIRST_BAD_STAGE=1`; every stage/lineage/formula number in `e2_result.json`; the candidate's `CANDIDATE_REJECTED`
verdict and its three failed checks; PLAN.md, PLAN.sha256, and all raw remote artifacts (verified byte-identical against
`data/artifact_remote_run_36129959490.sha256`, re-checked below).
