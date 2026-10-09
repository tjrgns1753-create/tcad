# E6N-W: 공통 측정 변경 후 단위 테스트83개 교차 회귀 결과

**83 PASS / 0 FAIL / 0 TIMEOUT / 0 ERROR**, 누락0.
이 숫자는 unit script의 계약 검사 결과이지 실제 TCAD 물리검증 점수가 아니다.
실제 균일 저항의 물리 결과는 T/U2 보고서에서 따로 판정한다.

일부 diffusion/anneal unit 로그의 Resolution.VERIFIED는 해당 계수·1D helper의
테스트 표기이며 현재 2D 공정→상태→측정 기능의 승인이 아니다. 현재 GUI anneal과
양의 시간 산화의 fail-closed 계약을 이 로그로 해제하지 않는다.

## 실행과 사전 목록

- 시작 HEAD a892ac05df5680512baabb14d6601279c504e918.
- PLAN/MANIFEST 단독 커밋 b688369, 실행 SHA 4ab9da6cc4bba7d57fcfb5991192563d3131f019.
- [원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37978922405), artifact remote-run-72.
- 2026-10-09 19:15:50.564304–19:18:11.007164 UTC, parent140.443초.
- GitHub-hosted Windows, Python3.11.9. 정확히1회 실행했다.
- tracked tests/unit/test_*.py 83개의 파일명과 LF SHA를 결과 전에 고정했다.
- parent preflight가 PLAN/manifest hash, 정확한83개 파일 집합과 각 입력 SHA를
  대조한 뒤 child를 시작했다. 로컬 read-only preflight도83개 일치, child 실행0.
- 파일별60초/parent900초 예산. 실제83개 모두 정상 반환하고 process-tree cleanup=true.
- 가장 오래 걸린 unit은 structured remesh26.547초, conformity21.032초,
  E6M judge18.031초, PN judge integrity16.531초로 모두 사전60초 예산 안이었다.

## 수집·재검사

각 파일의 stdout/stderr log, 종료 코드, duration, sampled process-tree memory,
cleanup, 입력 LF SHA, log SHA를 원본 records.json에 남겼다.
파일 완료마다 records를 저장했으며 실패/timeout을 통과로 치환하지 않았다.
모든83개 로그와 verdict/records/parent log는 `raw/`에 바이트 그대로 보존한다.

독립 `verify_artifact.py raw`에서:
- 실행 SHA/run 및 GitHub-hosted 출처 일치.
- summary 입력9개 git blob/checkout 해시 일치.
- manifest83개 입력 git blob의 LF SHA와 실제 기록의 입력 SHA 일치.
- 원본86개 파일의 크기·SHA 및 개별 log SHA 일치.
- 파일별 status/rc/cleanup으로 집계를 다시 계산해 전체 verdict equality 확인.
- 결과 evidence_integrity_pass=true, suite_pass=true, PASS83/FAIL0/TIMEOUT0/ERROR0.
- 독립 재검사에서는 엔진/Tk import를 audit hook으로 금지했다.

처음 workspace cwd에서 재검사할 때 Git의 소유권 안전 확인으로 읽기가 막혔다.
전역 설정을 변경하지 않고 검증 스크립트의 git show에 알려진 해당 저장소 경로만
명령별 safe.directory로 지정했다. 그 뒤 다른 cwd에서도 전체 대조를 완료했다.
이는 로컬 원본 읽기 환경 문제였고 원격 unit FAIL이나 코드 assertion 실패가 아니다.

## 범위와 변경

integration 디렉터리, 오래 걸리는 기존 PN 감사42 solve, 전체 regression을 실행하지
않았다. unit 내부의 엔진 사용을 부모 version probe 기록으로 추론하지 않는다.
summary NOT_PROBED/scope는 별도 버전 조회의 범위만 뜻한다.
이번83개는 mock/합성/AST 등의 계약 검증이며 새 PN/산화 물리 승인 근거가 아니다.

기존 단위 테스트 assertion은0건 수정했다. 새 감사 parent/manifest/verifier/profile만
추가했다. production 식·engine 내부·gate·기존 raw/PLAN·main 무변경.
동일83개 suite의 이전 파일별 baseline이 없어서 NEW_REGRESSION=0을 주장하지 않는다.
이번 실행 SHA에 연결된 파일별 원본을 다음 변경의 비교 기준으로 사용할 수 있다.
