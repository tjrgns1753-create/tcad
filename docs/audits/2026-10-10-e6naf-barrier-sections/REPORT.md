# E6N-AF 완료: 보호막 검출 오류와 불확실성 fallback 제거

## 1. 판정 범위
`EXPORTED_BARRIER_GEOMETRY_AND_GUI_REFUSAL_VERIFIED`.
연속 막의 가짜 검출 틈을 고쳤고, 검출 실패를 막 없음으로 바꿔 도핑하던
GUI 경로를 차단했다. 실제 공정 순서나 canonical certainty는 승격하지 않는다.
주입 에너지/선량/정지능, activation, 양의 시간 산화, 일반2D PN/DD는 미승인.

## 2. 수정 전 반례
AE run38054150843의 before/after 원본을 읽기 전용 재사용.
x=-4.75/-4.25um에 native와 triangle scanline 모두 막이 있지만 detector=false.
전후18개 중4 false negative, 나머지14 agreement. 기존 vertex bucket의
빈 버킷을 실제 기하 공백으로 읽은 오류. 빈칸 메우기/좌표 반올림은 사용하지 않음.

## 3. 생산 변경
기준6615d28→최종48bf6ab 사이 생산 변경은 정확히 다음3개 파일.
- `tcad/mesh/barrier_sections.py`: serialized triangle union 경계 추출,
  CCW winding, slab별 선형 scanline, threshold root, exact interval union.
- `tcad/device/devsim/mesh_import.py::derive_barrier_covered_windows`:
  vertex bucket 대신 위 기하 helper 사용. material 없는 경우와 읽기 실패 구분.
  multiple triangle block을 함께 읽으며 invalid axis/threshold/geometry는 raise.
- `tcad_2d_stagewise.py::TCADApplication.run_doping`: detector exception이면
  BARRIER_GEOMETRY_UNRESOLVED / DOPING NOT APPLIED 후 즉시False.
  attach/DEVSIM write/solve에 도달하지 않고 기존 canonical state는 보존.
전체 semantic diff는 IMPLEMENTATION.patch. 엔진 내부/물리식/gate는 무변경.

## 4. 알고리즘과 물리 의미
boundary vertex의 실제 좌표에서 slab 분할. Fraction이 저장 float 좌표를
정확 산술로 읽어 삼각형 내부가 갖는 material interval을 계산한다.
외부 material의 최상부 바로 위에 연결된 barrier만 검출한다.
기존1e-6um exported adjacency convention은 유지하고, floating roof는 거부.
두께 조건은 선형 부등식의 root로 계산한다. bucket_width 인자는 호환 유지하되
결과는 bucket 폭과 무관. node/triangle 순서나 x/y 축 교환에도 불변.
이 helper는 geometry 후처리이며 이온이 산화막을 통과하는 물리 모델이 아니다.
곡면 export와 native의 차이를 dopant 보존이나 oxide 성장으로 변환하지 않는다.

## 5. 합성 반례
연속 float32 grid, 실제 opening, shuffled node/triangle IDs, y-axis,
floating oxide, wedge threshold crossing, invalid axis/NaN/negative threshold,
negative node ID/중복 triangle/nonmanifold를 검사.
첫 원격 성공 뒤 자체 검토에서 duplicate boundary 상쇄 위험을 발견했고
orientation/winding 거부를 추가했다. 최초 성공을 최종 코드 승인으로 소급하지 않음.
SELF_REVIEW.md에 보완 기록. 원격을 제외한 이 검사에 engine import0.

## 6. 보존 실제 메쉬 대조
before/after VTU의 native/triangle material 자체는 바꾸지 않았다.
18개 위치 agreement, false negative4→0. 처음14개 기존 판정은 유지.
before 창[-5,5]. after 창[-5,-1.7138825352140428]와
[1.7138825352140428,5]. 중앙 opening은 메우지 않음.
이 경계는 export 선형 기하+0.01um threshold 판정이며 native 반응경계의
정확 물리 좌표나 에너지 의존 주입 창을 승인하는 수치가 아니다.

## 7. 실제 원격 실행
최초 코드4657753: run38054731192 성공, raw_initial/remote-run-82 보존.
최종 코드48bf6ab951c9851b5328ef0f1d502de540d90042:
run38054909716, raw_final/remote-run-83, profile34.381초,8/8 파일PASS.
- 신규 순수 기하 unit
- AE 보존 VTU 재대조
- 새 실제 ViennaPS selective etch1회 + native/exported/검출18위치
- 실제 withdrawn Tk의 detector 예외 주입
- GUI donor/acceptor 계약7case
- canonical measurement gate control
- headless/modal control
- doping stale-cache control
모두SKIP0/timeout0/프로세스 정리 성공. 실제 계산은 GitHub Windows만.

## 8. 정상/차단 GUI 결과
순수n형/p형 ACTIVE 선언 측정은 각각solve3회, 실제 전류쌍
±0.0016/±0.0004 A/cm. log-only notification으로 동일쌍이 반복 출력되며
접점이4개라는 뜻이 아니다. canonical NetDoping과 solved node 값의 mismatch0.
reattach는 객체/count/inventory/events를 중복 생성하지 않는다.
보상 도핑/chemical Gaussian/windows/곡면 etch 상태의 나머지5개는
write/solve0, 숫자 전류/필드/새 history 없음. 활성화나 상태 전달을 발명하지 않음.
별도 detector 예외는 attach/write/solve/modal0, prior state 객체와 cache/history 유지.
최종 GUI 보호 창도 fragmentation 없이 위2개와 같음.

## 9. 독립 원본 검증
verify_artifact.py는 엔진 없는 읽기 전용 판정. source SHA/run ID/runner,
13 input checkout hashes,21 output byte hashes,run.log hash를 확인.
PLAN LFsha 고정,8개 실행 exact set/exit/cleanup/skip 검사,
GUI JSON↔원본METRICS log 일치 및7case 계약, native Si 전후 불변,
fresh18개 위치9→8 보호 변화를 재검사. 누락/실패/cleanup/skip mutation4개 차단.
검증기 engine import/새solve0. raw는 -text -diff로 byte 보존.

## 10. 문헌/API 범위
실제 공정은 공식 ViennaPS material-rate IsotropicProcess/Process API.
https://viennatools.github.io/ViennaPS/models/prebuilt/isotropic.html
DEVSIM API/엔진 내부는 수정하지 않았다. 자체 geometry helper는
공식 API의 공정 모델을 재구현하지 않으며 exported tagged triangles의 읽기다.
화학/활성 농도, flux equation, transport parameter를 새로 계산하지 않는다.

## 11. 한계와 다음 단계
exact arithmetic은 serialized mesh의 일관성이지 실제 공정 mesh 수렴 증거가 아니다.
큰 multi-material geometry 성능, 다른 진짜 nonplanar domain 및 재료 경계는
일반 검증 안 됨. 부정상 boundary/order는 예외로 거부하며 숫자 fallback 없음.
full integration suite를 모두PASS라고 주장하지 않음.
다음 AG는 이전86개 단위 테스트+신규1개를 정확87개로 고정해 영향 검사한다.
main 병합/물리 capability gate 해제 없음. 사용자 기존 untracked 작업 보존.
