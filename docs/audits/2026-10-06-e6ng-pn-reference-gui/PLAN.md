# E6N-G: 별도 1D PN 기준 GUI

기존 2D gate는 유지한다. 현재 공정 웨이퍼를 바꾸거나 측정했다고 표시하지 않는다.
공식 DEVSIM 1D API, canonical ACTIVE profile, production apply_doping 및 PN sweep을
재사용한다. 입력은 E6N-E의 1545-node 정확 좌표, 대칭 NA=ND=1e17 cm⁻³,
40 µm, 300 K, 기존 이동도/SRH/접점/바이어스로 고정한다.
engine 내부와 구성방정식은 변경하지 않는다.

매 실행은 새 subprocess에서 균일 저항 대조군 3회와 PN 순·역방향 14회,
총 17회 solve를 수행한다. 각 장치는 독립적이며 cleanup 실패는 전체 실패다.
GUI main thread는 계산하지 않고 subprocess 종료를 poll한다.

기준 data 2개의 byte SHA를 엔진 준비 전에 검증한다.
기준해와 실제 계산의 current ≤1%, Potential ≤0.01Vt, carrier ≤1%,
KCL ≤1e-3, params 및 doping·native 좌표 일치가 필수다.
균일 저항 J=σV/L 상대/KCL ≤1e-6으로 A/cm² 단위를 확인한다.
Vbi=Vt log(NA ND/ni²)와 평형 contact 전위차 ≤0.01Vt,
순방향 장벽/전계 완화와 역방향 증가, 전류 부호/단조성을 확인한다.
공핍 근사의 W나 이상 Shockley 전류를 SRH 포함 해의 정확한 등식으로 강요하지 않는다.

GUI는 I–V, potential, n/p, ElectricField와 checklist를 표시한다.
검증 실패/누락 시 정상 곡선을 표시하지 않는다. 실패하면 마지막 성공 자료를 재사용하지 않는다.
문헌 기반 모델 일관성 및 고정 기준 문제 검증과 실험·공정 검증을 명확히 구분한다.
문헌: SG DOI 10.1109/T-ED.1969.16566, SRH DOI 10.1103/PhysRev.87.835,
공식 https://devsim.com/1d-diode-junction-part-ii/ 및 MIT 6.012 lecture 4.

로컬 pure tests/static만, 실제 엔진/Tk integration은 GitHub Windows에서 수행한다.
대표 정상·오류 차단·GUI 표시 및 기존 2D gate 회귀만 실행하고 전체 회귀는 실행하지 않는다.
