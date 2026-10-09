# E6NZ known-undoped Si 공식 API capability 실험

현재 GUI device profile 입력 미확보 gate는 그대로 두고 엔진 경로만 조사한다.
무도핑은 UNKNOWN이 아니라 정확히 알려진 ND=NA=0인 explicit 초기 상태로 정의한다.
명시적 canonical virgin Si rectangle(-1,1,-0.5,0)um, attachment0을 사용하고
기존 E6I one_sided8 메쉬(73노드)를 재사용한다. 산화/증착/주입 결과로 주장하지 않는다.
임의 zero DopingProfile를 만들지 않는다. apply_doping은 canonical query의 known0만 쓴다.

## 물리 기준: 결과를 보기 전 고정

공식 DEVSIM simple_physics.py의 n_i 및 constant mobility 구성을 재사용한다.
300K, n_i1e10, q1.6e-19, mu_n400, mu_p200, 기존 SRH lifetime1e-8을 변경하지 않는다.
열평형 n=p=n_i, 균일 저전계 sigma=q*(mu_n+mu_p)*n_i.
2D per-depth 전류 I=sigma*(0.5/2)*V [A/cm].
0,+1mV,-1mV 세 요청을 fresh device로 각각 production sweep에 통과시킨다.
기존 E6I 한도를 그대로 사용: current1%, 양단 KCL1e-6/(G*1mV),
0V전류1e-4/(G*1mV), n/p 균일성1e-4, affine Potential1e-2/(max|V|,1mV).
비영 바이어스의 electron/hole contribution은2/3와1/3, 절대 share오차1e-6.
전 노드의 Donors/Acceptors/NetDoping은0이고 canonical attachment0을 유지해야 한다.
모든 node 배열, 양단 분리 current, 실제 파라미터와 solve 횟수를 저장한다.

## 미지원 반례

동일 canonical 상태를 transform 없는 etch로 unresolved 처리한 뒤 apply_doping은
write0/solve0으로 거부해야 한다. None canonical도 마찬가지다.
두 반례의 query None을0으로 바꾸지 않는다. 각각 fresh device, finally cleanup.
공식 API와 기존 production pipeline만 사용하며 model/tolerance/gate 변경0.

## 실행·판정

PLAN 해시는 엔진 준비 전 대조. 실제 import/solve는 GitHub Windows에서만 한다.
세 요청의 최대 예상 solve9, 기존 driver timeout180초/profile240초.
원본의 수치 finite 여부와 모든 기준을 독립 재검사한다. 실패한 기준을 완화하지 않는다.
이 실험이 통과해도 GUI가 intrinsic input을 안전하게 구성하는지는 별도 구현 과제다.
PN/산화/활성화 모델과 물리 gate는 그대로 둔다.
