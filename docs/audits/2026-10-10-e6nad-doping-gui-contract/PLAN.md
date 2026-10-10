# E6N-AD: 도핑 GUI 통합 테스트의 현재 물리 계약 복구
기준 SHA: e1c0c025d955540251e00a8f295db836044e61f7
실행 전 고정 계획. 구현 후 결과를 보고 기준을 변경하지 않는다.

## 범위
production 물리 코드, gate, 기존 원본 증거, 엔진 내부는 변경하지 않는다.
tests/integration/test_gui_doping_donor_acceptor_real.py 한 파일만 migration한다.
원격 runner 등록과 이 감사 폴더만 추가/수정한다. main은 변경하지 않는다.
로컬 실행 환경 초기화 실패로 GitHub connector를 사용한다. 현재 로컬 동기화는 미확인.
원격 브랜치 ref는 expected_sha lease + non-force fast-forward로만 갱신한다.

## 물리 계약 및 사전 판정
1. ACTIVE Uniform ND=1e16, NA=5e15는 두 농도와 net=5e15를 보존한다.
   이 프로젝트의 compensated transport gate는 유지한다. 측정 0 solve/0 doping writes,
   결과/필드/성공 로그/측정 history 0. 이는 보상 반도체가 물리적으로 불가능하다는 뜻이 아니다.
2. 별도 virgin Si에서 순수 n형 ND=1e16와 p형 NA=5e15 각각 실측.
   MEASURE 전에 동일 입력 geometry를 다른 파일로 export해 cache를 stale로 만든다.
   실제 solve >=1, 두 finite terminal currents, KCL <=1e-4 relative,
   공식 API NetDoping과 canonical node query exact equality.
   reattach 후 state object, attachment ids, inventory, event count 불변,
   최신 cache 및 result/fields 존재. popup 8종 모두 0.
   transport 세부 물리 승인은 이미 고정된 low-field 감사에 한정한다.
3. Gaussian 원래 donor/acceptor peak 및 P/B species, window 원래 background 및
   source/drain donor/acceptor/합성 net 필드를 전부 보존해 확인한다.
   GUI helper pass-through observer로 실제 만들어진 요청을 읽는다. 대체 profile 금지.
   CHEMICAL attachments만 생성, ACTIVE 승격/last_doped_result/history/layer 성공 갱신 없음.
   측정은 DOPANT_ACTIVATION_MODEL_MISSING, 0 solve/0 write/결과 없음.
4. 기존 oxide-bearing 입력은 DIRECT_EXPLICIT_GEOMETRY의 기존 chain helper로 생성한다.
   폭10um, depth5um, grid0.1um, 초기 oxide0.3um. oxide는 공정 산출물이 아니다.
   기존 isotropic 실제 selective etch: open [-1.5,1.5], protected [-5,-1.5],[1.5,5],
   SiO2 rate -0.6um/s, Si/PHS0, 1s. native Si 불변도 확인한다.
   detector는 x=0을 uncovered, x=-4를 covered로 판정해야 한다.
   GUI attach 시 detector axis는 measurement x/y 모두 x, 실제 computed windows가 전달됨.
   etched geometry의 exact transform 없으므로 canonical는 LEGACY_UNRESOLVED/UNRESOLVED,
   새 Uniform doping은 거부, DevSim 0 writes/solves/숫자 결과. 과거 post-hoc zeroing 요구 폐기.
   실제 SiO2 제거/보호의 기하 확인과 도펀트 전달 미지원은 분리한다.
5. Tk/ViennaPS/DevSim 결손은 mandatory FAIL. SKIP/빈 metric도 PASS 금지.
6. targeted 4파일: migrated test + canonical gate real + headless no-modal real +
   unit doping_staleness_mock. 각 한 번, timeout 180s, process tree cleanup.
   전체 회귀는 하지 않는다.

## 공식 근거와 제한
DEVSIM 공식 simple_physics.py의 ohmic contacts, n_i, constant mu_n/mu_p,
public get_node_model_values/solve만 재사용한다.
https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py
CHEMICAL vs ACTIVE, unsupported geometry와 compensated gate는 프로젝트 지원 계약.
산화 kinetics, activation, compensated mobility, 일반 PN/2D mesh convergence 승인 아님.
판정은 성공/거부 경로의 실제 데이터로 확인하며 rc=0만으로 물리 승인하지 않는다.

## 기록과 실행
PLAN LF SHA-256을 runner 시작(엔진 import 전)에 검사한다.
모든 대상 파일 input hash, 실행 SHA, 결과 원시 로그와 semantic patch를 보존한다.
원격 Windows에서만 물리 실행. 기존 production tcad/ GUI의 git blob SHA 불변을 확인한다.
로컬 환경 복구 전 로컬 checkout이 새 commit과 동기화됐다고 주장하지 않는다.
