"""엔진 없는 정상 대조군과 실패 반례. 과거 증거를 수정하지 않는다."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

import pilot as P
from judge import evaluate_device, judge


def main():
    def forbidden(event,args):
        if event=='import' and args[0].split('.')[0] in ('devsim','viennaps'):
            raise AssertionError('LOCAL_ENGINE_IMPORT_FORBIDDEN')
    sys.addaudithook(forbidden)
    P.require_plan()
    with patch.object(P,'PLAN_SHA','0'*64):
        try:
            P.require_plan()
            raise AssertionError('BAD_PLAN_ACCEPTED')
        except ValueError:
            pass
    old = P.ROOT/'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/data/remote_run_36904995835/remote-run-32/outputs/e6m_out'
    raw = json.loads((old/'pn_2d_consistency.json').read_text())
    ref = json.loads((P.T.E6K/'pn_1d_diagnostic.json').read_text())
    with np.load(old/'arrays.npz',allow_pickle=False) as src, np.load(P.T.E6K/'states.npz',allow_pickle=False) as states:
        lv,d = 'L0','fwd'
        arrays = {'points_um':src[lv+'__points_um'],'triangles':src[lv+'__triangles']}
        for nm in P.M.GEOM_ARRAYS:
            rename = {'edge_x0':'x@n0','edge_x1':'x@n1','edge_y0':'y@n0','edge_y1':'y@n1','element_nodes':'elements'}.get(nm,nm)
            arrays[d+'_'+rename] = src[P.M.akey(lv,d,nm)]
        for v in P.M.SNAP_BIASES[d]:
            for nm in P.M.SNAP_ARRAYS:
                arrays[f'{d}_{v}_{nm}'] = src[P.M.akey(lv,d,nm,v)]
        dr = copy.deepcopy(raw['levels'][lv]['devices'][d])
        gi = raw['levels'][lv]['geometry_import']
        # 테스트용 합성 wrapper: 과거 누락 기록을 실제 증거로 승격하지 않는다.
        dr.update(error=None,cleanup_ok=True,node_count=len(arrays[d+'_x']),area_gate=gi['area_gate'],gate={'reason_code':P.T.J.GATE_REASON,'resolution':'UNSUPPORTED_BY_MODEL'},gate_counts={'writes':0,'attempts':0},solve_attempts=8,solves=8,solve_failures=0,snapshot_failures=0)
        dr['canonical_audit'] = {'canonical_checked':dr['node_count'],'canonical_unresolved':0,'canonical_mismatch':0}
        dr['contacts'] = {cn:np.flatnonzero(arrays[d+'_x']==xx).tolist() for cn,xx in [(P.T.C_MIN,-.002),(P.T.C_MAX,.002)]}
        cc,mm = evaluate_device(dr,arrays,lv,d,ref,states,P.T)
        assert cc and all(c['pass'] for c in cc),[c for c in cc if not c['pass']]
        mutations = [lambda q:q['canonical_audit'].update(canonical_unresolved=1),lambda q:q['canonical_audit'].update(canonical_checked=True),lambda q:q.update(cleanup_ok=False),lambda q:q.update(solves=7),lambda q:q['gate_counts'].update(writes=1),lambda q:q['metadata'].update(current_unit='A'),lambda q:q['currents'][0].update(I_min=float('nan')),lambda q:q['currents'].pop(),lambda q:q['contacts'][P.T.C_MIN].pop()]
        for mutate in mutations:
            changed = copy.deepcopy(dr)
            mutate(changed)
            try:
                checks,_ = evaluate_device(changed,arrays,lv,d,ref,states,P.T)
                assert not all(c['pass'] for c in checks)
            except (ValueError,KeyError):
                pass
    assert judge(Path('missing_e6nd_fixture'))['status']=='PILOT_NOT_APPROVED'
    print('PASS: normal wrapper + 9 negative controls + PLAN trap + missing evidence; engine imports 0')


if __name__=='__main__':
    main()
