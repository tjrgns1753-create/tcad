# E6N-AI 물리장 화면의 모델 범위 표시

AH actual GUI/API/JSON 및92-file 회귀 통과 후 다음 bounded 작업.
로그만이 아니라 사용자가 보는 field canvas에서도 모델 한계를 알려야 한다.
새 방정식·도핑·mobility·tau·온도·gate는 변경하지 않는다.

## 결과 전 기준
1. field_caption의 현재 출력에는 물성 calibration 범위가 없음: 합성 fixture로
   기존 출력에 '재료 calibration 미검증'이 없는 반례를 확인한다.
2. 실제 transport metadata가 valid이면 짧은 공통 helper가 고정 이동도,
   Boltzmann, SRH, 실제 재료 calibration 미검증을 설명한다.
   missing/invalid 기록은 '물성 기록 미기록/불완전'이며 기본 물성값을 채우지 않는다.
   긴11개 parameter 나열은 로그/JSON에 유지, canvas는 짧은 한계만 표시한다.
3. field_caption만 모델 범위 한 줄 추가. 원시 n/p/Potential 배열, 단위,
   접점 bias, 색 map, sampling 및 좌표 transform은 그대로 둔다.
4. 새로운 engine-free unit으로 metadata 유효/결손/NaN/단위 mismatch와
   기존 caption 계약의 양립을 확인. 기존 unit88개는 파일 변경 없이 유지한다.
5. 실제 remote Tk GUI n(1e16)/p(5e15)/intrinsic(known-undoped),
   4×1um grid0.2, x max source; n/p .01V, intrinsic .001V.
   각 기존 measurement3solve. potential/electron/hole9개 layer를 실제 redraw.
   caption 문자열=helper, 실제 노드 개수=field_samples, 노드 원좌표→pixel
   위치 및 원배열 무변경을 확인. 캔버스 크기/설명 bbox를 기록해 잘림을 확인.
   실제 캔버스 PNG가 가능한 환경이면 저장하되 PNG는 수치 물리 승인 근거 아님.
6. legacy/missing metadata는 경고 표시이지 새 물성/물리적 정확도 승인 아님.
   field numeric invalid는 기존 gate가 계속 차단한다. modal 및 잔여 device0.
7. 전체 tracked unit89 + 기존 actual GUI4 + 새 actual canvas1을 원격 격리 실행.
   파일별 unit60s/integration120s, profile900s. FAIL/timeout/skip 원본 유지.

## 조사를 수행한 심볼 및 허용 범위
Serena 도구 미노출로 rg/직접 읽기. field_caption→_draw_measurement_field→redraw,
save_node_field_evidence, 기존 test_node_field_caption_mock 및 caption source tests.
변경: transport_evidence의 짧은 scope helper, node_fields.field_caption,
새 unit/integration, 원격 profile/driver와 감사 자료만.
기존 AH PLAN/raw와 production 물리 코드/gate/엔진 내부는 수정 금지.
