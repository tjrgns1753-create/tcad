# E6N-R: 필드 화면의 실제 영역·접점 바이어스·전위 기준

시작 HEAD 64d59bd. 물리 계산을 확대하지 않고 표시의 물리적 의미를 명확히 한다.

## 확인한 문제

현재 map 설명에는 영역 이름과 두 접점의 실제 인가전압이 없고,
Potential이 접점에 가한 전압과 동일하지 않을 수 있다는 설명도 없다.
공식 simple_physics의 Si ohmic contact는 도핑에 따른 V_t*log(n_eq/n_i)를
포함한다. 따라서 uniform n Si의 0V 접점에도 약 0.3576V의 Potential이
관측되는 것은 0V를 잘못 계산했다는 뜻이 아니다. raw 값을 이동하지 않는다.

공식 근거: https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py
CreateSiliconPotentialOnly / CreateSiliconPotentialOnlyContact.
설치 2.11.0 Python helper도 import 없이 직접 읽어 동일 식을 확인했다.
여기서 단일 Si/Boltzmann/ohmic 모델의 기준을 모든 MOS 또는 이종재료로
일반화하지 않는다. 표시 문구는 원시 Potential과 접점 인가전압의 구별만 한다.

## 결과를 보기 전 기준

- 화면 caption에 저장된 성공 결과의 region, 모든 두 접점 이름과 voltages,
  선택된 필드 단위·actual node 수·선형색 범위·보간 없음이 나타난다.
- Potential만 원시 DEVSIM 전위와 접점 인가전압의 기준 차이를 설명한다.
  전자/정공에 전위 설명을 붙이지 않는다. 값이나 좌표를 재계산하지 않는다.
- caption은 요청 StringVar에서 값만 가져오지 않고 그 snapshot의 결과를 읽는다.
  누락/불일치 region/비유한/불완전 접점이면 점도 표시하지 않는다.
- 엔진 없는 합성 unit으로 이를 검사하고 기존 caption/hover/export 대조군을 유지한다.
- 원격은 기존 uniform ACTIVE Si 73 노드, +1mV 실제 측정 한 번(3 solve)을
  재사용한다. 실제 caption 3종, 표시 점 수, 실제 node 배열과 원본 API equality,
  ground contact의 원시 Potential과 공식 ohmic 식을 확인한다.
- ground 전위 식의 부수 확인 기준은 절대 1e-9V(이전 uniform field의
  1e-6 상대 / 1mV 기준과 동일 규모). solver tolerance나 PN 승인 기준은 아니다.
- 배열 및 export 결과는 이전 고정 73 노드 증거와 전체 비교한다.

## 범위·실행

허용 production: node_fields.py의 순수 설명 helper와 GUI field caption 경로.
전기 방정식·engine·도핑·접점·공정·gate는 불변. 새 solve 종류 없음.
로컬: 순수 Python/AST만, engine/Tk 금지. 원격: GitHub-hosted Windows.
자식 30~120초, profile 400초, output 8MB. 전체 회귀 없음.
무효 결과를 정상 caption이나 숫자로 보여주는 fallback은 금지한다.
