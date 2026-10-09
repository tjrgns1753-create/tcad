"""사전 고정한 실제 통합 script 세 개를 각 한 번 원격 실행."""
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
sys.path.insert(0,str(ROOT/'remote'))
from resource_supervisor import supervise
from run_profile import Sanitizer
MANIFEST_SHA='7d8598783c21d44e4c752583be4f197f992fce47f77dbd30a274a1f730c7b8f3'
PLAN_SHA='faffce40990ded7b3423e2fdf9d804b047dd4f800769b4c38a6208c8c4a14088'


def preflight():
    plan=(HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(plan).hexdigest()!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    blob=(HERE/'MANIFEST.json').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(blob).hexdigest()!=MANIFEST_SHA:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    manifest=json.loads(blob)
    names=[r['path'] for r in manifest['tests']]
    actual=sorted(['tests/unit/test_measurement_missing_profile_status_mock.py', 'tests/unit/test_electrode_source_context_mock.py', 'tests/integration/test_measurement_canonical_state_gate_real.py'])
    if manifest['count']!=3 or len(names)!=3 or len(set(names))!=3 or sorted(names)!=actual:
        raise ValueError('EXACT_THREE_INTEGRATION_INPUTS_REQUIRED')
    for r in manifest['tests']:
        data=(ROOT/r['path']).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=r['lf_sha256']:
            raise ValueError('INTEGRATION_INPUT_HASH_MISMATCH: '+r['path'])
    return names


def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    names=preflight()
    out=ROOT/'e6ny_out'
    out.mkdir(exist_ok=True)
    records={}
    sanitizer=Sanitizer()
    for path in names:
        log=out/(Path(path).stem+'.log')
        result=supervise([sys.executable,'-B',path],ROOT,log,candidate_s=180 if path.startswith('tests/integration/') else 30)
        text=log.read_text(encoding='utf-8',errors='replace')
        log.write_text(sanitizer.clean(text),encoding='utf-8',newline='\n')
        result['input_lf_sha256']=next(r['lf_sha256'] for r in json.loads((HERE/'MANIFEST.json').read_text(encoding='utf-8'))['tests'] if r['path']==path)
        result['skip_detected']=('SKIPPED:' in text or 'SKIP:' in text)
        result['log_sha256']=hashlib.sha256(log.read_bytes()).hexdigest()
        result['log_file']=log.name
        records[path]=result
        (out/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(json.dumps({'file':path,'status':result['status'],'rc':result.get('exit_code'),'completed_files':len(records)}),flush=True)
    counts={'PASS':0,'FAIL':0,'TIMEOUT':0,'ERROR':0,'SKIP':0}
    for r in records.values():
        label='PASS' if r['status']=='COMPLETED' and r.get('exit_code')==0 and r['cleanup_ok'] and not r['skip_detected'] else (
            'SKIP' if r['skip_detected'] else 'FAIL' if r['status']=='FAIL' else 'TIMEOUT' if r['status']=='TIMEOUT' else 'ERROR')
        counts[label]+=1
    passed=len(records)==3 and counts['PASS']==3
    (out/'verdict.json').write_text(json.dumps({'pass':passed,'counts':counts,'expected_files':3,
        'recorded_files':len(records),'scope':'ACTIVATION_STATUS_CONTRACT_NOT_ACTIVATION_PHYSICS'},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'counts':counts,'recorded_files':len(records)}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
