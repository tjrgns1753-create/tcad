# E6N-A 후보별 자원 감독 구현

## 판정 및 범위

사용자가 승인한 후보별 별도 프로세스/0.5초 감시/Job Object 종료 구조를 감사 실행기에 연결했다.
로컬의 짧은 Python 자식 프로세스 및 합성 child 증거만 검증했다.
DEVSIM/ViennaPS import0, 실제 solve0, 원격 실행0, 전체 회귀0, 커밋/push0이다.
PN 정확도/메쉬 수렴/이산 비환원성/원격 지원을 승인하지 않는다.

## 시작 상태와 Serena 조사

- 저장소: PycharmProjects/tcad/tcad. HEAD509f5e50db8cab3ae59c36c2c4693f27ade30567.
- 기존 tracked 변경: 감사 .gitattributes/diagnostics.py/run_e6na.py, +93/-21.
- 기존 untracked 증거와 보완 파일을 보존했다. production 변경은 이번 범위가 아니다.
- 이 세션에는 Serena tool이 노출되지 않는다. rg/직접 읽기로 대체했다.
- 조사 심볼: execute/_execute/_execute_import_audit/cleanup, remote PROFILES의 e6na_import_reduction.
- 실행 진입점은 profile의 고정 entry와 main이다. 기존 test_review_followup/test_contract가 preflight와 trap을 호출한다.
- 기존 단일 process 구조는 후보 loop 안의 사후 시간/peak_ws 검사뿐이었다.
- 부모 경로는 엔진 import를 하지 않고 child만 기존 공식 importer를 사용한다.
- 전체 프로세스 열거는 Get-CimInstance 권한 거부였다. 전체 시스템 계산0은 주장하지 않는다.
  이번 시험에서 소유한 Job PID 목록의 종료 후0은 직접 확인했다.

## 실제 변경과 semantic diff

이번 변경만 재구성한 전체 patch: RESOURCE_INTEGRATION.patch.
SHA256: 0d2d631e431c904c2ad5516151018639f2838e46bb5738a30e2a632bb419dcf4.
이 patch는 HEAD에 기존 FOLLOWUP_CHANGES.patch와 FLUX_GUARD_CHANGES.patch를
메모리에서 순서대로 적용해 복원한 시작 상태와 비교했다. 기존 수정은 이번 변경으로 계산하지 않았다.

### run_e6na.py

- import: resource_supervisor의 supervise/require_elements/payload_check/TOTAL_CAP 추가.
- RESOURCE_CONTRACT_SHA: 승인 후 고정한 새 계약 문서의 LF-normalized SHA를 상수로 추가.
- execute: 기존 PLAN 검사 뒤 새 resource 계약 검사, 불일치면 _execute callback0.
- _execute: 기본 진입은 _supervised_execute, 고정 child argv만 _execute_candidate.
- _supervised_execute: 부모가 후보별 감독, child 증거와 NPZ SHA 검사, 실패 이후 NOT_RUN.
- _execute_candidate: 기존 _execute 엔진 경로를 분리; 후보명이 유효해야 엔진 감사 단계로 전달.
- _execute_import_audit: 후보별 output 폴더/단일 후보 선택/생성 전후400000 검사.
- size hunk: raw arrays + JSON, NPZ uncompressed container 및 serialized 크기 재검사.

핵심 경계:
```diff
- return preflight(_execute)
+ return preflight(approved_resource_boundary)

+ monitor = supervise([...,'--candidate',lv], ROOT, out/(lv+'.log'), total_deadline=deadline)
+ rec['solve_attempts'] = None
+ if monitor['status']!='COMPLETED' or not monitor['cleanup_ok']:
+     raise ValueError('SUPERVISOR_BLOCKED')

+ require_elements(nt, lambda: None)
  p,t,tags,_=R.structured_lateral_refine(...)
+ require_elements(len(t), lambda: None)
```

### 신규 resource_supervisor.py

- require_elements/payload_check: 요소·출력 예산의 사전/사후 검사.
- Job.__init__/assign/pids/memory/stop/close: Win32 공식 API로 소유한 프로세스 트리만 관리.
- supervise: 시작 직전부터 시간 측정, Job 연결 후 release, working-set 합계 주기 감시, finally 정리.
- bootstrap: release가 없으면 대상 코드 미실행; 30초 뒤 실패 종료.
- kill-on-close는 OS 안전장치다. commit은 별도 관측하며 6GiB commit 강제 제한으로 주장하지 않는다.

### 나머지 변경 구간

- remote/profiles.py 입력 목록: guard/reference/supervisor/계약/test 의존 파일5개 추가. request 변경 없음.
- .gitattributes: RESOURCE_INTEGRATION.patch 바이트 보존 지정1줄 추가.
- test_resource_supervisor.py 신규: 짧은 OS 프로세스 시험, 요소·출력 상한 검사.
- test_supervised_entry.py 신규: 부모의 증거7종과 자원 계약 변조 callback0 검사.
- RESOURCE_EXECUTION_CONTRACT.md 신규: 이번에 승인한 운영 조건만 고정. 기존 PLAN 무변경.

## 로컬 검증

test_resource_supervisor.py RC0:

| 시험 | 결과 |
|---|---|
| 정상 종료 | COMPLETED, rc0, cleanup true |
| 비정상 종료 | FAIL, rc7, cleanup true |
| 0.8秒timeout | TIMEOUT, cleanup true |
| 손자 프로세스 생성 후1.5초 timeout | spawned 로그 확인, Job PID0, cleanup true |
| 전체 deadline 이미 경과 | TIMEOUT, Popen0 |
| Job 연결 실패 주입 | FAIL, 대상 marker0, bootstrap 정리 |
| 극소 memory cap | FAIL, WORKING_SET_RESOURCE_CAP. 실제 OOM 시험 아님 |
| cleanup 예외 주입 | 정상 rc0이어도 FAIL, cleanup false |
| 요소400001/파일121MiB | callback0/출력 거부 |

운영 감시 간격은0.5초이며 짧은 OS 시험은0.05초로 실행했다. 시험과 운영을 구분한다.

test_supervised_entry.py RC0:
정상3후보는 통과, INCONCLUSIVE는 다음 후보 NOT_RUN, timeout/누락/해시 불일치/
cleanup false/solve attempts1은 FAIL과 후속 NOT_RUN. timeout/누락 attempts는 null.
자원 계약 변조는 _execute callback0.
이는 합성 child 증거이며 실제 NPZ 물리 내용이나 native import 시험이 아니다.

기존 test_review_followup.py/test_flux_source_contract.py/test_contract.py도 각각 RC0.
기존 transition fixture의 INCONCLUSIVE를 유지했다. 양성 NONINVARIANCE_WITNESS의
전체 analyze 기하 fixture는 아직 미완성이다. 부모의 합성 PASS는 그 대체 증거가 아니다.

## 불변 증거

- PLAN.md: a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103
- raw/remote-run-33/summary.json: b6fee95b08db6a927d86f84c92192515a634dbb225c2dcd45d10ddb7c78618c4
- raw/remote-run-33/run.log: fc7b639da4b7f4d1df7806fa7df32d28c85c9727fa151d26bdb0084f427f23f3
- 기존 FOLLOWUP/FLUX patch 변경 없음. production/physics gate/기존 PLAN 변경 없음.

## 남은 한계와 다음 승인 조건

- 로컬 Windows Job은 실측했지만 GitHub-hosted 기존 Job과의 중첩 호환성은 미확인.
- 실제 Python3.11 호환성은 미확인. 새 원격 실행 없음.
- working set은0.5초 sample이며 순간 peak를 억제하는 할당 강제 상한이 아니다.
- OS 종료 후 PID0과 엔진 delete 성공은 별도 증거다. timeout 때 엔진 finally는 보장하지 않는다.
- 기존 원격 wrapper도1800초에 멈추므로 전체 deadline 직전 보고·정리에는 경합이 남는다.
  wrapper의 계산 외 정리 유예를 별도 승인 없이 늘리지 않았다.
- 양성 기하 대조군·artifact 독립 검증·위 원격 호환성 승인 전 원격 재실행하지 않는다.

Windows 근거: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
