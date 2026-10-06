"""부모 통합 경로의 합성 child 증거. 엔진과 remote 실행은 없음."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import run_e6na as R


def run_case(kind):
    with tempfile.TemporaryDirectory(prefix='e6na_entry_') as tmp:
        root=Path(tmp)
        calls=[]
        def fake(argv,cwd,log,**kw):
            lv=argv[-1]
            calls.append(lv)
            assert argv[-2]=='--candidate' and 'total_deadline' in kw
            monitor=dict(status='COMPLETED',cleanup_ok=True)
            if kind=='timeout':
                return dict(status='TIMEOUT',cleanup_ok=True)
            folder=root/'e6na_out'/lv
            folder.mkdir()
            array=folder/(lv+'.npz')
            array.write_bytes(b'synthetic unparsed array container')
            rec=dict(status='IMPORT_PASS', cleanup_ok=kind!='cleanup',raw_bytes=100,
                     array_sha=hashlib.sha256(array.read_bytes()).hexdigest(),
                     diagnostic={'verdict':'INCONCLUSIVE' if kind=='inconclusive' else 'NONINVARIANCE_WITNESS'})
            if kind=='hash':
                rec['array_sha']='0'*64
            child=dict(plan_sha=R.PLAN_SHA,solve_attempts=1 if kind=='solve' else 0,levels={lv:rec},
                       candidate=lv,official_flux_source_matches=True,execution_status='COMPLETED')
            if kind!='missing':
                (folder/'result.json').write_text(json.dumps(child),encoding='utf-8')
            return monitor
        with patch.object(R,'ROOT',root),patch.object(R,'require_inputs'),patch.object(R,'supervise',fake),patch.dict(R.os.environ,{'RUNNER_ENVIRONMENT':'github-hosted'}):
            rc=R._supervised_execute()
        report=json.loads((root/'e6na_out/result.json').read_text())
        if kind=='normal':
            assert rc==0 and report['verdict']=='NONINVARIANCE_WITNESS' and len(calls)==3
        elif kind=='inconclusive':
            assert rc==0 and report['verdict']=='INCONCLUSIVE' and len(calls)==1
        else:
            assert rc==1 and report['verdict']=='FAIL' and len(calls)==1
        if kind in ('timeout','missing'):
            assert report['solve_attempts'] is None
        if len(calls)==1:
            assert all(report['levels'][lv]['status']=='NOT_RUN' for lv in R.M.LEVELS[1:])
        print('PARENT_PATH',kind,'PASS')


if __name__=='__main__':
    for kind in ('normal','inconclusive','timeout','missing','hash','cleanup','solve'):
        run_case(kind)
    original=Path.read_bytes
    calls=[]
    def altered(path):
        return b'wrong resource contract' if path.name=='RESOURCE_EXECUTION_CONTRACT.md' else original(path)
    with patch.object(Path,'read_bytes',altered),patch.object(R,'_execute',lambda:calls.append(1)):
        try:
            R.execute()
        except ValueError as exc:
            assert 'RESOURCE_CONTRACT_PREFLIGHT_BLOCKED' in str(exc)
        else:
            raise AssertionError('resource contract bypass')
    assert not calls
    print('RESOURCE_CONTRACT_BLOCK callback=0')
    assert 'devsim' not in sys.modules and 'viennaps' not in sys.modules
    print('SUPERVISED_ENTRY_PASS; ENGINE_IMPORTS=0')
