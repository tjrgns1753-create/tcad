# Batch 7H-E6A REPORT: non-obtuse conforming mesh family L3 / L4 / L5 (geometry only)

**Verdict: `GEOMETRY_FAMILY_CANDIDATE_ONLY`** (the PLAN's maximum). L3, L4 and L5 each pass every PLAN section 4A-4D check,
L4 passes the section 3 reproduction contract, the cross-level nesting (4C6) holds, `devsim.solve` was called 0 times,
no device was left registered, and no artifact is missing. Not claimed: Poisson or current 2D mesh convergence, current
accuracy, biased I-V, production step-junction support, arbitrary process-order support, any change to the gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` or to 7H-E4's own `GEOMETRY_CANDIDATE_ONLY` verdict.

## 1. Provenance
* PLAN: `PLAN.md`, committed alone in `f9a9cfaa175d9162072ff6b51b8ae8e81b83642c` before any E6A code; LF sha256
  `5dcda927588941a2b88713434ab841e6346180e82ee33793336968d1981a87ba` (`PLAN.sha256`), re-verified in the run
  (`e6a_result.json` `inputs`). Not edited after the result.
* Code: `13e8b90` (scripts), `17b444f1fed3fb75b97c40162cdf607e53bd8b09` (profile `e6a_mesh_family`, request
  `e6a-mesh-family-001`). Unabridged patch of every code change: `data/batch_e6a_code.patch` (sha256 in section 8).
* Remote run: https://github.com/tjrgns1753-create/tcad/actions/runs/36388479824 (run 11, attempt 1), executed commit
  `17b444f1...`, `status PASS`, `exit_code 0`, 181.7 s. Runner: GitHub-hosted Windows, image `win25-vs2026` 20260922.246.2,
  4 CPUs, 17174360064 B physical memory, Python 3.11.9, DEVSIM 2.11.0 (MKL PARDISO). `code_paths_identical_to_review_sha:
  true` for `tcad`, `tests`, `tcad_2d_stagewise.py`, `examples` against `023bcb90...`. Exactly one run for this batch.
* Inputs (PLAN section 1), all equal: regenerated `wafer_volume.vtu` `cfae97d4...` (= E1-E4); `candidate_e4.vtu`
  `85ebcbae...`; `candidate_e4.npz` `740a643e...`; `e4_result.json` LF `3fdf0697...`; S0 = 201 x 101 lines, 40000
  triangles, tag 10, float32; e0 = 2.8610229492465e-7 um (same as the PLAN's reference value).
* Artifact (`data/remote_run_36388479824/`): all 12 outputs and `run.log` re-hashed after download against `summary.json`:
  12/12 equal, `omitted_outputs: []`, log sha256 `ae207d64...` equal, redactions none. Text artifacts are LF-only, `.vtu`
  are `-text`, `.npz` are binary, so the committed bytes keep these hashes on any checkout.

## 2. Construction and exact geometry (per level, raw values from `level_L<L>.json`)

| | L3 | L4 | L5 |
|---|---|---|---|
| target h at junction (um) | 0.00625 | 0.003125 | 0.0015625 |
| triangles / nodes (predicted = actual) | 95400 / 48033 | 255400 / 128067 | 882600 / 441733 |
| S_L triangles; kept fine / kept base / removed strip | 91800; 51200 / 38400 / 2200 | 247000; 204800 / 38400 / 3800 | 864600; 819200 / 38400 / 7000 |
| new nodes / new triangles / unreferenced | 1804 / 5800 / 0 | 4206 / 12200 / 0 | 9008 / 25000 / 0 |
| transition x-lines m_1..m_(L-1) (+ side, um) | 0.125, 0.1125 | 0.125, 0.1125, 0.10625 | 0.125, 0.1125, 0.10625, 0.103125 |
| template cells / long edges present / halves not owned twice | 1400 / 0 / 0 | 3000 / 0 / 0 | 6200 / 0 / 0 |
| exact area (um^2) = rectangle = S0 | 50/1 | 50/1 | 50/1 |
| non-positive orientation / exact obtuse / duplicates | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| edges; owners > 2; 2-owner same direction | 143432; 0; 0 | 383466; 0; 0 | 1324332; 0; 0 |
| 1-owner edges; off boundary | 664; 0 | 732; 0 | 864; 0 |
| boundary chains bottom / right / top / left (edges), all CCW, gap-free, all side nodes on chain | 232 / 100 / 232 / 100 | 266 / 100 / 266 / 100 | 332 / 100 / 332 / 100 |
| S0 boundary points lost / added | 0 / 64 | 0 / 132 | 0 / 264 |
| contact nodes x = -5 / +5 (= S0) | 101 / 101 | 101 / 101 | 101 / 101 |

With (T1)-(T3) true at every level, PLAN B4's winding-number argument gives a gap-free, overlap-free tiling; no pairwise
overlap scan was run. The fine region and base region are the production S_L rows, index-identical over a bit-identical
point prefix; the base region also equals S0's 38400 triangles as coordinate triples. Construction x-lines equal the
float32 midpoint recursion; row nesting R_L[::2^L] == S0 rows held (no `ROW_NESTING_FAIL`).

## 3. Junction resolution and stepwise spacing (PLAN 4C)

| | L3 | L4 | L5 |
|---|---|---|---|
| delta_L = e0 2^-L + L 2^-21 (um) | 1.4663e-6 | 1.9252e-6 | 2.3931e-6 |
| x = 0 nodes (= Ny 2^L + 1, = S_L's set) | 801 | 1601 | 3201 |
| x = 0 spacing min / median / max (um) | 0.0062499046 / 0.0062499940 / 0.0062503815 | 0.0031247139 / 0.0031249523 / 0.0031251907 | 0.0015621185 / 0.0015625060 / 0.0015625954 |
| x = 0 max abs deviation from h_L (um) | 3.815e-7 | 2.861e-7 | 3.815e-7 |
| fine x-lines (= 4 2^L + 1); max abs deviation (um) | 33; 5.96e-9 | 65; 4.47e-9 | 129; 5.96e-9 |
| transition column width max abs deviation (um) | 5.96e-9 | 5.96e-9 | 5.96e-9 |
| near bands max horizontal / vertical / edge (um), band [0, 0.025) | 0.0062500006 / 0.0062503815 / 0.0088391049 | 0.0031250007 / 0.0031251907 / 0.0044195528 | 0.0015625004 / 0.0015625954 / 0.0022097764 |
| band [0.1, 0.15): max edge vs S0 (um) | 0.027951 <= 0.070711 | 0.027951 <= 0.070711 | 0.027951 <= 0.070711 |
| band [0.15, 0.2): max edge vs S0 (um) | 0.055902 <= 0.070711 | 0.055902 <= 0.070711 | 0.055902 <= 0.070711 |

Cross-level (4C6): the x = 0 y-set of L4 at even indices equals L3's, L5's equals L4's, and likewise for the fine x-lines
(all bit-equal). Every level's deviations are below delta_L; the observed x = 0 deviations (2.9e-7 to 3.8e-7 um) are of the
size of one float32 ulp at |y| near 5 um (4.77e-7 um), i.e. the rounding mechanism the bound was derived from.

## 4. DEVSIM import and NodeVolume (PLAN 4D, 7H-E4 definitions)

| | L3 | L4 | L5 |
|---|---|---|---|
| DEVSIM nodes / elements / regions | 48033 / 95400 / Si | 128067 / 255400 / Si | 441733 / 882600 / Si |
| node coordinates = `(P32 * 1e-4).astype(float)` (multiset; also same node order) | yes | yes | yes |
| contacts Si_xmin / Si_xmax nodes; coords_sha256 = 7H-E4's | 101 / 101; yes | 101 / 101; yes | 101 / 101; yes |
| exact area (cm^2) | 18446741531089 / 2^65 (4.999999310821319e-7) | same | same |
| sum NodeVolume / exact area | 1.0 | 1.0 | 1.0 |
| tau | 3.188e-11 | 8.518e-11 | 2.941e-10 |
| max \|NodeVolume - F3\| / F3; nodes beyond b_i | 1.760e-16; 0 | 1.760e-16; 0 | 1.760e-16; 0 |
| max \|F3 - F2\| / F2 (reported) | 0.0 | 0.0 | 0.0 |
| EdgeCouple negative / zero / positive | 0 / 29745 / 113687 | 0 / 61082 / 322384 | 0 / 180401 / 1143931 |
| max \|EdgeCouple - G1\| / max G2 | 1.69e-16 | 1.69e-16 | 1.69e-16 |

NodeVolume and EdgeCouple were only read; nothing was overwritten or rescaled.

## 5. L4 reproduction of 7H-E4 (PLAN section 3)
Against `candidate_e4.vtu` read with meshio: node coordinate sets equal (128067 each, no duplicate coordinates), triangle
vertex-coordinate multisets equal (255400 each), tags equal (single tag 10), outer boundary and both contact sets equal:
`ok: true`. Reported only: the arrays are also equal in order, the written `level_L4.vtu` has the same sha256 as
`candidate_e4.vtu` (`85ebcbae...`), and DEVSIM NodeVolume matched by coordinate equals `candidate_e4.npz` bit for bit.

## 6. Resources (PLAN section 5; each level in its own subprocess)

| | L3 | L4 | L5 |
|---|---|---|---|
| memory envelope M(L) (GiB) | 1.41 | 2.10 | 4.79 |
| measured peak private / peak working set (GiB) | 0.180 / 0.186 | 0.428 / 0.421 | 1.328 / 1.271 |
| time envelope (s) | 179 | 478 | 1652 |
| measured stage wall (s) | 14.7 | 39.4 | 125.9 |
| of which: production refine / build / exact / resolution / import+read / NodeVolume (s) | 1.41 / 0.03 / 0.63 / 0.26 / 1.46 / 9.91 | 2.42 / 0.10 / 1.12 / 0.62 / 4.15 / 26.78 | 5.28 / 0.36 / 3.38 / 2.10 / 14.87 / 94.43 |

Measured L5 gate before L5: predicted peak max(1.589e9 B proportional, 1.503e9 B linear) = 1.589e9 B <= 8 GiB; predicted
time 204 s with 54.7 s elapsed <= 7200 s: L5 run. Total geometry wall time 180.6 s. No `RESOURCE_PREFLIGHT_FAIL`.

## 7. Independent local re-check of the downloaded arrays (`scripts/recheck_e6a_local.py` -> `data/recheck_e6a_local.json`)
Separate code, read-only numpy on the npz files (no ViennaPS, no DEVSIM). At every level: DEVSIM x, y equal the scaled
construction coordinates in the same node order; sum NodeVolume over the exact rectangle area from DEVSIM's own extreme
coordinates minus 1 = 0.0; NodeVolume all positive; EdgeCouple minimum 0.0 with 0 negatives; float64 maximum angle
90.0000000000 deg. One item needed explanation and is recorded, not waived: DEVSIM's element array is NOT equal to the
construction triangle array in order (the in-run check D2 compared only the element count). Checked directly: the
vertex-set multiset of DEVSIM's elements equals the construction's at every level, so the connectivity is identical and
DEVSIM only reorders elements; at L4 DEVSIM's element array is bit-equal to `candidate_e4.npz`'s, so the reordering is
deterministic.

## 8. Change record
Files added or changed by this batch (production code, tests, DEVSIM/ViennaPS, precision flags and the gate untouched):
* `docs/audits/2026-09-25-batch7h-e5-equilibrium-pilot/ERRATUM_2.md` section 4, first bullet: per-run solve-call recount
  (separate commit `05b9e655`).
* `PLAN.md`, `PLAN.sha256` (commit `f9a9cfaa`).
* `scripts/family_e6a.py` (level-L construction and exact checks), `scripts/stage_e6a.py` (remote worker),
  `scripts/run_e6a.py` (driver), `scripts/synthetic_e6a_test.py` (local synthetic test),
  `scripts/recheck_e6a_local.py` (post-run re-check); `data/synthetic_e6a_results_pre_run.json`,
  `data/recheck_e6a_local.json`, `data/remote_run_36388479824/` (downloaded evidence, unmodified except that the
  artifact's top folder `remote-run-11/` was flattened into `remote_run_36388479824/`).
* `remote/profiles.py` (new profile `e6a_mesh_family`, existing profiles unchanged), `remote/request.json`.
* `data/batch_e6a_code.patch`: unabridged `git diff -U1 05b9e655` of `scripts/` and `remote/` (7 files, 1080 added,
  3 removed lines), sha256 `8172d4c1496bcfad459744c746f3c0c4304de662c992fc7e97cfd3b825485f8e`. One context line instead of
  three because a blank context line in `remote/profiles.py` is encoded by the diff format as a lone space, which
  `git diff --check` flags; checked: `git apply` onto `05b9e655` succeeds and every resulting file is blob-identical to
  the committed one.
* `git diff --check` on this commit returns rc 2 in both the normal and a clean git configuration, only for the
  `level_L3/L4/L5.vtu` raw artifacts (29 flagged lines each: the CRLF line endings of meshio's XML header lines as written
  on the runner). These files are `-text` hash-pinned evidence (same state as 7H-E4's `candidate_e4.vtu`, index `crlf`);
  changing their bytes would break the recorded sha256, so they are committed exactly as downloaded.

## 9. Limits and items handed to E6B (observations; none is a pass/fail item of this batch)
1. Only the junction region changes with L. The fine region is |x| <= 0.1 um at every level and the base 0.05 um grid is
   identical beyond |x| = 0.2 um, so any discretization error originating in the quasi-neutral regions is the same at L3,
   L4 and L5. A Poisson convergence study on this family measures junction-region refinement only and may show a floor set
   by the unrefined far field; E6B must pre-register how that is separated.
2. The transition strip width (0.1-0.2 um) is fixed; the size jump it bridges grows with L (8x at L3, 16x at L4, 32x at
   L5), through the same 2:1 template sequence.
3. Analytic scales (Sze & Ng, values from the 7H-E1/E4 PLANs, not measured here): W(0 V) ~ 0.0484 um ~ 7.7 h_L3,
   15.5 h_L4, 31 h_L5; L_D ~ 0.0040 um, smaller than h_L3 = 0.00625 um and ~1.3 h_L4, ~2.6 h_L5. L3 therefore does not
   resolve the Debye length; whether L3-L5 lie in an asymptotic range is an open question for E6B, not assumed.
4. Right-triangle pairs sharing a hypotenuse give EdgeCouple exactly 0 (29745 / 61082 / 180401 edges): such edges carry no
   finite-volume flux. Consistent with the non-obtuse design (no negative couple anywhere), noted for E6B's flux reading.
5. DEVSIM reorders elements (section 7); any E6B comparison must key elements by vertex set or coordinates, not by index.
6. Scope stays 7H-E1's planar single-Si wafer with one straight junction; nothing here supports other geometries or any
   process sequence.
