# N0 원시 배열의 사후 전열 조사

이 분석은 기존 E6N-A의 INCONCLUSIVE를 소급 변경하지 않는다. 기존 최대 12개 x열 표본과 제한된 node pair는 192개 함수 비교에서 exact row 차이 0이었다. 표본 바깥의 전체 y spread는 비영이므로 설명을 위해 원시 데이터 전체를 별도 조사한다.

고정 입력 NPZ SHA: 69ffbc42aea5c11fea0347c922d872bb0387c0c87934c2ed14af93eaeffa222b. 새 엔진 import/solve/기하 생성은 없다.

모든 비접점 x열에서 같은 class의 node를 y순으로 정렬한다. 첫 node와 나머지 전부를 비교한다. strict interior(class 0)와 무접점 boundary(class 1)는 분리한다. 저장 좌표의 exact Fraction projected-row 차이를 전수 검사한다. 기존 네 polynomial과 동일 classifier, scale 및 uncertainty를 유지한다. 어떤 pair라도 조건을 통과하면 사후 witness로만 기록한다.

저장할 것: 조사 열·pair 수, exact 비영 차이 수, 기존 기준 통과 수, 첫 witness와 위치, 위치별 y spread 최대. 비영 row만으로 PN 수렴/전류 정확성을 승인하지 않는다. 아무 witness도 없으면 그대로 미입증이다. 입력과 원본 판정은 수정하지 않는다.
