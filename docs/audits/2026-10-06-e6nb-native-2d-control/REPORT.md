# E6N-B 결과 — 실제 native 2D 연산과 해석해 수렴 검증

## 결론

`NATIVE_2D_CONTROL_PASS`와 `MMS_2D_NUMERICAL_PASS`를 확인했다. 이는 공식 DEVSIM API를 사용하는 이 감사의 2D scalar Poisson 수치 검증이다. 실제 PN/DD 전류, 임의 제조 공정, WaferState 전달, 생산 GUI 전체의 물리 정확성을 승인한 결과는 아니다.

기존 E6N-A의 N0 INCONCLUSIVE 및 N1/N2 NOT_RUN은 변경하지 않았다. 새로운 독립 양성 대조군과 manufactured solution으로 판정기의 실제 native 양성 경로를 확인했다. 이전 PN gate는 모두 유지한다.

## 사전 고정과 근거

PLAN 단독 커밋 cc96611, LF-normalized SHA e126a3adc89b9c9b10a68908f5c4e28ade12a521eb75d50697cb9c87d32dc1a3. 기하·함수·접점·solver 설정·수렴 문턱을 native 실행 전에 고정했다.

[공식 DEVSIM Manual 2.11.0](https://devsim.net/models.html)의 control-volume / equation assembly 계약을 확인했다. EdgeCouple은 edge flux의 적분 가중치이고 NodeVolume은 node source의 적분 가중치다. flux에는 Potential 차이 / EdgeLength만 넣었다. 엔진 내부 코드, native 가중치 또는 기존 semiconductor 모델을 변경하지 않았다.

해석식은 sin(pi*x/Lx)*cos(pi*y/Ly), source는 독립 연속 미분으로 얻은 -K*phi이다. 좌우 phi=0, 위아래 zero flux를 사용했다. coefficient=1로 정규화한 PDE 검증이며 실제 Si dopant/space-charge 계산이나 자연적으로 생성된 웨이퍼 결과가 아니다. 이산 residual로 source를 만들어 정확 해를 강제로 재현하지 않았다.

## 원격 실행과 발견/수정

1. 첫 실행: [37420199258](https://github.com/tjrgns1753-create/tcad/actions/runs/37420199258), source d446b93643b0b11d25f2185221bc0386344b49ce, artifact remote-run-37. 실제4회 solve 성공, 사전 기준 통과. Source는 요청 배열만 보존해 native 입력 snapshot은 NOT_RECORDED이었다.
2. 원본 artifact와 독립 분석은 유지했다. SNAPSHOT_CORRECTION을 작성하고 실제 모델의 Source와 Flux를 공식 getter로 읽도록 보완했다. 기존 수렴 문턱은 불변.
3. 최종 실행: [37420757648](https://github.com/tjrgns1753-create/tcad/actions/runs/37420757648), source 0c37e56a52563d67fd44386ace189c4eaa7cd139, artifact remote-run-38. 4회 attempt,4회 success, solve/snapshot failure0. 실제 Source는 요청 source와 array_equal, 실제 Flux도 독립 Potential 차이 / EdgeLength 기준 통과.

이번 두 실행 합계 실제 Poisson solve는8회다. PN solve는0회다. 양성/음성 기하 대조군 단계는 solve trap으로0호출을 강제했다.

## 실제 수치 결과

양성 대조군의 두 지정 node 작용: -125000.0 / -132352.9411764706 cm^-2. 독립 손계산 -125000 / -2250000/17과 일치했다. native 진단 NONINVARIANCE_WITNESS, tensor 음성 대조군 INCONCLUSIVE.

| mesh | triangle | L_inf error (V) | weighted L2 (V) | L_inf rate |
|---|---:|---:|---:|---:|
| M0 |26|0.2153585236|0.0850774301|—|
| M1 |104|0.0491603738|0.0189024016|2.13117|
| M2 |416|0.0120171787|0.0045788768|2.03240|
| M3 |1664|0.0029869777|0.0011354767|2.00834|

weighted L2 rates 2.17021 / 2.04550 / 2.01170. 마지막 두 구간은 사전 최소1.5를 통과했다. 최종 L_inf<0.01V. native discrete residual relative의 최댓값은 약1.02e-15, 접점 오차0V, 중심 x열 y spread 약2.0038V. x만의 해로 통과한 사례가 아니다.

동일한 domain/contact에서 기존 _refine_once ALL-red branch만 재사용했다. 신규 remesher 없음. h_max는 매 단계 절반, conformity·면적·비둔각 검사 통과. green branch 국소성 또는 임의 mesh 지원을 승인하지 않는다.

## 독립 검증과 false-green 방지

로컬 verifier는 native 엔진을 import하지 않고15개 산출물과 run.log 해시를 대조했다. omitted_outputs=[], log_truncated=False. 실행 source는 summary가 아닌 독립 GitHub 확인 SHA를 입력으로 받아 대조했다.

native 기하 arrays에서 positive/tensor diagnostics를 다시 계산해 dict와 arrays가 동일한지 확인했다. MMS의 해석식/source/error를 재계산하고 math.fsum으로 discrete residual과 weighted L2를 독립 계산해 같은 최종 판정을 얻었다. 실제 Source/Flux snapshot도 직접 비교했다.

native get_element_node_list는 일관된 winding을 전제로 읽으면 안 된다. 처음 verifier의 기하 검사에서 정상 native 목록이 잘못 거부된 것을 발견하고 diagnostic copy만 CCW로 정렬했다. 원본 배열·connectivity·engine mesh는 수정하지 않았다. 이를 PN 또는 기하 수정으로 표현하지 않는다.

정상 artifact 통과 + 변조 반례10개 차단: omitted 출력, source SHA 충돌, PLAN 충돌, bool 호출 횟수, NaN 오차, snapshot failure, geometry 누락, 잘못된 hash, raw array 누락, 외부 expected source 충돌. 의미 충돌 반례는 외부 output hash를 일부러 갱신한 뒤에도 차단됐다. 이후 native snapshot 누락/False를 차단하는 계약 테스트도 통과했다.

## 원시 증거와 상태

두 원격 artifact를 raw/ 아래 바이트 그대로 보존했다(-text -diff). 최신 result.json SHA fa8c0a5b18ba2874916338d477b7f3bf45cd134100dc2de86802685acaf9e828. M3.npz SHA 04c2a9e2cbea180793c3b6baedc1c5b892af78a3b78555c0820b681d5a1fb169.

INDEPENDENT_RESULT_V1 / V2에 각각 별도 분석을 보존한다. v1의 native Source 기록 부재를 소급 고치지 않았다. v2는 NATIVE_VERIFIED이다.

production tcad/·tests/·GUI 변경0, 엔진 내부 변경0, 기존 gate 변경0. 변경은 감사 스크립트/계약/원격 profile/request/보고서/원시 증거에 한정한다. 전체 회귀/main 병합 없음. sampled working-set 감독은 주기 관측이며 순간 할당의 하드 메모리 상한이 아니다.

## 다음 물리 검증의 의미

이제 'DEVSIM이 2D 방정식을 다루는가 / 이번 메쉬에서 scalar Poisson이 해석해로 수렴하는가'에 실제 긍정 증거가 있다. 그러나 nonlinear semiconductor Poisson, SG carrier continuity, PN I-V, 활성 도핑 보존과 제조 공정 조합은 별도 검증 대상이다.

x/y에 무관한 물리 입력이 1D 해로 환원되는 것은 그 자체가 물리 버그가 아니다. 따라서 다음 PN 설계에서는 1D 대조군의 역할과 진짜 2D 물리 실험의 역할을 분리한다. 물리 대칭성이 있는 문제에서 메쉬 비환원성을 유일한 승인 조건으로 요구하지 않는다. 그렇더라도 이번 scalar 결과로 STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED gate를 자동 해제하지 않는다.
