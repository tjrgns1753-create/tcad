"""고정 입력과 정확 좌표 계약. NumPy 외 엔진 import는 없다."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = ROOT/'docs/audits/2026-10-06-e6nd-pn-transition-pilot'
DATA = PREVIOUS/'raw_fine/outputs/e6nd_fine_out/N2'
sys.path.insert(0,str(PREVIOUS))
import pilot as P

PLAN_SHA = '631e73ffd7b004f2e0d789d20201360d6f02d5d66b7b4e68fc802d2c842c117b'
INPUT_SHA = {'arrays.npz':'eb5538684433427b6c328d4e3b334566353a16d0e391a28c24e434d54b1784e7',
             'record.json':'ef4466ff4c35f432ad0db46109a786da855a71266600e377cf3e36da1588dce5'}


def preflight(callback=None):
    sha = hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    if sha!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    for name,expected in INPUT_SHA.items():
        if hashlib.sha256((DATA/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('SOURCE_EVIDENCE_HASH_MISMATCH:'+name)
    return callback() if callback is not None else sha


def matched_indices(expected, actual):
    """근사 좌표나 보간 없이 actual node를 unique 1D 좌표에 매핑한다."""
    expected,actual = np.asarray(expected),np.asarray(actual)
    if (expected.ndim!=1 or actual.ndim!=1 or expected.dtype.kind not in 'if'
            or actual.dtype.kind not in 'if' or not len(expected)
            or not np.all(np.isfinite(expected)) or not np.all(np.isfinite(actual))
            or np.any(np.diff(expected)<=0)):
        raise ValueError('INVALID_COORDINATE_ARRAY')
    indices = np.searchsorted(expected,actual)
    if np.any(indices>=len(expected)) or not np.array_equal(expected[indices],actual):
        raise ValueError('EXACT_COORDINATE_MISMATCH')
    return indices


def unique_source_x(arrays):
    x = np.unique(arrays['fwd_x'])
    if (len(x)!=1545 or not np.array_equal(x,np.unique(arrays['rev_x']))
            or x[0]!=-.002 or x[-1]!=.002 or not np.any(x==0)):
        raise ValueError('SOURCE_GRID_CONTRACT_MISMATCH')
    return x


def save(path,obj):
    path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
