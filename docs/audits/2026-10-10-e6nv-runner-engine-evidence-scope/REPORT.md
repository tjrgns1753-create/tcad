# E6N-V: 버전 정보 조회와 실제 엔진 사용 증거의 범위를 정정했다

**RUNNER_ENGINE_INFO_SCOPE_CORRECTED**. 물리 모델이나 엔진 기능의 승인 아니다.
수정 전 실제 실행기 AST 분기는 engine_info=False이면 NOT_IMPORTED와
engine-free profile을 기록했다. 실제 T/U처럼 child가 solve하는 profile에서도
같은 옵션을 사용하므로 전체 계산이 엔진 미사용이라는 의미로 읽으면 잘못이다.

## 실제 변경과 전/후 검증

`remote/run_profile.py:205`의 정보 조회 분기만 변경했다:

```diff
 if prof.get("engine_info", True):
     summary["devsim"] = devsim_info()
+    summary["devsim"].update({"scope": "ISOLATED_VERSION_PROBE", "profile_execution_observed": False})
 else:
-    summary["devsim"] = {"status": "NOT_IMPORTED", "reason": "engine-free profile"}
+    summary["devsim"] = {"status": "NOT_PROBED", "scope": "ISOLATED_VERSION_PROBE",
+                         "profile_execution_observed": False,
+                         "reason": "engine_info disabled; child engine imports/solves are not observed by this record; inspect profile outputs"}
```

False에서 probe callback0, True/default에서 각1, 실패 probe의 error/exit_code
보존을 실제 AST 추출 테스트로 확인했다. 물리 엔진을 import하지 않고 합성 probe로
분기 계약을 검증했다. 새 unit 테스트와 README의 증거 범위 설명을 추가했다.
이전 raw summary는 수정하지 않았다. 실제 child solve 수는 profile outputs에서
따로 확인하며 이 메타데이터 자체로 0 solve/물리 승인이라고 판정하지 않는다.

## 원격 결과와 독립 재검사

- 실행 SHA 3cfed5d4768c8f5232af0b02b2dd5d40a70ef37c.
- [원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37978207835).
- artifact remote-run-71, parent1.668초, scope/bias/caption 3단계 rc0, cleanup=true.
- 실제 summary: NOT_PROBED / ISOLATED_VERSION_PROBE / profile_execution_observed=false.
- 전체 원본은 `raw/`, 독립 `verify_artifact.py raw`에서 입력10개와 원본5개
  해시, 실행 SHA/run, 세 단계 결과 및 새 범위 필드를 다시 검사했다.
- 물리 계산 재실행0. 테스트와 독립 재검사에서는 엔진/Tk import를 금지했다.

실패/timeout을 PASS로 바꾸는 로직, subprocess 실행·정리·sanitizer·artifact 수집은
변경하지 않았다. 물리 production/gate/기존 실제 노드 원본/기존 PLAN 무변경.
코드 diff check0. 전체 회귀와 main 병합 없음.
