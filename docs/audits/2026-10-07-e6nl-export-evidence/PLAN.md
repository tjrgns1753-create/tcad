# E6N-L DC 결과 단위·export evidence

DC GUI wrapper가 unit metadata를 빠뜨리는 문제를 고친다. 공식
DEVSIM get_dimension()으로 확인한 dimension과 기존 current_unit_metadata를
재사용한다. SourceContext의 mesh SHA/pin만 직렬화하고 canonical 객체/id는
저장하지 않는다. canonical record는 GUI_SESSION_ONLY로 명시한다.

CSV 숫자는 그대로 유지하고 .metadata.json companion에 전체 voltages,
currents, converged, unit/source/검증 범위와 CSV SHA-256을 남긴다.
JSON의 NaN/Inf는 금지한다. 두 파일은 임시 파일에서 생성 후 교체한다.
두 파일 교체가 filesystem transaction이라고 주장하지 않는다. 소비자는
CSV hash를 확인해야 하고 단독 CSV에는 전체 출처 증거가 없다.
CSV/JSON 공통 기존 writer를 재사용한다. 새 물리 계산/방정식/gate 없음.

순수 반례로 기존 DC metadata에 unit/source 기록이 없는 것을 확인하고,
bundle round-trip/값·단위/해시/비유한 결과 거부를 검사한다.
원격에서 실제 GUI export 및 기존 canonical DC mock control과 실제
uniform DD 대조군을 검사한다. 합성 DC export는 MOSFET 물리 증거가 아니다.
실제 엔진/Tk는 원격 Windows만. 전체 회귀/main 병합/gate 해제 없음.
