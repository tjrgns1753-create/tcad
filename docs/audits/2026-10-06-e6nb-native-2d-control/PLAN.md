# E6N-B — native 양성 대조군과 2D Poisson 해석해 검증

## 목적 / 승인 경계

사용자는 승인 질문 없이 분석·구현·검증을 계속하도록 지시했다. 이 독립 감사는 이전 E6N-A의 고정 메쉬와 INCONCLUSIVE 판정을 바꾸지 않는다. production tcad/tests/GUI, PN/DD gate, 엔진 내부와 가중치 override는 변경하지 않는다. PN solve와 실제 공정 simulation은 하지 않는다.

이번에는 이미 손계산 양성 fixture로 고정한 21-node/26-triangle 메쉬를 재사용한다. 이 메쉬는 실제 PN 후보나 제조된 웨이퍼를 대표하지 않는다. 기존 tensor 대조군도 함께 import한다. 신규 remesher는 만들지 않는다.

## 근거 / 모델

DEVSIM Manual 2.11.0 https://devsim.net/models.html §5.2.6: node model은 NodeVolume으로, edge model은 EdgeCouple로 적분한다. 공식 API의 Potential 차이 / EdgeLength flux만 사용한다. source가 필요한 경우 node_model과 node_values로 명시한 manufactured source를 넣는다. 외부 라이브러리 내부 변경 없음.

Checkpoint B0: 실제 공식 배열을 합성 양성 fixture의 독립 손계산/기하 값과 대조한다. 상대오차 geometry weight/local volume <=1e-10, length 좌표 대조 기존 64eps 기준 유지. 분석 classify의 문턱도 그대로다. positive fixture는 NONINVARIANCE_WITNESS, tensor fixture는 INCONCLUSIVE여야 한다. node mapping은 좌표와 connectivity로 검증한다. pair 원본6/11의 power2 작용은 -125000 및 -2250000/17 cm^-2에 상대오차 <=1e-10로 일치해야 한다. 통과는 판정기/native 가중치 양성 경로만 승인한다.

Checkpoint B1은 B0 통과 때만 수행한다. scalar Poisson의 manufactured solution:

phi(x,y)=sin(pi*(x-xmin)/Lx)*cos(pi*(y-ymin)/Ly) [V].
-div(grad phi)=K*phi, K=pi^2*(1/Lx^2+1/Ly^2) [cm^-2].
좌우 contact는 phi=0 Dirichlet, 위아래는 natural zero flux이다(cos의 y 미분은 y 경계에서0). flux=(Potential@n0-Potential@n1)*EdgeInverseLength, node source=-K*phi_exact. 이는 coefficient를1로 정규화한 수치 PDE 검증이며 Si 전하 농도/도핑/PN carrier 모델이 아니다. 해석 source는 독립 연속 미분으로 만든다. 이산 residual로 source를 생성하면 안 된다.

## 고정 기하와 mesh convergence

positive_fixture의 cm 좌표를 VTU um 좌표로 변환하고 기존 production importer로 다시 cm로 읽는다. 생성/재료 태그는 실제 ViennaPS Material.Si enum 사용이다(공정 solve 없음). 공식 import / 가중치 검사는 매 mesh에서 수행한다.

M0=원본 양성 fixture. M1/M2/M3은 기존 mesh_refine._refine_once를 ALL triangles marked=True로 각각1회씩 적용한다. 각 triangle을4등분하는 기존 red branch만 사용한다. green/closure의 국소성 문제를 이 실험에서 우회 승인하지 않는다. 삼각형26/104/416/1664, 같은 domain/contact, h_max가 단계마다 절반이어야 한다. exact conformity·nonobtuse·면적·접점 검사 필수.

측정: L_inf node error[V], NodeVolume weighted L2[V], h_max[cm], rate=log(error_old/error_new)/log2, 실제 noncontact normalized residual(max abs / global row magnitude), source/Potential/native 기하 배열.

사전 합격 기준(물리 법칙이나 증명된 오차 상한이 아닌 이번 수치 검증의 engineering criteria):
- solve attempt와 성공은 mesh당1회, 총4회. solve 실패 / snapshot 실패 분리. maximum_iterations30, absolute_error=relative_error=1e-10.
- 최종 M3 L_inf<=0.01V; 마지막 두 구간(M1->M2, M2->M3)의 L_inf와 weighted L2 rate 모두>=1.5; error가0이면 정확 일치로 별도 기록하며 rate를 발명하지 않는다.
- 실제 noncontact discrete residual relative<=1e-9. 좌우 contact오차<=1e-10V.
- y-varying 해를 검사한다: M3에서 x중앙에 가장 가까운 비접점 열의 y spread>0.5V. x-only 해로 통과할 수 없다.
- 기준 실패는 FAIL/INCONCLUSIVE로 보존한다. geometry/함수/문턱을 결과에 맞춰 조정하지 않는다.

## 실행·자원·증거

로컬: AST/합성 식/기하/판정기 테스트만. native import/solve는 GitHub-hosted Windows만. PLAN SHA 진입점 검사→remote 확인→자식 Job 배정→native engine 준비. source SHA도 보존한다.
자식 총120초, 외부 profile150초(cleanup 여유), sampled working-set6GiB. 요소 상한10000, 출력50MiB. engine 준비부터 B0 완료까지 solve trap으로0호출을 강제한다. B1만4회 허용한다. 실패시 추가 호출 금지. 삭제 뒤 device/mesh0, Job descendant0. native weight 재정의/NetDoping 쓰기/PN sweep 금지.

원시 NPZ/result/log SHA, engine/package version, preflight/실행 source, actual call counts/cleanup, 실패도 보존한다. 이 결과만으로 PN/공정 물리 gate를 해제하지 않는다.
