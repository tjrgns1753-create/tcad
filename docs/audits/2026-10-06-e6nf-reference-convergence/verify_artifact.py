"""원격 원시 증거의 해시 및 수렴 판정 재검사, 엔진 import 금지."""
import hashlib
import json
import sys


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in ('devsim','viennaps','viennals'):
        raise AssertionError('LOCAL_ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
import convergence as F

raw=F.HERE/'raw'
summary=json.loads((raw/'summary.json').read_text())
assert summary['source']['github_sha']=='696c435a3894b3911bffbf3973f0ea422f4d8fff'
assert summary['source']['git_head']==summary['source']['github_sha']
assert summary['source']['run_id']=='37430543401'
assert summary['runner']['github_hosted_confirmed'] is True
assert summary['log_truncated'] is False and summary['omitted_outputs']==[]
for rec in summary['outputs']:
    data=(raw/'outputs'/rec['path']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==rec['sha256']
    assert len(data)==rec['bytes']
log=(raw/'run.log').read_bytes()
assert hashlib.sha256(log).hexdigest()==summary['log']['sha256']
assert len(log)==summary['log']['bytes']
out=raw/'outputs/e6nf_out'
saved=json.loads((out/'result.json').read_text())
recomputed=F.judge(out)
assert recomputed==saved
record=json.loads((out/'reference/record.json').read_text())
assert sum(d['solves'] for d in record['devices'].values())==14
assert sum(d['solve_attempts'] for d in record['devices'].values())==14
assert F.preflight()==F.PLAN_SHA
print(json.dumps({'status':saved['status'],'checks':len(saved['checks']),
                  'failures':[c['name'] for c in saved['checks'] if not c['pass']],
                  'hashes_checked':len(summary['outputs'])+1,'rejudgement_equal':True,
                  'local_engine_imports':0,'actual_remote_1d_solves':14,
                  'metrics':saved['metrics']},indent=2))
