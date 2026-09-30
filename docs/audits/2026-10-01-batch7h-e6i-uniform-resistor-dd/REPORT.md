# Batch 7H-E6I REPORT: low-field drift-diffusion current of a uniformly doped ACTIVE Si resistor

**Result, limited to the tested model, meshes and bias range.** Through the production DD path (`import_process_result` -> `apply_doping` on the canonical
ACTIVE `WaferStateV2` -> `run_pn_junction_iv_sweep`), the terminal currents of a 1e16 cm^-3 donor Si resistor (2 um x 0.5 um, full-side ohmic contacts,
300 K) agree with `I = sigma (H/L) DeltaV` to 5.5e-13 relative on every tested mesh and bias, with the pre-registered sign and per-unit-depth unit. This is not a
PN / high-doping / process-device validation; `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` and the PN/DD gates are unchanged.

Files: `CRITERIA.md` (33c249a, before any run). Production code: unchanged (this batch adds tests and a remote profile only).

## Model, parameters, theory (read from the device, not from literature)
q = 1.6e-19 C, n_i = 1e10 cm^-3, mu_n = 400, mu_p = 200 cm^2/Vs, T = 300 K, V_t = 0.025887 V, taun = taup = 1e-8 s (project override,
`semiconductor_equation.py:126-127`; DEVSIM default 1e-5), Permittivity 9.8235e-13 F/cm; all equal the pre-registered `simple_physics.py` values (checked in every run).
Theory: n0 = 1.000000000001e16, p0 = 9999.99999999 cm^-3, sigma = 0.6400000000009599 S/cm, G = sigma H/L = 0.16000000000024 A/V per cm depth
(H = 0.5e-4 cm, L = 2e-4 cm), I_ref = |I(+1 mV)| = 1.6e-4 A per cm depth. Unit: per unit out-of-plane depth (DEVSIM implicit 1 cm; GUI prints the same number as "A").
Sign: DEVSIM manual (models page) "current models refer to the instantaneous current flowing into the device": positive bias on Si_xmax gives I(Si_xmax) > 0 and I(Si_xmin) < 0.

## Results (run 36756889121, executed SHA `942d29aacef22518741380a25ea717d7126d153d`, DEVSIM 2.11.0, ViennaPS 4.6.2; all steps rc 0; `resistor_dd.json`)
7 meshes (uniform n=8; one-sided and two-sided transition meshes n = 8, 16, 32), 4 biases each, each on a fresh device, 3 `devsim.solve` per device (equilibrium Poisson, DD
enable, bias), 28 devices, none leaked. Identical at every mesh (to the printed digits): I(Si_xmax) = +1.6e-4 / -1.6e-4 / +3.2e-4 A/cm at +1 / -1 / +2 mV, I(Si_xmin) the opposite,
electron current equal to the total, hole current 8.0e-17 (share 5e-13 = q mu_p p0 / sigma), 0 V currents exactly 0.
| criterion (pre-registered limit) | worst observed over 247 checks |
|---|---|
| total current vs theory, relative (1e-2) | 5.54e-13 |
| conservation |I_max + I_min| / I_ref (1e-6) | 4.4e-13 |
| odd symmetry +1 / -1 mV (1e-2) | 0 |
| linearity +2 mV vs 2 x +1 mV (1e-2) | 8.9e-13 |
| mesh: |G(32) - G(16)| / G(32), both families (1e-2) | 8.9e-13 |
| equilibrium |I(0 V)| / I_ref (1e-4) | 0 (initialisation identity, not an independent validation) |
| electron uniformity max|n/n0 - 1| (1e-4); potential linearity (1e-2) | 0 ; 5.6e-14 |
Recorded only: p / p0 = 1.000 to 3 digits at every node, SRH recombination 0, `Donors` = {1e16}, `Acceptors` = {0}, `NetDoping` = {1e16} written on every device.
Interpretation limits: the discrete potential is exactly linear here, so the current is exact on any of these meshes (Laplace linear precision, E6H) and the mesh-insensitivity
says nothing about convergence for non-uniform doping. The 1e-2 limits were deliberately loose relative to the achieved 1e-13: the test catches unit, sign, depth, conductivity
and aggregation errors, not small-discretisation errors. Transition zones move with n (one-sided centred, two-sided near the left end): a sequence of layouts, not one fixed layout.

## GUI connection (one_sided n = 8, `TCADApplication.run_measurement`)
ACTIVE: 3 solves, 6 doping writes (node_model + set_node_values for Donors / Acceptors / NetDoping), log "DEVSIM MEASUREMENT", source Si_xmax +0.0010 V -> I = 1.6e-4 A, ground -1.6e-4 A;
equal to the direct path (limit 1e-6 on the printed digits), same sign. The GUI labels this number "A" but it is per unit depth (no depth factor is applied) -- reported, not changed.
CHEMICAL and UNKNOWN: 0 solves, 0 doping writes, no measurement block, no info dialog, no leaked device, `physics_status.resolution == UNSUPPORTED_BY_MODEL`; the earlier ACTIVE value was not
re-shown. (My probe read `reason_code` from the wrong key and recorded null; the resolution was asserted. The reason code itself is covered by the existing gate tests.) The GUI measurement used the
E6H mesh with the canonical state built from the explicit recipe bounds (not a ViennaPS-produced wafer mesh).

## Run 1 and the judge fix (kept)
Run 36756642576 (SHA `6401cadbb06e1f0eebde5b4a7b0a9e7b2770746b`) FAILED only criterion 1 on all 7 meshes: my judge's finiteness check also inspected string metadata (contact names, parameter dictionaries) and
treated it as non-finite. Every physics criterion, the input checks and the GUI checks had passed. The defect was in the judge (a false FAIL, not a physics failure); the fix restricts criterion 1 to the numeric
result keys (a missing key or NaN / inf / None / str there still FAILs; unit test extended) and changes no tolerance. The run-1 raw JSON re-judged offline with the fixed judge: pass, 247 checks. Run 2 is the
clean verdict. The NaN / inf synthetic tests in `tests/unit/test_resistor_dd_judge_mock.py` cover every numeric key and every criterion.

## Not verified
PN junctions, high or non-uniform doping, compensated doping, process-derived devices, field-dependent mobility, temperature dependence, F-scale meshes, the robust (continuation) solve path,
current accuracy beyond the linear-response uniform case, hole-dominated (p-type) resistor (same code path but not run).
