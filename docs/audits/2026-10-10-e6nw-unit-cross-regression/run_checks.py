"""정확히 고정된 unit 83개만 원격 실행. 결과를 매 파일 뒤 원본으로 기록."""
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
MANIFEST_SHA='bdb284bf6647262847bac8313b6d78676446a72043b6a2c59299ddaf21fc472d'
PLAN_SHA='93b222034937a1319e45f53e6a48b5746218871a87e0326c26ecc24494e92259'


def preflight():
    plan=(HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(plan).hexdigest()!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    blob=(HERE/'MANIFEST.json').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(blob).hexdigest()!=MANIFEST_SHA:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    manifest=json.loads(blob)
    names=[r['path'] for r in manifest['tests']]
    actual=sorted(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'tests/unit').glob('test_*.py'))
    if manifest['count']!=83 or len(names)!=83 or len(set(names))!=83 or sorted(names)!=actual:
        raise ValueError('EXACT_83_TRACKED_UNIT_SET_REQUIRED')
    for r in manifest['tests']:
        data=(ROOT/r['path']).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=r['lf_sha256']:
            raise ValueError('UNIT_INPUT_HASH_MISMATCH: '+r['path'])
    return names


def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    names=preflight()
    out=ROOT/'e6nw_out'
    out.mkdir(exist_ok=True)
    records={}
    sanitizer=Sanitizer()
    for path in names:
        log=out/(Path(path).stem+'.log')
        result=supervise([sys.executable,'-B',path],ROOT,log,candidate_s=60)
        text=log.read_text(encoding='utf-8',errors='replace')
        log.write_text(sanitizer.clean(text),encoding='utf-8',newline='\n')
        result['input_lf_sha256']=next(r['lf_sha256'] for r in json.loads((HERE/'MANIFEST.json').read_text(encoding='utf-8'))['tests'] if r['path']==path)
        result['log_sha256']=hashlib.sha256(log.read_bytes()).hexdigest()
        result['log_file']=log.name
        records[path]=result
        (out/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(json.dumps({'file':path,'status':result['status'],'rc':result.get('exit_code'),'completed_files':len(records)}),flush=True)
    counts={'PASS':0,'FAIL':0,'TIMEOUT':0,'ERROR':0}
    for r in records.values():
        label='PASS' if r['status']=='COMPLETED' and r.get('exit_code')==0 and r['cleanup_ok'] else (
            'FAIL' if r['status']=='FAIL' else 'TIMEOUT' if r['status']=='TIMEOUT' else 'ERROR')
        counts[label]+=1
    passed=len(records)==83 and counts['PASS']==83
    (out/'verdict.json').write_text(json.dumps({'pass':passed,'counts':counts,'expected_files':83,
        'recorded_files':len(records),'scope':'UNIT_SCRIPTS_NOT_PHYSICAL_APPROVAL'},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'counts':counts,'recorded_files':len(records)}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
