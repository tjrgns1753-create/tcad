# 원시 데이터 해석 경고

raw/outputs/e6nl_out/한국어.csv 및 companion의 DC ±1e-6 값은
FakeDevsim/Recorder가 반환한 합성값이다. 단위·출처·GUI export 배선 검사에
사용했으며 실제 MOSFET 계산 결과나 검증된 물리 기준 데이터가 아니다.
metadata의 mesh_sha256 역시 이 mock에서 사용한 stable-source token
(테스트 코드 파일)의 hash이며 실제 mesh의 hash가 아니다.
GUI가 실제 계산할 때는 실제 입력 mesh를 source context로 캡처한다.

실제 계산 대조군은 별도 gui_unit_contract.json의 uniform DD 결과다.
이 대조군은 ±0.0001600000000002224 A/cm를 반환했고, 그 결과를 임의
MOSFET/PN 결과로 확장해 해석하지 않는다.
