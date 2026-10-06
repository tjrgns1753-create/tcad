# E6N-D: 전이 메쉬 PN 바이어스 검증

## 1. 판정

첫 두 레벨 파일럿은 **PILOT_NOT_APPROVED**다. 28회 실제 solve가 전부
수렴했지만, 사전 고정한 내부 전위·캐리어·전계 분포 기준 일부가 실패했다.
종료 RC=1은 계산 중단/오류가 아니라 물리 비교 실패를 정상적으로 반영한다.
전류만 잘 맞는다고 PN 전체를 승인하지 않는다. Production gate는 그대로다.
추가 N2 진단은 별도의 사후 확장 계획으로 실행하며 첫 판정을 덮어쓰지 않는다.

## 2. 물리 방향성과 근거

이번 질문은 “실제 도핑 상태를 공식 장치 계산에 전달해 물리적으로 맞는
전류와 내부 상태를 얻는가?”다. 새 물리 모델이나 그래픽을 만든 것이 아니다.
DEVSIM 공식 diode 예제(https://devsim.net/examples_diode.html) 및
Scharfetter/Gummel (1969), DOI 10.1109/T-ED.1969.16566에 대응하는 기존
Poisson+드리프트-확산 경로를 그대로 호출했다. SRH 수명, 이동도, 온도,
도핑과 경계조건은 기존 1D 참조와 같고 native parameter로 대조했다.
1D 참조는 같은 모델의 수치 기준이지 실측 제조 논문의 독립 검증이 아니다.
본 문제는 y 방향으로 균일하다. 1D 환원은 올바른 물리 대칭이며, y 불균일은
추가 물리 효과가 아니라 우선 수치 오차 후보로 취급한다.
평형 DD 초기화의 전류 0/질량작용 항등식을 독립 검증 여러 건으로 세지 않았다.

## 3. 고정 조건과 실제 실행

- 단일 Si: 40 um × 0.1 um, 접합 x=0, NA=ND=1e17 cm^-3, ACTIVE, 300 K.
- 기존 E6G 구조화 전이 빌더만 사용; center=0, half-width=0.1 um.
- N0: 8037 nodes/15264 triangles, N1: 31173/60736.
- 각 메쉬마다 fresh forward/reverse 장치; 장치마다 모든 node canonical 검사.
- Forward 0.1~0.6 V 6개, reverse −0.25~−1 V 4개; 장치 초기화 각각 2 solve.
- 총 4개 장치/28회 시도/28회 성공; solve/snapshot 실패 0, cleanup 전부 성공.
- 전류 단위는 A/cm, 높이로 나눈 J는 A/cm². 실제 두께를 가정한 A가 아니다.
- 실행 위치 GitHub-hosted Windows, source `0aae0a35bcfa38ceca374556199a451dd01c3076`.
- Run https://github.com/tjrgns1753-create/tcad/actions/runs/37424050614,
  artifact remote-run-40, 원본은 `raw/`에 바이트 그대로 보존했다.
- 물리 자식 실행 N0 13.031초, N1 49.094초; 설치 시간은 별도다.
- sampled process-tree working set 최대 N0 240177152 bytes, N1 666808320 bytes.
  순간 메모리 hard cap으로 과장하지 않는다. Windows Job으로 owned tree를 정리했다.
- PLAN 선행 커밋 `31d27a3`, LF-normalized SHA
  `a11d5440fdfaf4e2e0e58be464a62080f08e08831427e611677338f69c22768d`.

## 4. 통과와 실패를 분리한 수치

| 항목 | 결과 | 해석 |
|---|---:|---|
| Production gate 호출 | 4개 장치에서 거부, doping write/solve attempt 0 | 안전 계약 유지 |
| canonical 검사 | 각 장치 실제 node 수와 일치, unresolved/mismatch 0 | 누락한 역방향 기록도 이번에는 직접 측정 |
| topology/면적/NodeVolume/접점 | 통과 | 물리 정확도의 필요조건이지 충분조건 아님 |
| 2D-1D 전류 최대 상대차 | 0.78231% | 사전 forward 1%, reverse 2% 이내 |
| 최대 KCL 상대차 | 0.007335% | 사전 0.1% 이내 |
| N0→N1 전류 최대 상대차 | 0.06524% | 전류 메쉬 민감도 작음 |
| 최대 y 전위 차 | 17.8810 µV | 사전 10 µV 초과 |
| 수평 edge 전계 최대 오차 | 3.25876% | 사전 2% 초과 |
| 원격 판정 | 84 checks 중 11 profile checks 실패 | 전체 미승인 |

독립 재검토에서 native 전계와 `(psi@n0-psi@n1)/EdgeLength`의 관계 및
edge 길이/좌표 일치를 18개 검사로 추가 확인했다. 전체 102개 검사 중
동일한 11개만 실패한다. 전계 배열 자체의 잘못된 저장을 원인으로 삼지 않는다.
검사기를 사후 강화했지만 수치 임계값, 물리 계산, 원격 원본 판정은 바꾸지 않았다.

## 5. 보간 오차와 실제 이산화 차이 분리

`POST_HOC_PROFILES.json`은 사후 진단이며 승인 판정을 바꾸지 않는다.
1D 참조에 없는 새 x노드는 선형 전위/log-carrier 보간이 필요하므로 보간 오차가
포함된다. 동시에 정확히 동일한 x좌표만 비교해도 다음 차이가 남는다.

| −1 V 비교 | N0 | N1 |
|---|---:|---:|
| 전체 전위 최대 차 | 0.782490 mV | 0.369167 mV |
| 공통 x 전위 최대 차 | 0.465242 mV | 0.290438 mV |
| 전체 carrier 최대 상대차 | 13.5982% | 4.29453% |
| 공통 x carrier 최대 상대차 | 7.61410% | 1.98160% |

따라서 “전부 보간 탓”은 반증된다. 정밀화에 따라 줄어드는 이산화 차이가
존재한다. 이를 production 물리식 오류로 확정하지도 않았다. 같은 L의 1D
메쉬도 유한 해상도이고 전이 메쉬가 x중점을 추가해 이산화가 달라진다.
사후 L2 참조와 전위 차는 N0 0.259329 mV/N1 0.117528 mV로 더 작지만,
원래 사전 기준을 바꾸는 근거로 사용하지 않는다.
소수 캐리어는 작은 절대 변화에도 큰 상대차를 보일 수 있고 SRH와 DD 내부
상태에 중요하므로 단자 전류가 맞는다는 이유로 버리지 않는다.

## 6. 코드 변경과 호출 경로

Production `tcad/`, `tcad_2d_stagewise.py`, 기존 tests는 무변경.
Serena는 이 세션 도구에 없어 rg/직접 읽기 fallback. 호출 경로:
`pilot.worker` → 기존 `canonical`/`write_mesh` → 공식 import → 실제 apply_doping
gate 거부 → canonical query → audit public node_model/set_node_values → 기존
run_pn_junction_iv_sweep. 기존 Obs를 재사용해 시도/성공/snapshot 실패를 분리했다.
새 audit 스크립트가 production의 우회 진입점으로 등록되지는 않는다.
각 장치 finally에서 기존 strict cleanup을 사용하며 다음 solve에 장치가 누출되지 않는다.

실제 semantic 변경:

- `pilot.py::require_plan/worker/main`: 실행 전 SHA 검사, 실제 메쉬 생성/도핑/solve/
  snapshot 저장, Windows Job 실행 경계. 기존 production 함수는 호출만 한다.
- `judge.py::evaluate_device/judge`: 필수 기록/좌표/topology/canonical/단위/parameter/
  current/profile/mesh 비교; 누락이나 실패를 PILOT_NOT_APPROVED와 RC=1로 전달.
- `test_contract.py`: 보존된 과거 데이터의 합성 wrapper 정상 대조군과 13개 손상
  반례, PLAN trap, 누락 증거 차단. 합성 canonical 기록을 실제 증거로 backfill하지 않는다.
- `verify_artifact.py`: 실행 source SHA, 모든 출력의 바이트 해시, 실제 RC와
  재판정 일치; 원격 summary 성공만으로 승인하지 않는다.
- `analyze_profiles.py`: 공통/추가 x를 분리하는 읽기 전용 사후 분석.
- `remote/profiles.py/request.json`: allowlist 실행 등록, 엔진 정보 자동 import는 끔.

전체 첫 구현 patch는 `IMPLEMENTATION.patch`. 최종 누적 diff는 별도
`FINAL_CHANGE.patch`로 보존한다. 새 파일이므로 모든 hunk는 파일 추가다.
주요 실행 경계 원문:

```python
require_plan()  # 엔진 준비/메쉬 생성보다 먼저 실행한다.
M.require_canonical(dr['canonical_audit'],len(x))
return 0 if result['status']=='PILOT_PASS' else 1
```

## 7. 검증 범위와 미검증

정상 wrapper + 13 손상 반례 + PLAN 불일치 + 누락 증거 검사는 로컬 엔진 없이
통과했다. 원격 artifact 9개 파일(log 포함)의 바이트 SHA/크기를 모두 검증했고
원래 수치/판정과 재계산이 일치했다. 원본 N0/N1 계산 재실행은 하지 않았다.
전체 regression, GUI 표시, 제조 공정 연속성, 산화 지원, 다른 도핑/기하/접점,
일반 PN 수렴, gate 해제, main 병합은 이번 결과가 검증하지 않는다.

## 8. 세 번째 메쉬 확장

`PLAN_FINE.md`를 `740ab8b` 독립 커밋으로 고정했다. 이 사후 확장은 첫
미승인 결과를 숨기지 않는다. N2 122761 nodes/242304 triangles만 새로 계산한다.
Source `7b2d2178597ef042fcd9b068df2018a797dafa1d`,
run https://github.com/tjrgns1753-create/tcad/actions/runs/37424675525.
결과와 독립 검증은 아래 완료 보완에 기재한다.

### 세 번째 메쉬 완료 보완

- N2: 122761 nodes/242304 triangles. 실제 14회 시도/14회 성공,
  solve/snapshot 실패 0. fresh forward/reverse의 canonical 및 gate 검사 모두 통과.
- 실행 328.016초, sampled tree working set 2333474816 bytes,
  tree commit 2735927296 bytes. cleanup 성공, 시간/메모리 상한 미초과.
- Artifact remote-run-41, 원시 파일 `raw_fine/`. log 포함 6개 파일의 크기와
  SHA를 원격 summary와 독립 대조했고 수치/판정 재계산도 완전히 일치했다.
- 판정 **FINE_PILOT_NOT_APPROVED**, 실제 원격 RC=1. 실패는 정확히
  `L2_rev_profile_-0.5`, `L2_rev_profile_-1.0` 두 항목이다.
- N2의 forward 전류 기준 최대 차 0.024684%, reverse 최대 차 약 1.75e-11%.
  전위 최대 차 0.223624 mV, y spread 최대 1.193984 µV, 수평 edge 전계 최대
  차 0.791780%: 모두 사전 기준 이내다. 역바이어스 정공 차 1.21827%/1.39232%는
  사전 1%를 넘는다. 다른 전자/정공/전위 항목은 통과한다.
- 총 새 물리 solve 42회, 6개 fresh 장치. N0/N1은 추가 실행하지 않았다.

| −1 V에서 최대 carrier 상대차 | N0 | N1 | N2 |
|---|---:|---:|---:|
| 전체 node | 13.5982% | 4.29453% | 1.39232% |
| 정확한 공통 x node | 7.61410% | 1.98160% | 0.725682% |

세 번째 메쉬의 남은 실패 최대값은 추가 x좌표에서 발생한다. 이는 reference
보간 오차가 포함된다는 근거이지 “실제로 정확하다”는 증명은 아니다.
앞선 두 메쉬는 공통 x에서도 실패했으므로 모든 실패를 보간 탓으로 묶지 않는다.
유효한 다음 검증은 N2의 실제 unique x좌표로 공식 1D 기준을 새로 계산해서
보간 없는 비교를 만드는 것이다. 기존 42회 2D solve를 반복하거나 기준을
완화하는 것보다 계산량과 인과 분리가 낫다. 같은 격자의 비교도 실험적 제조
검증을 대체하지 않으며 production gate를 자동으로 해제하지 않는다.

### 무변경 및 최종 검증

세 원격 source/사전 PLAN/최종 리뷰 source를 구분한다. 추가 review 검사는
배열 관계 및 기존 결과 해시/점 수 확인만 강화했고 결과 허용오차는 그대로다.
최종 local 정상 wrapper, 13 손상 반례, 원래/추가 PLAN 불일치, 누락 증거 차단은
엔진 없는 실행으로 통과했다. Artifact 전체 15개 파일의 바이트 해시를 확인했다.
`git diff 300e6f1 -- tcad tests tcad_2d_stagewise.py`는 비어 있다.
기존 원본 E6K/E6M 증거와 PLAN 변경도 없다. 전체 regression은 실행하지 않았다.

## 9. 전체 변경 hunk와 리뷰 포인터

최종 소스 patch SHA-256:
`1c38ef94400f543760131c92c685160af59c8c0654852232e9e52106b0de2fc9`.
첫 구현 patch SHA-256:
`993cb8c84fbcea3650fc74d0a25578323e9c7e7f3de9f8b2bfed5b719a0bedf3`.
범위는 새 audit 코드와 remote 실행 등록이다. 모든 hunk를 아래에 열거하고,
무생략 원문은 `FINAL_CHANGE.patch`를 확인한다.

| 파일 | hunk | 심볼/최종 위치 | 핵심 추가 원문 |
|---|---|---|---|
| analyze_profiles.py | `@@ -0,0 +1,40 @@` | analyze:11 | `shared = np.isin(x,r['x'])` |
| fine_pilot.py | `@@ -0,0 +1,82 @@` | preflight:16, evaluate:23, main:62 | `if sha!=FINE_SHA: raise ValueError('FINE_PLAN_HASH_MISMATCH')` |
| judge.py | `@@ -0,0 +1,140 @@` | evaluate_device:9, judge:111 | `M.require_canonical(dr['canonical_audit'],n)` |
| pilot.py | `@@ -0,0 +1,157 @@` | require_plan:24, worker:35, main:132 | `gate.install()` / `gate.restore()` / `cleanup(dv,name,mesh,dr)` |
| test_contract.py | `@@ -0,0 +1,76 @@` | main:14 | `assert not all(c['pass'] for c in checks)` |
| verify_artifact.py | `@@ -0,0 +1,48 @@` | main:14 | `raise ValueError('RAW_ARTIFACT_HASH_FAIL')` |
| remote/profiles.py | `@@ -11,6 +11,41 @@` | PROFILES | `"engine_info": False` / `"timeout_s": 930` 및 `1830` |
| remote/request.json | `@@ -1,7 +1,7 @@` | request | 기존 profile→`"e6nd_pn_fine_diagnostic"` |

기존 함수의 semantic 제거는 없고, remote 요청만 이전 재검증에서 새 파일럿으로
변경했다. 첫 실행 후 추가한 검사는 edge 좌표/길이/전계 관계, 이전 N1 증거의
해시와 비교 점 수다. 어떤 수치 기준도 완화하지 않았다. 추가 검사는 원격
실행 source와 최종 리뷰 source의 차이로 명시하고 raw 데이터를 로컬에서
재판정한다. 이에 따른 추가 solve는 없다.
