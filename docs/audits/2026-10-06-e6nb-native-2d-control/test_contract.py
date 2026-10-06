"""엔진 없는 사전 식/판정/실행 경계 반례."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock
import numpy as np
import run_control as R


def blocked(fn,name):
    try:
        fn()
    except (ValueError,KeyError):
        print('BLOCKED',name)
    else:
        raise AssertionError('FALSE_PASS '+name)


def main():
    cb=Mock(return_value='OK')
    assert R.preflight(cb)=='OK';cb.assert_called_once()
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'bad';p.write_text('wrong')
        for target in (p,Path(tmp)/'missing'):
            cb=Mock();blocked(lambda:R.preflight(cb,target),'plan')
            cb.assert_not_called()
    records=[dict(label=R.LABELS[i],triangles=26*4**i,status='PASS',solve_attempts=1,
                  solve_successes=1,solve_failures=0,snapshot_failures=0,cleanup_ok=True,
                  linf=.1/4**i,l2=.08/4**i,h_max=.001/2**i,residual_relative=1e-13,
                  contact_error=0.,y_spread=1.8,
                  geometry=dict(weight_relative=1e-16,volume_relative=1e-16,area={'pass':True}))
             for i in range(4)]
    assert R.judge(records)['verdict']=='MMS_2D_NUMERICAL_PASS'
    print('MATCHED_CONTROL_PASS')
    blocked(lambda:R.judge(records[:-1]),'missing_mesh')
    for key,value in (('linf',float('nan')),('solve_attempts',True),('solve_successes',0),
                      ('solve_failures',1),('snapshot_failures',1),('cleanup_ok',False),
                      ('residual_relative',1e-5),('contact_error',1e-3),('y_spread',0.),
                      ('h_max',.002),('status','FAIL')):
        bad=deepcopy(records);bad[3][key]=value
        blocked(lambda:R.judge(bad),key)
    bad=deepcopy(records);bad[-1]['linf']=.011
    blocked(lambda:R.judge(bad),'fine_error')
    bad=deepcopy(records);bad[2]['l2']=bad[1]['l2']
    blocked(lambda:R.judge(bad),'rate')
    bad=deepcopy(records);bad[1]['geometry']['area']['pass']=False
    blocked(lambda:R.judge(bad),'geometry')
    bad=deepcopy(records);del bad[0]['geometry']
    blocked(lambda:R.judge(bad),'missing_geometry')
    # Independent analytical derivative: central difference converges to -K*phi.
    Lx,Ly=4*float(R.H),8*float(R.H)
    x,y=.37*Lx,.29*Ly
    f=lambda x,y:math.sin(math.pi*x/Lx)*math.cos(math.pi*y/Ly)
    K=math.pi**2*(1/Lx**2+1/Ly**2)
    errs=[]
    for delta in (Lx/100,Lx/200,Lx/400):
        lap=(f(x+delta,y)+f(x-delta,y)+f(x,y+delta)+f(x,y-delta)-4*f(x,y))/delta**2
        errs.append(abs(lap+K*f(x,y)))
    assert errs[0]/errs[1]>3.9 and errs[1]/errs[2]>3.9
    assert f(0,y)==0 and abs(f(Lx,y))<1e-15
    for yy in (0.,Ly):
        delta=Ly/1000
        assert abs((f(x,yy+delta)-f(x,yy-delta))/(2*delta))<1e-9
    # Pure existing ALL-red refinement; no new mesher and no engine.
    from tcad.device.devsim.mesh_refine import _refine_once
    a=R.positive_fixture();points=np.column_stack((a['xy']*1e4,np.zeros(len(a['xy']))));tri=a['triangles']
    tags=np.zeros(len(tri),dtype=np.int32)
    previous=None
    for i in range(4):
        assert len(tri)==26*4**i
        p=points[:,:2]*1e-4
        e=np.array(sorted({tuple(sorted((int(t[k]),int(t[(k+1)%3])))) for t in tri for k in range(3)}))
        w,v=R.geometry_weights(p,tri,e)
        assert np.all(w>=0) and np.all(v>0)
        R.check_geometry(dict(xy=p,triangles=tri))
        h=float(np.max(np.linalg.norm(p[e[:,0]]-p[e[:,1]],axis=1)))
        if previous is not None:
            assert math.isclose(2*h,previous,rel_tol=1e-14)
        previous=h
        print('GEOMETRY_PASS',i,len(points),len(tri))
        if i<3:
            points,tri,tags=_refine_once(points,tri,tags,np.ones(len(tri),dtype=bool))
    assert not any(k in sys.modules for k in ('devsim','viennaps','viennals'))
    print('CONTRACT_PASS; ENGINE_IMPORTS=0; REAL_SOLVES=0')


if __name__=='__main__':
    main()
