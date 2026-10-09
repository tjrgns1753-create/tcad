"""원격 출처·원본 해시·전체 배열과 해석 판정을 독립 재검사. 엔진 없음."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SHA = '3cfed5d4768c8f5232af0b02b2dd5d40a70ef37c'
RUN = '37978207835'


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)


def main(root):
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha'] == summary['source']['git_head'] == SHA
    assert summary['source']['run_id'] == RUN and summary['runner']['runner_environment'] == 'github-hosted'
    assert summary['status'] == 'PASS' and summary['exit_code'] == 0 and not summary['omitted_outputs']
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    for record in summary['inputs']:
        blob = subprocess.check_output(['git', 'show', SHA + ':' + record['path']], cwd=repo, env=env)
        lf = blob.replace(b'\r\n', b'\n')
        assert any(len(b) == record['bytes'] and hashlib.sha256(b).hexdigest() == record['sha256']
                   for b in (blob, lf, lf.replace(b'\n', b'\r\n'))), record['path']
    for record in summary['outputs'] + [summary['log']]:
        path = root / ('outputs/' + record['path'] if 'path' in record else record['file'])
        blob = path.read_bytes()
        assert len(blob) == record['bytes'] and hashlib.sha256(blob).hexdigest() == record['sha256']
    out = root / 'outputs/e6nv_out'
    tests = json.loads((out / 'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps']) == {'scope', 'bias', 'caption'}
    assert all(r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
               for r in tests['steps'].values())
    info = summary['devsim']
    assert info['status'] == 'NOT_PROBED' and info['scope'] == 'ISOLATED_VERSION_PROBE'
    assert info['profile_execution_observed'] is False and 'child' in info['reason']
    assert 'engine-free profile' not in info['reason']
    assert 'PASS actual branch' in (out / 'scope.log').read_text(encoding='utf-8')
    print(json.dumps({'pass': True, 'inputs': len(summary['inputs']), 'raw_files': len(summary['outputs']) + 1,
        'steps': 3, 'probe_scope_confirmed': True, 'engine_imports': 0}))



if __name__ == '__main__':
    main(Path(sys.argv[1]))
