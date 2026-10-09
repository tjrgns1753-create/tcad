# E6N-Q 완료: 2단자 필드 저장의 불완전 접점 기록 차단

## 판정

`TWO_TERMINAL_FIELD_EVIDENCE_COMPLETE`: 현재 2단자 필드 저장 경계에 한정한다.
새 물리 지원, PN 검증, 산화 지원 또는 gate 해제를 승인하지 않는다.

## 시작·범위

시작 HEAD af63e0973e008c74a6b5ab43f30b4b5392b30b48,
브랜치 claude/remote-runner. tracked 변경 없음. 계산 프로세스 없음,
이전 세 원격 job 모두 완료. Serena 도구 미제공으로 직접 읽기 fallback.
PLAN을 c0aa0ef에서 먼저 커밋하고 결과 기준을 고정했다.

## 수정 전/후 반례

| 합성 기록 | 수정 전 | 수정 후 |
|---|---|---|
| source만 존재 | ACCEPTED | BLOCKED |
| ground 전류 누락 | ACCEPTED | BLOCKED |
| ground 전압 누락 | ACCEPTED | BLOCKED |
| 전압/전류 접점 이름 불일치 | ACCEPTED | BLOCKED |
| 전류에만 추가 접점 | ACCEPTED | BLOCKED |
| 세 접점 | ACCEPTED | BLOCKED |
| 빈 접점 이름 | ACCEPTED | BLOCKED |
| 문자열이 아닌 접점 이름 | ACCEPTED | BLOCKED |

모든 차단 케이스에서 기존 대상 바이트 및 임시 파일 부재를 assert했다.
정상 source/ground, 임의 이름·비영 기준 전압·음수 전류, 0 bias·0 전류
3개 대조군은 값 변경 없이 저장된다. 없는 sweep_contact도 차단한다.
로컬/원격 합성 테스트 모두 엔진·Tk import를 trap하며 호출 0회다.

## 실제 production semantic diff (전체)

파일 tcad/characterization/node_fields.py, save_node_field_evidence:

```diff
     point = result.points[0]
     validate_bias_point(point)
+    contacts = set(point.voltages)
+    if (len(contacts) != 2 or contacts != set(point.currents) or
+            any(not isinstance(name, str) or not name.strip() for name in contacts)):
+        raise ValueError("Field export requires the same two named contacts in voltages and currents.")
     if result.sweep_contact not in point.voltages:
```

기존 공통 validator의 다단자 계약은 변경하지 않았다. 새로운 KCL tolerance,
전위 이동, 결손 값 생성 또는 engine 수정도 없다.
다른 변경: 신규 unit test, 원격 감사 driver, profile allowlist/request, 본 감사 자료.

## 원격 검증

[Actions run 37972284680](https://github.com/tjrgns1753-create/tcad/actions/runs/37972284680),
실행 SHA 4b58898c91dc10b319a2a49b8e4242517732f847,
artifact remote-run-65. 2026-10-09 18:17:51~18:18:51 UTC.
Windows GitHub-hosted runner. 실제 uniform ACTIVE Si, +1mV, 73 노드 조건 그대로.

export / contacts / pure / hover / snapshot / readout / gate_control
7개 모두 COMPLETED, rc=0, cleanup_ok=True.
실제 export 측정 solve는 기존 3회. 표시·저장을 위한 추가 solve는 없다.
대조군 자체의 실제 solve는 별도 존재하므로 원격 전체 solve=0이라 주장하지 않는다.

독립 verify_artifact.py는 14개 입력을 실행 SHA의 git blob과 대조하고,
12개 raw 파일의 크기·해시, 실행 ID, runner, 누락 산출물 부재를 확인했다.
전체 JSON이 E6N-P 고정 원시 결과와 동일하다. 일부 선택 노드만 비교하지 않는다.

- 실제 노드 JSON SHA256:
  8111c300184eccc680938178e6112fc6e8152e2b4789cc1cdfa79d935df1056f
- source mesh SHA256:
  ad1ad8a16d43fd2e0b57653258d9f6e92aff02154112df0fc732c95993eb5805
- 전위·전자·정공 73개 전체 배열, 좌표, 두 접점 전압·전류 모두 불변.
- 단위 V / cm^-3 / µm / A/cm, 2D per_out_of_plane_depth 유지.
- 오래된 map/readout 삭제, 실패 재시도 저장 차단, device cleanup 모두 유지.

raw는 export되어 검증된 파일 그대로 보존하며 .gitattributes에서 변환하지 않는다.
원본 source VTU는 artifact에 없고 실제 원격 검사에서 계산한 해시만 보존된다.
GUI_SESSION_ONLY는 재시작 가능한 canonical checkpoint가 아니다.

## 정적 검사와 한계

로컬 접점/기존 export/노드 capture 국소 unit 3개 rc=0.
git diff --check rc=0. 전체 회귀는 실행하지 않았다.
로컬 validate-only 첫 실행은 출력 권한에 막혔다. writable 출력 경로로
재검증해 VALIDATED_ONLY를 얻었으며 물리 계산은 수행하지 않았다.
이 검사는 incomplete 기록 차단이지 전류 보존이나 PN 정확성 증명이 아니다.
2단자 외 필드 저장은 별도 계약 없이 허용하지 않는다.
production 물리 코드, canonical 상태, 기존 물리 gate, main 브랜치는 불변이다.
