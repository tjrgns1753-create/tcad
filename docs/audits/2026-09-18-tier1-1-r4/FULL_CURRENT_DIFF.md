# Tier 1-1 r4 -- 전체 현재 테스트 (baseline 120 + 신규)

- 총 124개 = baseline 120개 + 신규 4개
- 신규 파일: ['tests/unit/test_measurement_canonical_state_gate_mock.py', 'tests/unit/test_measurement_entry_point_gate_mock.py', 'tests/integration/test_float32_boundary_snap_real.py', 'tests/integration/test_measurement_canonical_state_gate_real.py']
- 전체: {"total": 124, "status": {"PASS": 95, "FAIL": 29}, "unit": {"PASS": 46}, "integration": {"PASS": 49, "FAIL": 29}, "failure_categories": {"API/자료형 호환 실패": 3, "assertion 불일치": 6, "예상한 도핑 profile 부재": 1, "v2 미지원 상태로 device mapping 차단": 19}}

## 기존(baseline) 실패 지속

| 테스트 | baseline | r4 | 분류 |
|---|---|---|---|
| test_gui_thermal_anneal_real.py | FAIL | FAIL | API/자료형 호환 실패 |
| test_ce2_oxidation_conversion_unsupported_real.py | FAIL | FAIL | assertion 불일치 |
| test_ce3_implant_anneal_etch_implant_real.py | FAIL | FAIL | 예상한 도핑 profile 부재 |
| test_gui_measurement_doping_kinds_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_auto_refine_from_doping_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_device_fabrication_to_dc_sweep_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_device_lifecycle_repeat_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_doping_barrier_windows_real.py | FAIL | FAIL | API/자료형 호환 실패 |
| test_doping_mapping_per_node_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_doping_mapping_recovery_real.py | FAIL | FAIL | API/자료형 호환 실패 |
| test_gaussian_implant_doping_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_gui_doping_color_overlay_real.py | FAIL | FAIL | assertion 불일치 |
| test_gui_doping_donor_acceptor_real.py | FAIL | FAIL | assertion 불일치 |
| test_gui_doping_survives_geometry_steps_real.py | FAIL | FAIL | assertion 불일치 |
| test_gui_electrode_panel_real.py | FAIL | FAIL | assertion 불일치 |
| test_implant_windows_doping_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_body_bias_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_body_contact_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_gate_stack_cv_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_id_vds_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_id_vgs_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_mosfet_vth_extraction_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_phase14_flow_devsim_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_phase7_doping_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_phase8_pn_junction_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_phase9_mos_cv_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_robust_iv_sweep_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_voltage_probe_real.py | FAIL | FAIL | v2 미지원 상태로 device mapping 차단 |
| test_wafer_state_accumulation_devsim_real.py | FAIL | FAIL | assertion 불일치 |

## baseline에 없던 신규 실패 (120개 중, r4에서 새로 실패)

| 테스트 | baseline | r4 | 분류 | 비고 |
|---|---|---|---|---|
| (없음) | | | | |

## 신규 테스트 파일 (4개, baseline 목록에 없음)

| 테스트 | 상태 | 초 |
|---|---|---:|
| test_measurement_canonical_state_gate_mock.py | PASS | 0.59 |
| test_measurement_entry_point_gate_mock.py | PASS | 0.86 |
| test_float32_boundary_snap_real.py | PASS | 3.61 |
| test_measurement_canonical_state_gate_real.py | PASS | 3.06 |
