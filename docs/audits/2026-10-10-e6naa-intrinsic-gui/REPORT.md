# E6NAA — 알려진 무도핑 Si의 실제 GUI 측정 연결

## 결론과 지원 경계

`KNOWN_UNDOPED_LOW_FIELD_GUI_VALIDATED` — 정확한 virgin Si 입력, 단일 직사각형,
상수 이동도 모델, 전계 <=5 V/cm 범위에서 실제 GUI→공식 DEVSIM→전체 노드 표시→JSON
경로를 확인했다. 모든 공정/도핑/PN 해를 검증했다는 뜻이 아니다.
UNKNOWN·CHEMICAL·기록이 있는 ACTIVE를 무도핑으로 바꾸지 않는다. 처리 후 unresolved,
양의 시간 산화, 보상 transport, 2D step-junction의 기존 차단은 유지된다.

## 출처와 실행

- PLAN 단독 커밋: `fba1461`, LF SHA256 `341c4413b363c8ec6a7501da2d3853b17ce849222c9ef8007c21cf95487021bb`.
- 구현·실행 SHA: `ad59b772cc9b1fb157816808306231e806bf4a29`.
- 원격 run: https://github.com/tjrgns1753-create/tcad/actions/runs/37983547425
- artifact: `remote-run-76`, GitHub-hosted Windows. 로컬 엔진/Tk 실행 0회.
- 원격 하위 단계 5개(contract/missing/bias/gui/canonical): 모두 정상 종료와 자식 정리 확인.
- 원본: `raw/summary.json`, `raw/run.log`, `raw/outputs/e6naa_out/`.
- 독립 검증: `verify_artifact.py`가 실행 SHA의 입력 18개, 원본 14개 해시, PLAN,
  모든 실제 node와 전류, GUI/저장 배열을 엔진 없이 대조하여 통과했다.

## 구현의 의미

`tcad/characterization/intrinsic.py`는 새로운 운반 모델이 아니다. 정확한
initial_geometry provenance와 attachment0/ledger0인 Si 입력인지 확인하고, 계산 뒤
공식 get_parameter 및 전체 노드 값으로 기존 상수 이동도 모델의 해석해를 검사한다.
`I=q*(mu_n+mu_p)*n_i*(W/L)*V`는 깊이당 전류 `A/cm`이다.

`run_measurement()`는 완전히 pristine GUI만 기존 materialization 경로로 입력을
구성한다. 가짜 zero DopingProfile을 만들거나 last_doped_result에 저장하지 않는다.
기존 canonical apply_doping가 알려진0을 확인한 뒤 기존 공개 DD API로 계산한다.
전체 field capture 또는 해석 검증 실패 시 성공 history/field/result를 제공하지 않는다.
도핑된 기존 경로의 terminal-current/capture 정책은 바꾸지 않았다.

## 실제 전체 노드와 해석 비교

실제 파라미터: T=300 K, n_i=1e10 cm^-3, mu_n=400, mu_p=200 cm²/Vs,
taun=taup=1e-8 s. 이는 현재 모델 입력값이며 모든 실제 Si의 보편 물성값이라는 주장이 아니다.
모든 경우 Donors/Acceptors/NetDoping은 전 노드에서 알려진0이고 n=p=1e10이다.

| 요청 | 노드 | 실측 source 전류 A/cm | 해석 전류 A/cm | 전류 상대오차 |
| --- | ---: | ---: | ---: | ---: |
| x 0 V | 73 | 0 | 0 | 0 |
| x +1 mV | 73 | 2.4000000000000005e-10 | 2.4e-10 | 2.16e-16 |
| x −1 mV | 73 | −2.4000000000000005e-10 | −2.4e-10 | 2.16e-16 |
| y +0.25 mV | 73 | 9.6e-10 | 9.6e-10 | 0 |
| fresh GUI→materialization→x +1 mV | 27 | 2.4e-10 | 2.4e-10 | 0 |

GUI 실제 solve는 각3회, 합계15회다. 별도 canonical integration의 solve는 이15회에
포함하지 않는다. KCL 최대2.16e-16, affine Potential 오차 최대1.09e-16,
전자·정공 상대오차0. 기준은 결과 전에 고정한 PLAN 그대로다.

세 layer 모두 전체 실제 node를 렌더링하고, 공개 API 값과 NodeFields가 정확히 같다.
다섯 JSON의 snapshot과 currents/voltages도 GUI가 보유한 동일 결과와 같다.
새 노드로 보간하거나 전위를 contact bias로 재기준화하지 않았다.

## 차단 대조군과 기존 동작

전계 상한 밖, unresolved, CHEMICAL, ACTIVE missing profile 네 요청 모두
solve/write/capture/history0, fields=None, state identity 유지. 무도핑으로 재초기화하지 않았다.
기존 missing-profile 합성6케이스와 잘못된 요청/result identity6반례·정상3대조군 통과.
기존 실제 canonical ACTIVE integration도 assertion 변경 없이 통과했다.
장치·mesh 삭제 후 잔존0, 모달 호출0.

## 정직한 검증 한계와 개발 중 수정

- 이 결과는 평형·균일 저전계 모델 검증이다. 비균일 PN, 고전계, 재결합으로 생긴
  공간 변화, trap/산화/activation/공정 이력 전달의 독립 검증을 대신하지 않는다.
- 기존 양의 시간 산화와 보상 transport 게이트를 해제하지 않았다.
- 전체 회귀는 이번 배치에서 실행하지 않았다. 이전 W의83파일 결과를 현재 전체 회귀로
  재인용하지 않는다. 이번에는 지정된5단계만 실행했다.
- 편집 중 intrinsic 분기를 `_doping_is_stale`에 잘못 삽입한 사실을 정적 읽기로 발견하여
  즉시 원복하고 정확한 run_measurement 위치에 넣었다. 그 중간 코드는 실행/원격 전송하지 않았다.
- 초기 prototype의 contact 이름 suffix 의존도 없애고 실제 min/max 위치 boolean을
  명시적으로 전달했다. arbitrary contact names 합성 대조군을 추가했다.

## 무결성과 다음 작업

원본 raw는 재포맷하지 않고 바이트 보존한다. 기존 감사자료/PLAN/엔진 내부 변경0,
main 변경0. 코드 diff check 통과. 원본의 줄바꿈을 보존하기 위한 raw 예외는 기존
gitattributes 계약을 따른다. 개인 경로/토큰 패턴 검색 결과0.

다음 확인은 해석 검증 실패를 실제 GUI 경로에 주입했을 때 숫자/field/history가
거짓 성공으로 남지 않는지와, 반대 source 위치·역방향 y 측정이다. 오류 상태의
physics_status가 이전 성공 상태로 남지 않도록 별도 반례 기반으로 보완할 수 있다.
