# E6N-A — 공식 import와 이산 환원 진단 사전 계획

이 문서는 원격 실행 전 단독 커밋한다. PN/DC solve는 0회이며 이 문서로 승인하지 않는다.
기준 production SHA: ffa7e4a8872cd914e42066b1b1742312883c8dda.
기존 E6M PLAN 및 원본 증거는 보존한다. 실행 시작에서 독립 상수 SHA를 LF 정규화 비교한다.

## 입력과 지원 범위
E6M/E6K 단일 Si x=[-20,20]µm, y=[-0.1,0]µm. 도핑 정의·접점·온도·물리 파라미터는 변경하지 않는다.
이번에는 도핑 쓰기와 물리 방정식 생성도 필요하지 않으며 실행하지 않는다.
E6G 빌더 structured_lateral_refine만 재사용한다. centers=[0],half_widths=[0.1]µm.
N0/N1/N2는 저장된 E6K L0/L1/L2 x 좌표와 y 행 16/32/64를 사용한다.
예상 출력 노드 8037/31173/122761, 삼각형 15264/60736/242304. 불일치하면 중단한다.
E6N 생성 코드·기하 결과·설계 규칙·E6K arrays SHA를 실행 입력 목록과 결과에 기록한다.
메쉬별 기하 SHA도 저장한다. 입력은 ffa7e4a의 파일로 고정한다.

## 공식 근거와 API
DEVSIM Manual 2.11.0: https://devsim.net/models.html (§5.2, §5.2.6).
공식 소스 revision 43b41ca845184c47e22b72d144db7e7db8509377 (v2.11.0.rc5/main 조사 시점).
최종 v2.11.0 태그는 조회 시 존재하지 않았다. 따라서 이 revision을 최종 wheel과 동일하다고 주장하지 않는다.
원격 wheel 버전과 simple_physics의 실제 소스 SHA/식 대응을 추가 기록한다.
https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/TriangleEdgeCouple.cc
https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/TriangleNodeVolume.cc
https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/NodeVolume.cc
https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/python_packages/simple_physics.py
EdgeCouple은 삼각형 circumcenter에서 edge midpoint까지의 길이를 edge별 합산한다.
비둔각 메쉬에서 transmissibility=EdgeCouple/EdgeLength=Σ cot(opposite angle)/2.
NodeVolume=Σincident-edge EdgeCouple*EdgeLength/4.
production semiconductor_equation은 공식 CreateSiliconPotentialOnly를 사용하며
flux=Permittivity*(Potential@n0-Potential@n1)*EdgeInverseLength를 EdgeCouple로 적분한다.
균일 Permittivity는 이산 부분공간 판정에서 공통 비영 인자라 생략할 수 있다. 전하 node term은 y균일 입력에서 별도 비균일성을 만들지 않는다.
production solve.py의 flux도 EdgeInverseLength이고 이중 EdgeCouple은 없다.
공식 create_gmsh_mesh/add_gmsh_region/add_gmsh_contact/finalize_mesh/create_device는 production importer로 재사용한다.
get_node_model_values/get_edge_model_values/get_element_node_list/edge_from_node_model/delete_device/delete_mesh만 추가 사용한다.
엔진 내부·모델 가중치 덮어쓰기·signed override·fallback 금지.

## 실행 경계와 기하/import
로컬은 엔진 없는 조사·합성 테스트만. 엔진 import는 GitHub-hosted Windows에서만.
PLAN SHA 확인 → remote 환경 확인 → backend import → 독립 solve trap → 기존 기하 생성 → 공식 import.
solve trap은 호출 직전 attempts를 증가시키고 예외를 던진다. attempts>0이면 전체 FAIL.
모든 후보 exact 둔각/퇴화/hanging 0, 영역·면적·경계 보존을 요구한다.
sum(NodeVolume)와 실제 triangle area 상대오차≤1e-12를 유지한다.
좌표 정렬 대응 및 삼각형 connectivity 일치, edge endpoint 대응을 검사한다.
NodeVolume>0, EdgeLength>0, EdgeCouple≥0, 모두 유한. zero EdgeCouple은 직각 대각선에서 허용한다.
접점은 전체 좌우 경계 node 집합과 정확히 같아야 한다. 삭제 후 device/mesh 누수 0.
공식 local volume은 기하로 독립 계산한 값과 후보 전체에서 상대오차≤1e-10로 대조한다.
cot weight는 전체 edge에서 abs-error≤1e-10*max(1,|w_geom|)로 대조한다.
이는 사전 등록된 수치 진단 기준이며 물리 법칙/엔진 roundoff 정리가 아니다.

## 이산 환원 진단과 승인 범위
A g(i)=Σ_j w_ij*(g(x_i)-g(x_j))/V_i. g={1,x/L,(x/L)^2,(x/L)^3}, L=40µm.
strict interior·top/bottom 무접점 node·contact node를 구분한다. contact는 bulk 판정에서 제외한다.
모든 node에서 네 함수의 작용과 raw/normalized 값을 저장한다. x별 grouping으로 y spread를 기록한다.
이 네 함수가 같다는 사실만으로 모든 x 함수에 대한 불변성을 증명하지 않는다.
서로 다른 y의 같은 x node pair에서 x별로 합친 row coefficients도 조사한다.
실제 공식 배열은 float 후처리와 math.fsum 후처리를 비교한다.
기하 exact Fraction cot/volume으로 witness row를 재계산하며 정확한 비영 projected-row 차이를 확인한다.
native 가중치 생성 roundoff가 Fraction 후처리로 복원된다고 주장하지 않는다.
공식-기하 coefficient 차이가 유발하는 bound를 Σ|δw||g_i-g_j|/V 및 volume 차이로 산정한다.
구조적 witness 기준: polynomial pair 차이 > 100*(기하-공식 연산자 오차 합 + 100*eps*operator_scale),
또한 >1e-8*operator_scale, exact geometry projected-row 차이가 비영이어야 한다.
operator_scale은 각 row의 2*Σ|w|/V로 고정한다. 결과에 맞춘 threshold 변경 금지.
이 기준은 보수적 진단 기준이며 native 기하 전체의 엄밀 오차상한이라고 주장하지 않는다.
각 x에서 strict interior pair 우선, 별도로 무접점 top/bottom을 포함한 pair를 비교한다.
선택 witness는 저장된 좌표 순서만으로 전이 영역 |x|≤0.2µm의 최대 12 x그룹을 균등 선택한다.
각 그룹 첫 strict interior·중간 strict interior·마지막 strict interior 및 top/bottom pair를 검사한다.
비교 가능 node 없으면 NOT_MEASURED. 충분한 witness가 없거나 오차 구분이 안 되면 INCONCLUSIVE.
stencil 차이만으로 승인하지 않는다. witness 통과는 후보의 이산 비환원성만 승인하고 PN 정확성은 미검증이다.
N0 import 또는 진단 FAIL/INCONCLUSIVE/NOT_MEASURED면 N1/N2는 NOT_RUN으로 멈춘다.
N0의 충분한 witness가 성립하면 같은 고정 기준으로 N1/N2를 순차 실행한다.

## 자원·완전성·판정
요소 상한400000/후보, 동시에 device1개. 후보 wall600초/전체1800초, working-set6GiB.
한계 초과/필수 출력 누락/해시 불일치/solve attempt/cleanup 실패는 FAIL. retry 없음.
예상 dense 배열 상한: node64bytes+triangle24bytes+edge96bytes(최대3T), 진단16node64bytes.
N2 예상 약90MiB 미만 수치 배열; Python/엔진 객체 overhead는 이 계산으로 보장되지 않는다.
전체 uncompressed raw 최대200MiB, 파일별최대120MiB. 저장 전에 bytes를 계산하고 초과하면 중단한다.
compressed npz와 요약/PLAN/SHA를 artifact로 보존. wrapper omitted_outputs가 있으면 승인 금지.
원본 geometry·import geometry·edge endpoint·가중치·contacts·polynomial action·witness exact strings를 저장한다.
실행 source/PLAN/input/artifact SHA, wheel version, precision, solve_attempts, cleanup을 기록한다.
합성 반례: 누락/endpoint범위/PLAN불일치·누락/비교node없음/stencil-only/roundoff-only/solveattempt/증거생략/정상대조군.
RC는 실행 종료 상태이고 verdict와 분리한다. 기하 PASS와 진단 PASS와 PN 미실행을 별도 기록한다.
어떤 결과에서도 PN sweep·전체회귀·gate해제·main병합을 자동 시작하지 않는다.
