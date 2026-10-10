# E6N-AJ 공식 Klaassen helper 입력 한계

## 결론

`OFFICIAL_HELPER_ZERO_DOPANT_INPUT_UNAVAILABLE` — 공식 API가 있으므로 무조건 안전하게 재사용할 수 있다는 결론은 성립하지 않는다. 새 방정식 구현이나 엔진 내부 수정 대신 공개 helper를 그대로 시험했다.

DEVSIM 2.11.0의 설치된 `python_packages.Klaassen`에서 PURE_N은 `Z_A`의 `pow(Acceptors,-1)`, PURE_P은 `Z_D`의 `pow(Donors,-1)`, INTRINSIC은 둘 다 정확한 zero로 평가 오류를 낸다. 모델 생성은 완료되지만 node/edge 이동도 값 평가가 실패한다. BOTH_POSITIVE_CONTROL은 유한 양수 평가 및 node↔edge geometric mean 일치를 통과했다.

## 증거

- PLAN 별도 커밋 `7f98cd5`, LF SHA `43b43558a4949363af10b9b2801454a0ad1d061378a13d6715a2b63ed3534516`.
- 실행 SHA `d726b8c48bf6064521af09c204807818d716331f`, run https://github.com/tjrgns1753-create/tcad/actions/runs/38057859918
- 모델 평가 4개 독립 subprocess, 2.759초. 모든 입력 readback 동일, exact zero 유지, solve 시도 0, device 누수 0.
- `verify_artifact.py`가 원본 출력 10개와 실행 로그/input git blob SHA를 독립 대조했다. production 변경 0을 git diff로 확인했다.
- 엔진 없는 `selftest.py`: 정상/불가 기록 대조 및 누락/가짜 zero/추가 solve/NaN/변경 PLAN/오류 누락/edge 불일치/계수 변경/알 수 없는 생성 상태의 9개 변조를 차단했다.

## 문헌·모델 경계

공식 구현: https://github.com/devsim/devsim/blob/main/python_packages/Klaassen.py
Klaassen 1992 Part I, DOI 10.1016/0038-1101(92)90325-7은 불순물/carrier/T 의존 이동도 모델이다. 이번에는 초록/메타데이터와 공식 구현만 읽었다. 전체 논문 calibration 또는 모든 species 정확성 검증이 아니다. 설치 helper의 기본 계수 주석은 As/B이며 임의 dopant와 동일시할 수 없다.

현재 production은 고정 이동도 모델 그대로다. compensation 및 PN gate를 유지한다. 둘 다 양수인 합성 대조군의 평가는 production compensation 승인이나 실제 소자 결과가 아니다. 수치 helper 문제와 물리 모델의 유효 범위를 구분해야 한다.

원본 `raw/remote-run-87/`는 수정하지 않는다. 기본 모델 전환은 하지 않는다. exact-zero 식의 연속극한 처리와 공식 지원 방식·species calibration은 별도 검증 전까지 미승인이다.
