# E6N-AL 공식 이동도 식의 zero 연속극한 후보

## 판정

`AUDIT_ZERO_LIMIT_EVALUABLE` — production 또는 물리 calibration 승인이 아니다.

공식 helper의 `1+1/(c+(Nref/D)^2)` 대신 감사 device에서만 `1+(D/Nref)^2/(1+c*(D/Nref)^2)`를 공개 `devsim.node_model`로 설정했다. 두 식은 D>0에서 대수적으로 같고 D=0의 연속극한은 1이다. 가짜 dopant나 epsilon을 넣지 않았고 Z_D/Z_A 외 모델 및 계수는 공식 helper 그대로다.

## 사전 기준 및 실제 결과

- PLAN 별도 커밋 `3cf49bc`, LF SHA `092d7042ee87364d4e32a051a88cde090e73dc5d28f0ee20c2b060635eab586e`.
- source `02c9605679b244cf6cf51ed64607737ea109f441`, run https://github.com/tjrgns1753-create/tcad/actions/runs/38058384455
- 순수 Decimal 80자리의 양수 입력 8개 비교는 차이 0, 정확한 zero 극한 2개도 1이었다. 물리 tolerance가 아니라 표현의 산술 검사다.
- 4개 실제 원격 모델 평가 모두 유한 양수. node↔edge geometric mean 16 ulp, 기존 양수 대조군 node/edge/Z 값 128 ulp 이내를 통과했다. zero 입력 readback 그대로, Z=1 정확 일치, solve 시도 0, device 누수 0.
- 2.718초. 설치 helper SHA `56db2f9b612626a7859732e4bdedd644885fa510e50c5bafd88a31b921696f33`가 이전 AJ와 동일하다.
- 독립 검증으로 원본 출력 10개, 입력 및 로그 해시를 대조했다. zero 변조/거짓 후보 승인/추가 모델 교체/양수 모델 변화/소스 변경/solve 시도 6개 변조를 차단했다.

## 물리적 해석 및 남은 조건

이것은 공식 식의 평가 가능성 문제를 기존 식의 연속 표현으로 해결할 후보다. 새로운 empirical mobility 법칙을 발명한 것은 아니지만 공식 helper 무수정 실행과는 다르므로 반드시 audit-only로 구분한다.

전체 논문 파라미터 calibration, species 적합성, DD Jacobian/실제 전류/PN 메쉬 수렴은 미검증이다. 이 때문에 기본 모델은 여전히 고정 이동도다. compensation/PN/산화/activation gate를 그대로 유지한다. 공식 engine 소스 및 설치 파일은 변경하지 않았다.

원본 AJ 증거와 PLAN은 그대로다. AL 원본 `raw/remote-run-89/`는 수정하지 않는다.
