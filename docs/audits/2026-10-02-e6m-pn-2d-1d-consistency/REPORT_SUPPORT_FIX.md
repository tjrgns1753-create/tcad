# E6M 보완 완료 보고 — 판정기 무결성 및 실행 전 차단
## 범위와 판정
기준 HEAD: `98ba83574ddb3ede0f743b3ab38f369836e65b54`, 브랜치 `claude/remote-runner`.
이번 작업은 엔진 없는 로컬 검증 코드 보완이다. 기존 42회 solve는 재실행하지 않았다.
DEVSIM/ViennaPS import, mesh import, solve, 전체 회귀, production 물리 코드 및 gate 변경은 모두 0회다.
Serena 도구가 연결된 목록에 없어 rg/직접 읽기로 조사했다. 적용되는 저장소 CLAUDE.md와 사용자 AGENTS.md를 읽었다.
원래 PN 결과를 물리적으로 틀렸다고 재분류하지 않는다. 새 검사가 과거 증거에서 입증할 수 없는 사실은 별도로 구분한다.

## 1. 수정 전 네 문제 재현과 수정 후
원본을 메모리에 복사해 변조했다. 디스크의 원본은 바꾸지 않았다.
기준 커밋의 판정기·metrics를 git blob에서 함께 읽어 이전 동작을 재현했다.

| 반례 | 수정 전 | 수정 후 |
|---|---|---|
| PLAN 해시를 f 64개로 교체 | 모든 범주 PASS | EVIDENCE_INTEGRITY_FAIL |
| L2 역방향 NodeVolume 전체 0 | 모든 범주 PASS | EVIDENCE_INTEGRITY_FAIL |
| L2 역방향 도핑 세 배열 전체 0 | 모든 범주 PASS | EVIDENCE_INTEGRITY_FAIL |
| L2 canonical_unresolved=1 | 모든 범주 PASS | G2 FAIL, 종속 물리 비교 차단 |

실제 출력은 `rejudge_support_result.json`, 재현 스크립트는 `rejudge_support.py`다.

## 2. 변경 파일·심볼과 semantic diff
- `scripts/e6m_metrics.py`: require_canonical, canonical_checks, guarded_audit, array_contract 추가.
  전체 canonical 검사·유한 수치 확인 후에만 writer와 sweep을 호출한다.
  각 direction의 원시 기하, NodeVolume, 도핑, edge 및 전기장 대응을 독립 검사한다.
  기존 compute의 물리 계산식은 유지했다.
- `scripts/judge_e6m.py`: 판정기 버전 2, 실제 PLAN SHA 상수 대조, 방향별 array_contract를 무결성 경계에 연결.
  역방향 canonical 기록 부재와 불량 기록을 구분한다.
- `tests/integration/test_pn_2d_1d_consistency_real.py`: 실제 각 device의 전체 노드에서 canonical_checks 실행.
  guarded_audit의 writer/sweep callback 안에 첫 도핑 쓰기와 sweep을 배치했다.
  이번에는 이 엔진 테스트를 실행하지 않았다.
- `tests/unit/test_e6m_judge_mock.py`: 양 방향 배열 변조, summary 동시 재계산, PLAN, 미해결 상태 차단 테스트 추가.

전체 변경은 `SUPPORT_FIX.patch`에 zero-context unified diff로 보존했다.
감사 helper와 테스트 외에 `tcad/`, GUI, 엔진 내부 구현은 변경하지 않았다.

## 3. 0 write / 0 sweep / 0 solve
실제 실행기가 사용하는 guarded_audit에 엔진 없는 callback spy를 연결했다.
unresolved=1, checked=0, checked<n, mismatch=1 각각에서 writer=0, sweep=0, solve callback=0.
정상 대조군은 write 후 sweep 순서로 호출됐다.
canonical query의 net=None/NaN/bool도 거부한다. donor/acceptor뿐 아니라 net도 검사한다.
이 결과는 실행 전 helper의 차단 증거다. 실제 엔진 실행을 이번에 관측했다는 뜻은 아니다.

## 4. 순·역방향 배열 계약
L0/L1/L2 × fwd/rev의 6개 원본 배열에서 새 계약 위반은 0건이었다.
좌표 순서가 다를 때는 좌표 대응표로 source mesh와 native mesh를 연결하고 topology를 대조한다.
NodeVolume은 실제 삼각형 면적과 합계를 재대조하며 0/NaN/음수/shape 위반을 거부한다.
도핑은 각 device의 실제 x 좌표로 재계산하고 Donors−Acceptors=NetDoping을 요구한다.
edge 길이는 끝점 거리와 대조한다. ElectricField는 각 bias의 Potential과 방향 있는 edge 길이로 재계산한다.
임의 edge의 값을 x 성분이라고 부르지 않는다.
양 방향 각각 변조한 12종 입력을 summary 유지/재계산 두 경로로 검사해 48개 배열 반례를 차단했다.

## 5. PLAN 해시
실제 예상 SHA는 검사 대상 JSON과 독립적인 상수다:
`5aeb9dc28bf79f82404d728f9507c6a8208c531cc9bff32829cbf46e58e5410f`.
PLAN 텍스트 바이트의 CRLF를 LF로 정규화하고 SHA-256을 계산한다. 원본 PLAN은 수정하지 않았다.
합성 테스트는 명시적인 별도 예상 해시를 전달하며 실제 증거의 기본 검사값은 약화하지 않는다.
다른 유효한 64자리 해시, 누락 및 형식 위반은 모두 차단된다.

## 6. 원본 재판정과 과거 기록 한계
이전 판정기: 무결성 및 G1~G9 모두 PASS.
새 판정기: 무결성 PASS, G1 PASS, G2 NOT_EVALUATED, G3 PASS,
G4~G9 BLOCKED_GATE_OR_AUDIT_DOPING.
G2의 제한은 역방향 실행 전 canonical 검사 기록이 과거 원본에 없기 때문이다.
순방향은 RECORDED_VALID, 역방향은 NOT_RECORDED다.
역방향 좌표·도핑·NodeVolume·전기장은 지금 원시 배열로 재검사했고 통과했다.
이 사후 배열 검사로 과거 실행 전 canonical query가 수행됐다고 주장하지 않는다.
따라서 새 종속 판정을 보류하되, 원본 물리 수치의 오류나 미해결 상태에서 계산했다는 주장으로 바꾸지 않는다.

## 7. 원본 해시 불변
- E6M JSON: `1a0e3fc7f9876119a34e8994b9e179d9584a5c1deca9819dc198e493e267391d`
- E6M NPZ: `6ec993c6f5201da46f901e11a7cc62a2edb921c5f05d946371be53c6338c174b`
- E6K JSON: `97e7e4845796b2899555baab458c65a5e68fc84c1f31d0c7a1f8f80b2a015e57`
- E6K NPZ: `65c1a938a6521a14897ed2ec2dfc04178e254248e5a2778f9e0b7d1a56e1c8e2`
- E6M PLAN: 위 §5와 동일.

기준 커밋 blob과 현재 원본 바이트의 동일성 및 위 해시를 확인한다.
E6K/E6L 과거 판정 문서·원본 JSON/NPZ/log는 수정하지 않았다.

## 8. 실행한 엔진 없는 테스트
- test_e6m_judge_mock.py: PASS, 강화된 합성 반례와 callback trap 통과.
- test_e6l_correction_mock.py: PASS.
- test_pb_equilibrium_mock.py: PASS.
- test_pn_judge_integrity_mock.py: PASS, 기존 279개 삭제 반례 통과.
- 원본 읽기 전용 재판정: PASS(스크립트 정상 종료), 위 §6의 제한 판정 그대로 기록.
수정한 Python 네 파일은 AST parse 통과, LF only다.
테스트 종료 코드 0은 검증 코드가 기대한 판정을 냈다는 뜻이며 PN 물리 승인 점수가 아니다.

## 9. 다음 단계
`PLAN_E6N_DRAFT.md`는 기존 E6G 전이 빌더 지원조건과 다음 실험 초안이다.
실제 후보 mesh 생성·DEVSIM import·solve는 수행하지 않았다.
기하 및 조립 가중치 검증으로 후보가 실제 1D 이산 환원을 벗어나는지 먼저 확인해야 한다.
생성 가능성·자원·TRANSITION_ASPECT가 아직 미확정이므로 원격 실행 승인이 아니다.
production PN gate는 유지한다.
