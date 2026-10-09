# E6N-T 결과: 실제 GUI의 전압 부호·접점 교환·x/y 방향 물리 대조

## 판정과 범위

**UNIFORM_LOW_FIELD_GUI_8_CASES_VERIFIED**. 단일 균일 Si 저항의 사전등록된 8개
요청에서 실제 DEVSIM 결과, 실제 Tk 노드 표시, 저장 JSON이 연결됨을 확인했다.
PN 접합·산화·MOS·모든 공정 순서를 승인한 것이 아니다. 기존 gate는 유지한다.

production 수정 없이 기존 공식 API 경로를 실행했다. 로컬은 소스/기하/판정기만,
엔진 import와 실제 GUI/solve는 GitHub-hosted Windows에서만 실행했다.

## 실행과 증거 식별

- 시작 HEAD: dcf7b3c. PLAN 단독 커밋: fcece2b.
- 실행 SHA: ddf01be947cad338f2905226733f5c49ee5d34b6.
- 원격 run: https://github.com/tjrgns1753-create/tcad/actions/runs/37974877904
- artifact: remote-run-68. 원본 전체는 `raw/`에 바이트 그대로 보존.
- 실행: 2026-10-09 18:41:03.839735–18:41:10.630900 UTC, parent 6.791초.
- 실제 GUI matrix child 4.515초, 8 요청 × 3 solve = **24 solve 호출**.
- remote 5항목(matrix/judge/bias/caption/contacts) rc=0, cleanup=true.
- ViennaPS 4.6.2, DEVSIM 2.11.0, Windows X64, Python 3.11.9.
- summary의 devsim NOT_IMPORTED는 **부모 실행기**를 뜻한다. 실제 child가 엔진을
  import하고 24회 solve했다. 이를 엔진 미사용 또는 0 solve로 해석하면 안 된다.

## 사전 기준과 실제 결과

Si 2µm × 0.5µm, ACTIVE donor 1e16cm^-3, acceptor 0, 300K.
공식 모델의 실제 q=1.6e-19C, n_i=1e10cm^-3, mu_n=400, mu_p=200cm²/(V·s),
수명 1e-8s는 원격 get_parameter로 읽고 사전 고정값과 대조했다.
sigma=q(mu_n*n0+mu_p*p0), G=sigma*height/length, I=GV를 기존 E6I judge로 계산했다.
허용기준은 PLAN의 기존 E6I 기준 그대로이며 결과에 맞춰 변경하지 않았다.

| 요청 | source I (A/cm) | 해석식 전류 상대차 |
|---|---:|---:|
| x / max / +1mV | +1.600000000002224e-4 | 1.098e-13 |
| x / max / -1mV | -1.600000000002224e-4 | 1.098e-13 |
| x / max / 0V | 0 | 0 (G×1mV 정규화) |
| x / min / +1mV | +1.600000000002224e-4 | 1.098e-13 |
| y / max / +1mV | +2.560000000003728e-3 | 4.354e-14 |
| y / min / +1mV | +2.560000000003728e-3 | 4.354e-14 |
| y / max / -1mV | -2.560000000003728e-3 | 4.354e-14 |
| y / max / 0V | 0 | 0 (G×1mV 정규화) |

y/x 전류비 **16.00000000000106**, 기대 16 대비 상대차 6.617e-14.
이는 접점 방향에 따른 길이·단면 변화로 설명되는 값이며 새 이동도 보정이 아니다.
최대 KCL 오차 4.489e-14 (G×1mV 정규화), 최대 affine Potential 오차
5.551e-14 (1mV 정규화), n 균일성 오차 0. 사전 33개 수치 판정 모두 통과.
0V 전류는 실제 반환값이 0이며 후처리에서 0으로 강제 치환하지 않았다.

공식 구성방정식 근거:
[DEVSIM simple_dd.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_dd.py),
[DEVSIM simple_physics.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py).
이 균일 저항의 해석해 비교는 비균일 PN 또는 반전층 검증을 대신하지 않는다.

## GUI→원본 API→저장 동일성

매 요청마다 공개 get_node_model_values로 읽은 73개 노드의 Potential/Electrons/Holes를
snapshot tuple과 전체 equality 비교했다. 3개 레이어마다 실제 Tk canvas 노드 73개,
영역 Si 및 No interpolation 문구, 해당 요청 전압의 캡션을 확인했다.
각 JSON의 전체 snapshot과 반환 bias point를 기록과 다시 비교했다.
원시 Potential은 보존했으며 접점 인가전압 기준으로 값을 바꾸지 않았다.

x/max/+1mV 저장 파일은 E6NP 원본과 바이트 단위 동일:
SHA256 8111c300184eccc680938178e6112fc6e8152e2b4789cc1cdfa79d935df1056f.
이전 정상 물리 결과를 표시 수정 때문에 바꾸지 않았음을 보여준다.

## 독립 재검사와 거짓 통과 방어

`verify_artifact.py raw`는 엔진/Tk import를 audit hook으로 차단한다.
실행 SHA/run, 입력 15개 git blob의 LF/CRLF checkout 해시, 원본 17개 파일의
크기·SHA를 대조하고 records에서 판정을 재계산해 전체 verdict equality를 확인했다.
추가로 전류 부호·0V·접점교환·전체 저장 파일을 직접 검사했다.
출력: pass=true, actual_cases=8, actual_solves=24, checks=33, engine_imports=0.

엔진 없는 합성 판정기 대조군과 7개 오류 입력도 통과/차단을 검증했다.
합성 데이터를 실제 계산 결과로 집계하지 않았다. 실제 24회는 모두 정상 반환한
이번 관측의 호출 수이며 실패 호출의 성공 횟수를 혼동하지 않는다.

## 변경과 남은 경계

이번 변경은 audit PLAN/스크립트/보고서/원본과 remote profile/request뿐이다.
production `tcad/`, `tcad_2d_stagewise.py`, 기존 테스트에는 변경 0건.
새 엔진 식·내부 코드 수정·숫자 fallback·gate 해제·전체 회귀·main 병합 없음.
73노드 소규모 한 구조의 검증이지 대형 표시 한도·모든 mesh 수렴 증명이 아니다.
전자 majority의 균일 n을 검증했지만 p-type majority 및 보상 도핑은 이번 범위 밖이다.
양의 시간 산화 및 2D step junction의 기존 미검증 상태를 그대로 유지한다.
