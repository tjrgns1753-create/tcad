# E6N-I: 깊이를 포함한 canonical 도핑 표시

시작 SHA: af3fafad03c3b370dab5cfe843f7b36a66bce4ab.

## 물리적 질문 및 범위

현재 y=0 도핑을 모든 깊이에 칠하는 표시와 x-only hover는 2D 물리 상태와 대응되지 않는다.
실제 mesh와 현재 WaferStateV2의 같은 (x,y) 좌표를 읽는다. 새 주입/확산/활성화 모델,
엔진 방정식, gate, 정확 inventory 적분은 변경하지 않는다. 문헌의 전기적 net doping
N_D(active)-N_A(active) 정의를 기존 canonical query 그대로 사용하며 화학 농도를 승격하지 않는다.

## 변경 전 반례와 사전 기준

- Si y=[-2,0], donor 1e17 전체 + acceptor 2e17 y=[-2,-1]: 상부 n, 하부 p.
- 현재 x-only overlay는 두 깊이를 모두 n으로 표시한다. 실제 y별 canonical 값과 대조한다.
- CHEMICAL/UNKNOWN 또는 geometry 미상은 unknown, 지원 무도핑은 정확한 0과 구분한다.
- 실제 canvas 삼각형을 canonical 조회 위치(삼각형 중심)의 부호로 표시하며 전체 셀에
  일정한 농도를 증명했다고 주장하지 않는다. legend에 중심 표본 및 농도 크기 미표시를 명시한다.
- 실제 material tag와 canonical material이 다르거나 소유 cell이 유일하지 않으면 unknown.
- 과거 mesh는 현재 도핑을 덧씌우지 않고 해당 시점 도핑 미보존 안내를 표시한다.
- 삼각형 2000개 초과 시 부분 sampled fill로 전영역처럼 보이지 않도록 도핑 채색을 생략하고
  자원 상한 안내를 표시한다. 실제 재료 형상은 유지하고 공정 버튼/solver gate는 변경하지 않는다.
- hover는 마우스 실제 y를 사용하고 실패/미상을 0으로 바꾸지 않는다.
- 실제 Tk/ViennaPS 및 기존 DEVSIM 대조군은 원격 Windows에서만 수행한다.
- 로컬은 AST/pure canonical/정적 검사만. 전체 회귀/PN 신규 solve/산화 solve/main 병합 없음.

## 영향 조사

Serena 도구가 세션에 없어 rg/직접 읽기 사용. `_draw_real_mesh_result`의 단일 production
caller는 redraw. `_doping_color_segments`는 기존 renderer와 legacy integration test가 사용했다.
legacy helper는 호환용으로 보존하고 production overlay만 2D 조회로 교체한다.
`_on_canvas_motion`이 hover의 단일 production caller이며 마우스 y 전달을 추가한다.
구형 hover 테스트의 직접 x 호출은 기본 y=0으로 유지한다. 과거 `surface_profile` helper는
다른 guide/테스트 계약 때문에 삭제하지 않는다.

## 구현 중 반례에 따른 한정 보완

합성 raw 농도 NaN 반례에서 `max(0.0, NaN)`이 0으로 처리되는 canonical 결함이 확인됐다.
이전의 canonical 무변경 범위에 대한 예외로, 농도 값 유효성 검사만 추가한다.
비유한값 및 음수 도펀트 농도는 세 concentration=None + UNSUPPORTED_BY_MODEL로 반환한다.
수식/분포/적분/활성화/gate 조건은 변경하지 않는다. 원격 actual GUI/DevSim 대조에서
NaN/inf/음수 각각 0 doping writes, 0 solves 및 해당 원인 note를 요구한다.
이미 시작된 첫 원격 run은 취소·은폐하지 않고 실패 결과를 보존한다.
