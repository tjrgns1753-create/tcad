# E6N-U: p형·보상 도핑·입력 순서의 실제 GUI 물리 대조

시작 HEAD 0ac52a9. production 변경 없이 기존 공식 DEVSIM 모델과 canonical
ACTIVE uniform attachment의 양극성 전달을 확인한다. PLAN을 결과 전에 단독 커밋한다.
엔진 import/실제 GUI/solve는 GitHub-hosted Windows에서만 한다.

## 고정 조건과 12개 요청

E6I one_sided_8 단일 Si 2µm×0.5µm, 73노드, 300K, x/max source,
ground 0V. 기존 mu_n=400, mu_p=200cm²/(V·s), n_i=1e10cm^-3,
q=1.6e-19C, SRH 수명 1e-8s, 기존 solver tolerance 그대로.
각 프로필은 +1mV/-1mV 두 요청, 매번 fresh canonical/device, 3 solve씩 총36회.

1. n_single: donor1e16, acceptor0 (한 번의 ACTIVE uniform 선언).
2. p_single: donor0, acceptor1e16 (한 번의 ACTIVE uniform 선언).
3. n_comp_da: donor2e16 선언 뒤 acceptor1e16 선언.
4. n_comp_ad: acceptor1e16 선언 뒤 donor2e16 선언.
5. p_comp_ad: acceptor2e16 선언 뒤 donor1e16 선언.
6. p_comp_da: donor1e16 선언 뒤 acceptor2e16 선언.

도핑 선언은 기존 apply_uniform_doping→advance_wafer_state로 각각 추가한다.
이온주입/열처리/활성화 공정을 수행했다는 뜻이 아니며, 사용자가 선언한 ACTIVE
농도라는 기존 계약만 검사한다. 원시 donor/acceptor와 net 및 전체 query가
두 declaration의 합을 보존하는지 검사한다. 한 단계짜리 프로필로 몰래 대체하지 않는다.

## 물리 기준과 증거

기존 E6I theory로 charge neutrality n-p=ND-NA, np=n_i²의 안정적인 근을
구하고 sigma=q(mu_n*n+mu_p*p), G=sigma*0.5/2, I=G*V를 계산한다.
정공 majority에는 p 균일성, 전자 majority에는 n 균일성을 검사한다.
이 해석식은 완전 이온화·비축퇴·상수 이동도 모델의 저항 문제에만 적용한다.
보상 농도가 같으면 같은 전류라는 예상은 **상수 이동도 모델 안의 결과**이며,
실제 불순물 산란·도핑 의존 이동도가 항상 같다는 일반화는 하지 않는다.

- 모든 노드 Donors/Acceptors/NetDoping는 실제 공개 API에서 읽어 선언합과 exact equality.
- 모든 node xy/Potential/Electrons/Holes는 공개 API→snapshot→JSON의 전체 equality.
- 비영 bias I=GV 상대차 ≤1%, KCL/(G×1mV) ≤1e-6, majority 균일성 ≤1e-4,
  affine Potential차/1mV ≤1e-2: 기존 E6I 허용기준 재사용.
- p/n source 전류비는 기존 mu_p/mu_n=0.5와 비교(≤1%).
- 같은 최종 농도의 declaration 순서를 바꾼 두 결과의 I·n·p·Potential은
  기존 전류1%/majority1e-4/전위1e-2 기준으로 비교. exact bit equality는 참고만.
- 각각 GUI 3레이어 73노드, 올바른 접점/전압/단위 A/cm, 성공로그/JSON 검증.
- 두 요청 비교는 입력 donor와 acceptor 둘 다 실제 API 값을 갖춘 후에만 판정한다.

사전 pure judge는 정상 합성 자료를 통과시키고 도핑 합 누락/잘못된 부호/순서별
전류 변조/NaN/누락 case를 차단한다. 합성자료는 실제 solve로 집계하지 않는다.

## 실행 예산과 금지

36회 실제 solve, matrix child180초, parent500초, artifact12MB.
중도 실패는 누적 raw를 보존하며 기준을 완화하지 않는다.
새 모델·엔진 내부·게이트 수정·기존 raw/PLAN 수정·전체 회귀·main 병합 없음.
이번에는 균일 p형/보상 ACTIVE 상태 전달만 검증하며 PN/산화/임의 공정 완료를 주장하지 않는다.
