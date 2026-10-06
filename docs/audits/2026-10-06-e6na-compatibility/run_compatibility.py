"""엔진 없는 원격 Python/Job/AST 호환성 시험."""
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUDIT = ROOT / 'docs/audits/2026-10-02-e6na-import-reduction'
PLAN_SHA = 'a3cdcaf553a582f2ed4ac3b90d4230ed2834509d04618922254eb0b1e2ed5c8f'
TESTS = ('test_contract.py', 'test_review_followup.py',
         'test_flux_source_contract.py', 'test_resource_supervisor.py',
         'test_supervised_entry.py', 'test_positive_geometry.py')


def no_engine(event, args):
    if event == 'import' and args[0].split('.')[0] in ('devsim', 'viennaps', 'viennals'):
        raise RuntimeError('ENGINE_IMPORT_FORBIDDEN')


def main():
    sys.addaudithook(no_engine)
    if '--child' in sys.argv:
        name = sys.argv[-1]
        if name not in TESTS:
            raise ValueError('UNKNOWN_TEST')
        sys.path.insert(0, str(AUDIT))
        sys.argv = [str(AUDIT / name)]
        runpy.run_path(str(AUDIT / name), run_name='__main__')
        if any(n.split('.')[0] in ('devsim', 'viennaps', 'viennals') for n in sys.modules):
            raise RuntimeError('ENGINE_MODULE_PRESENT')
        return 0
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.name != 'nt':
        raise RuntimeError('REMOTE_WINDOWS_REQUIRED')
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('PYTHON_3_11_REQUIRED')
    digest = hashlib.sha256((HERE / 'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    if digest != PLAN_SHA:
        raise RuntimeError('PLAN_HASH_MISMATCH')
    sys.path.insert(0, str(AUDIT))
    from flux_source_contract import require_reviewed_source
    from resource_supervisor import supervise
    dist = importlib.metadata.distribution('devsim')
    helper = Path(dist.locate_file('devsim/python_packages/simple_physics.py'))
    source = helper.read_text(encoding='utf-8')
    funcs = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
             and n.name == 'CreateSiliconPotentialOnly']
    if len(funcs) != 1:
        raise RuntimeError('OFFICIAL_HELPER_NOT_UNIQUE')
    ast_sha = require_reviewed_source(ast.get_source_segment(source, funcs[0]))
    out = ROOT / 'e6na_compat_out'
    out.mkdir(exist_ok=True)
    report = {'status': 'STARTED', 'plan_sha': digest, 'python': sys.version.split()[0],
              'devsim_distribution_version': dist.version, 'reviewed_ast_sha': ast_sha,
              'helper_file_sha': hashlib.sha256(helper.read_bytes()).hexdigest(),
              'engine_imports': 0, 'actual_solves': 0, 'tests': []}
    deadline = time.monotonic() + 110
    for name in TESTS:
        log = out / (name + '.log')
        rec = supervise([sys.executable, '-B', str(Path(__file__).resolve()), '--child', name],
                        str(ROOT), str(log), candidate_s=20, total_deadline=deadline)
        rec['test'] = name
        # Artifact logs are public; remove local/runner path identities even on failures.
        text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
        for value in (str(ROOT), str(Path.home()), os.environ.get('USERPROFILE', '')):
            if value:
                text = text.replace(value, '<REDACTED_PATH>')
        log.write_text(text, encoding='utf-8', newline='\n')
        report['tests'].append(rec)
        if rec['status'] != 'COMPLETED' or rec.get('cleanup_ok') is not True:
            break
    report['status'] = ('PASS' if len(report['tests']) == len(TESTS)
                        and all(r['status'] == 'COMPLETED' and r['cleanup_ok'] is True
                                for r in report['tests']) else 'FAIL')
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
