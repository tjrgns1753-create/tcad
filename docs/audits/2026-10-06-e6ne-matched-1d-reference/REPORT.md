# E6N-E: 정확히 같은 x좌표의 1D 기준으로 N2 PN 재검토

## 1. 결론과 승인 범위

판정은 `MATCHED_REFERENCE_PASS`이다. 기존 N2 2D 원시 배열을 수정하거나 다시 계산하지 않고, 그 메쉬의 서로 다른 x좌표 1,545개를 그대로 공식 DEVSIM 1D 메쉬에 넣어 새 기준해를 계산했다. 보간 없는 비교 28개 항목이 모두 통과했다.

이것은 **대칭 PN, 고정된 물리 파라미터와 바이어스, 이 N2 메쉬의 1D/2D 수치 일관성**을 확인한 결과다. 논문 또는 실험과의 전체 소자 특성 일치, 일반적인 비평면 2D PN, 제작 공정 시퀀스, 메쉬 수렴의 승인이 아니다. `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` 및 기존 production gate를 그대로 유지한다.

## 2. 작업 전 고정한 조건

- 시작 HEAD: `aadeb907347f4513155451f26daec7c35ca5aa4d`, 브랜치 `claude/remote-runner`.
- PLAN 단독 커밋: `9d8c801`, 계산 코드보다 먼저 고정했다.
- LF 정규화 PLAN SHA-256: `631e73ffd7b004f2e0d789d20201360d6f02d5d66b7b4e68fc802d2c842c117b`.
- 계산 코드 커밋: `ef0140593a0190cb974ec5a2c79cc7abda7ed212`.
- 기존 N2 순·역방향의 실제 x좌표는 정확히 일치하며, 범위는 −0.002~+0.002 cm이다. 노드 추가·좌표 이동·보간은 금지했다.
- 기존 PN 물성, 도핑, 온도, 접점, 이동도, SRH 수명 및 solve 종료 기준을 변경하지 않았다.
- 전류·전위·캐리어·전계 허용 기준은 결과를 보기 전에 PLAN에 고정했다. 기존 기준보다 완화하지 않았다.
- Serena 연결 도구가 없어 `rg`와 직접 읽기를 사용했다.

## 3. 물리 모델 및 공식 API와의 대응

DEVSIM 공식 diode 예제의 `create_1d_mesh`, `add_1d_mesh_line`, `add_1d_contact`, `add_1d_region`, `finalize_mesh`, `create_device`를 사용했다. 각 mesh line은 실제 N2 x좌표이고, 엔진이 만든 노드의 수와 좌표 집합을 solve 전에 정확히 대조했다. 이 검사를 통과해야 다음 단계로 진행한다.

공식 자료: https://devsim.net/examples_diode.html . 전류 이산화의 문헌 배경은 Scharfetter–Gummel, DOI `10.1109/T-ED.1969.16566`이다. 공식 예제나 이 논문의 존재 자체를 본 결과의 물리 검증으로 대신하지 않는다.

양쪽 계산은 같은 Poisson/전자·정공 연속방정식, SG 전류, SRH 재결합을 사용한다. 따라서 같은 격자에서의 일치는 서로 다른 물리 모델의 독립 검증이 아니다. 특히 평형 Boltzmann 초기화의 전류 상쇄·질량작용 관계를 Poisson 해 정확성의 별도 증거로 세지 않는다. 이번에는 비평형 순방향·역방향의 실제 전류와 공간 분포도 직접 비교했다.

엔진 내부 수정, signed override, 숫자 fallback, production gate 해제는 없었다. ViennaPS는 기존 입력 메쉬의 재료 enum을 읽는 용도였고 실제 공정은 실행하지 않았다.

## 4. 원격 실행과 실제 횟수

- GitHub Actions: https://github.com/tjrgns1753-create/tcad/actions/runs/37429019975
- artifact: `remote-run-42`, 원문은 `raw/`에 보존했다.
- 원격 실행 SHA: `ef0140593a0190cb974ec5a2c79cc7abda7ed212`.
- GitHub-hosted Windows X64, Python 3.11.9, DEVSIM 2.11.0, ViennaPS 4.6.2.
- wrapper 실행 시각: 2026-10-06 07:20:58.737752Z~07:21:03.078116Z, 4.34초. 패키지 설치 시간을 포함한 전체 Actions 시간은 아니다.
- 자식 프로세스 감독 시간 3.5초, 샘플링된 프로세스 트리 최대 working set 108,240,896 bytes. 샘플링값이지 연속적인 절대 메모리 최고치는 아니다.

| 장치 | 노드 | solve 시도 | 성공 | solve 실패 | snapshot 실패 | cleanup |
|---|---:|---:|---:|---:|---:|---|
| 균일 저항 단위 대조군 | 1,545 | 3 | 3 | 0 | 0 | 정상 |
| PN 순방향 | 1,545 | 8 | 8 | 0 | 0 | 정상 |
| PN 역방향 | 1,545 | 6 | 6 | 0 | 0 | 정상 |
| 합계 | 독립 장치 3개 | 17 | 17 | 0 | 0 | 모두 정상 |

신규 2D solve는 0회다. 기존 42회 2D 결과는 그대로 재사용했다. 모든 장치의 canonical 검사 노드 수는 1,545이고 unresolved 및 mismatch는 모두 0이다. 실제 production `apply_doping()`의 Donors/Acceptors/NetDoping 쓰기도 기록했다.

`summary.json`의 `devsim.status=NOT_IMPORTED`는 바깥 실행기가 사전 엔진 정보를 수집하지 않았다는 뜻이다. 자식 검증 프로그램의 실제 DEVSIM import/solve가 없었다는 뜻이 아니다. PLAN 검사보다 먼저 wrapper가 엔진을 불러오지 않도록 한 설정이다. 또한 전역 review SHA는 오래된 `023bcb90...`여서 `code_paths_identical_to_review_sha=false`다. 이를 true로 바꾸지 않았고, 이번 실제 계산 SHA를 별도로 검증했다.

## 5. 단위 대조군

production의 1D 결과 metadata는 여전히 `current_unit=None`이다. 임의로 A라고 가정하지 않고, 균일 ACTIVE donor 1e16 cm⁻³ 저항의 1 mV 응답을 `J=σV/L`, `σ=q(μn n₀+μp p₀)`와 비교했다.

- 해석 기준: 0.16000000000023998 A/cm².
- 실제 raw 접점 전류: 0.15999999999986808.
- 상대 오차: 2.32436e−12.
- KCL 상대 오차: 9.24746e−12.
- 사전 기준 1e−6을 모두 통과했다.

이 대조군이 이번 1D raw 전류의 A/cm² 해석을 지지한다. production 1D metadata가 이미 수정됐다고 주장하지 않는다. 2D A/cm 전류는 높이 0.1 µm로 나눠 A/cm²로 비교했다.

## 6. 보간 없는 PN 비교 결과

| 항목 | 전체 비교 최대값 | 사전 기준 | 결과 |
|---|---:|---:|---|
| 1D/2D 전류 상대 차이 | 1.10634e−8, 즉 0.00000110634% | 순방향 1%, 역방향 2% | 통과 |
| 캐리어 상대 차이 | 0.0303248% | 1% | 통과 |
| 전위 차이 | 7.84906 µV | 0.01 Vt = 약 258.872 µV | 통과 |
| 같은 x의 y 방향 전위 spread | 1.19398 µV | 10 µV | 통과 |
| 수평 edge 전계 차이/기준 peak | 0.0257127% | 2% | 통과 |

순방향 0.1~0.6 V, 역방향 −0.25~−1 V의 전류 부호·단조성·KCL을 검사했다. 평형 및 지정 비평형 snapshot에서 모든 노드의 Potential/Electrons/Holes를 비교했다. 전계는 같은 수평 edge 구간의 `(ψ0−ψ1)/length`와 비교했으며, 다른 위치의 전계 중심값을 보간해 같은 값인 것처럼 취급하지 않았다.

## 7. 이전 불합격과의 관계

이전 E6N-D의 N2 결과는 서로 다른 1D x격자의 캐리어를 보간해서 비교했고, −0.5 V와 −1 V의 Holes 차이가 각각 1.21827%, 1.39232%여서 지정 기준 1%를 넘었다. 이번에는 정확히 같은 x격자에서 전체 최대 캐리어 차이가 0.0303248%다.

이는 **이 N2의 이전 비교에서 기준 격자와 보간 방식이 불합격에 크게 기여했음**을 보여준다. 이전 수치를 삭제하거나 원본 판정을 소급 PASS로 바꾸지 않는다. 조밀한 다른 1D 해에 비해 같은 x의 1D 해 자체가 달라질 수 있으므로, 동일 x 비교가 연속 방정식에 대한 메쉬 수렴을 증명하지는 않는다. 앞선 N0/N1 공통 x에서도 실제 차이가 남았던 사실 역시 유지한다.

## 8. 독립 재검사와 false-green 검사

`verify_artifact.py`를 로컬에서 엔진 import를 금지한 상태로 실행했다.

- 5개 output 및 wrapper log, 총 6개 바이트 해시·크기가 summary와 일치했다.
- 원격 source SHA, run id, Windows runner, DEVSIM 버전을 확인했다.
- 기존 N2 원본 NPZ/JSON 해시와 PLAN LF 정규화 해시가 그대로였다.
- 원시 배열로 판정을 다시 계산했고 저장된 result JSON 전체와 정확히 일치했다.
- 비교 28개 모두 통과, 성공 및 시도 17회가 실제 record와 일치했다.
- 로컬 engine import/solve는 0회다.

`test_contract.py` 합성 정상 대조군과 15개 손상 반례, PLAN/원본 해시 불일치의 후속 callback 0회 trap 2개도 다시 통과했다. 반례에는 canonical unresolved, 누락 solve, cleanup 실패, 잘못된 단위/전류/도핑, 1 ULP 좌표 이동, 0 또는 NaN 배열, 바이어스 변경이 포함된다. 합성 PASS는 실제 PN 물리 결과로 세지 않는다.

독립 verifier를 처음 작성할 때 항목 수를 30개로 잘못 적어 assertion이 실패했다. 지정 방향·바이어스·snapshot에서 기대 항목 수를 직접 산정하도록 수정했고, 실제 28개임을 확인했다. 물리 판정기·수치·허용 기준·원시 증거는 이 과정에서 변경하지 않았다. 원격 solve 재실행도 하지 않았다.

## 9. 변경 파일과 semantic diff

- 새 `PLAN.md`: 계산 전 조건 및 범위 고정.
- 새 `common.py`: PLAN/원본 SHA와 정확 좌표 매핑.
- 새 `run_reference.py`: 공식 1D mesh 생성, production doping/sweep, observer, cleanup, 자원 감독.
- 새 `matched_judge.py`: 단위 대조군 및 보간 없는 raw 배열 판정.
- 새 `test_contract.py`: 합성 대조군·손상 반례.
- 새 `verify_artifact.py`: artifact 해시 및 독립 재판정.
- `remote/profiles.py`, `remote/request.json`: 이번 작업 allowlist 및 단일 요청.
- 새 `.gitattributes`: `raw/** -text -diff`로 증거 바이트 보존.
- 새 `raw/`, 본 보고서 및 `IMPLEMENTATION.patch`.

시작 SHA와 계산 코드 SHA 사이의 전체 구현 diff는 `IMPLEMENTATION.patch`에 보존했다. SHA-256: `b7907c0b11bfe189461ea95e4754d818040f1af270dcbc72a9accd9a5c85d1dc`.

핵심 계약은 다음과 같다.

```python
# common.matched_indices: 근사 일치나 보간을 허용하지 않는다.
indices = np.searchsorted(expected, actual)
if np.any(indices >= len(expected)) or not np.array_equal(expected[indices], actual):
    raise ValueError('EXACT_COORDINATE_MISMATCH')

# native field: 동일 interval의 기울기와 직접 대조한다.
expected_field = (psi1[m0] - psi1[m1]) / ell
```

`tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/`는 시작 SHA 대비 변경 0이다. 엔진 내부·기존 PLAN·원본 N2 증거·main·production gate도 변경하지 않았다. 전체 회귀는 실행하지 않았다. 코드와 일반 문서의 `git diff --check`는 RC=0이고, 원격 raw CRLF는 증거 바이트 보존 속성으로 유지했다. 공개 로그/JSON의 사용자 경로 및 토큰 패턴 검색은 0건이다.

## 10. 다음 단계

다음은 동일 좌표 비교를 계속 반복하는 것이 아니라 **PN 해의 실제 격자 수렴**이다. 우선 공식 1D API에서 기존 x구간을 2분할한 기준해와 비교해 기준해 자체의 수렴을 확인하고, N0/N1/N2는 공통 좌표와 접점 전류의 수렴 추세를 다시 계산한다. 이 검토를 거쳐야 이 대칭 PN 범위의 gate 해제 가능성을 판단할 수 있다.

같은 engine·같은 구성방정식의 수치 일치가 실험과의 독립 물리 검증을 대신하지 않는다. 실제 제작 공정으로 얻은 도핑 활성화·산화 재분포·임의 공정 순서의 물리 타당성은 여전히 별도 범위이며, 미지원 상태를 숫자로 채워 넣지 않는다.
