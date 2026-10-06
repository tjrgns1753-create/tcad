# E6N-G: 물리 검사와 분리된 1D PN 기준 GUI

## 1. 판정과 승인 범위

**고정된 1D PN 기준 문제를 실제 계산하고, 원시 결과를 재판정한 후 GUI에 표시하는 경로를 구현했다.**
현재 공정 웨이퍼를 측정하는 기능이 아니다. 일반 2D PN gate, 산화 capability gate,
도펀트 활성화 및 공정 상태 전달 계약은 해제하지 않았다.

논문의 구성방정식에 대응하는 모델과 기준 문제의 수치 검사를 통과했다는 뜻이다.
특정 제작 논문의 소자를 재현하거나 실험 결과와 일치함을 보증한다는 뜻은 아니다.
모든 임의 공정 순서의 물리 타당성을 이 배치에서 검증했다고 주장하지 않는다.

## 2. 사용 방법

GUI의 측정 영역에서 **PN 기준 다이오드 계산 (1D)** 버튼을 누른다.
매번 별도 프로세스에서 새 장치를 생성하여 계산하며 현재 웨이퍼는 바뀌지 않는다.
창에는 I–V, 정전위, 평형 전자/정공 농도, 전계 네 그래프가 표시된다.
별도 탭에서 물리 검사와 지원 범위, 논문 및 공식 구현 링크를 확인할 수 있다.
계산 중 중복 실행은 막고 GUI 이벤트 처리는 계속한다.

실패 시 이전 성공 곡선을 다시 쓰지 않는다. 결과 수신 시 검사 목록만 신뢰하지 않고
실제 원시 농도·전위·전계·전류를 다시 판정한다. 검사 실패 또는 필드 누락은 표시를 차단한다.

## 3. 고정 물리 입력과 공식 API

- Si 1D 대칭 급격 접합, NA=ND=1e17 cm^-3, 300 K, 길이 40 µm.
- 1545개 노드의 사전 고정 좌표. ACTIVE는 명시적인 분석 입력이며 공정 활성화 결과가 아니다.
- 기존 이동도, SRH 수명, 접점, Poisson 및 drift-diffusion 설정을 재사용한다.
- 공식 DEVSIM create_1d_mesh/add_1d_mesh_line/add_1d_contact/add_1d_region/
  finalize_mesh/create_device API를 사용한다.
- production apply_doping() 및 run_pn_junction_iv_sweep()를 재사용한다.
- DEVSIM/ViennaPS 내부 구현과 기존 전류 방정식은 수정하지 않았다.

## 4. 문헌 대응 및 독립성 한계

| 근거 | 구현에서의 역할 | 증명하지 않는 것 |
|---|---|---|
| [Scharfetter–Gummel](https://doi.org/10.1109/T-ED.1969.16566) | 기존 DEVSIM 전류 이산화 재사용 | 임의 2D 메쉬 정확성 |
| [Shockley–Read](https://doi.org/10.1103/PhysRev.87.835) | 기존 SRH 생성·재결합 모델 재사용 | 실제 제작 소자의 수명·결함 실측 |
| [DEVSIM 공식 PN 예제](https://devsim.com/1d-diode-junction-part-ii/) | Poisson/DD/SG/SRH 경로와 대응 | 공정 시뮬레이션 완성 |
| [MIT 6.012 접합 강의](https://ocw.mit.edu/courses/6-012-microelectronic-devices-and-circuits-fall-2009/resources/mit6_012f09_lec04/) | 평형·바이어스에 따른 접합 거동의 기준 | 공핍 근사를 모든 해의 정확한 등식으로 적용 |

기준 배열은 E6N-E에서 고정하고 E6N-F에서 1D 격자 세분 비교를 수행한 자료다.
같은 엔진·모델과의 재현성 비교는 독립적인 실험 검증이 아니다.
내장전위의 접점 차이는 접점 초기조건과 관계가 있으므로, 독립적인 내부 해 검증이라고 과장하지 않는다.
장벽 검사는 전위 범위 변화의 대리 지표이며 에너지 밴드·준페르미 장벽 전체를 검사한 것이 아니다.
평형 질량작용/준페르미 항등식을 별도의 독립 물리 증명으로 중복 계산하지 않았다.

## 5. 사전 기준과 실제 결과

PLAN은 구현 전에 8c17b00으로 단독 커밋했다. 기준 변경으로 실패를 통과시키지 않았다.

| 항목 | 사전 기준 | 이번 결과 |
|---|---|---|
| 기준 좌표·도핑·모델 파라미터 | 고정 자료와 정확 일치 | 통과 |
| 기준 전류 | 상대 차이 <=1% | 통과 |
| 기준 전위 | 최대 차이 <=0.01 Vt | 저장 기준과 차이 0 |
| 기준 전자/정공 농도 | 최대 상대 차이 <=1% | 저장 기준과 차이 0 |
| 접점 전류 보존 | PN <=1e-3 | 최대 7.1827e-5 |
| 저항 단위 대조군 | 해석 J=σV/L 상대 오차 및 KCL <=1e-6 | 통과, A/cm² |
| 평형 내장전위 | Vt ln(NA ND/ni²)와 <=0.01 Vt | 계산 0.834504509847162 V, 해석 0.8345045098471614 V |
| 순방향 | 장벽 대리 지표·최대 전계 감소, 전류 증가 | 통과 |
| 역방향 | 장벽 대리 지표·최대 전계 증가, 전류 부호 | 통과 |
| 전계 | native edge에서 -Δψ/Δx와 일치 | 통과 |

총 74개 검사 항목이 통과했다. 74개의 독립 실험 검증을 뜻하지 않는다.
단일 바이어스 저항 대조군의 단조성 항목은 공집합 검사이므로 증거로 취급하지 않는다.
SRH가 포함된 역방향 전류는 바이어스에 따라 달라질 수 있다. 이상 Shockley의 일정 역포화전류를
이 모델의 정확한 등식으로 요구하지 않는다. avalanche breakdown은 검사 범위 밖이다.

## 6. 실제 Tk/DEVSIM 원격 테스트

실제 계산: [run 37434698574](https://github.com/tjrgns1753-create/tcad/actions/runs/37434698574),
실행 SHA 5ec4c7d316e0237ad4c600c65163fcdb06e517a7, GitHub-hosted Windows.

| 파일 | 결과 |
|---|---|
| test_pn_reference_view_mock.py | PASS, 정상 및 8개 실패 차단 반례 |
| test_pn_reference_gui_real.py | PASS, 실제 버튼·subprocess·Tk·17회 solve |
| test_measurement_canonical_state_gate_mock.py | PASS |
| test_current_unit_contract_mock.py | PASS |
| test_gui_current_unit_contract_real.py | PASS |

새 PN 기능 17회 solve = 저항 대조군 3 + 순·역방향 14.
기존 GUI 단위 회귀는 별도로 6회 solve를 수행했다. 전체 실행을 17회라고 축소하지 않는다.
새 GUI 테스트 중 이벤트 업데이트 207회, 모달 0회, 기존 웨이퍼 상태 변화 0건,
그래프 4개 및 곡선 수 2/3/2/3을 확인했다. 장치 cleanup 검사도 통과했다.
기존 CHEMICAL/UNKNOWN 상태는 각각 doping write 0, solve 0, 수치 전류 표시 0을 유지했다.

## 7. 실제로 발견하고 수정한 구현 결함

1. 최초 실제 실행(run 37434418870)에서 저항 대조군 생성의 keyword-only API를
   위치 인자로 호출한 오류가 발생했다. 호출을 고쳤고, uniform canonical 대조군을
   단위 테스트에 추가했다. 이 실패에서는 정상 결과 표시가 차단됐다.
2. 첫 저장 이미지에서 한글 글꼴의 음수/지수 글리프가 잘못 표시됐다.
   Malgun Gothic 뒤에 DejaVu Sans fallback을 추가하고 로그 축을 1e-06 형태로 바꿨다.
   숫자나 물리 기준은 변경하지 않았다.

표시만 검사한 [run 37457046947](https://github.com/tjrgns1753-create/tcad/actions/runs/37457046947)은
보존 결과를 재판정하고 실제 Tk로 렌더링했다. engine import 0, solve 0, missing glyph 경고 0.
최종 지수 표기는 후속 [run 37457369364](https://github.com/tjrgns1753-create/tcad/actions/runs/37457369364)에서
통과했다. 실행 SHA e14661d0c095636ea5c61b3dfbe6c376079df330, 실제 Tk 렌더링,
로그 축의 명시적인 과학적 표기 assertion, missing glyph 경고 0, engine import 0, solve 0을 확인했다.
최종 PNG를 직접 시각 검토하여 음수 전압/전계 및 1e-01~1e-07 전류 눈금이 읽히는 것을 확인했다.
첫 이미지와 렌더링 증거는 서로 덮어쓰지 않고 보존한다.

## 8. 변경 범위와 무변경 보증

- pn_reference.py: 기준 무결성, 공식 API 장치, canonical 입력, 기존 solver 호출, 물리 검사.
- pn_reference_view.py: 표시 전 재판정, 네 그래프, 한국어 범위/문헌 안내, 숫자 표기.
- tcad_2d_stagewise.py: 별도 버튼 및 비동기 실행/오류 차단 69줄 추가.
- 고정 기준 data 2개 및 신규 unit/integration 테스트 각 1개.
- 원격 profile/driver와 감사 자료. 전체 회귀는 실행하지 않았다.

시작 SHA f1d98840a76ec3973882ec21ccf2089b68b0fb99 대비 tcad/device/,
tcad/process/, 기존 pn_junction_iv_sweep.py의 diff는 0이다.
일반 2D STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED gate는 유지한다.
main 병합은 하지 않았다. 기존 관련 없는 untracked 자료는 보존했다.

## 9. 증거 무결성과 공개 자료 점검

- pn_1d_arrays.npz: 3fb54277848ab4522cb23bf3fd6755d6a059e56130f1a31932f1617e10fa25b4
- pn_1d_record.json: 52bb73beae473188308616e9c4fbcce1e879c6ba25e67924f377c08e1b7d50d5
- 실제 새 결과 JSON: 9b3212aad5eb00acd02fa1289442bbda0ee814b37078f5296f27b604d143705d
- 렌더링은 이 실제 결과 해시를 확인한 뒤에만 수행한다.
- raw/**는 -text -diff로 원본 바이트를 보존한다.
- 공개 전 개인 이름/사용자 경로/이메일/인증 토큰/비밀 패턴을 검색했고 공개 저장소 이름만 검출됐다.
- 로컬에서도 require_pass()를 실제 원시 결과에 재적용하여 74개 통과를 재현했다.

## 10. 다음에 검증해야 할 범위

고정 1D 기준 GUI에서 임의 제작 웨이퍼로 넘어가기 위해서는 2D 전이 메쉬의 독립 수렴,
canonical ACTIVE 상태의 공정 전달, 실제 접점 정의 및 단위가 같은 검증을 통과해야 한다.
현재 버튼의 결과로 해당 조건이 충족됐다고 간주하지 않는다.
실험 논문과의 정량 비교에는 실제 소자 형상·도핑·수명·온도·접점·단위 및 측정 조건이 필요하다.
