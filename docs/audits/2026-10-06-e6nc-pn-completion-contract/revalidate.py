"""원본 PN 증거 재검토와 종료 계약 시험. 엔진 import/solve 없음."""
import ast
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN_SHA = '836dfbaff593b8b20ad702f0bbffa6c941770581cd67715e912f29476aa1e2e0'
BASE = ROOT / 'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency'
DATA = BASE / 'data/remote_run_36904995835/remote-run-32/outputs/e6m_out'
REF = ROOT / 'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out'
UNIT = ROOT / 'docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json'
TESTS = ('test_e6m_completion_exit_mock.py', 'test_e6m_judge_mock.py',
         'test_e6m_execution_contract_mock.py', 'test_e6l_correction_mock.py')


def no_engine(event, args):
    if event == 'import' and args[0].split('.')[0] in ('devsim', 'viennaps', 'viennals'):
        raise RuntimeError('ENGINE_IMPORT_FORBIDDEN')


def main():
    sys.addaudithook(no_engine)
    if hashlib.sha256((HERE / 'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() != PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    if '--local' not in sys.argv and (os.name != 'nt' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise ValueError('REMOTE_WINDOWS_REQUIRED')
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(BASE / 'scripts'))
    import numpy as np
    import judge_e6m as J
    import e6m_metrics as M
    preserved = (DATA / 'pn_2d_consistency.json', DATA / 'arrays.npz', REF / 'pn_1d_diagnostic.json', REF / 'states.npz',
                 BASE / 'PLAN.md', UNIT)
    hashes = lambda: {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved}
    before = hashes()
    tests = []
    for name in TESTS:
        path = ROOT / 'tests/unit' / name
        old_argv = sys.argv
        try:
            sys.argv = [str(path)]
            try:
                runpy.run_path(str(path), run_name='__main__')
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
        finally:
            sys.argv = old_argv
        tests.append({'test': name, 'status': 'PASS'})
    raw = json.loads((DATA / 'pn_2d_consistency.json').read_text(encoding='utf-8'))
    ref = json.loads((REF / 'pn_1d_diagnostic.json').read_text(encoding='utf-8'))
    unit = json.loads(UNIT.read_text(encoding='utf-8'))
    with np.load(DATA / 'arrays.npz', allow_pickle=False) as arrays, np.load(REF / 'states.npz', allow_pickle=False) as ref_arrays:
        verdicts = J.judge(raw, arrays, ref, ref_arrays, unit)
        metrics = M.compute(raw, arrays, ref, ref_arrays)
    rc = J.completion_exit_code(verdicts)
    if rc != 1 or verdicts['G2_PRODUCTION_GATE_HELD_AND_AUDIT_DOPING']['verdict'] != 'NOT_EVALUATED':
        raise AssertionError('PRESERVED_INCOMPLETE_EVIDENCE_MUST_NOT_GREEN')
    old_verdicts = {k: v['verdict'] for k, v in raw['verdicts'].items() if isinstance(v, dict) and 'verdict' in v}
    statuses = {k: v['verdict'] for k, v in verdicts.items() if isinstance(v, dict) and 'verdict' in v}
    source = ROOT / 'tests/integration/test_pn_2d_1d_consistency_real.py'
    ast.parse(source.read_text(encoding='utf-8'))
    after = hashes()
    if before != after or {'devsim', 'viennaps', 'viennals'}.intersection(sys.modules):
        raise AssertionError('RAW_CHANGED_OR_ENGINE_IMPORTED')
    cur = metrics['levels']['L2']['currents']
    diagnostics = {
        'current_density_L2_A_per_cm2': {k: v['J_2d_A_per_cm2'] for k, v in cur.items()},
        'max_kcl_relative': max(v['kcl_rel'] for L in metrics['levels'].values() for v in L['currents'].values()),
        'max_current_relative_2d_vs_1d': max(v['rel_diff'] for L in metrics['levels'].values() for v in L['currents'].values()),
        'max_y_potential_spread_V': max(p['psi_y_spread_V'] for L in metrics['levels'].values() for p in L['profiles'].values()),
        'mesh_sensitivity': metrics['mesh_sensitivity'],
        'equilibrium': metrics['equilibrium_diagnostics_not_judged'],
    }
    report = dict(status='PASS', source_sha=os.environ.get('GITHUB_SHA'), plan_sha=PLAN_SHA,
                  tests=tests, original_recorded_verdicts=old_verdicts, current_verdicts=statuses,
                  revalidated_audit_exit_code=rc, canonical_evidence=verdicts['canonical_evidence'],
                  raw_hashes=before, raw_hashes_unchanged=True, diagnostics_not_approved=diagnostics,
                  recorded_historical_solves=raw['total_solves'], engine_imports=0, new_solves=0,
                  pn_approved=False, gate_released=False)
    if '--local' not in sys.argv:
        out = ROOT / 'e6nc_out'
        out.mkdir(exist_ok=False)
        (out / 'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    # This revalidation checks that incomplete evidence is rejected, not that PN passed.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
