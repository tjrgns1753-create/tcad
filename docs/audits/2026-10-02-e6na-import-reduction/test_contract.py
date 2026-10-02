"""엔진 없는 E6N-A 실행 경계와 합성 반례."""
import sys
from pathlib import Path
from unittest.mock import Mock,patch

import numpy as np
import diagnostics as D
import run_e6na as R


def reject(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('false PASS')


def main():
    plan=(R.HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')
    for value in (b'wrong',None):
        callback=Mock()
        kwargs={'return_value':value} if value is not None else {'side_effect':FileNotFoundError()}
        with patch.object(Path,'read_bytes',**kwargs):
            reject(lambda:R.preflight(callback))
        callback.assert_not_called()
    for value in (plan,plan.replace(b'\n',b'\r\n')):
        callback=Mock(return_value='OK')
        with patch.object(Path,'read_bytes',return_value=value):
            assert R.preflight(callback)=='OK'
        callback.assert_called_once()
    xy=np.array([[-.002,-1e-5],[.002,-1e-5],[-.002,0],[.002,0]])
    tri=np.array([[0,1,2],[1,3,2]],dtype=np.int64)
    edges=np.array(sorted({tuple(sorted((int(t[i]),int(t[(i+1)%3])))) for t in tri for i in range(3)}),dtype=np.int64)
    w,v=D.geometry_weights(xy,tri,edges)
    length=np.linalg.norm(xy[edges[:,0]]-xy[edges[:,1]],axis=1)
    a=dict(xy=xy,triangles=tri,edges=edges,NodeVolume=v,EdgeLength=length,EdgeCouple=w*length)
    D.validate(a)
    for key in ('NodeVolume','EdgeCouple'):
        b=dict(a);b.pop(key)
        reject(lambda:D.validate(b))
    b=dict(a);b['edges']=edges.copy();b['edges'][0,0]=4
    reject(lambda:D.validate(b))
    reject(lambda:D.validate(a,solve_attempts=1))
    reject(lambda:D.validate(a,omitted=True))
    assert D.analyze(a)[0]['verdict']=='NOT_MEASURED'
    assert D.classify(0,1,0,True)=='INCONCLUSIVE' # stencil-only
    assert D.classify(1e-14,1,1e-14,True)=='INCONCLUSIVE' # roundoff-only
    assert D.classify(1,1,0,False)=='INCONCLUSIVE' # no geometry witness
    assert D.classify(1,1,0,True)=='NONINVARIANCE_WITNESS'
    assert not any(k in sys.modules for k in ('devsim','viennaps'))
    print('E6N-A synthetic/preflight PASS; actual engine imports=0, solve=0')


if __name__=='__main__':
    main()
