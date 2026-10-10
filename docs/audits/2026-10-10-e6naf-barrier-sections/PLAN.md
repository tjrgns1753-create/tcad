# E6N-AF: 실제 삼각형 경계 기반 barrier 검출

기준 production은 6615d28. AE 원격 38054150843은 전후 2개 지점씩
native/exported oxide가 있는데 기존 detector가 false를 반환함을 보였다.
SiO2 검출의 기하 후처리만 수정한다. 새 주입/활성화/산화 모델은 만들지 않는다.

## 사전 고정 계약
- 태그별 triangle union의 경계 edge를 읽고, 경계 vertex의 실제 축 좌표로 slab을 분할.
- slab 안에서 경계의 선형 교차와 material interval을 계산. 좌표 반올림이나
  bucket 빈칸 메우기 없음. Fraction으로 저장된 float 좌표를 정확 산술 처리.
- Si 최상부와 직접 연결된 oxide interval만 검출. 기존 1e-6um 인접 판정 한계,
  사용자 thickness threshold는 유지. 공중에 떠 있는 막을 보호막이라고 간주하지 않음.
- 선형 thickness가 threshold를 통과하는 좌표는 교차식으로 계산.
- 잘못된 축/비유한 값/퇴화/비정상 boundary/order/비평면은 명시적으로 거부.
- detector 예외를 GUI가 무도핑 mask(None)로 바꿔 진행하지 않도록 요청을 중단.
  기존 canonical 상태와 이전 도펀트를 바꾸지 않으며 해당 요청은 NOT APPLIED.
- 빈 material/triangle 범위는 명시된 material 부재일 때만 빈 windows 허용.
- bucket_width 인자는 호환 유지하되 결과는 bucket 폭에 의존하지 않음.

## 결과를 보기 전 테스트 기준
1. 연속 float32 slab에서 창 전체 검출; node/triangle 순서, 분할/축 교환 불변.
2. 실제 opening은 메우지 않고 열린 상태; 공중 oxide는 검출 안 됨.
3. wedge threshold 교차는 해석 좌표와 일치; 여러 창 구분.
4. malformed boundary/NaN/invalid axis는 FAIL; GUI detector 예외는 attach/solve0.
5. 보존 AE before/after VTU의 18개 고정 column을 독립 Fraction triangle
   scanline 결과와 대조: 4 false negative 제거, 기존 14 판정 유지.
6. 고정 AE fixture의 새 원격 실제 공정 + AD GUI 전체7 case/control3을 재확인.
   도핑/활성화/곡면 상태 전달/PN gate는 그대로 유지.
7. 추가 geometry helper, detector, GUI 실패 분기, 신규 unit 및 audit/remote만 허용.
   원본 AE/AD raw, 기존 PLAN/fixture, 엔진 내부는 변경 금지.

## 자원/증거
경계 edge 기반이라 full triangle별 매 slab 탐색은 하지 않는다.
원격 profile timeout 240초. 재검사에서 시간을 기록하고 초과 시 PASS 금지.
로컬 합성/기존 VTU 읽기만; 실제 ViennaPS/DEVSIM/Tk는 GitHub Windows만.
원본 byte hash/실행 SHA/실패/semantic diff 기록. main 병합/게이트 해제 없음.
