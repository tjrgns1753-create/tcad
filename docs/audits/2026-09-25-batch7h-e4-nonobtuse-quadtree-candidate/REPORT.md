# Batch 7H-E4 REPORT: E2/E3 corrections + non-obtuse 2:1 quadtree transition candidate (audit-only)

**Verdict: `GEOMETRY_CANDIDATE_ONLY`.** All 31 pre-registered checks pass. DEVSIM sum NodeVolume / exact area = **1.0**
(tau 8.52e-11); **0 obtuse** triangles, 0 Delaunay violations, 0 DEVSIM-negative EdgeCouple. Junction resolution equals
production S4 in every band out to 0.1 um, and at the junction line. This is a geometry result only. It says nothing about
electrical accuracy, 2D mesh convergence, the sufficiency of S4's own resolution, or process-order generality, and its scope
is 7H-E1's planar single-Si wafer. The production gate stays; nothing is applied to production.

* PLAN: `PLAN.md`, sha256 (LF) `5630cd702a0ae59e781f3bff0d9e3d6fab05c3b2d279609110e598d4aad866ad`. The runner's CRLF
  checkout hashes to `2d1179c5...`, the same content. Committed alone in `de697598e675ca9fe49e757200817c4ff1e9e9e9`.
* Code / profile / request: `b05d27131fe75cda56d4d3c0c7c3b52ea4ccdb56`.
* Run: https://github.com/tjrgns1753-create/tcad/actions/runs/36143535737 (request
  `e4-nonobtuse-quadtree-candidate-001`).
  * PASS, exit 0, 159.7 s, GitHub-hosted Windows, DEVSIM 2.11.0.
  * `code_paths_identical_to_review_sha = true`, `devsim.solve` calls 0, devices left 0.
  * PASS means the audit script finished; the candidate verdict is the one above.
* Artifact: 4 outputs + log + summary; sha256 in `data/artifact_remote_run_36143535737.sha256`, all equal to `summary.json`.
  Strict JSON parse OK; sensitive-pattern scan clean.
* Serena MCP was unavailable again ("Skipping connection, recent failure cached"); rg and direct reading were used.

## 1. Corrections to 7H-E2 / 7H-E3
Measured read-only from existing arrays (`scripts/recheck_e2_e3.py` -> `data/recheck_e2_e3.json`). Written up in
`../2026-09-25-batch7h-e2-nodevolume-first-bad-stage/ERRATUM_SUPPLEMENT_1.md` and
`../2026-09-25-batch7h-e3-junction-refinement-candidate/ERRATUM.md`. The earlier ERRATUM.md, PLANs and raw evidence are unchanged.

| Earlier statement | Kept / withdrawn | Raw data |
|---|---|---|
| E2 ERRATUM: x = 0 effect "0.0625 %" | withdrawn | S4 donor F2 - continuum = 7.809053e7 cm^-1 = **0.031236 %** |
| E2 ERRATUM: x = 0 effect "present, unchanged, at S0" | withdrawn | x = 0 F2 area S0 **2.499999765e-9**, S1 1.25e-9, S2 6.25e-10, S3 3.125e-10, S4 **1.562499853e-10 cm^2**; donor gap 1.249965e9 (0.4999 %) -> 7.809e7 (0.0312 %) |
| E2 ERRATUM: flip-candidate gap differs "because of the flip" | withdrawn | donor F2 total **2.5007809053e11** on S4, E2 flip and E3 alike |
| E2 ERRATUM: both species at full strength on x = 0; F2 and continuum are different references | kept | rule reproduces the queried arrays exactly on S4 and E3 |
| E3 REPORT: "coarser by 1.3e-4 relative ... not systematically under-resolving the junction" | withdrawn | x = 0 y-sets identical (1601 nodes); first columns +-3.125e-7 cm in both; but by band E3's max horizontal edge is 2x / 4x / 8x S4's at 0-0.025 / 0.025-0.05 / 0.05-0.1 um |
| E3 `boundary_bit_identical = False` read as a defect | reading corrected (value kept) | 0 of 600 lost; 32 added (16 on y = 0, 16 on y = -5); corners, bounding box and both contact sets (101 / 101) unchanged |
| E3 `exact_area_cm2 = "50/1"` | unit corrected | value is um^2; E4 names it `exact_area_um2` |
| E3 `CANDIDATE_REJECTED`; excess 5.825 % -> 0.9375 % | kept | ratio 1.0093750000010542 vs tau 2.64e-11 |

Where the x = 0 change happens:
* **Measured:** every pass S0 -> S4 halves the first-column spacing h and halves the gap.
* **Formula** (derived in the supplement, with the geometry stated): gap = N x H x h / 2. It matches every stage to within
  the float32 area deficit.
* **Mechanism:** the gap comes from the J0 double-assignment rule, not from triangle shape.

## 2. The candidate (PLAN sections 1, 3; local patch proof `data/patch_proof.txt`)
**The kept regions are production's.** The S4 fine region is kept unchanged: 204800 triangles with |x| <= 0.1 um. So is
the untouched base mesh: 38400 triangles with |x| >= 0.2 um. Only the two 0.1-0.2 um strips (3800 triangles, where the
green fans live) are removed.

**The strips are refilled** with 2:1-balanced square cells (sizes h3, h3, h2, h1, h0) and filled with 12200 new
triangles. A cell with a hanging midpoint on its junction-facing edge gets the three-triangle template:
* (LL, LR, M): 90 / 26.57 / 63.43 deg
* (M, LR, UR): 53.13 / 63.43 / 63.43 deg
* (M, UR, UL): 63.43 / 26.57 / 90 deg

All of its exact dot products are >= 0. Other cells get two right isosceles triangles.

**The local proof** reproduces the production cascade it replaces exactly: per origin 1, 3, 7, 15 obtuse and max angle
116.565, 126.870, 131.186, 133.152 deg, which are 7H-E2's measured values.

## 3. Comparison (areas cm^2; resolution in um by band of edge-midpoint |x|, never a single minimum)

| | S0 | production S4 | E3 (graded, rejected) | **E4 candidate** |
|---|---|---|---|---|
| nodes / triangles | 20301 / 40000 | 123861 / 247000 | 39817 / 79000 | **128067 / 255400** |
| sum NodeVolume / exact area | 1.0 | 1.0582519546022044 | 1.0093750000010542 | **1.0** |
| tau | 1.34e-11 | 8.28e-11 | 2.64e-11 | **8.52e-11** |
| acute / right / obtuse (exact) | 0 / 40000 / 0 | 0 / 244000 / 3000 | 0 / 76000 / 3000 | **3000 / 252400 / 0** |
| min / max angle (deg) | 45.0 / 90.0 | 1.85 / 133.15 | 18.43 / 116.57 | **26.56 / 90.0** |
| exact Delaunay violations | 0 | 200 | 3000 | **0** |
| signed couple / node-volume negatives | 0 / 0 | 200 / 200 | 3000 / 0 | **0 / 0** |
| DEVSIM EdgeCouple < 0 | 0 | 0 (200 predicted-negative stored positive) | 0 (3000 same) | **0** (0 predicted negative) |
| x = 0 line: nodes, y-spacing min / median / max (cm) | 101; 5.0e-6 | 1601; 3.1243e-7 / 3.1250e-7 / 3.1258e-7 | same as S4 (identical y-set) | **same as S4 (identical y-set)** |
| first column each side (cm) | +-5.0e-6 | +-3.125e-7 | +-3.125e-7 | **+-3.125e-7** |
| band 0-0.025: max edge / max horiz. / max vert. | 0.0707 / 0.05 / 0.05 | 0.00442 / 0.003125 / 0.003126 | 0.00884 / 0.00625 / 0.00625 | **0.00442 / 0.003125 / 0.003126** |
| band 0.025-0.05 | 0.05 / - / 0.05 | 0.00442 / 0.003125 / 0.003126 | 0.01768 / 0.0125 / 0.0125 | **0.00442 / 0.003125 / 0.003126** |
| band 0.05-0.1 | 0.0707 / 0.05 / 0.05 | 0.00442 / 0.003125 / 0.003126 | 0.03536 / 0.025 / 0.025 | **0.00442 / 0.003125 / 0.003126** |
| band 0.1-0.15: max edge (median) | 0.0707 (0.05) | 0.0707 (0.0559) | 0.0707 (0.0559) | **0.0280 (0.00699)** |
| band 0.15-0.2: max edge (median) | 0.0707 (0.05) | 0.0707 (0.05) | 0.0707 (0.05) | **0.0559 (0.05)** |
| boundary points: lost / added vs S0 | - | - | 0 / 32 | **0 / 132** (all on y = 0 or y = -5) |
| contacts (nodes, same coordinate set as S0) | 101 / 101 | 101 / 101 | 101 / 101 | **101 / 101** |
| donor: DEVSIM NodeVolume integral (cm^-1) | 2.51250e11 | 2.646411e11 (+5.856 %) | 2.524218e11 (+0.969 %) | **2.500781e11 (+0.0312 %)** |
| donor: same-mesh F2 integral | 2.51250e11 | 2.500781e11 | 2.500781e11 | **2.500781e11** |
| donor: continuum N x 25 um^2 | 2.5e11 | 2.5e11 | 2.5e11 | 2.5e11 |
| build / import / analysis time (s) | - | - | 2.0 / 0.7 / 35 | **0.1 / 2.6 / 140** |

In E4, DEVSIM's integral equals the same-mesh F2 integral exactly (acceptor identical). The remaining +0.0312 % versus the
continuum is the J0 junction-line term N x H x h / 2 (formula 7.8125e7, measured 7.809e7 cm^-1). That is a property of the
doping rule at the x = 0 node column, not of triangle shape. Whether it is acceptable is a separate physics decision this
batch does not take.

S0's doping integrals are RULE-APPLIED; the others are QUERIED. E4 queries `WaferStateV2.net_doping_at()` at all 128067
nodes, all finite. The band rows for S0, S4 and E3 come from their committed arrays.

Every PLAN check passed:
* identity: input sha; S4 reproduction; row nesting; fine and base regions identical to S4; removed strip area = generated
  area = 67108865/67108864 um^2;
* exact area 50/1 um^2 = S0;
* boundary: 0 lost; all 732 boundary edges on the outer lines;
* conforming; 0 non-positive orientation; 0 duplicates; 0 exact overlaps;
* NodeVolume = F3 at every node (max relative 1.8e-16); F3 = F2 exactly (max relative difference 0.0);
* NodeVolume = sum 0.25 EdgeCouple x EdgeLength to 6.5e-17;
* EdgeCouple matches G1 = G2 to 1.7e-16 of max.

## 4. What this establishes and what it does not
**Established, for this geometry only:** the obtuse-driven NodeVolume over-integration is removed at its source. The junction
resolution production S4 achieves inside 0.1 um is kept exactly. Mesh size grows by 3.4 %.

**Not established:**
* electrical accuracy of any solve on this mesh;
* whether S4's own resolution is sufficient. h = 3.125 nm against an estimated L_D of 4.0 nm and W of 48-56 nm; no
  convergence study;
* behaviour on other process geometries (curved or etched surfaces, several materials, tilted or multiple junctions). The
  construction assumes a structured square base grid and a full-height strip;
* the J0 junction-node term.

The gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` stays in force. Numerical measurement of the step junction stays
blocked.

**Local steps disclosed:**
* Before the remote run and after the PLAN commit, the candidate construction and exact checks were dry-run locally in
  numpy on E3's committed `wafer_volume.vtu`. They gave the same counts and invariants the runner later reported.
* The synthetic grid test passed (`data/synthetic_e4_results_pre_run.json`: candidate F3 / area = 1, synthetic S4
  1.5825, negative control detected).
* No DEVSIM or ViennaPS ran locally.

## 5. Evidence-integrity finding (not fixed; reported for decision)
The system git config sets `core.autocrlf=true` (`C:/Program Files/Git/etc/gitconfig`), and the repository has no
`.gitattributes`. Some runner artifacts are CRLF text: the meshio-written `.vtu` files. Git stores these as LF in the index.

On this machine, checkout restores CRLF, so every artifact sha256 check passes. On a checkout with `autocrlf=false`, such
as another reviewer's clone, five committed files would not match their recorded artifact hashes:
* E2 `C_ccw.vtu`, `C_rt.vtu` and `candidate_flip.vtu`;
* E3 `candidate.vtu`;
* E4 `candidate_e4.vtu`.

`data/eol_normalization_note.txt` lists both hashes for each file (CRLF = artifact, LF = committed blob), so any checkout can
be verified. The geometry in these files is identical either way. The binary npz files, which carry the arrays every
analysis used, and the JSON / log files are unaffected. Nothing was edited or re-committed. A fix (for example a
`.gitattributes` entry marking `docs/audits/*/data/remote_run_*/**` as `-text`) changes repository configuration and needs
a decision; it was not made here.

## 6. git diff --check
* **Source and docs:** `190516ca..b05d271` (errata, PLAN, scripts, `remote/`): normal environment rc 0, no output.
* **This report commit (`--cached`):**
  * normal environment, rc 2: one warning, `data/batch_e4_code_and_errata.patch:1101: trailing whitespace` (`+ `). It is a
    unified-diff blank context line (the blank line before `# Global limits` in `remote/profiles.py`) and is inherent to
    that hunk.
  * clean environment (`GIT_CONFIG_NOSYSTEM=1`, global `/dev/null`, `core.autocrlf=false`), rc 2: the same patch warning,
    plus 29 warnings on raw `outputs/e4_out/candidate_e4.vtu`. These are its CRLF line ends, section 5. The file is
    hash-bound evidence and was not edited.

## 7. No-change confirmation
* Production and tests: `start_hashes_prod_tests.txt` rc 0; `git diff --quiet 023bcb90 -- tcad tests tcad_2d_stagewise.py
  examples` rc 0.
* E1 / E2 / E3 tracked files (`start_hashes_e1_e2_e3_tracked.txt`) and all pre-existing audits
  (`start_hashes_all_audits.txt`): rc 0.
* E2 and E3 remote artifacts verified against their sha256 lists.
* Gate code, precision flags and DEVSIM are untouched; no DEVSIM value was overwritten or renormalized.
* No PN / DD / I-V solve, no full regression, no GUI run.
* `origin/claude/waferstate-v2 = 023bcb90...` and `origin/main = d60e9aed...`, unchanged.
