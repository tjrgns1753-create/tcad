# E6NX 실제 GUI·canonical 상태 통합 회귀

## 사전 고정 범위

시작 HEAD a8a97e98ff76ba55a39b1be0bed3bd4cf771b0fe.
기존 unit 83개는 모두 통과했으나 실제 공정·GUI·측정 경로의 통과를 뜻하지 않는다.
다음 기존 테스트 세 개만 assertion과 입력을 수정하지 않고 각 한 번 실행한다.

1. test_measurement_canonical_state_gate_real.py: CHEMICAL 차단, 명시적 ACTIVE 누적,
   anneal 후 unresolved 차단, uniform 대조군과 실제 NetDoping 비교.
2. test_gui_headless_no_modal_hang_real.py: 실제 worker, zero-time materialization/identity,
   Bosch 식각, SiO2 증착, 산화 refusal와 validation failure, 모달 차단.
3. test_gui_doping_donor_acceptor_real.py: 오래된 GUI donor/acceptor·재부착·barrier
   통합 계약을 현재 경로에서 그대로 실행하는 진단. 보상 도핑 후 숫자 측정을 기대하는
   과거 assertion은 현재 transport gate와 충돌할 수 있다. 실패를 자동 수정하거나
   예상된 PASS로 치환하지 않는다. 실제 첫 실패와 도달 범위를 보고한다.

## 위치·예산·판정

ViennaPS/DEVSIM/Tk 실제 실행은 GitHub-hosted Windows에 한정한다.
각 script 180초, 부모 profile 650초, 순차 실행하고 매 결과를 즉시 보존한다.
기존 resource_supervisor만 사용하고 cleanup_ok를 요구한다.
rc=0이어도 SKIPPED/SKIP 문구가 있으면 SKIP으로 기록하고 전체 통과를 금지한다.
실패해도 나머지 독립 script는 실행하되 동일 script를 재시도하지 않는다.
명시된 세 파일 LF SHA를 manifest에 고정하고 callback 시작 전에 대조한다.
기존 원본·모델·gate·기존 assertion·main은 수정하지 않는다.

전체 PASS는 세 통합 계약이 실행됐음을 뜻할 뿐 PN/공정 물리 전체 승인이 아니다.
실패는 원시 로그와 현재 코드로 분류하며 이전 baseline이 없는 항목의 회귀 귀속을
단정하지 않는다. 첫 실패가 물리적으로 잘못된 숫자 허용을 가리키면 별도 반례부터
수정하고, 단순 오래된 assertion이면 원래 목적을 보존한 migration 설계를 먼저 남긴다.

## 산출물

파일별 로그·rc·시간·cleanup·입력/로그 SHA, records와 verdict, 원격 summary.
다운로드 후 원본 SHA, 실행 SHA, manifest 입력을 엔진 없는 독립 검사로 대조한다.
기존 PN 감사 계산, 전체 regression, 공정 모델 추가, gate 해제를 하지 않는다.
