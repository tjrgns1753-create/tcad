# 이번 연속 작업 인수인계: Q~Z

시작 af63e0973e008c74a6b5ab43f30b4b5392b30b48.
실제 계산은 전부 GitHub-hosted Windows, 로컬은 pure/AST/원본 재검사만.
사용자 원칙은 한국어, 임의 공정 순서, 논문/구성식에 근거한 실제 결과와 동일 GUI,
지원 불명은 UNSUPPORTED/None, 원본 불변, engine 내부 수정과 main 병합 금지다.

## 구현된 개선

- Q: node field export의 정확한 양단 접점/전압/전류 증거를 요구한다.
- R: GUI caption에 실제 region과 인가전압을 표시하며 raw Potential 기준을 구분한다.
- S: 요청 전압/region/contact와 반환 기록이 다르면 capture/history/성공 로그 이전 차단.
- V: runner의 별도 버전 조회 NOT_PROBED를 실제 자식 engine 실행 여부와 혼동하지 않는다.
- Y: CHEMICAL/UNKNOWN activation 미지원과 GUI profile 미확보를 명시하고
  '도핑이 없으면 운반자가 없다'는 물리적으로 틀린 설명을 제거했다.

production 변경은 interface.py, node_fields.py, source_context.py,
tcad_2d_stagewise.py의 boundary/표시뿐이다. 식/농도/geometry/엔진 내부는 무변경.

## 실측과 실패 보존

- T: 실제 GUI x/y 방향, 전압±/0, 접점 교환8요청의 전체 fields/API/export 일치.
  전류 방향/기하비 해석 기준33개 통과. 균일 Si 대조군이지 PN 승인이 아니다.
- U2: n/p4numeric control과 보상 도핑8refusal. 보상 시0write/solve/capture/history.
  U1은 보상 transport를 지원한다고 잘못 가정한 감사 설계 실패로 그대로 보존했고
  별도 PLAN으로 U2를 실행했다. 원래 FAIL을 PASS로 재분류하지 않았다.
- W: 고정83unit script 83PASS. 이는 4ab9da6 실행 SHA의 파일별 기준선이다.
  Y에서 신규 unit 추가 이후 전체84개를 다시 실행한 것은 아니다.
- X: 고정3integration 2PASS/1FAIL. canonical ACTIVE 누적과 실제 공정 모달 검증 PASS.
  donor/acceptor의 보상 측정 성공 assertion은 현재 계약과 충돌해 FAIL, 후속 부분 미도달.
- Y: 상태 안내 수정 관련 고정3검증 모두 PASS. 실제 ACTIVE/anneal 경로는 유지됨.
- Z: known-undoped Si 공식 API9solve/56checks PASS. GUI 연결은 아직 구현하지 않았다.

각 폴더 REPORT/원격 run/immutable raw와 독립 verify_artifact를 보존했다.
숫자 합산으로 진척률이나 전체 물리 타당성 점수를 만들지 않는다.

## 다음 구현 우선순위

1. Z 결과를 기반으로 known-undoped canonical input을 GUI 측정 경로에 연결한다.
   None/CHEMICAL/UNKNOWN/UNRESOLVED를0으로 대체하지 않고 초기 geometry를
   자동 재생성해 불확실 상태를 회복시키지 않는다. 무도핑을 가짜 dopant attachment로
   바꾸지 않는다. 전체 node/current 해석 대조 후 같은 결과만 렌더·export한다.
2. X의 오래된 donor/acceptor integration을 목적별로 분리 migration한다.
   단일 polarity supported stale reattachment, 보상 transport refusal,
   GUI implant CHEMICAL 원본 입력 보존, barrier canonical-state 계약을 각각 확인한다.
   과거 '산화로 oxide 제작'과 '전체 기존 dopant를 oxide 아래0으로 제거'를 정답으로 유지하지 않는다.
   미도달 barrier 부분을 통과로 집계하거나 삭제하고 전체 coverage라 부르지 않는다.
3. 2D PN 지원은 독립 mesh/current 수렴·물리 대조를 추가하기 전 gate를 유지한다.
   양의 시간 산화와 보상 transport의 미지원도 그대로다.

원격 request는 Z capability이며 docs-only push는 추가 solve를 시작하지 않는다.
미커밋 과거 untracked 증거·.serena·remote-out은 사용자 자산으로 보존한다.
