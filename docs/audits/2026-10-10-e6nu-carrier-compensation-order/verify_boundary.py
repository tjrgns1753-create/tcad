"""별도 U2 실험의 실제 지원/차단 기록과 원본 출처를 엔진 없이 재검사."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
SHA='0ac145d48dbb0984b2b417bfa0c71075d668c717'
RUN='37977642901'


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from judge import CASES, PROFILES
from judge_boundary import evaluate


def main(root):
    repo=Path(__file__).resolve().parents[3]
    audit=Path(__file__).resolve().parent
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha']==summary['source']['git_head']==SHA
    assert summary['source']['run_id']==RUN and summary['runner']['runner_environment']=='github-hosted'
    assert summary['status']=='PASS' and summary['exit_code']==0 and not summary['omitted_outputs']
    env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1')
    for r in summary['inputs']:
        blob=subprocess.check_output(['git','show',SHA+':'+r['path']],cwd=repo,env=env)
        lf=blob.replace(b'\r\n',b'\n')
        assert any(len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256'] for b in (blob,lf,lf.replace(b'\n',b'\r\n'))),r['path']
    for r in summary['outputs']+[summary['log']]:
        blob=(root/('outputs/'+r['path'] if 'path' in r else r['file'])).read_bytes()
        assert len(blob)==r['bytes'] and hashlib.sha256(blob).hexdigest()==r['sha256']
    out=root/'outputs/e6nu_boundary_out'
    tests=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps'])=={'matrix','judge','bias','caption','no_resurrection'}
    assert all(r['status']=='COMPLETED' and r['exit_code']==0 and r['cleanup_ok'] is True for r in tests['steps'].values())
    records=json.loads((out/'records.json').read_text(encoding='utf-8'))
    verdict=json.loads((out/'verdict.json').read_text(encoding='utf-8'))
    assert evaluate(records)==verdict and verdict['pass'] is True and len(verdict['checks'])==30
    assert verdict['numeric_cases']==4 and verdict['blocked_cases']==8 and verdict['actual_solves']==12
    for name,profile,voltage in CASES:
        r=records[name]
        if profile in {'n_single','p_single'}:
            blob=(out/(name+'_fields.json')).read_bytes()
            assert hashlib.sha256(blob).hexdigest()==r['file_sha256']
            payload=json.loads(blob)
            assert payload['snapshot']==r['snapshot'] and payload['source_evidence']==r['source_evidence']
            point=r['measurement']['points'][0]
            for key in ('voltages','currents','converged'):
                assert payload['measurement'][key]==point[key]
            assert payload['measurement']['metadata']==r['measurement']['metadata']
            assert blob==(audit/'raw_initial/outputs/e6nu_out'/ (name+'_fields.json')).read_bytes()
        else:
            assert not (out/(name+'_blocked.json')).exists()
            assert r['solves']==r['doping_writes']==r['field_capture_attempts']==0
            assert r['measurement'] is None and r['snapshot'] is None
            assert r['canonical_queries_before']==r['canonical_queries_after']
            assert r['reason_code']=='COMPENSATED_TRANSPORT_MODEL_MISSING'
    print(json.dumps({'pass':True,'inputs':len(summary['inputs']),'raw_files':len(summary['outputs'])+1,
        'numeric_cases':4,'blocked_cases':8,'actual_solves':12,'checks':30,
        'entire_four_initial_numeric_exports_unchanged':True,'engine_imports':0}))


if __name__=='__main__':
    main(Path(sys.argv[1]))
