"""사전 기준의 합성 전체 경로. DEVSIM/ViennaPS는 import하지 않는다."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import diagnostics as D
import run_e6na as R


def blocked(callback, label):
    try:
        callback()
    except (ValueError, RuntimeError, OSError):
        print('BLOCKED', label)
        return
    raise AssertionError('false acceptance: ' + label)


def fixture(transition=False, scale=1.0):
    xy = [(-1e-5, y) for y in np.linspace(-1e-5, 0, 5)]
    xy += [(0, y) for y in np.linspace(-1e-5, 0, 5)]
    right = np.linspace(-1e-5, 0, 3 if transition else 5)
    xy += [(1e-5, y) for y in right]
    tri = []
    for k in range(4):
        tri.extend(((k, 5+k, k+1), (5+k, 6+k, k+1)))
    if transition:
        for k in range(2):
            a, m, b, c, d = 5+2*k, 6+2*k, 7+2*k, 10+k, 11+k
            tri.extend(((a,c,m), (m,c,d), (m,d,b)))
    else:
        for k in range(4):
            tri.extend(((5+k,10+k,6+k), (10+k,11+k,6+k)))
    xy = np.array(xy)*scale
    tri = np.array(tri, dtype=np.int64)
    edges = np.array(sorted({tuple(sorted((int(t[k]),int(t[(k+1)%3])))) for t in tri for k in range(3)}))
    w, v = D.geometry_weights(xy, tri, edges)
    delta = xy[edges[:,0]]-xy[edges[:,1]]
    length = np.hypot(delta[:,0],delta[:,1])
    return dict(xy=xy, triangles=tri, edges=edges, NodeVolume=v,
                EdgeLength=length, EdgeCouple=w*length)


def check_geometry(a):
    C = R.load('followup_conformity', R.ROOT/'docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py')
    p = np.column_stack((a['xy'],np.zeros(len(a['xy']))))
    result = C.check_conformity(p, a['triangles'])
    assert result['pass'], result


def main():
    normal, transition = fixture(), fixture(True)
    for name, a, expected in (('normal',normal,'INCONCLUSIVE'),
                               ('transition',transition,'INCONCLUSIVE'),
                               ('stencil_only',fixture(True,1e-6),'INCONCLUSIVE')):
        check_geometry(a)
        rec, arrays = D.analyze(a)
        assert rec['verdict']==expected, (name,rec['verdict'])
        assert arrays['actions'].shape==(4,len(a['xy']))
        if name in ('transition','stencil_only'):
            assert any(w['exact_projected_row_nonzero'] for w in rec['witnesses'])
            assert any(w['difference']>0 for w in rec['witnesses'])
        print('FULL_PATH', name, rec['verdict'])
    b=dict(normal, edges=normal['edges'][:,::-1])
    assert D.analyze(b)[0]['verdict']=='INCONCLUSIVE'
    print('FULL_PATH reversed_endpoints INCONCLUSIVE')
    b=dict(normal,EdgeCouple=np.nextafter(normal['EdgeCouple'],np.inf))
    assert D.analyze(b)[0]['verdict']=='INCONCLUSIVE'
    print('FULL_PATH roundoff_only INCONCLUSIVE')
    blocked(lambda:D.analyze(dict(normal,EdgeLength=normal['EdgeLength']*2,
                                   EdgeCouple=normal['EdgeCouple']*2)), 'joint_scale_corruption')
    for key in ('NodeVolume','EdgeLength','EdgeCouple'):
        b=dict(normal);b.pop(key)
        blocked(lambda:D.analyze(b),'missing_'+key)
    for label,value in (('fractional',0.5),('nan',np.nan),('negative',-1),('range',len(normal['xy']))):
        e=normal['edges'].astype(float);e[0,0]=value
        blocked(lambda:D.checked_indices(e,len(normal['xy']),2),'endpoint_'+label)
    assert np.array_equal(D.checked_indices(normal['edges'].astype(float),len(normal['xy']),2),normal['edges'])
    # 기존 비교 node 없는 control도 그대로 유지.
    no=dict(normal,xy=normal['xy'].copy());no['xy'][:,0]+=1
    # 단순 평행 이동은 길이 재계산 roundoff를 만들 수 있어 전체 기하를 다시 계산한다.
    w,v=D.geometry_weights(no['xy'],no['triangles'],no['edges'])
    delta=no['xy'][no['edges'][:,0]]-no['xy'][no['edges'][:,1]]
    no.update(NodeVolume=v,EdgeLength=np.hypot(delta[:,0],delta[:,1]))
    no['EdgeCouple']=w*no['EdgeLength']
    assert D.analyze(no)[0]['verdict']=='NOT_MEASURED'
    print('FULL_PATH no_candidate NOT_MEASURED')
    good=(R.HERE/'REVIEWED_FLUX_REFERENCE.txt').read_text(encoding='utf-8')
    for source in ('wrong',None):
        callback=Mock()
        kwargs={'return_value':source} if source is not None else {'side_effect':OSError('unavailable')}
        with patch.object(R.inspect,'getsource',**kwargs):
            blocked(lambda:R.require_flux_source(object(),callback),'flux_source')
        callback.assert_not_called()
    callback=Mock(return_value='OK')
    with patch.object(R.inspect,'getsource',return_value=good):
        assert R.require_flux_source(object(),callback)=='OK'
    callback.assert_called_once()
    # 실제 execute 진입에도 PLAN이 앞서며 backend callback은 0회.
    for value in (b'wrong',None):
        callback=Mock()
        kwargs={'return_value':value} if value is not None else {'side_effect':FileNotFoundError()}
        with patch.object(Path,'read_bytes',**kwargs),patch.object(R,'_execute',callback):
            blocked(R.execute,'actual_entry_plan')
        callback.assert_not_called()
    original=Mock()
    dv=SimpleNamespace(solve=original)
    for kind in ('np_load','cleanup'):
        report={'solve_attempts':0}
        def failing():
            if kind=='np_load':
                with patch.object(np,'load',side_effect=OSError('load failed')):
                    np.load('not-read')
            else:
                raise RuntimeError('cleanup callback failed')
        blocked(lambda:R.without_solve(dv,report,failing),'restore_'+kind)
        assert dv.solve is original and report['solve_attempts']==0
    report={'solve_attempts':0}
    blocked(lambda:R.without_solve(dv,report,lambda:dv.solve()),'forbidden_solve')
    assert report['solve_attempts']==1 and dv.solve is original
    devices=['d']; meshes=['m']
    fake=SimpleNamespace(get_device_list=lambda:list(devices),get_mesh_list=lambda:list(meshes),
                         delete_device=Mock(side_effect=RuntimeError('delete failed')),
                         delete_mesh=lambda **kw:meshes.clear())
    rec={'status':'IMPORT_PASS'}
    assert not R.cleanup(fake,'d','m',rec)
    assert rec['status']=='FAIL' and not meshes and rec['cleanup_errors']
    print('CLEANUP failure_is_FAIL and mesh_cleanup_attempted')
    fake.delete_device=lambda **kw:devices.clear()
    rec={}
    assert R.cleanup(fake,'d','m',rec)
    print('CLEANUP normal_PASS')
    assert not any(k in sys.modules for k in ('devsim','viennaps'))
    print('FOLLOWUP PASS; actual engine imports=0; actual solve=0')


if __name__=='__main__':
    main()
