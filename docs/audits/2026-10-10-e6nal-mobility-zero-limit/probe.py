"""공식 식의 제거 가능한 zero singularity 후보. AUDIT ONLY; solve 없음."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = '092d7042ee87364d4e32a051a88cde090e73dc5d28f0ee20c2b060635eab586e'
CASES = {
    'PURE_N': (1e16, 0., 1e16, 1e4),
    'PURE_P': (0., 5e15, 2e4, 5e15),
    'INTRINSIC': (0., 0., 1e10, 1e10),
}
n = (9e15 + math.sqrt((9e15)**2 + 4e20))/2
CASES['BOTH_POSITIVE_CONTROL'] = (1e16, 1e15, n, 1e20/n)


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    assert hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == PLAN_SHA
    label = sys.argv[1]
    values = CASES[label]
    baseline = json.loads((ROOT/'docs/audits/2026-10-10-e6naj-official-mobility/raw/remote-run-87/outputs/e6naj_out'/(label+'.json')).read_text(encoding='utf-8'))
    import devsim as dv
    from devsim.python_packages import Klaassen as helper
    source = Path(helper.__file__).read_bytes()
    assert hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest() == baseline['helper_source_lf_sha256']
    attempts = []
    original_solve = dv.solve
    def forbidden_solve(*args, **kwargs):
        attempts.append('solve')
        raise AssertionError('SOLVE_FORBIDDEN')
    dv.solve = forbidden_solve
    row = {'case': label, 'scope': 'SYNTHETIC_MODEL_INPUT_ONLY',
           'candidate': 'AUDIT_ONLY_CONTINUOUS_EXTENSION',
           'plan_sha': PLAN_SHA, 'devsim_version': importlib.metadata.version('devsim'),
           'helper_source_sha256': hashlib.sha256(source).hexdigest(),
           'helper_source_lf_sha256': hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest(),
           'helper': 'devsim.python_packages.Klaassen', 'temperature_K': 300.,
           'models': {}, 'status': 'NOT_EVALUATED'}
    device, region = 'mobility_probe', 'Si'
    try:
        # Exactly two right triangles. Gmsh elements: type, physical index, nodes.
        dv.create_gmsh_mesh(mesh='mobility_mesh', coordinates=[0.,0.,0., 1e-4,0.,0., 1e-4,1e-4,0., 0.,1e-4,0.],
                            elements=[2,0,0,1,2, 2,0,0,2,3], physical_names=['Si'])
        dv.add_gmsh_region(mesh='mobility_mesh', gmsh_name='Si', region=region, material='Silicon')
        dv.finalize_mesh(mesh='mobility_mesh')
        dv.create_device(mesh='mobility_mesh', device=device)
        count = len(dv.get_node_model_values(device=device, region=region, name='x'))
        assert count == 4
        dv.set_parameter(device=device, region=region, name='T', value=300.)
        readback = {}
        for name, value in zip(('Donors', 'Acceptors', 'Electrons', 'Holes'), values):
            if name in {'Electrons', 'Holes'}:
                dv.node_solution(device=device, region=region, name=name)
                dv.set_node_values(device=device, region=region, name=name, values=[value]*count)
            else:
                dv.node_model(device=device, region=region, name=name, equation=repr(value))
            actual = list(dv.get_node_model_values(device=device, region=region, name=name))
            assert actual == [value]*count
            readback[name] = actual
        row['inputs'] = readback
        helper.Set_Mobility_Parameters(device, region)
        row['coefficient_species_comments'] = ['As donor', 'B acceptor']
        row['parameters'] = {name: dv.get_parameter(device=device, region=region, name=name)
             for name in ('mu_min_e', 'mu_max_e', 'mu_min_h', 'mu_max_h', 'Nref_D', 'Nref_A')}
        try:
            helper.Klaassen_Mobility(device, region)
            for name, dopant, coefficient, reference in (('Z_D', 'Donors', 'c_D', 'Nref_D'), ('Z_A', 'Acceptors', 'c_A', 'Nref_A')):
                expression = f'1+({dopant}/{reference})^2/(1+{coefficient}*({dopant}/{reference})^2)'
                dv.node_model(device=device, region=region, name=name, equation=expression)
            row['replaced_models'] = ['Z_D', 'Z_A']
            row['creation'] = 'COMPLETE'
        except Exception as exc:
            row['creation'] = 'FAILED'
            row['creation_error'] = type(exc).__name__+': '+str(exc)
        for name, edge in (('Z_D', False), ('Z_A', False), ('mu_bulk_e_Node', False),
                           ('mu_bulk_h_Node', False), ('mu_bulk_e', True), ('mu_bulk_h', True)):
            try:
                getter = dv.get_edge_model_values if edge else dv.get_node_model_values
                actual = list(getter(device=device, region=region, name=name))
                assert len(actual) == (5 if edge else 4)
                assert all(math.isfinite(x) and x > 0 for x in actual)
                row['models'][name] = {'status': 'FINITE_POSITIVE', 'values': actual}
            except Exception as exc:
                row['models'][name] = {'status': 'EVALUATION_FAILED', 'error': type(exc).__name__+': '+str(exc)}
        okay = row['creation'] == 'COMPLETE' and all(r['status'] == 'FINITE_POSITIVE' for r in row['models'].values())
        if okay:
            for carrier in ('e', 'h'):
                node = row['models']['mu_bulk_'+carrier+'_Node']['values']
                edge = row['models']['mu_bulk_'+carrier]['values']
                assert max(node)-min(node) <= 16*math.ulp(node[0])
                assert all(abs(x-node[0]) <= 16*math.ulp(node[0]) for x in edge)
        row['status'] = 'NUMERIC_EVALUABLE' if okay else 'CAPABILITY_UNAVAILABLE'
        assert okay, row
        for name, value in zip(('Z_D', 'Z_A'), values[:2]):
            if value == 0.: assert row['models'][name]['values'] == [1.]*4
        if label == 'BOTH_POSITIVE_CONTROL':
            for name in row['models']:
                old = baseline['models'][name]['values']
                actual = row['models'][name]['values']
                assert all(abs(a-b) <= 128*math.ulp(b) for a,b in zip(actual, old)), (name, actual, old)
            row['positive_baseline_equal_128ulp'] = True
    finally:
        dv.solve = original_solve
        if device in dv.get_device_list(): dv.delete_device(device=device)
        row['cleanup_devices'] = list(dv.get_device_list())
        row['solve_attempts'] = len(attempts)
        out = ROOT/'e6nal_out'
        out.mkdir(exist_ok=True)
        (out/(label+'.json')).write_text(json.dumps(row, indent=2, allow_nan=False), encoding='utf-8')
    assert row['cleanup_devices'] == [] and row['solve_attempts'] == 0
    if label == 'BOTH_POSITIVE_CONTROL': assert row['status'] == 'NUMERIC_EVALUABLE', row
    print(json.dumps({'case': label, 'status': row['status'], 'solve_attempts': 0}))


if __name__ == '__main__': main()
