# E6N-C: PN 감사 종료 판정과 원시 증거 재검토

## 목적과 범위

시작 SHA: `1e625da4948de63682ee9c7e6e5ec77520b598d3`.
기존 E6M의 42회 solve 결과를 재사용한다. 새로운 물리 계산은 하지 않는다.
검증 실패 또는 미평가를 프로세스 정상 종료로 전달하는 문제를 고친다.
이 작업의 성공은 PN 물리 승인이나 production gate 해제를 뜻하지 않는다.

## 수정 전 반례

현재 `test_pn_2d_1d_consistency_real.run()`은 판정을 출력한 뒤 무조건
`return 0` 한다. 기존 증거는 최신 판정기에서 역방향 canonical 감사
미기록 때문에 G2가 NOT_EVALUATED이고 G4~G9가 차단된다.
따라서 성공 종료와 미완료 검증이 동시에 존재할 수 있다.

## 구현 계약

판정기와 실제 실행 파일이 동일한 종료 함수를 쓴다.
EVIDENCE_INTEGRITY 및 G1~G9가 모두 명시적 PASS여야만 0을 반환한다.
각 G 범주에는 비어 있지 않은 checks가 필요하고 각 pass는 정확히 True다.
누락, 문자열 True, bool 대신 숫자, FAIL, NOT_EVALUATED, BLOCKED,
잘못된 구조는 모두 1이다. 범주별 판정은 그대로 보존하며 합성 물리 승인
라벨을 만들지 않는다. 원본 PLAN/JSON/NPZ와 기존 물리 임계값은 수정하지 않는다.

## 검증과 사전 고정 기준

1. 엔진 없는 AST 조사로 수정 전 return 0 경로 확인.
2. 완전한 합성 PASS 대조군만 0. G1~G9 각각의 실패/누락과 증거 무결성
   실패, 빈 checks, 위조 boolean, NOT_EVALUATED, 차단은 1.
3. 실제 보존 JSON/NPZ를 최신 판정기로 재계산. 원본 해시 전후 일치.
4. current, KCL, y spread, field, mesh sensitivity는 원시 데이터에서
   기존 metrics로 재계산하되 차단된 결과를 승인으로 승격하지 않는다.
5. 1D 환원은 y에 독립적인 입력과 절연 경계에서 정당한 물리 대조군이다.
   동일 엔진 1D-2D 일치는 독립적인 실험 또는 2D PN 물리 검증이 아니다.
6. 로컬 순수 Python/NumPy 및 GitHub Windows에서 동일 엔진 없는 검사를 한다.
   import 차단기로 DEVSIM/ViennaPS/ViennaLS 접근을 즉시 실패시킨다.
7. 원격 작업은 120초 예산. 결과·파일 해시·source SHA·원시 로그를 보존한다.

## 금지

production 물리 코드, gate, 엔진 내부, 원본 증거, 이전 PLAN 변경 없음.
새 PN solve, 전체 회귀, main 병합 없음. 없는 역방향 기록을 만들지 않는다.
