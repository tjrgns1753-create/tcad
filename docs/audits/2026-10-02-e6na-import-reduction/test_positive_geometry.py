"""사전 고정한 합성 기하 양성 경로. 공식 엔진/실제 PN 계산은 없다."""
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import diagnostics as D
from test_review_followup import fixture, check_geometry

CRITERIA_SHA = '963d9a5c9b1933471a4edff04cdc14f807f3a56333a8a492f27e9728b61b8d70'
H = F(1, 4096)
L = F(1, 250)


def positive_fixture():
    """고정한21 node/26 triangle. 독립 Fraction 산술로 입력 가중치를 만든다."""
    a=2*H
    uv=[(u,k*H) for u in (-2*a,-a,F(0)) for k in range(5)]
    uv += [(u,2*k*H) for u in (a,2*a) for k in range(3)]
    xy=[(v-H,u) for u,v in uv]
    tri=[]
    for c in range(2):
        for k in range(4):
            tri.extend(((5*c+k,5*(c+1)+k,5*c+k+1),
                        (5*(c+1)+k,5*(c+1)+k+1,5*c+k+1)))
    for k in range(2):
        aa,m,b,c,d=10+2*k,11+2*k,12+2*k,15+k,16+k
        tri.extend(((aa,c,m),(m,c,d),(m,d,b)))
        tri.extend(((15+k,18+k,16+k),(18+k,19+k,16+k)))
    tri=[(i,k,j) for i,j,k in tri]
    weights={}
    volumes=[F(0) for _ in xy]
    total_area=F(0)
    for t in tri:
        p,q,r=(xy[i] for i in t)
        cross=(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        assert cross>0
        total_area+=cross/2
        for corner in range(3):
            o,i,j=t[corner],t[(corner+1)%3],t[(corner+2)%3]
            u=[xy[i][k]-xy[o][k] for k in (0,1)]
            v=[xy[j][k]-xy[o][k] for k in (0,1)]
            dot=sum(u[k]*v[k] for k in (0,1))
            assert dot>=0, 'obtuse exact geometry'
            w=dot/(2*cross)
            key=tuple(sorted((i,j)))
            weights[key]=weights.get(key,F(0))+w
            length2=sum((xy[i][k]-xy[j][k])**2 for k in (0,1))
            volumes[i]+=w*length2/4
            volumes[j]+=w*length2/4
    assert len(xy)==21 and len(tri)==26 and total_area==32*H**2
    assert volumes[6]==2*H**2 and volumes[11]==17*H**2/8
    assert sum(volumes)==total_area
    # 사전 문서에서 손으로 유도한 비영 weights와 전체 incident 집합을 대조한다.
    for node, expected in ((6,{5:F(2),7:F(2),1:F(1,2),11:F(1,2)}),
                           (11,{10:F(2),12:F(2),6:F(1,2),15:F(1,4),16:F(1,4)})):
        got={j if i==node else i:w for (i,j),w in weights.items() if node in (i,j) and w!=0}
        assert got==expected,(node,got)
    edges=np.array(sorted(weights),dtype=np.int64)
    points=np.array(xy,dtype=float)
    delta=points[edges[:,0]]-points[edges[:,1]]
    length=np.hypot(delta[:,0],delta[:,1])
    ws=np.array([float(weights[tuple(e)]) for e in edges])
    data=dict(xy=points,triangles=np.array(tri,dtype=np.int64),edges=edges,
              NodeVolume=np.array(volumes,dtype=float),EdgeLength=length,EdgeCouple=ws*length)
    # 진단 구현으로 기대값을 생성하지 않는다. 독립적으로 만든 전체 입력과 구현만 대조한다.
    gw,gv=D.geometry_weights(points,data['triangles'],edges)
    np.testing.assert_allclose(gw,ws,rtol=1e-14,atol=0)
    np.testing.assert_allclose(gv,data['NodeVolume'],rtol=1e-14,atol=0)
    return data


def projected_rows(a):
    incident=[[] for _ in a['xy']]
    for ti, t in enumerate(a['triangles']):
        for node in t:
            incident[int(node)].append(ti)
    return [D.exact_row(i,a['xy'],a['triangles'],incident) for i in range(len(incident))]


def blocked(callback,label):
    try:
        callback()
    except ValueError as exc:
        print('BLOCKED',label,str(exc))
        return {'case':label,'status':'BLOCKED','reason':str(exc)}
    raise AssertionError('false acceptance: '+label)


def main(output=None):
    path=Path(__file__).with_name('POSITIVE_GEOMETRY_CRITERIA.md')
    assert hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()==CRITERIA_SHA
    a=positive_fixture()
    check_geometry(a)
    rows=projected_rows(a)
    expected6={-H:-1/H**2,F(0):2/H**2,H:-1/H**2}
    expected11={-H:-18/(17*H**2),F(0):36/(17*H**2),H:-18/(17*H**2)}
    assert rows[6]==expected6 and rows[11]==expected11
    rec,arrays=D.analyze(a)
    assert rec['verdict']=='NONINVARIANCE_WITNESS'
    witness=next(w for w in rec['witnesses'] if w['nodes']==[6,11] and w['power']==2)
    assert witness['classes']==[0,0] and witness['verdict']=='NONINVARIANCE_WITNESS'
    np.testing.assert_allclose(arrays['stable_actions'][2,[6,11]],[-float(2/L**2),-float(36/(17*L**2))],rtol=2e-12,atol=0)
    np.testing.assert_allclose(witness['difference'],float(2/(17*L**2)),rtol=2e-12,atol=0)
    assert witness['scale']==float(5/H**2)
    assert witness['geometry_discrepancy_bound']<=1e-6
    threshold_relative=1e-8*witness['scale']
    threshold_error=100*(witness['geometry_discrepancy_bound']+100*np.finfo(float).eps*witness['scale'])
    assert witness['difference']>max(threshold_relative,threshold_error)
    print('POSITIVE_WITNESS',json.dumps(witness),flush=True)
    normal=fixture()
    normal_rows=projected_rows(normal)
    assert normal_rows[6]==normal_rows[7]==normal_rows[8]
    assert D.analyze(normal)[0]['verdict']=='INCONCLUSIVE'
    assert D.analyze(fixture(True))[0]['verdict']=='INCONCLUSIVE'
    assert D.analyze(fixture(True,1e-6))[0]['verdict']=='INCONCLUSIVE'
    assert D.analyze(dict(a,edges=a['edges'][:,::-1]))[0]['verdict']=='NONINVARIANCE_WITNESS'
    controls=[]
    for key in ('NodeVolume','EdgeLength','EdgeCouple'):
        b=dict(a);b.pop(key)
        controls.append(blocked(lambda:D.analyze(b),'missing_'+key))
    b=dict(a,EdgeCouple=a['EdgeCouple'].copy());b['EdgeCouple'][0]=np.nan
    controls.append(blocked(lambda:D.analyze(b),'nonfinite'))
    b=dict(a,edges=a['edges'].copy());b['edges'][0,0]=len(a['xy'])
    controls.append(blocked(lambda:D.analyze(b),'endpoint_range'))
    controls.append(blocked(lambda:D.analyze(dict(a,NodeVolume=a['NodeVolume']*2)),'volume_corruption'))
    controls.append(blocked(lambda:D.analyze(dict(a,EdgeLength=a['EdgeLength']*2,EdgeCouple=a['EdgeCouple']*2)),'joint_scale_corruption'))
    b=dict(a,xy=a['xy'].copy());b['xy'][:,0]+=0.01
    delta=b['xy'][b['edges'][:,0]]-b['xy'][b['edges'][:,1]]
    weights=a['EdgeCouple']/a['EdgeLength']
    b['EdgeLength']=np.hypot(delta[:,0],delta[:,1]);b['EdgeCouple']=weights*b['EdgeLength']
    assert D.analyze(b)[0]['verdict']=='NOT_MEASURED'
    assert 'devsim' not in sys.modules and 'viennaps' not in sys.modules
    report={'criteria_sha':CRITERIA_SHA,'verdict':rec['verdict'],'nodes':21,'triangles':26,
            'expected_row_6':{str(k):str(v) for k,v in expected6.items()},
            'expected_row_11':{str(k):str(v) for k,v in expected11.items()},
            'witness':witness,'threshold_relative':threshold_relative,'threshold_error':threshold_error,
            'actions':arrays['stable_actions'][2,[6,11]].tolist(),'controls':controls,
            'negative_verdict':'INCONCLUSIVE','legacy_transition_verdict':'INCONCLUSIVE',
            'reversed_endpoints_verdict':'NONINVARIANCE_WITNESS','no_candidate_verdict':'NOT_MEASURED',
            'engine_imports':0,'actual_solve_calls':0,'pn_validated':False}
    if output is not None:
        Path(output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('POSITIVE_GEOMETRY_PASS; ENGINE_IMPORTS=0; ACTUAL_SOLVES=0')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',help='선택적 결과 artifact 경로; 검증 기준에는 영향 없음')
    main(parser.parse_args().output)
