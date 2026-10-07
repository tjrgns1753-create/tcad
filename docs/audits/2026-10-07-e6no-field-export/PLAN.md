# E6N-O 실제 노드 필드 증거 저장

화면에 연결된 성공한 2-terminal 실제 노드 배열을 단일 JSON으로 보존한다.
Potential V, Electrons/Holes cm^-3, 좌표 um, 실제 모든 접점 voltage/current,
current 단위 metadata, input mesh SHA와 GUI_SESSION_ONLY canonical 출처를 포함.
이는 engine restart/checkpoint 또는 일반 물리 승인 파일이 아니다.
추가 solve/공정/도핑 쓰기/모델/PN gate 변경 없음.

새 측정 시도·reset에서 필드와 연계 결과를 함께 지운다. mesh/state/pins/측정 설정
불일치·이력 표시·없거나 실패한 결과는 저장 대화상자 전에 차단한다. 대화상자 후에도
출처를 재검사한다. 단일 파일 임시 저장→os.replace로 완성본만 교체한다.
invalid 배열/길이/negative carrier/nonfinite/미수렴/voltage·unit·출처 누락은 저장 금지.
내부 Python object id를 portable canonical proof로 저장하지 않는다.

로컬: 순수 Python 저장 성공/거부/기존 파일 보존/임시 파일 정리 + AST UI 차단.
원격: 기존 uniform ACTIVE DD 실제 Tk 측정에서 export callback으로 한국어 경로
JSON 저장, snapshot과 배열 동일, contact+단위+source hash 비교. 실제 bias 하나만
사용하고 기존 CHEMICAL/UNKNOWN solve/write0 대조군 유지. 이후 원시 artifact를
독립 해시·배열·전압·단위 대조. 전체 회귀·일반 PN/MOS 승인 없음.
