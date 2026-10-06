# E6N-A 검증 코드 보완 — 부분 완료, 원격 재실행 보류

## 범위와 판정

사용자가 Codex의 직접 구현을 승인했다. 기준 HEAD는
509f5e50db8cab3ae59c36c2c4693f27ade30567, 브랜치 claude/remote-runner.
시작 tracked diff 0. 이번 수정은 감사 실행기/판정기/합성 검증에만 적용했다.
production, tests/, GUI, gate, 엔진 내부, 기존 PLAN, 기존 원격 증거는 수정하지 않았다.
엔진 import/실제 solve/원격 재실행/전체 회귀/커밋/push는 수행하지 않았다.

판정: EVIDENCE_VALIDATION_PARTIALLY_HARDENED.
원격 실행 승인, NONINVARIANCE_WITNESS 양성 전체 경로 검증, PN/DD 물리 승인은 아니다.
운영 자원 watchdog은 구현하지 않았다. 구조 변경안 승인 전 원격 실행 금지.

## Serena investigation / 지침

적용 프로젝트 CLAUDE.md를 전체 구간으로 읽었다. 저장소 및 docs 아래 추가
CLAUDE.md/AGENTS.md는 발견되지 않았다. 상위/전역 CLAUDE.md도 조사한 경로에 없었다.
현재 Codex 작업 폴더 AGENTS.md의 한국어 원칙을 적용한다.
현재 세션의 Serena tool 목록은 비어 있어서 활성 프로젝트 확인/심볼 조회 불가능했다.
rg와 현재 파일을 직접 읽는 fallback으로 조사했다.

대상: diagnostics.validate/analyze/checked_indices,
run_e6na.execute/preflight/require_inputs/require_flux_source/without_solve/cleanup.
기존 caller는 감사 run_e6na와 test_contract, 원격 profile e6na_import_reduction이다.
production caller 없음. 추가 테스트도 audit 폴더 안에만 있다.
실제 execute 진입도 PLAN 검사를 거치도록 했고 _execute는 내부 경로로 분리했다.
기존 helper imports와 np.load가 solve trap 보호 밖/복원 범위 밖이던 점을 수정했다.
Serena 결과가 없어 일치 판정은 하지 않는다. 현재 코드/테스트/patch가 검토 증거다.

프로세스 명령줄 조회는 Get-CimInstance 접근 거부로 실패했다.
따라서 시스템 전체 실행 중 계산 0건이라고 주장하지 않는다. 기존 프로세스는 건드리지 않았다.

## 물리적 타당성 질문

실제 물리 상태와 이력을 지키는 TCAD로 향하는가? 잘못된 공식 배열이나 미확인
식 대응이 검증 증거로 통과하지 않게 하는 방향이다. 새로운 물리 계산은 없다.
공식 NodeVolume/EdgeCouple을 독립 기하로 대조하는 방법은 유지하고 native 모델을 덮어쓰지 않는다.
이번 import-only 이산 진단은 process conservation/PN current/논문과의 물리 일치를 증명하지 않는다.

공식 근거: https://devsim.net/models.html 표5.2 EdgeLength는 endpoint 사이 거리,
EdgeInverseLength는 역수, EdgeCouple은 surface integration 길이.
이 정의와 저장 xy/endpoint를 대조한다. cot/volume/기존 witness 식과 문턱은 그대로다.
새 64*eps64 길이 검사는 진단 기준이며 실제 wheel array 대응은 아직 측정하지 않았다.

## 수정 전/후 반례

기준 HEAD의 diagnostics 소스를 git show로 읽어 엔진 없는 namespace에서 실행했다.
동일 정상 fixture의 EdgeLength와 EdgeCouple을 동시에 두 배로 바꿨다.

```text
BEFORE_CORRUPT INCONCLUSIVE
AFTER_CORRUPT EVIDENCE_BLOCKED: EDGE_LENGTH_GEOMETRY_MISMATCH
BEFORE_AFTER_NORMAL INCONCLUSIVE INCONCLUSIVE
```

거짓 물리 PASS 재현이 아니라 잘못된 증거를 받아들이는 결함의 재현이다.
공식 식 mismatch 미차단과 late resource check는 이전 코드 정적 조사 결과이며
기존 원격 물리 실행에서 거짓 PASS가 나왔다고 주장하지 않는다.

## 테스트 결과

bundled pure Python -B, PYTHONIOENCODING=utf-8. 프로젝트 엔진 venv를 실행하지 않았다.

1. 기존 test_contract.py: RC=0, synthetic/preflight PASS.
2. 신규 test_review_followup.py: RC=0.
3. 신규 test_resource_proposal.py: RC=0. 운영 watchdog 검증이 아니라 순수 정책 prototype.
4. audit 전체 Python AST parse 통과.

신규 전체 경로:

```text
FULL_PATH normal INCONCLUSIVE
FULL_PATH transition INCONCLUSIVE
FULL_PATH stencil_only INCONCLUSIVE
FULL_PATH reversed_endpoints INCONCLUSIVE
FULL_PATH roundoff_only INCONCLUSIVE
BLOCKED joint_scale_corruption
BLOCKED missing_NodeVolume
BLOCKED missing_EdgeLength
BLOCKED missing_EdgeCouple
BLOCKED endpoint_fractional
BLOCKED endpoint_nan
BLOCKED endpoint_negative
BLOCKED endpoint_range
FULL_PATH no_candidate NOT_MEASURED
BLOCKED flux_source
BLOCKED flux_source
BLOCKED actual_entry_plan
BLOCKED actual_entry_plan
BLOCKED restore_np_load
BLOCKED restore_cleanup
BLOCKED forbidden_solve
CLEANUP failure_is_FAIL and mesh_cleanup_attempted
CLEANUP normal_PASS
FOLLOWUP PASS; actual engine imports=0; actual solve=0
```

forbidden_solve는 가짜 객체 함수의 시도 1회를 기록한 것으로 실제 엔진 solve가 아니다.
PLAN 불일치/누락과 flux 확인 실패/mismatch는 후속 callback 0회.
np.load/cleanup 예외 후 기존 solve callable identity 복원, cleanup 실패 시 mesh 삭제도 시도한다.

## 잘못된 사전 예상과 미충족 대조군

SYNTHETIC_REVIEW_CRITERIA.md를 테스트 전에 작성했다. 그 문서의 전이 fixture
NONINVARIANCE_WITNESS 예상이 최초 실행에서 실패했다.
pair 이차 차이=1923.0769230769074, operator_scale 약6.8e11,
기존 문턱 약6800이므로 INCONCLUSIVE가 옳다. exact projected row 차이는 비영이다.

좌표/연결/L/tolerance를 바꾸지 않았다. 잘못된 예상만 정정했고 원본 기준 문서와
CRITERIA_ERRATUM.md에 최초 실패를 보존했다. 구조적 차이/작용 차이 존재 assertion을 추가했다.
전체 analyze 경로의 충분한 양성 witness 대조군은 아직 미충족이다.
scalar classify 양성 테스트가 이것을 대신한다고 주장하지 않는다.
합성 기대가 틀린 것을 물리 코드 오류로 귀속하지 않는다.

## 자원 계약 — 제안만, 아직 미구현

기존 사후 시간/메모리 검사와 arrays-only bytes 합산은 그대로 남는다.
RESOURCE_POLICY_PROPOSAL.md에 supervisor/후보 child/OS Job Object/작업집합 감시,
전체 payload 예산과 artifact 완전성 검사 구조를 제출했다.
이는 기존 실행 구조 변경이므로 승인 전에 연결하지 않았다.

resource_policy_prototype과 그 테스트는 합성 snapshot의 600초/1800초/6GiB,
측정 실패/중단 callback 실패/JSON 포함 output budget 판단만 확인한다.
실제 clock 감시, OS process-tree 종료, native hang, 메모리 할당 보호는 검증하지 않았다.
감시 interval·working set과 commit limit 정의·child startup/cleanup 계약은 승인 필요다.

## 공식 소스 확인의 한계

require_flux_source는 inspect.getsource 실패나 기대 문자열 누락을 중단시킨다.
정상 callback 1회, 불일치/확인 불가 callback 0회가 합성 테스트로 확인됐다.
문자열 존재만 검사하므로 주석/사용되지 않는 식/코드 의미 변형을 완전히 배제하지 않는다.
엔진 내부 전체의 동일성이나 의미적 프로그램 동등성 증명은 아니다.
실제 wheel helper를 import해서 확인한 결과는 이번 작업에 없다.

## 원본 무변경

기준 HEAD의 E6M/E6K 및 E6N-A PLAN/raw tracked 파일 44개를 현재 파일과 대조했다.
텍스트는 git checkout CRLF 차이도 고려했고 binary는 원시 바이트 비교했다.
특히 E6N-A 아래 원시 파일의 현재 해시는 다음이며 수정하지 않았다.

- PLAN.md: a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103
- raw/remote-run-33/summary.json: b6fee95b08db6a927d86f84c92192515a634dbb225c2dcd45d10ddb7c78618c4
- raw/remote-run-33/run.log: fc7b639da4b7f4d1df7806fa7df32d28c85c9727fa151d26bdb0084f427f23f3

git diff --quiet -- tcad tests tcad_2d_stagewise.py RC=0.
커밋/push/stage 없음. 기존 원격 run33은 여전히 실패 증거이며 이번 테스트로 성공으로 바꾸지 않는다.

## Change diff

원래 tracked 변경은0. 이번 변경은 audit 디렉터리 안에만 있다.
핵심 변경 심볼:

- diagnostics.checked_indices: 정수 변환 전 원시 값을 검증.
- diagnostics.validate: xy/endpoint에서 재계산한 길이와 별도 대조.
- run_e6na.require_flux_source: 불일치/확인 실패 시 callback 호출 차단.
- run_e6na.without_solve: callback의 모든 예외 경로에서 원래 solve 복원.
- run_e6na.cleanup: device 실패해도 mesh 삭제 시도, 실패/잔존이면 후보 FAIL.
- run_e6na.execute/_execute/_execute_import_audit: 실제 진입 PLAN 검사,
  엔진 확보 직후 trap, helper/array loading까지 보호, 원시 index를 검증 후 변환.
- .gitattributes: 생성된 unified patch의 바이트 보존만 추가.
- 신규 합성 테스트/기준/정정/자원 정책 제안은 모두 이 디렉터리 안에 있다.

전체 코드/시험/정책 diff는 FOLLOWUP_CHANGES.patch(553줄)에 보존했다.
SHA-256: 3fe4286d8c80dbba03b43cc67a18128cc4f913df24b9852f03146245639c68b7.
원본 REPORT.md를 덮어쓰지 않고 이 문서에 보완 결과를 추가한다.
일반 git diff --check RC=0, clean config 공백 검사도 RC=0.
git diff --cached --stat는 비어 있고 HEAD는 기준 값 그대로다.

## 남은 다음 단계

1. 운영 자원 감시 구조와 PLAN 보완을 승인받아 구현해야 한다.
2. 전체 판정 경로의 충분한 양성 witness fixture를 독립 사전 계산하고 승인받아야 한다.
3. 그 전에는 원격 재실행/PN 계산/gate 해제 없음.
