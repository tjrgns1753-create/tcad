# 실제 엔진 입력/flux snapshot 보완 — 원본 실행은 보존

첫 실행은 4회 Poisson solve와 수렴 기준을 통과했고 독립 residual도 통과했다. 그러나 NPZ Source는 요청한 manufactured source 배열이지 엔진 모델에서 다시 읽은 snapshot이 아니었다. 엔진에 실제로 쓰인 Source 모델의 값을 별도로 보존하지 않았다는 증거 범위 누락이다. 원본 결과를 native Source snapshot으로 소급 표현하지 않는다.

다음 실행은 같은 기하/함수/solver/수렴 문턱으로4회만 실행한다. Potential을 읽은 직후 공식 get_node_model_values(Source)와 get_edge_model_values(Flux)를 읽는다. native Source는 prescribed Source와 byte-equal(array_equal)이어야 한다. Native Flux는 독립 Potential 차이 / EdgeLength와 256eps*max(abs(expected flux)) 이내여야 한다. 이 새 문턱은 보수적 산술 대조 기준이며 엄밀한 엔진 roundoff 증명은 아니다.

Source와 PrescribedSource를 구분해 저장하고 NativeFlux도 저장한다. 해당 snapshot 또는 대조 실패는 snapshot_failures를 증가시키고 이후 mesh를 실행하지 않는다. schema2에서 source_verified=True / flux_verified=True가 없으면 승인하지 않는다. schema1의 과거 실행에는 native snapshot을 발명하지 않고 NOT_RECORDED로 유지한다.

이것은 물리 모델이나 결과 수렴 문턱을 바꾸는 보정이 아니라 실제 엔진 입력·출력을 읽어 증거 계약을 보완하는 변경이다. 원본 PLAN/첫 실행 artifact는 유지한다.
