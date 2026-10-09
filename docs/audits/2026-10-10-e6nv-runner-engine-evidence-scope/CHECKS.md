# E6N-V: 원격 엔진 정보 조회와 실제 계산 증거의 범위를 분리한다

물리 모델·GUI·gate 변경이 아닌 실행기 증거 표기 수정이다.
시작 HEAD 0ac145d, U2 원격 실행은 그 고정 SHA로 진행 중이며 중복/취소하지 않는다.

수정 전 실제 AST 분기의 `engine_info=False`는 `NOT_IMPORTED / engine-free profile`을
만들었다. 이미 T/U의 실제 child solve가 있는 동일 옵션에서 나타나는 문구라 부정확하다.
새 표기는 NOT_PROBED, scope=ISOLATED_VERSION_PROBE, profile_execution_observed=false다.
engine_info=True/default는 기존 별도 공개 get_parameter(info) probe를 그대로 호출하며
버전·extended_precision·direct_solver 결과를 유지하고 범위만 추가한다.

검증 기준:
- 실제 runner 분기를 AST 추출해 False/True/default/실패 probe 4가지를 검사.
- False에서 probe callback0회, True/default에서 각1회.
- 실패 probe는 error/exit_code 그대로, 버전 성공 기록으로 대체하지 않음.
- 실제 원격 summary도 같은 NOT_PROBED/범위 필드를 기록하는지 확인.
- 합성 test에는 엔진/Tk import를 audit hook으로 금지한다.
- 기존 requested bias/caption 단위 대조군도 통과해야 한다.

새 원격 profile은 엔진 없는 3개 테스트만 한다. 물리 solve0회이며 T/U 계산을
재실행하지 않는다. timeout150초/개별30초/artifact2MB.
원본 과거 summary·PLAN·실제 run outputs는 불변이고 이 표기로 solve 성공을 승인하지 않는다.
