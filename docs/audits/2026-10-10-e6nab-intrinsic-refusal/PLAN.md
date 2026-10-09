# E6NAB intrinsic GUI 실패 상태와 반대 접점 검증

E6NAA의 실제5측정/4거부는 유지한다. 새로운 물리/방정식/허용오차를 만들지 않는다.
지원경계 밖 입력 또는 전체 field/해석 검증 실패 시 화면의 physics_status가 이전
MODELLED 상태로 남는 정적 반례를 먼저 재현하고 UNSUPPORTED_BY_MODEL로 기록한다.
이 결과 거부는 기존 canonical wafer state의 물리 상태를 재작성하는 동작이 아니다.

원격 실제 경로:
- 동일한2×0.5um known-undoped 직사각형, x min +1mV/−1mV, y min −0.25mV.
- full-node/API/GUI/export 및 해석전류를 E6NAA와 동일한 한계로 비교한다.
- 실제 solver가 정상 반환한 뒤 전자0/전위flat/좌표불일치/capture예외/전류배율2를
  감사 스크립트에서 의도적으로 주입한다. 이5반례는 엔진 오류/새 물리 실측이 아닌
  실패 처리 fault injection이다. 각3실제solve와 이후 numeric-result/history/field0,
  UNSUPPORTED reason, device cleanup을 확인한다. 실제 원본 배열은 fault와 구분한다.
- 고전계 preflight는 solve/write/capture/history0이며 구체적인 unsupported status를 기록한다.
- 엔진 없는 prefix 반례, 기존 intrinsic unit, 기존 missing/bias unit을 대조한다.
- 계산은 원격에서만1회. PLAN은 실행 전 해시 고정. 로컬은 순수 산술/AST만.

원본 감사 raw의 바이트를 checkout에도 보존하도록 gitattributes 범위를 이 날짜의
새 감사 raw로 좁혀 적용하고 저장소 blob와 원본 SHA를 대조한다.
기존 raw/PLAN 내용, main, 산화/activation/보상/PN gate, 엔진 내부는 수정하지 않는다.
추가 전체 회귀는 이번 batch 범위가 아니다.
