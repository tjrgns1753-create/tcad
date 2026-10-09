# E6N-U2 결과: 단독 p/n 물리 대조와 보상 도핑 transport 거절 분리

## 결론

**SINGLE_POLARITY_PHYSICAL_CONTROLS_AND_COMPENSATED_REFUSAL_VERIFIED**.
단독 p/n 균일 저항 4요청의 실제 결과와 기존 보상 도핑 8요청의 차단이 검증됐다.
보상 transport·PN·산화·이온주입·활성화 기능을 새로 승인한 것이 아니다.

최초 U1 run 37976122403은 FAIL로 그대로 보존한다. `ERRATUM_INITIAL.md`에
그 원인(감사 설계가 기존 capability gate를 놓침)을 기록했다. 이전 PLAN과 raw는
수정하지 않았고 누락 verdict를 발명하지 않았다. 후속은 별도 PLAN_BOUNDARY다.

## 시작·실행·원본

- U2 PLAN 단독 커밋 5c522f4, LF SHA d02b200d650bd0cb5e5aaa20de298b6bd94bcf2e5a390cff499241190384a7ef.
- 실행 SHA 0ac145d48dbb0984b2b417bfa0c71075d668c717.
- [원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37977642901), artifact remote-run-70.
- 전체 원본 `raw_boundary/`. 최초 실패 원본은 별도 `raw_initial/`.
- 실제 계산은 원격 Windows, 로컬은 소스·합성 테스트·원본 해시 재검사만 했다.
- remote 5단계 matrix/judge/bias/caption/no_resurrection 각각 rc=0, cleanup=true.
- 실제 12요청 중 4개만 3 solve씩 총 **12회** 계산됐다. 나머지8개는 0회로 차단.
- summary의 NOT_IMPORTED는 과거 실행기의 정보 조회 표기이지 child 0 solve의
  근거가 아니다. 실제 counts는 profile records와 supervisor logs에서 검증했다.

## 실제 단독 p/n 해석해 비교

geometry 2µm×0.5µm, ACTIVE ND=1e16 또는 NA=1e16cm^-3, 300K.
공식 상수 이동도 mu_n=400/mu_p=200와 q/ni/SRH는 고정값과 실제 API가 일치했다.

| 요청 | source I (A/cm) | I=GV 상대차 | ground 원시 Potential (V) |
|---|---:|---:|---:|
| n형 +1mV | +1.600000000002224e-4 | 1.098e-13 | +0.3576447899345236 |
| n형 -1mV | -1.600000000002224e-4 | 1.098e-13 | +0.3576447899345236 |
| p형 +1mV | +8.000000000023121e-5 | 1.098e-13 | -0.3576447899345236 |
| p형 -1mV | -8.000000000023121e-5 | 1.098e-13 | -0.3576447899345236 |

majority 균일성 오차0, KCL 오차0, 전위 affine 최대차/1mV=5.551e-14.
정공 majority가 정상적으로 전달되며 접점 인가전압0과 원시 Potential은 동일한
전위 기준이 아니다. 표시/JSON에서 원시 값의 부호·값을 바꾸지 않았다.
전류비 약0.5는 상수 이동도 선택의 결과이며 실제 모든 Si의 이동도비라는 뜻이 아니다.

공식 식 근거:
[DEVSIM simple_physics.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py),
[DEVSIM simple_dd.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_dd.py).
기존 E6I charge-neutrality 근과 sigma=q(mu_n*n0+mu_p*p0)를 재사용했다.
이 비교는 독립 해석식과 일치하는 **균일 저항의 제한된 물리 검증**이다.
DD 초기화의 준페르미/질량작용 항등식을 추가 독립 증거로 중복 집계하지 않았다.

## 실제 보상 입력 순서 8요청

n_comp의 두 순서: ND2e16/NA1e16/net+1e16.
p_comp의 두 순서: ND1e16/NA2e16/net-1e16. 각각 ±1mV 요청.
기존 apply_uniform_doping→advance_wafer_state를 두 번 실제로 호출했다.
1개 net-only attachment로 바꾸거나 donor/acceptor를 숨기지 않았다.

8개 모두 다음 기록을 갖는다:
- canonical donor/acceptor/net는 모든73개 지점에서 요청합과 같고 query status는 None.
- ACTIVE attachment2개, 측정 전/후 상태 객체 identity 및 전체 농도 배열 보존.
- COMPENSATED_TRANSPORT_MODEL_MISSING / UNSUPPORTED_BY_MODEL.
- observer solve0, doping write0, 실제 field capture callback0.
- measurement=None, snapshot=None; 전류0이나 carrier0으로 대체하지 않음.
- 측정 history 증가0, 성공 측정 로그 없음, 3레이어 solved node0.
- export dialog0회, 새 결과 파일 없음, 남은 device0.

두 선언 순서는 final canonical 농도와 refusal reason이 같다.
이것은 농도 보존과 정직한 차단 증거이며 보상 도핑의 전류를 계산했다는 뜻이 아니다.
compensated_transport_problems/canonical_node_doping의 기존 게이트는 그대로다.
이온화 불순물 산란·농도 의존 이동도 모델의 물리 승인은 별도 문제다.

## 전체 노드·저장·독립 재검사

단독4개: 각73노드×3필드의 공개 API와 snapshot equality, 실제 Tk 노드 표시,
접점 bias/current 및 단위 A/cm와 JSON의 전체 equality를 확인했다.
4개 저장 파일은 최초 U1의 정상 부분 결과와 **바이트 단위 동일**하다.

`verify_boundary.py raw_boundary`:
입력21개 git blob/checkout 해시, 원본13개 파일의 크기·SHA, 실제 records→verdict
전체 equality, 4개 numeric+8개 blocked, 사전30개 판정, actual solves12를 확인했다.
독립 재검사에서는 엔진/Tk import를 audit hook으로 금지했다.
별도 합성 분리 계약은 8개 반례(누락/attachment 소실/solve/write/fake current/
fake field/순서 훼손/wrong reason)를 차단했다. 합성 자료는 실제 결과가 아니다.

## 변경과 한계

U2는 새 감사 check_boundary/judge_boundary/test_boundary/run_boundary와 remote
profile/request를 추가했다. 기존 감사 judge에 cases 인자를 추가하여 동일한 수치
기준을 단독4개에 재사용하고, 합성 fixture 생성기를 분리했다. 기본 U1 12개 기준과
62개 합성 판정은 그대로 유지했다. 첫 실험 FAIL을 PASS로 재분류하지 않았다.
실제 변경 소스는 각 실행 SHA와 해당 파일에 전부 보존돼 있다.

실행 SHA 기준 production `tcad/`, GUI, 기존 tests 및 gate는 0ac52a9와 동일하다.
이후 병행 준비한 실행기 증거 범위 수정(V)은 이 실행 SHA에 들어 있지 않다.
원본/PLAN/engine 내부/수치 tolerance 수정·전체 회귀·main 병합 없음.
미지원 보상 전류, 양의 시간 산화, 2D step junction의 미검증 gate는 그대로다.
