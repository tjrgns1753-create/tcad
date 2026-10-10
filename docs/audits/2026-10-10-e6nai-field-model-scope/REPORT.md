# E6N-AI 실제 물리장 화면의 모델 범위 표시

## 판정

`ACTUAL_CANVAS_MODEL_SCOPE_VISIBLE` — 재료 calibration 또는 PN 검증 승인이 아니다.

## 구현

- `transport_evidence.py`: 기존 실제 파라미터 검증을 공유하는 `_record_values`와 짧은 `transport_model_scope`를 추가했다. 모델명/기록 상태를 검증한 후에만 고정 이동도·Boltzmann·SRH 및 calibration 미검증을 표시한다. 값 누락/NaN/잘못된 단위는 불완전 기록으로 표시한다.
- `node_fields.py::field_caption`: 공통 설명에 모델 범위 한 줄을 추가했다. 노드 배열, 색 계산, 좌표 변환, 전류, 방정식, 게이트는 바꾸지 않았다.
- 신규 unit은 실제 변경 전 캡션 누락을 재현했다. 신규 integration은 실제 Tk 캔버스 9개 층을 검사했다.

## 실제 실행과 독립 대조

- 사전 PLAN SHA: `c4cc6d1d42edae7f632cebd7d00b51898304d90373f4762251da21302b6e6d33`.
- 실행 SHA: `3641aa80cb14e121b622a023b694cb67985e6a43`.
- GitHub run: https://github.com/tjrgns1753-create/tcad/actions/runs/38057101920
- 192.744초, 94개 PASS, mandatory skip 0. 기존 88개 unit의 입력 해시와 PASS를 그대로 대조했다.
- n형/p형/known-undoped 각각 실제 solve 3회, 전위·전자·정공 9층, 각 126노드. 이전 필드 배열이 변하지 않았고 픽셀 좌표와 색이 원래 렌더링 계산과 일치한다.
- 캡션 bbox는 631×292 실제 캔버스 안에 포함된다. 9장 PNG가 실제 원격 데스크톱에서 저장됐다. n형 전위 PNG를 직접 열어 모델 한계 및 원시 Potential 설명이 보이고 잘리지 않음을 확인했다.
- 독립 검증기는 106개 출력 파일의 바이트 수/SHA, 입력 git blob/checkout 줄바꿈 SHA, 원시 실행 로그, 전체 94개 개별 결과/로그 해시를 대조했다.
- 누락 층, 거짓 calibration, 배열 변경, 잘린 캡션, 추가 solve의 5개 합성 변조는 모두 차단됐다.

## 물리적으로 말할 수 있는 범위

GUI가 표시하는 값은 현재 선택한 고정 이동도·Boltzmann·SRH 모델의 실제 계산 노드 값이다. 보간된 실제 측정 결과나 모든 공정/고농도/고전계의 실리콘 정확도를 보장하지 않는다. 화면 설명의 일치는 물리 모델 calibration 증거가 아니다.

양의 시간 산화, activation/anneal, compensation, 일반 2D step PN 게이트를 유지한다. DEVSIM/ViennaPS 내부 수정 및 main 병합은 없다. 실제 엔진/Tk 호출은 원격에서만 실행했다.

원본: `raw_initial/remote-run-86/`; 검증: `verify_artifact.py`. 원본 바이트는 수정하지 않는다.
