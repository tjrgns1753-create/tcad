# E6NY 측정 입력 누락과 활성화 미지원 상태 구분

E6NX 원본 B0에서 CHEMICAL attachment는 존재하지만 run_measurement 초기 분기는
last_doped_result None만 보고 no doping profile/no carriers로 안내했다.
활성 도펀트 부재는 열적 운반자 부재와 같지 않다. 공식 엔진의 n_i를 변경하거나
intrinsic solve를 새로 허용하지 않는다. 이 GUI가 검증된 device input을 갖지 못한
상황과 CHEMICAL/UNKNOWN의 미지원 활성화를 구분해서 표시한다.

수정은 source_context의 engine-free 상태 생성 helper와 run_measurement의
last_doped_result None 분기에 한정한다. 실제 농도/상태/이력/식/mesh/gate 무변경.
CHEMICAL/UNKNOWN attachment가 있으면 DOPANT_ACTIVATION_MODEL_MISSING,
그 밖에는 DEVICE_PROFILE_NOT_AVAILABLE, resolution UNSUPPORTED_BY_MODEL로 기록한다.
둘 다 write/solve/capture/history0, 이전 field cache 제거, 운반자0이라는 주장 금지.
상태가 있고도 무도핑이라고 오인하거나 ACTIVE가 없어졌다고 주장하지 않는다.

## 반례와 검증

수정 전 실제 GUI 메서드의 초기 분기를 AST로 추출해 CHEMICAL state에서
status 부재와 잘못된 문구를 재현한다. 엔진 없는 대조군은 None/empty,
CHEMICAL/UNKNOWN/mixed/ACTIVE-only 기록을 검사한다.
원격은 같은 canonical-state integration을 한 번 재실행해 B0 차단 사유를
강화 assert하고 B1 누적/anneal refusal/B2 지원 경로가 그대로 유지되는지 확인한다.
기존 headless/모든 unit/PN 계산은 다시 실행하지 않는다.
최종 report는 상태 안내 개선이지 activation physics 구현이 아니라고 명시한다.
