# E6N-AM 공식 carrier derivative 검사

## 결론

`PARTIAL_NUMERICAL_DERIVATIVE_EVIDENCE` — 64개 중 32개는 사전 step/budget에서 일치, 32개는 ROUND_OFF_LIMITED다. 불일치 0이 전체 미분 검증 완료를 뜻하지 않는다. DD/PN/재료 calibration 승인은 없다.

## 고정 기준 및 결과

PLAN LF SHA `461e774f1022a9b29b542ed579af34aad60603b1a4df1a33fad3669942b322e9`; source `81e0844df10c7c5ab765ad4ceaa983641a949c74`.

실제 run https://github.com/tjrgns1753-create/tcad/actions/runs/38058776477 — 1.330초. 공식 helper의 `mu_bulk_e_Node:Electrons/Holes` 및 `mu_bulk_h_Node:Electrons/Holes`를 4입력×4노드에서 확인했다. 공개 set_node_values로 한 carrier/node만 변화시켰으며 다른 node와 도핑은 고정하고 perturbation마다 원래 값을 복원했다.

고정 central difference 3개 step과 Richardson 비교 예산을 적용했다. 32개 CONSISTENT_AT_TESTED_STEPS, 32개 ROUND_OFF_LIMITED, NUMERICAL_DERIVATIVE_MISMATCH 0이다. 이 예산은 사전 수치 산술 비교법이지 엄밀한 오차 보장 또는 물리 tolerance가 아니다.

solve 시도 0, device 누수 0, 설치 helper source 바이트 불변. production/test 변경 0. Z_D/Z_A의 감사용 연속극한 표현은 AL과 동일하고 기본 모델을 바꾸지 않았다.

## 독립 검증

원본 출력 2개 및 실행 로그/입력 SHA를 대조했다. 64개 행의 case/model/carrier/node 조합이 정확하고 중복/누락이 없음을 확인했다. AL 원본의 carrier 입력·기준 이동도·설치 helper source SHA와 각 행을 직접 대조했다. 모든 차이와 예산 및 classification을 재계산했다.

누락 행/중복 행/거짓 일치/소스 변경/carrier 변경/solve 시도의 6개 변조를 차단했다. 합성 대조군에서도 일치·불일치·반올림 한계가 서로 구분되고 NaN/누락/틀린 step은 거부됐다.

## 다음 물리 조건

반올림 한계 32개는 아직 미검증이다. 이를 억지로 일치로 바꾸거나 epsilon/농도/계수/허용오차를 조정하지 않는다. 이후 독립 기준 계산이나 사전 등록된 더 잘 해상되는 차분 실험으로 보완할 수 있다. 실제 DD Jacobian, carrier-dependent edge current, species calibration, 온도/도핑 유효 범위 및 2D PN 수렴이 따로 필요하다.

원본 `raw/remote-run-90/`는 수정하지 않는다. 현재 GUI는 고정 이동도·Boltzmann·SRH 및 calibration 미검증이라는 실제 모델 범위를 명시한다.
