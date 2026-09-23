# 실행 결과 인덱스 — 2026-09-16

기존 테스트 파일 120개 실행 시도 완료: {'PASS': 91, 'FAIL': 29}.
Unit 44개: {'PASS': 44}.
Integration 76개: {'PASS': 47, 'FAIL': 29}.

전체 결과는 `validated-env/results.json`, 상세 물리 판정은 [REPORT.md](REPORT.md).
Unit 60초/integration 180초 제한 감사이며 정식 회귀의 장기 timeout 예산과 다르다.
파일이 일찍 실패한 경우 뒤쪽 시나리오는 미실행이다. 아래 분류는 이번 로그의 실패 지점 분류이며 baseline 대비 회귀 판정은 아니다.

| 테스트 | 결과 | 초 | 로그상 실패 유형 |
|---|---|---:|---|
| [test_anneal_profile_mock.py](validated-env/test_anneal_profile_mock.log) | PASS | 0.25 |  |
| [test_cad_negative_validation_mock.py](validated-env/test_cad_negative_validation_mock.log) | PASS | 0.36 |  |
| [test_cli_doping_initial_state_branch_mock.py](validated-env/test_cli_doping_initial_state_branch_mock.log) | PASS | 0.59 |  |
| [test_dc_operating_point_mock.py](validated-env/test_dc_operating_point_mock.log) | PASS | 0.17 |  |
| [test_diffusion_model_mock.py](validated-env/test_diffusion_model_mock.log) | PASS | 0.30 |  |
| [test_dopant_models_mock.py](validated-env/test_dopant_models_mock.log) | PASS | 0.45 |  |
| [test_dopant_profile_mock.py](validated-env/test_dopant_profile_mock.log) | PASS | 0.59 |  |
| [test_doping_staleness_mock.py](validated-env/test_doping_staleness_mock.log) | PASS | 2.52 |  |
| [test_doping_unsupported_hover_note_mock.py](validated-env/test_doping_unsupported_hover_note_mock.log) | PASS | 1.08 |  |
| [test_gaussian_implant_no_existing_param_mock.py](validated-env/test_gaussian_implant_no_existing_param_mock.log) | PASS | 0.34 |  |
| [test_gui_error_dialog_visibility_gate_mock.py](validated-env/test_gui_error_dialog_visibility_gate_mock.log) | PASS | 1.25 |  |
| [test_gui_gate_stack_state_mock.py](validated-env/test_gui_gate_stack_state_mock.log) | PASS | 1.11 |  |
| [test_gui_litho_lifecycle_mock.py](validated-env/test_gui_litho_lifecycle_mock.log) | PASS | 1.28 |  |
| [test_gui_no_forced_order_mock.py](validated-env/test_gui_no_forced_order_mock.log) | PASS | 1.61 |  |
| [test_implant_windows_from_mask_mock.py](validated-env/test_implant_windows_from_mask_mock.log) | PASS | 0.39 |  |
| [test_mask_spans_from_openings_mock.py](validated-env/test_mask_spans_from_openings_mock.log) | PASS | 0.28 |  |
| [test_mesh_refine_mock.py](validated-env/test_mesh_refine_mock.log) | PASS | 1.09 |  |
| [test_phase1_bosch_mock.py](validated-env/test_phase1_bosch_mock.log) | PASS | 0.31 |  |
| [test_physics_tables_mock.py](validated-env/test_physics_tables_mock.log) | PASS | 0.39 |  |
| [test_physics_values_mock.py](validated-env/test_physics_values_mock.log) | PASS | 0.52 |  |
| [test_pin_model_mock.py](validated-env/test_pin_model_mock.log) | PASS | 0.75 |  |
| [test_resolver_mock.py](validated-env/test_resolver_mock.log) | PASS | 0.34 |  |
| [test_thermal_anneal_mock.py](validated-env/test_thermal_anneal_mock.log) | PASS | 0.64 |  |
| [test_wafer_state_doping_mock.py](validated-env/test_wafer_state_doping_mock.log) | PASS | 0.97 |  |
| [test_wafer_state_v2_anneal_fail_closed_mock.py](validated-env/test_wafer_state_v2_anneal_fail_closed_mock.log) | PASS | 0.36 |  |
| [test_wafer_state_v2_apply_doping_barrier_mock.py](validated-env/test_wafer_state_v2_apply_doping_barrier_mock.log) | PASS | 0.28 |  |
| [test_wafer_state_v2_barrier_physics_mock.py](validated-env/test_wafer_state_v2_barrier_physics_mock.log) | PASS | 0.33 |  |
| [test_wafer_state_v2_devsim_mapping_gate_mock.py](validated-env/test_wafer_state_v2_devsim_mapping_gate_mock.log) | PASS | 0.50 |  |
| [test_wafer_state_v2_etch_conservation_mock.py](validated-env/test_wafer_state_v2_etch_conservation_mock.log) | PASS | 0.47 |  |
| [test_wafer_state_v2_exact_inventory_mock.py](validated-env/test_wafer_state_v2_exact_inventory_mock.log) | PASS | 0.31 |  |
| [test_wafer_state_v2_explicit_doping_target_mock.py](validated-env/test_wafer_state_v2_explicit_doping_target_mock.log) | PASS | 0.33 |  |
| [test_wafer_state_v2_fail_closed_no_resurrection_mock.py](validated-env/test_wafer_state_v2_fail_closed_no_resurrection_mock.log) | PASS | 0.42 |  |
| [test_wafer_state_v2_gate_stack_fallback_fail_closed_mock.py](validated-env/test_wafer_state_v2_gate_stack_fallback_fail_closed_mock.log) | PASS | 0.81 |  |
| [test_wafer_state_v2_instance_not_name_mock.py](validated-env/test_wafer_state_v2_instance_not_name_mock.log) | PASS | 0.41 |  |
| [test_wafer_state_v2_legacy_migration_fail_closed_mock.py](validated-env/test_wafer_state_v2_legacy_migration_fail_closed_mock.log) | PASS | 0.98 |  |
| [test_wafer_state_v2_multi_extent_provenance_mock.py](validated-env/test_wafer_state_v2_multi_extent_provenance_mock.log) | PASS | 0.34 |  |
| [test_wafer_state_v2_no_last_step_category_mock.py](validated-env/test_wafer_state_v2_no_last_step_category_mock.log) | PASS | 1.12 |  |
| [test_wafer_state_v2_no_numeric_without_exact_integral_mock.py](validated-env/test_wafer_state_v2_no_numeric_without_exact_integral_mock.log) | PASS | 0.30 |  |
| [test_wafer_state_v2_oxidation_unsupported_mock.py](validated-env/test_wafer_state_v2_oxidation_unsupported_mock.log) | PASS | 0.64 |  |
| [test_wafer_state_v2_redeposit_no_resurrection_mock.py](validated-env/test_wafer_state_v2_redeposit_no_resurrection_mock.log) | PASS | 0.52 |  |
| [test_wafer_state_v2_remesh_preserved_mock.py](validated-env/test_wafer_state_v2_remesh_preserved_mock.log) | PASS | 0.42 |  |
| [test_wafer_state_v2_transform_structural_validation_mock.py](validated-env/test_wafer_state_v2_transform_structural_validation_mock.log) | PASS | 0.34 |  |
| [test_wafer_state_v2_transform_targets_instance_mock.py](validated-env/test_wafer_state_v2_transform_targets_instance_mock.log) | PASS | 0.58 |  |
| [test_wafer_state_v2_unsupported_returns_none_mock.py](validated-env/test_wafer_state_v2_unsupported_returns_none_mock.log) | PASS | 0.52 |  |
| [test_wafer_state_v2_initial_geometry_devsim_real.py](validated-env/test_wafer_state_v2_initial_geometry_devsim_real.log) | PASS | 7.77 |  |
| [test_physics_references_real.py](validated-env/test_physics_references_real.log) | PASS | 25.39 |  |
| [test_etch_selectivity_real.py](validated-env/test_etch_selectivity_real.log) | PASS | 20.64 |  |
| [test_order_independence_real.py](validated-env/test_order_independence_real.log) | PASS | 5.62 |  |
| [test_thermal_anneal_acceptance_real.py](validated-env/test_thermal_anneal_acceptance_real.log) | PASS | 1.42 |  |
| [test_gui_thermal_anneal_real.py](validated-env/test_gui_thermal_anneal_real.log) | FAIL | 3.42 | API/자료형 호환 실패 |
| [test_ce1_order_sensitive_geometry_real.py](validated-env/test_ce1_order_sensitive_geometry_real.log) | PASS | 1.97 |  |
| [test_ce2_oxidation_conversion_unsupported_real.py](validated-env/test_ce2_oxidation_conversion_unsupported_real.log) | FAIL | 110.70 | assertion 불일치; 보고서와 로그 확인 |
| [test_ce3_implant_anneal_etch_implant_real.py](validated-env/test_ce3_implant_anneal_etch_implant_real.log) | FAIL | 4.05 | 예상한 도핑 profile 부재 |
| [test_gui_measurement_doping_kinds_real.py](validated-env/test_gui_measurement_doping_kinds_real.log) | FAIL | 1.09 | v2 미지원 상태로 device mapping 차단 |
| [test_auto_refine_from_doping_real.py](validated-env/test_auto_refine_from_doping_real.log) | FAIL | 3.86 | v2 미지원 상태로 device mapping 차단 |
| [test_blanket_no_mask_real.py](validated-env/test_blanket_no_mask_real.log) | PASS | 3.56 |  |
| [test_bosch_cycle_safety_real.py](validated-env/test_bosch_cycle_safety_real.log) | PASS | 18.78 |  |
| [test_bosch_drie_resist_mask_real.py](validated-env/test_bosch_drie_resist_mask_real.log) | PASS | 11.84 |  |
| [test_cad_negative_validation_real.py](validated-env/test_cad_negative_validation_real.log) | PASS | 1.66 |  |
| [test_deposition_mask_mode_real.py](validated-env/test_deposition_mask_mode_real.log) | PASS | 1.34 |  |
| [test_device_fabrication_to_dc_sweep_real.py](validated-env/test_device_fabrication_to_dc_sweep_real.log) | FAIL | 109.84 | v2 미지원 상태로 device mapping 차단 |
| [test_device_lifecycle_repeat_real.py](validated-env/test_device_lifecycle_repeat_real.log) | FAIL | 9.45 | v2 미지원 상태로 device mapping 차단 |
| [test_directional_deposition_growth_real.py](validated-env/test_directional_deposition_growth_real.log) | PASS | 7.44 |  |
| [test_dopant_profile_matches_devsim_real.py](validated-env/test_dopant_profile_matches_devsim_real.log) | PASS | 1.86 |  |
| [test_doping_barrier_windows_real.py](validated-env/test_doping_barrier_windows_real.log) | FAIL | 2.55 | API/자료형 호환 실패 |
| [test_doping_donor_acceptor_all_kinds_real.py](validated-env/test_doping_donor_acceptor_all_kinds_real.log) | PASS | 0.30 |  |
| [test_doping_mapping_per_node_real.py](validated-env/test_doping_mapping_per_node_real.log) | FAIL | 1.69 | v2 미지원 상태로 device mapping 차단 |
| [test_doping_mapping_recovery_real.py](validated-env/test_doping_mapping_recovery_real.log) | FAIL | 1.44 | API/자료형 호환 실패 |
| [test_doping_overlay_surface_profile_real.py](validated-env/test_doping_overlay_surface_profile_real.log) | PASS | 1.26 |  |
| [test_gate_contact_placement_real.py](validated-env/test_gate_contact_placement_real.log) | PASS | 1.20 |  |
| [test_gate_patterning_remask_real.py](validated-env/test_gate_patterning_remask_real.log) | PASS | 2.55 |  |
| [test_gate_stack_geometry_real.py](validated-env/test_gate_stack_geometry_real.log) | PASS | 1.58 |  |
| [test_gaussian_implant_doping_real.py](validated-env/test_gaussian_implant_doping_real.log) | FAIL | 1.69 | v2 미지원 상태로 device mapping 차단 |
| [test_geometric_trench_deposition_real.py](validated-env/test_geometric_trench_deposition_real.log) | PASS | 1.19 |  |
| [test_gui_doping_color_overlay_real.py](validated-env/test_gui_doping_color_overlay_real.log) | FAIL | 108.59 | assertion 불일치; 보고서와 로그 확인 |
| [test_gui_doping_donor_acceptor_real.py](validated-env/test_gui_doping_donor_acceptor_real.log) | FAIL | 22.17 | assertion 불일치; 보고서와 로그 확인 |
| [test_gui_doping_survives_geometry_steps_real.py](validated-env/test_gui_doping_survives_geometry_steps_real.log) | FAIL | 4.72 | assertion 불일치; 보고서와 로그 확인 |
| [test_gui_electrode_panel_real.py](validated-env/test_gui_electrode_panel_real.log) | FAIL | 7.42 | assertion 불일치; 보고서와 로그 확인 |
| [test_gui_headless_no_modal_hang_real.py](validated-env/test_gui_headless_no_modal_hang_real.log) | PASS | 10.59 |  |
| [test_gui_implant_windows_overlay_note_real.py](validated-env/test_gui_implant_windows_overlay_note_real.log) | PASS | 15.25 |  |
| [test_gui_litho_placeholder_visibility_real.py](validated-env/test_gui_litho_placeholder_visibility_real.log) | PASS | 5.36 |  |
| [test_gui_measurement_captures_physics_status_real.py](validated-env/test_gui_measurement_captures_physics_status_real.log) | PASS | 17.64 |  |
| [test_gui_process_state_chaining_real.py](validated-env/test_gui_process_state_chaining_real.log) | PASS | 1.42 |  |
| [test_implant_windows_doping_real.py](validated-env/test_implant_windows_doping_real.log) | FAIL | 2.62 | v2 미지원 상태로 device mapping 차단 |
| [test_koh_crystallographic_wet_etch_real.py](validated-env/test_koh_crystallographic_wet_etch_real.log) | PASS | 0.97 |  |
| [test_litho_lifecycle_state_real.py](validated-env/test_litho_lifecycle_state_real.log) | PASS | 6.25 |  |
| [test_locos_birds_beak_real.py](validated-env/test_locos_birds_beak_real.log) | PASS | 15.31 |  |
| [test_locos_chaining_real.py](validated-env/test_locos_chaining_real.log) | PASS | 2.92 |  |
| [test_locos_contact_mode_fix_real.py](validated-env/test_locos_contact_mode_fix_real.log) | PASS | 1.30 |  |
| [test_locos_devsim_import_real.py](validated-env/test_locos_devsim_import_real.log) | PASS | 0.95 |  |
| [test_mask_spans_real.py](validated-env/test_mask_spans_real.log) | PASS | 1.86 |  |
| [test_mosfet_body_bias_real.py](validated-env/test_mosfet_body_bias_real.log) | FAIL | 108.09 | v2 미지원 상태로 device mapping 차단 |
| [test_mosfet_body_contact_real.py](validated-env/test_mosfet_body_contact_real.log) | FAIL | 99.50 | v2 미지원 상태로 device mapping 차단 |
| [test_mosfet_gate_stack_cv_real.py](validated-env/test_mosfet_gate_stack_cv_real.log) | FAIL | 3.56 | v2 미지원 상태로 device mapping 차단 |
| [test_mosfet_id_vds_real.py](validated-env/test_mosfet_id_vds_real.log) | FAIL | 111.12 | v2 미지원 상태로 device mapping 차단 |
| [test_mosfet_id_vgs_real.py](validated-env/test_mosfet_id_vgs_real.log) | FAIL | 103.94 | v2 미지원 상태로 device mapping 차단 |
| [test_mosfet_vth_extraction_real.py](validated-env/test_mosfet_vth_extraction_real.log) | FAIL | 102.64 | v2 미지원 상태로 device mapping 차단 |
| [test_oxidation_pr_etch_reaches_si_real.py](validated-env/test_oxidation_pr_etch_reaches_si_real.log) | PASS | 10.12 |  |
| [test_phase13_process_flow_real.py](validated-env/test_phase13_process_flow_real.log) | PASS | 3.80 |  |
| [test_phase14_flow_devsim_real.py](validated-env/test_phase14_flow_devsim_real.log) | FAIL | 22.02 | v2 미지원 상태로 device mapping 차단 |
| [test_phase2_etching_real.py](validated-env/test_phase2_etching_real.log) | PASS | 6.89 |  |
| [test_phase3_deposition_real.py](validated-env/test_phase3_deposition_real.log) | PASS | 2.42 |  |
| [test_phase4_oxidation_real.py](validated-env/test_phase4_oxidation_real.log) | PASS | 1.33 |  |
| [test_phase5_devsim_real.py](validated-env/test_phase5_devsim_real.log) | PASS | 1.08 |  |
| [test_phase6_characterization_real.py](validated-env/test_phase6_characterization_real.log) | PASS | 2.62 |  |
| [test_phase7_doping_real.py](validated-env/test_phase7_doping_real.log) | FAIL | 1.30 | v2 미지원 상태로 device mapping 차단 |
| [test_phase8_pn_junction_real.py](validated-env/test_phase8_pn_junction_real.log) | FAIL | 12.53 | v2 미지원 상태로 device mapping 차단 |
| [test_phase9_mos_cv_real.py](validated-env/test_phase9_mos_cv_real.log) | FAIL | 55.86 | v2 미지원 상태로 device mapping 차단 |
| [test_physics_rules_real.py](validated-env/test_physics_rules_real.log) | PASS | 18.11 |  |
| [test_pin_placement_validation_real.py](validated-env/test_pin_placement_validation_real.log) | PASS | 2.61 |  |
| [test_point_contact_import_real.py](validated-env/test_point_contact_import_real.log) | PASS | 2.62 |  |
| [test_pr_strip_real.py](validated-env/test_pr_strip_real.log) | PASS | 2.16 |  |
| [test_process_state_resume_real.py](validated-env/test_process_state_resume_real.log) | PASS | 10.41 |  |
| [test_resolver_wired_real.py](validated-env/test_resolver_wired_real.log) | PASS | 5.44 |  |
| [test_robust_iv_sweep_real.py](validated-env/test_robust_iv_sweep_real.log) | FAIL | 108.62 | v2 미지원 상태로 device mapping 차단 |
| [test_status_propagation_real.py](validated-env/test_status_propagation_real.log) | PASS | 4.74 |  |
| [test_voltage_probe_real.py](validated-env/test_voltage_probe_real.log) | FAIL | 2.44 | v2 미지원 상태로 device mapping 차단 |
| [test_wafer_state_accumulation_devsim_real.py](validated-env/test_wafer_state_accumulation_devsim_real.log) | FAIL | 2.28 | assertion 불일치; 보고서와 로그 확인 |
| [test_wafer_state_real.py](validated-env/test_wafer_state_real.log) | PASS | 150.72 |  |
| [test_wet_etch_crystal_frame_real.py](validated-env/test_wet_etch_crystal_frame_real.log) | PASS | 1.38 |  |

## 실패 지점 분류

- API/자료형 호환 실패: 3개
- assertion 불일치; 보고서와 로그 확인: 6개
- 예상한 도핑 profile 부재: 1개
- v2 미지원 상태로 device mapping 차단: 19개

## 별도 반례와 실제 물리 benchmark

- [상태 전달 반례 수치](counterexample_state.json): 6개 주요 결함 + 보조 조회
- [실제 ViennaPS 산화](counterexample_oxidation.json): 3 grids × 2 durations
- [실제 GUI/DevSim 미지원 상태 우회](counterexample_gui.json)
- [실제 PN 3-grid 결과](counterexample_diode.json)

초기 DLL 경로 오류로 중단한 상위 폴더 로그는 집계에서 제외했다.
