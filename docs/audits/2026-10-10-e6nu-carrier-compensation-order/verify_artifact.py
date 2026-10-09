"""원본 출처/해시/도핑 배열/전체 field와 판정 검증. 엔진 없음."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
SHA='d6c1f1393170380cd88406c90265b6b50ebbd9ad'
RUN='37976122403'


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from judge import evaluate, CASES, PROFILES


def main(root):
    repo=Path(__file__).resolve().parents[3]
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha']==summary['source']['git_head']==SHA
    assert summary['source']['run_id']==RUN and summary['runner']['runner_environment']=='github-hosted'
    assert summary['status']=='FAIL' and summary['exit_code']==1 and not summary['omitted_outputs']
    env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1')
    for r in summary['inputs']:
        blob=subprocess.check_output(['git','show',SHA+':'+r['path']],cwd=repo,env=env)
        lf=blob.replace(b'\r\n',b'\n')
        assert any(len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
                   for b in (blob,lf,lf.replace(b'\n',b'\r\n'))),r['path']
    for r in summary['outputs']+[summary['log']]:
        path=root/('outputs/'+r['path'] if 'path' in r else r['file'])
        blob=path.read_bytes()
        assert len(blob)==r['bytes'] and hashlib.sha256(blob).hexdigest()==r['sha256']
    out=root/'outputs/e6nu_out'
    tests=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is False and set(tests['steps'])=={'matrix','judge','bias','caption','no_resurrection'}
    assert tests['steps']['matrix']['status']=='FAIL' and tests['steps']['matrix']['exit_code']==1
    assert all(r['cleanup_ok'] is True for r in tests['steps'].values())
    assert all(r['status']=='COMPLETED' and r['exit_code']==0 for n,r in tests['steps'].items() if n!='matrix')
    records=json.loads((out/'records.json').read_text(encoding='utf-8'))
    assert not (out/'verdict.json').exists()
    assert evaluate(records)['pass'] is False  # 불완전한 원래 실험은 여전히 실패다.
    assert set(records)=={'n_single_pos','n_single_neg','p_single_pos','p_single_neg'}
    assert sum(r['solves'] for r in records.values())==12
    matrix_log=(out/'matrix.log').read_text(encoding='utf-8')
    assert 'n_comp_da_pos' in matrix_log and 'COMPENSATED_TRANSPORT_MODEL_MISSING' in matrix_log
    for name,profile,voltage in CASES:
        if name not in records:
            continue
        r=records[name]
        blob=(out/(name+'_fields.json')).read_bytes()
        assert hashlib.sha256(blob).hexdigest()==r['file_sha256']
        payload=json.loads(blob)
        assert payload['snapshot']==r['snapshot'] and payload['source_evidence']==r['source_evidence']
        point=r['measurement']['points'][0]
        for key in ('voltages','currents','converged'):
            assert payload['measurement'][key]==point[key]
        assert payload['measurement']['metadata']==r['measurement']['metadata']
        assert r['steps']==[list(step) for step in PROFILES[profile]]
        # 미리 계산한 요약값이 아닌 원본 배열로 두 선언이 엔진까지 전달됐는지 확인한다.
        nd,na=(sum(step[k] for step in PROFILES[profile]) for k in (0,1))
        assert r['doping_arrays']['Donors']==[nd]*73 and r['doping_arrays']['Acceptors']==[na]*73
        assert r['doping_arrays']['NetDoping']==[nd-na]*73
    prior=(repo/'docs/audits/2026-10-07-e6np-readout-invalidation/raw/outputs/e6no_out/실제노드.json').read_bytes()
    assert (out/'n_single_pos_fields.json').read_bytes()==prior
    print(json.dumps({'pass':True,'inputs':len(summary['inputs']),'raw_files':len(summary['outputs'])+1,
        'original_experiment_status':'FAIL','completed_numeric_cases':4,'recorded_solves':12,
        'compensated_failure_observed':True,'remaining_requested_cases_not_run':7,
        'entire_prior_export_unchanged':True,'engine_imports':0}))


if __name__=='__main__':
    main(Path(sys.argv[1]))
