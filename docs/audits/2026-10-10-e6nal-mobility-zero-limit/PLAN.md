# E6N-AL 공식 이동도 식의 exact-zero 연속극한 후보

## 문제와 범위

E6N-AJ는 공식 Klaassen helper의 Z_D/Z_A에 존재하는 reciprocal zero 평가 오류를 실제로 확인했다. 엔진 내부를 바꾸거나 가짜 농도를 넣지 않는 해법을 감사 경로에서만 시험한다. production 모델/계수/도핑/gate는 그대로다.

기존 식 `1+1/(c+(Nref/D)^2)`는 D>0에서 `1+(D/Nref)^2/(1+c*(D/Nref)^2)`와 대수적으로 동일하다. Nref>0에서 후자는 D=0의 연속극한 1을 표현한다. 이 변경은 새로운 이동도 구성방정식이 아니라 기존 식의 제거 가능한 zero singularity를 피하는 평가 표현이다. 그러나 공식 helper 그대로는 아니므로 반드시 AUDIT_ONLY_CONTINUOUS_EXTENSION이라고 표기한다.

## 후보 구현 계약

공식 helper.Set_Mobility_Parameters 및 Klaassen_Mobility를 그대로 실행한 뒤 공개 devsim.node_model로 Z_D/Z_A 두 표현만 감사 device에 교체한다. 나머지 모델/미분/계수는 공식 생성 결과 그대로 쓴다. 엔진 소스/설치 파일 수정 0. zero input은 그대로 두고 floor/epsilon은 금지한다. 생산 캐리어/전류/PN/재료 calibration 승인이 아니다.

Z_D/Z_A는 Donors/Acceptors(고정 도핑)만 의존하여 공식 carrier derivatives에는 새 미분항이 없다. 실제 current helper가 아니라 모델 값 평가만 실행한다. solve 시도 0으로 trap한다.

## 결과 전 기준

1. 로컬 Decimal 80자리로 c_D=.21,Nref_D=4e20,c_A=.50,Nref_A=7.2e20 및 D=1e10/1e16/1e20/1e22의 positive 두 표현 상대 차이가 1e-70 이하인지 확인한다. 이는 대수 산술 검사이며 물리 tolerance가 아니다. D=0의 확장값은 정확히 1이어야 한다.
2. GitHub Windows에서 AJ의 4개 고정 입력을 각 독립 subprocess로 재평가한다. geometry/T/input/helper version 및 coefficients는 AJ와 동일하다. 공개 API 2개 Z model만 교체한다.
3. 모든 모델 값 유한 양수, node↔edge geometric mean 16 ulp 이내, exact-zero readback 동일, cleanup 0, solve 시도 0 필수. BOTH_POSITIVE_CONTROL의 Z_D/Z_A와 node/edge 이동도는 기존 AJ 원본 대비 128 ulp 이내(식 평가의 float64 산술 비교일 뿐 calibration 오차가 아니다).
4. 기존 공식 source SHA가 AJ와 동일해야 한다. 설치 소스 byte/LF hash를 기록한다. 원본 AJ는 읽기만 한다. 모든 getter 배열·오류를 저장한다.
5. 4개 subprocess 각 45초, 전체 240초. production 경로 통합 및 실제 DD solve는 금지한다. 실패하면 숨기지 않고 원본 및 후보를 비교 보고한다.

새 PLAN 단독 커밋 후 구현한다. 기존 PLAN/원본은 바꾸지 않는다. 결과가 좋아도 기본 모델 변경과 gate 해제는 하지 않는다.
