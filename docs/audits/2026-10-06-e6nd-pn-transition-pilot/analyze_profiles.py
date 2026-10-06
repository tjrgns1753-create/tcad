"""사후 원인 분리: 공통 x와 추가 x를 구분. 사전 판정은 변경하지 않는다."""
import json
from pathlib import Path
import sys

import numpy as np

import pilot as P


def analyze(out):
    result = {'label':'POST_HOC_DIAGNOSTIC_NOT_APPROVAL','profiles':[]}
    with np.load(P.T.E6K/'states.npz',allow_pickle=False) as ref:
        for k,lv in enumerate(('L0','L1')):
            with np.load(out/f'N{k}/arrays.npz',allow_pickle=False) as arr:
                for direction in P.M.DIRECTIONS:
                    x,y = arr[direction+'_x'],arr[direction+'_y']
                    for bias in P.M.SNAP_BIASES[direction]:
                        r = P.M.e6k_snapshot(ref,lv,direction,bias)
                        shared = np.isin(x,r['x'])
                        psi = arr[f'{direction}_{bias}_Potential']
                        rec = {'level':lv,'direction':direction,'V':bias,'common_nodes':int(shared.sum()),'added_nodes':int((~shared).sum())}
                        for nm in ('Potential','Electrons','Holes'):
                            v = arr[f'{direction}_{bias}_{nm}']
                            expected = np.interp(x,r['x'],r[nm]) if nm=='Potential' else np.exp(np.interp(x,r['x'],np.log(r[nm])))
                            diff = np.abs(v-expected) if nm=='Potential' else np.abs(v-expected)/expected
                            imax = int(np.argmax(diff))
                            rec[nm] = {'all_max':float(diff[imax]),'common_max':float(np.max(diff[shared])),'added_max':float(np.max(diff[~shared])) if np.any(~shared) else None,'max_location_um':[float(x[imax]*1e4),float(y[imax]*1e4)],'value_at_max':float(v[imax]),'reference_at_max':float(expected[imax])}
                        # 더 세밀한 1D 기준과의 비교는 사후 진단이며 고정 판정을 덮어쓰지 않는다.
                        fine = P.M.e6k_snapshot(ref,'L2',direction,bias)
                        rec['fine_L2_potential_max_V'] = float(np.max(np.abs(psi-np.interp(x,fine['x'],fine['Potential']))))
                        result['profiles'].append(rec)
    return result


if __name__=='__main__':
    print(json.dumps(analyze(Path(sys.argv[1])),indent=2))
