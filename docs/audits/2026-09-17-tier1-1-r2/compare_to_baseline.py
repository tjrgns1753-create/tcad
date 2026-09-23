"""Compare the Tier 1-1 supplement (r2) full audit with the 2026-09-16
baseline, and show the Tier 1-1 (first round) audit alongside.

Failure categories use exactly the classifier of
docs/audits/2026-09-16/summarize_audit.py so every run is labelled the
same way. Writes BASELINE_DIFF.md next to this script; reruns nothing.
"""
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE.parent / "2026-09-16/validated-env"
T1_DIR = HERE.parent / "2026-09-17-tier1-1/full-audit"
NEW_DIR = HERE / "full-audit"


def category(run_dir, row):
    if row["status"] == "PASS":
        return ""
    if row["status"] == "AUDIT_TIMEOUT":
        return "진단 시간 예산 초과"
    content = (run_dir / row["log"]).read_text(encoding="utf-8", errors="replace")
    if "raise UnsupportedDopingState" in content:
        return "v2 미지원 상태로 device mapping 차단"
    if "AttributeError:" in content or "TypeError:" in content:
        return "API/자료형 호환 실패"
    if "StopIteration" in content:
        return "예상한 도핑 profile 부재"
    if "AssertionError" in content:
        return "assertion 불일치"
    return "기타 실행 실패"


def load(run_dir):
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return data, {r["test"]: r for r in data["results"]}


def summary(rows, run_dir):
    units = [r for r in rows if "unit" in Path(r["test"]).parts]
    integ = [r for r in rows if r not in units]
    return dict(
        total=len(rows),
        status=dict(collections.Counter(r["status"] for r in rows)),
        unit=dict(collections.Counter(r["status"] for r in units)),
        integration=dict(collections.Counter(r["status"] for r in integ)),
        failure_categories=dict(collections.Counter(
            category(run_dir, r) for r in rows if r["status"] != "PASS")),
    )


def main():
    base_data, base = load(BASE_DIR)
    t1_data, t1 = load(T1_DIR)
    new_data, new = load(NEW_DIR)
    if not new_data["complete"]:
        raise SystemExit(f"r2 audit not finished: {len(new)}/{new_data['planned']}")
    assert list(base) == list(new) == list(t1), "the runs must cover the same tests in the same order"
    s_base = summary(base_data["results"], BASE_DIR)
    s_t1 = summary(t1_data["results"], T1_DIR)
    s_new = summary(new_data["results"], NEW_DIR)

    lines = ["# Tier 1-1 보완(r2) 전체 감사 — baseline(2026-09-16) 대비", "",
             f"- baseline: {json.dumps(s_base, ensure_ascii=False)}",
             f"- Tier 1-1 (1차): {json.dumps(s_t1, ensure_ascii=False)}",
             f"- r2 post-fix: {json.dumps(s_new, ensure_ascii=False)}", "",
             "## baseline 대비 상태 또는 실패 분류가 바뀐 파일", "",
             "| 테스트 | baseline | 분류 | Tier 1-1 | r2 | 분류 | 판정 |",
             "|---|---|---|---|---|---|---|"]
    changed = 0
    for test in base:
        b, t, n = base[test], t1[test], new[test]
        cb, cn = category(BASE_DIR, b), category(NEW_DIR, n)
        if (b["status"], cb) == (n["status"], cn):
            continue
        changed += 1
        if b["status"] == "PASS" and n["status"] != "PASS":
            verdict = "신규 실패"
        elif b["status"] != "PASS" and n["status"] == "PASS":
            verdict = "신규 통과"
        else:
            verdict = "기존 실패 지속(분류 변경)"
        lines.append(f"| {Path(test).name} | {b['status']} | {cb} | {t['status']} | {n['status']} | {cn} | {verdict} |")
    if not changed:
        lines.append("| (없음) | | | | | | |")
    lines += ["", "## 전체 파일 대조", "",
              "| 테스트 | baseline | Tier 1-1 | r2 | baseline 초 | r2 초 |", "|---|---|---|---|---:|---:|"]
    for test in base:
        b, t, n = base[test], t1[test], new[test]
        lines.append(f"| {Path(test).name} | {b['status']} | {t['status']} | {n['status']} | "
                     f"{b['seconds']:.2f} | {n['seconds']:.2f} |")
    (HERE / "BASELINE_DIFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(baseline=s_base, tier1_1=s_t1, r2=s_new, changed_files=changed),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
