# E6N-AM 공식 carrier derivative 독립 검사

## 범위

E6N-AL audit-only 연속극한의 실제 node mobility 값은 평가됐다. DD solver에 연결하기 전에 공식 helper의 carrier derivatives가 그 값의 변화와 일치하는지 조사한다. production/engine/계수/물리 gate는 바꾸지 않는다. 공개 모델 값 조회 및 set_node_values만 사용하며 solve 시도 0이다.

동일 4노드·2삼각형/300K 및 PURE_N/P/INTRINSIC/BOTH_POSITIVE_CONTROL 입력을 사용한다. 공식 helper 생성 후 Z_D/Z_A 두 개만 AL과 동일한 공개 node_model 식을 쓴다. source hash는 AL과 동일해야 한다.

## 사전 수치 기준

각 입력에서 mu_bulk_e_Node 및 mu_bulk_h_Node의 공식 derivative `:Electrons`/`:Holes`를 모든 4노드에서 조회한다. 각 carrier는 한 노드만 변화시키며 다른 값은 고정한다. 이동도는 국소 node 모델이므로 해당 노드의 central difference와 비교한다.

carrier 크기의 1e-3, 5e-4, 2.5e-4 세 step으로 central difference d1,d2,d3를 구하고 Richardson r1=(4d2-d1)/3,r2=(4d3-d2)/3를 계산한다. 사전 비교 예산은 8*abs(r2-r1)+64*ulp(max(abs(mu_plus),abs(mu_minus),abs(mu_base)))/(carrier*2.5e-4)다. 이는 절삭·반올림의 경험적 수치 비교 예산이며 엄밀한 오차 정리나 물리 tolerance라고 주장하지 않는다.

analytic derivative와 r2의 차이가 위 예산을 넘으면 NUMERICAL_DERIVATIVE_MISMATCH로 기록한다. 예산이 derivative/finite-difference 신호보다 크면 ROUND_OFF_LIMITED로 기록하여 일치 검증이라고 세지 않는다. 그렇지 않고 차이가 예산 안이면 CONSISTENT_AT_TESTED_STEPS다. derivative 자체의 finite 값·길이·모델 누락은 evidence failure다.

## 기록과 실행

4 입력×2 이동도×2 carrier×4노드=64개 비교를 저장한다. 각 derivative, step, mobility 값, difference, budget를 저장하고 각 perturbation 후 원래 입력을 복원한다. device cleanup 및 solve 시도 0 필수다. 어떤 불일치도 성공으로 바꾸지 않는다.

모든 엔진 import와 평가 GitHub-hosted Windows. local은 AST/판정기 합성만. 단일 profile 120초. 결과 전 PLAN 별도 커밋. 불일치가 있으면 원인 분석이지 production 수정을 허용하지 않는다. PN/전류/실제 재료 calibration 승인 아님.
