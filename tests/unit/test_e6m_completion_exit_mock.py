"""엔진 없이 PN 감사의 실패/미평가가 정상 종료되지 않는지 검증한다."""
import ast
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts'))
import judge_e6m as J


def run():
    valid = {'EVIDENCE_INTEGRITY': {'verdict': 'PASS', 'problems': []}}
    valid.update({k: {'verdict': 'PASS', 'checks': [{'pass': True}]} for k in J.CATEGORIES})
    assert J.completion_exit_code(valid) == 0
    count = 1
    for name in J.CATEGORIES:
        for status in ('FAIL', 'NOT_EVALUATED', 'BLOCKED_GATE_OR_AUDIT_DOPING', 'EVIDENCE_INTEGRITY_FAIL'):
            v = copy.deepcopy(valid)
            v[name]['verdict'] = status
            assert J.completion_exit_code(v) == 1, (name, status)
            count += 1
        v = copy.deepcopy(valid)
        del v[name]
        assert J.completion_exit_code(v) == 1
        count += 1
        for checks in ([], None, [{'pass': 1}], [{'pass': 'True'}], [{'pass': False}], [{}]):
            v = copy.deepcopy(valid)
            v[name]['checks'] = checks
            assert J.completion_exit_code(v) == 1
            count += 1
    for record in (None, {}, {'verdict': 'PASS'}, {'verdict': 'PASS', 'problems': ['missing']},
                   {'verdict': 'FAIL', 'problems': []}):
        v = copy.deepcopy(valid)
        v['EVIDENCE_INTEGRITY'] = record
        assert J.completion_exit_code(v) == 1
        count += 1
    assert J.completion_exit_code(None) == 1
    count += 1
    source = ROOT / 'tests/integration/test_pn_2d_1d_consistency_real.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    assert ast.unparse(returns[0].value) == 'J.completion_exit_code(verdict)'
    count += 1
    assert not {'devsim', 'viennaps', 'viennals'}.intersection(sys.modules)
    print(f'PASS: {count} completion-contract cases; engine imports=0; solves=0')
    return count


if __name__ == '__main__':
    run()
