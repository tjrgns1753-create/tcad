"""기존 native 배열의 엔진 없는 사후 전열 조사. 원본 판정 변경 금지."""
import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'2026-10-02-e6na-import-reduction'))
from diagnostics import validate, geometry_weights, exact_row, classify

EXPECTED = '69ffbc42aea5c11fea0347c922d872bb0387c0c87934c2ed14af93eaeffa222b'


def main(path, output):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError('INPUT_HASH_MISMATCH')
    with np.load(path, allow_pickle=False) as z:
        a = {k:z[k] for k in z.files}
    xy, triangles, edges = validate(a)
    gw, gv = geometry_weights(xy, triangles, edges)
    w, nv = a['EdgeCouple']/a['EdgeLength'], a['NodeVolume']
    if np.max(np.abs(w-gw)/np.maximum(1,np.abs(gw))) > 1e-10 or np.max(np.abs(nv-gv)/gv) > 1e-10:
        raise ValueError('LOCAL_WEIGHT_MISMATCH')
    incident = [[] for _ in xy]
    links = [[] for _ in xy]
    for ti, tri in enumerate(triangles):
        for node in tri:
            incident[int(node)].append(ti)
    for ei, (i,j) in enumerate(edges):
        links[int(i)].append((ei,int(j)))
        links[int(j)].append((ei,int(i)))
    scale = np.array([2*math.fsum(abs(float(w[ei])) for ei,j in inc)/nv[i]
                      for i,inc in enumerate(links)])
    uncertainty = np.zeros((4,len(xy)))
    for power in range(4):
        f = (xy[:,0]/0.004)**power
        for i,inc in enumerate(links):
            geom = math.fsum(float(gw[ei]*(f[i]-f[j])) for ei,j in inc)
            uncertainty[power,i] = (math.fsum(abs(float((w[ei]-gw[ei])*(f[i]-f[j]))) for ei,j in inc)/nv[i]
                                    +abs(geom*(1/nv[i]-1/gv[i])))
    groups = defaultdict(list)
    for i in range(len(xy)):
        if a['node_class'][i] != 2:
            groups[(float(xy[i,0]),int(a['node_class'][i]))].append(i)
    counts = dict(groups=0,pairs=0,exact_nonzero_pairs=0,passing_polynomial_pairs=0)
    first = None
    first_exact = None
    for (x,kind),nodes in sorted(groups.items()):
        nodes.sort(key=lambda i:xy[i,1])
        if len(nodes)<2:
            continue
        counts['groups'] += 1
        base = nodes[0]
        r0 = exact_row(base,xy,triangles,incident)
        for j in nodes[1:]:
            counts['pairs'] += 1
            r1 = exact_row(j,xy,triangles,incident)
            diffrow = {k:r0.get(k,Fraction(0))-r1.get(k,Fraction(0)) for k in set(r0)|set(r1)}
            structural = any(v != 0 for v in diffrow.values())
            if structural:
                counts['exact_nonzero_pairs'] += 1
                if first_exact is None:
                    first_exact = dict(nodes=[base,j],x_cm=x,node_class=kind,
                                       exact_row_difference={str(k):str(v) for k,v in diffrow.items() if v})
            for power in range(4):
                diff = abs(float(a['stable_actions'][power,base]-a['stable_actions'][power,j]))
                sc = float(max(scale[base],scale[j]))
                unc = float(uncertainty[power,base]+uncertainty[power,j])
                if classify(diff,sc,unc,structural) == 'NONINVARIANCE_WITNESS':
                    counts['passing_polynomial_pairs'] += 1
                    if first is None:
                        first = dict(nodes=[base,j],x_cm=x,node_class=kind,power=power,
                                     difference=diff,scale=sc,uncertainty=unc,
                                     exact_row_difference={str(k):str(v) for k,v in diffrow.items() if v})
    report = dict(input_sha=EXPECTED,original_verdict='INCONCLUSIVE',scope='POSTHOC_ONLY',
                  counts=counts,first_exact_difference=first_exact,first_posthoc_witness=first,
                  engine_imports=0,solve_calls=0,pn_approved=False)
    Path(output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    args=parser.parse_args()
    main(args.input,args.output)
