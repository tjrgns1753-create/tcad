# E6N-A 중간 제출 — INPUT_PREFLIGHT_BLOCKED (물리/import 판정 미실행)

## 1. 판정과 중단
이번 E6N-A는 완료 승인하지 않는다. 원격 1회는 실행기 입력 해시 오류로 import 전에 실패했다.
N0/N1/N2 모두 NOT_RUN. 기하/import 통과, NodeVolume·조립·1D 비환원성을 새로 주장하지 않는다.
PN/DC solve, E6M 42회 재실행, 전체 회귀, main 병합, gate 해제 없음.
원격 재실행은 금지 지시에 따라 하지 않았다. 수정 후 원격 실측은 별도 승인이 필요하다.

## 2. 시작·동기화
브랜치 claude/remote-runner, 시작 HEAD/origin cdcb830ff07ef5e8f4938c111eaa18be546de6e7.
기존 staged E6M 보완 12개 파일을 보존하고 승인된 내용만 ffa7e4a8872cd914e42066b1b1742312883c8dda로 커밋·push했다.
당시 로컬/원격 SHA 일치. E6M push는 workflow trigger 경로를 변경하지 않았다.
원격 기존 계산은 모두 completed. 별도 로컬 run_all.py --mode holdout은 목적 미확정이라 보존했다.
사용자가 제공한 AGENTS 한국어 원칙과 프로젝트 CLAUDE.md를 읽었다. 조사한 상위/global 지침 파일은 발견되지 않았다.

## 3. 고정 PLAN·실행
PLAN 단독 커밋 f9ddff72c161812dc8dd340fffdc929f33be7aea.
LF 정규화 SHA a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103.
실행 SHA 1dac0a4edd2be83ba99f981483a2cfd4cc804a04.
run https://github.com/tjrgns1753-create/tcad/actions/runs/36966289573 .
run number 33, attempt 1, request e6na-import-reduction-001.
profile 시작 2026-10-02T04:51:12.279662Z, duration0.827초, RC1, wrapper FAIL.
summary의 원시 PLAN hash는 checkout CRLF 기준이며 위 LF 정규화 hash와 직접 비교하면 안 된다.
원본 artifact summary.json/run.log를 raw/remote-run-33에 바이트 그대로 보존했다.
summary log SHA fc7b639da4b7f4d1df7806fa7df32d28c85c9727fa151d26bdb0084f427f23f3.
outputs/omitted_outputs 모두 빈 목록. 계산 결과 배열은 생성되지 않았다.

## 4. 실제 결함과 수정
execute()는 문자를 LF 정규화해 검사하지만 mesh_refine.py/mesh_import.py의 예상 SHA에는 로컬 CRLF 원시 SHA를 넣었다.
따라서 정상적이며 원격과 같은 내용의 파일을 잘못 거부했다. TCAD/DEVSIM 결함이 아니라 이번 감사 실행기의 결함이다.
원격 summary의 두 원시 SHA가 로컬 원시 SHA와 정확히 같으므로 이번 실패가 동기화 불일치라는 근거는 없다.

| 파일 | 잘못 넣은 원시 SHA | 수정한 LF 정규화 SHA |
|---|---|---|
| mesh_refine.py | 3b84190bbb4c0cfe9f13b668518820f8822e0fd04b2de0ec6c6194483f7c507d | 8973c358aca2e0173918b33117006dc638f37f8c68d8dc922c573c257b50f5e0 |
| mesh_import.py | cbc4111e0a7d30d7b0f1317ba26c7947c132e580802e6bd1913fc9bc7310a62d | 0fe7c71d6594db777d038907a52067ad13b99b868f094758f196d0bbbfe721a8 |

require_inputs()를 분리해 실제 입력 파일과 LF/CRLF 변형 대조군을 엔진 없이 검사했다.
LF/CRLF 모두 통과, 실제 내용 변경은 차단. PLAN 누락/불일치 callback0 계약도 유지된다.
PLAN이나 원본 파일 내용은 수정하지 않았다. 사후 물리 tolerance 튜닝도 하지 않았다.

## 5. 공식 API와 production 대응
[DEVSIM Manual 2.11.0](https://devsim.net/models.html) §5.2/5.2.6:
NodeVolume은 node 적분, EdgeCouple은 edge flux 적분에 쓰이고 EdgeInverseLength는 inverse length다.
공식 소스 조사 revision43b41ca845184c47e22b72d144db7e7db8509377은 v2.11.0.rc5/main으로,
존재하지 않는 최종 v2.11.0 tag와 같다고 주장하지 않는다.
TriangleEdgeCouple.cc는 midpoint-circumcenter 거리의 magnitude, TriangleNodeVolume.cc는 couple*length/4.
비둔각 조건 아래 cotangent transmissibility와 local Voronoi area로 독립 대조하는 진단을 작성했다.
production semiconductor_equation.py는 공식 CreateSiliconPotentialOnly를 사용한다.
공식 simple_physics는 Permittivity*ElectricField, ElectricField=(Potential@n0-Potential@n1)*EdgeInverseLength.
production solve.py의 EdgeInverseLength 수정은 읽기 전용으로 확인했고 바꾸지 않았다.
공식 소스 경로 및 source revision 링크는 PLAN.md에 있다.
이번 worker는 backend 전에 중단돼 실제 설치 wheel의 source/가중치는 새로 확보되지 않았다.

## 6. solve와 import 경계
worker traceback은 require_inputs의 mesh_refine 검사에서 중단했다.
따라서 audit worker의 backend import0, mesh 생성/import0, doping write0, solve call0.
공용 remote wrapper는 실행 전 패키지/DEVSIM info를 별도 subprocess로 읽는다.
그러므로 “원격 job 전체에서 DEVSIM import0”라고 주장하지 않는다.
실제 solve0의 근거는 worker의 실행 전 중단과 wrapper의 info-only 호출이다.
메쉬·가중치·contact·precision·cleanup 실측은 NOT_MEASURED다.

## 7. 로컬 테스트
test_contract.py 엔진 없이 PASS:
PLAN missing/mismatch→callback0, valid LF/CRLF→synthetic callback1.
필수 가중치 누락/endpoint 범위 밖/solveattempt1/omitted evidence→차단.
비교 node없음→NOT_MEASURED, stencil-only/roundoff-only→INCONCLUSIVE.
정상 metric 대조군→NONINVARIANCE_WITNESS.
원격 실패 후 실제 입력 전체 LF/CRLF 대조를 추가해 PASS.
이는 원격 import 정상성 또는 production PN 정확성 검증이 아니다.
remote/run_profile.py --validate-only PASS, Python AST PASS.
실제 DEVSIM/ViennaPS local import0, solve0.

## 8. 기하·자원 상태
E6N-A에서 생성하지 않았다. 이전 순수 기하 15264/60736/242304 요소 결과만 입력으로 고정한다.
새 후보별 import/time/memory/output 실측은 없다.
PLAN의 600초/후보·1800초 전체·6GiB·200MiB는 예산이지 성공 보장이 아니다.
현재 구현의 후보 wall/memory 검사 일부는 단계 종료 후 checkpoint다.
장시간 단일 native call의 후보별 즉시 중단까지 보장한 것으로 승인하지 않는다.
remote wrapper 전체 timeout은 별도로 존재한다.
수정 후 원격 재실행 전 자원 enforcement 및 판정기 독립 검토가 남아 있다.

## 9. 무변경 증거
git diff ffa7e4a -- tcad tests tcad_2d_stagewise.py는 빈 diff.
E6M PLAN raw SHA5aeb9dc28bf79f82404d728f9507c6a8208c531cc9bff32829cbf46e58e5410f 유지.
followup_evidence.py를 읽기 전용으로 재실행해 E6M/E6K JSON·NPZ·PLAN byte==기준 git blob 확인.
과거 역방향 canonical NOT_RECORDED 및 종속 BLOCKED 판정 유지.
production/gate/엔진 설치/기존 원본 PLAN 수정0.

## 10. Serena investigation
도구 inventory에 Serena가 없어 실제 호출을 하지 못했다. 재시도 성공을 발명하지 않는다.
rg/직접 읽기로 조사:
- structured_lateral_refine / structured_grid_of / _strip_depths: 기존 E6G 기하 생성.
- import_process_result: production importer, 공식 create_gmsh/add_gmsh/finalize/create_device 호출 및 area gate.
- setup_semiconductor_potential_equation: 공식 simple_physics helper 사용.
- run_basic_potential_solve: EdgeInverseLength flux 유지.
- M.build_mesh / T.write_mesh / T.nodes_of_contact: 기존 감사 helper 재사용.
새 diagnostics는 새 run_e6na.py 및 test_contract.py만 호출한다.
새 run_e6na.py의 원격 진입은 allowlist profile1개다. 기존 production caller 수정0.
상세 코드 의미는 Serena memory가 아니라 현재 파일과 Git diff로 확인했다.

## 11. 실제 변경과 미승인 범위
새 PLAN.md, diagnostics.py, run_e6na.py, test_contract.py; remote/profiles.py profile 추가, remote/request.json 교체.
diagnostics는 검증 후처리이며 production solver 대체나 새 remesher가 아니다.
1D 환원 판정의 selected polynomial/witness 및 roundoff 기준은 아직 원격 검증되지 않았다.
witness가 없다는 사실로 불변성을 승인하지 않는다.
공식 coefficient를 읽고 모든 node polynomial action을 저장하도록 작성했지만 실제 결과는 없다.
PN/DC·일반2D·GUI·공정이력 검증은 이 배치로 승인하지 않는다.

## 12. 다음 승인 조건
수정한 해시 계약·정상 대조군을 검토하고 입력 경계 오류가 더 없는지 확인한다.
후보별 자원 enforcement와 endpoint 증거 검증을 별도 검토한다.
그 다음에만 원격 import-only 1회 재실행을 별도 승인한다.
PN sweep은 그 후에도 공식 import·local weights·이산 환원 진단 결과의 별도 검토 전 금지한다.

## 13. Change diff
CHANGES_FINAL.patch는 ffa7e4a 기준 구현·PLAN·remote 설정의 전체 semantic diff다.
SHA256 a3e4df4a5c4abb4ea807d0b5bf665d35cf2b30fd78548ff04411ac8c147b335c.
아래는 모든 hunk를 포함한 동일 patch다. 최종 심볼 위치는 아래 unified hunk 및 소스 파일에서 확인한다.
보고서/원본 artifact는 patch 자체 참조 순환을 피하려고 diff 수치에서 제외했다.

```diff
diff --git a/docs/audits/2026-10-02-e6na-import-reduction/PLAN.md b/docs/audits/2026-10-02-e6na-import-reduction/PLAN.md
new file mode 100644
index 0000000..e101bf0
--- /dev/null
+++ b/docs/audits/2026-10-02-e6na-import-reduction/PLAN.md
@@ -0,0 +1,82 @@
+# E6N-A — 공식 import와 이산 환원 진단 사전 계획
+
+이 문서는 원격 실행 전 단독 커밋한다. PN/DC solve는 0회이며 이 문서로 승인하지 않는다.
+기준 production SHA: ffa7e4a8872cd914e42066b1b1742312883c8dda.
+기존 E6M PLAN 및 원본 증거는 보존한다. 실행 시작에서 독립 상수 SHA를 LF 정규화 비교한다.
+
+## 입력과 지원 범위
+E6M/E6K 단일 Si x=[-20,20]µm, y=[-0.1,0]µm. 도핑 정의·접점·온도·물리 파라미터는 변경하지 않는다.
+이번에는 도핑 쓰기와 물리 방정식 생성도 필요하지 않으며 실행하지 않는다.
+E6G 빌더 structured_lateral_refine만 재사용한다. centers=[0],half_widths=[0.1]µm.
+N0/N1/N2는 저장된 E6K L0/L1/L2 x 좌표와 y 행 16/32/64를 사용한다.
+예상 출력 노드 8037/31173/122761, 삼각형 15264/60736/242304. 불일치하면 중단한다.
+E6N 생성 코드·기하 결과·설계 규칙·E6K arrays SHA를 실행 입력 목록과 결과에 기록한다.
+메쉬별 기하 SHA도 저장한다. 입력은 ffa7e4a의 파일로 고정한다.
+
+## 공식 근거와 API
+DEVSIM Manual 2.11.0: https://devsim.net/models.html (§5.2, §5.2.6).
+공식 소스 revision 43b41ca845184c47e22b72d144db7e7db8509377 (v2.11.0.rc5/main 조사 시점).
+최종 v2.11.0 태그는 조회 시 존재하지 않았다. 따라서 이 revision을 최종 wheel과 동일하다고 주장하지 않는다.
+원격 wheel 버전과 simple_physics의 실제 소스 SHA/식 대응을 추가 기록한다.
+https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/TriangleEdgeCouple.cc
+https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/TriangleNodeVolume.cc
+https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/src/GeomModels/NodeVolume.cc
+https://github.com/devsim/devsim/blob/43b41ca845184c47e22b72d144db7e7db8509377/python_packages/simple_physics.py
+EdgeCouple은 삼각형 circumcenter에서 edge midpoint까지의 길이를 edge별 합산한다.
+비둔각 메쉬에서 transmissibility=EdgeCouple/EdgeLength=Σ cot(opposite angle)/2.
+NodeVolume=Σincident-edge EdgeCouple*EdgeLength/4.
+production semiconductor_equation은 공식 CreateSiliconPotentialOnly를 사용하며
+flux=Permittivity*(Potential@n0-Potential@n1)*EdgeInverseLength를 EdgeCouple로 적분한다.
+균일 Permittivity는 이산 부분공간 판정에서 공통 비영 인자라 생략할 수 있다. 전하 node term은 y균일 입력에서 별도 비균일성을 만들지 않는다.
+production solve.py의 flux도 EdgeInverseLength이고 이중 EdgeCouple은 없다.
+공식 create_gmsh_mesh/add_gmsh_region/add_gmsh_contact/finalize_mesh/create_device는 production importer로 재사용한다.
+get_node_model_values/get_edge_model_values/get_element_node_list/edge_from_node_model/delete_device/delete_mesh만 추가 사용한다.
+엔진 내부·모델 가중치 덮어쓰기·signed override·fallback 금지.
+
+## 실행 경계와 기하/import
+로컬은 엔진 없는 조사·합성 테스트만. 엔진 import는 GitHub-hosted Windows에서만.
+PLAN SHA 확인 → remote 환경 확인 → backend import → 독립 solve trap → 기존 기하 생성 → 공식 import.
+solve trap은 호출 직전 attempts를 증가시키고 예외를 던진다. attempts>0이면 전체 FAIL.
+모든 후보 exact 둔각/퇴화/hanging 0, 영역·면적·경계 보존을 요구한다.
+sum(NodeVolume)와 실제 triangle area 상대오차≤1e-12를 유지한다.
+좌표 정렬 대응 및 삼각형 connectivity 일치, edge endpoint 대응을 검사한다.
+NodeVolume>0, EdgeLength>0, EdgeCouple≥0, 모두 유한. zero EdgeCouple은 직각 대각선에서 허용한다.
+접점은 전체 좌우 경계 node 집합과 정확히 같아야 한다. 삭제 후 device/mesh 누수 0.
+공식 local volume은 기하로 독립 계산한 값과 후보 전체에서 상대오차≤1e-10로 대조한다.
+cot weight는 전체 edge에서 abs-error≤1e-10*max(1,|w_geom|)로 대조한다.
+이는 사전 등록된 수치 진단 기준이며 물리 법칙/엔진 roundoff 정리가 아니다.
+
+## 이산 환원 진단과 승인 범위
+A g(i)=Σ_j w_ij*(g(x_i)-g(x_j))/V_i. g={1,x/L,(x/L)^2,(x/L)^3}, L=40µm.
+strict interior·top/bottom 무접점 node·contact node를 구분한다. contact는 bulk 판정에서 제외한다.
+모든 node에서 네 함수의 작용과 raw/normalized 값을 저장한다. x별 grouping으로 y spread를 기록한다.
+이 네 함수가 같다는 사실만으로 모든 x 함수에 대한 불변성을 증명하지 않는다.
+서로 다른 y의 같은 x node pair에서 x별로 합친 row coefficients도 조사한다.
+실제 공식 배열은 float 후처리와 math.fsum 후처리를 비교한다.
+기하 exact Fraction cot/volume으로 witness row를 재계산하며 정확한 비영 projected-row 차이를 확인한다.
+native 가중치 생성 roundoff가 Fraction 후처리로 복원된다고 주장하지 않는다.
+공식-기하 coefficient 차이가 유발하는 bound를 Σ|δw||g_i-g_j|/V 및 volume 차이로 산정한다.
+구조적 witness 기준: polynomial pair 차이 > 100*(기하-공식 연산자 오차 합 + 100*eps*operator_scale),
+또한 >1e-8*operator_scale, exact geometry projected-row 차이가 비영이어야 한다.
+operator_scale은 각 row의 2*Σ|w|/V로 고정한다. 결과에 맞춘 threshold 변경 금지.
+이 기준은 보수적 진단 기준이며 native 기하 전체의 엄밀 오차상한이라고 주장하지 않는다.
+각 x에서 strict interior pair 우선, 별도로 무접점 top/bottom을 포함한 pair를 비교한다.
+선택 witness는 저장된 좌표 순서만으로 전이 영역 |x|≤0.2µm의 최대 12 x그룹을 균등 선택한다.
+각 그룹 첫 strict interior·중간 strict interior·마지막 strict interior 및 top/bottom pair를 검사한다.
+비교 가능 node 없으면 NOT_MEASURED. 충분한 witness가 없거나 오차 구분이 안 되면 INCONCLUSIVE.
+stencil 차이만으로 승인하지 않는다. witness 통과는 후보의 이산 비환원성만 승인하고 PN 정확성은 미검증이다.
+N0 import 또는 진단 FAIL/INCONCLUSIVE/NOT_MEASURED면 N1/N2는 NOT_RUN으로 멈춘다.
+N0의 충분한 witness가 성립하면 같은 고정 기준으로 N1/N2를 순차 실행한다.
+
+## 자원·완전성·판정
+요소 상한400000/후보, 동시에 device1개. 후보 wall600초/전체1800초, working-set6GiB.
+한계 초과/필수 출력 누락/해시 불일치/solve attempt/cleanup 실패는 FAIL. retry 없음.
+예상 dense 배열 상한: node64bytes+triangle24bytes+edge96bytes(최대3T), 진단16node64bytes.
+N2 예상 약90MiB 미만 수치 배열; Python/엔진 객체 overhead는 이 계산으로 보장되지 않는다.
+전체 uncompressed raw 최대200MiB, 파일별최대120MiB. 저장 전에 bytes를 계산하고 초과하면 중단한다.
+compressed npz와 요약/PLAN/SHA를 artifact로 보존. wrapper omitted_outputs가 있으면 승인 금지.
+원본 geometry·import geometry·edge endpoint·가중치·contacts·polynomial action·witness exact strings를 저장한다.
+실행 source/PLAN/input/artifact SHA, wheel version, precision, solve_attempts, cleanup을 기록한다.
+합성 반례: 누락/endpoint범위/PLAN불일치·누락/비교node없음/stencil-only/roundoff-only/solveattempt/증거생략/정상대조군.
+RC는 실행 종료 상태이고 verdict와 분리한다. 기하 PASS와 진단 PASS와 PN 미실행을 별도 기록한다.
+어떤 결과에서도 PN sweep·전체회귀·gate해제·main병합을 자동 시작하지 않는다.
diff --git a/docs/audits/2026-10-02-e6na-import-reduction/diagnostics.py b/docs/audits/2026-10-02-e6na-import-reduction/diagnostics.py
new file mode 100644
index 0000000..1ff543d
--- /dev/null
+++ b/docs/audits/2026-10-02-e6na-import-reduction/diagnostics.py
@@ -0,0 +1,159 @@
+"""엔진 없는 E6N-A 기하/연산자 진단. 물리 solver가 아니다."""
+import math
+from fractions import Fraction as F
+
+import numpy as np
+
+
+def validate(a, solve_attempts=0, omitted=False):
+    if type(solve_attempts) is not int or solve_attempts != 0 or omitted:
+        raise ValueError('EVIDENCE_BLOCKED: solve attempt or omitted evidence')
+    keys = ('xy', 'triangles', 'edges', 'NodeVolume', 'EdgeCouple', 'EdgeLength')
+    if any(k not in a for k in keys):
+        raise ValueError('EVIDENCE_BLOCKED: required array missing')
+    xy, t, e = (np.asarray(a[k]) for k in keys[:3])
+    n = len(xy)
+    if xy.shape != (n, 2) or n == 0 or not np.all(np.isfinite(xy)) or len(np.unique(xy, axis=0)) != n:
+        raise ValueError('EVIDENCE_BLOCKED: invalid nodes')
+    for q, width in ((t, 3), (e, 2)):
+        if q.ndim != 2 or q.shape[1] != width or q.dtype.kind not in 'iu' or not len(q) or np.any(q < 0) or np.any(q >= n):
+            raise ValueError('EVIDENCE_BLOCKED: invalid endpoint/topology')
+    if np.any(e[:, 0] == e[:, 1]) or len(np.unique(np.sort(e, axis=1), axis=0)) != len(e):
+        raise ValueError('EVIDENCE_BLOCKED: duplicate/degenerate edge')
+    for key, count, positive in (('NodeVolume', n, True), ('EdgeLength', len(e), True), ('EdgeCouple', len(e), False)):
+        q = np.asarray(a[key])
+        if q.shape != (count,) or not np.all(np.isfinite(q)) or np.any(q <= 0 if positive else q < 0):
+            raise ValueError('EVIDENCE_BLOCKED: invalid ' + key)
+    return xy, t, e
+
+
+def geometry_weights(xy, triangles, edges):
+    """비둔각 삼각형 cotangent transmissibility와 local Voronoi area 대조."""
+    weights = {}
+    nv = np.zeros(len(xy))
+    for k in range(3):
+        i, j, o = triangles[:, k], triangles[:, (k + 1) % 3], triangles[:, (k + 2) % 3]
+        u, v = xy[i] - xy[o], xy[j] - xy[o]
+        cross = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
+        if np.any(cross == 0):
+            raise ValueError('degenerate triangle')
+        cot = np.einsum('ij,ij->i', u, v) / cross
+        if np.any(cot < -1e-14):
+            raise ValueError('negative geometric cotangent')
+        w = cot / 2
+        length2 = np.sum((xy[i] - xy[j])**2, axis=1)
+        np.add.at(nv, i, w * length2 / 4)
+        np.add.at(nv, j, w * length2 / 4)
+        for aa, bb, ww in zip(i, j, w):
+            key = (min(int(aa), int(bb)), max(int(aa), int(bb)))
+            weights[key] = weights.get(key, 0.0) + float(ww)
+    if set(weights) != {tuple(sorted(map(int, p))) for p in edges}:
+        raise ValueError('edge topology differs from triangles')
+    return np.array([weights[tuple(sorted(map(int, p)))] for p in edges]), nv
+
+
+def exact_row(node, xy, triangles, incident):
+    """선택 witness의 실제 저장 좌표를 Fraction으로 계산. native roundoff 복원 아님."""
+    q = {i: (F(float(xy[i, 0])), F(float(xy[i, 1]))) for ti in incident[node] for i in triangles[ti].tolist()}
+    row, volume = {}, F(0)
+    for ti in incident[node]:
+        tri = list(map(int, triangles[ti]))
+        for j in tri:
+            if j == node:
+                continue
+            o = next(i for i in tri if i != node and i != j)
+            u = (q[node][0]-q[o][0], q[node][1]-q[o][1])
+            v = (q[j][0]-q[o][0], q[j][1]-q[o][1])
+            w = (u[0]*v[0]+u[1]*v[1]) / (2*abs(u[0]*v[1]-u[1]*v[0]))
+            length2 = sum((q[node][k]-q[j][k])**2 for k in (0, 1))
+            volume += w * length2 / 4
+            row[j] = row.get(j, F(0)) + w
+    grouped = {}
+    for j, w in row.items():
+        xx = q[j][0]
+        grouped[xx] = grouped.get(xx, F(0)) - w / volume
+    xx = q[node][0]
+    grouped[xx] = grouped.get(xx, F(0)) + sum(row.values()) / volume
+    return grouped
+
+
+def classify(diff, scale, uncertainty, exact_nonzero):
+    if not all(math.isfinite(v) and v >= 0 for v in (diff, scale, uncertainty)):
+        raise ValueError('invalid diagnostic metric')
+    return 'NONINVARIANCE_WITNESS' if exact_nonzero and diff > 1e-8*scale and diff > 100*(uncertainty+100*np.finfo(float).eps*scale) else 'INCONCLUSIVE'
+
+
+def analyze(a):
+    xy, triangles, edges = validate(a)
+    w = a['EdgeCouple']/a['EdgeLength']
+    gw, gv = geometry_weights(xy, triangles, edges)
+    nv = a['NodeVolume']
+    wr = float(np.max(np.abs(w-gw)/np.maximum(1, np.abs(gw))))
+    vr = float(np.max(np.abs(nv-gv)/gv))
+    if wr > 1e-10 or vr > 1e-10:
+        raise ValueError('LOCAL_GEOMETRY_WEIGHT_MISMATCH')
+    n = len(xy)
+    operator_scale = np.zeros(n)
+    for k in (0, 1):
+        np.add.at(operator_scale, edges[:, k], 2*np.abs(w))
+    operator_scale /= nv
+    xx = xy[:, 0]/0.004
+    result = np.zeros((4, n))
+    raw = np.zeros_like(result)
+    error = np.zeros_like(result)
+    stable = np.zeros_like(result)
+    incident_edges = [[] for _ in range(n)]
+    incident_triangles = [[] for _ in range(n)]
+    for ti, tri in enumerate(triangles):
+        for node in tri:
+            incident_triangles[int(node)].append(ti)
+    for ei, (i, j) in enumerate(edges):
+        incident_edges[int(i)].append((ei, int(j)))
+        incident_edges[int(j)].append((ei, int(i)))
+    for power in range(4):
+        f = xx**power
+        delta = f[edges[:, 0]]-f[edges[:, 1]]
+        flux = w*delta
+        geometric = np.zeros(n)
+        for k, sign in ((0, 1), (1, -1)):
+            np.add.at(raw[power], edges[:, k], sign*flux)
+            np.add.at(geometric, edges[:, k], sign*gw*delta)
+            np.add.at(error[power], edges[:, k], np.abs((w-gw)*delta))
+        result[power] = raw[power]/nv
+        error[power] = error[power]/nv + np.abs(geometric*(1/nv-1/gv))
+        for node, inc in enumerate(incident_edges):
+            stable[power, node] = math.fsum(float(w[ei]*(f[node]-f[j])) for ei, j in inc)/nv[node]
+    groups = {}
+    for node, x in enumerate(xy[:, 0]):
+        groups.setdefault(float(x), []).append(node)
+    xmin, xmax, ymin, ymax = xy[:,0].min(), xy[:,0].max(), xy[:,1].min(), xy[:,1].max()
+    classes = np.where((xy[:,0] == xmin)|(xy[:,0] == xmax), 2, np.where((xy[:,1] == ymin)|(xy[:,1] == ymax), 1, 0))
+    candidates = sorted(x for x, nodes in groups.items() if abs(x) <= 0.2e-4 and sum(classes[i] == 0 for i in nodes) >= 2)
+    if not candidates:
+        return {'verdict': 'NOT_MEASURED', 'weight_rel':wr, 'local_volume_rel':vr}, {'actions':result, 'raw_actions':raw, 'stable_actions':stable, 'node_class':classes}
+    chosen = [candidates[i] for i in sorted(set(np.linspace(0, len(candidates)-1, min(12,len(candidates)), dtype=int).tolist()))]
+    witnesses = []
+    for x in chosen:
+        nodes = sorted(groups[x], key=lambda i:xy[i,1])
+        interior = [i for i in nodes if classes[i] == 0]
+        pairs = [(interior[0], interior[len(interior)//2]), (interior[0],interior[-1]), (nodes[0],interior[0]), (interior[-1],nodes[-1])]
+        exact = {i: exact_row(i, xy, triangles, incident_triangles) for pair in pairs for i in pair}
+        for i, j in pairs:
+            if i == j:
+                continue
+            differences = {key:exact[i].get(key,F(0))-exact[j].get(key,F(0)) for key in set(exact[i])|set(exact[j])}
+            structural = any(v != 0 for v in differences.values())
+            for power in range(4):
+                diff = abs(float(stable[power,i]-stable[power,j]))
+                scale = float(max(operator_scale[i], operator_scale[j]))
+                uncertainty = float(error[power,i]+error[power,j])
+                witnesses.append({'nodes':[i,j], 'classes':[int(classes[i]),int(classes[j])], 'x_cm':x, 'power':power,
+                                  'difference':diff, 'scale':scale, 'geometry_discrepancy_bound':uncertainty,
+                                  'exact_projected_row_nonzero':structural,
+                                  'exact_row_difference':{str(k):str(v) for k,v in differences.items() if v != 0},
+                                  'verdict':classify(diff,scale,uncertainty,structural)})
+    verdict = 'NONINVARIANCE_WITNESS' if any(v['verdict']=='NONINVARIANCE_WITNESS' for v in witnesses) else 'INCONCLUSIVE'
+    return {'verdict':verdict,'weight_rel':wr,'local_volume_rel':vr,'witnesses':witnesses,
+            'float_vs_fsum_max':float(np.max(np.abs(result-stable))),
+            'y_spread_max':[float(max(np.ptp(result[k, nodes]) for x,nodes in groups.items() if x not in (xmin,xmax))) for k in range(4)]}, {
+                'actions':result,'raw_actions':raw,'stable_actions':stable,'node_class':classes}
diff --git a/docs/audits/2026-10-02-e6na-import-reduction/run_e6na.py b/docs/audits/2026-10-02-e6na-import-reduction/run_e6na.py
new file mode 100644
index 0000000..3404159
--- /dev/null
+++ b/docs/audits/2026-10-02-e6na-import-reduction/run_e6na.py
@@ -0,0 +1,202 @@
+"""원격 공식 import-only 감사. 엔진 변경 및 실제 solve 금지."""
+import hashlib
+import importlib.util
+import inspect
+import json
+import os
+import sys
+import time
+import subprocess
+from pathlib import Path
+from unittest.mock import patch
+
+import numpy as np
+
+HERE = Path(__file__).resolve().parent
+ROOT = HERE.parents[2]
+M_DIR = ROOT/'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency'
+sys.path.insert(0,str(ROOT))
+sys.path.insert(0,str(M_DIR/'scripts'))
+import e6m_metrics as M
+from diagnostics import analyze, validate
+
+PLAN_SHA = 'a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103'
+INPUT_SHAS = {
+    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py':'47ce559e56e32d9d7214cc0ca30a0a360ba485e7661817e3b992725409448a9b',
+    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json':'5b7225e949c6f41bbd72bd73e8d4ea54f88b937221f52618b03cdec21c038f6f',
+    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md':'e51caf5218ba725b99a918c16501e725c62ae87fa389ad28f6ef29c06ebce1c0',
+    'tcad/device/devsim/mesh_refine.py':'8973c358aca2e0173918b33117006dc638f37f8c68d8dc922c573c257b50f5e0',
+    'tcad/device/devsim/mesh_import.py':'0fe7c71d6594db777d038907a52067ad13b99b868f094758f196d0bbbfe721a8',
+    'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz':'65c1a938a6521a14897ed2ec2dfc04178e254248e5a2778f9e0b7d1a56e1c8e2'}
+
+
+def preflight(callback, path=None):
+    try:
+        digest = hashlib.sha256((HERE/'PLAN.md' if path is None else path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
+    except OSError as exc:
+        raise ValueError('PLAN_PREFLIGHT_BLOCKED: missing') from exc
+    if digest != PLAN_SHA:
+        raise ValueError('PLAN_PREFLIGHT_BLOCKED: mismatch')
+    return callback()
+
+
+def load(name, path):
+    spec = importlib.util.spec_from_file_location(name,path)
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+def sha(path):
+    return hashlib.sha256(path.read_bytes()).hexdigest()
+
+
+def require_inputs():
+    """문자 파일 예상 해시는 LF 정규화, npz 예상 해시는 원시 바이트 기준."""
+    for relative,expected in INPUT_SHAS.items():
+        data=(ROOT/relative).read_bytes()
+        if not relative.endswith('.npz'):
+            data=data.replace(b'\r\n',b'\n')
+        if hashlib.sha256(data).hexdigest()!=expected:
+            raise ValueError('INPUT_PREFLIGHT_BLOCKED: '+relative)
+
+
+def execute():
+    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
+        raise RuntimeError('REMOTE_ONLY')
+    require_inputs()
+    if subprocess.run(['git','diff','--quiet','ffa7e4a8872cd914e42066b1b1742312883c8dda','HEAD','--','tcad','tests','tcad_2d_stagewise.py'],cwd=ROOT).returncode != 0:
+        raise ValueError('PRODUCTION_OR_TEST_SOURCE_CHANGED')
+    from tcad.device.devsim import backend
+    dv = backend.require_devsim()
+    from devsim.python_packages import simple_physics
+    out = ROOT/'e6na_out'
+    out.mkdir(exist_ok=False)
+    report = {'plan_sha':PLAN_SHA,'source_sha':os.environ.get('GITHUB_SHA'), 'solve_attempts':0,'levels':{},'pn':'NOT_RUN',
+              'installed_simple_physics_sha':hashlib.sha256(inspect.getsource(simple_physics).encode()).hexdigest(),
+              'official_flux_source_matches':all(s in inspect.getsource(simple_physics.CreateSiliconPotentialOnly) for s in ('(Potential@n0-Potential@n1)*EdgeInverseLength','Permittivity * ElectricField')),
+              'precision':{}}
+    for key in ('extended_model','extended_equation'):
+        try:
+            report['precision'][key]=dv.get_parameter(name=key)
+        except Exception:
+            report['precision'][key]='NOT_RECORDED'
+    import importlib.metadata
+    report['versions']={k:importlib.metadata.version(k) for k in ('devsim','ViennaPS','numpy','meshio')}
+    input_paths=[M_DIR/'e6n_geometry_preflight.py',M_DIR/'e6n_geometry_result.json',M_DIR/'GEOMETRY_DESIGN_RULE.md',
+                 ROOT/'tcad/device/devsim/mesh_refine.py',ROOT/'tcad/device/devsim/mesh_import.py',
+                 ROOT/'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz']
+    report['inputs']={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in input_paths}
+    R=load('e6na_existing_builder',input_paths[3])
+    C=load('e6na_existing_conformity',ROOT/'docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py')
+    T=load('e6na_import_helpers',ROOT/'tests/integration/test_pn_2d_1d_consistency_real.py')
+    from tcad.device.devsim.mesh_import import import_process_result
+    from tcad.mesh.viennaps_adapter import build_process_result
+    if dv.get_device_list() or dv.get_mesh_list():
+        raise RuntimeError('PREEXISTING_ENGINE_OBJECTS')
+    old_solve=dv.solve
+    def forbidden(*args,**kwargs):
+        report['solve_attempts']+=1
+        raise RuntimeError('SOLVE_FORBIDDEN')
+    dv.solve=forbidden
+    ref=np.load(input_paths[-1])
+    t0=time.monotonic()
+    byte_budget=0
+    failed=False
+    try:
+        for lv,ny,nn,nt in zip(M.LEVELS,(16,32,64),(8037,31173,122761),(15264,60736,242304)):
+            started=time.monotonic()
+            rec=report['levels'][lv]={'status':'STARTED'}
+            name='e6na_'+lv
+            mesh=name+'_mesh'
+            try:
+                x1=M.e6k_snapshot(ref,lv,'rev',0.0)['x']
+                with patch.object(M,'Y_LINES_UM',np.linspace(-M.H_UM,0,ny+1).tolist()):
+                    p,t=M.build_mesh(x1)
+                p,t,tags,_=R.structured_lateral_refine(p,t,np.zeros(len(t),dtype=np.int32),[0.],[0.1])
+                assert (len(p),len(t))==(nn,nt)
+                conf=C.check_conformity(p,t)
+                geo=M.geometry_checks(p,t)
+                if not conf['pass'] or geo['obtuse_triangles'] or geo['degenerate_triangles'] or geo['area_rel_err']>1e-12:
+                    raise ValueError('PRE_IMPORT_GEOMETRY_FAIL')
+                rec.update(conformity=conf,geometry=geo,mesh_sha=hashlib.sha256(p.tobytes()+t.tobytes()).hexdigest())
+                path=T.write_mesh(p,t,lv)
+                result=build_process_result({'final_mesh':path,'snapshots':[]})
+                imported=import_process_result(result,mesh_name=mesh,device_name=name,contact_regions=['Si'],contact_axis='x',length_scale_to_cm=1e-4)
+                if imported.regions != ['Si']:
+                    raise ValueError('REGION_MISMATCH')
+                a={k:np.array(dv.get_node_model_values(device=name,region='Si',name=k)) for k in ('x','y','NodeVolume')}
+                a['xy']=np.column_stack((a.pop('x'),a.pop('y')))
+                a['triangles']=np.array(dv.get_element_node_list(device=name,region='Si'),dtype=np.int64)
+                for k in ('node_index','x','y'):
+                    dv.edge_from_node_model(device=name,region='Si',node_model=k)
+                a['edges']=np.column_stack([np.array(dv.get_edge_model_values(device=name,region='Si',name='node_index@n'+str(k)),dtype=np.int64) for k in (0,1)])
+                a.update({k:np.array(dv.get_edge_model_values(device=name,region='Si',name=k)) for k in ('EdgeCouple','EdgeLength')})
+                validate(a,report['solve_attempts'])
+                refpoints=p[:,:2]*1e-4
+                oo=np.lexsort((a['xy'][:,1],a['xy'][:,0]));rr=np.lexsort((refpoints[:,1],refpoints[:,0]))
+                if len(a['xy'])!=len(refpoints) or not np.all(np.abs(a['xy'][oo]-refpoints[rr]) <= [4e-15,1e-17]):
+                    raise ValueError('IMPORT_COORDINATE_MISMATCH')
+                mapping=np.empty(nn,dtype=np.int64);mapping[oo]=rr
+                canonical=lambda q:sorted(map(tuple,np.sort(q,axis=1).tolist()))
+                if canonical(mapping[a['triangles']]) != canonical(t):
+                    raise ValueError('IMPORT_CONNECTIVITY_MISMATCH')
+                if not imported.area_conservation['Si']['pass']:
+                    raise ValueError('IMPORT_AREA_FAIL')
+                contacts={}
+                for contact,xx in (('Si_xmin',-.002),('Si_xmax',.002)):
+                    ids=T.nodes_of_contact(dv,name,contact)
+                    expected=np.flatnonzero(a['xy'][:,0]==xx).tolist()
+                    if ids!=expected:
+                        raise ValueError('CONTACT_NODE_MISMATCH')
+                    contacts[contact]=ids
+                    a[contact]=np.array(ids,dtype=np.int64)
+                diagnostic,arrays=analyze(a)
+                a.update(arrays,source_points_um=p,source_triangles=t)
+                rec.update(diagnostic=diagnostic,contacts=contacts,area_gate=imported.area_conservation['Si'])
+                size=sum(v.nbytes for v in a.values())
+                byte_budget+=size
+                if size>120*1024**2 or byte_budget>200*1024**2:
+                    raise ValueError('OUTPUT_RESOURCE_CAP')
+                if time.monotonic()-started>600 or time.monotonic()-t0>1800:
+                    raise ValueError('WALL_RESOURCE_CAP')
+                import ctypes
+                class Memory(ctypes.Structure):
+                    _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
+                mem=Memory();mem.cb=ctypes.sizeof(mem)
+                if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(mem),mem.cb):
+                    raise RuntimeError('MEMORY_METRIC_UNAVAILABLE')
+                if mem.peak_ws>6*1024**3:
+                    raise ValueError('MEMORY_RESOURCE_CAP')
+                rec.update(raw_bytes=size,peak_working_set=mem.peak_ws)
+                np.savez_compressed(out/(lv+'.npz'),**a)
+                rec['array_sha']=sha(out/(lv+'.npz'))
+                rec['status']='IMPORT_PASS'
+            except Exception as exc:
+                rec.update(status='FAIL',error_type=type(exc).__name__,error=str(exc))
+                failed=True
+            finally:
+                if name in dv.get_device_list():
+                    dv.delete_device(device=name)
+                if mesh in dv.get_mesh_list():
+                    dv.delete_mesh(mesh=mesh)
+                rec['duration_s']=time.monotonic()-started
+                rec['cleanup_ok']=not dv.get_device_list() and not dv.get_mesh_list()
+                if not rec['cleanup_ok']:
+                    failed=True
+                (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
+            if failed or report['solve_attempts'] or rec['diagnostic']['verdict']!='NONINVARIANCE_WITNESS':
+                break
+        for lv in M.LEVELS:
+            report['levels'].setdefault(lv,{'status':'NOT_RUN'})
+        report['execution_status']='FAIL' if failed or report['solve_attempts'] else 'COMPLETED'
+        report['verdict']='FAIL' if failed or report['solve_attempts'] else ('NONINVARIANCE_WITNESS' if all(report['levels'][lv].get('diagnostic',{}).get('verdict')=='NONINVARIANCE_WITNESS' for lv in M.LEVELS) else 'INCONCLUSIVE')
+    finally:
+        dv.solve=old_solve
+        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
+    print(json.dumps({k:report[k] for k in ('execution_status','verdict','solve_attempts')},indent=2))
+    return int(failed or report['solve_attempts']>0)
+
+
+if __name__=='__main__':
+    sys.exit(preflight(execute))
diff --git a/docs/audits/2026-10-02-e6na-import-reduction/test_contract.py b/docs/audits/2026-10-02-e6na-import-reduction/test_contract.py
new file mode 100644
index 0000000..e4879a0
--- /dev/null
+++ b/docs/audits/2026-10-02-e6na-import-reduction/test_contract.py
@@ -0,0 +1,71 @@
+"""엔진 없는 E6N-A 실행 경계와 합성 반례."""
+import sys
+from pathlib import Path
+from unittest.mock import Mock,patch
+
+import numpy as np
+import diagnostics as D
+import run_e6na as R
+
+
+def reject(fn):
+    try:
+        fn()
+    except ValueError:
+        return
+    raise AssertionError('false PASS')
+
+
+def main():
+    plan=(R.HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')
+    for value in (b'wrong',None):
+        callback=Mock()
+        kwargs={'return_value':value} if value is not None else {'side_effect':FileNotFoundError()}
+        with patch.object(Path,'read_bytes',**kwargs):
+            reject(lambda:R.preflight(callback))
+        callback.assert_not_called()
+    for value in (plan,plan.replace(b'\n',b'\r\n')):
+        callback=Mock(return_value='OK')
+        with patch.object(Path,'read_bytes',return_value=value):
+            assert R.preflight(callback)=='OK'
+        callback.assert_called_once()
+    R.require_inputs()
+    paths=list(R.INPUT_SHAS)
+    fixture={str(R.ROOT/p):(R.ROOT/p).read_bytes() for p in paths}
+    for kind in ('LF','CRLF'):
+        def read(path):
+            value=fixture[str(path)]
+            if path.suffix!='.npz':
+                value=value.replace(b'\r\n',b'\n')
+                if kind=='CRLF':
+                    value=value.replace(b'\n',b'\r\n')
+            return value
+        with patch.object(Path,'read_bytes',read):
+            R.require_inputs()
+    with patch.object(Path,'read_bytes',return_value=b'changed'):
+        reject(R.require_inputs)
+    xy=np.array([[-.002,-1e-5],[.002,-1e-5],[-.002,0],[.002,0]])
+    tri=np.array([[0,1,2],[1,3,2]],dtype=np.int64)
+    edges=np.array(sorted({tuple(sorted((int(t[i]),int(t[(i+1)%3])))) for t in tri for i in range(3)}),dtype=np.int64)
+    w,v=D.geometry_weights(xy,tri,edges)
+    length=np.linalg.norm(xy[edges[:,0]]-xy[edges[:,1]],axis=1)
+    a=dict(xy=xy,triangles=tri,edges=edges,NodeVolume=v,EdgeLength=length,EdgeCouple=w*length)
+    D.validate(a)
+    for key in ('NodeVolume','EdgeCouple'):
+        b=dict(a);b.pop(key)
+        reject(lambda:D.validate(b))
+    b=dict(a);b['edges']=edges.copy();b['edges'][0,0]=4
+    reject(lambda:D.validate(b))
+    reject(lambda:D.validate(a,solve_attempts=1))
+    reject(lambda:D.validate(a,omitted=True))
+    assert D.analyze(a)[0]['verdict']=='NOT_MEASURED'
+    assert D.classify(0,1,0,True)=='INCONCLUSIVE' # stencil-only
+    assert D.classify(1e-14,1,1e-14,True)=='INCONCLUSIVE' # roundoff-only
+    assert D.classify(1,1,0,False)=='INCONCLUSIVE' # no geometry witness
+    assert D.classify(1,1,0,True)=='NONINVARIANCE_WITNESS'
+    assert not any(k in sys.modules for k in ('devsim','viennaps'))
+    print('E6N-A synthetic/preflight PASS; actual engine imports=0, solve=0')
+
+
+if __name__=='__main__':
+    main()
diff --git a/remote/profiles.py b/remote/profiles.py
index e22640c..71ad7df 100644
--- a/remote/profiles.py
+++ b/remote/profiles.py
@@ -13,0 +14,22 @@ PROFILES = {
+    "e6na_import_reduction": {
+        "description": "E6N-A fixed-plan official import and discrete reduction diagnostics; no solve calls permitted.",
+        "entry": "docs/audits/2026-10-02-e6na-import-reduction/run_e6na.py",
+        "args": [], "params": {}, "timeout_s": 1800,
+        "inputs": [
+            "docs/audits/2026-10-02-e6na-import-reduction/PLAN.md",
+            "docs/audits/2026-10-02-e6na-import-reduction/run_e6na.py",
+            "docs/audits/2026-10-02-e6na-import-reduction/diagnostics.py",
+            "docs/audits/2026-10-02-e6na-import-reduction/test_contract.py",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/e6m_metrics.py",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py",
+            "tests/integration/test_pn_2d_1d_consistency_real.py",
+            "tcad/device/devsim/mesh_refine.py",
+            "tcad/device/devsim/mesh_import.py",
+            "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py",
+            "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz"
+        ],
+        "outputs": [{"glob": "e6na_out/**/*", "max_mb": 120}],
+        "regenerate": "Only rerun after explicit approval; no solve permitted.",
+    },
diff --git a/remote/request.json b/remote/request.json
index 8677460..c7bc5bd 100644
--- a/remote/request.json
+++ b/remote/request.json
@@ -3,2 +3,2 @@
- "request_id": "e6m-pn-2d-1d-001",
- "profile": "e6m_pn_2d_1d_consistency",
+ "request_id": "e6na-import-reduction-001",
+ "profile": "e6na_import_reduction",
@@ -6 +6 @@
- "note": "E6M 2D-1D PN consistency audit. PLAN committed alone in 7f4ebbe before any solve. 42 solves planned, one run. No production gate change, no full regression, no 1D re-run."
+ "note": "E6N-A import-only diagnostics. PLAN fixed in f9ddff7. Solve calls forbidden; N0 inconclusive/failure stops later levels. No gate or production change."
```
