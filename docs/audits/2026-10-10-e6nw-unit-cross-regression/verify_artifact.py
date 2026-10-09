"""원격 출처·원본 해시·전체 배열과 해석 판정을 독립 재검사. 엔진 없음."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SHA = '4ab9da6cc4bba7d57fcfb5991192563d3131f019'
RUN = '37978922405'


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)


def main(root):
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha'] == summary['source']['git_head'] == SHA
    assert summary['source']['run_id'] == RUN and summary['runner']['runner_environment'] == 'github-hosted'
    assert summary['status'] in {'PASS', 'FAIL'} and not summary['omitted_outputs']
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    for record in summary['inputs']:
        blob = subprocess.check_output(['git', '-c', 'safe.directory=' + str(repo), 'show', SHA + ':' + record['path']], cwd=repo, env=env)
        lf = blob.replace(b'\r\n', b'\n')
        assert any(len(b) == record['bytes'] and hashlib.sha256(b).hexdigest() == record['sha256']
                   for b in (blob, lf, lf.replace(b'\n', b'\r\n'))), record['path']
    for record in summary['outputs'] + [summary['log']]:
        path = root / ('outputs/' + record['path'] if 'path' in record else record['file'])
        blob = path.read_bytes()
        assert len(blob) == record['bytes'] and hashlib.sha256(blob).hexdigest() == record['sha256']
    out = root / 'outputs/e6nw_out'
    records = json.loads((out / 'records.json').read_text(encoding='utf-8'))
    verdict = json.loads((out / 'verdict.json').read_text(encoding='utf-8'))
    manifest_blob = subprocess.check_output(['git', '-c', 'safe.directory=' + str(repo), 'show', SHA + ':docs/audits/2026-10-10-e6nw-unit-cross-regression/MANIFEST.json'], cwd=repo, env=env)
    manifest = json.loads(manifest_blob)
    assert manifest['count'] == len(manifest['tests']) == len(records) == 83
    assert set(records) == {r['path'] for r in manifest['tests']}
    counts = {'PASS': 0, 'FAIL': 0, 'TIMEOUT': 0, 'ERROR': 0}
    for record in manifest['tests']:
        path = record['path']
        r = records[path]
        assert path.startswith('tests/unit/') and r['input_lf_sha256'] == record['lf_sha256']
        blob = subprocess.check_output(['git', '-c', 'safe.directory=' + str(repo), 'show', SHA + ':' + path], cwd=repo, env=env)
        assert hashlib.sha256(blob.replace(b'\r\n', b'\n')).hexdigest() == record['lf_sha256']
        log = out / r['log_file']
        assert log.name == Path(path).stem + '.log'
        assert hashlib.sha256(log.read_bytes()).hexdigest() == r['log_sha256']
        label = 'PASS' if r['status'] == 'COMPLETED' and r.get('exit_code') == 0 and r['cleanup_ok'] else (
            'FAIL' if r['status'] == 'FAIL' else 'TIMEOUT' if r['status'] == 'TIMEOUT' else 'ERROR')
        counts[label] += 1
    passed = counts['PASS'] == 83
    assert verdict == {'pass': passed, 'counts': counts, 'expected_files': 83, 'recorded_files': 83,
                       'scope': 'UNIT_SCRIPTS_NOT_PHYSICAL_APPROVAL'}
    assert summary['status'] == ('PASS' if passed else 'FAIL') and summary['exit_code'] == (0 if passed else 1)
    info = summary['devsim']
    assert info['status'] == 'NOT_PROBED' and info['scope'] == 'ISOLATED_VERSION_PROBE'
    assert info['profile_execution_observed'] is False
    print(json.dumps({'evidence_integrity_pass': True, 'suite_pass': passed, 'inputs': len(summary['inputs']),
        'unit_input_hashes': 83, 'raw_files': len(summary['outputs']) + 1, 'counts': counts,
        'engine_imports_in_independent_verifier': 0}))



if __name__ == '__main__':
    main(Path(sys.argv[1]))
