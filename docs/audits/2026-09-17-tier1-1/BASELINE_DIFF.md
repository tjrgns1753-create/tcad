# Tier 1-1 전체 감사 — baseline(2026-09-16) 대비

- baseline: {"total": 120, "status": {"PASS": 91, "FAIL": 29}, "unit": {"PASS": 44}, "integration": {"PASS": 47, "FAIL": 29}, "failure_categories": {"API/자료형 호환 실패": 3, "assertion 불일치": 6, "예상한 도핑 profile 부재": 1, "v2 미지원 상태로 device mapping 차단": 19}}
- post-fix: {"total": 120, "status": {"PASS": 89, "FAIL": 31}, "unit": {"PASS": 44}, "integration": {"PASS": 45, "FAIL": 31}, "failure_categories": {"API/자료형 호환 실패": 3, "assertion 불일치": 8, "예상한 도핑 profile 부재": 1, "v2 미지원 상태로 device mapping 차단": 19}}

## 상태 또는 실패 분류가 바뀐 파일

| 테스트 | baseline | 분류 | post-fix | 분류 | 판정 |
|---|---|---|---|---|---|
| test_bosch_drie_resist_mask_real.py | PASS |  | FAIL | assertion 불일치 | 신규 실패 |
| test_gui_implant_windows_overlay_note_real.py | PASS |  | FAIL | assertion 불일치 | 신규 실패 |

## 전체 파일 대조

| 테스트 | baseline | post-fix | baseline 초 | post-fix 초 |
|---|---|---|---:|---:|
| test_anneal_profile_mock.py | PASS | PASS | 0.25 | 0.25 |
| test_cad_negative_validation_mock.py | PASS | PASS | 0.36 | 0.42 |
| test_cli_doping_initial_state_branch_mock.py | PASS | PASS | 0.59 | 0.72 |
| test_dc_operating_point_mock.py | PASS | PASS | 0.17 | 0.14 |
| test_diffusion_model_mock.py | PASS | PASS | 0.30 | 0.28 |
| test_dopant_models_mock.py | PASS | PASS | 0.45 | 0.33 |
| test_dopant_profile_mock.py | PASS | PASS | 0.59 | 0.27 |
| test_doping_staleness_mock.py | PASS | PASS | 2.52 | 1.31 |
| test_doping_unsupported_hover_note_mock.py | PASS | PASS | 1.08 | 0.83 |
| test_gaussian_implant_no_existing_param_mock.py | PASS | PASS | 0.34 | 0.31 |
| test_gui_error_dialog_visibility_gate_mock.py | PASS | PASS | 1.25 | 0.94 |
| test_gui_gate_stack_state_mock.py | PASS | PASS | 1.11 | 0.94 |
| test_gui_litho_lifecycle_mock.py | PASS | PASS | 1.28 | 0.95 |
| test_gui_no_forced_order_mock.py | PASS | PASS | 1.61 | 0.94 |
| test_implant_windows_from_mask_mock.py | PASS | PASS | 0.39 | 0.36 |
| test_mask_spans_from_openings_mock.py | PASS | PASS | 0.28 | 0.23 |
| test_mesh_refine_mock.py | PASS | PASS | 1.09 | 0.36 |
| test_phase1_bosch_mock.py | PASS | PASS | 0.31 | 0.28 |
| test_physics_tables_mock.py | PASS | PASS | 0.39 | 0.31 |
| test_physics_values_mock.py | PASS | PASS | 0.52 | 0.27 |
| test_pin_model_mock.py | PASS | PASS | 0.75 | 0.44 |
| test_resolver_mock.py | PASS | PASS | 0.34 | 0.30 |
| test_thermal_anneal_mock.py | PASS | PASS | 0.64 | 0.33 |
| test_wafer_state_doping_mock.py | PASS | PASS | 0.97 | 0.31 |
| test_wafer_state_v2_anneal_fail_closed_mock.py | PASS | PASS | 0.36 | 0.34 |
| test_wafer_state_v2_apply_doping_barrier_mock.py | PASS | PASS | 0.28 | 0.33 |
| test_wafer_state_v2_barrier_physics_mock.py | PASS | PASS | 0.33 | 0.31 |
| test_wafer_state_v2_devsim_mapping_gate_mock.py | PASS | PASS | 0.50 | 0.31 |
| test_wafer_state_v2_etch_conservation_mock.py | PASS | PASS | 0.47 | 0.33 |
| test_wafer_state_v2_exact_inventory_mock.py | PASS | PASS | 0.31 | 0.33 |
| test_wafer_state_v2_explicit_doping_target_mock.py | PASS | PASS | 0.33 | 0.34 |
| test_wafer_state_v2_fail_closed_no_resurrection_mock.py | PASS | PASS | 0.42 | 0.30 |
| test_wafer_state_v2_gate_stack_fallback_fail_closed_mock.py | PASS | PASS | 0.81 | 0.73 |
| test_wafer_state_v2_instance_not_name_mock.py | PASS | PASS | 0.41 | 0.27 |
| test_wafer_state_v2_legacy_migration_fail_closed_mock.py | PASS | PASS | 0.98 | 0.28 |
| test_wafer_state_v2_multi_extent_provenance_mock.py | PASS | PASS | 0.34 | 0.28 |
| test_wafer_state_v2_no_last_step_category_mock.py | PASS | PASS | 1.12 | 0.53 |
| test_wafer_state_v2_no_numeric_without_exact_integral_mock.py | PASS | PASS | 0.30 | 0.34 |
| test_wafer_state_v2_oxidation_unsupported_mock.py | PASS | PASS | 0.64 | 0.28 |
| test_wafer_state_v2_redeposit_no_resurrection_mock.py | PASS | PASS | 0.52 | 0.28 |
| test_wafer_state_v2_remesh_preserved_mock.py | PASS | PASS | 0.42 | 0.31 |
| test_wafer_state_v2_transform_structural_validation_mock.py | PASS | PASS | 0.34 | 0.33 |
| test_wafer_state_v2_transform_targets_instance_mock.py | PASS | PASS | 0.58 | 0.30 |
| test_wafer_state_v2_unsupported_returns_none_mock.py | PASS | PASS | 0.52 | 0.28 |
| test_wafer_state_v2_initial_geometry_devsim_real.py | PASS | PASS | 7.77 | 3.88 |
| test_physics_references_real.py | PASS | PASS | 25.39 | 13.48 |
| test_etch_selectivity_real.py | PASS | PASS | 20.64 | 10.55 |
| test_order_independence_real.py | PASS | PASS | 5.62 | 3.30 |
| test_thermal_anneal_acceptance_real.py | PASS | PASS | 1.42 | 0.88 |
| test_gui_thermal_anneal_real.py | FAIL | FAIL | 3.42 | 2.19 |
| test_ce1_order_sensitive_geometry_real.py | PASS | PASS | 1.97 | 0.81 |
| test_ce2_oxidation_conversion_unsupported_real.py | FAIL | FAIL | 110.70 | 53.64 |
| test_ce3_implant_anneal_etch_implant_real.py | FAIL | FAIL | 4.05 | 2.25 |
| test_gui_measurement_doping_kinds_real.py | FAIL | FAIL | 1.09 | 0.89 |
| test_auto_refine_from_doping_real.py | FAIL | FAIL | 3.86 | 2.22 |
| test_blanket_no_mask_real.py | PASS | PASS | 3.56 | 1.94 |
| test_bosch_cycle_safety_real.py | PASS | PASS | 18.78 | 12.41 |
| test_bosch_drie_resist_mask_real.py | PASS | FAIL | 11.84 | 7.06 |
| test_cad_negative_validation_real.py | PASS | PASS | 1.66 | 0.80 |
| test_deposition_mask_mode_real.py | PASS | PASS | 1.34 | 0.80 |
| test_device_fabrication_to_dc_sweep_real.py | FAIL | FAIL | 109.84 | 97.03 |
| test_device_lifecycle_repeat_real.py | FAIL | FAIL | 9.45 | 4.50 |
| test_directional_deposition_growth_real.py | PASS | PASS | 7.44 | 3.67 |
| test_dopant_profile_matches_devsim_real.py | PASS | PASS | 1.86 | 1.03 |
| test_doping_barrier_windows_real.py | FAIL | FAIL | 2.55 | 1.52 |
| test_doping_donor_acceptor_all_kinds_real.py | PASS | PASS | 0.30 | 0.30 |
| test_doping_mapping_per_node_real.py | FAIL | FAIL | 1.69 | 1.19 |
| test_doping_mapping_recovery_real.py | FAIL | FAIL | 1.44 | 0.72 |
| test_doping_overlay_surface_profile_real.py | PASS | PASS | 1.26 | 0.94 |
| test_gate_contact_placement_real.py | PASS | PASS | 1.20 | 0.80 |
| test_gate_patterning_remask_real.py | PASS | PASS | 2.55 | 1.16 |
| test_gate_stack_geometry_real.py | PASS | PASS | 1.58 | 0.80 |
| test_gaussian_implant_doping_real.py | FAIL | FAIL | 1.69 | 0.89 |
| test_geometric_trench_deposition_real.py | PASS | PASS | 1.19 | 0.80 |
| test_gui_doping_color_overlay_real.py | FAIL | FAIL | 108.59 | 52.03 |
| test_gui_doping_donor_acceptor_real.py | FAIL | FAIL | 22.17 | 12.09 |
| test_gui_doping_survives_geometry_steps_real.py | FAIL | FAIL | 4.72 | 3.03 |
| test_gui_electrode_panel_real.py | FAIL | FAIL | 7.42 | 4.28 |
| test_gui_headless_no_modal_hang_real.py | PASS | PASS | 10.59 | 5.61 |
| test_gui_implant_windows_overlay_note_real.py | PASS | FAIL | 15.25 | 8.08 |
| test_gui_litho_placeholder_visibility_real.py | PASS | PASS | 5.36 | 3.92 |
| test_gui_measurement_captures_physics_status_real.py | PASS | PASS | 17.64 | 11.08 |
| test_gui_process_state_chaining_real.py | PASS | PASS | 1.42 | 0.91 |
| test_implant_windows_doping_real.py | FAIL | FAIL | 2.62 | 1.75 |
| test_koh_crystallographic_wet_etch_real.py | PASS | PASS | 0.97 | 0.69 |
| test_litho_lifecycle_state_real.py | PASS | PASS | 6.25 | 3.75 |
| test_locos_birds_beak_real.py | PASS | PASS | 15.31 | 7.50 |
| test_locos_chaining_real.py | PASS | PASS | 2.92 | 1.97 |
| test_locos_contact_mode_fix_real.py | PASS | PASS | 1.30 | 0.95 |
| test_locos_devsim_import_real.py | PASS | PASS | 0.95 | 0.86 |
| test_mask_spans_real.py | PASS | PASS | 1.86 | 1.06 |
| test_mosfet_body_bias_real.py | FAIL | FAIL | 108.09 | 96.12 |
| test_mosfet_body_contact_real.py | FAIL | FAIL | 99.50 | 97.48 |
| test_mosfet_gate_stack_cv_real.py | FAIL | FAIL | 3.56 | 3.31 |
| test_mosfet_id_vds_real.py | FAIL | FAIL | 111.12 | 97.33 |
| test_mosfet_id_vgs_real.py | FAIL | FAIL | 103.94 | 97.23 |
| test_mosfet_vth_extraction_real.py | FAIL | FAIL | 102.64 | 96.64 |
| test_oxidation_pr_etch_reaches_si_real.py | PASS | PASS | 10.12 | 6.28 |
| test_phase13_process_flow_real.py | PASS | PASS | 3.80 | 2.95 |
| test_phase14_flow_devsim_real.py | FAIL | FAIL | 22.02 | 16.69 |
| test_phase2_etching_real.py | PASS | PASS | 6.89 | 4.59 |
| test_phase3_deposition_real.py | PASS | PASS | 2.42 | 1.47 |
| test_phase4_oxidation_real.py | PASS | PASS | 1.33 | 0.89 |
| test_phase5_devsim_real.py | PASS | PASS | 1.08 | 0.89 |
| test_phase6_characterization_real.py | PASS | PASS | 2.62 | 1.66 |
| test_phase7_doping_real.py | FAIL | FAIL | 1.30 | 0.83 |
| test_phase8_pn_junction_real.py | FAIL | FAIL | 12.53 | 3.38 |
| test_phase9_mos_cv_real.py | FAIL | FAIL | 55.86 | 14.58 |
| test_physics_rules_real.py | PASS | PASS | 18.11 | 4.98 |
| test_pin_placement_validation_real.py | PASS | PASS | 2.61 | 0.84 |
| test_point_contact_import_real.py | PASS | PASS | 2.62 | 0.83 |
| test_pr_strip_real.py | PASS | PASS | 2.16 | 0.75 |
| test_process_state_resume_real.py | PASS | PASS | 10.41 | 2.81 |
| test_resolver_wired_real.py | PASS | PASS | 5.44 | 1.41 |
| test_robust_iv_sweep_real.py | FAIL | FAIL | 108.62 | 30.77 |
| test_status_propagation_real.py | PASS | PASS | 4.74 | 1.41 |
| test_voltage_probe_real.py | FAIL | FAIL | 2.44 | 0.75 |
| test_wafer_state_accumulation_devsim_real.py | FAIL | FAIL | 2.28 | 0.84 |
| test_wafer_state_real.py | PASS | PASS | 150.72 | 108.30 |
| test_wet_etch_crystal_frame_real.py | PASS | PASS | 1.38 | 0.78 |
