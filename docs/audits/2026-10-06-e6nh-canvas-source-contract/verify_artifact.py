"""보존 artifact 바이트 및 실제 canvas 계약 결과를 엔진 없이 재검사."""
import hashlib
import json
from pathlib import Path
import sys

def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)

def main(root):
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha']==summary['source']['git_head']=='7bfc27e35952c729f7293398034dc20b54311934'
    assert summary['source']['run_id']=='37459938706'
    assert summary['status']=='PASS' and summary['exit_code']==0 and not summary['omitted_outputs']
    assert summary['runner']['runner_environment']=='github-hosted'
    for record in summary['outputs']+[summary['log']]:
        path=root/('outputs/'+record['path'] if 'path' in record else record['file'])
        data=path.read_bytes()
        assert len(data)==record['bytes']
        assert hashlib.sha256(data).hexdigest()==record['sha256']
    out=root/'outputs/e6nh_out'
    tests=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps'])=={'before','canvas','source_mock','canonical_gate','existing_gui','pn_reference'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in tests['steps'].values())
    before=json.loads((root/'outputs/e6nh_before_out/canvas.json').read_text(encoding='utf-8'))
    after=json.loads((out/'canvas.json').read_text(encoding='utf-8'))
    for case in ('missing','corrupt'):
        assert before[case]['solid_count']>0 and 'Si substrate' in before[case]['texts']
        assert after[case]['solid_count']==0 and '형상 표시 차단' in '\n'.join(after[case]['texts'])
    assert before['malformed']['system_exit'] is True and after['malformed']['system_exit'] is False
    assert after['real_geometry']['canvas_mesh_bbox_match'] is True
    assert after['real_geometry']['unsupported_geometry_preserved'] is True
    assert '미지원' in '\n'.join(after['real_geometry']['texts'])
    bounds=json.loads((out/'bbox.json').read_text(encoding='utf-8'))
    error=max(abs(a-b) for suffix in ('min','max') for a,b in zip(bounds['drawn_'+suffix],bounds['silicon_'+suffix]))
    assert error<=1e-7
    print(json.dumps({'pass':True,'outputs_checked':len(summary['outputs'])+1,
                      'bbox_error_um':error,'engine_imports':0},indent=2))

if __name__=='__main__':
    main(Path(sys.argv[1]))
