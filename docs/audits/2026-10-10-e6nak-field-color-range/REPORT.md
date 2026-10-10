# E6N-AK 실제 색 범위의 정직한 표시

## 수정과 반례

수정 전 `1e16`과 `1e16+2`가 둘 다 `1.0000e+16`으로 표시되는 반례를 실제 production caption으로 재현했다. 이후 양 끝을 `.17g`로 표시하고 Δ/상대 범위 및 자동 색 확대의 유의성 미보장 설명을 추가했다. 원시 Potential은 상대 범위의 기준 전위 의존도 명시한다.

색, 원시 값, 노드, 좌표, 방정식 및 gate는 바꾸지 않는다. numerical noise를 threshold로 지우거나 물리적으로 의미 있다고 판정하지 않는다. 균일 carrier는 `Δ=0`으로 표시된다.

## 실제 검증

PLAN LF SHA `17bbb79400f32fa55b79cbc0dc71cf053cd2d4940858c40697f3d082ade7c80d`; source `5c53b146c13044e14b1cc5c0d304d12a53fcaa0c`.

원격 run https://github.com/tjrgns1753-create/tcad/actions/runs/38058145706 — 11.208초, unit 4개 + real integration 2개 = 6개 PASS. 전류/물성 실제 대조군을 재확인했고 필드 9개 층의 배열/색/좌표 불변 및 캡션의 실제 캔버스 완전 포함을 확인했다.

독립 검증기에서 원본 출력 18개, 모든 입력/source/log SHA를 대조했다. 캡션의 정확한 최소·최대·Δ·상대 범위 계산을 재검산했고 범위 누락/틀린 Δ/거짓 유의성/반올림 endpoint의 4개 변조를 차단했다. n형 Potential PNG를 직접 열어 실제 글자가 잘리지 않는 것을 확인했다.

production semantic 변경은 `node_fields.py::field_caption`뿐이다. 구현 전 94개 교차 회귀가 통과했고, 이번에는 관련 6개를 재검증했으며 전체 회귀를 다시 했다고 주장하지 않는다. 추가 solve나 값 재계산을 표시 과정에 넣지 않았다.

원본 `raw/remote-run-88/`를 변경하지 않는다. 모델 calibration 및 일반 TCAD 물리 승인 아님.
