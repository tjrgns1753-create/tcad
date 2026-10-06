"""실제 원시 artifact 복사본의 false-green 반례. 새 엔진/solve 없음."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import sys
import verify_artifact as V


def main():
    original=Path(__file__).parent/'raw/remote-run-37'
    assert V.verify(original)['verdict']=='MMS_2D_NUMERICAL_PASS'
    cases=('omitted','wrong_source','wrong_plan','wrong_counter','nan_metric',
           'snapshot_failed','missing_geometry','wrong_hash','missing_array','wrong_expected_source')
    for name in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'artifact';shutil.copytree(original,root)
            summary=json.loads((root/'summary.json').read_text())
            result_path=root/'outputs/e6nb_out/result.json'
            result=json.loads(result_path.read_text())
            expected=V.SOURCE_SHA
            if name=='omitted':summary['omitted_outputs']=[{'path':'M0.npz'}]
            elif name=='wrong_source':summary['source']['github_sha']='0'*40
            elif name=='wrong_plan':result['plan_sha']='0'*64
            elif name=='wrong_counter':result['meshes'][0]['solve_attempts']=True
            elif name=='nan_metric':result['meshes'][0]['linf']=float('nan')
            elif name=='snapshot_failed':result['meshes'][1]['snapshot_failures']=1
            elif name=='missing_geometry':del result['meshes'][0]['geometry']
            elif name=='wrong_hash':summary['outputs'][0]['sha256']='0'*64
            elif name=='missing_array':(root/'outputs/e6nb_out/M0.npz').unlink()
            elif name=='wrong_expected_source':expected='1'*40
            if name in ('wrong_plan','wrong_counter','nan_metric','snapshot_failed','missing_geometry'):
                result_path.write_text(json.dumps(result),encoding='utf-8')
                # 외부 hash를 일부러 갱신해도 내부 의미 충돌은 반드시 차단해야 한다.
                for item in summary['outputs']:
                    if item['path']=='e6nb_out/result.json':
                        item.update(sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),bytes=result_path.stat().st_size)
            (root/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
            try:V.verify(root,expected)
            except (ValueError,KeyError,OSError,AssertionError):print('BLOCKED',name)
            else:raise AssertionError('FALSE_GREEN '+name)
    assert not any(k in sys.modules for k in ('devsim','viennaps','viennals'))
    print('ARTIFACT_CONTRACT_PASS; REAL_SOLVES=0')


if __name__=='__main__':
    main()
