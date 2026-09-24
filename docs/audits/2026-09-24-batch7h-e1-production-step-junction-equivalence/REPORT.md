# Batch 7H-E1 REPORT: production 2D step-junction path vs the D2/D4 benchmarks

PLAN: `PLAN.md`, sha256 `ef7a3eadcd4d2e16935f95696bda257dd47c5f91f351ea08fe8fec83fd030a57`, committed alone in
`628895894b6d16bd47970095dfae68f7413ca266` before any code or execution (`analysis_e1.json: plan_matches = true`).
Code + profile + request: `7688b41fb1a16da62ccf9dbe69bf1fb29fc201a6`. Execution: GitHub-hosted Windows runner only,
run `36012608804` (request `e1-production-step-junction-001`, profile `e1_production_step_junction`), status PASS, exit 0,
402 s, DEVSIM 2.11.0 with MKL PARDISO, `code_paths_identical_to_review_sha = true` (review SHA
`023bcb90f8b8a0972d6df84f097ca6387f0ab82a`). Locally: code writing, static checks, synthetic analyzer test (6/6 cases plus
strict JSON, `data/synthetic_e1_results_pre_run.json`) and a post-hoc numpy localization of the downloaded mesh arrays
(`data/posthoc_mesh_localization.txt`, descriptive, not preregistered, not graded). No ViennaPS or DEVSIM ran locally.

Artifact integrity: every output sha256 matches `summary.json`; all JSON parse with a strict parser (NaN/Infinity rejected);
sensitive-pattern scan (user path, runner home, tokens) found nothing. Hashes: `data/artifact_remote_run_36012608804.sha256`.

## 1. Same / different / still unknown

**Same (numbers or hashes match):**
- Region set `["Si"]`; two ohmic contacts on the x extremes (`Si_xmin`, `Si_xmax`), 101 nodes each.
- Material parameters read back from the production device (both shadows) equal the 7H-D benchmark readback exactly:
  T 300 K, kT 4.1419509e-21 J, V_t 0.025887193125 V, q 1.6e-19 C, eps 9.8235e-13 F/cm, n_i = n1 = p1 = 1e10 cm^-3,
  mu_n 400, mu_p 200 cm^2/(V s), taun = taup = 1e-8 s (SRH only, constant mobility).
- No boundary Gabriel violation (0 = 0).
- At 0 V, S12: contact potentials +-0.4768597 V, i.e. psi_R - psi_L = 0.9537194 V = analytic V_bi 0.95372 V (report only).

**Different (every property that determines the discrete solution):**
- Domain 10 x 5 um (production) vs 1 x 0.1 um; 123861 nodes / 247000 triangles vs 4242 / 8040.
- Mesh quality: production has 3000 obtuse triangles (max angle 133.15 deg, min 1.85 deg), 200 exact Delaunay violations,
  200 negative signed edge couples and 200 negative signed node volumes; the D2/D4 fixtures (M1/M2 D0) have 0 of each.
- DEVSIM sum NodeVolume / exact area: 1.0582520 (production) vs 1.0 (benchmark).
- Junction representation: J0 (1601 nodes exactly on x = 0, NetDoping = 0 there, control-volume area 1.5625e-10 cm^2) vs J1
  (no node on x = 0).
- Doping 1e18 / 1e18 cm^-3 vs 1e17 / 1e17.
- Bias: single jump to +0.3 V on the n contact (0.3 V reverse) vs 0.025 V ramp on the p contact to +-0.10 V.
- Solver: production routine Poisson abs 1.0 / rel 1e-6, DD abs 1e10 / rel 1e-6, 100 iterations vs benchmark Poisson
  1e-10 / 1e-10, DD 1e30 / 1e-10, 50 iterations with an info-converged acceptance rule.
- Precision flags: none (production default) vs P12 / P4.

**Still unknown (not measured by this batch):**
- Whether any production result converges with the mesh (one mesh only: `mesh_convergence = UNVERIFIED`).
- The DEVSIM `EdgeCouple` values actually used on the 200 edges whose signed couple is negative (NodeVolume was recorded,
  EdgeCouple was not).
- The effect of the NodeVolume excess (section 4) on the terminal current and on Poisson charge balance.
- Whether the production solver tolerances give an accurate solution (a converged solve with RelError below tolerance is a
  convergence diagnostic, not an error bound).
- J0 convergence behaviour (the D series certified nothing for J0).
- Any other GUI-reachable geometry (etched surface, non-empty barrier windows, off-centre junction, other doping levels).
- The GUI display of this result (GUI not executed, by instruction).

## 2. Production path (read-only mapping, file:line)

The only path that reaches the 2D step-junction gate today is the GUI. The CLI (`tcad/cli/run_pipeline.py:415`, with
`:26`, `:48`, `:96`, `:223`, `:247`, `:278`) fails closed earlier, as the module docstring of
`tests/integration/test_step_junction_2d_gate_real.py` documents.

| # | Step | Production location | Reproduced in E1 by |
|---|---|---|---|
| 1 | Wafer defaults: width 10 um, depth 5 um, y extent 8 um, grid 0.05 um | `tcad/core/models.py:22-23,100` | `common_e1.GUI` |
| 2 | Materialize the wafer (mask spans, volume mesh with floor) | `tcad_2d_stagewise.py:254-285` | `prod_build_e1.build()` via `make_mask_spans`, `save_volume_mesh` |
| 3 | Initial WaferStateV2 | `tcad_2d_stagewise.py:3854` | `initial_wafer_state_from_recipe` |
| 4 | State sync with the mesh-producing step | `tcad_2d_stagewise.py:5012-5026` | `advance_wafer_state(state, mesh result, None)` |
| 5 | `run_doping` | `tcad_2d_stagewise.py:5028` | same library calls |
| 6 | Build ProcessResult | `tcad_2d_stagewise.py:5074` | `build_process_result` |
| 7 | Step junction: Si, axis x, 0 um, ND = NA = 1e18, ACTIVE | `tcad_2d_stagewise.py:5110`, defaults `:4823-4837` | `apply_step_junction_doping` |
| 8 | Barrier windows (SiO2, x, min thickness 0.0) | `tcad_2d_stagewise.py:5228-5236`, default `:4938-4940` | `derive_barrier_covered_windows` (result `[]`, status OK) |
| 9 | Record doping in state | `tcad_2d_stagewise.py:5278` | `advance_wafer_state(..., "doping", barrier_windows, "x")` |
| 10 | `run_measurement`: import with refine near junction | `tcad_2d_stagewise.py:5704`, kwargs `:5779-5786`, import `:5822`; `tcad/device/devsim/mesh_import.py:974-987` | `import_process_result` (refine near 0.0 on x, half width 0.1 um, 4 levels) |
| 11 | `apply_doping` (gate) | `tcad_2d_stagewise.py:5891`; `tcad/device/devsim/doping_mapping.py:131`, `:339-428`, `:677`; `tcad/physics/wafer_state_v2.py:731` | CONTROL (section 3) |
| 12 | Poisson / DD / contact current | `tcad_2d_stagewise.py:5895`; `tcad/characterization/pn_junction_iv_sweep.py:41`; `tcad/device/devsim/semiconductor_equation.py:50`, `:83`, `:138-159` | SHADOW only (section 5) |
| 13 | Measurement defaults: source pin max, 0.3 V, other pin 0 V | `tcad_2d_stagewise.py:5583-5624` | `common_e1.GUI["measure"]` |

## 3. Control: the production gate (PLAN section 2)

Verdict **GATE_HELD**. `UnsupportedDopingState` raised with reason_code `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`,
resolution `UNSUPPORTED_BY_MODEL`; 123861 of 123861 nodes blocked; `devsim.solve` calls **0**; Donors / Acceptors /
NetDoping writes through `node_model` / `set_node_values` / `edge_model` **0**; doping models absent afterwards: true.
`WaferStateV2.net_doping_at` was observed 123861 times (one per node, in node order, query coordinate = node coordinate at
every node; 0 mismatches against an independent direct query; every value known). Canonical array hashes: Donors
`1b68eef3...46f`, Acceptors `9a140a7d...71e`, NetDoping `6e03dc28...b8f`.

## 4. Pre-checks and comparison table (PLAN section 3)

| Property | Production | D2/D4 benchmark | Same |
|---|---|---|---|
| Si x range (um) | -4.99999966 .. +4.99999966 | -0.5 .. 0.5 | no |
| Si y range (um) | -4.99999966 .. 0 | 0 .. 0.1 | no |
| Regions | `["Si"]` | `["Si"]` | yes |
| Nodes / triangles | 123861 / 247000 | M1, M2: 4242 / 8040 | no |
| Angle classes (acute / right / obtuse) | 0 / 244000 / 3000 | M1 7840 / 200 / 0; M2 0 / 8040 / 0 | no |
| Max angle (deg) | 133.1528692 | 90.0 | no |
| Exact Delaunay violations (interior) | 200 | 0 | no |
| Boundary Gabriel violations | 0 | 0 | yes |
| Negative signed edge couples | 200 (min -3.3146e-06 cm) | 0 | no |
| Negative signed node volumes | 200 (min -2.3315e-12 cm^2) | 0 | no |
| DEVSIM sum NodeVolume / exact area | 1.0582520 | 1.0 | no |
| Nodes exactly at x = 0 | 1601 | 0 | no |
| Junction representation | J0, NetDoping 0.0 at x = 0 (Donors = Acceptors = 1e18 there) | J1 | no |
| x = 0 control-volume area (cm^2) | 1.5625e-10 | 0 | no |
| NA / ND (cm^-3) | 1e18 / 1e18 | 1e17 / 1e17 | no |
| Inventory sum(N x NodeVolume), donor / acceptor (cm^-1) | 2.646411e11 / 2.646411e11 | N x side area exactly (J1) | not comparable |
| Contacts | `Si_xmin`, `Si_xmax` at x = -/+4.99999966 um, 101 nodes each | left / right at -/+0.5 um | no |
| x spacing | 261 distinct x, 0.003125 .. 0.05 um; 0.003125 within 0.1 um of the junction | uniform 0.005 (M2) / irregular non-obtuse (M1) | no |
| Material parameters | readback (section 1) | 7H-D readback | yes (every value equal) |
| Solver rule | Poisson 1.0 / 1e-6; DD 1e10 / 1e-6; 100 it | Poisson 1e-10 / 1e-10; DD 1e30 / 1e-10; 50 it; info-converged | no |
| Precision flags | none | P12 / P4 | no |
| Bias | +0.3 V single jump on the n contact (reverse) | 0.025 V ramp to +-0.10 V on the p contact | no |

Where the mesh defects sit (post-hoc, descriptive, `data/posthoc_mesh_localization.txt`, input npz sha256
`feac9643...b64f`): all 3000 obtuse triangles and all 200 Delaunay-violating edges have their vertices at |x| = 0.10 and
0.15 um, i.e. in the coarse-to-fine transition of the junction refinement (fine side 0.003125 um with 1601 rows, coarse
side 0.05 um with 101 rows). DEVSIM's NodeVolume is exact (ratio 1.0000 to 4 digits) in every other column but is inflated
in exactly these four columns: x = +-0.15 um sum 0.967773 um^2 against a geometric column area of 0.25 um^2 (3.87x),
x = +-0.10 um sum 0.871338 against 0.132812 um^2 (6.56x). The excess, 2.912591 um^2, is the whole difference between
DEVSIM's total 52.912590 um^2 and the triangle area 50.0 um^2. DEVSIM's minimum NodeVolume is positive (4.88e-14 cm^2)
while the exact signed dual volume is negative at 200 nodes, so DEVSIM does not use the signed dual there. Consequence for
the dopant inventory: the geometric integral is N x 25 um^2 = 2.5e11 cm^-1 per side (plus the J0 column share), while
sum(N x NodeVolume) is 2.646411e11 cm^-1, 5.86 % higher. (The `exact_donor_cm-1` field in `prod.json` uses NodeVolume as its
basis and is therefore not a geometric reference.) Its effect on the solution is not quantified here.

## 5. Shadows (audit-only, never production; PLAN sections 4-5)

Identity held for both shadows: mesh file sha256, x / y / element sha256, contacts, regions, doping array sha256, node order
and inventory all equal the control device. Both ran the unmodified `run_pn_junction_iv_sweep` exactly as the GUI calls it
(sweep `Si_xmax` to +0.3 V, `Si_xmin` 0 V); 3 solves each, all converged; no device left afterwards. Flags read back:
S0 all unset; S12 `extended_model` = `extended_equation` = true, `extended_solver` unset. Currents are DEVSIM 2D values
in A/cm (per unit depth).

| Check (limit) | S0 (no flag) | S12 (model + equation) |
|---|---|---|
| Verdict | **SHADOW_INCONSISTENT** | **SHADOW_CONSISTENT** |
| lr mismatch abs(I_L + I_R) / abs(I_L) (1e-5) | 3.998e-3 FAIL | 1.90e-16 |
| 5-cut spread (1e-5) | 1.472e-3 FAIL | 0.0 |
| left vs cut 0 (1e-5) | 2.456e-4 FAIL | 0.0 |
| right vs cut 0 (1e-5) | 4.245e-3 FAIL | 1.90e-16 |
| C3 species (1e-5 abs(I_cut0)) | 1.723e-3 FAIL | 1.41e-16 |
| C3 total (1e-5 abs(I_cut0)) | 1.723e-3 FAIL | 0.0 |
| positivity 0 V / 0.3 V | ok / ok | ok / ok |
| zero-bias currents (1e-6 of the 0.3 V current) | FAIL (cuts up to 9.43e-13 = 2.8 % of 3.4e-11) | ok (max 2.6e-30) |
| quasi-Fermi flatness at 0 V (1e-6 V) | 7.08e-16 V | 5.55e-17 V |
| mass action at 0 V (1e-6) | 2.60e-14 | 2.22e-16 |
| undecidable (denominator rule) | none | none |

Raw values at +0.3 V (reverse):

| Quantity | S0 | S12 |
|---|---|---|
| I contact `Si_xmin` (total; n / p) | -3.397041094e-11 (-1.165e-16 / -3.397029e-11) | -3.396207121e-11 (-1.165e-16 / -3.396195e-11) |
| I contact `Si_xmax` (total; n / p) | +3.410622840e-11 (+3.410619e-11 / +4.21e-17) | +3.396207121e-11 (+3.396203e-11 / +4.21e-17) |
| C1 left / right | -3.397041094e-11 / +3.410622840e-11 | -3.396207121e-11 / +3.396207121e-11 |
| cuts -0.25 / -0.10 / 0 / +0.10 / +0.25 | -3.397057e-11 / -3.391207e-11 / -3.396207e-11 / -3.393024e-11 / -3.397508e-11 | -3.396207121e-11 at all five |
| q int U per band (-0.25..-0.10 / -0.10..0 / 0..+0.10 / +0.10..+0.25) | -2.26e-17 / -1.0750e-11 / -2.3212e-11 / -2.23e-17 | same to 13 digits |
| contact psi (V) | -0.4768597 / +0.7768597 | -0.4768597 / +0.7768597 |
| max abs(E) on edges (V/cm) | 4.172498e5 | 4.172498e5 |
| n range / p range (cm^-3) | 0.0713 .. 1e18 / 0.0969 .. 1e18 | same |
| wall time | 66.2 s | 234.2 s |

At 0 V (S12): max abs(E) 3.581130e5 V/cm. Analytic depletion references (report only, not graded; abrupt, full
depletion, infinite neutral regions): E_peak 3.94e5 V/cm (0 V) and 4.52e5 V/cm (0.3 V reverse); the discrete edge maxima are
9.1 % and 7.7 % lower. These are not exact solutions of the finite-domain problem and are not evidence of error or accuracy.

Reading: on the production mesh, S0 (the production default) reproduces the 7H-D2 float64 contact-current defect (contact
currents disagree with each other and with the interior cuts at the 1e-3 level; spurious 0 V cut currents of 3 %). S12
removes it: all five cuts, both contacts and C1 agree to 1e-16 and the 0 V currents vanish. The S0 x = 0 cut agrees with S12
to about 1e-13 relative; the S0 contact values do not. SHADOW_CONSISTENT is a statement about internal conservation of one
discrete solution on one mesh. It is not evidence that this solution is close to the continuum answer, it does not extend
D4's P12 == P4 result to this mesh (P4 was not run here, by PLAN), and it is not a production-supported result.

## 6. Stop-condition review (PLAN section 7)
No stop condition fired: identity and readback all matched, both shadows converged, carriers positive and finite. The S0
conservation failure is reported as a result, not repaired. Grounds on which the production path remains
`UNSUPPORTED_BY_MODEL` are listed in section 8.

## 7. Confirmation of no change
- Gate unchanged: `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` still raised with 0 solves (section 3).
- No precision flag changed in production; flags were set only inside the audit-only S12 subprocess.
- Production / tests: `sha256sum -c data/start_hashes_prod_tests.txt` rc 0 (232 files); `git diff --quiet 023bcb90 --
  tcad tests tcad_2d_stagewise.py examples` rc 0.
- Existing audits: `data/start_hashes_all_audits.txt` rc 0 (2429 files), `data/start_hashes_d2_d3_d4_tracked.txt` rc 0 (83);
  D4's two original JSON files unchanged.
- `origin/claude/waferstate-v2` = `023bcb90f8b8a0972d6df84f097ca6387f0ab82a`, `origin/main` =
  `d60e9aed3c52ba33dc243f12894bf12f74db16f8` (both equal to the start state). No merge, no force-push, no full regression,
  no GUI execution.

## 8. What must be proven before the gate can be reviewed
1. **Production mesh validity.** The production junction refinement produces 3000 obtuse triangles, 200 non-Delaunay edges
   and 200 negative signed couples / node volumes in its coarse-to-fine transition (|x| = 0.10-0.15 um), where DEVSIM's
   NodeVolume is inflated 3.9x and 6.6x. Either the refinement must produce a mesh without these defects, or a treatment must
   be proven correct for them; the D4 result covers only non-obtuse fixtures.
2. **Dopant conservation.** sum(N x NodeVolume) exceeds the geometric integral N x area by 5.86 %. The DEVSIM inventory must
   equal the canonical WaferStateV2 integral within a derived tolerance, or the discrepancy must be proven harmless for the
   quantities reported to the user.
3. **Contact-current precision in production.** The production default (no flag) fails conservation on the production mesh
   (4.0e-3). A production flag choice needs its own approval and evidence on production-type meshes.
4. **Mesh convergence of the production path.** A refinement study of the actual production refinement (base grid,
   refinement half width and levels) showing monotone convergence of terminal current, cut currents and potential, with J0.
5. **J0 representation.** The node column on x = 0 with NetDoping 0 and its own control volume has no convergence evidence;
   the D series certified J1 only.
6. **Solver accuracy under production tolerances** (Poisson abs 1.0, DD abs 1e10, rel 1e-6, single 0.3 V jump), shown by an
   independent error estimate, not by RelError.
7. **Coverage of reverse bias and 1e18 doping**, which the D2/D4 benchmarks did not cover.
8. **Other GUI-reachable geometries** (etched surfaces, non-empty barrier windows, off-centre junctions, other doping kinds).
9. **The DEVSIM EdgeCouple values used on the 200 negative-couple edges**, which this batch did not record.
10. **GUI display chain**: the displayed result must be the same computed result (not checked here).

## 9. Files of this batch
`PLAN.md`, `PLAN.sha256` (commit 6288958); `scripts/{common_e1,prod_build_e1,shadow_e1,analyze_e1,run_e1,synthetic_e1_test}.py`,
`remote/profiles.py` (profile added), `remote/request.json` (commit 7688b41); `REPORT.md`, `data/start_state.txt`,
`data/start_hashes_*.txt`, `data/synthetic_e1_results_pre_run.json`, `data/posthoc_mesh_localization.txt`,
`data/artifact_remote_run_36012608804.sha256`, `data/remote_run_36012608804/{summary.json,run.log,outputs/e1_out/*}`.
