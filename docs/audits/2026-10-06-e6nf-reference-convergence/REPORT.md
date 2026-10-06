# E6N-F 완료: 공식 1D API 재사용 및 PN 기준해 refinement 안정성

## 결론

`REFERENCE_CONVERGENCE_PASS`, 19개 항목 통과다. 기존 1,545-node 기준의 각 구간에 midpoint만 추가한 3,089-node 공식 DEVSIM 1D 메쉬로 비교했다. 기존 노드 좌표를 정확히 유지하고 보간 없이 비교했다.

이 대칭 PN 문제에서 지정한 2분할에 대한 수치 안정성을 확인했다. 무한 refinement의 수렴 증명, 연속해 오차 상한, 일반적인 2D PN 또는 제작 공정 검증은 아니다. 기존 N0/N1 불합격, N2의 이전 보간 비교 불합격은 원문 그대로 유지한다. production gate는 해제하지 않았다.

## 절차와 코드 재사용

- 시작 SHA `b3db789`, 브랜치 `claude/remote-runner`.
- PLAN 단독 커밋 `a6835a5`, LF 정규화 SHA `352a71f1cd042968b370a455bd9b163300b1feeceb62f7c617ddc21ad2567051`.
- 계산 코드/요청 커밋 `696c435a3894b3911bffbf3973f0ea422f4d8fff`.
- E6N-E의 `build_device`, `canonical_audit`, `run_device`, observer, strict cleanup을 그대로 재사용했다.
- 공식 `create_1d_mesh`/`add_1d_mesh_line` 경로만 사용했다. 새 remesher, SG 전류식, Poisson/연속방정식 구현을 만들지 않았다.
- 물리 파라미터, 도핑, 접점, 바이어스, solver 기준은 E6N-E와 동일했다.
- Serena는 연결 도구가 없어 rg/직접 읽기로 대체했다.
- 로컬은 순수 배열·합성 검사만, 엔진 import/solve는 GitHub-hosted Windows에서만 수행했다.

## 원격 실행

run: https://github.com/tjrgns1753-create/tcad/actions/runs/37430543401

artifact `remote-run-43`, source SHA `696c435a3894b3911bffbf3973f0ea422f4d8fff`.
GitHub-hosted Windows, 실제 solve 프로세스 감독 시간 4.515초이며 패키지 설치를 포함한 Actions job은 54초였다.
샘플링된 프로세스 트리 working-set 최대 120,827,904 bytes. 샘플 사이의 절대 최고치는 측정하지 않았다.

순방향 solve 8회, 역방향 6회 = 시도·성공 각각 14회다. solve 실패·snapshot 실패 0, 두 장치 cleanup 정상이다. 신규 2D solve는 0회다.

## 실제 수치 결과

| 항목 | 최대 변화 | 사전 기준 |
|---|---:|---:|
| 순방향 전류 | 0.00731793% | 1% |
| 역방향 전류 | 0.0147406% | 2% |
| 캐리어 농도, 원래 노드 비교 | 0.323825% | 1% |
| 전위 | 0.102159 mV | 0.258872 mV (0.01 Vt) |
| 같은 coarse 구간의 평균 전계/peak | 0.0186303% | 2% |
| KCL 상대 오차 | 0.0192580% | 0.1% |

전계는 서로 다른 edge 중심값의 차이가 아니라 동일 coarse 구간의 양 끝 전위로 계산한 평균 기울기를 비교했다. fine mesh의 native ElectricField와 전위 차분 관계도 별도로 확인했다.

역방향 일부 전류의 격자 변화가 1e−11 수준이라는 사실을 높은 물리 정확도의 독립 증거로 과대 해석하지 않는다. 캐리어·전위 변화와 KCL도 함께 검사했고, 같은 solver와 구성방정식을 재사용한 비교라는 한계를 유지한다.

## 독립 검사 및 오류 차단

- `test_contract.py`: 합성 정상 대조군, 10개 증거 손상 반례, 2개 잘못된 격자 모두 기대한 결과. 로컬 engine import 0회.
- 반례: canonical unresolved, solve 누락, cleanup 실패, metadata 변화, 누락 전류, PLAN 불일치, 1 ULP 좌표 변경, 도핑 변경, carrier/field NaN.
- `verify_artifact.py`: 원격 output 5개 + log 1개의 byte SHA/크기 검사 통과.
- 실제 실행 source SHA/run id/runner와 원본 E6N-E 해시 확인.
- 원시 배열로 다시 계산한 result가 원격 result JSON 전체와 정확히 일치.
- 19개 검사의 실패 0, 기존 원본 evidence 및 PLAN 불변.

## 변경 파일과 범위

새 audit 파일: PLAN.md, convergence.py, test_contract.py, verify_artifact.py, REPORT.md, IMPLEMENTATION.patch, raw/ 및 .gitattributes.
원격 설정 변경: remote/profiles.py의 단일 allowlist 추가, remote/request.json의 이번 요청.
전체 구현 semantic diff는 IMPLEMENTATION.patch에 보존했다.

핵심 구현은 아래와 같다.

```python
fine = np.empty(3089)
fine[::2], fine[1::2] = x, x[:-1] + np.diff(x)/2
# 공식 엔진이 만든 native mesh가 이 좌표를 정확히 유지하는지 검사한다.
dr = R.run_device(dv, state, direction, fine, arrays, raw)
```

production 코드, tests/, 기존 gate, engine internals, main 변경 0이다. 전체 회귀는 실행하지 않았다. 새로운 숫자나 미지원 상태의 fallback도 없다. 코드/문서 공백 검사 RC=0, raw 증거는 -text -diff로 원본 바이트를 유지했다.

## 작업 방식 정리 및 다음 우선순위

기존 엔진/API와 실행기를 재사용한 작은 검사 1회로 이 기준해의 refinement 안정성을 확인했다. 이 대칭 PN 기준해에 대한 수치 조사 범위를 더 확장하지 않는다.

다음 사용자 기능 개선은 다음 순서로 좁힌다.
1. 측정 결과의 단위와 지원 범위 표기를 실제 출력 경로에서 일관되게 유지.
2. PN 측정 지원 범위를 production 경로에서 명확히 정의하고, 검증되지 않은 입력은 차단 유지.
3. 공정 후 geometry/material-instance/doping 상태 전달 개선. 엔진이 지원하는 공정 자체는 공식 API를 재사용.

이번 결과만으로 임의 공정 순서나 모든 PN 메쉬를 허용하지 않는다. 산화/활성화 등 미지원 공정을 실제 계산한 것처럼 표시하지 않는 원칙은 계속 적용한다.
