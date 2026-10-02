"""엔진 없는 E6N-A 기하/연산자 진단. 물리 solver가 아니다."""
import math
from fractions import Fraction as F

import numpy as np


def validate(a, solve_attempts=0, omitted=False):
    if type(solve_attempts) is not int or solve_attempts != 0 or omitted:
        raise ValueError('EVIDENCE_BLOCKED: solve attempt or omitted evidence')
    keys = ('xy', 'triangles', 'edges', 'NodeVolume', 'EdgeCouple', 'EdgeLength')
    if any(k not in a for k in keys):
        raise ValueError('EVIDENCE_BLOCKED: required array missing')
    xy, t, e = (np.asarray(a[k]) for k in keys[:3])
    n = len(xy)
    if xy.shape != (n, 2) or n == 0 or not np.all(np.isfinite(xy)) or len(np.unique(xy, axis=0)) != n:
        raise ValueError('EVIDENCE_BLOCKED: invalid nodes')
    for q, width in ((t, 3), (e, 2)):
        if q.ndim != 2 or q.shape[1] != width or q.dtype.kind not in 'iu' or not len(q) or np.any(q < 0) or np.any(q >= n):
            raise ValueError('EVIDENCE_BLOCKED: invalid endpoint/topology')
    if np.any(e[:, 0] == e[:, 1]) or len(np.unique(np.sort(e, axis=1), axis=0)) != len(e):
        raise ValueError('EVIDENCE_BLOCKED: duplicate/degenerate edge')
    for key, count, positive in (('NodeVolume', n, True), ('EdgeLength', len(e), True), ('EdgeCouple', len(e), False)):
        q = np.asarray(a[key])
        if q.shape != (count,) or not np.all(np.isfinite(q)) or np.any(q <= 0 if positive else q < 0):
            raise ValueError('EVIDENCE_BLOCKED: invalid ' + key)
    return xy, t, e


def geometry_weights(xy, triangles, edges):
    """비둔각 삼각형 cotangent transmissibility와 local Voronoi area 대조."""
    weights = {}
    nv = np.zeros(len(xy))
    for k in range(3):
        i, j, o = triangles[:, k], triangles[:, (k + 1) % 3], triangles[:, (k + 2) % 3]
        u, v = xy[i] - xy[o], xy[j] - xy[o]
        cross = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        if np.any(cross == 0):
            raise ValueError('degenerate triangle')
        cot = np.einsum('ij,ij->i', u, v) / cross
        if np.any(cot < -1e-14):
            raise ValueError('negative geometric cotangent')
        w = cot / 2
        length2 = np.sum((xy[i] - xy[j])**2, axis=1)
        np.add.at(nv, i, w * length2 / 4)
        np.add.at(nv, j, w * length2 / 4)
        for aa, bb, ww in zip(i, j, w):
            key = (min(int(aa), int(bb)), max(int(aa), int(bb)))
            weights[key] = weights.get(key, 0.0) + float(ww)
    if set(weights) != {tuple(sorted(map(int, p))) for p in edges}:
        raise ValueError('edge topology differs from triangles')
    return np.array([weights[tuple(sorted(map(int, p)))] for p in edges]), nv


def exact_row(node, xy, triangles, incident):
    """선택 witness의 실제 저장 좌표를 Fraction으로 계산. native roundoff 복원 아님."""
    q = {i: (F(float(xy[i, 0])), F(float(xy[i, 1]))) for ti in incident[node] for i in triangles[ti].tolist()}
    row, volume = {}, F(0)
    for ti in incident[node]:
        tri = list(map(int, triangles[ti]))
        for j in tri:
            if j == node:
                continue
            o = next(i for i in tri if i != node and i != j)
            u = (q[node][0]-q[o][0], q[node][1]-q[o][1])
            v = (q[j][0]-q[o][0], q[j][1]-q[o][1])
            w = (u[0]*v[0]+u[1]*v[1]) / (2*abs(u[0]*v[1]-u[1]*v[0]))
            length2 = sum((q[node][k]-q[j][k])**2 for k in (0, 1))
            volume += w * length2 / 4
            row[j] = row.get(j, F(0)) + w
    grouped = {}
    for j, w in row.items():
        xx = q[j][0]
        grouped[xx] = grouped.get(xx, F(0)) - w / volume
    xx = q[node][0]
    grouped[xx] = grouped.get(xx, F(0)) + sum(row.values()) / volume
    return grouped


def classify(diff, scale, uncertainty, exact_nonzero):
    if not all(math.isfinite(v) and v >= 0 for v in (diff, scale, uncertainty)):
        raise ValueError('invalid diagnostic metric')
    return 'NONINVARIANCE_WITNESS' if exact_nonzero and diff > 1e-8*scale and diff > 100*(uncertainty+100*np.finfo(float).eps*scale) else 'INCONCLUSIVE'


def analyze(a):
    xy, triangles, edges = validate(a)
    w = a['EdgeCouple']/a['EdgeLength']
    gw, gv = geometry_weights(xy, triangles, edges)
    nv = a['NodeVolume']
    wr = float(np.max(np.abs(w-gw)/np.maximum(1, np.abs(gw))))
    vr = float(np.max(np.abs(nv-gv)/gv))
    if wr > 1e-10 or vr > 1e-10:
        raise ValueError('LOCAL_GEOMETRY_WEIGHT_MISMATCH')
    n = len(xy)
    operator_scale = np.zeros(n)
    for k in (0, 1):
        np.add.at(operator_scale, edges[:, k], 2*np.abs(w))
    operator_scale /= nv
    xx = xy[:, 0]/0.004
    result = np.zeros((4, n))
    raw = np.zeros_like(result)
    error = np.zeros_like(result)
    stable = np.zeros_like(result)
    incident_edges = [[] for _ in range(n)]
    incident_triangles = [[] for _ in range(n)]
    for ti, tri in enumerate(triangles):
        for node in tri:
            incident_triangles[int(node)].append(ti)
    for ei, (i, j) in enumerate(edges):
        incident_edges[int(i)].append((ei, int(j)))
        incident_edges[int(j)].append((ei, int(i)))
    for power in range(4):
        f = xx**power
        delta = f[edges[:, 0]]-f[edges[:, 1]]
        flux = w*delta
        geometric = np.zeros(n)
        for k, sign in ((0, 1), (1, -1)):
            np.add.at(raw[power], edges[:, k], sign*flux)
            np.add.at(geometric, edges[:, k], sign*gw*delta)
            np.add.at(error[power], edges[:, k], np.abs((w-gw)*delta))
        result[power] = raw[power]/nv
        error[power] = error[power]/nv + np.abs(geometric*(1/nv-1/gv))
        for node, inc in enumerate(incident_edges):
            stable[power, node] = math.fsum(float(w[ei]*(f[node]-f[j])) for ei, j in inc)/nv[node]
    groups = {}
    for node, x in enumerate(xy[:, 0]):
        groups.setdefault(float(x), []).append(node)
    xmin, xmax, ymin, ymax = xy[:,0].min(), xy[:,0].max(), xy[:,1].min(), xy[:,1].max()
    classes = np.where((xy[:,0] == xmin)|(xy[:,0] == xmax), 2, np.where((xy[:,1] == ymin)|(xy[:,1] == ymax), 1, 0))
    candidates = sorted(x for x, nodes in groups.items() if abs(x) <= 0.2e-4 and sum(classes[i] == 0 for i in nodes) >= 2)
    if not candidates:
        return {'verdict': 'NOT_MEASURED', 'weight_rel':wr, 'local_volume_rel':vr}, {'actions':result, 'raw_actions':raw, 'stable_actions':stable, 'node_class':classes}
    chosen = [candidates[i] for i in sorted(set(np.linspace(0, len(candidates)-1, min(12,len(candidates)), dtype=int).tolist()))]
    witnesses = []
    for x in chosen:
        nodes = sorted(groups[x], key=lambda i:xy[i,1])
        interior = [i for i in nodes if classes[i] == 0]
        pairs = [(interior[0], interior[len(interior)//2]), (interior[0],interior[-1]), (nodes[0],interior[0]), (interior[-1],nodes[-1])]
        exact = {i: exact_row(i, xy, triangles, incident_triangles) for pair in pairs for i in pair}
        for i, j in pairs:
            if i == j:
                continue
            differences = {key:exact[i].get(key,F(0))-exact[j].get(key,F(0)) for key in set(exact[i])|set(exact[j])}
            structural = any(v != 0 for v in differences.values())
            for power in range(4):
                diff = abs(float(stable[power,i]-stable[power,j]))
                scale = float(max(operator_scale[i], operator_scale[j]))
                uncertainty = float(error[power,i]+error[power,j])
                witnesses.append({'nodes':[i,j], 'classes':[int(classes[i]),int(classes[j])], 'x_cm':x, 'power':power,
                                  'difference':diff, 'scale':scale, 'geometry_discrepancy_bound':uncertainty,
                                  'exact_projected_row_nonzero':structural,
                                  'exact_row_difference':{str(k):str(v) for k,v in differences.items() if v != 0},
                                  'verdict':classify(diff,scale,uncertainty,structural)})
    verdict = 'NONINVARIANCE_WITNESS' if any(v['verdict']=='NONINVARIANCE_WITNESS' for v in witnesses) else 'INCONCLUSIVE'
    return {'verdict':verdict,'weight_rel':wr,'local_volume_rel':vr,'witnesses':witnesses,
            'float_vs_fsum_max':float(np.max(np.abs(result-stable))),
            'y_spread_max':[float(max(np.ptp(result[k, nodes]) for x,nodes in groups.items() if x not in (xmin,xmax))) for k in range(4)]}, {
                'actions':result,'raw_actions':raw,'stable_actions':stable,'node_class':classes}
