"""원격 원시 bytes·반례·대조군을 엔진 없이 재검사."""
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
    assert summary['source']['github_sha']==summary['source']['git_head']=='481fe8a07978ccbff95487ce9f856ca57d75561f'
    assert summary['source']['run_id']=='37462960267'
    assert summary['status']=='PASS' and summary['exit_code']==0 and not summary['omitted_outputs']
    assert summary['runner']['runner_environment']=='github-hosted'
    for record in summary['outputs']+[summary['log']]:
        path=root/('outputs/'+record['path'] if 'path' in record else record['file'])
        data=path.read_bytes()
        assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256']
    out=root/'outputs/e6ni_out'
    tests=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True
    assert set(tests['steps'])=={'depth','invalid','source','canvas_source','hover_legacy','canonical_gate','existing_gui'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in tests['steps'].values())
    depth=json.loads((out/'depth.json').read_text(encoding='utf-8'))
    assert depth['pass'] is True and depth['before']['all_surface_buckets_n'] is True
    assert depth['before']['actual_lower_net']==-1e17
    assert depth['ACTIVE']['counts']['n']>0 and depth['ACTIVE']['counts']['p']>0
    for label in ('CHEMICAL','UNKNOWN'):
        assert depth[label]['counts']['unknown']>0 and depth[label]['counts']['n']>0
        assert depth[label]['counts']['p']==0
    assert depth['ZERO']['counts']['zero']>0
    for label in ('ACTIVE','CHEMICAL','UNKNOWN','ZERO'):
        assert sum(depth[label]['counts'].values())==depth[label]['items']
    assert depth['vertex_inverse_error_um']<=1e-7
    assert depth['hover_depth'] is depth['history_no_current_doping'] is depth['mesh_unchanged'] is True
    assert depth['resource_cap']['triangles']>2000 and depth['resource_cap']['no_partial_fill'] is True
    invalid=json.loads((out/'invalid.json').read_text(encoding='utf-8'))
    assert invalid['pass'] is True and set(invalid['cases'])=={'nan','inf','negative'}
    for r in invalid['cases'].values():
        assert r['attempted_solves']==r['doping_writes']==0
        assert r['resolution']=='UNSUPPORTED_BY_MODEL' and r['parameter']=='dopant_concentration_validity'
    existing=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert existing['pass'] is True and all(c['pass'] is True for c in existing['checks'])
    print(json.dumps({'pass':True,'outputs_checked':len(summary['outputs'])+1,
                      'vertex_inverse_error_um':depth['vertex_inverse_error_um'],'engine_imports':0},indent=2))

if __name__=='__main__': main(Path(sys.argv[1]))
