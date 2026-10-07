# E6N-P 화면 갱신 시 마지막 수치 readout 해제

원인: redraw가 canvas만 지우고 coord_var에는 마지막 mouse hover 숫자를 남긴다.
물리 상태·bias가 바뀌어도 숫자가 남아있을 수 있다. redraw 시작에서 coord_var를
비운다. 새 mouse event에서만 현재 좌표와 지원되는 실제 노드를 다시 조회한다.
물리 식/엔진/gate/수렴 기준 변경 없음.

로컬 AST prefix 재현: stale readout이 기존 redraw 초입 이후에도 남는 반례 →
수정 후 빈 문자열. 원격은 기존 E6N-O 실제 export script의 73-node uniform DD
입력을 그대로 재사용하고 live node hover 후 voltage edit/reset이 readout도
비우는지 추가 assert. 기존 export·단위·canonical gate 대조군 재사용, 추가 solve0.
원시 기존 결과는 변경하지 않고 새 artifact를 별도 보존한다.
