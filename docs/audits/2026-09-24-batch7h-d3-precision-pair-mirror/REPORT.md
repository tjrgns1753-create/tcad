# Batch 7H-D3 REPORT: precision pair P0/P12/P4 in 2D and corrected mirror re-check

Executed on a GitHub-hosted Windows runner only (nothing physical was computed locally). Numerical precision and
current-conservation check on the fixtures below; NOT a validation of PN-diode physics, other meshes, finer h,
other doping or process order. 7H-D2's failure of M1/M3 against the registered potential-convergence criterion
stands. The gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the production default precision flags are unchanged.

## 1. PLAN before execution
* `PLAN.md` sha256 (LF-normalized) `eb6096a9ffc8a338a86dafee5f8f6fee88bf8bc93ac1eaea3fc2f8b62eee1071`, fixed
  2026-09-23T17:23:16Z, commit `959581c000a7873ff594f14b093330f9bc48e157` (PLAN only; no code, no result existed).
  Every run re-computed the hash: match = True.
* Erratum written before the first run (`PLAN_ERRATA.md`): PLAN section 4 says "11 solve steps"; D3 records 12
  (D2 solved but did not record the reverse 0 V state). The criterion (every recorded solve accepted) is unchanged.

## 2. Execution
* Code/run commit `3888ea5cf84c06b8fdf483ae86541ed0753f2e98`; Actions run
  https://github.com/tjrgns1753-create/tcad/actions/runs/35896298771 (runner PASS, 115 s; physics verdicts are in
  `analysis_d3.json`). Windows Server 2025 (10.0.26100), Python 3.11.9, ViennaPS 4.6.2, ViennaLS 5.8.5, DevSim 2.11.0
  (`extended_precision` true, `mkl_pardiso`, `mkl_rt.3.dll`), mkl 2026.1.0, numpy 2.4.6.
  `tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/` identical to review SHA `023bcb90...` (runner-recorded True).
* **First attempt, disclosed:** run https://github.com/tjrgns1753-create/tcad/actions/runs/35895798384 (commit `a960b01`)
  completed all 11 runs and the analysis with the same verdicts, but the driver wrote `d3_out` one directory too high
  (`docs/`), so no result JSON reached the artifact. I had read its final verdict lines before rerunning. The rerun
  (`3888ea5`) changed only that path (`run_d3.py` ROOT); PLAN, worker, analysis and criteria are unchanged. Its log and
  summary are kept in `data/remote_run_35895798384_result_json_not_uploaded/`.
* Evidence in `data/remote_run_35896298771/` (artifact `remote-run-3`): `summary.json`, sanitized `run.log`,
  11 run JSONs, `analysis_d3.json/.md`. Artifact scan for user paths / runner name / tokens: 0 hits.

## 3. Fixtures and readback
* `fixtures_d1.json` sha256 `80d65d513ff9f923ff35cfe54cd937214b33cd47571797a005013e6e82d9f7f5` (read from the checkout,
  not regenerated). M2 h = 0.005 um and M1 h = 0.005 um: 4242 nodes / 8040 triangles each; coordinates and connectivity
  hashes recomputed on the runner equal the stored ones (`identical_to_stored` True for all 11 runs). 1D J1: 202 nodes.
  Mirror geometry: max |x - (-x_expected)| = 5.6e-17 um; donors/acceptors on the expected sides.
* Flags: every run started with the three parameters unset, was set explicitly, read back equal to the target and
  unchanged at the end; no device left behind. All 12 solve steps accepted in all 11 runs.

## 4. Experiment 1: M2/D0 h = 0.005 um (currents A/cm)
Runner wall time: P0 5.2 s, P12 20.8 s, P4 21.2 s (solver flag adds nothing measurable).

| point | quantity | P0 | P12 | P4 | rel(P12,P4) | rel(P0,P4) |
|---|---|---|---|---|---|---|
| +0.05 V | C0 left | 1.110697968e-12 | 1.114137468e-12 | 1.114137468e-12 | 0 | 3.09e-3 |
| | C0 right | -1.109568873e-12 | -1.114137468e-12 | -1.114137468e-12 | 1.8e-16 | 4.10e-3 |
| | cut 0 | 1.114137468e-12 | 1.114137468e-12 | 1.114137468e-12 | 0 | 7e-11 |
| +0.10 V | C0 left | 3.910615556e-12 | 3.910703893e-12 | 3.910703893e-12 | 0 | 2.3e-5 |
| | C0 right | -3.915107702e-12 | -3.910703893e-12 | -3.910703893e-12 | 2.1e-16 | 1.13e-3 |
| | cut 0 | 3.910703892e-12 | 3.910703893e-12 | 3.910703893e-12 | 2.1e-16 | 3.8e-10 |
| -0.10 V | C0 left | -9.503859493e-13 | -9.467798999e-13 | -9.467798999e-13 | 2.1e-16 | 3.81e-3 |
| | C0 right | 9.480750258e-13 | 9.467798999e-13 | 9.467798999e-13 | 0 | 1.37e-3 |
| | cut 0 | -9.467798999e-13 | -9.467798999e-13 | -9.467798999e-13 | 0 | 3.2e-12 |
All five cuts (x = -0.25, -0.10, 0, +0.10, +0.25 um) and all three biases are in `analysis_d3.md`. Worst residuals over the
three biased points:

| variant | L/R mismatch | 5-cut spread | contact vs cut(0) L / R | C3 species | C3 total | zero-bias rule |
|---|---|---|---|---|---|---|
| P0 | 2.4e-3 | 4.6e-3 | 3.8e-3 / 4.1e-3 | 4.7e-3 | 4.7e-3 | violated (B0, B0rev) |
| P12 | 2.1e-16 | 2.1e-16 | 2.1e-16 / 1.8e-16 | 2.1e-16 | 2.1e-16 | ok |
| P4 | 2.1e-16 | 2.1e-16 | 2.1e-16 / 0 | 1.7e-16 | 2.1e-16 | ok |

## 5. Experiment 2: mirror
Correspondence defined in PLAN section 5 before running (p contact takes +v in both devices: original `left_bias`,
mirror `right_bias`; C0_M,right = C0_O,left; C0_M,left = C0_O,right; I_M(-x_c) = -I_O(x_c); node on a cut to R for the
original and to L' for the mirror). Actual readback, identical for 1D and M1, P4:

| point | device | p-contact parameter | readback | n-contact parameter | readback | V from contact potentials |
|---|---|---|---|---|---|---|
| +0.05 / +0.10 / -0.10 V | original | `left_bias` | +0.05 / +0.10 / -0.10 | `right_bias` | 0 | equal to v to 12 digits |
| +0.05 / +0.10 / -0.10 V | mirror | `right_bias` | +0.05 / +0.10 / -0.10 | `left_bias` | 0 | equal to v to 12 digits |

Pair errors at all three biased points (1D and M1, P4): p-contact, n-contact and all five cuts, |M - expected| /
|O| = 0 (bit-identical; e.g. +0.10 V, 1D: 3.910703893e-7 A/cm^2 on both p contacts; every cut O = +3.910703893e-7,
M = -3.910703893e-7; M1 2D: 3.887730509e-12 A/cm). M1 has 10 nodes exactly on each of the four non-zero cuts; the tie rule
changes the cut current by 4.2e-16 in P4 (1.75e-3 in P0), so the result does not depend on the tie choice in P4.

## 6. Verdicts (each separate)
| item | verdict | scope / limit |
|---|---|---|
| fixture identity (hash, counts) | PASS | inputs read from the checkout |
| flag readback, solve acceptance | PASS | 11 runs x 12 solves |
| P0 defect reproduced | YES (`SELF_VIOLATED`, up to 5.8e-3 vs P4, zero-bias rule violated) | control only |
| **P12 == P4** | **PASS** | M2/D0 h = 0.005 um; 21 comparisons, max rel diff 2.1e-16; no undecidable; P12 self-consistent to 2.1e-16 |
| **mirror 1D h=0.005, P4** | **MIRROR_PASS** | bias correct from the start; 0 issues |
| **mirror M1/D0 h=0.005, P4** | **MIRROR_PASS** | same |
| mirror control P0, 1D | MIRROR_FAIL | 12 of 21 pair comparisons > 1e-5 (worst 6.2e-3) plus zero-bias rule |
| mirror control P0, M1 | MIRROR_FAIL | only through the zero-bias rule; the 21 pair comparisons matched exactly at P0, so this control does not show that the pair criterion can fail on M1 |
No re-pairing after the fact was used; "CERTIFIED" is not claimed.

## 7. What is and is not established
Established (on these fixtures, DEVSIM 2.11.0, this runner): P12 reproduces P4 to double rounding in 2D M2/D0; both restore
contact/cut/species conservation to ~2e-16 while P0 shows 1e-3 defects; the mirror correspondence holds when the bias is
set as defined; remote P4 results equal the earlier local 7H-D2 results bit for bit (max rel diff 0 for M2, M1 and 1D at P4).
Not established: any other mesh family, h, doping, M3 D1/signed override with P12, finer h cost, other DEVSIM/MKL builds;
physical PN validity or mesh convergence. Observation: P0 on the runner differs from the local P0 by up to 2.4e-4 (same
config); P0 is the known-defective mode and P4/P12 agree exactly, but I did not isolate the cause separately.
Production flags, the gate and the review branch are untouched; applying any flag in production needs Codex approval.

## 8. Files, integrity
New: this directory (PLAN, PLAN.sha256, PLAN_ERRATA, REPORT, scripts/, data/) and, on `claude/remote-runner`,
`remote/profiles.py` (profile `d3_precision_mirror`), `remote/request.json`. `tcad/`, `tests/`, `tcad_2d_stagewise.py`,
`examples/` and the 7H-D/D1/D2 audits are identical to review SHA `023bcb90...` (verified by `git diff`).
