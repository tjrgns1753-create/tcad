# E6N-S: 요청 바이어스와 반환 측정 기록의 일치

시작 HEAD 79daa22. 현재 run_measurement는 유한·수렴·두 접점 존재만 검사한 뒤
반환 기록과 무관하게 요청 voltage로 로그를 붙인다. source/ground 바이어스가
다른 기록이나 다른 region/sweep_contact도 terminal 숫자로 승인될 수 있다.

## 사전 기준

- 기존 실제 GUI 검증 구문을 AST로 추출해 엔진 없이 잘못된 바이어스 기록이
  차단되지 않음을 재현한다. 이는 합성 반례이며 engine 오계산 주장이 아니다.
- 반환 region, sweep_contact가 현재 요청과 일치하고, 모든 두 접점 전압 및
  전류 집합이 실제 import한 접점 집합과 같아야 한다.
- source 전압은 요청 voltage, ground는 요청 0.0와 기록상 정확히 같아야 한다.
  이것은 solver Potential의 정확 비교가 아니라 Python의 command metadata
  비교다. 공식 두 sweep producer 모두 요청 값을 그대로 BiasPoint에 기록한다.
  물리 허용오차·PN 수렴 gate·전위 기준은 변경하지 않는다.
- 공통 validate_bias_point에 선택적 expected_voltages 검사만 추가한다.
  인자를 생략하는 다단자 DC/capacitance caller는 기존 동작을 유지한다.
- 불일치는 field capture보다 앞에서 오류로 거부한다. 성공 로그·history·필드
  및 export 가능한 결과를 만들지 않고 device와 mesh는 finally 정리한다.
- 정상 음수/0 바이어스와 음수/0 전류는 허용하고 임의 접점 이름을 고정하지 않는다.

## 실행·검증

로컬은 순수 Python/AST, 엔진·Tk import 금지. 원격 GitHub-hosted Windows에서
기존 uniform ACTIVE Si, +1mV, 73 노드를 사용한다.
정상 1회 및 원래 성공한 solve 이후 wrong_source_voltage/wrong_ground_voltage
두 통제된 기록 변조를 각각 1회 수행한다. 각 3 solve, 총 9 solve 예산.
변조 케이스는 실제 library가 잘못 반환한 사례가 아니라 방어 검증이다.
두 케이스 모두 성공 로그·field 없음, capture callback 0회, cleanup을 확인한다.
정상 결과 전체 배열·단위·출처는 R/Q 고정 증거와 비교한다.
기존 validity·caption·접점·export·hover·field·readout 국소 unit을 함께 실행한다.
전체 회귀·새 PN sweep·원격 기존 증거 재생성·main 변경·gate 해제는 하지 않는다.
profile 400초, 자식 30~120초, 산출물 8MB.
