# Batch 7H-D3 PLAN (fixed BEFORE any D3 computation; never edited after a result is seen)

Execution location: **GitHub-hosted Windows runner only** (remote runner, branch `claude/remote-runner`,
profile `d3_precision_mirror`). Nothing physical is computed locally.

## 0. What this experiment is and is not
Two open questions left by 7H-D2, tested numerically on the fixtures named below:
1. Does `extended_model=True` + `extended_equation=True` (P12), which restored the contact current in 1D, also match
   all-flags-extended P4 in 2D?
2. Does the mirror check pass with the bias set correctly from the start?

It is a numerical-precision / current-conservation check on these fixtures. It is NOT a validation of PN-diode
physics, other meshes, finer h, other doping or any process order. 7H-D2's failure of M1/M3 against the
registered potential-convergence criterion stands. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the
production default precision flags are not touched. No 7H-D/D1/D2 file, criterion or result is modified.

## 1. Inputs (fixed)
* Physics/setup: identical to 7H-D2 (J1 junction, N_A = N_D = 1e17 cm^-3, T = 300 K, taun = taup = 1e-8 s,
  domain x in [-0.5, 0.5] um, 2D height 0.1 um = 1e-5 cm, ohmic contacts, production setup functions unmodified).
* Solver rule: identical to 7H-D2 (`common_d2.solve`): Poisson abs 1e-10 / rel 1e-10 / 50 it; drift-diffusion
  abs 1e30 / rel 1e-10 / 50 it; accepted iff `converged` and final device relative update < 1e-10.
* Fixtures: `docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixtures_d1.json`
  (file sha256 `80d65d513ff9f923ff35cfe54cd937214b33cd47571797a005013e6e82d9f7f5`, no line breaks inside, so
  checkout newline conversion cannot change it). Used keys, taken from the file, none regenerated:
  * `M2_h0.005`: 4242 nodes, 8040 triangles (all right), coordinates sha256
    `158f59fed0823626fae406d2152306ca908f46e7c8a7118a4fb307443c58dd49`, connectivity sha256
    `f2c579853b7b53a35d4bd9cc6e79aaab92ff07f7cead5527bf1897819eb74c79`
  * `M1_h0.005`: 4242 nodes, 8040 triangles (0 obtuse), coordinates sha256
    `9e4b5bce717f6f37bbeb54ea93da060284a7434d759d157cf536549140a32d85`, connectivity sha256
    `9de5267bb51d699955c58231aaf190aab2515445456d75a8d3d59db7a943b7fc`
  * 1D J1 h = 0.005 um: built by `meshes_d1.grid_1d(0.005, "J1")` (202 nodes).
* Every run re-computes and logs these hashes and counts; any mismatch is a STOP (section 9).

## 2. Experiment 1: precision pair (M2/D0, h = 0.005 um)
Variants, each in its own Python subprocess, only the flags differ:
* P0 all three `extended_*` flags False; P12 model = True, equation = True, solver False; P4 all True.
* Flags are set explicitly (False too) at process start, read back before and after setting, and read again at the end.
Bias sequence exactly as 7H-D2: 0 V DD state, then p contact +0.025, +0.05, +0.075, +0.10 V; device rebuilt, then
-0.025 ... -0.10 V. Recorded points: -0.10, +0.05, +0.10 V and the 0 V control (both branches).
The bias applied is the **actual** `get_parameter` value of the p-contact parameter, read back at every step.
Observables per recorded point (7H-D2 definitions, `worker_d2.measure`, unchanged, imported read-only):
C0 contact currents (left, right, electron+hole), C1 contact reconstruction, C2 five cut currents at
x = -0.25, -0.10, 0, +0.10, +0.25 um (node on a cut goes to the R side; M2 has no node on any of these cuts),
C3 residuals between consecutive cuts per species (`dI_n - q*sum(U*V)`, `dI_p + q*sum(U*V)`) and total (`dI_total`).
Units: 2D A/cm per unit depth (1D: A/cm^2); never mixed. Also recorded: wall time of every solve.

## 3. Tolerances (no new number is invented)
* tau = 1e-5 relative: the 7H-D2 registered conservation/agreement threshold (derived there as 10x better than the
  7.4e-5 reference uncertainty). Reused unchanged for every comparison below.
* Zero-bias rule (7H-D2): every contact and cut current at 0 V satisfies |I| <= 1e-6 * |I(-0.10 V)| of the same run.
* Denominator rule (near-zero currents): a relative comparison of a quantity q is made only if
  |q_reference| >= 1e-6 * max over the five cuts of |I_cut,reference| at the same point. Otherwise that comparison is
  `INCONCLUSIVE` (never replaced by an absolute floor, never PASS). The 0 V point is never compared relatively.
* Bias readback (mirror): parameter readback within 1e-12 V of the set value (a set/get round trip);
  contact-node-potential-derived applied voltage within 1e-9 V (stopping rule: relative update 1e-10 times
  |psi| <= 0.5 V gives <= 5e-11 V; 1e-9 V is 20x that).

## 4. Experiment 1 verdict rules (per biased point, then overall)
* Convergence first: a run whose 11 solve steps are not all accepted is `NOT_COMPLETED`; its currents are not compared.
* Self-consistency of a variant (`SELF_OK`): at each biased point
  |C0_left + C0_right| / |C0_left| <= tau; five-cut spread max|I_cut - median| / |median| <= tau;
  |C0_left - I_cut(0)| / |I_cut(0)| and |C0_right + I_cut(0)| / |I_cut(0)| <= tau;
  C3 species and total residuals / |I_cut(0)| <= tau; C1 = C0 to 1e-10 relative; zero-bias rule.
* `P12 == P4` is **PASS** iff both runs converged, P12 `SELF_OK`, and for all three biased points every one of
  C0_left, C0_right, I_cut(x) (x = 5 cuts) satisfies |q_P12 - q_P4| <= tau * |q_P4|. **FAIL** if any comparison
  exceeds tau or P12 is not `SELF_OK`. **INCONCLUSIVE** if no comparison fails but any is undecidable by the denominator rule.
  **NOT_COMPLETED** if a run did not converge.
* P0 is the control, tabulated identically. `P0_DEFECT_REPRODUCED` iff P0 violates `SELF_OK` at a biased point
  (informational; P0 is not required to pass).

## 5. Experiment 2: mirror, with the correspondence defined before running
Original device O (p at x < 0): acceptors x < 0, donors x > 0; contact `left` (x = -0.5) is the p contact and takes
the applied voltage, `right` (x = +0.5) is the n contact at 0 V.
Mirror device M is the exact reflection x' = -x of the same fixture (node order kept, triangle vertex order
reversed to stay counter-clockwise): donors x' < 0, acceptors x' > 0. Contact `left` (x' = -0.5) is now the **n**
contact, `right` (x' = +0.5) is the **p** contact.

| quantity | original O | mirror M | required relation |
|---|---|---|---|
| p-contact bias parameter | `left_bias` = v | `right_bias` = v (the SAME physical voltage; 7H-D2 set -v) | readback equals v |
| n-contact bias parameter | `right_bias` = 0 | `left_bias` = 0 | readback equals 0 |
| p-contact current C0 | `left` | `right` | C0_M,right = C0_O,left (a contact current is a scalar, invariant under reflection) |
| n-contact current C0 | `right` | `left` | C0_M,left = C0_O,right |
| cut position | x_c | x'_c = -x_c | five pairs (-0.25, +0.25), (-0.10, +0.10), (0, 0), ... |
| cut current (toward +x resp. +x') | I_O(x_c) | I_M(-x_c) | I_M(-x_c) = -I_O(x_c) (flow direction reverses under reflection) |
| node exactly on a cut (|x - x_c| <= 1e-9 um) | assigned to R (side x > x_c) | assigned to **L'** (side x' <= -x_c) | makes the two edge sets mirror images |

Applied voltage is verified twice: parameter readback and contact-node potentials
(V_applied = (psi_p - psi_n)|_bias - (psi_p - psi_n)|_0V of the same branch, within 1e-9 V).
Runs (each original and mirror in its own subprocess): 1D J1 h = 0.005 um and M1/D0 h = 0.005 um, both **P4**
(graded); the same two fixtures at P0 as an ungraded control showing the criterion can fail.
Bias points as in section 2.

## 6. Experiment 2 verdict rules (per fixture, P4)
`MIRROR_PASS` iff all solves accepted, bias readback conditions of section 3 hold on both devices, and at every
biased point |C0_M,right - C0_O,left| <= tau |C0_O,left|, |C0_M,left - C0_O,right| <= tau |C0_O,right|, and for every
cut |I_M(-x_c) + I_O(x_c)| <= tau |I_O(x_c)|; zero-bias rule on both devices. `MIRROR_FAIL` if any condition is
violated (no re-pairing, no sign change afterwards; the cause is analysed separately). `INCONCLUSIVE` if only the
denominator rule blocks a comparison. `NOT_COMPLETED` if any solve failed.
"CERTIFIED" is never used for a post-hoc re-pairing.

## 7. Remote execution
Profile `d3_precision_mirror` (allowlist in `remote/profiles.py`), request id `d3-precision-mirror-001`, on
`claude/remote-runner`. The driver refuses to run outside a GitHub-hosted runner. Runner status PASS means only that
the driver finished and wrote results; the physics verdicts are in `analysis_d3.json`. Artifact: `summary.json`,
`run.log`, every run JSON, analysis JSON/markdown (well below the 200 MB limit).

## 8. Reporting
Every verdict above is stated separately (PASS / FAIL / INCONCLUSIVE / NOT_COMPLETED) with limits. Results are
reported even if they contradict expectations; the PLAN is not edited afterwards.

## 9. Stop conditions (report, do not adapt)
Fixture hash / node / triangle mismatch; contact bias not readable; remote result differing from a local one without
an isolated cause; anything requiring a production change. No physical parameter, mesh, tolerance or sign rule is
changed to obtain a result.
