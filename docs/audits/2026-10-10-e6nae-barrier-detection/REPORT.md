# E6N-AE 결과: 연속 SiO2의 가짜 검출 틈 확인

## 판정
`DETECTOR_FALSE_NEGATIVE_REPRODUCED`. 실제 보호막이 없는 구간이라고
해석하면 안 되는 검출 오류가 식각 전후에 각각 2개씩 확인됐다.
새 주입/활성화 모델이나 전기 측정 능력은 승인하지 않는다.

## 실행과 증거
- 최초 run 38053776361, SHA 6d9695b6b9bba92c6ee680f2fe6050b2fb500fb9:
  FAIL. 초기 요청 좌표와 native reading에 변화량용 epsilon을 잘못 적용.
  `raw_initial/remote-run-80` 전체 원본 보존.
- ERRATUM_MEASUREMENT.md를 실행 전에 고정. 원본 PLAN 불변.
- 수정 조사 run 38054150843, SHA 6615d28e06f03af29c4d95cfbf0c2a68525c1af8:
  성공. `raw_corrected/remote-run-81` 전체 원본 보존.
- 실제 Isotropic Process 1회, Oxidation/DEVSIM solve 0회.
- 입력은 explicit oxide 0.3um, grid0.1um, 폭10/Si깊이5um.
  oxide만 -0.6um/s, Si/PHS0, 1s. 마스크[-5,-1.5],[1.5,5].
  입력막은 직접 구성한 구조이며 산화 성장 결과가 아니다.

## 삼중 대조
고정 9개 column에서 native level-set 표면, exported triangle scanline,
기존 vertex-bucket detector를 각각 읽었다. x=-4.75/-4.25um에서는
native와 실제 triangle union 모두 충분한 oxide를 갖지만 detector=false.
전후 18판정 중 false negative 4, 나머지 agreement 14.
x=0은 식각 전 보호/후 개방이며 보호 위치의 native oxide와 Si는
기존 native_eps(8) 이하로 유지된다.

초기 oxide native top은 0.2999999999999um, 요청 대비
-9.997558336749535e-14um. 이 offset을 물리 성장이나 검증된 오차라고
주장하지 않는다. export Si top은 약0.00049751246um으로 native와 다르므로
서로 다른 표면 표현을 혼합해 Si 소비량을 계산하지 않는다.

## 원인 및 제한
생산 detector는 삼각형 내부 대신 bucket에 들어간 vertex만 검사했다.
spacing 약0.10000002384um과 좌표가 만나 빈 bucket을 실제 공백으로 읽었다.
이 결과는 연속 막 fixture의 반례이며 모든 기하의 원인 확정은 아니다.
Fraction triangle scanline은 직렬화된 export 자체의 정확 교차값이지
ViennaPS level-set의 연속 물리 해상도까지 보장하는 방법은 아니다.

## 공식 모델과의 대응
ViennaPS 공식 isotropic 문서는 material별 normal velocity와 0-rate 보호를
정의한다. 이 fixture의 Si0/oxide 음수 rate 선택은 그 API 범위다.
https://viennatools.github.io/ViennaPS/models/prebuilt/isotropic.html
이 문서/fixture는 oxide의 에너지 의존 이온 정지능을 검증하지 않는다.

후속 AF는 기하 검출 수정만 허용한다. activation/oxidation/PN 및
nonrepresentable canonical transition gate는 그대로 유지해야 한다.
