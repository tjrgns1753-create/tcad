# E6N-A 양성 기하 대조군 보완 완료

## 결론과 승인 범위

판정기 구현은 수정하지 않았다. 새로운 독립 합성 기하를 기존 전체 analyze 경로에 넣어
NONINVARIANCE_WITNESS를 확인했다. 기존 상대·오차 문턱과 L은 그대로다.
양성 경로, 정상 음성 경로, 증거 변조 차단의 검증이지 실제 N0/N1/N2 결과나 PN 승인은 아니다.
실제 엔진 import/solve/원격 실행/전체 회귀/커밋/push는 모두0이다.

## 시작 상태와 Serena 조사

- HEAD509f5e50db8cab3ae59c36c2c4693f27ade30567, claude/remote-runner.
- 기존 자원 감독 보완 등 dirty 변경을 보존했다. 기존4 tracked 파일의 +188/-22 변경은 이번 수정이 아니다.
- Serena tool은 이번 세션에 노출되지 않았다. rg/직접 읽기를 사용했다.
- 조사 대상: diagnostics.analyze/exact_row/geometry_weights/classify,
  test_review_followup.fixture/check_geometry, 기존 exact conformity checker.
- 기존 production 물리 경로를 호출하지 않는 감사 테스트다. 기존 감사 실행기는 analyze를 사용한다.
- classify 우회 없이 실제 analyze가 선택한 pair/power를 직접 검증했다.
- 기존 test 및 판정 코드 수정0. 새 기하 생성과 독립 Fraction 기준만 추가했다.

## 실행 전에 고정한 기준

POSITIVE_GEOMETRY_CRITERIA.md를 최초 analyze 실행 전에 생성하고 SHA를 확인했다.
SHA256963d9a5c9b1933471a4edff04cdc14f807f3a56333a8a492f27e9728b61b8d70.
시험 코드에 독립 상수로 고정했고 이후 문서 수정0이다.

새 기하는21 node/26 triangle의 가로 방향 전이 rectangle이다.
추가 fine/coarse strip과 회전된 전이 방향으로 기존 실패 fixture와 다른 topology다.
기존 실패 fixture의 uniform scaling을 사용하지 않았다. 원 fixture와 정정 기록은 그대로다.
h=1/4096cm는 저장 좌표의 정확한 binary rational을 위한 선택이다.
새 합성 domain이 실제 PN geometry와 다르다는 점을 사전 문서에 명시했다.

사전 손 유도:
- node6 volume2h², 비영 incident weights={2,2,1/2,1/2}.
- node11 volume17h²/8, 비영 incident weights={2,2,1/2,1/4,1/4}.
- projected rows는 각각 (-1,2,-1)/h², (-18,36,-18)/(17h²).
- 차이는 (1,-2,1)/(17h²), 정확히 비영이다.

입력 가중치와 volume은 Fraction triangle 산술로 생성했다.
그 결과를 손 유도한 상수와 먼저 대조한 뒤 diagnostics 결과와 비교했다.
diagnostics.geometry_weights/exact_row로 기대값을 만들지 않았다.
exact conformity의 직사각형 경계·면적·hanging·owner 검사를 통과했다.
독립 Fraction dot product로 모든 triangle의 비둔각·비퇴화 및 면적32h²도 확인했다.

## 실제 결과

| 항목 | 사전 예상 | 실측 |
|---|---|---|
| pair / power | [6,11] /2 | 일치 |
| node class | strict interior 두 개 | [0,0] |
| node6 작용 | -125000 | -125000.0 |
| node11 작용 | -2250000/17 | -132352.9411764706 |
| 차이 | 125000/17 | 7352.941176470602 |
| operator scale | 83886080 | 83886080.0 |
| 상대 문턱 | 0.8388608 | 0.8388608 |
| 기하 가중치 차이 bound | ≤1e-6 예상 |0.0 |
| 두 번째 문턱 | <0.000287 예상 |0.0001862645149230957 |
| 최종 | NONINVARIANCE_WITNESS | 일치 |

이 시험에서 uncertainty0은 독립 기하 입력의 곱/나눗셈이 해당 float 저장에서
동일한 weights를 재현한 결과다. 실제 native DEVSIM 오차0이라는 의미가 아니다.

## 대조군과 실패 보존

- 기존 tensor-grid INCONCLUSIVE, 내부 node6/7/8의 exact projected rows는 동일.
- 기존 transition과 축소 stencil-only는 모두 기존 INCONCLUSIVE 유지.
- 새 기하의 endpoint 방향 반전은 같은 NONINVARIANCE_WITNESS.
- NodeVolume/EdgeLength/EdgeCouple 누락3종, NaN, 범위 밖 endpoint,
  volume2배, length/couple 동시2배의7반례 모두 예외 차단.
- 비교 영역 밖 평행 이동은 NOT_MEASURED.

최초 시험은 위 수학·대조군 assertion을 모두 통과했지만 마지막 JSON 저장에서
저장소 경로 접근 PermissionError로 RC1이었다. 이를 물리 실패나 PASS로 숨기지 않는다.
출력 경로만 CLI --output으로 지정 가능하게 수정했다. 좌표·연결·기준·assertion 변경0.
허용된 workspace에 결과를 저장하여 재실행 RC0을 확인했다.
저장소 결과 파일은 그 JSON 값을 LF 형식으로 보존한 사본이다.

관련6파일을 direct script로 다시 실행했고 각각 RC0:
test_contract.py, test_review_followup.py, test_flux_source_contract.py,
test_resource_supervisor.py, test_supervised_entry.py, test_positive_geometry.py.
시험은 전체 회귀가 아니다. 자원 시험의 짧은 프로세스에는 물리 엔진이 없다.

## Change diff

신규 파일만 추가했다. 기존 tracked diff에는 이번 작업이 추가한 변경이 없다.
- POSITIVE_GEOMETRY_CRITERIA.md: 기하·정확한 rows·기대값·범위 사전 고정.
- test_positive_geometry.py: positive_fixture/projected_rows/blocked/main.
- POSITIVE_GEOMETRY_RESULT.json: pair·작용값·두 문턱·반례 결과.
- 본 보고서와 POSITIVE_GEOMETRY_CHANGES.diff.txt: 변경 및 실행 기록.

전체 신규 기준/테스트/결과 diff:
POSITIVE_GEOMETRY_CHANGES.diff.txt
SHA256f6e0f00f6300cd548b137b01e875348c96727d6abfd461a51cfcce2dc8e81da2.

주요 코드 구간:
```python
assert rows[6]==expected6 and rows[11]==expected11
rec,arrays=D.analyze(a)
assert rec['verdict']=='NONINVARIANCE_WITNESS'
witness=next(w for w in rec['witnesses'] if w['nodes']==[6,11] and w['power']==2)
assert witness['difference']>max(threshold_relative,threshold_error)
```

## 불변 증거 및 남은 승인 조건

기존 PLAN SHAa7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103 유지.
원격 summary SHAb6fee95b08db6a927d86f84c92192515a634dbb225c2dcd45d10ddb7c78618c4 유지.
원격 log SHAfc7b639da4b7f4d1df7806fa7df32d28c85c9727fa151d26bdb0084f427f23f3 유지.
production/gate 무변경. git diff --check RC0.

다음은 작은 원격 엔진 없는 감독 시험으로 Python3.11 및 GitHub Job 중첩 호환성을 확인하는 단계다.
계산 deadline와 wrapper cleanup 유예 경합, artifact 독립 검증도 별도 정리가 필요하다.
그 뒤에만 기존 고정 N0/N1/N2 import 감사의 재실행을 검토한다.
합성 양성 결과로 실제 후보의 이산 비환원성이나 PN 물리를 미리 승인하지 않는다.
