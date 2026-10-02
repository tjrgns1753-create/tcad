# E6N PLAN 초안 — E6G 전이 템플릿 PN 일치성
상태: 검토용 초안. 이번 배치에서 mesh 생성·엔진 import·solve를 실행하지 않는다.
원본 E6M PLAN과 tolerance는 바꾸지 않는다. 다음 실행 전 이 초안을 승인·고정해야 한다.

## 1. 물리 문제와 기준
E6M과 같은 단일 Si, x=[−20,+20]µm, y=[−0.1,0]µm,
N_A=N_D=1e17 cm⁻³ ACTIVE, x=0 급격 접합, 300K.
x≤0 acceptor, x≥0 donor이므로 x=0에서는 양쪽 농도를 갖고 net=0이다.
q, ε, n_i, 이동도, SRH 수명 및 이온화·통계 모델은 E6M/E6K와 정확히 같게 유지한다.
양쪽 전체 높이 ohmic contact, 위·아래 무접점 경계도 같다.
입력은 명시적 검증 geometry이며 공정 제작 및 일반 2D 소자 검증을 주장하지 않는다.

## 2. 기존 빌더의 실제 호출·조건
`tcad/device/devsim/mesh_refine.py:structured_lateral_refine(points, triangles, tags, centers, half_widths, cap=400000)`.
`structured_grid_of`가 단일 재료·축 정렬·평면 full tensor-product node set 및 셀별 정확히 두 삼각형을 검증한다.
`_strip_depths`는 x strip을 이진 세분하고 이웃 깊이 차이를 최대 1로 맞춘다.
rows도 strip 깊이에 따라 세분하며 서로 다른 row 해상도가 만나는 곳에 전이 template을 둔다.
한쪽 전이 template은 실제 float 좌표를 Fraction으로 검사해 width≥sub-row-height/2이어야 한다.
조건 위반은 TRANSITION_ASPECT, 자원 초과는 RESOURCE_CAP로 중단한다.
새 remesher·node 임의 이동·signed override·기존 실패 graded 경로 fallback을 추가하지 않는다.
production caller와 지원 범위는 E6G 그대로 유지한다.

## 3. 세 등급·전이 폭·자원 예산
후보 N0/N1/N2는 E6K L0/L1/L2의 저장 x 좌표와 E6M의 세 y line을 초기 입력으로 사용한다.
같은 요청 centers=[0.0], half_widths=[0.1]µm을 빌더에 전달하는 단일 ring 후보로 시작한다.
전이는 접합 양쪽 약 ±0.1µm에서 실제 원래 셀 경계를 따라 생기므로 정확 위치는 생성 보고서로 기록한다.
요청 경계와 실제 template support를 구분한다. 사후 PN 결과에 맞춰 폭을 바꾸지 않는다.
현재 E6M near-junction 비등방성 때문에 TRANSITION_ASPECT가 날 가능성이 있다.
세 후보의 기하 preflight가 통과하기 전에는 실행 가능·비용 확정이라고 주장하지 않는다.
삼각형 상한 각 400000, 세 등급 합계 1200000; 최대 한 device만 메모리에 유지한다.
원격 실행 시간 상한 1800초, 원시 결과 상한 200MB. 초과 시 생략 후 PASS로 처리하지 말고 중단한다.
지원 불가면 사유·셀 좌표·width·height·계획 요소 수를 제출하고 재설계 승인을 요청한다.
이번 초안에서 새 y 격자나 폭을 자동 선택하는 튜닝은 허용하지 않는다.

## 4. 1D 환원 여부를 먼저 검증
연속 물리 문제의 해는 여전히 y에 균일하다. 바뀌는 것은 그 해를 근사하는 이산 topology다.
대각 edge 존재 자체는 1D 환원이 깨졌다는 증거가 아니다.
전이 strip의 서로 다른 y-row 연결, 비균일 edge-length, EdgeCouple/EdgeLength 조립 계수,
NodeVolume을 실제로 저장하고 E6M의 반복 row stencil과 어떻게 달라지는지 비교한다.
같은 x에서 y가 다른 interior node를 대응해 x만의 함수에 대한 Poisson 조립 기여/NodeVolume을 비교한다.
상수·선형 함수뿐 아니라 x²·x³ 시험 함수를 사용한다. contact/boundary node는 별도 분류한다.
저장된 float 좌표·EdgeCouple·EdgeLength를 정확 유리수로 취급한 진단으로 차이와 반올림 영향을 구분한다.
개별 stencil이 다르다는 사실과 y-균일 부분공간의 불변성이 깨졌다는 사실을 구분한다.
이 부분공간이 그대로 불변이면 해당 후보는 추가 2D 이산 검증 후보로 인정하지 않는다.
비불변성은 이산 검증의 성격을 입증할 뿐 물리적인 y-비균일 소자를 만든다는 뜻이 아니다.

## 5. 기하·import 사전 gate
모든 등급에서 둔각=0, 퇴화=0, 정확 hanging node=0, 재료 중첩/틈=0,
domain 면적과 삼각형 합계 상대오차≤1e-12를 요구한다.
큰 mesh에서도 hanging node 검사를 생략하지 않는다.
공식 import 후 sum(NodeVolume)와 삼각형 면적을 기존 1e-12 기준으로 대조한다.
이 중 하나 실패하면 해당 후보 solve=0. 접점이 전체 y 높이를 덮는지 확인한다.
기하 승인만으로 전류·국소 제어체적·PN 정확도를 승인하지 않는다.

## 6. canonical·production gate
각 방향의 fresh device마다 전체 node의 canonical donor/acceptor/net를 유한 수치로 검사한다.
checked=n, unresolved=mismatch=0을 요구하고 실패 시 audit doping write=0, sweep=0, solve=0.
production apply_doping의 STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED 거부를 기록한다.
production gate를 해제하지 않고 감사 입력만 공식 node API로 쓴다.
엔진·설치 파일·NodeVolume·EdgeCouple·물리식은 변경하지 않는다.

## 7. 1D 대응과 전기장
E6K 원시 x 좌표와 같은 좌표에서만 nodal profile을 직접 비교한다.
세분으로 추가된 x에서는 기존 1D reference에 없는 값임을 명시한다.
추가 node에 보간한 값을 진짜 1D solve 값으로 부르지 않으며 pass 판정에 섞지 않는다.
공통 좌표로 도핑 경계를 넘어 보간하지 않는다. 공통 좌표가 부족하면 비교 NOT_EVALUATED.
edge ElectricField는 edge 방향 성분 E_edge=(ψ@n0−ψ@n1)/length다.
x 성분은 endpoint orientation과 cosθ를 반영하되, E_x(y 균일)의 역추정은 가정과 조건을 명시한다.
주 판정은 동일 endpoint의 수평 edge 또는 동일 양끝 potential 차/거리로 제한한다.
EdgeCouple을 곱한 적분 flux는 edge 전기장 자체와 구분해 진단으로 저장한다.

## 8. bias·solve 수·continuation
E6M과 동일 forward [0.1,0.2,0.3,0.4,0.5,0.6]V,
reverse [−0.25,−0.5,−0.75,−1.0]V.
각 방향 fresh device, equilibrium Poisson+DD 후 순서대로 continuation.
등급당 8+6=14, 세 등급 최대42 solves. 실패한 solve도 호출 예산에 포함한다.
추가 물리 재실행·retry·bias 분할·tolerance 변경은 승인 없이 하지 않는다.
실제 호출 로그로 중복 호출이 없음을 확인한다.

## 9. 기존 기준 적용
전류 보존 1e-3, forward 1D 비교 1%, reverse 2%, potential 비교 0.01V_t,
carrier 1%, junction-field 2%, mesh sensitivity 전류1%/2%·field2%는 E6M 기준 유지.
공통 endpoint가 없는 전기장 비교는 기존 기준을 억지로 적용하지 않고 NOT_EVALUATED.
y 변동 1e-5V/1e-3은 이산 오차 진단으로 유지하며 PN 물리 y균일 조건과 구분한다.
새 mesh에서 충분한 common reference가 없으면 기존 reference로 검증 불가라고 보고한다.
공학 허용오차를 물리 법칙이나 논문 정리라고 부르지 않는다.

## 10. 원시 증거
source/PLAN/judge 해시, 패키지·precision·solver·물리 parameters, 원본/생성 좌표,
node/triangle/edge 대응, tags, full contact node set, NodeVolume, 공식 get_edge_model_values의
EdgeCouple·EdgeLength·끝점 모델, Donors/Acceptors/NetDoping을 방향별로 저장한다.
각 판정 bias의 Potential/Electrons/Holes/ElectricField, 양 접점 전류,
실제 solve 호출 기록, 수렴 기록, canonical 사전검사와 차단 spy를 포함한다.
원본 E6M에는 EdgeCouple이 없으므로 과거에 측정된 자료로 보충하지 않는다.
출력 누락·상한 초과·해시 불일치는 fail-closed이며 RC=0을 물리 PASS로 대체하지 않는다.

## 11. 승인 경계
이 문서는 초안이며 원격 실행 승인이 아니다.
후보의 geometric preflight 및 이산 비환원성 진단이 성립하지 않으면 이유를 보고하고 멈춘다.
일반 2D PN, 생산 GUI PN, 공정 이력·산화/확산/활성화 검증으로 확대하지 않는다.
현재 production gate와 기존 원본 PLAN은 그대로 유지한다.
