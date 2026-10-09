# E6NAC — intrinsic GUI 구현 뒤 unit 전체 회귀

## 결과

`86 PASS / 0 FAIL / 0 TIMEOUT / 0 ERROR`, 파일 삭제0/skip0.
부모 러너 실행141.984초. 고정된86개 각각 독립 subprocess에서1회 실행했다.
이 결과는 unit 계약 회귀이며, 모든 TCAD 물리와 integration 검증 통과라는 뜻이 아니다.

## 고정 출처와 원본

- PLAN/MANIFEST 별도 커밋: `96ebb08`.
- PLAN LF SHA `3bd331af97e578bc287975697954f2eeec7661a5105a267a449c906f4ede9b12`.
- MANIFEST LF SHA `c26e843f24e02471eec7393269585c4fd6b9fd101a818eb60ac73645803baa79`.
- 실행 SHA `7940b1363101fdf3b79da8d3ab0844d2ff948d38`.
- https://github.com/tjrgns1753-create/tcad/actions/runs/37984855464
- artifact `remote-run-78`. 원본은 raw/summary.json, raw/run.log,
  raw/outputs/e6nac_out/{파일별86로그,records.json,verdict.json}.
- 실제 테스트는 GitHub-hosted Windows에서만 실행했다. 로컬은 순수 manifest/원본
  대조만 했고 독립 검증기 엔진/Tk import0.

## 독립 검증과 파일별 이전 기준선 비교

verify_artifact.py가 입력11개, unit86개의 LF SHA와 정확한집합, 원본89개 SHA,
모든 종료코드/cleanup 및 records→verdict를 다시 계산했다. 생략된 output0.
이전 W의 원본83개 기록과 비교한 결과:

- 공통83개: 모두 PASS→PASS. FAIL로 바뀐파일0.
- 삭제0, 공통unit 자체의 SHA변경0.
- 새3개는 모두 PASS: missing_profile_physics_status, intrinsic_measurement_contract,
  intrinsic_refusal_status.

이는 이 두 실행 사이의 unit 상태 변화이며, 과거95/29 또는83/46 전체 integration
기준선과 혼동하지 않는다. 기존 실패 integration donor/acceptor의 낡은 기대는 여전히
별도 과제로 남는다. 이번에는 그 파일을 수정하거나 실행하지 않았다.

## 구현 과정의 정정

기존83개 runner를 복사할 때 count의 문자열 치환이 기존 manifest hash의83부분도
바꾼 것을 정적검사에서 발견했다. 올바른 새 MANIFEST SHA로 고쳤고 로컬 preflight가
정확히86개를 통과한 뒤 처음 원격 실행했다. 잘못된 해시로 원격 계산하지 않았다.
테스트 내용·물리 코드·gate는 이번 회귀 배치에서 변경0이다.

## 현재 사용자가 얻는 결과

E6NAA/E6NAB에서 정확히 알려진 무도핑 virgin Si의 저전계 실제 GUI 측정이 추가됐다.
열적 전자·정공을0으로 만들지 않고, 공식 DEVSIM 전체노드와 terminal current를
해석 기준으로 확인한 다음 동일한 노드/단위로 화면과 JSON을 제공한다.
손상 결과5반례와 지원 전계 밖은 숫자를 정상 결과로 내보내지 않는다.
기존 n/p 균일 저항, compensated/activation/공정 unknown 차단 원칙도 유지한다.

원본 Git 줄바꿈 정정은 E6NAA/ERRATUM_RAW_PORTABILITY.md에 별도로 기록했다.
임의 공정·양의 시간 산화·2D PN의 물리적 정확성까지 승인하지 않는다.
main/엔진 내부 변경0. 이후 작업은 남은 integration 계약을 물리 검증과 구분하여
정리하고, 비균일 실제2D PN의 수렴/전류 기준을 기존 게이트 아래서 조사하는 것이다.
