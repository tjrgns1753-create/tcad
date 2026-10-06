# E6N-A 실제 import 및 사후 분석 결과

## 판정

공식 DEVSIM import와 기하 가중치 대조는 첫 후보 N0(L0)에서 통과했다. 그러나 기존 PLAN의 이산 비환원성 판정은 INCONCLUSIVE이다. 실행 성공(RC=0)을 물리 검증 성공으로 표현하지 않는다. N1/N2(L1/L2)는 계약대로 NOT_RUN, PN은 NOT_RUN, solve_attempts=0이다.

## 원격 실행

Actions: https://github.com/tjrgns1753-create/tcad/actions/runs/37419006613
source: 2cbb78fb44789c03b805885531edc0ee84de6b83. artifact: remote-run-36.
고정 PLAN SHA a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103 유지.

- 노드 8037, 삼각형 15264. 둔각·퇴화·hanging node 0, 경계와 면적 일치.
- 독립 기하 대조: edge weight 최대 상대오차 3.6856850930099756e-16, local volume 최대 상대오차 4.713606060825576e-16.
- NodeVolume 합과 삼각형 면적의 상대 차이 -1.1102230246251565e-16. 면적 gate의 uncertainty는 코드가 명시한 ASSUMED_BOUND이지 엔진 소스에서 증명된 엄밀 상한은 아니다.
- 좌우 접점 node 집합과 원본 connectivity 일치, cleanup_ok=True.
- 감독 종료 COMPLETED, 약 2.015초, sampled process-tree working-set 최대 122368000 bytes. 이는 주기 관측값이며 순간 peak의 엄밀 상한이 아니다.
- 원본 witness 비교 192개에서 exact projected-row 비영 차이 0. 공식 판정 INCONCLUSIVE 유지.

## 원시 증거 무결성

summary의 모든 output SHA와 run.log SHA를 다운로드한 artifact 바이트에 직접 대조했다. omitted_outputs=[], log_truncated=False.
L0.npz SHA 69ffbc42aea5c11fea0347c922d872bb0387c0c87934c2ed14af93eaeffa222b.
다운로드한 native 배열에 원본 diagnostics.analyze를 로컬에서 엔진 없이 다시 적용했다. 진단 dict는 원격 결과와 완전히 같았고 재계산한 네 출력 배열은 np.array_equal로 전부 일치했다. 원격 기록을 단순히 인용한 것뿐 아니라 판정 계산을 재현했다.
실행기 devsim 정보 NOT_IMPORTED는 공통 부모 조회를 생략했다는 의미다. 실제 후보 자식은 DEVSIM을 import했으며, 이 실행 전체를 엔진 import=0이라고 주장하지 않는다. solve_attempts=0은 실제 후보의 trap 기록이다.

summary의 오래된 review_sha(023bcb90)에 대한 비교 False는 숨기지 않는다. 실제 후보 진입점은 고정 production SHA ffa7e4a와 tcad/tests/GUI를 별도로 대조해 통과했다. 이번 작업 시작 509f5e5 이후 해당 production/test 파일 변경도 0이다.

## 별도 사후 조사 — 원본 승인으로 사용 금지

POSTHOC_ROW_PLAN을 별도로 작성한 뒤 저장 NPZ를 pure NumPy/Fraction으로 재분석했다. 새 엔진 import와 solve는 없다. 모든 비접점 x열에서 같은 class끼리 y순 첫 node와 나머지를 비교했다. strict interior와 boundary class는 분리했다.

774개 (x,class) group, 7229개 pair를 검사했다. exact projected-row 비영 차이는 84 pair였으나 동일 classifier의 네 polynomial 통과 수는 0이었다. first_posthoc_witness=null이다. 이 84개의 비영 차이가 새로운 물리 오류나 충분한 2D 효과라는 해석은 하지 않는다. 서로 다른 class의 모든 pair를 전수 조사한 결과는 아니다.

기존 최대 12열 witness만으로 모든 x함수 또는 모든 node pair의 불변성을 증명할 수 없다. 사후 결과 또한 PN 해·전류·수렴의 승인 자료가 아니다. 결과를 보고 원본 threshold나 PLAN을 바꾸지 않았다.

## 다음 단계와 현재 경계

자원/소스 계약/원격 환경의 실행 결함은 보완하고 실측 검증했다. 하지만 현재 고정 후보에서 다음 PN pilot을 승인할 충분한 이산 비환원성 증거는 얻지 못했다. 따라서 더 미세한 후보를 무작정 돌리거나 PN gate를 해제하지 않는다.

다음 물리 단계에는 진짜 2D 효과를 구분할 새 사전 실험 설계가 필요하다. geometry/domain/접점 변경은 기존 고정 입력을 바꾸므로 별도 스코프로 다뤄야 한다. 기존 엔진 내부, 가중치 override, tolerance 완화, 새 remesher를 이번 작업에서 도입하지 않았다.

전체 회귀·PN solve·main 병합·gate 해제 없음. 원본 PLAN/과거 증거는 그대로 보존한다.
