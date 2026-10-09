# 이번 자율 진행의 검증 인수인계

모든 사용자 설명은 한국어. 로컬은 소스/AST/합성/원본 읽기, 실제 공정·DEVSIM·Tk는
GitHub-hosted Windows. 작업 브랜치는 claude/remote-runner, main 변경 금지.
API를 연결하고 검증하는 프로젝트이며 엔진 내부/새 임의 계수/숫자 fallback은 금지한다.

## 실제 완료된 연결

- Q/R: contact/bias/원시 Potential과 같은 snapshot 증거. 접점전압과 물리전위는
  같은 값이 아닐 수 있고 화면이 raw Potential을 다시0으로 shift하지 않는다.
- S: 반환 전압·region·source/contact identity가 요청과 다르면 capture/history 차단.
- T: 실제 GUI x/y ±/0와 source 위치8요청, 전류의 width/length 비례 및 전체노드
  API→화면→JSON 동일성. 실행37974877904.
- U2: n/p 단독4측정, compensated8요청 차단. compensation을 net만으로 축약하지 않음.
  최초 U1 audit의 잘못된 지원 가정은 raw_initial/ERRATUM으로 보존. 실행37977642901.
- V: runner engine NOT_PROBED를 실제 child 미실행과 혼동하지 않도록 scope metadata 수정.
- W: 당시83 unit 모두 통과. 현재 기준선은 아래 AC로 구분.
- X: 실제3integration 원본2PASS/1FAIL. compensated 결과를 기대한 기존 donor/acceptor
  실패는 그대로 보존하며 뒤쪽 미도달 시나리오를 통과로 집계하지 않는다.
- Y: CHEMICAL/UNKNOWN 및 missing profile 거부가 정확한 physics_status/설명을 남기도록 수정.
- Z: known-undoped 공식 API pilot, n=p=n_i 및 해석 전류. 실행37981805856.
- AA: pristine GUI→실제 입력 구성→known-undoped5측정,4차단. 실행37983547425,
  report docs/audits/2026-10-10-e6naa-intrinsic-gui/REPORT.md.
- AB: 이전 성공상태 잔존 반례 수정. 반대 source3정상 측정과 손상 결과5fault injection,
  고전계1차단. 기존 AA대조군 재통과. 실행37984357015.
- AC: 현재86unit 파일별 고정/SHA검증/1회 실행,86PASS/실패0. 실행37984855464.

모든 최신 run은 종료했다. 원본 및 독립검증기는 해당 audit/raw와 verify_artifact.py.
AA raw의2JSON이 Git 정규화됐던 사실은 정정 기록과89e67b9에서 복원했고 AA/AB
전체36원본이 artifact/Git blob/local byte 모두 같음을 확인했다. 재실측으로 은폐하지 않았다.

## 지원 범위와 남은 일

known-undoped 지원은 initial_geometry의 단일 ACTIVE MODELLED Si rectangle,
attachment0/ledger0, 상수 이동도, <=5 V/cm다. fresh GUI부터 직접 측정 가능하되
불명/처리후 state를 reset으로 복구한 척하지 않는다. 숫자에 full-field/runtime guard가 있다.
그림의 물리적 타당성은 이 검증 범위 안에서만 설명한다.

양의 시간 산화, activation/anneal, compensated transport, 2D step junction 및
임의 공정의 geometry 변환 uncertainty는 아직 기존 gate 아래에 있다.
단순 단위 테스트 통과나 Newton 수렴으로 이 게이트를 해제하지 않는다.

다음 우선순위:
1. X에서 발견한 오래된 donor/acceptor integration의 계약을 migration 설계한다.
   compensated 거부와 지원 n/p stale-cache 대조군을 분리하고 Gaussian/window/
   oxide barrier의 미도달 coverage를 복구한다. 단지 assertion 삭제로 PASS 만들지 않는다.
2. 기존2D PN gate 원인의 실제 mesh/공식 가중치/국소 전류/1D 이산 환원을 분리하여
   사전 고정한 기준으로 조사한다. 이전 equilibrium 항등식을 독립 검증으로 세지 않는다.
3. 산화 지원은 bare Si seed의 무상 물질생성 문제를 해결하지 않은 상태에서 켜지 않는다.
   explicit 입력 geometry를 fabrication physics의 증거로 쓰지 않는다.

현재 AC는 unit 전체 회귀이지 integration 전체 결과가 아니다. 과거83/46,95/29를
최신 baseline으로 인용하지 말고 원본 파일별 결과와 실행 SHA를 구분한다.
