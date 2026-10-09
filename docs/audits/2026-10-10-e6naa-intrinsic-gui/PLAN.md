# E6NAA known-undoped Si GUI 측정 연결

E6NZ 원격 원본9solve/56checks를 기반으로 기존 공식 DD 계산을 GUI에 연결한다.
새 방정식/엔진 내부/가짜 zero DopingProfile/activation 모델을 만들지 않는다.
지원 입력은 정확한 initial_geometry provenance의 단일 ACTIVE MODELLED Si rectangle,
attachment0/ledger0이다. 처리 후 UNRESOLVED·legacy·CHEMICAL·UNKNOWN·ACTIVE 도핑
기록을 무도핑으로 재해석하지 않는다. 해당 입력은 기존 경로/gate로 처리한다.

완전 virgin GUI이며 mesh/state가 둘 다 없을 때만 기존 _materialize_current_wafer로
입력 geometry를 export할 수 있다. 불확실한 prior state를 재초기화하지 않는다.
last_doped_result에는 가짜 프로필을 저장하지 않는다. 실제 canonical node gate를
통과한 알려진0만 공식 DEVSIM에 전달한다.

## 결과 전에 고정한 검증 경계

- axis x/y, 양단 전압차가 만드는 전계 <=5 V/cm (Z의1mV/2um).
- 전체 node n/p는 n_i 대비1e-4, affine Potential1e-2, 전류해석1%, KCL1e-6,
  0V전류1e-4: 모두 Z와 기존 E6I의 고정 기준을 유지한다.
- I=q*(mu_n+mu_p)*n_i*(W/L)*V, params는 live공식 get_parameter로 읽는다.
- 실제 mesh node extents와 canonical bounds의 차이는 기존 float32 serialization
  _float32_roundtrip_ulp_um으로만 허용한다. 임의 epsilon/격자비율 tolerance 금지.
- 위 검사가 실패하거나 전체 field capture가 불가능하면 cache/history/성공전류를
  내보내지 않는다. 근사field·재시도·0 fallback으로 통과시키지 않는다.

## 원격 실제 GUI matrix

Z의 explicit 2×0.5um/73node 입력에서 x 0,+1mV,-1mV, y+0.25mV 네 요청.
각 fresh device3solve, 동일 실노드/API/GUI/JSON과 canonical attachment0 유지 확인.
불명 state·CHEMICAL·ACTIVE missing profile은 기존 거부를 유지하고,
지원 전계 밖 요청은 solve/write/capture/history0으로 차단한다.
별도 fresh GUI의 실제 wafer materialization→intrinsic 측정도 검증한다.
기존 canonical ACTIVE 누적 integration을 대조군으로1회 실행한다.
로컬은 pure 반례/정적 검사만, 실제 공정/Tk/solve는 GitHub Windows.

양의 시간 산화·보상 transport·2D PN gate와 기존 original PLAN/raw는 무변경.
반도체 전 현상 검증이 아니라 이 known-undoped/constant-mobility 저전계 범위의
full pipeline을 추가하는 것이다. 수치 실패 시 그 기준을 수정하지 않는다.
