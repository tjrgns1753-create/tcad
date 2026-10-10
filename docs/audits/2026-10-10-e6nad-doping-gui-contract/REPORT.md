# E6N-AD 완료: donor/acceptor GUI 계약 migration

## 판정
GUI_DOPING_CONTRACT_MIGRATION_PASS. production 물리 코드/게이트 변경 0.
기존 X의 실패 원본은 보존했고, 이번에는 실제 GUI 7시나리오 전부 도달했다.
모든 임의 공정/도핑의 물리 정확성이나 일반 PN/산화를 승인한 결과가 아니다.

## 시작과 실행
시작 HEAD e1c0c025d955540251e00a8f295db836044e61f7, 원격 일치, tracked diff 0.
기존 사용자 untracked 파일은 그대로 보존했다.
Serena 도구는 세션에 없어 직접 소스 읽기/rg로 대체했다.
초기 sandbox/Node 실행 초기화 실패와 GitHub connector 쓰기403은 변경을 남기지 않았다.
이후 승인된 외부 실행으로 로컬 편집/정적 검사/독립 읽기가 복구됐다.
로컬 실제 엔진 import/solve 0. 물리 계산은 GitHub-hosted Windows만 사용했다.

PLAN 단독 commit 07e5481, LF SHA e56c4eb99142e01a2aea347bc2cb0ed98961c913f2059531f2e3994cf8e5b935.
구현/실행 SHA 586b6f9f4da4f80f456cde1b65431558af8686e0.
run https://github.com/tjrgns1753-create/tcad/actions/runs/38053242103
artifact remote-run-79, 실제 profile 24.869초. targeted 4파일 모두 PASS/0 SKIP/0 timeout.
수정 대상 script 8.516초, 기존 canonical control 4초, headless control 10.531초,
staleness unit control 1.5초. runner sampled memory는 순간 최고치의 증명이 아니다.

## 실제 결과
| 시나리오 | 실제 solve | doping writes | 결과 |
|---|---:|---:|---|
| 순수 n형, ND1e16 | 3 | >0 | source +0.0016, ground -0.0016 A/cm |
| 순수 p형, NA5e15 | 3 | >0 | source +0.0004, ground -0.0004 A/cm |
| ND1e16/NA5e15 보상 | 0 | 0 | COMPENSATED_TRANSPORT_MODEL_MISSING |
| Gaussian GUI implant | 0 | 0 | DOPANT_ACTIVATION_MODEL_MISSING |
| Windows GUI implant | 0 | 0 | DOPANT_ACTIVATION_MODEL_MISSING |
| actual etch 후 barrier, contact x | 0 | 0 | unresolved 상태 차단 |
| 같은 입력, contact y | 0 | 0 | unresolved 상태 차단 |

정상 두 경우의 NetDoping은 공식 API와 canonical 전체노드 query exact equality.
재-export한 다른 mesh 경로에서 stale-cache를 만들고 reattach했으나 state object,
attachment id/count/inventory/event count가 변하지 않았다. 모달 8종 호출0.
이 테스트의 정상 solve 6회를 전체 profile solve 횟수라고 축소하지 않는다.
대조군도 실제 solve를 수행하나 이번 report의 GUI7 표는 migrated script만 다룬다.

Gaussian 원래 donor/acceptor peak2e17/3e16, P/B 및 window background1e14/1e17,
source1e20/0, drain9e19/1e19 원시 입력 필드 검증을 그대로 유지했다.
실제 GUI helper를 pass-through 관찰했으며 CHEMICAL 생성만 허용하고 ACTIVE 승격,
성공 history/last_doped_result/viewer 갱신 및 측정 숫자는 차단했다.

## barrier 및 문헌/API 대응
공식 MakePlane을 이용하는 기존 DIRECT_EXPLICIT_GEOMETRY helper에서 SiO2 입력을 만들었다.
이는 산화/증착의 산출물이 아니다. 실제 isotropic selective etch를 수행했고 native Si 불변,
Oxidation 호출0, Process 호출>0을 확인했다. detector의 x0 uncovered/x-4 covered만 보증한다.
도핑 attach 시 실제 detector는 measurement x/y 양쪽에서 고정 x방향을 사용한다.
실제 curved etch의 exact transform이 없어 canonical은 unresolved. NetDoping을0으로
덮어쓰거나 원래 도펀트를 지우는 옛 기대를 제거하고, 미지원 상태 차단을 확인했다.
보상 반도체가 물리적으로 불가능하다는 뜻이 아니라 프로젝트 transport 지원이 미검증이다.

공식 모델:
https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py
기존 ohmic contacts/Poisson/DD를 재사용했다. 새 전류식/활성화식/엔진 내부 변경은 없다.
구성방정식/저전계 분석 입력에 대한 이전 감사와 대응하며 실제 제작 소자 재현은 주장하지 않는다.

## 독립 검증
verify_artifact.py가 input13/output7/run.log의 SHA/크기/실행SHA/run ID/PLAN을 대조했다.
GUI 원본 log의 METRICS와 별도 JSON이 완전히 같고, 7시나리오·4파일을 재검사했다.
9반례(시나리오 누락, 차단 solve, canonical mismatch, duplicate reattach,
CHEMICAL ACTIVE, species/window 변조, detector axis, stale current)를 모두 차단했다.
독립 검사 engine import0/new solve0. 성공 결과는 원본 raw 아래 바이트 그대로 보존한다.

독립 verifier 초판에서 전류 로그를2개로 가정해 FAIL했다.
원본에는 결과 섹션과 log-only 안내에 같은2접점이 반복돼 총4값이었다.
4값의 동일 반복까지 검사하도록 정정했다. 또한 canonical zero window 항은 생략되지만
GUI 원시0 입력 검증은 유지한다. 물리 입력/threshold/원격 결과를 바꾸거나 재실행하지 않았다.

## 범위와 남은 일
변경: 대상 integration1, runner profile/request, 새 감사 PLAN/runner/verifier/report/원본.
production tcad/와 tcad_2d_stagewise.py는 시작 SHA와 blob/diff가 동일하다.
semantic diff 전체는 IMPLEMENTATION.patch. 다른 controls는 원본 그대로다.
전체 회귀/main 병합/게이트 해제 없음. 기존 unit86 baseline은 별도 AC 기록이다.

추가 발견: detector는 protected 쪽에서 [-5,-4.80000019],
[-4.69999981,-4.29999971],[-4.19999981,-1.79999924] 같은 분할을 반환했다.
보호 지점 한 곳 통과를 전체 막 검출의 정확성으로 주장하지 않는다.
다음은 이 틈이 실제 geometry/export representation인지 detector sampling 문제인지
공식 native surface와 triangle-column 교차로 분리하는 읽기 전용 capability 조사다.
숫자 doping 복구/새 모델/threshold 완화는 하지 않는다.
