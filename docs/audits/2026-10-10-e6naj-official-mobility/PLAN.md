# E6N-AJ 공식 Klaassen 모델 입력 범위 조사

## 목적과 금지

현재 고정 이동도 모델을 대체하기 전에 설치된 DEVSIM 2.11.0의 공식 `python_packages.Klaassen` helper가 정확한 zero Donors/Acceptors를 처리하는지 조사한다. 이 단계는 SYNTHETIC_MODEL_INPUT_ONLY 모델 평가다. canonical 상태·실제 공정·device 전류·calibration·PN 정확성 승인이 아니다.

production/test/물리 게이트와 엔진 내부 코드를 수정하지 않는다. epsilon/floor/가짜 dopant, 식 재작성, 실패 은폐, 새 remesher를 금지한다. solve 시도는 0회로 trap한다. 모든 실제 DEVSIM 호출은 GitHub-hosted Windows에서만 한다. ViennaPS는 필요 없고 import하지 않는다.

## 출처

공식 소스: https://github.com/devsim/devsim/blob/main/python_packages/Klaassen.py
공식 simple_physics의 `CreateSiliconDriftDiffusion(..., mu_n, mu_p)`는 edge model 이름을 받는다. 이번에는 DD 방정식을 만들거나 풀지 않는다.

Klaassen 1992 Part I, DOI 10.1016/0038-1101(92)90325-7은 donor/acceptor/carrier/T 의존 이동도 모델이다. 이번에 논문 초록/메타데이터와 공식 구현을 읽었으며, 전체 논문의 파라미터 calibration을 완료했다고 주장하지 않는다. 설치 helper 기본 계수의 주석은 donor As, acceptor B다. 임의 species를 같은 것으로 취급하지 않는다.

## 고정 matrix

모든 케이스는 T=300K, ni=1e10 cm^-3, 축 정렬 1um 정사각형 2개 직각삼각형/4노드/5edge다. 공개 create_gmsh_mesh/add_gmsh_region/finalize_mesh/create_device를 사용한다. 접점·solve·공정은 없다.

1. PURE_N: Donors=1e16, Acceptors=0, Electrons=1e16, Holes=1e4.
2. PURE_P: Donors=0, Acceptors=5e15, Electrons=2e4, Holes=5e15.
3. INTRINSIC: Donors=Acceptors=0, Electrons=Holes=1e10.
4. BOTH_POSITIVE_CONTROL: Donors=1e16, Acceptors=1e15; n=(9e15+sqrt((9e15)^2+4e20))/2, p=1e20/n. 이는 helper 모델의 합성 입력이며 production compensation 게이트를 우회하는 device가 아니다.

각 케이스 독립 subprocess 45초; 전체 profile 240초. 기존 대규모 회귀와 장시간 PN solve는 중복 실행하지 않는다.

## 실행 기록

Set_Mobility_Parameters와 Klaassen_Mobility를 그대로 호출한다. 설치된 helper source SHA/LF SHA 및 DEVSIM 버전을 기록한다. 실제 set_node_values 입력 배열을 readback하여 원래 zero가 그대로인지 확인한다.

Z_D/Z_A, mu_bulk_e_Node/mu_bulk_h_Node와 edge mu_bulk_e/mu_bulk_h를 각각 get_*_model_values로 읽는다. 모델 생성 중 오류와 값 평가 오류를 분리하고 오류는 수정 없이 남긴다. 성공 평가 배열은 모든 노드/edge가 유한 양수일 때만 NUMERIC_EVALUABLE로 판정한다. 균일 입력의 edge geometric mean과 node 이동도의 일치는 float64 반올림 16 ulp 이내로만 비교한다(물리 calibration tolerance가 아님).

device cleanup, solve 시도 0, 원래 zero 보존은 필수다. helper 실패는 CAPABILITY_UNAVAILABLE 판정으로 허용하지만 evidence 누락/실행 오류/cleanup 실패/solve 시도는 검증 실패다. BOTH_POSITIVE_CONTROL은 정상 평가가 필수다. zero 입력 케이스도 처음부터 성공으로 가정하지 않는다.

## 완료 판정

4개 결과 모두 입력/source/오류/cleanup/solve 기록을 가져야 한다. 원격 source와 출력 해시를 독립 대조한다. 성공은 API 모델 평가 가능성일 뿐이다. 실패하면 기본 모델 변경 없이 원인과 다음 지원 조건을 제출한다.
