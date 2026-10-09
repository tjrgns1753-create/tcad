# E6NAB — 실패 결과의 거짓 성공 상태 방지

## 판정

`INTRINSIC_FAILURE_STATUS_AND_OPPOSITE_CONTACT_VALIDATED`.
기존 known-undoped GUI 지원 범위를 넓히거나 물리 게이트를 해제한 것이 아니다.
반대 접점의 같은 저전계 모델을 확인하고 결과가 손상되면 성공 상태도 차단했다.

## 수정 전 반례 → 실제 수정

`test_intrinsic_refusal_status_mock.py --before`가 엔진 import0으로 실제 GUI prefix를
AST 실행했다. +2mV/2um 요청이 차단됐는데도 last_physics_status는 `OLD_MODELLED`로
남았다. 수정 뒤에는 `UNSUPPORTED_BY_MODEL / INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED`.
전체 field/결과 검증 실패는 `INTRINSIC_RESULT_NOT_VALIDATED`로 기록한다.
오류 메시지를 원본 note에 유지하고 canonical wafer state를 재작성하지 않는다.

실제 production diff는 intrinsic.py의 상태 기록 helper6줄과 run_measurement의
두 오류 경로다. 새 물리 방정식/계수/숫자 fallback/activation/엔진 수정0.
기존 source 경계와 양의 시간 산화·보상·2D PN gate 유지.

## 실행과 독립 검증

- PLAN 단독 커밋 `2a7b2e3`, LF SHA `6b0d1be28bad2b658fbf2dc1623e9fa5ba8105d706391142a0fbf6f34c49ec02`.
- 실행 SHA `adb174994d72abf3f6cb9d1a1b857dac2cea7e58`.
- https://github.com/tjrgns1753-create/tcad/actions/runs/37984357015
- artifact `remote-run-77`, GitHub-hosted Windows. 로컬 실제 engine/Tk/solve0。
- 원격6하위단계(status/contract/missing/bias/baseline_gui/refusal_gui) 모두 정상 종료,
  cleanup 통과. 원격 실제 solve: 기존 GUI 대조군15 + 새 경로24 =39.
- verify_artifact.py가 입력20/원본20 해시, PLAN, 정상 전체배열, fault 이전 실제배열,
  source 전류를 엔진 없이 독립 대조했다. 기존 원본은 `raw/`에 바이트 보존.

## 반대 접점의 실제 결과

| 요청, source=min | 실제 A/cm | 해석 A/cm | 전류 상대오차 |
| --- | ---: | ---: | ---: |
| x +1mV | 2.4000000000000005e-10 | 2.4e-10 | 2.16e-16 |
| x −1mV | −2.4000000000000005e-10 | −2.4e-10 | 2.16e-16 |
| y −0.25mV | −9.600000000000002e-10 | −9.6e-10 | 2.16e-16 |

각73node, 3실제solve. 모든 node n/p=n_i, affine Potential 검증과 GUI/export 동일성
확인. source의 문자열 suffix를 물리적 위치의 근거로 쓰지 않고 실제 min/max를 전달한다.

## 실패 주입: 엔진 오류나 새로운 물리 현상으로 오인 금지

감사 스크립트에서 실제 정상 solve가 반환된 뒤 다음5손상을 의도적으로 주입했다.
전자0, 전위flat, 좌표 y+0.25um, capture예외, 양 contact current×2.
각각 실제 solver3회는 수행됐으나 잘못된 field/result/history/성공로그는 0건이다.
물리 상태도 UNSUPPORTED로 바뀌며 device/mesh는 모두 삭제된다.
주입 전 실제 API 배열과 실제 current는 별도 original_api_evidence에 보존했고,
그 정상 배열 자체는 독립 해석검증을 통과한다. 따라서 이5건을 DEVSIM 수치 오류로
집계하면 안 된다. 오직 출력 거부 장치가 작동한다는 증거다.

고전계1요청은 solver/write/capture/history0, state identity 유지.
기존 E6NAA 다섯 정상 측정/네 차단도 수정 후 다시 통과했다.
모든 유효범위·수치 tolerance는 PLAN 그대로, 느슨하게 변경하지 않았다.

## 원본 portability와 한계

root gitattributes의 기존 예외는 옛 VTU에만 적용됐으므로 이번 날짜의 E6N raw/**를
좁게 -text/-diff로 지정했다. 원본을 재포맷한 것이 아니라 checkout 변환을 차단했다.
보고서/source는 여전히 text이다. 공개 개인 경로/토큰 패턴 검사0.
코드 diff check 통과. 이전 PLAN/raw 내용·main 변경0.

전체 integration 회귀는 실행하지 않았다. PN/DD 비균일 해의 정확성, 임의 공정,
고전계까지 검증됐다고 주장하지 않는다. 다음은 현재 unit86목록을 고정한 교차 회귀다.
