# E6N-M 실제 측정 노드 필드 보존·표시

물리 방정식·canonical gate·수렴 기준은 변경하지 않는다. 새 공정 모델이 아니다.
공식 get_node_model_list/get_node_model_values로 성공한 단일 bias의 Potential(V),
Electrons/Holes(cm^-3), x/y(cm)를 장치 삭제 전에 복사한다. 좌표는 기존 import
scale 1e-4 cm/um의 역변환만 사용한다. VTU node ID와 대응을 추정하지 않는다.

화면은 모든 노드의 점 표시(선형 색 범위)이며 보간/연속장/삼각형 평균이 아니다.
캡처 상한 20,000 노드, 표시 상한 2,000 노드. 초과하면 전체 필드 미표시;
일부를 골라 전체 결과라고 부르지 않는다. 전류 측정과 필드 표시 지원은 구분한다.
모델 누락·배열 길이 차이·NaN/Inf·음수 캐리어·잘못된 scale는 필드 미지원이다.
새 측정 시도 전에 이전 필드를 지운다. mesh hash, canonical 객체, 핀,
측정 voltage/axis/source 선택이 달라지거나 과거 step 표시 중이면 필드 미표시.

로컬: 엔진 import 금지, 합성 API와 AST GUI 메서드로 실패/정상/불변성 검증.
원격: 기존 uniform ACTIVE 실제 DD/Tk 경로를 재사용. 실제 노드 배열과 캡처
값 동일, 전위의 기존 선형 해 tolerance 유지, n/p finite/positive, 3개 layer
모든 점 표시, 잘못된 전압 재시도 뒤 캡처 없음, 장치 누수 없음 확인.
CHEMICAL/UNKNOWN 기존 대조군은 solve/write 0 유지. 기존 단위/출처 테스트 실행.
PN·MOSFET·일반 2D 물리 승인을 주장하지 않는다.

공식 API 사용 근거: https://github.com/devsim/devsim_3dmos/blob/main/ieee/mos90.py
(get_node_model_values로 Potential 조회). 새 engine 내부 수정·solve 추가 없음.
